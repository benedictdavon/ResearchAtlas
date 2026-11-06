# Configuration

## The atlas home

Everything ResearchAtlas reads or writes, apart from the transcripts themselves, lives in one folder, the
*atlas home* (D29):

1. `$RESEARCHATLAS_HOME`, if set;
2. else the source checkout, when the CLI runs from one (`python atlas.py`);
3. else `~/.researchatlas`.

`researchatlas init` writes the template [`atlaslib/config.example.toml`](../atlaslib/config.example.toml) to
`<home>/config.toml`. `--config PATH` uses another file; the folder holding the config file is then the home.
Relative `work_dir`, `knowledge_dir`, `review_ledger` and `chat_storage` values resolve against the home, and every
path may start with `~`. A missing file or section stops the CLI with a message (exit 2).

The home is worth keeping in a private git repository: `projects/` holds the curated knowledge and the review
ledger, while `work/` is generated and can be rebuilt with `researchatlas extract`.

## Example

```toml
[sources]
codex_sessions = "~/.codex/sessions"
codex_session_index = "~/.codex/session_index.jsonl"
claude_projects = "~/.claude/projects"

[sources.copilot]                                   # optional; omit keys you don't use
chat_storage = "work/copilot_import/workspaceStorage"
chat_dirs = [ { path = "~/copilot_export/chatSessions", cwd = "~/research/demo_project" } ]
agent_state = "~/.copilot/session-state"
vscode_storage = "~/.vscode-server/data/User/workspaceStorage"
workspace_cwd = { "<workspace hash>" = "~/research/demo_project" }

[project]
name = "demo_project"
work_dir = "work/demo_project"
knowledge_dir = "projects/demo_project/knowledge"
# review_ledger = "projects/demo_project/reviewed_sessions.jsonl"   # default: next to knowledge/
roots = ["~/research/demo_project"]
cwd_also = ["~/research"]
exclude_cwd = ["~/.researchatlas"]
exclude_ids = []

[paths]
roots = ["/mnt/data", "~/research"]
verify_timeout_s = 5
max_session_ids = 20

[limits]
user_text = 8000
agent_final = 40000
agent_commentary = 2000
tool_input = 400
subagent_result = 3000

[knowledge]
abbreviations = { DP = "~/research/demo_project", RAW = "/mnt/data/demo_project/raw" }
new_path_min_sessions = 1
```

## `[sources]`

Every key is optional; a missing key disables that source. Where each agent stores its transcripts:
[transcript-formats.md](transcript-formats.md#transcript-locations).

| Key | Meaning |
|---|---|
| `codex_sessions` | OpenAI Codex CLI rollouts (`~/.codex/sessions`) |
| `codex_session_index` | Codex thread-name index, used for session titles |
| `claude_projects` | Claude Code transcripts (`~/.claude/projects`) |

### `[sources.copilot]` (D22, D24)

| Key | Meaning |
|---|---|
| `chat_storage` | Mirror written by `import-copilot`. Must be `work/copilot_import/workspaceStorage` (relative to the home) |
| `chat_dirs` | Manually copied VS Code Chat logs: a list of `{ path, cwd }`, where `cwd` is the workspace folder they belong to |
| `agent_state` | Copilot agent sessions (`~/.copilot/session-state`) |
| `vscode_storage` | Chat transcripts kept by a VS Code Server (often lost when its container restarts) |
| `workspace_cwd` | Folder for a workspace hash that has no `workspace.json` |

If the same session appears in several Copilot inputs, one copy is used: the synced mirror, then manual copies, then
agent state, then server transcripts.

## `[project]`

| Key | Meaning |
|---|---|
| `name` | Project name, used in reports |
| `work_dir` | Generated files (condensed sessions, indexes, path data). Safe to delete and rebuild |
| `knowledge_dir` | The curated knowledge base ([knowledge-format.md](knowledge-format.md)) |
| `review_ledger` | Which sessions the knowledge base covers. Default: `reviewed_sessions.jsonl` next to `knowledge_dir` |
| `roots` | Project folders. A session is selected if its working directory is under one, or if its text mentions one |
| `cwd_also` | Extra folders that select a session by working directory only (e.g. the parent of several repos) |
| `exclude_cwd` | Sessions started here are never selected. Include the atlas home, so work on the atlas isn't cited as research (D16) |
| `exclude_ids` | Session ids or id prefixes to skip, with their subagents and forks, e.g. sessions that only tested the atlas (D20) |

Subagents and forks of a selected session are always selected with it.

## `[paths]`

| Key | Meaning |
|---|---|
| `roots` | Absolute paths under these prefixes are harvested from transcripts and verified. List the project folders and the data mounts |
| `verify_timeout_s` | Per-path timeout for the on-disk check. Network mounts can hang; a timeout gives status `unreachable` |
| `max_session_ids` | How many session ids to keep per path in `paths.jsonl` (newest first) |

## `[limits]`

Truncation limits, in characters, for the condensed transcripts. Longer text is cut and marked.

| Key | Applies to |
|---|---|
| `user_text` | Each user message |
| `agent_final` | The agent's final answer in a turn |
| `agent_commentary` | Intermediate agent messages |
| `tool_input` | Each tool-call input (commands, arguments) |
| `subagent_result` | Each subagent result |

## `[knowledge]`

| Key | Meaning |
|---|---|
| `abbreviations` | Short prefixes for long paths in the knowledge files, e.g. `DP/experiments/run_01/`. `refresh` expands them before checking cited paths |
| `new_path_min_sessions` | `refresh` reports uncited new paths used in at least this many sessions |
