"""Claude Code transcripts: sessions, subagent files, and condensing (docs/02: Transcript parsing rules)."""

from pathlib import Path

from atlaslib.core import (
    bullet,
    cmd_line,
    collapse_ws,
    heading,
    new_state,
    note_ts,
    parse_ts,
    read_json,
    scan_obj,
    scan_paths,
    truncate,
    walk_jsonl,
)

NAME = "claude"
CLAUDE_DROP_PREFIXES = (
    "[Image: ",
    "Base directory for this skill:",
    "<local-command-caveat>",
    "<command-name>",
    "<local-command-stdout>",
)


def claude_flush(st, buf, cwd_default, lim):
    """Emit buffered assistant blocks of one message.id in apiBlockIndex order."""
    items = sorted(buf, key=lambda x: (x[0], x[1]))
    buf.clear()
    for _, _, b, stop, ts, cwd in items:
        btype = b.get("type")
        if btype == "text":
            final = stop == "end_turn"
            heading(
                st,
                "AGENT (final)" if final else "AGENT",
                ts,
                b.get("text") or "",
                lim["agent_final"] if final else lim["agent_commentary"],
            )
        elif btype == "tool_use":
            claude_tool_bullets(st, ts, b.get("name") or "", b.get("input") or {}, cwd or cwd_default, lim)


def claude_tool_bullets(st, ts, name, inp, cwd, lim):
    """Bullets for one Claude tool_use (docs/02: Tool inputs); SubagentHandback becomes a report."""
    if not isinstance(inp, dict):
        inp = {}
    scan_obj(inp, st["rx"], st["hits"])
    if name == "SubagentHandback":
        heading(st, "SUBAGENT REPORT", ts, inp.get("message") or "", None)
    elif name == "Bash":
        if inp.get("command"):
            bullet(st, ts, cmd_line(str(inp["command"]), cwd, lim))
    elif name in ("Read", "Edit", "Write"):
        if inp.get("file_path"):
            bullet(st, ts, f"{name} {inp['file_path']}")
    elif name == "Agent":
        desc = collapse_ws(inp.get("description") or "")
        prompt = truncate(collapse_ws(inp.get("prompt") or ""), lim["tool_input"])
        bullet(st, ts, f"Agent: {desc}" + (f" — {prompt}" if prompt else ""))
    elif name == "SendMessage":
        msg = truncate(collapse_ws(inp.get("message") or ""), lim["tool_input"])
        bullet(st, ts, f"SendMessage to {inp.get('to') or ''}: {msg}")
    else:
        bullet(st, ts, f"tool: {name}")


def claude_user_record(st, rec, subagent, lim):
    """Human prompts, the subagent task, and tool_result scanning (docs/02: Claude what to keep)."""
    msg = rec.get("message") or {}
    c = msg.get("content")
    origin = (rec.get("origin") or {}).get("kind")
    ts = parse_ts(rec.get("timestamp"))
    if isinstance(c, str):
        if origin == "human":
            if not c.lstrip().startswith(CLAUDE_DROP_PREFIXES):
                heading(st, "USER", ts, c, lim["user_text"])
        elif subagent and not st["task_done"] and origin is None and not rec.get("isMeta"):
            st["task_done"] = True
            heading(st, "TASK (from parent)", ts, c, lim["user_text"])
    elif isinstance(c, list):
        for b in c:
            if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                continue
            tc = b.get("content")
            if isinstance(tc, list):
                tc = "\n".join(x.get("text", "") for x in tc if isinstance(x, dict))
            tc = tc if isinstance(tc, str) else ""
            scan_paths(tc, st["rx"], st["hits"])
            tur = rec.get("toolUseResult")
            if isinstance(tur, str):
                scan_paths(tur, st["rx"], st["hits"])
            elif isinstance(tur, dict):
                f = tur.get("file") if isinstance(tur.get("file"), dict) else {}
                for v in (tur.get("stdout"), tur.get("stderr"), f.get("content")):
                    if isinstance(v, str) and v and v not in tc:
                        scan_paths(v, st["rx"], st["hits"])


def claude_condense(path, subagent, rx, rx_proj, lim, body_path):
    """Stream one Claude session or subagent file into body_path. Returns the parse state."""
    st = new_state(rx, rx_proj, body_path, lim)
    st.update(task_done=False)
    buf = []
    buf_id = None
    try:
        for n, rec in walk_jsonl(path):
            if st["cwd"] is None and rec.get("cwd"):
                st["cwd"] = rec["cwd"]
            if st["cli"] is None and rec.get("version"):
                st["cli"] = rec["version"]
            typ = rec.get("type")
            if typ == "assistant":
                msg = rec.get("message") or {}
                if buf and msg.get("id") != buf_id:
                    claude_flush(st, buf, st["cwd"], lim)
                buf_id = msg.get("id")
                ts = parse_ts(rec.get("timestamp"))
                note_ts(st, ts)
                blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
                for b in blocks:
                    if isinstance(b, dict):
                        buf.append((rec.get("apiBlockIndex") or 0, n, b, msg.get("stop_reason"), ts, rec.get("cwd")))
                continue
            claude_flush(st, buf, st["cwd"], lim)
            if typ == "user":
                note_ts(st, parse_ts(rec.get("timestamp")))
                claude_user_record(st, rec, subagent, lim)
            elif typ == "system":
                note_ts(st, parse_ts(rec.get("timestamp")))
                if rec.get("subtype") == "away_summary" and isinstance(rec.get("content"), str):
                    heading(st, "RECAP", parse_ts(rec.get("timestamp")), rec["content"], lim["agent_final"])
            elif typ == "ai-title" and rec.get("aiTitle"):
                st["title"] = rec["aiTitle"]
        claude_flush(st, buf, st["cwd"], lim)
    finally:
        st["fh"].close()
    return st


def claude_first_cwd(path):
    """cwd of the first record that has one (docs/02: session cwd)."""
    for n, rec in walk_jsonl(path):
        if rec.get("cwd"):
            return rec["cwd"]
        if n >= 200:
            break
    return None


def discover(cfg, paths=None):
    """Session files and subagent files under claude_projects. paths is unused (Codex takes a file list)."""
    if "claude_projects" not in cfg["sources"]:
        return [], 0
    cands = []
    root = Path(cfg["sources"]["claude_projects"])
    if root.is_dir():
        for proj in sorted(p for p in root.iterdir() if p.is_dir()):
            for f in sorted(proj.glob("*.jsonl")):
                cands.append(
                    {
                        "source": NAME,
                        "kind": "root",
                        "id": f.stem,
                        "short": f.stem[:8],
                        "path": f,
                        "parent_id": None,
                        "cwd": claude_first_cwd(f),
                        "meta": {},
                    }
                )
            for f in sorted(proj.glob("*/subagents/agent-*.jsonl")):
                aid = f.name[len("agent-") : -len(".jsonl")]
                meta = read_json(f.with_name(f"agent-{aid}.meta.json"))
                parent = meta.get("parentAgentId") or f.parent.parent.name
                cands.append(
                    {
                        "source": NAME,
                        "kind": "subagent",
                        "id": aid,
                        "short": aid[:8],
                        "path": f,
                        "parent_id": parent,
                        "cwd": claude_first_cwd(f),
                        "meta": meta,
                    }
                )
    return cands, 0


def prepare(cfg, ctx):
    """Nothing to read before parsing."""


def condense(c, ctx, body_path):
    """Parse one session or subagent file into body_path."""
    return claude_condense(c["path"], c["kind"] == "subagent", ctx["rx"], ctx["rx_proj"], ctx["lim"], body_path)


def title(c, st, ctx):
    """Last ai-title record in the file."""
    return st["title"]
