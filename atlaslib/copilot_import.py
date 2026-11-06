"""Receive a selective PC chat archive into the generated workspace mirror."""
import filecmp
import json
import os
import posixpath
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

from atlaslib.core import ATLAS_DIR, under
from atlaslib.extract import cmd_extract
from atlaslib.sources.copilot import _folder_path


ENTRY_RE = re.compile(
    r"([0-9a-f]{32}(?:-\d+)?)/(workspace\.json|chatSessions/"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.jsonl)"
)


def import_archive(archive, destination, project):
    """Validate all archive contents before replacing any mirror files."""
    destination = Path(destination)
    with zipfile.ZipFile(archive) as zf:
        names, workspaces, sessions = set(), {}, set()
        infos = zf.infolist()
        for info in infos:
            match = ENTRY_RE.fullmatch(info.filename)
            if (not match or info.filename in names
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError(f"Unexpected, duplicate, or symlink archive entry: {info.filename}")
            names.add(info.filename)
            workspace, relative = match.groups()
            if relative == "workspace.json":
                if info.file_size > 65536:
                    raise ValueError(f"Workspace metadata too large: {info.filename}")
                doc = json.loads(zf.read(info))
                cwd = _folder_path(doc.get("folder")) if isinstance(doc, dict) else None
                if not cwd:
                    raise ValueError(f"Missing workspace folder URI: {info.filename}")
                cwd = posixpath.normpath(cwd)
                roots = project["roots"] + project.get("cwd_also", [])
                if not under(cwd, roots) or under(cwd, project.get("exclude_cwd", [])):
                    raise ValueError(f"Workspace is outside the configured project selection: {cwd}")
                workspaces[workspace] = cwd
            else:
                sessions.add(workspace)
        if not sessions or not sessions <= workspaces.keys():
            raise ValueError("Archive must contain chat logs and workspace.json for every workspace.")
        for name in names:
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"Mirror path escapes its destination: {name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".copilot-import-", dir=destination.parent) as tmp:
            staging = Path(tmp)
            for info in infos:
                target = staging / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
            changed, unchanged = 0, 0
            for name in sorted(names):
                source, target = staging / name, destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file() and filecmp.cmp(source, target, shallow=False):
                    unchanged += 1
                else:
                    os.replace(source, target)
                    changed += 1
    return changed, unchanged


def cmd_import_copilot(cfg, args):
    try:
        configured = cfg["sources"].get("copilot", {}).get("chat_storage")
        expected = ATLAS_DIR / "work/copilot_import/workspaceStorage"
        if not configured or Path(configured).resolve() != expected:
            raise ValueError(f"Set sources.copilot.chat_storage to {expected} before importing.")
        if not expected.resolve().is_relative_to(ATLAS_DIR):
            raise ValueError("The Copilot mirror must stay inside ResearchAtlas.")
        changed, unchanged = import_archive(args.archive, expected, cfg["project"])
        print(f"Copilot import: {changed} files installed, {unchanged} unchanged; existing history retained.")
        if args.extract:
            return cmd_extract(cfg, SimpleNamespace(force=False))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: Copilot import failed: {exc}", file=sys.stderr)
        return 1
