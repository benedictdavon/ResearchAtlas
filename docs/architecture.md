# Architecture

## Goal

A new Codex, Claude Code or Copilot session, started anywhere in a research repo **with no paths supplied by the
user**, can:
1. find the right dataset(s) and their current, verified locations;
2. know the caveats (authoritative references, known data problems, dev vs. validation data);
3. know the relevant experiment history and decisions, including superseded conclusions, with sources it can follow.

## Non-goals

SQLite, MCP, a reconciliation engine, scheduled or background scanning, full crawling of data mounts, code-graph
tools, multi-project support beyond leaving room for it. See [roadmap.md](roadmap.md).

## Layout

```
ResearchAtlas/                    # source checkout; also the default atlas home when run from it
├── docs/                         # this documentation
├── pyproject.toml                # package metadata; installs the `researchatlas` command (D29)
├── atlas.py                      # `python atlas.py` from a checkout (thin shim, D23)
├── atlaslib/                     # core, extract, paths, refresh, review, find, copilot_import, cli
│   ├── config.example.toml       # template written by `researchatlas init`
│   └── sources/                  # codex.py, claude.py, copilot.py behind a small registry
├── tools/copilot_sync.py         # optional client-side selective Copilot upload over SSH/SCP (D24)
├── examples/demo/                # end-to-end demo on a fictional project
├── tests/                        # stdlib unittest, synthetic transcripts only
├── config.toml                   # sources, project roots, filters, limits
├── projects/
│   └── demo_project/
│       ├── reviewed_sessions.jsonl   # review ledger (D25)
│       └── knowledge/            # curated, agent-facing output (the product)
│           ├── INDEX.md          # short entry point: what's here, how to search
│           ├── datasets.md
│           ├── recipes.md        # tested loaders for the main datasets (D27)
│           ├── experiments.md    # hub: conventions, logs, index of track files (D27)
│           ├── experiments_<track>.md
│           ├── decisions.md
│           └── open_questions.md
└── work/                         # generated intermediates (re-creatable)
    ├── copilot_import/workspaceStorage/   # Copilot chat mirror written by import-copilot (D24)
    └── demo_project/
        ├── sessions/<source>_<shortid>.md     # condensed transcripts (codex 13 chars, claude/copilot 8; D15, D22)
        ├── sessions.jsonl                     # per-session metadata index
        ├── pathhits/<source>_<shortid>.json   # per-session path hits from extract (D17)
        ├── paths.jsonl                        # aggregated paths + verification status
        ├── unselected.jsonl                   # cache of parsed-but-unselected sessions
        └── refresh_<YYYYMMDD>.txt             # saved refresh reports (input to mark-reviewed)
```

## Configuration

`config.toml` in the atlas home (or `--config <path>`), read with `tomllib`. The atlas home is `$RESEARCHATLAS_HOME`,
else the source checkout when run from one, else `~/.researchatlas` (D29); `researchatlas init` writes the template
there. The folder holding `config.toml` is the home: relative `work_dir`, `knowledge_dir`, `review_ledger` and
`chat_storage` resolve against it, and every path may start with `~`.

```toml
[sources]
codex_sessions = "/home/user/.codex/sessions"
codex_session_index = "/home/user/.codex/session_index.jsonl"
claude_projects = "/home/user/.claude/projects"

[sources.copilot]                      # optional (D22, D24); omit keys you don't use
chat_storage = "work/copilot_import/workspaceStorage"   # must be exactly this (relative to the home) for import-copilot
chat_dirs = [ { path = "/home/user/copilot_import/chatSessions", cwd = "/home/user/research/demo_project" } ]
agent_state = "/home/user/.copilot/session-state"
vscode_storage = "/home/user/.vscode-server/data/User/workspaceStorage"
workspace_cwd = { "<workspace hash>" = "/home/user/research/demo_project" }

[project]
name = "demo_project"
work_dir = "work/demo_project"
knowledge_dir = "projects/demo_project/knowledge"
# review_ledger = "projects/demo_project/reviewed_sessions.jsonl"   # default: next to knowledge/
roots = ["/home/user/research/demo_project"]          # selection by cwd and by mention
cwd_also = ["/home/user/research"]                     # selection by cwd only
exclude_cwd = ["~/.researchatlas"]                    # never selected (D16)
exclude_ids = []                                       # ids / id prefixes of test sessions (D20)

[paths]
roots = ["/mnt/data", "/home/user/research"]          # prefixes harvested and verified
verify_timeout_s = 5
max_session_ids = 20

[limits]                                               # truncation (characters) in condensed files
user_text = 8000
agent_final = 40000
agent_commentary = 2000
tool_input = 400
subagent_result = 3000

[knowledge]
abbreviations = { DP = "/home/user/research/demo_project", RAW = "/mnt/data/demo_project/raw" }
new_path_min_sessions = 1
```

## Components

### 1. `researchatlas extract [--force]`
Reads Codex, Claude Code and GitHub Copilot transcripts and writes condensed per-session markdown plus a metadata
index. Rules per source: transcript-formats.md, "Transcript parsing rules".

- **Selection:** sessions whose cwd is under `[project].roots` or `cwd_also`; subagents/forks of selected sessions;
  plus sessions elsewhere whose condensed text mentions a `[project].roots` path. Excluded: `exclude_cwd`,
  `exclude_ids` and their descendants, Codex guardians (D16, D20).
- **Keep:** user messages, the agent's visible messages, compaction summaries/recaps, subagent tasks and reports,
  tool-call *inputs* (commands, file paths; truncated per `[limits]`).
- **Drop:** system prompts, injected AGENTS.md/CLAUDE.md/environment blocks, reasoning, tool *outputs* (scanned for
  paths only), token/telemetry records.
- **Forks/subagents:** records inherited from a parent are skipped; the index keeps a `parent_id` link.
- **Index record** (`sessions.jsonl`): `source` (codex|claude|copilot), `id`, `short_id`, `kind`, `parent_id`, `cwd`,
  `start`, `end`, `title`, `n_user_msgs`, `selected_by` (cwd|parent|mention), `condensed_path`, `raw_path`,
  `raw_size`, `raw_mtime`, `cli_version`. Sessions without any kept text get no condensed file
  (`condensed_path: null`) but still get path hits.
- **Path hits:** every kept text and tool output is scanned for absolute paths under `[paths].roots`; per-session
  counts go to `pathhits/` (D17).
- **Idempotent:** a session whose raw file is unchanged (size + mtime) and whose outputs exist is reused; unselected
  sessions are cached in `unselected.jsonl`; outputs of sessions no longer selected are removed. One unreadable
  transcript produces a warning, not a failed run.

### 2. `researchatlas paths [--no-verify]`
- Aggregates the per-session path hits into one record per path: `path`, `root`, `first_seen`, `last_seen`,
  `n_sessions`, `n_mentions`, `session_ids` (newest first, capped at `max_session_ids`), `kind` (guess by extension:
  data, notebook, code, doc, config, figure, model; else `dir` or `other`).
- **Verifies** each path with a per-path timeout in a helper subprocess (hard network mounts can hang): `status`
  (`exists` | `missing` | `unreachable`), `is_dir`, `size`, `mtime`, `is_symlink`, `checked_at`, `error`. See transcript-formats.md,
  "Path verification".
- Output: `paths.jsonl`, plus a summary (counts by status, root and kind; top paths) on stdout. `--no-verify` keeps
  the previous verification fields.

### Copilot import: `researchatlas import-copilot <archive> [--extract]` (D24)
- Receives a ZIP from `tools/copilot_sync.py` containing only `<hash>/workspace.json` and
  `<hash>/chatSessions/<uuid>.jsonl` entries.
- Requires `[sources.copilot].chat_storage` to be `<atlas home>/work/copilot_import/workspaceStorage`.
- Rejects unexpected, duplicate or symlink entries, oversized `workspace.json`, workspaces without a folder, and
  workspaces outside the project selection (`roots` + `cwd_also`, minus `exclude_cwd`).
- Stages everything, then replaces changed files atomically; unchanged files (and their mtimes) are kept, and older
  logs not in the archive are retained.
- `--extract` then runs `extract` (no path verification, no knowledge update, no ledger update).

### 3. Synthesis (agent-driven, not code)
An agent reads the condensed sessions (grouped by experiment folder or cwd), `paths.jsonl`, the research repo's own
handoff/summary documents and the experiment folders' READMEs/results. Related repos are read via `git show` /
`git log`, never checked out (D14). Trust order: D13. It writes the `knowledge/` files:

- **datasets.md:** one section per logical dataset: id, aliases, type, verified paths with roles (raw data,
  references, labels, configs), database tables/keys if any, caveats, sources.
- **experiments.md** + **experiments_<track>.md:** one `###` entry per experiment that matters: purpose, data,
  method, result, status (current / superseded by X), sources; current status first (D27).
- **recipes.md:** short loaders for the main datasets, each run read-only before it was added (D27).
- **decisions.md:** accepted and rejected hypotheses and baselines, with dates, superseded markers, sources.
- **open_questions.md:** §1 questions for the user, §3 result conflicts (other sections as the project needs).
- **INDEX.md:** ≤ ~60 lines: what each file holds, top datasets at a glance, how to search (`grep -n`,
  `researchatlas find`), when to run `refresh`.

**Citation format:** `[codex:0190abcd-1234 2026-01-02]`, `[claude:1a2b3c4d 2026-01-02]`,
`[copilot:5e6f7a8b 2026-01-02]`, `[file:experiments/run_01/README.md]`. Verified paths are marked `✓ <date>`,
known-missing ones `✗ <date>`, unverified leads `? lead`. Paths may be written with an abbreviation
(`DP/experiments/run_01/`), defined in `[knowledge].abbreviations`.

The repeatable incremental version of this step is `docs/prompts/incremental-update.md`.

### 4. `researchatlas refresh` and `researchatlas mark-reviewed`
`refresh` runs `extract` and `paths` (their output captured), then prints a report. It writes no review state.

- **Step 3a: sessions.** Compares the index with the review ledger (D25) and lists "New sessions (not reviewed)"
  and "Changed since review" (one line each: `<source>:<short id>  <start>  <kind>  sha=<12 hex>  <title>`, then the
  condensed file), followed by "Atlas feedback in these sessions".
- **Step 3b: cited paths.** Re-verifies every path cited in `knowledge/*.md`: each backtick span, with any text from
  ` (` on removed, cut at the first space (unless the space starts a ` HH:MM:SS` recording time). Spans with
  `<>{}*` or template tokens (`YYYY`, `HH:MM:SS`, `HHMMSS`) are ignored; spans starting with an abbreviation key
  are expanded; spans followed by `✗` are skipped. Lists those now `missing` or `unreachable` with their
  `file:line`. `--no-verify-cited` skips this.
- **Step 3c: new paths.** Existing paths that were not in `paths.jsonl` before this refresh, used in at least
  `new_path_min_sessions` sessions, and not under a cited path (abbreviation roots cover only themselves), skipping
  `.git`, `__pycache__` and similar; top 30 (D18).

The agent then updates `knowledge/` from the report (docs/prompts/incremental-update.md) and runs
`mark-reviewed --report <report>`, which records each listed session with the sha the report printed. Explicit ids
(`<source>:<id prefix>` or a bare prefix) limit it to some sessions; `--note` stores a note. Any unknown, ambiguous
or unlisted id aborts without writing (exit 2). A session that changed after the report stays pending.

### 5. `researchatlas find <words…> [--limit N]`
Case-insensitive search: `knowledge/*.md` first (per Markdown section, all words in the section or its heading path;
output `file:line  heading path` plus up to 3 snippet lines), then `paths.jsonl` (existing paths first, then by
session count), then the condensed sessions (matched per message, aggregated per file). `--limit` (default 10)
applies per group. Stdlib only, no index (D26).

### 6. Agent integration
- Global instruction files, a few lines each: `~/.codex/AGENTS.md` (Codex) and `~/.claude/CLAUDE.md` (Claude Code),
  or the equivalent for other agents. Example:
  > For demo_project data locations and research history, read
  > `/home/user/.researchatlas/projects/demo_project/knowledge/INDEX.md` before guessing paths or asking the user.
- One pointer line with the same message in the research repo's `AGENTS.md`, **only with the repo owner's
  approval**. This is the only edit the atlas makes outside its own folder. If the repo is shared, keep the line
  local (e.g. list the file in `.git/info/exclude`).
- Verify that each agent actually loads its global file (test in a fresh session).

## Acceptance tests

Run in a *fresh*, non-persistent session (D20), started in the research repo, with no paths given. Replace the
examples with the project's real priority questions.

| # | Query | Pass if |
|---|-------|---------|
| A1 | "Where is the raw data for <main dataset>, and what are its references/labels?" | Correct verified paths (and DB tables if any) |
| A2 | "Which recordings pair with which reference files, and which pairings are validated?" | Verified paths, pairings, and the caveats stated correctly |
| A3 | "Where is the <month> data?" | Correct verified paths; distinguished from similar datasets |
| A4 | "Which experiments tested <method>, and what was concluded? Is <baseline> still current?" | Correct folders, conclusions, current-vs-superseded status, with sources |
| A5 | Ask about a made-up dataset | The agent says it isn't in the atlas and doesn't invent paths |
| A6 | Rename or move a cited test path, then `refresh` | Flagged as missing; not silently kept as verified |
