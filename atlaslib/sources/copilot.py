"""GitHub Copilot transcript source for ResearchAtlas (docs/transcript-formats.md, "GitHub Copilot history").

Inputs, configured under [sources.copilot]:
  chat_dirs       VS Code Chat panel op logs, <dir>/<uuid>.jsonl            kind "chat"
  chat_storage    synced PC workspaceStorage mirror, <hash>/chatSessions/  kind "chat"
  agent_state     Copilot agent state, <dir>/<uuid>/events.jsonl           kind "agent"
  vscode_storage  VS Code Server workspaceStorage,
                  <dir>/<hash>/GitHub.copilot-chat/transcripts/<uuid>.jsonl  kind "transcript"
                  (cwd from <hash>/workspace.json, else the workspace_cwd map {hash: folder})

Condensed text uses the same headings and bullets as the Codex and Claude sources (atlaslib.core helpers).
Stdlib only. A subagent's own activity is never rendered as main-agent text: its paths are harvested, and its
report is the subagent's result (A: toolCallResults; B: the task result, or the subagent's final message at
subagent.completed).
"""

import json
import os
import re
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

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

NAME = "copilot"
FS_TIMEOUT_S = 10  # hard NFS mounts can hang; every discovery-time filesystem call is guarded
KIND_RANK = {"chat": 0, "agent": 1, "transcript": 2}  # duplicate ids: chat (A) beats agent (B) beats transcript (C)

# Tool names -> one canonical tool. Chat (A) uses VS Code toolIds (copilot_*); agent/transcript (B/C) use CLI names.
CANON = {
    "copilot_readFile": "read_file",
    "read_file": "read_file",
    "view": "read_file",
    "copilot_listDirectory": "list_dir",
    "list_dir": "list_dir",
    "copilot_findTextInFiles": "grep",
    "grep_search": "grep",
    "grep": "grep",
    "rg": "grep",
    "copilot_findFiles": "find",
    "file_search": "find",
    "glob": "find",
    "copilot_editNotebook": "edit",
    "edit_notebook_file": "edit",
    "copilot_replaceString": "edit",
    "replace_string_in_file": "edit",
    "edit": "edit",
    "copilot_multiReplaceString": "multi_edit",
    "multi_replace_string_in_file": "multi_edit",
    "copilot_applyPatch": "apply_patch",
    "apply_patch": "apply_patch",
    "copilot_createFile": "create",
    "create_file": "create",
    "create": "create",
    "run_in_terminal": "terminal",
    "bash": "terminal",
    "runSubagent": "agent",
    "execution_subagent": "agent",
    "search_subagent": "agent",
    "task": "agent",
    "ask_user": "ask",
}
# No bullet: bookkeeping, polling and memory tools (docs/transcript-formats.md: Noise). read_agent only polls a
# subagent; its report comes from the subagent's completion (see event_record).
SILENT_TOOLS = {
    "manage_todo_list",
    "tool_search",
    "task_complete",
    "get_terminal_output",
    "kill_terminal",
    "read_bash",
    "read_agent",
    "copilot_memory",
    "memory",
}
# Subagent results that only say the agent was started. The report comes later, from subagent.completed (B).
BOILERPLATE_PREFIXES = ("Agent started in background",)
PATCH_FILE_RE = re.compile(r'\*\*\* (Add|Update|Delete) File: ([^\s"\'`\\]+)')


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def _guarded(fn, *args):
    """Run one filesystem call in a daemon thread with FS_TIMEOUT_S. None on timeout or error."""
    box = {}

    def run():
        try:
            box["v"] = fn(*args)
        except Exception as e:  # missing file, permission, NFS error: skip this item
            box["e"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(FS_TIMEOUT_S)
    if th.is_alive():
        print(f"warning: copilot: filesystem call timed out: {args[0] if args else fn}", file=sys.stderr)
        return None
    return box.get("v")


def _list_files(root, pattern):
    return sorted(p for p in Path(root).glob(pattern) if p.is_file())


def _list_dirs(root):
    return sorted(p for p in Path(root).iterdir() if p.is_dir())


def _read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _head_records(path, n=30):
    """First n parseable records of a JSONL file (session.start is always near the top)."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _ in range(n):
            line = fh.readline()
            if not line:
                break
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _session_start(path):
    """(cwd, cli) from the first session.start record of an events file; (None, None) if absent."""
    for rec in _head_records(path):
        if rec.get("type") == "session.start":
            data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
            ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
            cwd = ctx.get("cwd") if isinstance(ctx.get("cwd"), str) else None
            prod, ver = data.get("producer"), data.get("copilotVersion")
            cli = " ".join(str(x) for x in (prod, ver) if x) or None
            return cwd, cli
    return None, None


def _folder_path(folder):
    """Filesystem path of a workspace.json 'folder' URI (vscode-remote://host%2B.../path or file:///path)."""
    if not isinstance(folder, str) or not folder:
        return None
    return unquote(urlsplit(folder).path) or None


def _yaml_value(path, key):
    """Value of a top-level 'key: value' line in a small YAML file (outer quotes stripped); None if absent."""
    text = _guarded(_read_text, path)
    for line in (text or "").splitlines():
        if line.startswith(key + ":"):
            v = line[len(key) + 1 :].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            return v or None
    return None


def _cand(kind, path, cid, cwd, meta, st):
    return {
        "source": "copilot",
        "kind": kind,
        "id": cid,
        "short": cid[:8],
        "path": path,
        "parent_id": None,
        "cwd": cwd,
        "meta": meta,
        "size": st.st_size,
        "mtime": st.st_mtime,
        "key": ("copilot", cid),
    }


def _chat_cands(entry):
    root = entry.get("path")
    if not root:
        return []
    out = []
    for f in _guarded(_list_files, root, "*.jsonl") or []:
        st = _guarded(os.stat, f)
        if st is not None:
            out.append(_cand("chat", f, f.stem, entry.get("cwd"), {}, st))
    return out


def _agent_cands(root):
    if not root:
        return []
    out = []
    for d in _guarded(_list_dirs, root) or []:
        ev = d / "events.jsonl"
        st = _guarded(os.stat, ev)
        if st is None:
            continue
        cwd, cli = _guarded(_session_start, ev) or (None, None)
        out.append(_cand("agent", ev, d.name, cwd, {"cli_version": cli} if cli else {}, st))
    return out


def _chat_storage_cands(root):
    if not root:
        return []
    out = []
    for hd in _guarded(_list_dirs, root) or []:
        ws = _guarded(read_json, hd / "workspace.json")
        cwd = _folder_path(ws.get("folder")) if isinstance(ws, dict) else None
        if not cwd:
            print(f"warning: copilot: skipping mirror without workspace folder: {hd}", file=sys.stderr)
            continue
        for cand in _chat_cands({"path": hd / "chatSessions", "cwd": cwd}):
            cand["synced"] = True
            out.append(cand)
    return out


def _transcript_cands(root, workspace_cwd=None):
    """workspace_cwd maps a workspace hash to its folder, for hashes without a workspace.json (the server has none)."""
    if not root:
        return []
    out = []
    for hd in _guarded(_list_dirs, root) or []:
        tdir = hd / "GitHub.copilot-chat" / "transcripts"
        ws = _guarded(read_json, hd / "workspace.json")
        ws_cwd = _folder_path(ws.get("folder")) if isinstance(ws, dict) else None
        ws_cwd = ws_cwd or (workspace_cwd or {}).get(re.sub(r"-\d+$", "", hd.name))
        for f in _guarded(_list_files, tdir, "*.jsonl") or []:
            st = _guarded(os.stat, f)
            if st is None:
                continue
            start_cwd, cli = _guarded(_session_start, f) or (None, None)
            meta = {"workspace_hash": hd.name}
            if cli:
                meta["cli_version"] = cli
            out.append(_cand("transcript", f, f.stem, ws_cwd or start_cwd, meta, st))
    return out


def discover(cfg, paths=None):
    """Candidates from the configured Copilot sources, one per id. Returns (cands, skipped).

    Synced chat copies beat old manual chat imports, even after a log is rewritten smaller.
    Otherwise skipped counts lower-ranked sources or smaller copies of the same kind.
    Ids that collide on their first 8 chars (with different ids) use 13 chars for both.
    """
    sources = cfg.get("sources") if isinstance(cfg, dict) else None
    scfg = sources.get("copilot") if isinstance(sources, dict) else None
    if not isinstance(scfg, dict):
        return [], 0
    cands = []
    for entry in scfg.get("chat_dirs") or []:
        if isinstance(entry, dict):
            cands += _chat_cands(entry)
    cands += _chat_storage_cands(scfg.get("chat_storage"))
    cands += _agent_cands(scfg.get("agent_state"))
    cands += _transcript_cands(scfg.get("vscode_storage"), scfg.get("workspace_cwd"))

    best, skipped = {}, 0
    for c in sorted(
        cands, key=lambda c: (KIND_RANK[c["kind"]], not c.get("synced", False), -c["size"], str(c["path"]))
    ):
        if c["id"] in best:
            skipped += 1
        else:
            best[c["id"]] = c
    kept = sorted(best.values(), key=lambda c: (KIND_RANK[c["kind"]], c["id"]))
    ids8 = {}
    for c in kept:
        ids8.setdefault(c["short"], set()).add(c["id"])
    for c in kept:
        if len(ids8[c["short"]]) > 1:
            c["short"] = c["id"][:13]
    for short, ids in sorted(ids8.items()):
        if len(ids) > 1:
            print(
                f"warning: copilot: ids share prefix {short}: {', '.join(sorted(ids))}; using 13 chars", file=sys.stderr
            )
    return kept, skipped


def prepare(cfg, ctx):
    """No setup needed for Copilot sources."""
    return None


# ---------------------------------------------------------------------------
# chat (kind "chat"): replay of the VS Code op log
# ---------------------------------------------------------------------------


def _child(cur, key, make):
    """cur[key] as a container, created with make() where the slot is missing. None if cur cannot hold key."""
    if isinstance(key, int):
        if not isinstance(cur, list) or key < 0:
            return None
        while len(cur) <= key:
            cur.append(None)
        if not isinstance(cur[key], (dict, list)):
            cur[key] = make()
        return cur[key]
    if not isinstance(cur, dict):
        return None
    if not isinstance(cur.get(key), (dict, list)):
        cur[key] = make()
    return cur[key]


def _parent(root, path):
    """Container holding path[-1], creating missing intermediate levels. None if unreachable."""
    cur = root
    for key, nxt in zip(path[:-1], path[1:], strict=True):
        cur = _child(cur, key, list if isinstance(nxt, int) else dict)
        if cur is None:
            return None
    return cur


def _set(root, path, value):
    parent, last = _parent(root, path), path[-1]
    if isinstance(last, int):
        if not isinstance(parent, list) or last < 0:
            return False
        while len(parent) <= last:
            parent.append(None)
        parent[last] = value
        return True
    if not isinstance(parent, dict):
        return False
    parent[last] = value
    return True


def _extend(root, path, items, idx):
    """kind 2: truncate the list at path to idx (when given), then append items. A missing or null slot becomes []."""
    parent, last = _parent(root, path), path[-1]
    if isinstance(last, int) and isinstance(parent, list) and last >= 0:
        while len(parent) <= last:
            parent.append(None)
        if parent[last] is None:
            parent[last] = []
        lst = parent[last]
    elif isinstance(last, str) and isinstance(parent, dict):
        if parent.get(last) is None:
            parent[last] = []
        lst = parent[last]
    else:
        return False
    if not isinstance(lst, list):
        return False
    if isinstance(idx, int) and idx >= 0:
        del lst[idx:]
    lst.extend(items)
    return True


def replay_oplog(path):
    """Replay a chatSessions op log into its final snapshot. Returns (state or None, n_bad_ops).

    kind 0 = full snapshot; kind 1 = set v at key path k; kind 2 = truncate the list at k to i (if given) and
    extend it with v (null v = truncate only). Missing dict/list levels are created, so a set into an absent parent
    recovers. An op that still cannot be applied is counted and skipped: a line that is not JSON, an op before any
    snapshot (state is still None), a list op on a non-list. A file with no snapshot returns (None, n_ops).
    """
    state, bad = None, 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                op = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if not isinstance(op, dict):
                bad += 1
                continue
            kind, k, v = op.get("kind"), op.get("k"), op.get("v")
            if kind == 0 and isinstance(v, dict):
                state = v
                continue
            ok = False
            if state is not None and isinstance(k, list) and k:
                if kind == 1:
                    ok = _set(state, k, v)
                elif kind == 2 and (v is None or isinstance(v, list)):
                    ok = _extend(state, k, v or [], op.get("i"))  # v null = truncate only (e.g. pendingRequests)
            if not ok:
                bad += 1
    return state, bad


def _ms_ts(ms):
    """Epoch milliseconds to an aware UTC datetime, or None."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def uri_path(u):
    """Absolute filesystem path of a VS Code URI (dict with path, or a file:/vscode- string); None otherwise."""
    if isinstance(u, dict):
        p = u.get("path")
    elif isinstance(u, str):
        p = unquote(urlsplit(u).path) if u.startswith(("file:", "vscode-")) else u
    else:
        return None
    return p if isinstance(p, str) and p.startswith("/") else None


def first_str(a, *keys):
    for k in keys:
        v = a.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def parse_args(raw):
    """Tool arguments as a dict. A JSON object string is parsed; other text is kept as {'_raw': text}."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return v if isinstance(v, dict) else {"_raw": raw}
    return {}


def text_leaves(obj, out):
    """Collect the 'text' / 'value' string leaves of a nested tool result (prompt-tsx trees)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("text", "value") and isinstance(v, str):
                out.append(v)
            elif isinstance(v, (dict, list)):
                text_leaves(v, out)
    elif isinstance(obj, list):
        for v in obj:
            text_leaves(v, out)
    return out


def tool_lines(canon, name, a, lim):
    """Bullet texts for one tool call. canon is the CANON name; name is the raw label for unknown tools."""
    if name in SILENT_TOOLS or canon in SILENT_TOOLS:
        return []
    lim_in = lim["tool_input"]
    if canon == "terminal":
        cmd = first_str(a, "command")
        return [cmd_line(cmd, None, lim)] if cmd else [f"tool: {name}"]
    if canon == "read_file":
        p = first_str(a, "filePath", "path")
        return [f"Read {p}"] if p else [f"tool: {name}"]
    if canon == "list_dir":
        p = first_str(a, "path", "dirPath")
        return [f"List {p}"] if p else [f"tool: {name}"]
    if canon in ("grep", "find"):
        q = first_str(a, "query", "pattern")
        return [f"Search {truncate(collapse_ws(q), lim_in)}"] if q else [f"tool: {name}"]
    if canon == "edit":
        p = first_str(a, "filePath", "path")
        return [f"Edit {p}"] if p else [f"tool: {name}"]
    if canon == "create":
        p = first_str(a, "filePath", "path")
        return [f"Write {p}"] if p else [f"tool: {name}"]
    if canon == "multi_edit":
        paths = []
        for r in a.get("replacements") or []:
            if isinstance(r, dict) and isinstance(r.get("filePath"), str) and r["filePath"] not in paths:
                paths.append(r["filePath"])
        return [f"Edit {p}" for p in paths] or [f"tool: {name}"]
    if canon == "apply_patch":
        text = first_str(a, "input", "_raw") or ""
        lines = [f"{'Write' if op == 'Add' else 'Edit'} {target}" for op, target in PATCH_FILE_RE.findall(text)]
        return lines or [f"tool: {name}"]
    if canon == "agent":
        desc = collapse_ws(first_str(a, "description") or "")
        prompt = truncate(collapse_ws(first_str(a, "prompt", "query") or ""), lim_in)
        return [f"Agent: {desc}" + (f" — {prompt}" if prompt else "")]
    if canon == "ask":
        msg = truncate(collapse_ws(first_str(a, "message", "question") or ""), lim_in)
        return [f"ask_user: {msg}" if msg else f"tool: {name}"]
    return [f"tool: {name}"]


def _emit_turn(st, events, lim):
    """Write one turn's events in order. The last text event of the turn is AGENT (final); others AGENT."""
    last = max((i for i, e in enumerate(events) if e[0] == "text"), default=None)
    for i, (kind, ts, val) in enumerate(events):
        if kind == "text":
            final = i == last
            heading(
                st,
                "AGENT (final)" if final else "AGENT",
                ts,
                val,
                lim["agent_final"] if final else lim["agent_commentary"],
            )
        elif kind == "bullet":
            bullet(st, ts, val)
        elif kind == "report":
            heading(st, "SUBAGENT REPORT", ts, val, lim["subagent_result"])
        elif kind == "recap":
            heading(st, "RECAP", ts, val, lim["agent_final"])


def _attached_paths(vd):
    """Explicit file and folder attachments of a request (not instruction files, images, or the implicit editor)."""
    out = []
    for v in (vd.get("variables") or []) if isinstance(vd, dict) else []:
        if not isinstance(v, dict) or v.get("kind") not in ("file", "directory"):
            continue
        if str(v.get("id") or "").startswith("vscode.implicit"):
            continue
        val = v.get("value")
        p = uri_path(val.get("uri", val)) if isinstance(val, dict) else None
        if p and p not in out:
            out.append(p)
    return out


def part_message(part):
    """Text of a tool part's past-tense (else invocation) message, or ''."""
    for field in ("pastTenseMessage", "invocationMessage"):
        msg = part.get(field)
        if isinstance(msg, dict) and isinstance(msg.get("value"), str):
            return msg["value"]
    return ""


MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~<>])")


def md_unescape(obj):
    """Undo markdown backslash escapes in every string of obj. Tool messages escape '_' ('demo\\_project'),
    which would cut paths at the backslash."""
    if isinstance(obj, str):
        return MD_ESCAPE_RE.sub(r"\1", obj)
    if isinstance(obj, dict):
        return {k: md_unescape(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [md_unescape(v) for v in obj]
    return obj


def backtick_query(part):
    """Search query from the message ('Searched for regex `QUERY` (`GLOB`), 3 results'), used when args are absent."""
    m = re.search(r"`([^`]+)`", md_unescape(part_message(part)))
    return m.group(1) if m else None


def part_uri_paths(part):
    """Paths of the URIs on a tool part's invocation/past-tense message (keys or values)."""
    out = []
    for field in ("invocationMessage", "pastTenseMessage"):
        msg = part.get(field)
        uris = msg.get("uris") if isinstance(msg, dict) else None
        if not isinstance(uris, dict):
            continue
        for key, val in uris.items():
            for p in (uri_path(key), uri_path(val)):
                if p and p not in out:
                    out.append(p)
    return out


def inline_text(part):
    """Text of an inlineReference part: a code symbol's name (as the Chat panel shows it), else its file path or name.

    A symbol reference ({name, kind, location}) must not become its location path: that path is often a library file
    (e.g. json.load -> /usr/lib/python3.8/json/__init__.py) and would corrupt the prose. Its path is harvested
    separately.
    """
    ref = part.get("inlineReference")
    if not isinstance(ref, dict):
        return ""
    name = ref.get("name")
    if isinstance(ref.get("location"), dict) and isinstance(name, str) and name:
        return name
    for u in (ref, ref.get("uri")):
        p = uri_path(u)
        if p:
            return p
    return name if isinstance(name, str) else ""


def base_id(tool_call_id):
    """Chat tool call ids carry a '__vscode-<ms>' suffix in toolCallRounds/toolCallResults but not on the parts."""
    return tool_call_id.split("__", 1)[0] if isinstance(tool_call_id, str) else None


def chat_tool_events(part, calls, results, ts, lim, events):
    """Events for one toolInvocationSerialized part, args taken from toolCallRounds by toolCallId."""
    tid = part.get("toolId") if isinstance(part.get("toolId"), str) else ""
    tcid = part.get("toolCallId")
    call = calls.get(base_id(tcid), {}) if isinstance(tcid, str) else {}
    cname = call.get("name") if isinstance(call.get("name"), str) else ""
    canon = CANON.get(tid) or CANON.get(cname) or tid or cname
    name = tid or cname or "unknown"
    a = parse_args(call.get("arguments"))
    tsd = part.get("toolSpecificData")
    if canon == "terminal" and isinstance(tsd, dict) and isinstance(tsd.get("commandLine"), dict):
        original = tsd["commandLine"].get("original")
        if isinstance(original, str) and original.strip():
            a = dict(a, command=original)
    uris = part_uri_paths(part)
    if canon in ("read_file", "list_dir", "edit", "create") and not first_str(a, "filePath", "path") and uris:
        a = dict(a, filePath=uris[0], path=uris[0])
    if canon in ("grep", "find") and not first_str(a, "query", "pattern"):
        q = backtick_query(part)
        if q:
            a = dict(a, query=q)
    if canon == "apply_patch" and not first_str(a, "input", "_raw") and uris:
        # No patch text kept: the message only names the files it touched.
        lines = [f"Edit {p}" for p in uris]
        events.extend(("bullet", ts, line) for line in lines)
        return
    for line in tool_lines(canon, name, a, lim):
        events.append(("bullet", ts, line))
    if canon == "agent" and isinstance(tcid, str):
        report = "\n".join(text_leaves(results.get(base_id(tcid)) or {}, [])).strip()
        if report:
            events.append(("report", ts, report))


def chat_request(st, req, lim):
    """One chat request: USER (unless system-initiated), then its response as text runs, bullets and reports."""
    ts = _ms_ts(req.get("timestamp"))
    note_ts(st, ts)
    msg = req.get("message") if isinstance(req.get("message"), dict) else {}
    text = msg.get("text") if isinstance(msg.get("text"), str) else ""
    result = req.get("result") if isinstance(req.get("result"), dict) else {}
    md = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    vd = req.get("variableData")
    scan_obj(vd, st["rx"], st["hits"])
    scan_obj(req.get("editedFileEvents"), st["rx"], st["hits"])

    if req.get("isSystemInitiated") or req.get("hiddenFromTranscript"):
        scan_paths(text, st["rx"], st["hits"])
    else:
        files = _attached_paths(vd)
        attached = "[attached: " + ", ".join(files) + "]" if files else ""
        body = text + ("\n\n" if text.strip() and files else "") + attached
        heading(st, "USER", ts, body, lim["user_text"])

    calls = {}
    for rnd in md.get("toolCallRounds") or []:
        for tc in (rnd.get("toolCalls") or []) if isinstance(rnd, dict) else []:
            if isinstance(tc, dict) and isinstance(tc.get("id"), str):
                calls[base_id(tc["id"])] = tc
                scan_obj(parse_args(tc.get("arguments")), st["rx"], st["hits"])
    raw_results = md.get("toolCallResults") if isinstance(md.get("toolCallResults"), dict) else {}
    results = {base_id(k): v for k, v in raw_results.items()}
    scan_obj(results, st["rx"], st["hits"])

    events, run = [], []
    for part in req.get("response") if isinstance(req.get("response"), list) else []:
        if not isinstance(part, dict) or part.get("kind") == "thinking":
            continue
        kind = part.get("kind")
        if kind is None:  # markdown; its text is scanned when the run is written, its file links here
            scan_obj(part.get("uris"), st["rx"], st["hits"])
            if isinstance(part.get("value"), str):
                run.append(part["value"])
            continue
        if kind == "inlineReference":
            scan_obj(part.get("inlineReference"), st["rx"], st["hits"])
            run.append(inline_text(part))
            continue
        scan_obj(md_unescape(part), st["rx"], st["hits"])
        if part.get("subAgentInvocationId"):  # a subagent's own tool call: paths only (its text is not shown here)
            continue
        if kind == "toolInvocationSerialized":
            _close_run(events, run, ts)
            chat_tool_events(part, calls, results, ts, lim, events)
        elif kind in ("textEditGroup", "notebookEditGroup"):
            _close_run(events, run, ts)
            p = uri_path(part.get("uri"))
            if p and not _last_bullet_is(events, f"Edit {p}"):
                events.append(("bullet", ts, f"Edit {p}"))
    _close_run(events, run, ts)
    _emit_turn(st, events, lim)


def _close_run(events, run, ts):
    text = "".join(run)
    run.clear()
    if text.strip():
        events.append(("text", ts, text))


def _last_bullet_is(events, line):
    for kind, _, val in reversed(events):
        if kind == "bullet":
            return val == line
    return False


def chat_condense(path, rx, rx_proj, lim, body_path):
    st = new_state(rx, rx_proj, body_path, lim)
    st.update(n_req=0, bad_ops=0)
    try:
        state, bad = replay_oplog(path)
        st["bad_ops"] = bad
        if state is not None:
            note_ts(st, _ms_ts(state.get("creationDate")))
            if isinstance(state.get("customTitle"), str):
                st["title"] = state["customTitle"]
            for req in state.get("requests") if isinstance(state.get("requests"), list) else []:
                if isinstance(req, dict):
                    st["n_req"] += 1
                    chat_request(st, req, lim)
    finally:
        st["fh"].close()
    return st


# ---------------------------------------------------------------------------
# events (kinds "agent" and "transcript"): Copilot agent event log
# ---------------------------------------------------------------------------


def _flush_turn(st, lim):
    events, st["turn"] = st["turn"], []
    _emit_turn(st, events, lim)


def event_record(st, typ, data, ts, lim):
    """Dispatch one events record (docs/transcript-formats.md: Copilot events).

    Subagent-owned records are scanned only.
    """
    sub = bool(data.get("parentToolCallId"))
    if typ == "session.start":
        ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
        if isinstance(ctx.get("cwd"), str):
            st["cwd"] = ctx["cwd"]
        cli = " ".join(str(x) for x in (data.get("producer"), data.get("copilotVersion")) if x)
        st["cli"] = cli or st["cli"]
    elif typ == "user.message":
        content = data.get("content") if isinstance(data.get("content"), str) else ""
        if str(data.get("source") or "").startswith("agent-") or sub:
            # Inter-agent input (a subagent task or follow-up): its content is the tool call that sent it.
            scan_paths(content, st["rx"], st["hits"])
            scan_obj(data.get("attachments"), st["rx"], st["hits"])
            return
        scan_obj(data.get("attachments"), st["rx"], st["hits"])
        _flush_turn(st, lim)
        heading(st, "USER", ts, content, lim["user_text"])
    elif typ == "assistant.message":
        scan_obj(data.get("toolRequests"), st["rx"], st["hits"])
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return
        if sub:  # a subagent's own message: scanned for paths, and kept as its final text for the report
            scan_paths(content, st["rx"], st["hits"])
            st["sub_last"][data["parentToolCallId"]] = content
        else:
            st["turn"].append(("text", ts, content))
    elif typ == "tool.execution_start":
        name = data.get("toolName") if isinstance(data.get("toolName"), str) else ""
        if isinstance(data.get("toolCallId"), str):
            st["tools"][data["toolCallId"]] = name
        if not sub:
            canon = CANON.get(name, name)
            for line in tool_lines(canon, name, parse_args(data.get("arguments")), lim):
                st["turn"].append(("bullet", ts, line))
    elif typ == "tool.execution_complete":
        scan_obj(data.get("result"), st["rx"], st["hits"])
        name = st["tools"].get(data.get("toolCallId"), "")
        res = data.get("result")
        text = res.get("content") if isinstance(res, dict) else res
        text = text.strip() if isinstance(text, str) else ""
        if sub or not text or text.startswith(BOILERPLATE_PREFIXES):
            return
        if CANON.get(name) == "agent":  # foreground subagent: the tool result is the report
            _report(st, ts, text, data.get("toolCallId"))
    elif typ == "subagent.completed":  # background subagent: its final message is the report
        text = st["sub_last"].get(data.get("toolCallId"))
        if text:
            _report(st, ts, text, data.get("toolCallId"))
    elif typ == "session.compaction_complete":
        summary = data.get("summaryContent")
        if data.get("success") and isinstance(summary, str) and summary.strip():
            st["turn"].append(("recap", ts, summary))


def _report(st, ts, text, tcid):
    """One SUBAGENT REPORT per subagent task (by toolCallId), and never the same text twice."""
    if tcid in st["reported"] or text in st["reports"]:
        return
    st["reported"].add(tcid)
    st["reports"].add(text)
    st["turn"].append(("report", ts, text))


def events_condense(path, rx, rx_proj, lim, body_path):
    st = new_state(rx, rx_proj, body_path, lim)
    st.update(turn=[], tools={}, reports=set(), reported=set(), sub_last={})
    try:
        for _, rec in walk_jsonl(path):
            if not isinstance(rec, dict):
                continue
            ts = parse_ts(rec.get("timestamp"))
            note_ts(st, ts)
            data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
            event_record(st, rec.get("type"), data, ts, lim)
        _flush_turn(st, lim)
    finally:
        st["fh"].close()
    return st


# ---------------------------------------------------------------------------
# registry entry points
# ---------------------------------------------------------------------------


def condense(c, ctx, body_path):
    """Condense one Copilot candidate into body_path. Returns the parse state (new_state dict)."""
    rx, rx_proj, lim = ctx["rx"], ctx["rx_proj"], ctx["lim"]
    if c["kind"] == "chat":
        st = chat_condense(c["path"], rx, rx_proj, lim, body_path)
        st["cli"] = "vscode-chat"
    else:
        st = events_condense(c["path"], rx, rx_proj, lim, body_path)
    st["cwd"] = c.get("cwd") or st.get("cwd")
    st["title"] = title(c, st, ctx)
    return st


def title(c, st, ctx):
    """Chat: customTitle from the snapshot. Agent: 'summary:' of the sibling workspace.yaml. Transcript: None."""
    if c["kind"] == "chat":
        return st.get("title")
    if c["kind"] == "agent":
        return _yaml_value(c["path"].parent / "workspace.yaml", "summary")
    return None
