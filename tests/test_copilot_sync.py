"""Synthetic tests for the standalone PC uploader and server archive receiver."""

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlaslib import copilot_import
from atlaslib.sources import copilot
from tools import copilot_sync as sync

ROOT = "/home/user/research"
CWD = ROOT + "/demo_project"
HASH = "a" * 32
SID = "12345678-1111-2222-3333-444444444444"
URI = "vscode-remote://ssh-remote%2Bjupyter" + CWD
CHAT = (
    json.dumps(
        {
            "kind": 0,
            "v": {
                "sessionId": SID,
                "creationDate": 1780000000000,
                "requests": [
                    {
                        "message": {"text": "synthetic prompt"},
                        "timestamp": 1780000000000,
                        "response": [{"value": "Synthetic answer"}],
                    }
                ],
            },
        }
    )
    + "\n"
).encode()
PROJECT = {"roots": [CWD], "cwd_also": [ROOT], "exclude_cwd": ["/home/user/ResearchAtlas"]}


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.storage = self.tmp / "PC/workspaceStorage"
        self.destination = self.tmp / "mirror/workspaceStorage"
        self.archive = self.tmp / "upload.zip"

    def workspace(self, name=HASH, uri=URI, body=CHAT):
        folder = self.storage / name
        sessions = folder / "chatSessions"
        sessions.mkdir(parents=True)
        (folder / "workspace.json").write_text(json.dumps({"folder": uri}), encoding="utf-8")
        (sessions / (SID + ".jsonl")).write_bytes(body)
        return folder

    def bundle(self):
        sync.make_bundle(sync.collect(self.storage, [ROOT]), self.archive, self.tmp)

    def import_bundle(self):
        return copilot_import.import_archive(self.archive, self.destination, PROJECT)

    def raw_archive(self, entries):
        with zipfile.ZipFile(self.archive, "w") as zf:
            for name, value in entries:
                zf.writestr(name, value)

    def test_selects_workspace_folder_with_boundary_not_similar_prefix(self):
        self.workspace()
        self.workspace("b" * 32, URI.replace("/research/", "/researchOther/"))
        selected = sync.collect(self.storage, [ROOT])
        self.assertEqual([(ws["hash"], ws["cwd"]) for ws in selected], [(HASH, CWD)])

    def test_multiple_roots_and_percent_encoded_uris(self):
        self.workspace(uri=URI.replace("demo_project", "demo%20project"))
        self.workspace("b" * 32, "file:///some/other/project")
        selected = sync.collect(self.storage, [ROOT, "/some/other"])
        self.assertEqual([ws["cwd"] for ws in selected], [ROOT + "/demo project", "/some/other/project"])

    def test_bundle_contains_only_mapping_and_chat_logs(self):
        folder = self.workspace()
        (folder / "state.vscdb").write_bytes(b"not needed")
        edits = folder / "chatEditingSessions"
        edits.mkdir()
        (edits / "huge-snapshot").write_bytes(b"not needed")
        self.bundle()
        with zipfile.ZipFile(self.archive) as zf:
            self.assertEqual(
                sorted(zf.namelist()), [HASH + "/chatSessions/" + SID + ".jsonl", HASH + "/workspace.json"]
            )
            self.assertEqual(zf.read(HASH + "/chatSessions/" + SID + ".jsonl"), CHAT)
        self.assertFalse((self.tmp / "snapshot.jsonl").exists())

    def test_preview_does_not_copy_or_connect(self):
        self.workspace()
        before = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob("*"))
        with mock.patch.object(sync, "upload") as upload, mock.patch.object(sync, "make_bundle") as bundle:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                result = sync.main(["--storage", str(self.storage), "--root", ROOT])
        self.assertEqual(result, 0)
        self.assertIn("Preview only", out.getvalue())
        self.assertEqual(before, sorted(p.relative_to(self.tmp) for p in self.tmp.rglob("*")))
        upload.assert_not_called()
        bundle.assert_not_called()

    def test_no_matching_workspace_is_an_explicit_error(self):
        self.workspace()
        with self.assertRaisesRegex(ValueError, "No matching"):
            sync.collect(self.storage, ["/unrelated"])

    def test_missing_storage_is_an_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            sync.collect(self.storage, [ROOT])

    def test_corrupt_metadata_is_not_silently_ignored(self):
        folder = self.workspace()
        (folder / "workspace.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            sync.collect(self.storage, [ROOT])

    def test_snapshot_retries_and_fails_for_a_continuously_changing_file(self):
        source = self.workspace() / "chatSessions" / (SID + ".jsonl")
        before = SimpleNamespace(st_size=len(CHAT), st_mtime_ns=1)
        after = SimpleNamespace(st_size=len(CHAT), st_mtime_ns=2)
        with mock.patch.object(sync.os, "fstat", side_effect=[before, after] * 3):
            with self.assertRaisesRegex(RuntimeError, "kept changing"):
                sync.snapshot(source, self.tmp / "snapshot")

    def test_windows_shared_read_requests_read_write_delete_sharing(self):
        source = self.workspace() / "chatSessions" / (SID + ".jsonl")
        fd = os.open(source, os.O_RDONLY)
        kernel = mock.Mock()
        kernel.CreateFileW.return_value = 99
        msvcrt = SimpleNamespace(open_osfhandle=mock.Mock(return_value=fd))
        with (
            mock.patch.dict(sys.modules, {"msvcrt": msvcrt}),
            mock.patch.object(sync.os, "O_BINARY", 0x8000, create=True),
            mock.patch.object(sync.ctypes, "WinDLL", return_value=kernel, create=True),
        ):
            with sync.windows_shared_read(source) as stream:
                self.assertEqual(stream.read(), CHAT)
        args = kernel.CreateFileW.call_args.args
        self.assertEqual(args[1:3], (0x80000000, 7))
        self.assertEqual(args[4], 3)
        msvcrt.open_osfhandle.assert_called_once_with(99, os.O_RDONLY | 0x8000)
        kernel.CloseHandle.assert_not_called()

    def test_windows_native_handle_is_closed_if_fd_conversion_fails(self):
        kernel = mock.Mock()
        kernel.CreateFileW.return_value = 99
        msvcrt = SimpleNamespace(open_osfhandle=mock.Mock(side_effect=OSError("fd failed")))
        with (
            mock.patch.dict(sys.modules, {"msvcrt": msvcrt}),
            mock.patch.object(sync.os, "O_BINARY", 0x8000, create=True),
            mock.patch.object(sync.ctypes, "WinDLL", return_value=kernel, create=True),
        ):
            with self.assertRaisesRegex(OSError, "fd failed"):
                sync.windows_shared_read("locked.jsonl")
        kernel.CloseHandle.assert_called_once_with(99)

    def test_failed_snapshot_is_cleaned_up(self):
        self.workspace()
        with mock.patch.object(sync, "snapshot", side_effect=RuntimeError("busy")):
            with self.assertRaisesRegex(RuntimeError, "busy"):
                self.bundle()
        self.assertFalse((self.tmp / "snapshot.jsonl").exists())

    def test_import_preserves_workspace_mapping_and_content(self):
        self.workspace()
        self.bundle()
        self.assertEqual(self.import_bundle(), (2, 0))
        path = self.destination / HASH / "chatSessions" / (SID + ".jsonl")
        self.assertEqual(path.read_bytes(), CHAT)
        cands, dropped = copilot.discover({"sources": {"copilot": {"chat_storage": str(self.destination)}}})
        self.assertEqual(dropped, 0)
        self.assertEqual([(c["id"], c["cwd"], c["kind"]) for c in cands], [(SID, CWD, "chat")])

    def test_unchanged_import_preserves_mtime_and_old_history(self):
        self.workspace()
        self.bundle()
        self.import_bundle()
        session = self.destination / HASH / "chatSessions" / (SID + ".jsonl")
        old = session.with_name("87654321-1111-2222-3333-444444444444.jsonl")
        old.write_bytes(b"old retained history")
        mtime = session.stat().st_mtime_ns
        self.assertEqual(self.import_bundle(), (0, 2))
        self.assertEqual(session.stat().st_mtime_ns, mtime)
        self.assertEqual(old.read_bytes(), b"old retained history")

    def test_changed_import_replaces_complete_file(self):
        folder = self.workspace()
        self.bundle()
        self.import_bundle()
        updated = CHAT + b'{"kind":1,"k":["customTitle"],"v":"Updated"}\n'
        (folder / "chatSessions" / (SID + ".jsonl")).write_bytes(updated)
        self.bundle()
        self.assertEqual(self.import_bundle(), (1, 1))
        self.assertEqual((self.destination / HASH / "chatSessions" / (SID + ".jsonl")).read_bytes(), updated)

    def test_path_traversal_is_rejected_before_any_mirror_write(self):
        self.raw_archive([(HASH + "/workspace.json", json.dumps({"folder": URI})), ("../../outside", "bad")])
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.import_bundle()
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.tmp / "outside").exists())

    def test_extra_non_conversation_files_are_rejected(self):
        self.raw_archive([(HASH + "/state.vscdb", "bad")])
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.import_bundle()

    def test_duplicate_archive_entry_is_rejected(self):
        name = HASH + "/workspace.json"
        metadata = json.dumps({"folder": URI})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.raw_archive([(name, metadata), (name, metadata)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.import_bundle()

    def test_symlink_archive_entry_is_rejected(self):
        entry = zipfile.ZipInfo(HASH + "/workspace.json")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.raw_archive([(entry, "/outside")])
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.import_bundle()

    def test_existing_destination_symlink_cannot_escape_mirror(self):
        self.workspace()
        self.bundle()
        self.destination.mkdir(parents=True)
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.destination / HASH).symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.import_bundle()
        self.assertEqual(list(outside.iterdir()), [])

    def test_missing_mapping_is_rejected(self):
        self.raw_archive([(HASH + "/chatSessions/" + SID + ".jsonl", CHAT)])
        with self.assertRaisesRegex(ValueError, "workspace.json"):
            self.import_bundle()

    def test_unrelated_workspace_is_rejected(self):
        self.raw_archive(
            [
                (HASH + "/workspace.json", json.dumps({"folder": "file:///private/project"})),
                (HASH + "/chatSessions/" + SID + ".jsonl", CHAT),
            ]
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            self.import_bundle()

    def test_excluded_workspace_is_rejected(self):
        self.workspace()
        self.bundle()
        project = dict(PROJECT, exclude_cwd=[CWD])
        with self.assertRaisesRegex(ValueError, "outside"):
            copilot_import.import_archive(self.archive, self.destination, project)

    def test_bad_crc_does_not_overwrite_existing_mirror(self):
        self.workspace()
        self.bundle()
        self.import_bundle()
        self.raw_archive(
            [
                (HASH + "/workspace.json", json.dumps({"folder": URI})),
                (HASH + "/chatSessions/" + SID + ".jsonl", b"synthetic prompt"),
            ]
        )
        data = self.archive.read_bytes().replace(b"synthetic prompt", b"corrupted prompt")
        self.archive.write_bytes(data)
        with self.assertRaises(zipfile.BadZipFile):
            self.import_bundle()
        self.assertEqual((self.destination / HASH / "chatSessions" / (SID + ".jsonl")).read_bytes(), CHAT)

    def test_transport_uses_port_2222_and_runs_import_then_cleanup(self):
        with (
            mock.patch.object(sync.shutil, "which", return_value="/mock"),
            mock.patch.object(sync.subprocess, "run") as run,
        ):
            sync.upload(self.archive, "user@192.0.2.10", 2222, "/atlas", "/opt/conda/bin/python")
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(calls[0][:5], ["ssh", "-T", "-p", "2222", "-o"])
        self.assertEqual(calls[1][:4], ["scp", "-P", "2222", "-o"])
        self.assertIn("user@192.0.2.10:/atlas/work/copilot-upload-", calls[1][-1])
        self.assertIn("import-copilot", calls[2][-1])
        self.assertTrue(calls[2][-1].endswith("--extract"))
        self.assertTrue(calls[3][-1].startswith("rm -f -- /atlas/work/copilot-upload-"))
        self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))

    def test_failed_upload_does_not_run_extraction_and_cleans_partial_archive(self):
        failure = subprocess.CalledProcessError(1, ["scp"])
        with (
            mock.patch.object(sync.shutil, "which", return_value="/mock"),
            mock.patch.object(sync.subprocess, "run", side_effect=[None, failure, None]) as run,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                sync.upload(self.archive, "user@host", 2222, "/atlas", "/python")
        self.assertEqual(run.call_count, 3)
        self.assertTrue(run.call_args.args[0][-1].startswith("rm -f"))

    def test_unsafe_host_is_rejected_before_subprocess(self):
        with mock.patch.object(sync.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                sync.upload(self.archive, "-oProxyCommand=bad", 22, "/atlas", "/python")
        run.assert_not_called()

    def test_upload_errors_return_failure_not_success(self):
        self.workspace()
        with mock.patch.object(sync, "upload", side_effect=RuntimeError("transfer failed")):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                result = sync.main(
                    [
                        "--storage",
                        str(self.storage),
                        "--root",
                        ROOT,
                        "--upload",
                        "--host",
                        "user@host",
                        "--atlas-dir",
                        "/atlas",
                    ]
                )
        self.assertEqual(result, 1)
        self.assertIn("transfer failed", err.getvalue())

    def test_cli_import_and_extract_produces_condensed_session_without_watermark(self):
        self.workspace()
        self.bundle()
        expected = self.tmp / "work/copilot_import/workspaceStorage"
        cfg = {
            "sources": {
                "copilot": {"chat_storage": str(expected)},
                "codex_sessions": str(self.tmp / "absent-codex"),
                "codex_session_index": str(self.tmp / "absent-index"),
                "claude_projects": str(self.tmp / "absent-claude"),
            },
            "project": dict(
                PROJECT,
                name="synthetic",
                work_dir=self.tmp / "work/synthetic",
                knowledge_dir=self.tmp / "knowledge",
                exclude_ids=[],
            ),
            "paths": {"roots": [ROOT]},
            "limits": {
                "user_text": 8000,
                "agent_final": 40000,
                "agent_commentary": 2000,
                "tool_input": 400,
                "subagent_result": 3000,
            },
        }
        with mock.patch.object(copilot_import, "ATLAS_DIR", self.tmp):
            with contextlib.redirect_stdout(io.StringIO()):
                code = copilot_import.cmd_import_copilot(cfg, SimpleNamespace(archive=self.archive, extract=True))
        self.assertEqual(code, 0)
        work = cfg["project"]["work_dir"]
        row = json.loads((work / "sessions.jsonl").read_text())
        self.assertEqual((row["source"], row["id"], row["cwd"]), ("copilot", SID, CWD))
        body = (work / "sessions/copilot_12345678.md").read_text()
        self.assertIn("synthetic prompt", body)
        self.assertIn("Synthetic answer", body)
        self.assertFalse((work / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
