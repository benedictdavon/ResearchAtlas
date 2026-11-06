# Transcript formats and parsing rules

Generic, reusable facts about where coding agents store their transcripts, what the records look like, and
which rules `researchatlas extract` implements. Code docstrings refer to the section names below
(e.g. "docs/transcript-formats.md: Transcript parsing rules", "docs/transcript-formats.md: Tool inputs").

These formats are **observed, not documented by the vendors**, and they change between versions. Codex CLI rollouts
from roughly version 0.117 to 0.161 were inspected; shapes differ by version, so the parser relies only on records
present in all of them. When a new version breaks something, add a synthetic test case and amend this file.

## Transcript locations

| Agent | Location | Unit |
|-------|----------|------|
| Codex CLI | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` (default `CODEX_HOME=~/.codex`) | one rollout per session, subagent or fork |
| Codex titles | `$CODEX_HOME/session_index.jsonl` (`id`, `thread_name`, `updated_at`) | one line per rename; ids repeat |
| Claude Code | `~/.claude/projects/<cwd with "/" replaced by "-">/<session-uuid>.jsonl` | one file per session |
| Claude Code subagents | `<projdir>/<session-uuid>/subagents/agent-<agentId>.jsonl` (+ `agent-<agentId>.meta.json`) | one file per subagent |
| GitHub Copilot | several stores; see "GitHub Copilot history" | |

All are JSONL. Files can be large (hundreds of MB for one session, single records up to ~2 MB) and a live
session's file can end in a partial line, so every `json.loads` is wrapped in try/except and malformed lines are
skipped (`atlaslib.core.read_jsonl` / `walk_jsonl`).

## Codex rollout record format

Each line: `{"timestamp", "ordinal", "type", "payload"}`.

- Line 1: `type=session_meta`. Payload keys include `id`, `session_id`, `cwd`, `timestamp`, `forked_from_id`,
  `parent_thread_id`, `agent_nickname`, `agent_path`, `subagent_history_start_ordinal`, `git`, `cli_version`,
  `base_instructions`, `source`. **`base_instructions` is the system prompt; never extract it.**
- Other `type`s:
  - `response_item`, with `payload.type` ∈ `message`, `agent_message`, `reasoning`, `function_call`,
    `function_call_output`, `custom_tool_call`, `custom_tool_call_output`;
  - `event_msg` (`item_completed`, `token_count`, `task_started`, `task_complete`, …);
  - `turn_context`, `compacted` (context-compaction summaries), `world_state`, `token_usage_record`,
    `inter_agent_communication_metadata`.
- `ordinal` is absent in older CLIs and in guardian rollouts. Use file order then.
- The file id is the last 36 characters of the file name before `.jsonl`.

### Other Codex state (not used)

`history.jsonl` (user prompts; they also appear verbatim in rollouts), `state_*.sqlite` (thread table incl.
`rollout_path` and spawn edges), `thread_history_*.sqlite` (a projection of rollouts), `goals_*.sqlite`,
`logs_*.sqlite` (runtime traces) and `memories/` add nothing beyond rollouts plus `session_index.jsonl`.
If they are ever needed, open the SQLite files read-only (`mode=ro`).

## Claude Code record format

- Record `type`s: `user`, `assistant` (with `message.role` and `message.content` blocks: `text`, `tool_use`,
  `tool_result`, `thinking`), plus `attachment`, `system`, `ai-title`, `last-prompt`, `file-history-*`,
  `queue-operation`, `cost-state`, `mode`, `permission-mode`, … Records carry `cwd`, `timestamp` and `version`.
- An assistant message is split into one record per content block, grouped by `message.id` and ordered by
  `apiBlockIndex`. File order is not strictly chronological.
- Subagent `.meta.json` holds `toolUseId`, `spawnDepth` and, at depth 2, `parentAgentId`. Subagent files never
  repeat the parent's history; the parent holds only the hand-back.
- No compaction records were observed. `system` with `subtype=away_summary` is a recap.

## Transcript parsing rules

These are the rules `extract` implements, per source. Kept text goes into condensed markdown; everything kept
**and** every tool output is scanned for paths (see "Extraction and path facts").

### Condensed file format

```
# <source>:<short id> — <title>
- kind: <root|subagent|fork|chat|agent|transcript> · source: <source> · cli: <version or —>
- id: <full id> · parent: <parent id or —>
- cwd: <session cwd>
- start: <ISO UTC> · end: <ISO UTC>
- raw: <raw transcript path> (<size> MB)

### YYYY-MM-DD HH:MM USER
<text>

### YYYY-MM-DD HH:MM AGENT
- `$ <command>` (in <workdir>)
- Edit <path>
```

Section labels: `USER`, `TASK (from parent)`, `GOAL`, `AGENT`, `AGENT (final)`, `SUBAGENT RESULT`,
`SUBAGENT REPORT`, `COMPACTION SUMMARY`, `RECAP`. Tool calls are bullets under the current `AGENT` section.
Markdown headings inside message text are demoted to bold so only `### <ts> <label>` lines are headings. Texts are
truncated per `[limits]` in the config (user text, final answer, commentary, tool input, subagent result).

### Short ids

The first 8 characters of Codex UUIDv7 ids collide (forks spawned in the same second share them). Codex files and
citations use the **first 13 characters** (`0190abcd-1234`; D15). Claude Code uses the first 8 characters of the
session uuid or subagent `agentId`. Copilot uses 8, switching to 13 for both ids when two ids share an 8-char prefix
(`extract` warns).

### Codex session classes

Determined from `session_meta.payload`:

| Class (`kind`) | How to tell | Treatment |
|---|---|---|
| root | no `parent_thread_id`, no `forked_from_id` | extract all non-injected content |
| guardian (approval reviewer) | `source.subagent.other == "guardian"` | **skip entirely**. Its "user" messages are pasted chunks of the parent transcript plus approval-request boilerplate (D16) |
| spawned subagent (`subagent`) | `source.subagent.thread_spawn` or `parent_thread_id`, no `forked_from_id` | extract; it holds **no** parent history. The first non-injected user message is the parent's task, labelled `TASK (from parent)` |
| fork with start ordinal (`fork`) | `forked_from_id` + `subagent_history_start_ordinal` | **skip records with `ordinal < start`** (inherited from the parent) |
| fork without start ordinal (`fork`) | `forked_from_id`, no start ordinal | drop records whose canonical payload hash (sha1 of `json.dumps(payload, sort_keys=True)`, payloads > 40 bytes) occurs in the parent rollout |

- `parent_id` in the index = `parent_thread_id`, else `forked_from_id`.
- The start-ordinal rule applies only when `ordinal` exists.
- Some newer spawned subagents receive their task as an encrypted inter-agent message, so their condensed file
  holds agent text only. Their title falls back to `subagent <agent_path> (<nickname>)`.

### Codex: what to keep

- **User text:** `response_item` `type=message`, `role=user`, per content part (`input_text`). This is a superset of
  `event_msg user_message` / `item_completed UserMessage`, which are ignored as duplicates. Per-part filter:
  - drop parts starting with `# AGENTS.md instructions`, `<environment_context>`, `<turn_aborted>`,
    `<recommended_plugins>`, `<image`, `</image>`;
  - `# Context from my IDE setup:` → keep only the text after `## My request for Codex:`;
  - `<codex_internal_context` → keep only the `<objective>…</objective>` text, labelled `GOAL`;
  - `<subagent_notification>` → keep, labelled `SUBAGENT RESULT`, truncated;
  - `<send_user_message_question_reply>` → keep (the user's answers to the agent's questions);
  - everything else is real user text.
- **Agent text:** `response_item` `type=message`, `role=assistant`; `phase=final_answer` → `AGENT (final)`,
  `phase=commentary` → `AGENT`. Ignore `event_msg agent_message`, `item_completed AgentMessage` and
  `task_complete.last_agent_message` (duplicates).
- **Compaction:** `compacted.payload.message` → `COMPACTION SUMMARY`. Skipped if its first 200 characters already
  appeared in an emitted assistant message (the pre-compaction handoff is often also a final answer).
- **Inter-agent** `response_item type=agent_message`: keep only plaintext `Message Type: FINAL_ANSWER` bodies
  (`SUBAGENT RESULT`, truncated). The others are encrypted.
- **Title:** the latest `thread_name` for the id in `session_index.jsonl` (max `updated_at`); fallback = the first
  user text, ~80 characters.

#### Tool inputs (Codex)

- `custom_tool_call name=exec`: the `input` is JavaScript. Regex out `cmd` and `workdir` per `exec_command({...})`
  call (keys may be quoted or unquoted) and `apply_patch` targets (`*** (Add|Update|Delete) File: <path>`).
- `custom_tool_call name=apply_patch`: target paths.
- `function_call` `exec_command` / `shell` (JSON args `cmd`/`command`, `workdir`): keep the command.
- `spawn_agent` / `send_message` / `followup_task`: keep only `task_name`/`target` and the `message` when it is
  not encrypted (encrypted blobs start with `gAAAAA`).
- `wait`, `wait_agent`, `sleep`, `list_agents`, `close_agent`, `write_stdin`: dropped.

#### Codex: what to drop / what to scan

- **Drop:** `session_meta.base_instructions`, all `developer` messages, `turn_context`, `world_state`, `reasoning`
  (encrypted), `token_count`, `token_usage_record`, `inter_agent_communication_metadata`, `thread_settings_applied`,
  `task_started` / `task_complete`, all `event_msg` / `item_completed`.
- **Scan only:** tool outputs (`*_call_output`, `patch_apply_end`, `CommandExecution.aggregated_output`) are scanned
  for paths and never written to condensed files.

### Claude Code: what to keep

(Code references: "Claude what to keep".)

- **User text:** `type=user`, `message.content` is a string and `origin.kind == "human"`. `isMeta` is **not** a
  usable filter. In subagent files, the first user record with string content, no origin and no `isMeta` is the
  task, labelled `TASK (from parent)`; later meta records there are harness text and are dropped.
- **Dropped user records:** any other origin (e.g. `task-notification`, `peer`: hand-backs whose content the subagent
  file already holds), and human text starting with `[Image: `, `Base directory for this skill:`,
  `<local-command-caveat>`, `<command-name>`, `<local-command-stdout>`.
- **Dropped record types:** `attachment` (incl. injected CLAUDE.md/AGENTS.md as `attachment.type=="instructions"`),
  `queue-operation`, `last-prompt`, `mode`, `permission-mode`, `file-history-*`, `cost-state`, and `system` except
  `away_summary` (kept as `RECAP`).
- **Agent text:** `type=assistant`, grouped by `message.id`. `text` blocks are kept (`AGENT (final)` when the
  message's `stop_reason` is `end_turn`, else `AGENT`); `thinking` is dropped (it is stored empty).
- **Subagent report:** the `SubagentHandback` tool input's `message`, kept in full as `SUBAGENT REPORT`.
- **Scan only:** `tool_result` blocks in user records, plus `toolUseResult` (Bash stdout/stderr, Read
  `file.content`). `originalFile` / `structuredPatch` are skipped.
- **Title:** the last `ai-title` record (`aiTitle`); fallback = the first human prompt. Start/end = min/max timestamp.

#### Tool inputs (Claude Code)

Bash → `command` (with the record's cwd); Read/Edit/Write → `file_path` (never contents); Agent → `description` +
`prompt` (truncated); SendMessage → `to` + `message` (truncated); any other tool → its name only. The full input is
still scanned for paths.

### Session cwd

- Codex: `session_meta.payload.cwd`.
- Claude Code: the `cwd` of the first record that has one (searched in the first ~200 records). Not the project
  folder name, which is lossy (`/` and `-` both become `-`).
- Copilot chat logs: the workspace folder (from `workspace.json`, or the `cwd` configured for a `chat_dirs` entry).
- Copilot agent sessions and server transcripts: `session.start` → `data.context.cwd`; for server transcripts a
  `workspace.json` folder or the configured `workspace_cwd` hash map wins.

## GitHub Copilot history

Copilot keeps history in several places, depending on which client produced it (D22):

| | Location | Producer | Content | Read as (`kind`) |
|---|---|---|---|---|
| A | Client PC: `%APPDATA%\Code\User\workspaceStorage\<hash>\chatSessions\<uuid>.jsonl` (copied to the server, see refresh-guide.md step 0) | VS Code Chat panel | op log (below): prompts, replies, tool args, tool results | `chat` |
| B | `~/.copilot/session-state/<uuid>/events.jsonl` (+ `workspace.yaml`, `session.db`, `checkpoints/`) | Copilot agent runtime (CLI / SDK / VS Code agent host) | event log with tool results | `agent` (only `events.jsonl` is read; the other files may hold credentials) |
| C | `~/.vscode-server/data/User/workspaceStorage/<hash>[-N]/GitHub.copilot-chat/transcripts/<uuid>.jsonl` | VS Code Chat panel (server-side mirror) | B's event schema without tool results (`success` only) | `transcript` |
| D | `~/.vscode-server/data/agentSessionData/<id>/session.db` (+ `attachments/`) | VS Code agent-host UI store | SQLite turns, file edits, terminal outputs | not read (redundant with Codex rollouts or B) |

- `workspace.json` in a workspace-storage folder maps the hash to its folder URI (`file:///path` or
  `vscode-remote://<authority>/path`). The PC side has it; a VS Code Server may not, hence the `workspace_cwd` map.
  The same workspace was observed to have the same hash on client and server.
- On containerised servers `~/.vscode-server` may sit on an ephemeral overlay, so C and D vanish on restart. The
  durable copy of Chat-panel history is A, on the client.
- `chatEditingSessions/` (edit/undo snapshots) and `state.vscdb` next to `chatSessions/` are not needed.
- **Dedup:** one candidate per session UUID. A beats B beats C; within A, a synced mirror (`chat_storage`) beats a
  manual import (`chat_dirs`), then the largest file wins (D22, D24).

### Chat op log (A)

`chatSessions/<uuid>.jsonl` is an operation log that must be replayed:

- `kind:0`: full snapshot `v` (`sessionId`, `creationDate` (ms), `customTitle?`, `requests[]`, …);
- `kind:1`: set `v` at key path `k`;
- `kind:2`: optionally truncate the list at `k` to index `i`, then append the list `v` (no `v` = truncate only).

Replay is tolerant: missing intermediate containers are created; bad ops are counted and skipped. A log without a
snapshot yields no content.

Each request has `message.text`, `timestamp` (ms), `modelId`, `variableData` (attachments), `editedFileEvents`,
`result.metadata` and `response[]` parts:

- markdown parts (no `kind`, text in `value`) and `inlineReference` parts form the reply text. An inline reference
  to a code *symbol* (`{name, kind, location}`) is rendered as its name; its location is only path-scanned (it often
  points into a library and would corrupt the prose).
- `toolInvocationSerialized` (`toolId`, `toolCallId`, `invocationMessage` / `pastTenseMessage`,
  `toolSpecificData`) → a tool bullet. Tool messages escape markdown (`demo\_project`), so their strings are
  unescaped before path scanning.
- `textEditGroup` / `notebookEditGroup` → `Edit <path>` bullet.
- `thinking` → dropped.
- A part with `subAgentInvocationId` is a subagent's own call: path-scanned only.
- **Tool arguments** are in `result.metadata.toolCallRounds[].toolCalls[]` (JSON strings); **tool results** are in
  `result.metadata.toolCallResults` (`{toolCallId: prompt-tsx node tree}`, text in `text`/`value` leaves), not on the
  parts. Ids there carry a `__vscode-<ms>` suffix that the parts' `toolCallId` lacks. Results are path-scanned only,
  except subagent results, which become `SUBAGENT REPORT`.
- Parts have no timestamps; every section of a request carries the request's timestamp.
- Requests with `isSystemInitiated` or `hiddenFromTranscript` (e.g. terminal notifications) get no `USER` heading.
- Title: `customTitle` from the snapshot.

### Copilot events

Agent sessions (B) and server transcripts (C) are event logs: `{type, id, parentId, timestamp, data}`.

| `type` | Handling |
|---|---|
| `session.start` | `data.context.cwd`; `producer` + `copilotVersion` as the cli field |
| `user.message` | `content` → `USER`. `source: agent-…` (inter-agent input) and subagent-owned records are path-scanned only |
| `assistant.message` | `content` → agent text; `toolRequests` scanned |
| `tool.execution_start` | `toolName` + `arguments` → tool bullet |
| `tool.execution_complete` | `result` scanned (B only; C stores no results). A foreground subagent's result → `SUBAGENT REPORT` |
| `subagent.completed` | a background subagent's last message → `SUBAGENT REPORT` |
| `session.compaction_complete` | `summaryContent` (when `success`) → `RECAP` |
| everything else (hooks, permissions, usage, …) | ignored |

- Records with `data.parentToolCallId` belong to a subagent: path-scanned only, never shown as main-agent text.
- One `SUBAGENT REPORT` per subagent task, never the same text twice. "Agent started in background" boilerplate
  results are ignored.
- The last text of each turn is `AGENT (final)`.
- Title: `summary:` from the sibling `workspace.yaml`; some versions write only `name:` (the first prompt), so the
  title then falls back to the first user text.

### Copilot tool names

Chat logs use VS Code tool ids (`copilot_readFile`, `copilot_findTextInFiles`, `run_in_terminal`, …); event logs
use CLI names (`view`, `grep`, `bash`, `task`, …). Both map onto one canonical set (read_file, list_dir, grep, find,
edit, multi_edit, apply_patch, create, terminal, agent, ask) so bullets look the same.

#### Noise

No bullet for bookkeeping, polling and memory tools: `manage_todo_list`, `tool_search`, `task_complete`,
`get_terminal_output`, `kill_terminal`, `read_bash`, `read_agent` (only polls a subagent; the report comes from its
completion), `copilot_memory`, `memory`.

## Extraction and path facts

### Selection

A session is selected when (D16, D20):
1. its cwd is under a `[project].roots` or `[project].cwd_also` prefix (by cwd), or
2. it is a subagent/fork of a selected session (by parent), or
3. its condensed (non-injected) text mentions a `[project].roots` path (by mention; a raw-byte prefilter skips
   files that cannot match).

Sessions whose cwd is under `[project].exclude_cwd` (e.g. the atlas's own folder) or whose id starts with an
`[project].exclude_ids` entry are never selected, and neither are their subagents/forks. Codex guardians are
always skipped. Mentions inside configuration or permission dumps are not part of the condensed text and do not
select a session.

### Path harvesting

- Every kept text, every tool input and every tool output is scanned for absolute paths under `[paths].roots`.
- A path ends at whitespace, quotes, backticks, `<>|,;:{}[]*?$` and backslash.
- Parentheses: a `(…)` group is part of the path (`case_1x1(a).yaml`); a `)` without its `(` inside the path ends it
  (D21).
- Recording-style folder names `YYYY-MM-DD HH:MM:SS` or `YYYY-MM-DD HH_MM_SS` keep the space and colons
  (`/mnt/data/demo_project/raw/2026-01-02 03:04:05/run_1/data_0.npy`).
- A path may start right after a literal `\n`, `\t` or `\r` (doubly escaped tool output) or after `file://`.
- `grep -n` context suffixes (`…/loader.py-52-…`) are cut only after a known file extension, so names like
  `x.cpython-311-pytest-8.0.pyc` stay whole.
- Trailing `.`, `:`, `'`, `/` are stripped; paths are normalised; paths over 400 characters are dropped.
- `#` is not a stop, so a few bogus `….md#L17` rows can appear; they verify as `missing` and are harmless.
- Known gap: Codex `compacted` records are scanned only in `payload.message`, not in `replacement_history` /
  `retained_context`.
- Transcripts may mention paths from other machines; they simply verify as `missing`.

### Path verification

- Network mounts (e.g. NFS with the `hard` option) can make `stat()` hang indefinitely. Verification therefore
  runs in a helper subprocess with a per-path timeout (`[paths].verify_timeout_s`). A hung helper is killed and
  replaced.
- After 3 timeouts under one top-level mount (`/mnt/<name>`, else the first directory), the remaining paths there
  are marked `unreachable` unchecked.
- Status: `exists`, `missing` (not found), `unreachable` (timeout, permission or other `OSError`; the error string
  is stored).
- Copilot discovery also guards each filesystem call with a timeout thread.

### Non-interactive agent runs

Useful for tests that must not create transcripts (D20):
- `codex exec --ephemeral` writes no rollout. `--json` streams events to stdout (`thread.started` carries the id).
  Without `< /dev/null` it waits for stdin.
- `claude -p --no-session-persistence` writes no `<sid>.jsonl`, but may still create
  `~/.claude/projects/<cwd>/<sid>/tool-results/*.txt` for large tool outputs. `extract` ignores those (it reads only
  `*.jsonl` and `*/subagents/agent-*.jsonl`).
- In `claude -p --permission-mode default`, `--allowedTools "Bash(ls:*)"` does not cover `ls` outside the working
  directory, and compound commands are refused if any part is not allowed.

### Agent isolation for benchmarks

Observations from building the D28 benchmark:
- **Codex reads the repo `AGENTS.md` from disk.** `project_doc_max_bytes=0` only keeps it out of the prompt; the
  agent may still `cat` it and follow it. To change what an agent sees, replace the file in a mount namespace.
- **Tool allowlists do not make `claude -p` read-only.** An allowlisted interpreter can write files. A read-only
  filesystem root works.
- A `bwrap` base that works: `bwrap --ro-bind / / --dev-bind /dev /dev --bind /proc /proc --bind /tmp /tmp
  --bind <stage> <stage> --die-with-parent`. `/proc` must be writable, or Codex's own nested sandbox fails with
  "setting up uid map: Read-only file system". `--tmpfs <dir>` hides a directory; entries can be re-bound inside it.
  Codex refuses a `CODEX_HOME` under `/tmp`; `/var/tmp` works.
- **Token accounting:** Claude's final `result` record has `modelUsage` covering all models incl. subagents, with
  `costUSD`. Codex: per rollout file (parent and subagents), the last `token_count.total_token_usage`; Codex reports
  no cost, and list-price estimates can differ substantially from actual billing.
