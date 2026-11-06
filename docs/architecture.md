# Architecture

How ResearchAtlas is put together. For using it, start with [getting-started.md](getting-started.md); command
details are in [cli.md](cli.md).

## Goal

A new Codex, Claude Code or Copilot session, started anywhere in a research repo **with no paths supplied by the
user**, can:

1. find the right datasets and their current, verified locations;
2. know the caveats: authoritative references, known data problems, development vs. validation data;
3. know the relevant experiment history and decisions, including superseded conclusions, with sources it can
   follow.

## Non-goals

A database, an MCP server, a conflict-reconciliation engine, scheduled or background scanning, crawling data
mounts, and code-graph analysis. Each is deferred until a real limit calls for it ([roadmap.md](roadmap.md), D2).

## Overview

The work splits into a deterministic part, done by the CLI without any LLM, and an understanding part, done by a
coding agent following written prompts:

| Stage | Who | Input → output |
|---|---|---|
| `extract` | CLI | agent transcripts → condensed sessions, session index, per-session path hits |
| `paths` | CLI | path hits → `paths.jsonl` with on-disk status |
| Synthesis | agent ([prompts](prompts/)) | condensed sessions, verified paths, the research repo's own files → `knowledge/*.md` |
| `refresh` | CLI | everything above + review ledger → report of what the knowledge base is missing |
| Update | agent ([prompt](prompts/incremental-update.md)) | report → updated `knowledge/*.md`, then `mark-reviewed` → ledger |
| `find` | CLI | knowledge, paths, sessions → ranked matches for agents |

Keeping the agent's job to reading and writing Markdown, and the CLI's job to everything that can be checked
mechanically, means every fact in the knowledge base can be traced to a session or a file and re-verified (D1, D8).

## Layout

```
<atlas home>/                     # $RESEARCHATLAS_HOME, the source checkout, or ~/.researchatlas (D29)
├── config.toml                   # sources, project roots, filters, limits (configuration.md)
├── projects/
│   └── <project>/
│       ├── reviewed_sessions.jsonl   # review ledger (D25)
│       └── knowledge/            # curated, agent-facing output (knowledge-format.md)
└── work/                         # generated, re-creatable
    ├── copilot_import/workspaceStorage/   # Copilot chat mirror written by import-copilot (D24)
    └── <project>/
        ├── sessions/<source>_<shortid>.md     # condensed transcripts
        ├── sessions.jsonl                     # session index
        ├── pathhits/<source>_<shortid>.json   # per-session path hits (D17)
        ├── paths.jsonl                        # aggregated paths with verification status
        ├── unselected.jsonl                   # cache of parsed but unselected sessions
        └── refresh_<YYYYMMDD>.txt             # saved refresh reports
```

Source tree:

```
ResearchAtlas/
├── atlaslib/
│   ├── cli.py                    # argument parsing, `init`, error handling
│   ├── core.py                   # config and atlas home, JSONL I/O, path harvesting, condensed-file writer
│   ├── extract.py                # session selection, incremental condensing, path hits
│   ├── paths.py                  # aggregation and timeout-guarded verification
│   ├── refresh.py                # the refresh report
│   ├── review.py                 # review ledger, mark-reviewed
│   ├── find.py                   # section-aware search
│   ├── copilot_import.py         # receives uploads from tools/copilot_sync.py
│   ├── config.example.toml       # template written by `researchatlas init`
│   └── sources/                  # codex.py, claude.py, copilot.py behind a small registry (D23)
├── atlas.py                      # `python atlas.py` from a checkout (thin shim)
├── tools/copilot_sync.py         # client-side Copilot chat uploader (D24)
├── examples/demo/                # end-to-end demo on a fictional project
├── tests/                        # stdlib unittest, synthetic transcripts only
└── docs/
```

## Transcript sources

Each source is one module in `atlaslib/sources/` with the same small interface, documented in
`sources/__init__.py`:

| Member | Role |
|---|---|
| `NAME` | Source name used in ids, file names and citations (`codex`, `claude`, `copilot`) |
| `discover(cfg)` | List candidate sessions (id, parent, working directory, raw file) and count deliberately skipped ones |
| `prepare(cfg, ctx)` | One-time setup per run, e.g. reading the Codex title index |
| `condense(c, ctx, path)` | Parse one transcript, write its condensed Markdown, and return the parse state (path hits, counts) |
| `title(c, st, ctx)` | The session title, if the source has one |

All three write the same condensed format (`### <date time> USER`, `AGENT`, `SUBAGENT REPORT`, …; see
[transcript-formats.md](transcript-formats.md#condensed-file-format)), so everything downstream is
source-independent. Adding a source means adding a module and one registry entry.

## Data files

**`sessions.jsonl`**, one record per selected session: `source`, `id`, `short_id`, `kind`, `parent_id`, `cwd`,
`start`, `end`, `title`, `n_user_msgs`, `selected_by` (`cwd`, `parent` or `mention`), `condensed_path`, `raw_path`,
`raw_size`, `raw_mtime`, `cli_version`. Sessions without any kept text have `condensed_path: null` but still
contribute path hits.

**`pathhits/<source>_<shortid>.json`**: the absolute paths under `[paths].roots` found in one session, with
mention counts. Written by `extract` so transcripts are parsed only once (D17).

**`paths.jsonl`**, one record per path: `path`, `root`, `first_seen`, `last_seen`, `n_sessions`, `n_mentions`,
`session_ids` (newest first, capped), `kind`, and the verification fields `status` (`exists`, `missing` or
`unreachable`), `is_dir`, `size`, `mtime`, `is_symlink`, `checked_at`, `error`.

**`reviewed_sessions.jsonl`**, the review ledger, one row per reviewed session:
`{"session": "<source>:<id>", "reviewed": "YYYY-MM-DD", "sha": "<12 hex>", "bytes": n, "note": "..."}`. `sha` is
a hash of the condensed transcript, so a session that grows after review becomes pending again (D25).

## Properties

- **Incremental.** `extract` reuses a session whose raw file is unchanged (size and mtime) and caches the sessions it
  didn't select, so a refresh parses only new or changed transcripts. Unchanged Copilot mirror files keep their
  mtimes for the same reason.
- **Safe on network mounts.** Paths are checked in a helper subprocess with a per-path timeout; after repeated
  timeouts under one mount, the rest of that mount is marked `unreachable` without waiting.
- **Read-only outside the atlas home.** The CLI only reads transcripts and stats paths. The agent prompts forbid
  edits to research repos and data; the only external change is the pointer line in an agent's instruction file,
  added by the user ([getting-started.md](getting-started.md#5-point-your-agents-at-the-atlas)).
- **Robust to format drift.** An unreadable or unexpected transcript produces a warning and is skipped; one bad
  file never fails a run. Agent transcript formats are undocumented and change between versions
  ([transcript-formats.md](transcript-formats.md)).
- **No circular evidence.** Sessions started in the atlas home and sessions that only tested the atlas are never
  selected, so the atlas doesn't cite its own work (D16, D20).
- **Standard library only.** Python 3.11+, no runtime dependencies, plain Markdown and JSONL (D3, D9).
