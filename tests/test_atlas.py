"""Regression tests for atlas.py: the documented parsing, selection, path and citation rules.

The spec is docs/02_transcript_formats.md ("Transcript parsing rules", "Extraction and path facts"),
docs/03_decisions.md (D15-D20) and docs/04_mvp_spec.md (sections 1-5). Tests describe those rules.
They don't snapshot what atlas.py happens to do.

Only synthetic transcripts in temporary directories are used. Nothing under ~/.codex, ~/.claude,
/mnt, work/ or the real knowledge files is read.

Run: cd /home/user/ResearchAtlas && /opt/conda/bin/python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from atlaslib.cli import main  # noqa: E402
from atlaslib.core import clean_path, load_config, parse_ts, path_regex, scan_paths, under, work_paths  # noqa: E402
from atlaslib.extract import discover_candidates, select_candidates  # noqa: E402
from atlaslib.refresh import atlas_feedback, cited_paths, expand_cited  # noqa: E402
from atlaslib.review import condensed_digest, load_ledger, parse_report, pending_sessions, session_key  # noqa: E402
from atlaslib.sources.claude import claude_condense  # noqa: E402
from atlaslib.sources.codex import codex_class, codex_condense, codex_user_part  # noqa: E402

TS = "2026-10-10T10:00:00.000Z"
TS2 = "2026-10-10T10:05:00.000Z"
RESEARCH = "/home/user/research"
ROOT_DP = RESEARCH + "/demo_project"
ROOT_MB = RESEARCH + "/model_bank"
ATLAS_CWD = "/home/user/ResearchAtlas"
OTHER_CWD = "/home/user/other_project"
PATH_ROOTS = ["/mnt/data", "/mnt/nas_data", "/mnt/tmp", "/mnt/shared", RESEARCH]
NAS_RECORDING = (
    "/mnt/nas_data/lab/data/site/exports/rec_export_20261012_152940/files/2026-10-10 17:45:04/002/00/1/2/data_0.npy"
)
NAS_RECORDING_HHMMSS = (
    "/mnt/nas_data/lab/data/site/exports/rec_export_20261012_152940/files/2026-10-10 17_45_04/002/00/1/2/data_0.npy"
)

# Same values as the [limits] table written by make_config(); used for direct calls.
LIMITS = {"user_text": 8000, "agent_final": 40000, "agent_commentary": 2000, "tool_input": 400, "subagent_result": 3000}

# Codex ids: 36-char UUIDs. The first 13 chars are the citation id (D15).
CX_ROOT = "01a1619b-8270-7000-8000-000000000001"
CX_CHILD = "01a1619b-c103-7000-8000-000000000002"  # shares the 8-char prefix, not the 13-char one
CX_EXCLUDED = "01a1700a-530c-7000-8000-000000000003"  # id prefix that config.toml excludes (D20)

HEADING_RE = re.compile(r"^### (?:\d{4}-\d\d-\d\d \d\d:\d\d|----) (.+)$", re.M)


def labels(body):
    """Labels of the '### <stamp> <label>' section headings in a condensed body, in order."""
    return HEADING_RE.findall(body)


def dump_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(r if isinstance(r, str) else json.dumps(r))
            fh.write("\n")


def make_config(tmp, *, roots=(ROOT_DP, ROOT_MB), cwd_also=(RESEARCH,), exclude_cwd=(ATLAS_CWD,), exclude_ids=()):
    """Write a temp config.toml (absolute work/knowledge/source paths) and load it with load_config."""
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    def s(v):
        return json.dumps(str(v))  # JSON string literals are valid TOML basic strings for these paths

    def arr(xs):
        return "[" + ", ".join(s(x) for x in xs) + "]"

    lines = (
        [
            "[sources]",
            f"codex_sessions = {s(tmp / 'codex' / 'sessions')}",
            f"codex_session_index = {s(tmp / 'codex' / 'session_index.jsonl')}",
            f"claude_projects = {s(tmp / 'claude' / 'projects')}",
            "",
            "[project]",
            'name = "demo_project"',
            f"work_dir = {s(tmp / 'work')}",
            f"knowledge_dir = {s(tmp / 'knowledge')}",
            f"roots = {arr(roots)}",
            f"cwd_also = {arr(cwd_also)}",
            f"exclude_cwd = {arr(exclude_cwd)}",
            f"exclude_ids = {arr(exclude_ids)}",
            "",
            "[paths]",
            f"roots = {arr(PATH_ROOTS)}",
            "verify_timeout_s = 1",
            "max_session_ids = 20",
            "",
            "[limits]",
        ]
        + [f"{k} = {v}" for k, v in LIMITS.items()]
        + [
            "",
            "[knowledge]",
            f"abbreviations = {{ DP = {s(ROOT_DP)}, RIG = {s(ROOT_DP + '/experiment/rig')}, "
            f"EXP = {s('/mnt/nas_data/lab/data/site/exports')} }}",
            "new_path_min_sessions = 1",
            "",
        ]
    )
    path = tmp / "config.toml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return load_config(path), path


class TempAtlasCase(unittest.TestCase):
    """Each test gets its own temporary directory and a temp config (no real data)."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.cfg, self.cfg_path = make_config(self.tmp)
        self.rx = path_regex(self.cfg["paths"]["roots"])
        self.rx_proj = path_regex(self.cfg["project"]["roots"])

    def write_codex_rollout(self, records, name="rollout-2026-10-10T10-00-00-x.jsonl"):
        path = self.tmp / name
        dump_jsonl(path, records)
        return path

    def condense_codex(self, records, kind="root", parent_path=None, meta=None):
        """Run codex_condense on synthetic records. Returns (parse state, condensed body text)."""
        path = self.write_codex_rollout(records)
        meta = meta if meta is not None else records[0]["payload"]
        body = self.tmp / "codex_body.md"
        st = codex_condense(path, kind, parent_path, meta, self.rx, self.rx_proj, LIMITS, body)
        return st, body.read_text(encoding="utf-8")

    def condense_claude(self, records, subagent=False):
        """Run claude_condense on synthetic records. Returns (parse state, condensed body text)."""
        path = self.tmp / "session.jsonl"
        dump_jsonl(path, records)
        body = self.tmp / "claude_body.md"
        st = claude_condense(path, subagent, self.rx, self.rx_proj, LIMITS, body)
        return st, body.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Record builders (synthetic transcripts)
# ---------------------------------------------------------------------------


def cx_meta(cid, cwd=ROOT_DP, source="cli", **extra):
    payload = {
        "id": cid,
        "session_id": cid,
        "cwd": cwd,
        "timestamp": TS,
        "cli_version": "0.161.0",
        "base_instructions": "BASE_INSTRUCTIONS_SECRET",
        "source": source,
    }
    payload.update(extra)
    return {"timestamp": TS, "type": "session_meta", "payload": payload}


def cx_msg(role, text, phase=None, ts=TS, ordinal=None):
    part = "input_text" if role in ("user", "developer") else "output_text"
    payload = {"type": "message", "role": role, "content": [{"type": part, "text": text}]}
    if phase:
        payload["phase"] = phase
    rec = {"timestamp": ts, "type": "response_item", "payload": payload}
    if ordinal is not None:
        rec["ordinal"] = ordinal
    return rec


def cx_call(name, args, call_id="call_1"):
    return {
        "timestamp": TS,
        "type": "response_item",
        "payload": {"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": call_id},
    }


def cx_output(text, call_id="call_1"):
    return {
        "timestamp": TS,
        "type": "response_item",
        "payload": {"type": "function_call_output", "call_id": call_id, "output": text},
    }


def cx_custom(name, text, call_id="custom_1"):
    return {
        "timestamp": TS,
        "type": "response_item",
        "payload": {"type": "custom_tool_call", "name": name, "input": text, "call_id": call_id},
    }


def cl_user(text, origin="human", ts=TS, **extra):
    rec = {
        "type": "user",
        "timestamp": ts,
        "cwd": ROOT_DP,
        "version": "2.0.1",
        "message": {"role": "user", "content": text},
    }
    if origin is not None:
        rec["origin"] = {"kind": origin}
    rec.update(extra)
    return rec


def cl_block(block, mid="msg_1", idx=0, stop=None, cwd=ROOT_DP, ts=TS):
    return {
        "type": "assistant",
        "timestamp": ts,
        "cwd": cwd,
        "apiBlockIndex": idx,
        "message": {"id": mid, "role": "assistant", "stop_reason": stop, "content": [block]},
    }


def cl_text(text, mid="msg_1", idx=0, stop=None):
    return cl_block({"type": "text", "text": text}, mid=mid, idx=idx, stop=stop)


def cl_tool(name, inp, mid="msg_1", idx=0, stop=None):
    return cl_block({"type": "tool_use", "id": "toolu_1", "name": name, "input": inp}, mid=mid, idx=idx, stop=stop)


def cl_tool_result(text, tool_use_result=None):
    rec = {
        "type": "user",
        "timestamp": TS,
        "cwd": ROOT_DP,
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": text}]},
    }
    if tool_use_result is not None:
        rec["toolUseResult"] = tool_use_result
    return rec


# ---------------------------------------------------------------------------
# 1. Codex user text (codex_user_part)
# ---------------------------------------------------------------------------


class CodexUserTextTests(unittest.TestCase):
    def test_injected_parts_are_dropped(self):
        # docs/02 "Codex: what to keep", user text drop list.
        injected = [
            "# AGENTS.md instructions for /home/user\n\nsome repo rules",
            "<environment_context>\n  <cwd>/x</cwd>\n</environment_context>",
            "<turn_aborted>\nthe user interrupted\n</turn_aborted>",
            "<recommended_plugins>\nplugin list\n</recommended_plugins>",
            "<image name=[Image #1]>",
            "</image>",
        ]
        for text in injected:
            with self.subTest(prefix=text[:30]):
                self.assertIsNone(codex_user_part(text, LIMITS))

    def test_ide_context_keeps_only_text_after_my_request_marker(self):
        text = (
            "# Context from my IDE setup:\n\n## Active file: /x/y.py\nIDE_NOISE_LINE\n\n"
            "## My request for Codex:\nPlease rerun the 0920 baseline check"
        )
        self.assertEqual(codex_user_part(text, LIMITS), ("USER", "\nPlease rerun the 0920 baseline check"))

    def test_internal_context_keeps_only_objective_as_goal(self):
        text = (
            "<codex_internal_context version=2>\n<objective>Find the 0920 sensor reference</objective>\n"
            "<scratch>INTERNAL_SCRATCH</scratch>\n</codex_internal_context>"
        )
        label, body = codex_user_part(text, LIMITS)
        self.assertEqual(label, "GOAL")
        self.assertEqual(body.strip(), "Find the 0920 sensor reference")
        self.assertNotIn("INTERNAL_SCRATCH", body)

    def test_subagent_notification_is_subagent_result(self):
        text = "<subagent_notification>\nworker finished: 3 files checked\n</subagent_notification>"
        label, body = codex_user_part(text, LIMITS)
        self.assertEqual(label, "SUBAGENT RESULT")
        self.assertIn("worker finished", body)

    def test_ordinary_text_is_user(self):
        self.assertEqual(codex_user_part("What is the pilot dataset?", LIMITS), ("USER", "What is the pilot dataset?"))

    def test_question_reply_is_kept_as_user_text(self):
        # docs/02 keeps the user's answers to the agent's questions.
        text = "<send_user_message_question_reply>\nYes, use night 2\n</send_user_message_question_reply>"
        self.assertEqual(codex_user_part(text, LIMITS), ("USER", text))


# ---------------------------------------------------------------------------
# 2. Codex condense, end to end (root rollout)
# ---------------------------------------------------------------------------


def root_rollout():
    """A root session with every record kind the parser must keep or drop (docs/02 Codex lists)."""
    return [
        cx_meta(CX_ROOT, cwd=ROOT_DP),
        cx_msg("developer", "DEVELOPER_SECRET sandbox policy"),
        cx_msg("user", "# AGENTS.md instructions for /x\n\nAGENTS_SECRET repo rules"),
        cx_msg("user", "<environment_context>\n<cwd>/x</cwd>\nENV_SECRET\n</environment_context>"),
        cx_msg("user", "Find the 0920 baseline signal folder", ts=TS),
        {"timestamp": TS, "type": "turn_context", "payload": {"cwd": ROOT_DP, "model": "TURN_CONTEXT_SECRET"}},
        {
            "timestamp": TS,
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "REASONING_SECRET"}],
                "encrypted_content": "gAAAAAencrypted",
            },
        },
        cx_msg("assistant", "Listing the recording folder first.", phase="commentary", ts=TS2),
        cx_call("exec_command", {"cmd": "ls /mnt/nas_data/lab/data/site/exports", "workdir": ROOT_DP}),
        cx_output("TOOL_OUTPUT_SECRET listing\n" + NAS_RECORDING),
        {"timestamp": TS2, "type": "event_msg", "payload": {"type": "token_count", "info": "TOKEN_SECRET"}},
        cx_msg("assistant", "The 0920 folder is the 5-1 room recording.", phase="final_answer", ts=TS2),
    ]


class CodexCondenseTests(TempAtlasCase):
    def test_base_instructions_developer_and_reasoning_never_written(self):
        _, body = self.condense_codex(root_rollout())
        for secret in (
            "BASE_INSTRUCTIONS_SECRET",
            "DEVELOPER_SECRET",
            "REASONING_SECRET",
            "AGENTS_SECRET",
            "ENV_SECRET",
            "TURN_CONTEXT_SECRET",
            "TOKEN_SECRET",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, body)

    def test_user_and_final_agent_headings_are_written(self):
        _, body = self.condense_codex(root_rollout())
        self.assertEqual(labels(body), ["USER", "AGENT", "AGENT (final)"])
        self.assertIn("Find the 0920 baseline signal folder", body)
        self.assertIn("The 0920 folder is the 5-1 room recording.", body)

    def test_exec_command_is_written_as_bullet_with_workdir(self):
        _, body = self.condense_codex(root_rollout())
        self.assertIn("- `$ ls /mnt/nas_data/lab/data/site/exports` (in " + ROOT_DP + ")", body)

    def test_tool_output_text_is_not_written_but_its_path_is_a_hit(self):
        st, body = self.condense_codex(root_rollout())
        self.assertNotIn("TOOL_OUTPUT_SECRET", body)
        self.assertIn(NAS_RECORDING, st["hits"])

    def test_session_cwd_and_timestamps_are_tracked(self):
        st, _ = self.condense_codex(root_rollout())
        self.assertEqual(st["cwd"], ROOT_DP)
        self.assertEqual(st["start"], parse_ts(TS))
        self.assertEqual(st["end"], parse_ts(TS2))
        self.assertEqual(st["n_user"], 1)

    def test_commentary_is_labelled_agent_not_final(self):
        _, body = self.condense_codex(root_rollout())
        self.assertIn("### 2026-10-10 10:05 AGENT\nListing the recording folder first.", body)

    def test_partial_last_line_is_skipped(self):
        # docs/02: live files can end in a partial line; the earlier records must still be condensed.
        records = root_rollout()
        path = self.write_codex_rollout(records)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"timestamp": "2026-10-10T10:06:00.000Z", "type": "response_item", "payl')
        out = self.tmp / "partial_body.md"
        codex_condense(path, "root", None, records[0]["payload"], self.rx, self.rx_proj, LIMITS, out)
        self.assertIn("The 0920 folder is the 5-1 room recording.", out.read_text(encoding="utf-8"))

    def test_compaction_summary_is_skipped_when_already_in_an_agent_message(self):
        # docs/02: skip compacted.message if its first 200 chars already appeared in an emitted assistant message.
        summary = "Summary of the session so far: " + "x" * 220
        records = [
            cx_meta(CX_ROOT),
            cx_msg("assistant", summary, phase="final_answer"),
            {"timestamp": TS, "type": "compacted", "payload": {"message": summary}},
        ]
        _, body = self.condense_codex(records)
        self.assertEqual(labels(body), ["AGENT (final)"])

    def test_compaction_summary_is_kept_when_new(self):
        records = [
            cx_meta(CX_ROOT),
            cx_msg("user", "start"),
            {"timestamp": TS, "type": "compacted", "payload": {"message": "NEW_COMPACTION_SUMMARY text"}},
        ]
        _, body = self.condense_codex(records)
        self.assertIn("NEW_COMPACTION_SUMMARY text", body)


class CodexToolInputTests(TempAtlasCase):
    def test_exec_js_cell_yields_command_and_workdir(self):
        js = (
            'const r = await tools.exec_command({cmd: "/opt/conda/bin/python atlas.py paths", '
            'workdir: "/home/user/ResearchAtlas"});'
        )
        _, body = self.condense_codex([cx_meta(CX_ROOT), cx_custom("exec", js)])
        self.assertIn("`$ /opt/conda/bin/python atlas.py paths` (in /home/user/ResearchAtlas)", body)

    def test_apply_patch_yields_target_paths_not_patch_body(self):
        patch = (
            "*** Begin Patch\n*** Update File: " + ROOT_DP + "/tools/loader.py\n"
            "@@\n-PATCH_OLD_LINE\n+PATCH_NEW_LINE\n*** End Patch"
        )
        _, body = self.condense_codex([cx_meta(CX_ROOT), cx_custom("apply_patch", patch)])
        self.assertIn("- patch: " + ROOT_DP + "/tools/loader.py", body)
        self.assertNotIn("PATCH_OLD_LINE", body)

    def test_polling_and_wait_calls_are_dropped(self):
        records = [
            cx_meta(CX_ROOT),
            cx_call("wait_agent", {"targets": ["worker"]}, "c1"),
            cx_call("sleep", {"seconds": 5}, "c2"),
            cx_call("write_stdin", {"chars": "POLL_INPUT"}, "c3"),
        ]
        _, body = self.condense_codex(records)
        self.assertNotIn("wait_agent", body)
        self.assertNotIn("sleep", body)
        self.assertNotIn("POLL_INPUT", body)

    def test_encrypted_message_body_is_not_written_but_target_is(self):
        records = [
            cx_meta(CX_ROOT),
            cx_call("send_message", {"target": "worker-1", "message": "gAAAAABencryptedblob"}, "c1"),
        ]
        _, body = self.condense_codex(records)
        self.assertIn("send_message → worker-1", body)
        self.assertNotIn("gAAAAA", body)


# ---------------------------------------------------------------------------
# 3. Codex fork and subagent rules (docs/02: session classes)
# ---------------------------------------------------------------------------


class CodexForkTests(TempAtlasCase):
    def test_fork_with_start_ordinal_skips_records_before_start(self):
        parent_id = CX_ROOT
        meta = cx_meta(CX_CHILD, cwd=ROOT_DP, forked_from_id=parent_id, subagent_history_start_ordinal=2)
        records = [
            meta,
            cx_msg("user", "INHERITED_USER_TEXT", ordinal=0),
            cx_msg("assistant", "INHERITED_AGENT_TEXT", phase="final_answer", ordinal=1),
            cx_msg("user", "CHILD_OWN_USER_TEXT", ordinal=2),
            cx_msg("assistant", "CHILD_OWN_AGENT_TEXT", phase="final_answer", ordinal=3),
        ]
        _, body = self.condense_codex(records, kind="fork", meta=meta["payload"])
        self.assertNotIn("INHERITED_USER_TEXT", body)
        self.assertNotIn("INHERITED_AGENT_TEXT", body)
        self.assertIn("CHILD_OWN_USER_TEXT", body)
        self.assertIn("CHILD_OWN_AGENT_TEXT", body)
        self.assertEqual(labels(body), ["USER", "AGENT (final)"])

    def test_fork_without_start_drops_payloads_copied_from_parent(self):
        shared_user = (
            "Please rerun the full baseline follow-up with the corrected sensor sync, "
            "keeping the earlier 0920 results for comparison"
        )
        shared_agent = (
            "Rerun done. The corrected sensor sync lowers the error on the 0920 night but the 0813 result is unchanged."
        )
        parent_records = [
            cx_meta(CX_ROOT),
            cx_msg("user", shared_user, ts=TS),
            cx_msg("assistant", shared_agent, phase="final_answer", ts=TS2),
        ]
        parent_path = self.write_codex_rollout(parent_records, name="parent.jsonl")
        child_meta = cx_meta(CX_CHILD, forked_from_id=CX_ROOT)
        child_records = [
            child_meta,
            cx_msg("user", shared_user, ts=TS),
            cx_msg("assistant", shared_agent, phase="final_answer", ts=TS2),
            cx_msg("user", "CHILD_NEW_USER_TEXT", ts=TS2),
        ]
        _, body = self.condense_codex(child_records, kind="fork", parent_path=parent_path, meta=child_meta["payload"])
        self.assertNotIn("Rerun done", body)
        self.assertNotIn("rerun the full baseline", body)
        self.assertIn("CHILD_NEW_USER_TEXT", body)

    def test_spawned_subagent_first_user_message_is_task_from_parent(self):
        meta = cx_meta(
            CX_CHILD, source={"subagent": {"thread_spawn": {"parent_thread_id": CX_ROOT}}}, parent_thread_id=CX_ROOT
        )
        records = [
            meta,
            cx_msg("user", "# AGENTS.md instructions for /x\n\nAGENTS_SECRET"),
            cx_msg("user", "TASK_TEXT_FROM_PARENT: audit the 0920 folder"),
            cx_msg("assistant", "DONE_TEXT", phase="final_answer"),
            cx_msg("user", "LATER_FOLLOWUP_TEXT"),
        ]
        _, body = self.condense_codex(records, kind="subagent", meta=meta["payload"])
        self.assertEqual(labels(body), ["TASK (from parent)", "AGENT (final)", "USER"])
        self.assertNotIn("AGENTS_SECRET", body)


class CodexClassTests(unittest.TestCase):
    def test_guardian_is_classified_guardian(self):
        meta = {"source": {"subagent": {"other": "guardian"}}, "parent_thread_id": CX_ROOT}
        self.assertEqual(codex_class(meta), "guardian")

    def test_spawned_subagent_by_thread_spawn_source(self):
        meta = {"source": {"subagent": {"thread_spawn": {"parent_thread_id": CX_ROOT}}}}
        self.assertEqual(codex_class(meta), "subagent")

    def test_spawned_subagent_by_parent_thread_id(self):
        meta = {"source": "cli", "parent_thread_id": CX_ROOT}
        self.assertEqual(codex_class(meta), "subagent")

    def test_fork_by_forked_from_id(self):
        meta = {"source": "cli", "forked_from_id": CX_ROOT, "subagent_history_start_ordinal": 5}
        self.assertEqual(codex_class(meta), "fork")

    def test_root_sources(self):
        for source in ("cli", "vscode", "exec"):
            with self.subTest(source=source):
                self.assertEqual(codex_class({"source": source, "cwd": ROOT_DP}), "root")

    def test_guardian_wins_over_fork_fields(self):
        meta = {"source": {"subagent": {"other": "guardian"}}, "forked_from_id": CX_ROOT}
        self.assertEqual(codex_class(meta), "guardian")


# ---------------------------------------------------------------------------
# 5. Claude condense (claude_condense)
# ---------------------------------------------------------------------------


class ClaudeUserTextTests(TempAtlasCase):
    def test_only_human_string_content_counts_as_user(self):
        records = [
            cl_user("Where is the pilot data?"),
            cl_user("NO_ORIGIN_STR_TEXT", origin=None),
            cl_user("LIST_CONTENT_TEXT", origin="human")
            | {"message": {"role": "user", "content": [{"type": "text", "text": "LIST_CONTENT_TEXT"}]}},
            cl_text("ok", stop="end_turn"),
        ]
        _, body = self.condense_claude(records)
        self.assertEqual(labels(body), ["USER", "AGENT (final)"])
        self.assertIn("Where is the pilot data?", body)
        self.assertNotIn("NO_ORIGIN_STR_TEXT", body)
        self.assertNotIn("LIST_CONTENT_TEXT", body)

    def test_task_notification_and_peer_origins_are_dropped(self):
        records = [
            cl_user("<task-notification>TASK_NOTIFICATION_BODY</task-notification>", origin="task-notification"),
            cl_user("PEER_MESSAGE_BODY", origin="peer"),
            cl_user("REAL_HUMAN_TEXT"),
        ]
        _, body = self.condense_claude(records)
        self.assertNotIn("TASK_NOTIFICATION_BODY", body)
        self.assertNotIn("PEER_MESSAGE_BODY", body)
        self.assertEqual(labels(body), ["USER"])

    def test_injected_human_prefixes_are_dropped(self):
        injected = [
            "[Image: original 1920x1080, displayed at 1024x576]",
            "<local-command-caveat>CAVEAT_BODY</local-command-caveat>",
            "<command-name>/clear</command-name>",
            "<local-command-stdout>STDOUT_BODY</local-command-stdout>",
            "Base directory for this skill: /home/user/skills/x SKILL_BODY",
        ]
        records = [cl_user(t) for t in injected] + [cl_user("REAL_HUMAN_TEXT")]
        _, body = self.condense_claude(records)
        for t in ("CAVEAT_BODY", "STDOUT_BODY", "SKILL_BODY", "[Image:", "<command-name>"):
            with self.subTest(text=t):
                self.assertNotIn(t, body)
        self.assertEqual(labels(body), ["USER"])

    def test_attachments_and_non_keep_record_types_are_dropped(self):
        records = [
            {
                "type": "attachment",
                "timestamp": TS,
                "attachment": {"type": "instructions", "content": "ATTACHMENT_SECRET agents.md"},
            },
            {"type": "queue-operation", "timestamp": TS, "content": "QUEUE_SECRET"},
            {"type": "last-prompt", "timestamp": TS, "lastPrompt": "LASTPROMPT_SECRET"},
            {"type": "system", "subtype": "compact_boundary", "timestamp": TS, "content": "SYSTEM_SECRET"},
            cl_user("REAL_HUMAN_TEXT"),
        ]
        _, body = self.condense_claude(records)
        for t in ("ATTACHMENT_SECRET", "QUEUE_SECRET", "LASTPROMPT_SECRET", "SYSTEM_SECRET"):
            with self.subTest(text=t):
                self.assertNotIn(t, body)


class ClaudeAgentTextTests(TempAtlasCase):
    def test_text_kept_thinking_dropped_and_final_marked(self):
        records = [
            cl_block({"type": "thinking", "thinking": "THINKING_SECRET", "signature": "sig"}, mid="msg_1"),
            cl_text("Plan: check the sensor sync first.", mid="msg_1", idx=1),
            cl_text("Final: the sensor is 0920 reference.", mid="msg_2", idx=0, stop="end_turn"),
            cl_user("next question"),
        ]
        _, body = self.condense_claude(records)
        self.assertNotIn("THINKING_SECRET", body)
        self.assertEqual(labels(body), ["AGENT", "AGENT (final)", "USER"])
        self.assertIn("Final: the sensor is 0920 reference.", body)

    def test_bash_command_and_read_path_are_kept(self):
        records = [
            cl_tool("Bash", {"command": "ls /mnt/nas_data/lab/data", "description": "list"}, idx=0),
            cl_tool("Read", {"file_path": "/mnt/nas_data/lab/data/readme.txt"}, idx=1),
            cl_user("next"),
        ]
        _, body = self.condense_claude(records)
        self.assertIn("- `$ ls /mnt/nas_data/lab/data` (in " + ROOT_DP + ")", body)
        self.assertIn("- Read /mnt/nas_data/lab/data/readme.txt", body)

    def test_edit_writes_file_path_not_contents(self):
        records = [
            cl_tool(
                "Edit",
                {"file_path": ROOT_DP + "/x.py", "old_string": "EDIT_OLD_SECRET", "new_string": "EDIT_NEW_SECRET"},
            ),
            cl_user("next"),
        ]
        _, body = self.condense_claude(records)
        self.assertIn("- Edit " + ROOT_DP + "/x.py", body)
        self.assertNotIn("EDIT_OLD_SECRET", body)
        self.assertNotIn("EDIT_NEW_SECRET", body)

    def test_subagent_handback_is_kept_in_full(self):
        long_report = "REPORT " + ("filler line\n" * 400) + "END_OF_REPORT"
        self.assertGreater(len(long_report), LIMITS["subagent_result"])
        records = [cl_user("TASK_FROM_PARENT", origin=None), cl_tool("SubagentHandback", {"message": long_report})]
        _, body = self.condense_claude(records, subagent=True)
        self.assertIn("SUBAGENT REPORT", labels(body))
        self.assertIn("END_OF_REPORT", body)


class ClaudeSubagentAndRecapTests(TempAtlasCase):
    def test_subagent_first_user_record_is_task_from_parent(self):
        records = [
            cl_user("TASK_TEXT_FROM_PARENT: summarise the 0920 folder", origin=None),
            cl_text("Working on it.", mid="msg_1"),
            cl_text("DONE_TEXT", mid="msg_2", stop="end_turn"),
            cl_user("HARNESS_META_TEXT", origin=None, isMeta=True),
        ]
        _, body = self.condense_claude(records, subagent=True)
        self.assertEqual(labels(body), ["TASK (from parent)", "AGENT", "AGENT (final)"])
        self.assertNotIn("HARNESS_META_TEXT", body)

    def test_away_summary_is_recap_and_other_system_records_dropped(self):
        records = [
            {
                "type": "system",
                "subtype": "away_summary",
                "timestamp": TS,
                "content": "RECAP_TEXT: last session was about the pilot import",
            },
            {"type": "system", "subtype": "api_error", "timestamp": TS, "content": "SYSTEM_ERROR_TEXT"},
            cl_user("next"),
        ]
        _, body = self.condense_claude(records)
        self.assertEqual(labels(body), ["RECAP", "USER"])
        self.assertIn("RECAP_TEXT", body)
        self.assertNotIn("SYSTEM_ERROR_TEXT", body)

    def test_tool_result_is_scanned_for_paths_but_not_written(self):
        records = [
            cl_user("look"),
            cl_tool("Bash", {"command": "ls"}, idx=0),
            cl_tool_result(
                "TOOL_RESULT_SECRET " + NAS_RECORDING,
                tool_use_result={"stdout": "STDOUT_SECRET " + NAS_RECORDING_HHMMSS},
            ),
            cl_user("next"),
        ]
        st, body = self.condense_claude(records)
        self.assertNotIn("TOOL_RESULT_SECRET", body)
        self.assertNotIn("STDOUT_SECRET", body)
        self.assertIn(NAS_RECORDING, st["hits"])
        self.assertIn(NAS_RECORDING_HHMMSS, st["hits"])

    def test_original_file_and_patch_fields_are_not_scanned(self):
        # docs/02: skip originalFile / structuredPatch when scanning tool results.
        tur = {
            "file": {"content": "ok", "originalFile": "/mnt/nas_data/ORIGINAL_ONLY.npy"},
            "structuredPatch": [{"lines": ["/mnt/nas_data/PATCH_ONLY.npy"]}],
        }
        st, _ = self.condense_claude([cl_tool_result("short result", tool_use_result=tur), cl_user("next")])
        self.assertNotIn("/mnt/nas_data/ORIGINAL_ONLY.npy", st["hits"])
        self.assertNotIn("/mnt/nas_data/PATCH_ONLY.npy", st["hits"])

    def test_session_title_and_cwd_are_read(self):
        records = [cl_user("first"), {"type": "ai-title", "aiTitle": "Pilot import check", "timestamp": TS}]
        st, _ = self.condense_claude(records)
        self.assertEqual(st["title"], "Pilot import check")
        self.assertEqual(st["cwd"], ROOT_DP)


# ---------------------------------------------------------------------------
# 6. Selection (select_candidates) and candidate discovery (discover_candidates)
# ---------------------------------------------------------------------------


def cand(source, kind, cid, cwd, parent_id=None):
    """Candidate dict shaped like discover_candidates() output (only the keys selection reads)."""
    short = cid[:13] if source == "codex" else cid[:8]
    return {
        "source": source,
        "kind": kind,
        "id": cid,
        "short": short,
        "path": None,
        "parent_id": parent_id,
        "cwd": cwd,
        "meta": {},
        "key": (source, cid),
    }


class SelectionTests(TempAtlasCase):
    def select(self, cands, cfg=None):
        return select_candidates(cands, cfg or self.cfg)

    def test_cwd_under_root_is_selected_by_cwd(self):
        cands = [cand("codex", "root", CX_ROOT, ROOT_DP + "/experiment/rig")]
        self.assertEqual(self.select(cands), {("codex", CX_ROOT): "cwd"})

    def test_cwd_under_related_root_is_selected(self):
        cands = [cand("codex", "root", CX_ROOT, ROOT_MB + "/src")]
        self.assertEqual(self.select(cands), {("codex", CX_ROOT): "cwd"})

    def test_cwd_also_directory_is_selected(self):
        cands = [cand("codex", "root", CX_ROOT, RESEARCH)]
        self.assertEqual(self.select(cands), {("codex", CX_ROOT): "cwd"})

    def test_cwd_outside_roots_is_not_selected(self):
        cands = [cand("codex", "root", CX_ROOT, OTHER_CWD)]
        self.assertEqual(self.select(cands), {})

    def test_cwd_under_exclude_cwd_is_never_selected(self):
        cands = [
            cand("codex", "root", CX_ROOT, ATLAS_CWD + "/tests"),
            cand("claude", "root", "4ff003a4-0000-0000-0000-000000000000", ATLAS_CWD),
        ]
        self.assertEqual(self.select(cands), {})

    def test_subagent_under_exclude_cwd_is_not_selected_even_with_selected_parent(self):
        cands = [
            cand("codex", "root", CX_ROOT, ROOT_DP),
            cand("codex", "subagent", CX_CHILD, ATLAS_CWD, parent_id=CX_ROOT),
        ]
        sel = self.select(cands)
        self.assertEqual(sel, {("codex", CX_ROOT): "cwd"})

    def test_exclude_ids_prefix_excludes_the_session(self):
        cfg, _ = make_config(self.tmp / "excl", exclude_ids=["01a1700a-530c"])
        cands = [cand("codex", "root", CX_EXCLUDED, ROOT_DP), cand("codex", "root", CX_ROOT, ROOT_DP)]
        self.assertEqual(self.select(cands, cfg), {("codex", CX_ROOT): "cwd"})

    def test_children_of_excluded_session_are_excluded_transitively(self):
        # D20: subagents and forks of an excluded session are excluded, even with a root cwd.
        cfg, _ = make_config(self.tmp / "excl", exclude_ids=["01a1700a-530c"])
        # Child ids must not share the excluded prefix, or the prefix rule alone would exclude them.
        child = "01a17777-0001-7000-8000-000000000010"
        grandchild = "01a17777-0002-7000-8000-000000000011"
        cands = [
            cand("codex", "root", CX_EXCLUDED, ROOT_DP),
            cand("codex", "subagent", child, ROOT_DP, parent_id=CX_EXCLUDED),
            cand("codex", "fork", grandchild, ROOT_DP, parent_id=child),
        ]
        self.assertEqual(self.select(cands, cfg), {})

    def test_children_of_exclude_cwd_session_are_excluded_transitively(self):
        child = CX_CHILD
        grandchild = "01a1619b-c103-7000-8000-000000000009"
        cands = [
            cand("codex", "root", CX_ROOT, ATLAS_CWD),
            cand("codex", "subagent", child, ROOT_DP, parent_id=CX_ROOT),
            cand("codex", "fork", grandchild, ROOT_DP, parent_id=child),
        ]
        self.assertEqual(self.select(cands), {})

    def test_subagent_selected_by_selected_parent_when_cwd_is_elsewhere(self):
        child = CX_CHILD
        grandchild = "01a1619b-c103-7000-8000-000000000009"
        cands = [
            cand("codex", "root", CX_ROOT, ROOT_DP),
            cand("codex", "subagent", child, OTHER_CWD, parent_id=CX_ROOT),
            cand("codex", "fork", grandchild, OTHER_CWD, parent_id=child),
        ]
        self.assertEqual(
            self.select(cands), {("codex", CX_ROOT): "cwd", ("codex", child): "parent", ("codex", grandchild): "parent"}
        )

    def test_child_of_unselected_parent_is_not_selected(self):
        cands = [
            cand("codex", "root", CX_ROOT, OTHER_CWD),
            cand("codex", "subagent", CX_CHILD, OTHER_CWD, parent_id=CX_ROOT),
        ]
        self.assertEqual(self.select(cands), {})

    def test_claude_subagent_selected_by_parent_session(self):
        sid = "9f1e2d3c-0000-4000-8000-000000000001"
        cands = [
            cand("claude", "root", sid, ROOT_DP),
            cand("claude", "subagent", "abcdef12-0000-4000-8000-000000000002", OTHER_CWD, parent_id=sid),
        ]
        sel = self.select(cands)
        self.assertEqual(sel[("claude", sid)], "cwd")
        self.assertEqual(sel[("claude", "abcdef12-0000-4000-8000-000000000002")], "parent")

    def test_discover_candidates_takes_claude_subagent_parent_from_its_folder(self):
        # docs/02: subagents live in <projdir>/<sid>/subagents/agent-<agentId>.jsonl.
        proj = self.tmp / "claude" / "projects" / "-home-user-research-demo_project"
        sid = "9f1e2d3c-0000-4000-8000-000000000001"
        dump_jsonl(proj / f"{sid}.jsonl", [cl_user("hi")])
        dump_jsonl(proj / sid / "subagents" / "agent-aaa111.jsonl", [cl_user("task", origin=None)])
        dump_jsonl(proj / sid / "subagents" / "agent-bbb222.jsonl", [cl_user("task", origin=None)])
        (proj / sid / "subagents" / "agent-bbb222.meta.json").write_text(
            json.dumps({"parentAgentId": "aaa111"}), encoding="utf-8"
        )
        cands, guardians = discover_candidates(self.cfg, [])
        self.assertEqual(guardians, 0)
        by_id = {c["id"]: c for c in cands}
        self.assertEqual(by_id[sid]["kind"], "root")
        self.assertEqual(by_id["aaa111"]["parent_id"], sid)
        self.assertEqual(by_id["aaa111"]["kind"], "subagent")
        self.assertEqual(by_id["bbb222"]["parent_id"], "aaa111")
        self.assertEqual(by_id[sid]["cwd"], ROOT_DP)


# ---------------------------------------------------------------------------
# 7. Paths (path_regex, scan_paths, clean_path)
# ---------------------------------------------------------------------------


class PathHarvestTests(unittest.TestCase):
    def setUp(self):
        self.rx = path_regex(PATH_ROOTS)

    def harvest(self, text):
        hits = {}
        scan_paths(text, self.rx, hits)
        return hits

    def test_recording_folder_with_space_is_kept_whole(self):
        # docs/02: recording folders are named "YYYY-MM-DD HH:MM:SS" (or HH_MM_SS).
        self.assertEqual(set(self.harvest("saved to " + NAS_RECORDING + " and then")), {NAS_RECORDING})
        self.assertEqual(set(self.harvest("see " + NAS_RECORDING_HHMMSS + ".")), {NAS_RECORDING_HHMMSS})

    def test_grep_context_suffix_is_stripped(self):
        # grep -n -A/-B output: "<file>-<line>-<text>" glues onto the path.
        text = ROOT_DP + "/experiment/loader.py-52-    x = 1\n/mnt/nas_data/lab/notes.txt-7-more"
        self.assertEqual(set(self.harvest(text)), {ROOT_DP + "/experiment/loader.py", "/mnt/nas_data/lab/notes.txt"})

    def test_grep_match_colon_suffix_is_not_part_of_path(self):
        self.assertEqual(set(self.harvest("/mnt/nas_data/lab/loader.py:52: x")), {"/mnt/nas_data/lab/loader.py"})

    def test_trailing_punctuation_and_quotes_are_not_part_of_path(self):
        cases = {
            "end of sentence /mnt/nas_data/a/b.npy.": "/mnt/nas_data/a/b.npy",
            'quoted "/mnt/nas_data/a/b.npy" here': "/mnt/nas_data/a/b.npy",
            "single '/mnt/nas_data/a/b.npy' here": "/mnt/nas_data/a/b.npy",
            "backticks `/mnt/nas_data/a/b.npy`": "/mnt/nas_data/a/b.npy",
            "parens (/mnt/nas_data/a/b.npy)": "/mnt/nas_data/a/b.npy",
            "question /mnt/nas_data/a/b.npy?": "/mnt/nas_data/a/b.npy",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(set(self.harvest(text)), {expected})

    def test_several_paths_in_a_list_are_each_trimmed(self):
        self.assertEqual(
            set(self.harvest("list /mnt/nas_data/a/b.npy, /mnt/tmp/c.npy;")),
            {"/mnt/nas_data/a/b.npy", "/mnt/tmp/c.npy"},
        )

    def test_paths_outside_configured_roots_are_ignored(self):
        text = "/home/user/other/x.npy /var/log/y.log /opt/tool/z /srv/data/w.npy"
        self.assertEqual(self.harvest(text), {})

    def test_root_must_match_a_whole_path_component(self):
        # /mnt/nas_datax and /mnt/data_old are different roots, not /mnt/nas_data or /mnt/data.
        text = "/mnt/nas_datax/y.npy /mnt/data_old/z.npy /mnt/dataset/q.npy"
        self.assertEqual(self.harvest(text), {})

    def test_repeated_paths_are_counted(self):
        text = "/mnt/nas_data/a.npy and again /mnt/nas_data/a.npy"
        self.assertEqual(self.harvest(text), {"/mnt/nas_data/a.npy": 2})

    def test_clean_path_normalises_and_rejects_empty_or_overlong(self):
        self.assertEqual(clean_path("/mnt/nas_data//a/./b.npy/"), "/mnt/nas_data/a/b.npy")
        self.assertIsNone(clean_path("..."))
        self.assertIsNone(clean_path("/mnt/nas_data/" + "x" * 400))

    def test_parentheses_inside_a_path_are_kept(self):
        # Real names such as "1x1(iw612)" (directory) and "tier1a_feat_PCA_(10D).png" (file) occur in transcripts.
        cases = [
            ROOT_DP + "/dataPlan/test_case/1x1(iw612)/test_case1-1.yaml",
            ROOT_DP + "/experiment/rig/figures/tier1a_feat_PCA_(10D).png",
            ROOT_DP + "/dataPlan/test_case/2x2(synaptics)/.ipynb_checkpoints/test_case1-1-checkpoint.yaml",
        ]
        for path in cases:
            with self.subTest(path=path):
                self.assertEqual(set(self.harvest("see " + path + " now")), {path})

    def test_closing_paren_without_opening_paren_inside_path_is_not_part_of_it(self):
        # A ")" with no "(" inside the path is prose, a markdown link end, or the end of a call.
        cases = {
            "(see /mnt/nas_data/a/b)": "/mnt/nas_data/a/b",
            "func(/mnt/nas_data/a/b, x)": "/mnt/nas_data/a/b",
            "[see](/mnt/nas_data/a/b.md)": "/mnt/nas_data/a/b.md",
            "/mnt/nas_data/a/b.npy)": "/mnt/nas_data/a/b.npy",
            "(/mnt/nas_data/a/b(1))": "/mnt/nas_data/a/b(1)",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(set(self.harvest(text)), {expected})

    def test_braces_and_brackets_still_end_a_path(self):
        cases = {"/mnt/nas_data/a/b.npy]": "/mnt/nas_data/a/b.npy", "/mnt/nas_data/a/b.npy{x}": "/mnt/nas_data/a/b.npy"}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(set(self.harvest(text)), {expected})

    def test_grep_context_after_a_known_extension_is_stripped(self):
        # Real grep -A/-B output after a source or text file name (extensions listed in _KIND_BY_EXT).
        cases = {
            ROOT_DP + "/experiment/run.py-12-import os": ROOT_DP + "/experiment/run.py",
            ROOT_DP + "/notes/readme.md-3-## Setup": ROOT_DP + "/notes/readme.md",
            "/mnt/nas_data/lab/table.csv-1-id,value": "/mnt/nas_data/lab/table.csv",
            "/mnt/nas_data/lab/config.yaml-9-  lr: 0.1": "/mnt/nas_data/lab/config.yaml",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(set(self.harvest(text)), {expected})

    def test_cpython_tag_in_pyc_name_is_kept_whole(self):
        # "-310-pytest-" is part of the .pyc file name, not grep context: ".cpython" is not a known extension.
        pyc = ROOT_DP + "/experiment/x/__pycache__/test_d4f.cpython-310-pytest-9.1.1.pyc"
        core = ROOT_DP + "/experiment/x/__pycache__/core.cpython-310.pyc"
        self.assertEqual(set(self.harvest("ran " + pyc + " ok")), {pyc})
        self.assertEqual(set(self.harvest(core)), {core})

    def test_path_right_after_a_literal_backslash_escape_is_found(self):
        # Doubly escaped tool output has a literal backslash + n/t/r before the path. The character before the
        # backslash does not matter.
        rec = "/mnt/nas_data/lab/data/demo/raw_data/0408_site_2/signal"
        for esc in ("\\n", "\\t", "\\r"):
            for before in ("notice.xlsx", "foo", "1", ".", "/", ")"):
                text = before + esc + rec
                with self.subTest(text=text):
                    self.assertEqual(set(self.harvest(text)), {rec})
        two = "/mnt/nas_data/a.npy\\n/mnt/nas_data/b.npy"
        self.assertEqual(set(self.harvest(two)), {"/mnt/nas_data/a.npy", "/mnt/nas_data/b.npy"})

    def test_root_glued_to_a_word_or_a_non_escape_backslash_is_not_found(self):
        # Only a backslash + n/t/r escape counts. A plain word character before the root does not.
        cases = ["bar/mnt/nas_data/a.npy", "foo\\nbar/mnt/nas_data/a.npy", "foo\\x/mnt/nas_data/a.npy"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.harvest(text), {})


# ---------------------------------------------------------------------------
# 8. Citations (expand_cited, cited_paths)
# ---------------------------------------------------------------------------

ABBREV = {"DP": ROOT_DP, "RIG": ROOT_DP + "/experiment/rig", "EXP": "/mnt/nas_data/lab/data/site/exports"}


class ExpandCitedTests(unittest.TestCase):
    def test_abbreviations_expand_to_absolute_paths(self):
        self.assertEqual(expand_cited("DP/experiment/20260921_x", ABBREV), ROOT_DP + "/experiment/20260921_x")
        self.assertEqual(
            expand_cited("RIG/20260922_0920_dataset/README.md", ABBREV),
            ROOT_DP + "/experiment/rig/20260922_0920_dataset/README.md",
        )
        self.assertEqual(
            expand_cited("EXP/rec_export_20261012_152940", ABBREV),
            "/mnt/nas_data/lab/data/site/exports/rec_export_20261012_152940",
        )

    def test_absolute_span_is_returned_as_is(self):
        self.assertEqual(expand_cited("/mnt/nas_data/lab/x.npy", ABBREV), "/mnt/nas_data/lab/x.npy")

    def test_templates_return_none(self):
        templates = [
            "DP/experiment/<date>_x",
            "DP/experiment/{a,b}",
            "RIG/*.npy",
            "EXP/rec_export_YYYYMMDD",
            "EXP/files/HH:MM:SS",
            "EXP/data/20261010_HHMMSS",
        ]
        for span in templates:
            with self.subTest(span=span):
                self.assertIsNone(expand_cited(span, ABBREV))

    def test_non_path_spans_return_none(self):
        spans = [
            "pytest -q",
            "atlas.py",
            "sessions.jsonl",
            "[codex:01a1619b-8270 2026-10-22]",
            "DP",
            "knowledge/INDEX.md",
            "/",
            "",
            "[file:experiment/rig/x/README.md]",
        ]
        for span in spans:
            with self.subTest(span=span):
                self.assertIsNone(expand_cited(span, ABBREV))

    def test_command_span_is_cut_at_first_space(self):
        self.assertEqual(expand_cited("/opt/conda/bin/python atlas.py refresh", ABBREV), "/opt/conda/bin/python")

    def test_recording_time_stays_inside_the_span(self):
        span = "EXP/rec_export_20261012_152940/files/2026-10-10 17:45:04/002"
        self.assertEqual(
            expand_cited(span, ABBREV),
            "/mnt/nas_data/lab/data/site/exports/rec_export_20261012_152940/files/2026-10-10 17:45:04/002",
        )

    def test_parenthesised_note_is_dropped(self):
        self.assertEqual(expand_cited("DP/experiment/x (lead)", ABBREV), ROOT_DP + "/experiment/x")


class CitedPathsTests(TempAtlasCase):
    def write_knowledge(self, name, text):
        kdir = self.cfg["project"]["knowledge_dir"]
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / name).write_text(text, encoding="utf-8")

    def test_reports_path_with_file_name_and_line_number(self):
        self.write_knowledge(
            "datasets.md",
            "# Datasets\n\n"
            "- raw signal: `DP/experiment/20260921_x` ✓ 2026-10-22\n"
            "- command: `/opt/conda/bin/python atlas.py refresh`\n",
        )
        cited = cited_paths(self.cfg)
        self.assertEqual(
            cited, [(ROOT_DP + "/experiment/20260921_x", "datasets.md", 3), ("/opt/conda/bin/python", "datasets.md", 4)]
        )

    def test_spans_followed_by_cross_mark_are_skipped(self):
        # docs/04 §4: ✗-marked citations are known-missing and are not re-reported.
        self.write_knowledge(
            "datasets.md",
            "- gone: `EXP/rec_export_29990101_000000` ✗ 2026-10-22\n"
            "- here: `EXP/rec_export_20261012_152940` ✓ 2026-10-22\n",
        )
        cited = cited_paths(self.cfg)
        self.assertEqual([p for p, _, _ in cited], ["/mnt/nas_data/lab/data/site/exports/rec_export_20261012_152940"])

    def test_template_and_non_path_spans_are_not_cited(self):
        self.write_knowledge("INDEX.md", "- `DP/experiment/<date>_x` and `pytest -q` and `sessions.jsonl`\n")
        self.assertEqual(cited_paths(self.cfg), [])

    def test_all_knowledge_files_are_scanned_in_name_order(self):
        self.write_knowledge("open_questions.md", "`DP/experiment/b`\n")
        self.write_knowledge("datasets.md", "`DP/experiment/a`\n")
        names = [name for _, name, _ in cited_paths(self.cfg)]
        self.assertEqual(names, ["datasets.md", "open_questions.md"])


# ---------------------------------------------------------------------------
# under()
# ---------------------------------------------------------------------------


class UnderTests(unittest.TestCase):
    def test_sibling_with_shared_string_prefix_is_not_under(self):
        self.assertFalse(under("/a/bc", ["/a/b"]))

    def test_equal_path_counts_as_under(self):
        self.assertTrue(under("/a/b", ["/a/b"]))

    def test_child_path_is_under(self):
        self.assertTrue(under("/a/b/c/d", ["/a/b"]))

    def test_any_prefix_in_the_list_can_match(self):
        self.assertTrue(under("/x/y", ["/a/b", "/x"]))

    def test_missing_path_is_never_under(self):
        self.assertFalse(under(None, ["/a/b"]))
        self.assertFalse(under("", ["/a/b"]))


# ---------------------------------------------------------------------------
# Review ledger and mark-reviewed (D25)
# ---------------------------------------------------------------------------

CL_A = "5a1c3e9b-ace1-4efc-a261-57553cba4e4d"
CL_B = "5a1c3e9b-ffff-4efc-a261-57553cba4e4e"  # shares the 8-char prefix with CL_A
CP_A = "7f3b2c10-6b58-4cdf-8a5e-b55b20f7d48a"


class ReviewLedgerTests(TempAtlasCase):
    def setUp(self):
        super().setUp()
        self.sdir = self.cfg["project"]["work_dir"] / "sessions"
        self.sdir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.cfg["project"]["review_ledger"]
        self.rows = [
            self.session("claude", CL_A, "first"),
            self.session("claude", CL_B, "second"),
            self.session("copilot", CP_A, "third"),
            self.session("codex", CX_ROOT, None),
        ]
        dump_jsonl(work_paths(self.cfg)["sessions_index"], self.rows)

    def session(self, source, sid, text):
        short = sid[:13] if source == "codex" else sid[:8]
        cp = None
        if text is not None:
            cp = self.sdir / f"{source}_{short}.md"
            cp.write_text(text, encoding="utf-8")
        return {
            "source": source,
            "id": sid,
            "short_id": short,
            "kind": "root",
            "condensed_path": str(cp) if cp else None,
        }

    def mark(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["--config", str(self.cfg_path), "mark-reviewed", *argv])
        return rc, out.getvalue(), err.getvalue()

    def pending(self):
        new, changed = pending_sessions(self.rows, load_ledger(self.ledger_path))
        return [session_key(r) for r, *_ in new], [session_key(r) for r, *_ in changed]

    def test_default_ledger_sits_next_to_knowledge_dir(self):
        self.assertEqual(self.ledger_path, self.tmp / "reviewed_sessions.jsonl")

    def test_everything_is_new_without_a_ledger(self):
        new, changed = self.pending()
        self.assertEqual(len(new), 4)
        self.assertEqual(changed, [])

    def test_marked_session_is_no_longer_pending_until_its_text_changes(self):
        rc, _, _ = self.mark("copilot:7f3b", "--note", "merged")
        self.assertEqual(rc, 0)
        new, changed = self.pending()
        self.assertNotIn("copilot:" + CP_A, new)
        self.assertEqual(changed, [])
        (self.sdir / "copilot_7f3b2c10.md").write_text("third, grown", encoding="utf-8")
        _, changed = self.pending()
        self.assertEqual(changed, ["copilot:" + CP_A])

    def test_row_records_sha_bytes_date_and_note(self):
        self.mark("copilot:7f3b", "--note", "merged")
        row = load_ledger(self.ledger_path)["copilot:" + CP_A]
        self.assertEqual(row["bytes"], len("third"))
        self.assertRegex(row["sha"], r"^[0-9a-f]{12}$")
        self.assertRegex(row["reviewed"], r"^\d{4}-\d\d-\d\d$")
        self.assertEqual(row["note"], "merged")

    def test_session_without_condensed_text_can_be_marked(self):
        self.mark(CX_ROOT[:13])
        self.assertEqual(load_ledger(self.ledger_path)["codex:" + CX_ROOT]["sha"], None)
        self.assertNotIn("codex:" + CX_ROOT, self.pending()[0])

    def test_ambiguous_or_unknown_id_writes_nothing(self):
        rc, _, err = self.mark("copilot:7f3b", "claude:5a1c3e9b")
        self.assertEqual(rc, 2)
        self.assertIn("ambiguous", err)
        rc, _, err = self.mark("copilot:7f3b", "deadbeef")
        self.assertEqual(rc, 2)
        self.assertIn("no indexed session", err)
        self.assertFalse(self.ledger_path.exists())

    def test_ledger_is_sorted_by_session_key(self):
        self.mark("copilot:7f3b", "claude:5a1c3e9b-ace1", "claude:5a1c3e9b-ffff")
        keys = [json.loads(line)["session"] for line in self.ledger_path.read_text().splitlines()]
        self.assertEqual(keys, sorted(keys))

    def write_report(self, rows):
        lines = ["New sessions (not reviewed): 2"]
        for r in rows:
            sha, _ = condensed_digest(r)
            lines += [
                f"  {r['source']}:{r['short_id']}  2026-10-30 06:33  root  sha={sha or '-'}  title",
                f"      {r['condensed_path']}",
            ]
        path = self.tmp / "report.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_report_marks_every_listed_session(self):
        report = self.write_report([self.rows[2], self.rows[3]])
        self.assertEqual(
            parse_report(report), {"copilot:7f3b2c10": condensed_digest(self.rows[2])[0], "codex:" + CX_ROOT[:13]: None}
        )
        rc, _, _ = self.mark("--report", str(report))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(load_ledger(self.ledger_path)), ["codex:" + CX_ROOT, "copilot:" + CP_A])

    def test_session_changed_after_the_report_stays_pending(self):
        report = self.write_report([self.rows[2]])
        (self.sdir / "copilot_7f3b2c10.md").write_text("third, grown after the report", encoding="utf-8")
        rc, out, _ = self.mark("--report", str(report))
        self.assertEqual(rc, 0)
        self.assertIn("stays pending", out)
        self.assertEqual(self.pending()[1], ["copilot:" + CP_A])

    def test_id_not_in_the_report_is_refused(self):
        report = self.write_report([self.rows[2]])
        rc, _, err = self.mark("--report", str(report), "claude:5a1c3e9b-ace1")
        self.assertEqual(rc, 2)
        self.assertIn("not listed in", err)


class AtlasFeedbackTests(unittest.TestCase):
    def feedback(self, text):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.md"
            p.write_text(text, encoding="utf-8")
            return [t for _, t in atlas_feedback(str(p))]

    def test_correction_in_a_session_that_read_the_atlas_is_reported(self):
        hits = self.feedback(
            "- `$ cat /home/user/ResearchAtlas/projects/demo_project/knowledge/INDEX.md`\n"
            "Three Atlas recording IDs differ from the actual CSV import keys.\n"
            "The pilot import works.\n"
        )
        self.assertEqual(hits, ["Three Atlas recording IDs differ from the actual CSV import keys."])

    def test_session_that_never_read_the_atlas_reports_nothing(self):
        self.assertEqual(self.feedback("The atlas is outdated, someone said.\n"), [])

    def test_tool_command_lines_are_not_feedback(self):
        hits = self.feedback("- `$ /opt/conda/bin/python atlas.py find stale wrong`\n")
        self.assertEqual(hits, [])

    def test_correction_word_without_atlas_on_the_line_is_ignored(self):
        hits = self.feedback("- `$ atlas.py find sensor`\nThe sensor clock is wrong by 8 hours.\n")
        self.assertEqual(hits, [])


# ---------------------------------------------------------------------------
# find (main(["--config", ..., "find", ...]))
# ---------------------------------------------------------------------------


class FindTests(TempAtlasCase):
    def run_find(self, *terms):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--config", str(self.cfg_path), "find", *terms])
        return rc, buf.getvalue()

    def write_knowledge(self, name, text):
        kdir = self.cfg["project"]["knowledge_dir"]
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / name).write_text(text, encoding="utf-8")

    def test_matching_section_is_printed_with_file_line_heading_and_line(self):
        self.write_knowledge("INDEX.md", "# Atlas\n\n## Datasets\n\nTop datasets: pilot nights (DS-1)\n")
        rc, out = self.run_find("pilot")
        self.assertEqual(rc, 0)
        self.assertIn("== knowledge: 1 matching sections", out)
        self.assertIn("INDEX.md:3  Datasets\n", out)
        self.assertIn("      :5  Top datasets: pilot nights (DS-1)", out)

    def test_words_may_sit_on_different_lines_of_one_section(self):
        # D26: "pilot import notebook" must find an entry that spreads those words over its bullets.
        self.write_knowledge(
            "experiments.md", "# E\n\n## Pilot import\n- notebook: `x.ipynb`\n\n## Sensor\n- notebook: `y.ipynb`\n"
        )
        _, out = self.run_find("pilot", "import", "notebook")
        self.assertIn("experiments.md:3  Pilot import", out)
        self.assertNotIn("experiments.md:6", out)

    def test_words_in_different_sections_do_not_match(self):
        self.write_knowledge("INDEX.md", "# A\nsensor only\n# B\npilot only\n")
        rc, out = self.run_find("pilot", "sensor")
        self.assertIn("No match", out)

    def test_heading_inside_code_fence_does_not_split_a_section(self):
        self.write_knowledge("recipes.md", "## Load sensor\n```python\n# read the pilot csv\n```\n")
        _, out = self.run_find("sensor", "pilot")
        self.assertIn("recipes.md:1  Load sensor", out)

    def test_section_with_all_words_on_one_line_ranks_first(self):
        self.write_knowledge("a.md", "## Loose\npilot here\nsensor there\n")
        self.write_knowledge("b.md", "## Tight\npilot sensor together\n")
        _, out = self.run_find("pilot", "sensor")
        self.assertLess(out.index("b.md:1"), out.index("a.md:1"))

    def test_limit_counts_sections(self):
        self.write_knowledge("a.md", "".join(f"## S{i}\npilot\n" for i in range(5)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--config", str(self.cfg_path), "find", "pilot", "--limit", "2"])
        self.assertEqual(buf.getvalue().count("a.md:"), 2)
        self.assertIn("(3 more", buf.getvalue())

    def test_search_is_case_insensitive(self):
        self.write_knowledge("INDEX.md", "The 0920 Baseline dataset\n")
        _, out = self.run_find("BASELINE")
        self.assertIn("INDEX.md:1  (top of file)", out)

    def test_existing_paths_with_most_sessions_come_first(self):
        dump_jsonl(
            work_paths(self.cfg)["paths"],
            [
                {"path": "/x/sensor_a", "status": "missing", "n_sessions": 9},
                {"path": "/x/sensor_b", "status": "exists", "n_sessions": 1},
                {"path": "/x/sensor_c", "status": "exists", "n_sessions": 5},
            ],
        )
        _, out = self.run_find("sensor")
        self.assertLess(out.index("/x/sensor_c"), out.index("/x/sensor_b"))
        self.assertLess(out.index("/x/sensor_b"), out.index("/x/sensor_a"))

    def test_condensed_sessions_are_summarised_per_file(self):
        sdir = self.cfg["project"]["work_dir"] / "sessions"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "codex_01a1619b-8270.md").write_text(
            "# codex:01a1619b-8270 — Pilot import check\n- kind: root\n\n### 2026-10-10 10:00 USER\n"
            "Where is the October pilot data?\n\n### 2026-10-10 10:01 AGENT\nOctober pilot data is in EXP.\n",
            encoding="utf-8",
        )
        _, out = self.run_find("october", "pilot")
        self.assertIn("== sessions: 1 matching transcripts", out)
        self.assertIn("  codex:01a1619b-8270 — Pilot import check  [2 msg]", out)
        self.assertIn("codex_01a1619b-8270.md:5  Where is the October pilot data?", out)

    def test_no_match_prints_dont_guess_message(self):
        self.write_knowledge("INDEX.md", "nothing relevant here\n")
        rc, out = self.run_find("0230", "rowing")
        self.assertEqual(rc, 0)
        self.assertIn("No match for '0230 rowing' in the atlas.", out)
        self.assertIn("Don't guess a path", out)
        self.assertNotIn("==", out)


if __name__ == "__main__":
    unittest.main()
