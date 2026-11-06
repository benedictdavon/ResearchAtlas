"""Preview or upload selected Windows VS Code Copilot chat logs to ResearchAtlas.

Standalone Python 3.9+, stdlib only. Preview is the default; --upload enables SSH/SCP.
Only workspace folder metadata and chatSessions/*.jsonl are collected.
"""
import argparse
import ctypes
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


WORKSPACE_RE = re.compile(r"[0-9a-f]{32}(?:-\d+)?")
SESSION_RE = re.compile(r"[0-9a-fA-F-]{36}\.jsonl")


def shared_read(path):
    """Windows editors may require FILE_SHARE_READ | WRITE | DELETE."""
    if os.name != "nt":
        return open(path, "rb")
    return windows_shared_read(path)


def windows_shared_read(path):
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 7, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        close(handle)
        raise
    return os.fdopen(fd, "rb")


def collect(storage, roots):
    if not storage.is_dir():
        raise ValueError(f"workspaceStorage directory not found: {storage}")
    workspaces = []
    for folder in sorted(storage.iterdir()):
        if not folder.is_dir() or not WORKSPACE_RE.fullmatch(folder.name):
            continue
        metadata = folder / "workspace.json"
        if not metadata.is_file():
            continue
        with shared_read(metadata) as fh:
            doc = json.load(fh)
        uri = doc.get("folder") if isinstance(doc, dict) else None
        if not isinstance(uri, str):
            print(f"warning: skipping workspace without a single folder: {metadata}", file=sys.stderr)
            continue
        cwd = posixpath.normpath(unquote(urlsplit(uri).path))
        if not any(cwd == root or cwd.startswith(root.rstrip("/") + "/") for root in roots):
            continue
        sessions = []
        for path in sorted((folder / "chatSessions").glob("*.jsonl")):
            if not path.is_file() or path.is_symlink() or not SESSION_RE.fullmatch(path.name):
                raise ValueError(f"Unexpected chat log path: {path}")
            uuid.UUID(path.stem)
            sessions.append(path)
        if sessions:
            workspaces.append({"hash": folder.name, "uri": uri, "cwd": cwd, "sessions": sessions})
    if not workspaces:
        raise ValueError("No matching chatSessions/*.jsonl files; check --storage and --root.")
    return workspaces


def snapshot(source, target):
    for _ in range(3):
        with shared_read(source) as src, open(target, "wb") as dst:
            before = os.fstat(src.fileno())
            remaining = before.st_size
            while remaining:
                data = src.read(min(1024 * 1024, remaining))
                if not data:
                    break
                dst.write(data)
                remaining -= len(data)
            after = os.fstat(src.fileno())
        if not remaining and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return
    raise RuntimeError(f"Chat log kept changing during copying; retry when the session is idle: {source}")


def make_bundle(workspaces, archive, scratch):
    copy = scratch / "snapshot.jsonl"
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for ws in workspaces:
                zf.writestr(ws["hash"] + "/workspace.json", json.dumps({"folder": ws["uri"]}))
                for path in ws["sessions"]:
                    print(f"Copying {ws['hash']}/{path.name}", flush=True)
                    snapshot(path, copy)
                    zf.write(copy, ws["hash"] + "/chatSessions/" + path.name)
    finally:
        copy.unlink(missing_ok=True)


def upload(archive, host, port, atlas_dir, remote_python):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_.-]+)?", host) or host.startswith("-"):
        raise ValueError("--host must be an SSH alias or user@hostname (not a command).")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", atlas_dir) or ".." in atlas_dir.split("/"):
        raise ValueError("--atlas-dir must be an absolute POSIX path without spaces or '..'.")
    if not remote_python.startswith("/") or "\n" in remote_python:
        raise ValueError("--remote-python must be an absolute server-side executable path.")
    for command in ("ssh", "scp"):
        if not shutil.which(command):
            raise RuntimeError(f"{command} is not available on PATH.")
    remote = atlas_dir.rstrip("/") + "/work/copilot-upload-" + uuid.uuid4().hex + ".zip"
    ssh = ["ssh", "-T", "-p", str(port), "-o", "ConnectTimeout=10", host]
    subprocess.run(ssh + [shlex.join(["mkdir", "-p", atlas_dir + "/work"])], check=True)
    try:
        subprocess.run(["scp", "-P", str(port), "-o", "ConnectTimeout=10",
                        str(archive), host + ":" + remote], check=True)
        command = [remote_python, atlas_dir + "/atlas.py", "import-copilot", remote, "--extract"]
        subprocess.run(ssh + [shlex.join(command)], check=True)
    finally:
        try:
            subprocess.run(ssh + [shlex.join(["rm", "-f", "--", remote])], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"warning: could not clean up remote temporary archive {remote}: {exc}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    appdata = os.environ.get("APPDATA")
    default_storage = Path(appdata) / "Code/User/workspaceStorage" if appdata else None
    parser.add_argument("--storage", type=Path, default=default_storage,
                        help="workspaceStorage path; defaults to %%APPDATA%%/Code/User/workspaceStorage")
    parser.add_argument("--root", action="append", required=True,
                        help="remote research folder prefix to include; repeat for additional roots")
    parser.add_argument("--upload", action="store_true", help="upload and extract; otherwise preview only")
    parser.add_argument("--host", help="SSH alias or user@hostname")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--atlas-dir", help="absolute ResearchAtlas path on the server (required with --upload)")
    parser.add_argument("--remote-python", default="/opt/conda/bin/python")
    args = parser.parse_args(argv)
    if args.storage is None:
        parser.error("--storage is required when APPDATA is not set")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    roots = [posixpath.normpath(root) for root in args.root]
    if any(not root.startswith("/") or root == "/" for root in roots):
        parser.error("--root must be a specific absolute remote folder, not '/'")
    if args.upload and not args.host:
        parser.error("--host is required with --upload")
    if args.upload and not args.atlas_dir:
        parser.error("--atlas-dir is required with --upload")
    try:
        workspaces = collect(args.storage, roots)
        total, size = 0, 0
        for ws in workspaces:
            n = len(ws["sessions"])
            total += n
            size += sum(path.stat().st_size for path in ws["sessions"])
            print(f"{ws['hash']}: {ws['cwd']} ({n} logs)", flush=True)
        print(f"Selected {total} logs, {size / 1048576:.1f} MiB uncompressed.", flush=True)
        if not args.upload:
            print("Preview only: nothing copied, uploaded, or changed.")
            return 0
        with tempfile.TemporaryDirectory(prefix="copilot-sync-") as tmp:
            scratch = Path(tmp)
            archive = scratch / "conversations.zip"
            make_bundle(workspaces, archive, scratch)
            print(f"Uploading {archive.stat().st_size / 1048576:.1f} MiB...", flush=True)
            upload(archive, args.host, args.port, args.atlas_dir, args.remote_python)
        print("Upload and extraction complete. Curated knowledge and refresh watermark were not updated.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
