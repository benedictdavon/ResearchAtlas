"""Unit tests for atlaslib/sources/copilot.py: the chat op-log replay, the chat and events condensers, and discovery.

Only synthetic fixtures written to temporary directories are used. Nothing under the real Copilot, workspaceStorage or
ResearchAtlas folders is read.

Run: python -m unittest discover -s tests
"""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlaslib.core import path_regex  # noqa: E402
from atlaslib.sources import copilot  # noqa: E402

RESEARCH = "/home/user/research"
ROOT_DP = RESEARCH + "/demo_project"
NAS_FILE = "/mnt/nas_data/lab/data/site/exports/rec_export_20261012_152940/files/data_0.npy"
TS_MS = int(datetime(2026, 10, 10, 10, 0, tzinfo=UTC).timestamp() * 1000)
TS = "2026-10-10T10:00:00.000Z"
TS2 = "2026-10-10T10:05:00.000Z"
LIMITS = {"user_text": 8000, "agent_final": 40000, "agent_commentary": 2000, "tool_input": 400, "subagent_result": 3000}
RX = path_regex(["/mnt/data", "/mnt/nas_data", "/mnt/tmp", "/mnt/shared", RESEARCH])
RX_PROJ = path_regex([ROOT_DP])
HEADING_RE = re.compile(r"^### (?:\d{4}-\d\d-\d\d \d\d:\d\d|----) (.+)$", re.M)


def labels(body):
    """Labels of the '### <stamp> <label>' section headings in a condensed body, in order."""
    return HEADING_RE.findall(body)


def write_lines(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(r if isinstance(r, str) else json.dumps(r))
            fh.write("\n")
    return path


def snapshot(requests=(), **extra):
    v = {
        "version": 3,
        "creationDate": TS_MS,
        "sessionId": "9b80a70e-0000-0000-0000-000000000000",
        "requests": list(requests),
    }
    v.update(extra)
    return {"kind": 0, "v": v}


def chat_request(text="hello", response=(), **extra):
    r = {
        "requestId": "request_1",
        "timestamp": TS_MS,
        "message": {"text": text},
        "response": list(response),
        "result": {},
        "variableData": {"variables": []},
    }
    r.update(extra)
    return r


def md(value):
    return {"value": value, "supportThemeIcons": False}


def tool_part(tool_id, tool_call_id=None, **extra):
    p = {"kind": "toolInvocationSerialized", "toolId": tool_id, "isComplete": True}
    if tool_call_id:
        p["toolCallId"] = tool_call_id
    p.update(extra)
    return p


def uri(path):
    return {"$mid": 1, "path": path, "scheme": "vscode-remote"}


def run_chat(tmp, records):
    """Condense a synthetic chatSessions op log. Returns (state, body text, path of the log)."""
    log = write_lines(Path(tmp) / "chat" / "s.jsonl", records)
    body = Path(tmp) / "body.md"
    st = copilot.chat_condense(log, RX, RX_PROJ, LIMITS, body)
    return st, body.read_text(encoding="utf-8")


def run_events(tmp, records):
    """Condense a synthetic events.jsonl. Returns (state, body text)."""
    log = write_lines(Path(tmp) / "agent" / "s" / "events.jsonl", records)
    body = Path(tmp) / "body.md"
    st = copilot.events_condense(log, RX, RX_PROJ, LIMITS, body)
    return st, body.read_text(encoding="utf-8")


def ev(typ, data, ts=TS, **extra):
    r = {"type": typ, "data": data, "id": f"id-{typ}-{id(data)}", "timestamp": ts, "parentId": None}
    r.update(extra)
    return r


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# chat op-log replay
# ---------------------------------------------------------------------------


class ReplayTests(TempCase):
    def replay(self, records):
        return copilot.replay_oplog(write_lines(self.tmp / "s.jsonl", records))

    def test_snapshot_then_set_changes_the_value(self):
        state, bad = self.replay(
            [snapshot(customTitle="old"), {"kind": 1, "k": ["customTitle"], "v": "Locate demo module"}]
        )
        self.assertEqual(state["customTitle"], "Locate demo module")
        self.assertEqual(bad, 0)

    def test_append_extends_the_list(self):
        state, bad = self.replay(
            [snapshot(requests=[{"n": 1}]), {"kind": 2, "k": ["requests"], "v": [{"n": 2}, {"n": 3}]}]
        )
        self.assertEqual(state["requests"], [{"n": 1}, {"n": 2}, {"n": 3}])
        self.assertEqual(bad, 0)

    def test_truncate_at_index_then_extend(self):
        state, bad = self.replay(
            [snapshot(requests=[{"n": 1}, {"n": 2}]), {"kind": 2, "k": ["requests"], "i": 1, "v": [{"n": 9}]}]
        )
        self.assertEqual(state["requests"], [{"n": 1}, {"n": 9}])
        self.assertEqual(bad, 0)

    def test_truncate_only_op_without_v_key_clears_the_list(self):
        # Seen in real logs (9b80a70e): kind 2 on pendingRequests with i 0 and no v key clears the list.
        state, bad = self.replay(
            [snapshot(pendingRequests=[{"id": "p"}]), {"kind": 2, "k": ["pendingRequests"], "i": 0}]
        )
        self.assertEqual(state["pendingRequests"], [])
        self.assertEqual(bad, 0)

    def test_set_into_missing_parent_creates_it(self):
        state, bad = self.replay(
            [snapshot(requests=[{"n": 1}]), {"kind": 1, "k": ["requests", 1, "message"], "v": {"text": "x"}}]
        )
        self.assertIsNone(state["requests"][0].get("message"))
        self.assertEqual(state["requests"][1], {"message": {"text": "x"}})
        self.assertEqual(bad, 0)

    def test_set_past_end_of_list_pads_with_none(self):
        state, bad = self.replay([snapshot(requests=[]), {"kind": 1, "k": ["requests", 2, "timestamp"], "v": 5}])
        self.assertEqual(state["requests"], [None, None, {"timestamp": 5}])
        self.assertEqual(bad, 0)

    def test_stub_without_snapshot_gives_no_state_and_counts_the_op(self):
        # Same shape as a031df31 (58 bytes): one set op, no kind 0 snapshot.
        state, bad = self.replay([{"kind": 1, "k": ["responderUsername"], "v": "GitHub Copilot"}])
        self.assertIsNone(state)
        self.assertEqual(bad, 1)

    def test_ops_before_snapshot_are_counted_and_later_snapshot_applies(self):
        state, bad = self.replay([{"kind": 1, "k": ["customTitle"], "v": "early"}, snapshot(customTitle="late")])
        self.assertEqual(state["customTitle"], "late")
        self.assertEqual(bad, 1)

    def test_list_op_on_a_non_list_is_counted_and_skipped(self):
        state, bad = self.replay([snapshot(customTitle="t"), {"kind": 2, "k": ["customTitle"], "v": ["x"]}])
        self.assertEqual(state["customTitle"], "t")
        self.assertEqual(bad, 1)

    def test_partial_last_line_is_counted_as_bad(self):
        state, bad = self.replay([snapshot(customTitle="t"), '{"kind": 1, "k": ["cust'])
        self.assertEqual(state["customTitle"], "t")
        self.assertEqual(bad, 1)


# ---------------------------------------------------------------------------
# chat condensing (chatSessions)
# ---------------------------------------------------------------------------


class ChatUserTests(TempCase):
    def test_system_initiated_request_has_no_user_heading_but_its_paths_are_harvested(self):
        req = chat_request(
            text=f"[Terminal 1 notification: command completed.] Output: {NAS_FILE}",
            response=[md("Checked the output.")],
            isSystemInitiated=True,
        )
        st, body = run_chat(self.tmp, [snapshot([req])])
        self.assertNotIn("USER", labels(body))
        self.assertIn("Checked the output.", body)
        self.assertNotIn("Terminal 1 notification", body)
        self.assertIn(NAS_FILE, st["hits"])

    def test_hidden_from_transcript_request_is_treated_like_system_initiated(self):
        req = chat_request(text="internal note", response=[md("ok")], hiddenFromTranscript=True)
        st, body = run_chat(self.tmp, [snapshot([req])])
        self.assertEqual(labels(body), ["AGENT (final)"])

    def test_user_message_heading_and_empty_user_text_is_skipped(self):
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="  "), chat_request(text="Hi there")])])
        self.assertEqual(labels(body), ["USER"])
        self.assertIn("Hi there", body)
        self.assertEqual(st["n_user"], 1)

    def test_attached_files_are_listed_and_implicit_editor_is_not(self):
        vd = {
            "variables": [
                {"kind": "file", "id": "vscode.implicit.viewport", "value": {"uri": uri(ROOT_DP + "/open.py")}},
                {"kind": "file", "value": {"uri": uri(ROOT_DP + "/attached.ipynb")}},
                {
                    "kind": "promptFile",
                    "id": "vscode.instructions.file.root__x",
                    "value": {"uri": uri(ROOT_DP + "/.github/copilot-instructions.md")},
                },
            ]
        }
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="Look at this", variableData=vd)])])
        self.assertIn("Look at this\n\n[attached: " + ROOT_DP + "/attached.ipynb]", body)
        self.assertNotIn("open.py", body)

    def test_custom_title_and_session_timestamps_are_read(self):
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x")], customTitle="Copilot title")])
        self.assertEqual(st["title"], "Copilot title")
        self.assertEqual(st["start"], datetime(2026, 10, 10, 10, 0, tzinfo=UTC))
        self.assertIn("### 2026-10-10 10:00 USER", body)


class ChatResponseTests(TempCase):
    def test_text_runs_are_agent_and_only_the_last_one_is_final(self):
        resp = [
            md("I'll look first."),
            tool_part(
                "copilot_readFile",
                None,
                invocationMessage={"value": "Reading", "uris": {}},
                pastTenseMessage={"value": "Read", "uris": {"file://" + ROOT_DP + "/a.py": {}}},
            ),
            md("Found it."),
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="go", response=resp)])])
        self.assertEqual(labels(body), ["USER", "AGENT", "AGENT (final)"])
        self.assertIn("- Read " + ROOT_DP + "/a.py", body)
        self.assertIn("Found it.", body)

    def test_one_text_run_split_by_a_tool_part_is_still_two_runs(self):
        resp = [
            md("A"),
            tool_part("run_in_terminal", toolSpecificData={"kind": "terminal", "commandLine": {"original": "ls"}}),
            md("B"),
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertEqual(labels(body), ["USER", "AGENT", "AGENT (final)"])

    def test_thinking_is_dropped_completely(self):
        resp = [
            {"kind": "thinking", "value": "SECRET-REASONING " + ROOT_DP + "/hidden.py", "id": "t1"},
            md("Visible answer."),
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertNotIn("SECRET-REASONING", body)
        self.assertNotIn("hidden.py", str(st["hits"]))
        self.assertIn("Visible answer.", body)

    def test_terminal_command_bullet_uses_command_line_original(self):
        part = tool_part(
            "run_in_terminal",
            toolCallId="call_1",
            toolSpecificData={"kind": "terminal", "commandLine": {"original": "git status  --short"}},
        )
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=[part])])])
        self.assertIn("- `$ git status --short`", body)

    def test_read_and_edit_bullets_come_from_uris_when_no_args_are_known(self):
        resp = [
            tool_part(
                "copilot_readFile",
                None,
                pastTenseMessage={"value": "Read", "uris": {"file://" + ROOT_DP + "/read_me.py": {}}},
            ),
            tool_part(
                "copilot_replaceString",
                None,
                pastTenseMessage={"value": "Edited", "uris": {"file://" + ROOT_DP + "/edit_me.py": {}}},
            ),
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertIn("- Read " + ROOT_DP + "/read_me.py", body)
        self.assertIn("- Edit " + ROOT_DP + "/edit_me.py", body)

    def test_arguments_from_tool_call_rounds_match_despite_vscode_suffix(self):
        rounds = [
            {
                "toolCalls": [
                    {
                        "id": "toolu_abc__vscode-1777",
                        "name": "read_file",
                        "arguments": json.dumps({"filePath": ROOT_DP + "/args_path.py"}),
                    }
                ]
            }
        ]
        resp = [tool_part("copilot_readFile", "toolu_abc")]
        req = chat_request(text="x", response=resp, result={"metadata": {"toolCallRounds": rounds}})
        st, body = run_chat(self.tmp, [snapshot([req])])
        self.assertIn("- Read " + ROOT_DP + "/args_path.py", body)

    def test_write_and_search_bullets_from_round_arguments(self):
        rounds = [
            {
                "toolCalls": [
                    {
                        "id": "c1__vscode-1",
                        "name": "create_file",
                        "arguments": json.dumps({"filePath": ROOT_DP + "/new.py"}),
                    },
                    {"id": "c2__vscode-1", "name": "grep_search", "arguments": json.dumps({"query": "csi_G5|csi_G6"})},
                ]
            }
        ]
        resp = [tool_part("copilot_createFile", "c1"), tool_part("copilot_findTextInFiles", "c2")]
        req = chat_request(text="x", response=resp, result={"metadata": {"toolCallRounds": rounds}})
        st, body = run_chat(self.tmp, [snapshot([req])])
        self.assertIn("- Write " + ROOT_DP + "/new.py", body)
        self.assertIn("- Search csi_G5|csi_G6", body)

    def test_inline_reference_is_rendered_as_its_path_inside_the_text(self):
        resp = [
            md("See "),
            {
                "kind": "inlineReference",
                "name": "notes.md",
                "inlineReference": {"$mid": 1, "path": ROOT_DP + "/notes.md", "scheme": "file"},
            },
            md(" for details."),
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertIn("See " + ROOT_DP + "/notes.md for details.", body)

    def test_symbol_inline_reference_is_its_name_and_its_location_is_only_harvested(self):
        # A symbol ({name, kind, location}) often points into a library; its path must not replace the name in prose.
        lib = "/usr/lib/python3.8/json/__init__.py"
        resp = [
            md("Use "),
            {
                "kind": "inlineReference",
                "inlineReference": {"name": "json.load", "kind": 12, "location": {"uri": uri(lib), "range": {}}},
            },
            md(" or "),
            {
                "kind": "inlineReference",
                "inlineReference": {
                    "name": "test_model()",
                    "kind": 12,
                    "location": {"uri": uri(ROOT_DP + "/lib/f.py"), "range": {}},
                },
            },
            md("."),
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertIn("Use json.load or test_model().", body)
        self.assertNotIn(lib, body)
        self.assertIn(ROOT_DP + "/lib/f.py", st["hits"])

    def test_markdown_escaped_tool_message_paths_are_harvested_whole(self):
        # Tool messages escape '_' ("demo\_project"); the scan must not stop at the backslash.
        resp = [
            tool_part(
                "run_in_terminal",
                None,
                invocationMessage={"value": "Running ` cd " + RESEARCH + "/demo\\_project/dataPlan/test\\_case && ls`"},
            )
        ]
        st, _ = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertIn(ROOT_DP + "/dataPlan/test_case", st["hits"])
        self.assertNotIn(RESEARCH + "/demo", st["hits"])

    def test_text_edit_group_is_an_edit_bullet_and_is_not_repeated(self):
        resp = [
            tool_part("copilot_applyPatch", None, pastTenseMessage={"value": "Edited", "uris": {}}),
            {"kind": "textEditGroup", "uri": uri(ROOT_DP + "/patched.py"), "edits": []},
            {"kind": "textEditGroup", "uri": uri(ROOT_DP + "/patched.py"), "edits": []},
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertEqual(body.count("- Edit " + ROOT_DP + "/patched.py"), 1)

    def test_subagent_internal_tool_parts_produce_no_bullets_only_paths(self):
        resp = [
            tool_part(
                "copilot_readFile",
                None,
                subAgentInvocationId="call_sub",
                pastTenseMessage={"value": "Read", "uris": {"file://" + NAS_FILE: {}}},
            )
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertNotIn("- Read", body)
        self.assertIn(NAS_FILE, st["hits"])

    def test_unknown_tool_is_named_by_its_tool_id(self):
        resp = [tool_part("copilot_viewImage", None)]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertIn("- tool: copilot_viewImage", body)

    def test_silent_tools_have_no_bullet(self):
        resp = [
            tool_part("manage_todo_list", None),
            tool_part("copilot_memory", None),
            tool_part("tool_search", None),
            md("done"),
        ]
        st, body = run_chat(self.tmp, [snapshot([chat_request(text="x", response=resp)])])
        self.assertNotIn("- ", body)
        self.assertNotIn("tool:", body)


class ChatSubagentTests(TempCase):
    def test_subagent_bullet_and_report_from_tool_results_text_leaves(self):
        rounds = [
            {
                "toolCalls": [
                    {
                        "id": "call_s__vscode-1",
                        "name": "runSubagent",
                        "arguments": json.dumps({"description": "Survey data", "prompt": "Find the CSV files"}),
                    }
                ]
            }
        ]
        results = {
            "call_s__vscode-1": {"$mid": 20, "content": [{"$mid": 21, "value": "REPORT: 3 CSV files in " + NAS_FILE}]}
        }
        resp = [tool_part("runSubagent", "call_s")]
        req = chat_request(
            text="go", response=resp, result={"metadata": {"toolCallRounds": rounds, "toolCallResults": results}}
        )
        st, body = run_chat(self.tmp, [snapshot([req])])
        self.assertIn("- Agent: Survey data — Find the CSV files", body)
        self.assertIn("### 2026-10-10 10:00 SUBAGENT REPORT\nREPORT: 3 CSV files in " + NAS_FILE, body)
        self.assertIn(NAS_FILE, st["hits"])

    def test_tool_result_of_an_ordinary_tool_is_harvested_but_not_written(self):
        secret = "/mnt/nas_data/tool_output_only/huge_dump.npy"
        rounds = [
            {
                "toolCalls": [
                    {"id": "c_t__vscode-1", "name": "run_in_terminal", "arguments": json.dumps({"command": "ls"})}
                ]
            }
        ]
        results = {"c_t__vscode-1": {"content": [{"value": "listing: " + secret}]}}
        resp = [tool_part("run_in_terminal", "c_t")]
        req = chat_request(
            text="x", response=resp, result={"metadata": {"toolCallRounds": rounds, "toolCallResults": results}}
        )
        st, body = run_chat(self.tmp, [snapshot([req])])
        self.assertIn(secret, st["hits"])
        self.assertNotIn(secret, body)
        self.assertNotIn("SUBAGENT REPORT", labels(body))


# ---------------------------------------------------------------------------
# events condensing (agent events.jsonl and VS Code server transcripts)
# ---------------------------------------------------------------------------


class EventsMainTests(TempCase):
    def test_session_start_gives_cwd_and_cli(self):
        st, body = run_events(
            self.tmp,
            [
                ev(
                    "session.start",
                    {
                        "sessionId": "s",
                        "producer": "copilot-agent",
                        "copilotVersion": "1.0.103",
                        "context": {"cwd": ROOT_DP},
                    },
                )
            ],
        )
        self.assertEqual(st["cwd"], ROOT_DP)
        self.assertEqual(st["cli"], "copilot-agent 1.0.103")

    def test_user_text_is_content_not_transformed_content(self):
        st, body = run_events(
            self.tmp,
            [
                ev(
                    "user.message",
                    {
                        "content": "please check the data",
                        "transformedContent": "<ide_selection> INJECTED " + ROOT_DP + "/x.py",
                        "attachments": [],
                    },
                )
            ],
        )
        self.assertEqual(labels(body), ["USER"])
        self.assertIn("please check the data", body)
        self.assertNotIn("INJECTED", body)
        self.assertNotIn("x.py", str(st["hits"]))

    def test_user_attachment_paths_are_harvested(self):
        st, body = run_events(
            self.tmp,
            [ev("user.message", {"content": "see attached", "attachments": [{"type": "file", "path": NAS_FILE}]})],
        )
        self.assertIn(NAS_FILE, st["hits"])

    def test_text_then_tool_then_final_text_per_turn(self):
        st, body = run_events(
            self.tmp,
            [
                ev("user.message", {"content": "list it", "attachments": []}, TS),
                ev("assistant.message", {"messageId": "m1", "content": "Listing now.", "toolRequests": []}, TS),
                ev(
                    "tool.execution_start",
                    {"toolCallId": "t1", "toolName": "bash", "arguments": {"command": "ls -la " + ROOT_DP}},
                    TS2,
                ),
                ev(
                    "tool.execution_complete",
                    {"toolCallId": "t1", "success": True, "result": {"content": "total 0"}},
                    TS2,
                ),
                ev("assistant.message", {"messageId": "m2", "content": "Done.", "toolRequests": []}, TS2),
            ],
        )
        self.assertEqual(labels(body), ["USER", "AGENT", "AGENT (final)"])
        self.assertIn("- `$ ls -la " + ROOT_DP + "`", body)
        self.assertNotIn("total 0", body)  # tool output is never written

    def test_tool_bullets_for_read_edit_create_search_and_patch_strings(self):
        st, body = run_events(
            self.tmp,
            [
                ev("user.message", {"content": "go", "attachments": []}),
                ev(
                    "tool.execution_start",
                    {"toolCallId": "a", "toolName": "view", "arguments": {"path": ROOT_DP + "/v.py"}},
                ),
                ev(
                    "tool.execution_start",
                    {"toolCallId": "b", "toolName": "edit", "arguments": {"path": ROOT_DP + "/e.py"}},
                ),
                ev(
                    "tool.execution_start",
                    {"toolCallId": "c", "toolName": "create", "arguments": {"path": ROOT_DP + "/c.py"}},
                ),
                ev("tool.execution_start", {"toolCallId": "d", "toolName": "rg", "arguments": {"pattern": "def foo"}}),
                ev(
                    "tool.execution_start",
                    {
                        "toolCallId": "f",
                        "toolName": "apply_patch",
                        "arguments": "*** Begin Patch\n*** Add File: " + ROOT_DP + "/p.py\n",
                    },
                ),
            ],
        )
        for line in [
            "- Read " + ROOT_DP + "/v.py",
            "- Edit " + ROOT_DP + "/e.py",
            "- Write " + ROOT_DP + "/c.py",
            "- Search def foo",
            "- Write " + ROOT_DP + "/p.py",
        ]:
            self.assertIn(line, body)

    def test_hook_permission_and_usage_records_are_dropped(self):
        st, body = run_events(
            self.tmp,
            [
                ev("user.message", {"content": "hi", "attachments": []}),
                ev("hook.start", {"hookType": "preToolUse", "input": {"path": "/mnt/nas_data/hook_path.npy"}}),
                ev("permission.requested", {"permissionRequest": {"path": "/mnt/nas_data/perm.npy"}}),
                ev("session.usage_record", {"usage": {"tokens": 5}}),
                ev("model.turn_started", {"model": "x"}),
                ev("assistant.turn_start", {"turnId": "0"}),
                ev("assistant.message", {"content": "Answer.", "toolRequests": []}),
            ],
        )
        self.assertEqual(labels(body), ["USER", "AGENT (final)"])
        self.assertNotIn("hook_path", body)
        self.assertNotIn("perm.npy", body)
        self.assertNotIn("hook_path", str(st["hits"]))

    def test_inter_agent_user_message_is_not_a_user_heading(self):
        st, body = run_events(
            self.tmp,
            [
                ev("user.message", {"content": "TASK SENT TO SUBAGENT " + NAS_FILE, "source": "agent-abc"}),
            ],
        )
        self.assertEqual(labels(body), [])
        self.assertIn(NAS_FILE, st["hits"])

    def test_ask_user_question_is_a_bullet_and_todo_is_silent(self):
        st, body = run_events(
            self.tmp,
            [
                ev("user.message", {"content": "x"}),
                ev(
                    "tool.execution_start",
                    {"toolCallId": "q", "toolName": "ask_user", "arguments": {"message": "Shall I continue?"}},
                ),
                ev(
                    "tool.execution_start",
                    {"toolCallId": "m", "toolName": "manage_todo_list", "arguments": {"todoList": []}},
                ),
            ],
        )
        self.assertIn("- ask_user: Shall I continue?", body)
        self.assertEqual(body.count("- "), 1)

    def test_compaction_summary_is_a_recap_and_failed_compaction_is_not(self):
        st, body = run_events(
            self.tmp,
            [
                ev("user.message", {"content": "x"}),
                ev(
                    "session.compaction_complete",
                    {"success": True, "summaryContent": "<overview>\nSUMMARY TEXT\n</overview>"},
                ),
                ev("session.compaction_complete", {"success": False, "summaryContent": "SHOULD NOT APPEAR"}),
            ],
        )
        self.assertEqual(labels(body), ["USER", "RECAP"])
        self.assertIn("SUMMARY TEXT", body)
        self.assertNotIn("SHOULD NOT APPEAR", body)


class EventsSubagentTests(TempCase):
    def subagent_records(self):
        # Order follows the real file: the background task returns its boilerplate early; the subagent finishes later.
        return [
            ev("user.message", {"content": "hand the work off"}),
            ev(
                "tool.execution_start",
                {
                    "toolCallId": "T1",
                    "toolName": "task",
                    "arguments": {
                        "agent_type": "worker",
                        "description": "Build notebook",
                        "prompt": "Build the notebook " + ROOT_DP,
                    },
                },
            ),
            ev("subagent.started", {"toolCallId": "T1", "agentName": "worker"}),
            ev("user.message", {"content": "Build the notebook", "source": "agent-main", "parentToolCallId": "T1"}),
            ev(
                "tool.execution_complete",
                {
                    "toolCallId": "T1",
                    "success": True,
                    "result": {"content": "Agent started in background with agent_id: x"},
                },
            ),
            ev(
                "assistant.message",
                {"content": "SUBAGENT INTERNAL " + NAS_FILE, "toolRequests": [], "parentToolCallId": "T1"},
            ),
            ev(
                "tool.execution_start",
                {
                    "toolCallId": "S1",
                    "toolName": "bash",
                    "parentToolCallId": "T1",
                    "arguments": {"command": "echo SUBCMD"},
                },
            ),
            ev(
                "tool.execution_complete",
                {"toolCallId": "S1", "parentToolCallId": "T1", "success": True, "result": {"content": "SUBCMD OUTPUT"}},
            ),
            ev("assistant.message", {"content": "SUBAGENT FINAL REPORT", "toolRequests": [], "parentToolCallId": "T1"}),
            ev("subagent.completed", {"toolCallId": "T1", "agentName": "worker"}),
            ev("tool.execution_start", {"toolCallId": "R1", "toolName": "read_agent", "arguments": {"agent_id": "x"}}),
            ev(
                "tool.execution_complete",
                {
                    "toolCallId": "R1",
                    "success": True,
                    "result": {"content": "Agent is idle.\n\n[Turn 0]\nPREVIEW ONLY"},
                },
            ),
            ev("assistant.message", {"content": "Main agent wrap-up.", "toolRequests": []}),
        ]

    def test_subagent_activity_is_not_main_agent_text_and_its_report_is_the_final_message(self):
        st, body = run_events(self.tmp, self.subagent_records())
        self.assertEqual(labels(body), ["USER", "AGENT", "SUBAGENT REPORT", "AGENT (final)"])
        self.assertIn("- Agent: Build notebook — Build the notebook " + ROOT_DP, body)
        self.assertIn("SUBAGENT FINAL REPORT", body)
        self.assertNotIn("SUBAGENT INTERNAL", body)  # its own intermediate message: paths only
        self.assertNotIn("SUBCMD", body)
        self.assertNotIn("SUBCMD OUTPUT", body)
        self.assertIn(NAS_FILE, st["hits"])
        self.assertIn("Main agent wrap-up.", body.split("AGENT (final)")[1])

    def test_background_start_is_not_a_report_and_read_agent_preview_is_not_written(self):
        st, body = run_events(self.tmp, self.subagent_records())
        self.assertNotIn("Agent started in background", body)
        self.assertNotIn("PREVIEW ONLY", body)
        self.assertNotIn("read_agent", body)

    def test_foreground_subagent_result_is_the_report_and_is_not_repeated_at_completion(self):
        recs = [
            ev("user.message", {"content": "go"}),
            ev(
                "tool.execution_start",
                {
                    "toolCallId": "F1",
                    "toolName": "execution_subagent",
                    "arguments": {"description": "Quick check", "query": "is it there"},
                },
            ),
            ev("subagent.started", {"toolCallId": "F1", "agentName": "explore"}),
            ev("assistant.message", {"content": "FG SUB TEXT", "toolRequests": [], "parentToolCallId": "F1"}),
            ev(
                "tool.execution_complete",
                {"toolCallId": "F1", "success": True, "result": {"content": "FG RESULT REPORT"}},
            ),
            ev("subagent.completed", {"toolCallId": "F1", "agentName": "explore"}),
        ]
        st, body = run_events(self.tmp, recs)
        self.assertEqual(body.count("SUBAGENT REPORT"), 1)
        self.assertIn("FG RESULT REPORT", body)
        self.assertNotIn("FG SUB TEXT", body)
        self.assertIn("- Agent: Quick check — is it there", body)


# ---------------------------------------------------------------------------
# registry entry points and discovery
# ---------------------------------------------------------------------------


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


class TitleTests(TempCase):
    def test_title_per_kind(self):
        chat = {"kind": "chat", "path": self.tmp / "a.jsonl"}
        self.assertEqual(copilot.title(chat, {"title": "T"}, {}), "T")
        agent_dir = self.tmp / "s1"
        agent_dir.mkdir()
        (agent_dir / "events.jsonl").write_text("", encoding="utf-8")
        (agent_dir / "workspace.yaml").write_text(
            "id: s1\nname: 'old name'\nsummary: \"Fix the import pipeline\"\ncwd: /x\n", encoding="utf-8"
        )
        agent = {"kind": "agent", "path": agent_dir / "events.jsonl"}
        self.assertEqual(copilot.title(agent, {}, {}), "Fix the import pipeline")
        (agent_dir / "workspace.yaml").write_text("id: s1\nname: only\n", encoding="utf-8")
        self.assertIsNone(copilot.title(agent, {}, {}))
        self.assertIsNone(copilot.title({"kind": "transcript", "path": self.tmp / "t.jsonl"}, {}, {}))


class DiscoverTests(TempCase):
    def test_synced_chat_beats_larger_old_manual_copy(self):
        same = "aaaaaaaa-1111-2222-3333-444444444444"
        mirror = self.tmp / "mirror"
        folder = mirror / ("a" * 32)
        write_json(folder / "workspace.json", {"folder": "file://" + ROOT_DP})
        synced = write_lines(folder / "chatSessions" / (same + ".jsonl"), [snapshot([])])
        write_lines(self.tmp / "manual" / (same + ".jsonl"), [snapshot([])] * 10)
        cands, skipped = copilot.discover(
            {
                "sources": {
                    "copilot": {
                        "chat_storage": str(mirror),
                        "chat_dirs": [{"path": str(self.tmp / "manual"), "cwd": ROOT_DP}],
                    }
                }
            }
        )
        self.assertEqual(skipped, 1)
        self.assertEqual(cands[0]["path"], synced)
        self.assertEqual(cands[0]["cwd"], ROOT_DP)

    def test_mirror_without_workspace_metadata_is_warned_and_skipped(self):
        mirror = self.tmp / "mirror"
        write_lines(mirror / "unknown/chatSessions/s.jsonl", [snapshot([])])
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = copilot.discover({"sources": {"copilot": {"chat_storage": str(mirror)}}})
        self.assertEqual(result, ([], 0))
        self.assertIn("without workspace folder", err.getvalue())

    def test_missing_copilot_config_returns_nothing(self):
        self.assertEqual(copilot.discover({"sources": {}}), ([], 0))
        self.assertEqual(copilot.discover({}), ([], 0))

    def test_missing_directories_are_skipped_quietly(self):
        cfg = {
            "sources": {
                "copilot": {
                    "chat_dirs": [{"path": str(self.tmp / "nope")}],
                    "agent_state": str(self.tmp / "nope2"),
                    "vscode_storage": str(self.tmp / "nope3"),
                }
            }
        }
        self.assertEqual(copilot.discover(cfg), ([], 0))

    def test_chat_agent_and_transcript_candidates(self):
        chat = self.tmp / "chatSessions"
        write_lines(chat / "aaaaaaaa-1111-2222-3333-444444444444.jsonl", [snapshot([])])
        state = self.tmp / "session-state"
        write_lines(
            state / "bbbbbbbb-1111-2222-3333-444444444444" / "events.jsonl",
            [
                {
                    "type": "session.start",
                    "data": {"producer": "copilot-agent", "copilotVersion": "1.0.1", "context": {"cwd": ROOT_DP}},
                    "timestamp": TS,
                }
            ],
        )
        vs = self.tmp / "workspaceStorage"
        hd = vs / "0123456789abcdef0123456789abcdef"
        write_json(
            hd / "workspace.json", {"folder": "vscode-remote://ssh-remote%2B192.0.2.10/home/user/research/demo_project"}
        )
        write_lines(
            hd / "GitHub.copilot-chat" / "transcripts" / "cccccccc-1111-2222-3333-444444444444.jsonl",
            [
                {
                    "type": "session.start",
                    "data": {"producer": "copilot-agent", "copilotVersion": "0.67.0"},
                    "timestamp": TS,
                }
            ],
        )
        cfg = {
            "sources": {
                "copilot": {
                    "chat_dirs": [{"path": str(chat), "cwd": ROOT_DP}],
                    "agent_state": str(state),
                    "vscode_storage": str(vs),
                }
            }
        }
        cands, skipped = copilot.discover(cfg)
        self.assertEqual(skipped, 0)
        by_kind = {c["kind"]: c for c in cands}
        self.assertEqual(sorted(by_kind), ["agent", "chat", "transcript"])
        self.assertEqual(by_kind["chat"]["id"], "aaaaaaaa-1111-2222-3333-444444444444")
        self.assertEqual(by_kind["chat"]["short"], "aaaaaaaa")
        self.assertEqual(by_kind["chat"]["cwd"], ROOT_DP)
        self.assertEqual(by_kind["agent"]["id"], "bbbbbbbb-1111-2222-3333-444444444444")
        self.assertEqual(by_kind["agent"]["cwd"], ROOT_DP)
        self.assertEqual(by_kind["agent"]["meta"]["cli_version"], "copilot-agent 1.0.1")
        self.assertEqual(by_kind["transcript"]["cwd"], "/home/user/research/demo_project")
        self.assertIsNone(by_kind["transcript"]["parent_id"])
        self.assertEqual(by_kind["transcript"]["source"], "copilot")
        self.assertIsInstance(by_kind["transcript"]["path"], Path)
        for c in cands:
            self.assertGreater(c["size"], 0)

    def test_transcript_cwd_from_file_uri_and_unquoted_path(self):
        vs = self.tmp / "ws"
        hd = vs / "hash1"
        write_json(hd / "workspace.json", {"folder": "file:///home/user/my%20folder"})
        write_lines(
            hd / "GitHub.copilot-chat" / "transcripts" / "dddddddd-0000-0000-0000-000000000000.jsonl",
            [{"type": "session.start", "data": {}, "timestamp": TS}],
        )
        cands, _ = copilot.discover({"sources": {"copilot": {"vscode_storage": str(vs)}}})
        self.assertEqual(cands[0]["cwd"], "/home/user/my folder")

    def test_transcript_cwd_from_config_map_when_workspace_json_is_missing(self):
        # The server's workspaceStorage hashes have no workspace.json; "-1" copies share the hash's folder.
        vs = self.tmp / "ws"
        for hd, cid in (
            ("d72828c7", "dddddddd-0000-0000-0000-000000000001"),
            ("d72828c7-1", "dddddddd-0000-0000-0000-000000000002"),
            ("other", "dddddddd-0000-0000-0000-000000000003"),
        ):
            write_lines(
                vs / hd / "GitHub.copilot-chat" / "transcripts" / f"{cid}.jsonl",
                [{"type": "session.start", "data": {}, "timestamp": TS}],
            )
        cands, _ = copilot.discover(
            {"sources": {"copilot": {"vscode_storage": str(vs), "workspace_cwd": {"d72828c7": ROOT_DP}}}}
        )
        by_id = {c["id"][-1]: c["cwd"] for c in cands}
        self.assertEqual(by_id, {"1": ROOT_DP, "2": ROOT_DP, "3": None})

    def test_chat_session_beats_transcript_with_the_same_id(self):
        same = "eeeeeeee-0000-0000-0000-000000000000"
        chat = write_lines(self.tmp / "chat" / f"{same}.jsonl", [snapshot([])])
        vs = self.tmp / "ws"
        write_lines(
            vs / "h" / "GitHub.copilot-chat" / "transcripts" / f"{same}.jsonl",
            [{"type": "session.start", "data": {}, "timestamp": TS}] * 50,
        )
        cands, skipped = copilot.discover(
            {"sources": {"copilot": {"chat_dirs": [{"path": str(self.tmp / "chat")}], "vscode_storage": str(vs)}}}
        )
        self.assertEqual(skipped, 1)
        self.assertEqual([c["kind"] for c in cands], ["chat"])
        self.assertEqual(cands[0]["path"], chat)

    def test_agent_state_beats_transcript_with_the_same_id(self):
        same = "ffffffff-0000-0000-0000-000000000000"
        write_lines(
            self.tmp / "state" / same / "events.jsonl", [{"type": "session.start", "data": {}, "timestamp": TS}]
        )
        write_lines(
            self.tmp / "ws" / "h" / "GitHub.copilot-chat" / "transcripts" / f"{same}.jsonl",
            [{"type": "session.start", "data": {}, "timestamp": TS}] * 5,
        )
        cands, skipped = copilot.discover(
            {"sources": {"copilot": {"agent_state": str(self.tmp / "state"), "vscode_storage": str(self.tmp / "ws")}}}
        )
        self.assertEqual(skipped, 1)
        self.assertEqual([c["kind"] for c in cands], ["agent"])

    def test_largest_copy_of_a_duplicate_is_kept(self):
        same = "99999999-0000-0000-0000-000000000000"
        small = write_lines(
            self.tmp / "ws" / "d72828c7-1" / "GitHub.copilot-chat" / "transcripts" / f"{same}.jsonl",
            [{"type": "session.start", "data": {}, "timestamp": TS}],
        )
        big = write_lines(
            self.tmp / "ws" / "d72828c7" / "GitHub.copilot-chat" / "transcripts" / f"{same}.jsonl",
            [{"type": "session.start", "data": {}, "timestamp": TS}] * 20,
        )
        cands, skipped = copilot.discover({"sources": {"copilot": {"vscode_storage": str(self.tmp / "ws")}}})
        self.assertEqual(skipped, 1)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["path"], big)
        self.assertNotEqual(cands[0]["path"], small)

    def test_ids_sharing_eight_chars_use_thirteen(self):
        a = "01a1619b-8270-7000-8000-000000000001"
        b = "01a1619b-c103-7000-8000-000000000002"
        c = "02000000-0000-0000-0000-000000000003"
        write_lines(self.tmp / "chat" / f"{a}.jsonl", [snapshot([])])
        write_lines(self.tmp / "chat" / f"{b}.jsonl", [snapshot([])])
        write_lines(self.tmp / "chat" / f"{c}.jsonl", [snapshot([])])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            cands, _ = copilot.discover({"sources": {"copilot": {"chat_dirs": [{"path": str(self.tmp / "chat")}]}}})
        shorts = {c_["id"]: c_["short"] for c_ in cands}
        self.assertEqual(shorts[a], a[:13])
        self.assertEqual(shorts[b], b[:13])
        self.assertEqual(shorts[c], c[:8])
        self.assertIn("share prefix 01a1619b", err.getvalue())


class CondenseEntryPointTests(TempCase):
    def ctx(self):
        return {"rx": RX, "rx_proj": RX_PROJ, "lim": LIMITS}

    def test_condense_sets_cli_cwd_and_title_for_chat(self):
        log = write_lines(self.tmp / "chat" / "s.jsonl", [snapshot([chat_request(text="hi")], customTitle="Named")])
        cand = {"kind": "chat", "path": log, "cwd": ROOT_DP, "id": "s", "short": "s"}
        st = copilot.condense(cand, self.ctx(), self.tmp / "b.md")
        self.assertEqual((st["cli"], st["cwd"], st["title"]), ("vscode-chat", ROOT_DP, "Named"))
        self.assertEqual(st["n_user"], 1)

    def test_condense_uses_session_start_cli_for_transcripts(self):
        log = write_lines(
            self.tmp / "t" / "s.jsonl",
            [
                {
                    "type": "session.start",
                    "data": {"producer": "copilot-agent", "copilotVersion": "0.67.0"},
                    "timestamp": TS,
                },
                {"type": "user.message", "data": {"content": "hello"}, "timestamp": TS},
            ],
        )
        cand = {"kind": "transcript", "path": log, "cwd": None, "id": "s", "short": "s"}
        st = copilot.condense(cand, self.ctx(), self.tmp / "b2.md")
        self.assertEqual(st["cli"], "copilot-agent 0.67.0")
        self.assertIsNone(st["title"])
        self.assertIsNone(st["cwd"])


if __name__ == "__main__":
    unittest.main()
