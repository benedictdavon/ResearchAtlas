"""Codex rollouts: discovery, classification, and condensing (docs/02: Codex rollout record format)."""
import hashlib
import json
import os
import re
from pathlib import Path

from atlaslib.core import (bullet, cmd_line, collapse_ws, heading, new_state, note_ts, parse_ts, read_jsonl,
                           scan_obj, scan_paths, truncate, walk_jsonl)

NAME = "codex"
INJECTED_CODEX = ("# AGENTS.md instructions", "<environment_context>", "<turn_aborted>",
                  "<recommended_plugins>", "<image", "</image>")
CODEX_DROP_CALLS = {"wait", "wait_agent", "sleep", "list_agents", "close_agent", "write_stdin"}
CODEX_MESSAGE_CALLS = {"spawn_agent", "send_message", "followup_task"}


def codex_session_index(path):
    """Map Codex id -> latest thread_name (max updated_at), from session_index.jsonl."""
    names = {}
    if not os.path.exists(path):
        return names
    for r in read_jsonl(path):
        rid, name, upd = r.get("id"), r.get("thread_name"), r.get("updated_at") or ""
        if rid and name and upd >= names.get(rid, ("",))[0]:
            names[rid] = (upd, name)
    return {k: v[1] for k, v in names.items()}


def discover_codex(cfg):
    """Return (rollout paths, id -> path map). File id is the last 36 chars before .jsonl."""
    root = Path(cfg["sources"]["codex_sessions"])
    paths = sorted(p for p in root.rglob("rollout-*.jsonl") if p.is_file())
    by_id = {p.name[:-len(".jsonl")][-36:]: p for p in paths}
    return paths, by_id


def codex_meta(path):
    """Read only the first line (session_meta) of a rollout. None if unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
        rec = json.loads(first)
    except (OSError, json.JSONDecodeError):
        return None
    return rec.get("payload") if rec.get("type") == "session_meta" else None


def codex_class(meta):
    """Classify a session_meta payload per docs/02 (Transcript parsing rules)."""
    src = meta.get("source")
    sub = src.get("subagent") if isinstance(src, dict) else None
    if isinstance(sub, dict) and sub.get("other") == "guardian":
        return "guardian"
    if meta.get("forked_from_id"):
        return "fork"
    if meta.get("parent_thread_id") or (isinstance(sub, dict) and "thread_spawn" in sub):
        return "subagent"
    return "root"


JS_STR = r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`)"""


def js_literal(lit):
    """Decode a JS string literal from exec input (double-quoted ones are JSON-compatible)."""
    if lit.startswith('"'):
        try:
            return json.loads(lit)
        except json.JSONDecodeError:
            return lit[1:-1]
    return lit[1:-1]


def exec_commands(js):
    """(cmd, workdir) pairs from a Codex `exec` JS cell; one per tools.exec_command({...}) call."""
    out = []
    chunks = js.split("exec_command")[1:] if "exec_command" in js else [js]
    for chunk in chunks:
        m = re.search(r"\bcmd\s*:\s*" + JS_STR, chunk)
        if not m:
            continue
        w = re.search(r"\bworkdir\s*:\s*" + JS_STR, chunk)
        out.append((js_literal(m.group(1)), js_literal(w.group(1)) if w else None))
    return out


def patch_targets(text):
    """File paths touched by an apply_patch body (*** Add/Update/Delete File: <path>)."""
    return re.findall(r'\*\*\* (?:Add|Update|Delete) File: ([^\s"\'`\\]+)', text or "")


def text_of(output):
    """Plain text of a *_call_output (str, or list of parts with .text)."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(p.get("text", "") for p in output if isinstance(p, dict))
    return ""


def codex_user_part(text, lim):
    """Classify one user input_text part: (label, text) or None if injected (docs/02)."""
    s = text.lstrip()
    if s.startswith(INJECTED_CODEX):
        return None
    if s.startswith("# Context from my IDE setup:"):
        marker = "## My request for Codex:"
        if marker in s:
            return ("USER", s.split(marker, 1)[1])
        return ("USER", s)
    if s.startswith("<codex_internal_context"):
        m = re.search(r"<objective>(.*?)</objective>", s, re.S)
        return ("GOAL", m.group(1)) if m else None
    if s.startswith("<subagent_notification>"):
        return ("SUBAGENT RESULT", s)
    return ("USER", text)


def codex_call_bullets(st, ts, name, args, lim):
    """Bullets for one Codex function_call (args is the JSON string)."""
    try:
        a = json.loads(args) if isinstance(args, str) else (args or {})
    except json.JSONDecodeError:
        a = {}
    if not isinstance(a, dict):
        a = {}
    scan_obj(a, st["rx"], st["hits"])
    if name in CODEX_DROP_CALLS:
        return
    if name in ("exec_command", "shell"):
        cmd = a.get("cmd") or a.get("command")
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd[-1:]) if cmd else ""
        if cmd:
            bullet(st, ts, cmd_line(str(cmd), a.get("workdir"), lim))
        return
    if name in CODEX_MESSAGE_CALLS:
        target = a.get("target") or a.get("task_name") or ""
        msg = a.get("message") or ""
        line = f"{name} → {target}"
        if msg and not str(msg).startswith("gAAAAA"):
            line += ": " + truncate(collapse_ws(msg), lim["tool_input"])
        bullet(st, ts, line)
        return
    if name in ("request_user_input", "request_user_input_async"):
        qs = [q.get("question") or q.get("title") or "" for q in a.get("questions", []) if isinstance(q, dict)]
        bullet(st, ts, f"{name}: " + truncate(collapse_ws(" | ".join(qs)), lim["tool_input"]))
        return
    bullet(st, ts, f"tool: {name}")


def codex_custom_bullets(st, ts, name, raw, lim):
    """Bullets for a Codex custom_tool_call (exec JS or apply_patch)."""
    scan_paths(raw, st["rx"], st["hits"])
    if name == "exec":
        for cmd, workdir in exec_commands(raw):
            bullet(st, ts, cmd_line(cmd, workdir, lim))
        for target in patch_targets(raw):
            bullet(st, ts, f"patch: {target}")
    elif name == "apply_patch":
        for target in patch_targets(raw):
            bullet(st, ts, f"patch: {target}")
    else:
        bullet(st, ts, f"tool: {name}")


def codex_message(st, ts, pl, lim):
    """response_item message: user parts (filtered), assistant text (commentary or final)."""
    role = pl.get("role")
    parts = [c for c in pl.get("content") or [] if isinstance(c, dict)]
    if role == "user":
        for c in parts:
            if c.get("type") != "input_text" or not c.get("text"):
                continue
            got = codex_user_part(c["text"], lim)
            if not got:
                continue
            label, text = got
            if label == "USER" and st.get("spawned") and not st.get("task_done"):
                label = "TASK (from parent)"
                st["task_done"] = True
            limit = lim["subagent_result"] if label == "SUBAGENT RESULT" else lim["user_text"]
            heading(st, label, ts, text, limit)
    elif role == "assistant":
        text = "\n".join(c.get("text", "") for c in parts if c.get("text"))
        if not text.strip():
            return
        final = pl.get("phase") == "final_answer"
        st["agent_texts"].append(text)
        heading(st, "AGENT (final)" if final else "AGENT", ts, text,
                lim["agent_final"] if final else lim["agent_commentary"])


def codex_interagent(st, ts, pl, lim):
    """Plaintext FINAL_ANSWER bodies of inter-agent messages (encrypted ones are dropped)."""
    texts = [c.get("text", "") for c in pl.get("content") or [] if isinstance(c, dict) and c.get("type") == "input_text"]
    header = "\n".join(texts)
    if "Message Type: FINAL_ANSWER" not in header:
        return
    body = header.split("Payload:\n", 1)[1] if "Payload:\n" in header else ""
    heading(st, "SUBAGENT RESULT", ts, body, lim["subagent_result"])


def payload_hashes(path):
    """sha1 of canonical payloads longer than 40 bytes, for the fork-without-start dedupe."""
    out = set()
    for _, rec in walk_jsonl(path):
        pl = rec.get("payload")
        if pl is None:
            continue
        s = json.dumps(pl, sort_keys=True)
        if len(s.encode("utf-8")) > 40:
            out.add(hashlib.sha1(s.encode("utf-8")).hexdigest())
    return out


def codex_record(st, typ, pl, ts, lim):
    """Dispatch one non-inherited Codex record (docs/02: what to keep / what to scan)."""
    if typ == "response_item":
        pt = pl.get("type")
        if pt == "message":
            codex_message(st, ts, pl, lim)
        elif pt == "agent_message":
            codex_interagent(st, ts, pl, lim)
        elif pt == "function_call":
            codex_call_bullets(st, ts, pl.get("name") or "", pl.get("arguments"), lim)
        elif pt == "custom_tool_call":
            raw = pl.get("input") or ""
            raw = raw if isinstance(raw, str) else json.dumps(raw)
            codex_custom_bullets(st, ts, pl.get("name") or "", raw, lim)
        elif pt in ("custom_tool_call_output", "function_call_output"):
            scan_paths(text_of(pl.get("output")), st["rx"], st["hits"])
    elif typ == "event_msg":
        pt = pl.get("type")
        if pt == "item_completed":
            item = pl.get("item") or {}
            if item.get("type") == "CommandExecution":
                scan_paths(item.get("aggregated_output"), st["rx"], st["hits"])
                scan_paths(item.get("cwd"), st["rx"], st["hits"])
            elif item.get("type") in ("FileChange", "ImageView"):
                scan_obj(item, st["rx"], st["hits"])
        elif pt == "patch_apply_end":
            scan_obj(pl, st["rx"], st["hits"])
    elif typ == "compacted":
        msg = pl.get("message") or ""
        head = msg[:200]
        dup = any(head in t or (len(t) >= 200 and t[:200] in msg) for t in st["agent_texts"])
        if head and not dup:
            heading(st, "COMPACTION SUMMARY", ts, msg, lim["agent_final"])


def codex_condense(path, kind, parent_path, first_meta, rx, rx_proj, lim, body_path):
    """Stream one Codex rollout into body_path. Returns the parse state (hits, dates, counts)."""
    st = new_state(rx, rx_proj, body_path, lim)
    st.update(cwd=first_meta.get("cwd"), cli=first_meta.get("cli_version"),
              spawned=kind == "subagent", task_done=False)
    start_ord = first_meta.get("subagent_history_start_ordinal") if kind == "fork" else None
    parent_hashes = None
    if kind == "fork" and start_ord is None:
        parent_hashes = payload_hashes(parent_path) if parent_path else set()
    try:
        for _, rec in walk_jsonl(path):
            if start_ord is not None and isinstance(rec.get("ordinal"), int) and rec["ordinal"] < start_ord:
                continue
            pl = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
            if parent_hashes is not None and len(json.dumps(pl, sort_keys=True).encode("utf-8")) > 40:
                if hashlib.sha1(json.dumps(pl, sort_keys=True).encode("utf-8")).hexdigest() in parent_hashes:
                    continue
            ts = parse_ts(rec.get("timestamp"))
            note_ts(st, ts)
            codex_record(st, rec.get("type"), pl, ts, lim)
    finally:
        st["fh"].close()
    return st


def discover(cfg, paths=None):
    """Non-guardian rollouts as candidates. paths: rollout files already listed (default: list the folder)."""
    if "codex_sessions" not in cfg["sources"]:
        return [], 0
    if paths is None:
        paths = discover_codex(cfg)[0]
    cands, guardians = [], 0
    for p in paths:
        meta = codex_meta(p)
        if not meta:
            continue
        kind = codex_class(meta)
        if kind == "guardian":
            guardians += 1
            continue
        cid = meta.get("id") or p.name[:-len(".jsonl")][-36:]
        cands.append({"source": NAME, "kind": kind, "id": cid, "short": cid[:13], "path": p,
                      "parent_id": meta.get("parent_thread_id") or meta.get("forked_from_id"),
                      "cwd": meta.get("cwd"), "meta": meta})
    return cands, guardians


def prepare(cfg, ctx):
    """Rollout ids (fork parents) and session_index thread names, read before parsing."""
    src = cfg["sources"]
    ctx["codex_by_id"] = discover_codex(cfg)[1] if "codex_sessions" in src else {}
    ctx["codex_names"] = codex_session_index(src["codex_session_index"]) if "codex_session_index" in src else {}


def condense(c, ctx, body_path):
    """Parse one rollout into body_path; a fork's parent (found by id) is used for the dedupe."""
    parent = ctx["codex_by_id"].get(c["parent_id"]) if c["kind"] == "fork" else None
    return codex_condense(c["path"], c["kind"], parent, c["meta"], ctx["rx"], ctx["rx_proj"], ctx["lim"],
                          body_path)


def title(c, st, ctx):
    """Latest session_index thread_name; spawned subagents without one are named by agent path/nickname."""
    t = ctx["codex_names"].get(c["id"])
    if not t and c["kind"] != "root":
        # Spawned Codex subagents often get their task encrypted; name them by agent path/nickname.
        sub = (c["meta"].get("source") or {}).get("subagent") if isinstance(c["meta"].get("source"), dict) else None
        spawn = sub.get("thread_spawn", {}) if isinstance(sub, dict) else {}
        who = c["meta"].get("agent_path") or spawn.get("agent_path") or ""
        nick = c["meta"].get("agent_nickname") or spawn.get("agent_nickname") or ""
        if who or nick:
            t = "subagent " + " ".join(x for x in (who, f"({nick})" if nick else "") if x)
    return t
