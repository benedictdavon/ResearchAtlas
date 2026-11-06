# CLI reference

```
researchatlas [--config PATH] <command> [options]
```

From a source checkout, `python atlas.py` and `python -m atlaslib` run the same CLI.

| Global option | Meaning |
|---|---|
| `--config PATH` | Config file to use. Default: `config.toml` in the atlas home ([configuration.md](configuration.md)) |
| `--version` | Print the version and exit |

**Exit codes:** `0` success; `1` the run failed (unreadable input, `paths` before `extract`, a rejected Copilot
archive); `2` usage or configuration error (missing or invalid config, empty search, `mark-reviewed` rejecting an
id). Commands never modify anything outside the atlas home.

| Command | Purpose |
|---|---|
| [`init`](#init) | Create `config.toml` in the atlas home |
| [`extract`](#extract) | Select and condense the project's sessions; harvest their paths |
| [`paths`](#paths) | Aggregate harvested paths and verify them on disk |
| [`refresh`](#refresh) | `extract` + `paths`, then report what the knowledge base needs to catch up on |
| [`mark-reviewed`](#mark-reviewed) | Record sessions as covered by the knowledge base |
| [`find`](#find) | Search knowledge, verified paths and condensed sessions |
| [`import-copilot`](#import-copilot) | Install VS Code Chat logs uploaded from a client PC |

## `init`

```
researchatlas init [--home DIR]
```

Copies the bundled template to `<home>/config.toml`. Never overwrites an existing file. `--home` defaults to the
atlas home; when it differs, `init` prints the `RESEARCHATLAS_HOME` setting to use.

## `extract`

```
researchatlas extract [--force]
```

Reads Codex, Claude Code and GitHub Copilot transcripts and writes one condensed Markdown file per selected session
plus a metadata index. Per-source parsing rules: [transcript-formats.md](transcript-formats.md).

- **Selection:** sessions whose working directory is under `[project].roots` or `cwd_also`; subagents and forks of
  selected sessions; and sessions elsewhere whose text mentions a `[project].roots` path. Excluded: `exclude_cwd`,
  `exclude_ids` and their descendants, and Codex guardian reviewers (D16, D20).
- **Kept:** user messages, the agent's visible messages, compaction summaries, subagent tasks and reports, and
  tool-call *inputs* (commands, file paths), each truncated per `[limits]`.
- **Dropped:** system prompts, injected instruction files and environment blocks, reasoning, tool *outputs* (scanned
  for paths only), and token or telemetry records.
- **Path hits:** every kept text and tool output is scanned for absolute paths under `[paths].roots`; per-session
  counts go to `pathhits/` (D17).
- **Incremental:** a session whose raw file is unchanged (size and mtime) is reused; `--force` re-extracts
  everything. Unselected sessions are cached, and outputs of sessions no longer selected are removed. An unreadable
  transcript produces a warning, not a failed run.

Output (under `work/<project>/`, see [architecture.md](architecture.md#data-files)): `sessions/<source>_<id>.md`,
`sessions.jsonl`, `pathhits/`, `unselected.jsonl`, and a summary on stdout.

## `paths`

```
researchatlas paths [--no-verify]
```

Aggregates the per-session path hits into one record per path and checks each path on disk in a helper
subprocess with a per-path timeout (`[paths].verify_timeout_s`), so a hung network mount can't stall the run.
Each path gets a status: `exists`, `missing` or `unreachable` (timeout or I/O error), plus a kind guessed from the
extension (data, notebook, code, doc, config, figure, model, dir, other).

Writes `work/<project>/paths.jsonl` and prints counts by status, root and kind and the most-used paths.
`--no-verify` re-aggregates only and keeps the previous verification fields. Fails (exit 1) if `extract` hasn't
run.

## `refresh`

```
researchatlas refresh [--no-verify-cited] > work/<project>/refresh_YYYYMMDD.txt
```

Runs `extract` and `paths` (their output captured), then prints a report in three parts. It writes no review state;
save the report, because `mark-reviewed` reads it.

1. **Sessions.** Compares the session index with the review ledger (D25). Lists "New sessions (not reviewed)" and
   "Changed since review" as `<source>:<short id>  <start>  <kind>  sha=<12 hex>  <title>`, each followed by its
   condensed file. Then "Atlas feedback in these sessions": lines where a session that consulted the atlas called
   something in it wrong or stale.
2. **Cited paths.** Re-verifies every path cited in `knowledge/*.md` and lists those now `missing` or
   `unreachable`, with the `file:line` that cites them. `--no-verify-cited` skips this. A cited path is a backtick
   span, with any text from ` (` on removed and cut at the first space (unless the space starts a ` HH:MM:SS`
   time). Spans containing `<>{}*` or template tokens (`YYYY`, `HH:MM:SS`, `HHMMSS`) are ignored, spans starting
   with an abbreviation key are expanded, and spans marked `✗` are skipped as known-missing.
3. **New paths.** Existing paths that weren't in `paths.jsonl` before this refresh, used in at least
   `[knowledge].new_path_min_sessions` sessions, and not under a cited path; caches such as `.git` and
   `__pycache__` are skipped. Top 30 (D18).

An agent then applies the report to the knowledge files ([refresh-guide.md](refresh-guide.md)).

## `mark-reviewed`

```
researchatlas mark-reviewed --report REPORT [ID ...] [--note TEXT]
researchatlas mark-reviewed ID ... [--note TEXT]
```

Records sessions in the review ledger (`projects/<project>/reviewed_sessions.jsonl`) with a hash of their condensed
text. With `--report`, it marks every session the report lists, at the hash the report printed; a session that
changed after the report therefore stays pending. IDs (`<source>:<id prefix>` or a bare prefix) limit it to some
sessions. `--note` stores a note with each row.

Any unknown, ambiguous or (with `--report`) unlisted id aborts the whole command without writing (exit 2).

## `find`

```
researchatlas find WORD ... [--limit N]
```

Case-insensitive search in three groups, each limited to `N` results (default 10):

1. **Knowledge:** `knowledge/*.md` split into Markdown sections. A section matches when all words occur in it or its
   heading path; sections with one line containing all words rank first. Prints `file:line  heading path` and up
   to three matching lines (D26).
2. **Paths:** `paths.jsonl`, existing paths first, then by number of sessions.
3. **Sessions:** condensed transcripts, matched per message and aggregated per file. These are leads, not
   verified facts.

## `import-copilot`

```
researchatlas import-copilot ARCHIVE [--extract]
```

Installs a ZIP produced by [`tools/copilot_sync.py`](../tools/copilot_sync.py) into
`<atlas home>/work/copilot_import/workspaceStorage/`, which `[sources.copilot].chat_storage` must point to (D24).
Usually the uploader runs it over SSH; see [refresh-guide.md](refresh-guide.md), step 0.

- Accepts only `<hash>/workspace.json` and `<hash>/chatSessions/<uuid>.jsonl` entries. Rejects unexpected,
  duplicate or symlink entries, oversized `workspace.json` files, workspaces without a folder, and workspaces
  outside the project selection (`roots` and `cwd_also`, minus `exclude_cwd`).
- Stages everything, then replaces changed files atomically. Unchanged files keep their mtimes, so extraction
  caching stays effective, and older logs not in the archive are retained.
- `--extract` then runs `extract`. It doesn't verify paths or touch the knowledge base or the ledger.
