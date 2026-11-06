# Design decisions

Format: decision · alternatives considered · why. Code comments cite these numbers. Don't reopen a decision
without new evidence; to change one, add a new entry that supersedes it.

ResearchAtlas was first built for one research project; entries that only concerned that project's data are
reduced to a one-line summary so the numbering stays stable.

### D1 — Hybrid evidence-based approach; code-graph tools deferred
- **Alternatives:** documentation only; a code/document graph tool as the foundation; transcript mining only.
- **Why:** a code graph can't say which dataset is valid or which reference is authoritative. Docs alone go stale.
  Transcripts alone aren't trustworthy. Combine transcript mining, verification against the filesystem, and
  markdown knowledge files.

### D2 — Smallest useful version first; every extra component optional
- **Alternatives:** a multi-phase plan with SQLite, an MCP server, a reconciliation engine, scheduled scanners.
- **Why:** the real cost is checking extraction quality, not writing code, and each extra component adds failure
  modes. Build what every option needs, use it, and add components only when a real limit appears (roadmap.md). Don't build
  stubs or placeholders for deferred parts.

### D3 — Markdown knowledge files, not SQLite
- **Why:** expected volume is at most a few hundred records. Agents read markdown natively, grep is enough, and git
  diffs make review easy. Structured metadata that already lives in a project database stays there. Revisit if
  grep/markdown stops scaling (roadmap.md).

### D4 — No MCP server; CLI + markdown
- **Why:** Codex, Claude Code and Copilot agents all have a shell. MCP adds value only for shell-less clients,
  complex structured queries or many shared users, and needs a long-running server plus client config.

### D5 — Reconcile conflicts once (one LLM pass + one user review), not with an engine
- **Why:** with tens of root sessions it is faster and more accurate to resolve conflicts once: the newest verified
  claim wins by default; unclear ones go to `open_questions.md` for the user. Afterwards `refresh` surfaces new
  material incrementally.

### D6 — Update on command (`refresh`), not by scheduled scanning
- **Alternatives:** automatic incremental updates (cron, daemon).
- **Why:** cron/daemons don't survive container restarts, and periodic crawls of network mounts are costly.
  Knowledge changes only when someone works, so a session-driven refresh (new transcripts + re-checking cited
  paths) matches how the data changes. Agents may run `refresh` themselves.

### D7 — Knowledge lives in the atlas repo; the research repo gets one pointer line
- **Why:** no generated bulk files in the research repo. A short pointer line in its `AGENTS.md` is acceptable.
  Global agent instruction files (`~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`) point to the atlas too, because an
  `AGENTS.md` inside the atlas home isn't loaded when an agent starts in the research repo (architecture.md §6).

### D8 — Transcripts are leads; paths are verified; claims cite sources
- **Why:** past agent statements can be wrong or out of date. Every path gets a status (`exists` / `missing` /
  `unreachable`) with a check time. Every knowledge claim cites a session id and date, or a file.

### D9 — Plain Python stdlib, one CLI entry
- **Why:** no dependency management. Python 3.11+ (`tomllib` for the TOML config). Split into modules only when the
  file becomes unwieldy (that happened: D23).

### D10 — Progressive disclosure for agents
- **Why:** one giant knowledge file costs every session context and gets ignored. Agents read a short `INDEX.md`
  first and open topic files only as needed.

### D11 — Name and layout: per-project knowledge under `projects/<project>/`
- **Why:** `projects/` rather than `repo/`, so nobody mistakes it for a clone. It holds knowledge *about* a repo,
  never copies of it, and leaves room for more projects.

### D12 — The docs set is the cross-session handoff
- **Why:** users switch chats and agents freely. `docs/` is the source of truth for project context and status;
  every agent keeps it current.

### D13 — Source trust ranking for synthesis
1. The current filesystem / project database (verified facts)
2. Recent transcripts and the experiment folders' own files (results, READMEs, logs)
3. Handoff/summary documents maintained in the research repo
4. Older transcripts
5. Older agent-docs folders known to be outdated (low-trust leads)

Higher ranks win conflicts. Within a rank, newer evidence wins. Material conflicts go to `open_questions.md`.

### D14 — Related repos: all branches, read-only
- **Why:** relevant code may live on feature branches. Read them with `git show` / `git log` / `git ls-tree`;
  never check out, since the working tree may hold someone's work.

### D15 — Codex short ids are 13 characters, not 8
- **Evidence:** UUIDv7 prefixes collide at 8 characters (forks spawned in the same second, e.g. `0190abcd-1234`,
  `0190abcd-5678`); 0 collisions were seen at 13.
- **Decision:** Codex condensed files and citations use the first 13 characters: `[codex:0190abcd-1234 2026-01-02]`.
  Claude keeps 8 (session uuid or subagent `agentId`). Grepping an 8-char prefix still finds them.

### D16 — Skip guardian rollouts and the atlas's own sessions
- **Guardian** rollouts (`source.subagent.other == "guardian"`) are approval reviewers that re-paste parts of the
  parent transcript. Extracting them would duplicate content and mislabel it as user text.
- **Atlas sessions** (cwd under the atlas home, `[project].exclude_cwd`) mention project paths but are about
  building the atlas. They are excluded from selection to avoid circular evidence.

### D17 — `extract` records per-session path hits; `paths` aggregates and verifies
- **Why:** transcripts can total close to a gigabyte; parsing them once avoids a second full pass. `extract` scans all
  content (incl. tool outputs) for absolute paths under the configured roots and writes per-session hits to
  `work/<project>/pathhits/<source>_<shortid>.json`. `paths` aggregates them into `paths.jsonl` and verifies each
  with a timeout. Stop characters: transcript-formats.md, "Path harvesting".

### D18 — refresh "new paths" = not in the previous `paths.jsonl`
- **Alternatives:** `last_seen` after a watermark (one live session re-surfaces thousands of paths); `first_seen`
  after a watermark (misses new paths inside long-running sessions).
- **Decision:** compare against the path set from before this refresh; report existing, uncited paths used in at
  least `[knowledge].new_path_min_sessions` sessions (cap 30). Knowledge files may cite paths with abbreviations
  (`DP/…`, defined in `[knowledge].abbreviations`); refresh expands them.

### D19 — (project-specific; omitted)
When one related repo exists as several clones, take evidence from the freshest object store. Otherwise specific to
the original project.

### D20 — Atlas test sessions never enter the index
- **Problem:** acceptance tests start agents in the research repo, so `extract` would select them by cwd and the
  atlas would cite its own test answers (circular, like D16).
- **Rejected:** a fixed tag in each test prompt; it changes the question the agent sees.
- **Decision:** run test agents without persisting a transcript (`codex exec --ephemeral`,
  `claude -p --no-session-persistence`). For sessions persisted anyway, `[project].exclude_ids` lists ids or id
  prefixes; `extract` excludes them and, transitively, their subagents/forks.

### D21 — Path tokens may contain parentheses; grep-context stripping needs a known extension
- **Evidence:** a path-recall audit showed real paths containing `(` were cut (`…/case_1x1(a).yaml` →
  `…/case_1x1`), the `-NN-` grep-context rule cut `…/x.cpython-311-pytest-8.0.pyc` to `…/x.cpython`, and paths right
  after a literal `\n` in doubly escaped tool output were skipped.
- **Decision (amends D17):** `(…)` groups are part of a path; a `)` without a `(` inside the path ends it. The `-NN-…`
  suffix is stripped only after a known file extension. A path may start right after a literal `\n`/`\t`/`\r`.

### D22 — GitHub Copilot is a third transcript source
- **Why:** much research work happens in the VS Code Copilot Chat panel, which Codex/Claude transcripts don't cover.
  Locations and formats: transcript-formats.md, "GitHub Copilot history".
- **Inputs** (`[sources.copilot]`): A = Chat-panel op logs copied from the client PC (`chat_dirs`, each with its
  workspace folder; `chat_storage`, the uploader mirror, D24), B = Copilot agent sessions (`agent_state`,
  `<id>/events.jsonl`), C = server-side Chat transcripts (`vscode_storage`; cwd from `workspace.json`, else the
  `workspace_cwd` hash map). D (`agentSessionData/*/session.db`) is not read: its sessions exist as Codex rollouts
  or as B.
- **Dedup:** one candidate per session UUID; A beats B beats C, then the largest file. Reported as "copilot
  duplicates dropped".
- **Condensing:** same headings and bullets as Codex/Claude. A: the op log is replayed tolerantly; system-initiated
  or hidden requests get no `USER` heading; `thinking` is dropped; tool results are path-scanned only, except
  subagent results (`SUBAGENT REPORT`); every section carries the request timestamp. B/C: records with
  `data.parentToolCallId` belong to a subagent and are scanned only; `session.compaction_complete` is a `RECAP`.
- **Review fixes:** an inline reference to a code symbol is rendered as its name, not its location (which often
  points into a library and corrupted the prose); tool-message strings are markdown-unescaped before path scanning
  (`demo\_project` would cut the path).
- **Citation:** `[copilot:<id8> <date>]` (13 characters only on an 8-char collision, which `extract` warns about).
- **Rejected:** separate citation prefixes for B (one source is simpler for readers); reading D (redundant, often
  ephemeral).

### D23 — `atlas.py` is a thin shim over the `atlaslib/` package
- **Why:** a third source would have pushed the single file past ~2,300 lines with `if source == …` branches.
- **Decision:** `atlaslib/{core,extract,paths,refresh,review,find,copilot_import,cli}.py` plus one module per source
  in `atlaslib/sources/` behind a small registry (`NAME`, `discover`, `prepare`, `condense`, `title`; documented in
  `sources/__init__.py`). `atlas.py` stays the only CLI entry and re-exports the old names so existing tests run
  unchanged. The split was verified as a pure move (byte-identical outputs from a back-to-back run).
- Not named `atlas/`, because a package of that name would shadow `atlas.py` on import.

### D24 — Client-side selective Copilot upload over existing SSH; server-side transformation
- **Why:** manual workspace searches, ZIP creation and browser upload are cumbersome. A server-to-PC connection
  would need an inbound service on the client; an outbound SSH connection from the client usually already exists.
- **Decision:** `tools/copilot_sync.py` runs on the client (stdlib Python 3.9+). Preview is the default. Explicit
  `--root` prefixes select workspace folders; only `workspace.json` folder mappings and `chatSessions/*.jsonl` are
  bundled. `--upload` uses ordinary SSH/SCP authentication and runs `atlas.py import-copilot <archive> --extract` on
  the server. No credentials in config, no client-side service, no third-party storage, no scheduler, no second
  parser.
- **Storage:** server files go only under `<atlas>/work/copilot_import/workspaceStorage/`
  (`sources.copilot.chat_storage`); older manual imports stay read-only.
- **Amends D22 dedup:** within chat sources a synced mirror beats a manual import even when its current log is
  smaller, so a stale large export can't shadow a newer compacted snapshot. Unchanged mirror files keep their mtimes,
  so extraction caching stays effective.
- **Scope:** on-demand full snapshots of the selected logs; no incremental transfer, no automatic knowledge
  synthesis. Multi-root workspaces and workspaces without a single folder are skipped with a warning.

### D25 — Per-session review ledger replaces the refresh watermark
- **Why:** a single `last_refresh` timestamp was easy to leave un-advanced (every refresh then listed the same
  sessions as "new"), and a session that grew after review was invisible.
- **Decision:** `projects/<project>/reviewed_sessions.jsonl` (committed) has one row per reviewed session:
  `{session, reviewed, sha, bytes, note}`; `sha` = first 12 hex of SHA-256 of the condensed transcript. A session is
  pending when it has no row or its sha differs. `refresh` only reads the ledger and lists "New sessions", "Changed
  since review" and "Atlas feedback in these sessions". After updating knowledge, the agent runs
  `atlas.py mark-reviewed --report <report>` (or explicit ids with `--note`), which records the sha printed in the
  report; a session that changed after the report stays pending. Unknown, ambiguous or unlisted ids write nothing
  (exit 2). `refresh --dry-run` is accepted but is a no-op.
- **Atlas feedback:** pending sessions that used the atlas (`ResearchAtlas/projects/` or `atlas.py find` in their
  text) are scanned for lines that mention the atlas together with correction words (wrong, stale, outdated,
  differ…), max 5 per session, so corrections flow back. False positives are accepted; it is a review aid.
- A deliberate re-extract changes every sha; re-baseline with `mark-reviewed` after checking the diff.
- Review a stable report version even if sessions keep growing during synthesis; mark against that report so later
  content stays pending. Don't broaden a batch to sessions arriving during review.

### D26 — `find` matches per Markdown section, not per line
- **Why:** agents search with natural multi-word queries; line-level all-words matching returned nothing when the
  words were spread over one entry.
- **Decision:** knowledge files are split into fence-aware sections; a section matches when all words occur in it or
  its heading path. Ranking: sections with a line containing all words first, then total hits. Output
  `file:line  heading path` plus up to 3 snippet lines. `paths.jsonl`: existing paths first, then by session count.
  Sessions: matched per message, aggregated per transcript. `--limit` (default 10) applies per group. Stdlib, no
  index.

### D27 — Large topic files become a hub plus track files; a tested recipes file
- **Why:** a knowledge file ordered by ingestion batch listed one item in several places with conflicting statuses.
- **Decision:** `experiments.md` keeps conventions, authoritative logs and an index; entries live in
  `experiments_<track>.md` files, one `###` entry per experiment with the current status first; older claims stay,
  labelled superseded or "conflict between sources". Such a restructuring is checked mechanically (every citation,
  path, backticked span and number of the original survives).
- **Recipes:** `knowledge/recipes.md` holds short copy-paste loaders for the main datasets. Every code block is run
  read-only before it is added and states which interpreter to use and which side effects to avoid. Untested snippets
  are not added.

### D28 — Measure the atlas's impact with a sandboxed four-arm benchmark
- **Question:** does the atlas pointer reduce or increase agent token usage and answer quality compared with the
  alternatives?
- **Method:**
  - A fixed set of questions with atomic rubrics and ground truth checked on disk: most need research history, a
    few are controls that don't.
  - Four arms that differ only in the standing instructions the agent sees: `none` (no atlas), `atlas` (the pointer
    line), `dump` (an instruction to read every knowledge file in full first), `hint` (a folder hint only).
  - Each agent runs as normally configured, fresh and non-persistent (D20), inside a read-only `bwrap` sandbox that
    replaces the on-disk instruction files per arm and hides the atlas from `none`/`hint` (transcript-formats.md, "Agent isolation for
    benchmarks").
  - Primary metric: total tokens incl. subagents. Also cost, wall time, a blind LLM rubric grade and invented paths.
  - Analysis per question (geometric mean of arm/none over repetitions), bootstrapped over questions.
  - A hard spending cap per agent.
- **Outcome:** the pointer arm used clearly fewer tokens than `none` with equal or better grades, so the pointer
  design was kept; dumping the knowledge into context was not adopted.
- **Lesson:** budget guards based on list-price estimates can undercount real billing. Use a lower cap and check
  actual billing.
- **Report:** [benchmark.md](benchmark.md).

### D29 — Installable `researchatlas` CLI with an atlas home
- **Alternatives:** keep running `python atlas.py` from a clone with `config.toml` next to the code; a full
  `~/.config` + `~/.local/share` XDG split.
- **Decision:** `pyproject.toml` installs a `researchatlas` command (also `python -m atlaslib`). Config, `work/` and
  knowledge bases live in one *atlas home*: `$RESEARCHATLAS_HOME`, else the source checkout when run from one (so
  `python atlas.py` keeps working unchanged), else `~/.researchatlas`. `researchatlas init` writes the bundled
  template there and never overwrites. Relative paths in `config.toml` resolve against the folder holding it, and
  every configured path may start with `~`.
- **Why:** a pip install has no writable code folder to keep data next to, and one home folder is easier to back up,
  version in a private repo and point agents at than an XDG split. The uploader (D24) runs `python -m atlaslib` from
  the home, so it works with either layout.
