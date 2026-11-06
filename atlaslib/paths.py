"""paths: aggregate per-session path hits into paths.jsonl and verify each path (timeout-guarded)."""
import json
import os
import select
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from atlaslib.core import _KIND_BY_EXT, read_jsonl, work_paths, write_jsonl

PATH_MOUNT_TIMEOUT_LIMIT = 3  # timeouts under one top-level mount before the rest of it is skipped
VERIFY_FIELDS = ("status", "is_dir", "size", "mtime", "is_symlink", "checked_at", "error")

# Runs in a child process (python -I -c). Reads one path per stdin line (bytes, filesystem
# encoding) and answers one JSON line per path. All NFS access happens here, so a hung stat
# blocks only this helper, which the parent can kill.
_PROBE_SRC = r'''
import json, os, stat, sys
for line in sys.stdin.buffer:
    path = os.fsdecode(line.rstrip(b"\n"))
    out = {"path": path}
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        out["status"] = "missing"
    except OSError as e:
        out["status"] = "unreachable"
        out["error"] = type(e).__name__ + ": " + str(e)
    else:
        out["status"] = "exists"
        out["is_dir"] = stat.S_ISDIR(st.st_mode)
        out["size"] = None if out["is_dir"] else st.st_size
        out["mtime"] = st.st_mtime
    if out["status"] != "unreachable":
        out["is_symlink"] = os.path.islink(path)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
'''


class _PathProbe:
    """One helper subprocess that stats paths on request (see verify_paths)."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-c", _PROBE_SRC],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd="/")
        self.buf = b""

    def check(self, path, timeout_s):
        """Return the helper's answer as a dict, or None on timeout.

        Raises EOFError if the helper died (or ValueError if it sent a bad line).
        """
        try:
            self.proc.stdin.write(os.fsencode(path) + b"\n")
            self.proc.stdin.flush()
        except BrokenPipeError:
            raise EOFError("helper stdin closed")
        fd = self.proc.stdout.fileno()
        deadline = time.monotonic() + timeout_s
        while b"\n" not in self.buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(fd, 65536)
            if not chunk:
                raise EOFError("helper stdout closed")
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return json.loads(line)

    def kill(self):
        """Kill without waiting long: a helper stuck in an NFS call may not die until the mount answers."""
        try:
            self.proc.kill()
        except OSError:
            pass
        for f in (self.proc.stdin, self.proc.stdout):
            try:
                f.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _paths_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _paths_ts_iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_mount(path):
    """Top-level mount: /mnt/<name> for NAS mounts, otherwise the first directory (e.g. /home)."""
    parts = path.split("/")  # ['', 'mnt', 'nas_data', ...]
    if len(parts) > 2 and parts[1] == "mnt":
        return "/".join(parts[:3])
    return "/" + parts[1] if len(parts) > 1 else "/"


def _path_result(raw):
    """Turn one helper answer (or a synthetic one) into the stored verification fields."""
    mtime = raw.get("mtime")
    return {
        "status": raw["status"],
        "is_dir": raw.get("is_dir"),
        "size": raw.get("size"),
        "mtime": _paths_ts_iso(mtime) if mtime is not None else None,
        "is_symlink": raw.get("is_symlink"),
        "checked_at": _paths_now_iso(),
        "error": raw.get("error"),
    }


def verify_paths(paths, timeout_s):
    """Stat each path in a helper subprocess, with a per-path timeout.

    Returns {path: {status, is_dir, size, mtime, is_symlink, checked_at, error}}.
    status is exists | missing | unreachable. A PermissionError (or any other OSError other
    than not-found) is recorded as unreachable with an error string, because the path could
    not be verified. A timed-out path is unreachable; after PATH_MOUNT_TIMEOUT_LIMIT timeouts
    under one top-level mount, the remaining paths there are marked unreachable unchecked.
    Independent of the pathhits format, so `refresh` can reuse it.
    """
    results = {}
    timeouts = {}  # top-level mount -> number of timed-out paths
    probe = None
    try:
        for path in paths:
            if path in results:
                continue
            mount = _path_mount(path)
            if timeouts.get(mount, 0) >= PATH_MOUNT_TIMEOUT_LIMIT:
                results[path] = _path_result({
                    "status": "unreachable",
                    "error": f"skipped: {mount} timed out {PATH_MOUNT_TIMEOUT_LIMIT} times"})
                continue
            if "\n" in path or "\r" in path:
                results[path] = _path_result({"status": "unreachable", "error": "path has a newline"})
                continue
            if probe is None:
                probe = _PathProbe()
            try:
                raw = probe.check(path, timeout_s)
            except (EOFError, ValueError) as e:
                probe.kill()
                probe = None
                raw = {"status": "unreachable", "error": f"verify helper failed: {e}"}
            else:
                if raw is None:
                    probe.kill()
                    probe = None
                    timeouts[mount] = timeouts.get(mount, 0) + 1
                    raw = {"status": "unreachable", "error": f"timeout after {timeout_s}s"}
            results[path] = _path_result(raw)
    finally:
        if probe is not None:
            probe.kill()
    return results


def _load_pathhits(pathhits_dir):
    """Read per-session path hits written by `extract` (D17). Malformed files are skipped."""
    sessions = []
    if not Path(pathhits_dir).is_dir():
        return sessions
    for fp in sorted(Path(pathhits_dir).glob("*.json")):
        try:
            with open(fp, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, json.JSONDecodeError):
            print(f"warning: unreadable pathhits file {fp}", file=sys.stderr)
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("hits"), dict) or "source" not in rec or "short_id" not in rec:
            print(f"warning: malformed pathhits file {fp}", file=sys.stderr)
            continue
        sessions.append(rec)
    return sessions


def _path_root(path, roots):
    """Longest configured root that is a path-component prefix of path, else '(none)'."""
    best = None
    for root in roots:
        root = root.rstrip("/")
        if (path == root or path.startswith(root + "/")) and (best is None or len(root) > len(best)):
            best = root
    return best or "(none)"


def _path_kind(path, is_dir):
    ext = os.path.splitext(path)[1].lower()
    if ext in _KIND_BY_EXT:
        return _KIND_BY_EXT[ext]
    return "dir" if is_dir else "other"


def _paths_aggregate(sessions, roots, max_ids):
    """Fold per-session hits into one record per path. Verification fields are added later."""
    seen = {}  # path -> {"sessions": {"<source>:<short_id>": (start, end)}, "n_mentions": int}
    for s in sessions:
        sid = f"{s['source']}:{s['short_id']}"
        for raw_path, count in s["hits"].items():
            path = os.path.normpath(raw_path)
            # Drop harvest artifacts that normalize outside every root ("../", truncation "…").
            if not path.startswith("/") or _path_root(path, roots) == "(none)" or "…" in path:
                continue
            rec = seen.setdefault(path, {"sessions": {}, "n_mentions": 0})
            rec["sessions"][sid] = (s.get("start"), s.get("end"))
            rec["n_mentions"] += int(count)
    rows = []
    for path, rec in seen.items():
        ss = rec["sessions"]
        starts = [a for a, _ in ss.values() if a]
        ends = [b for _, b in ss.values() if b]
        newest_first = sorted(ss, key=lambda k: (ss[k][0] or "", k), reverse=True)
        rows.append({
            "path": path,
            "root": _path_root(path, roots),
            "first_seen": min(starts) if starts else None,
            "last_seen": max(ends) if ends else None,
            "n_sessions": len(ss),
            "n_mentions": rec["n_mentions"],
            "session_ids": newest_first[:max_ids],
        })
    return rows


def _print_counts(title, counter):
    print(f"{title}:")
    for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:6d}  {key}")


def _print_paths_summary(rows, n_sessions, verify_s):
    print(f"sessions read: {n_sessions}")
    print(f"unique paths: {len(rows)}")
    if verify_s is None:
        print("verification: skipped (--no-verify); previous status kept")
    else:
        print(f"verification: {verify_s:.1f}s")
    _print_counts("counts by status", Counter(r["status"] for r in rows))
    _print_counts("counts by root", Counter(r["root"] for r in rows))
    _print_counts("counts by kind", Counter(r["kind"] for r in rows))
    print("top 25 paths by n_sessions:")
    for r in rows[:25]:
        print(f"  {r['n_sessions']:4d} sess {r['n_mentions']:6d} mentions  "
              f"{r['status']:11s} {r['kind']:8s} {r['path']}")


def cmd_paths(cfg, args):
    wp = work_paths(cfg)
    roots = cfg["paths"]["roots"]
    sessions = _load_pathhits(wp["pathhits_dir"])
    if not sessions:
        print(f"no pathhits in {wp['pathhits_dir']}; run `extract` first", file=sys.stderr)
        return 1
    rows = _paths_aggregate(sessions, roots, cfg["paths"]["max_session_ids"])
    rows.sort(key=lambda r: (-r["n_sessions"], r["path"]))

    if args.no_verify:
        old = {}
        if wp["paths"].is_file():
            old = {r["path"]: r for r in read_jsonl(wp["paths"])}
        for r in rows:
            prev = old.get(r["path"], {})
            for field in VERIFY_FIELDS:
                r[field] = prev.get(field)
            if "status" not in prev:
                r["status"] = "unverified"
        verify_s = None
    else:
        t0 = time.monotonic()
        results = verify_paths([r["path"] for r in rows], cfg["paths"]["verify_timeout_s"])
        verify_s = time.monotonic() - t0
        for r in rows:
            r.update(results[r["path"]])

    for r in rows:
        r["kind"] = _path_kind(r["path"], r["is_dir"])
    write_jsonl(wp["paths"], rows)
    print(f"wrote {wp['paths']}")
    _print_paths_summary(rows, len(sessions), verify_s)
    return 0
