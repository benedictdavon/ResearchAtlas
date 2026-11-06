# 06 — Future Work (optional, deferred)

None of these are part of the MVP. Build one only when its **trigger** actually happens, and record the decision
in 03.

| Component | What it would add | Trigger to build it |
|-----------|-------------------|---------------------|
| **SQLite catalog** (+ FTS) | Structured queries ("all recordings between two dates with status=verified") | Knowledge files grow past what grep/markdown handle comfortably, or queries need joins/filters |
| **MCP server** | Tool access for agents without a shell; typed queries | A shell-less client must use the atlas, or many users share it |
| **Reconciliation engine** | Automatic conflict detection/merging on each refresh | New sessions arrive too often for agent + user review of `refresh` reports |
| **Scheduled / automatic refresh** | Fresh knowledge without anyone running a command | Reliable scheduling exists (e.g. a persistent service outside an ephemeral container), and on-command refresh is often forgotten |
| **Data-mount inventory scanner** | Discover data that no session ever mentioned | Important datasets turn out to be missing from the atlas because no agent ever touched them |
| **Project-database extractor** | Pull dataset/recording metadata straight from the project's database | The database holds many datasets that transcripts don't cover |
| **Experiment-folder miner** | Systematically summarise every experiment folder (README, notebook header cells) | Acceptance tests fail on experiments that had no agent sessions |
| **Code/document graph** | Relationship graph (scripts ↔ loaders ↔ reports) | Recurring questions about *code* relationships that grep and agents answer poorly. Evaluate against the working atlas first |
| **Multi-project support** | More `projects/<name>/` entries | A second repo needs coverage. The layout already allows it; config currently describes one project |
| **Codex native memories** | Use Codex's own `memories/` feature as a cache | It proves useful alongside the atlas |
| **More Copilot Chat workspaces** | Chat history of further client workspaces | Questions about work done there; add another `--root` to the uploader or a `chat_dirs` entry (REFRESH.md step 0) |
| **Incremental Copilot upload** | Transfer only changed chat logs | Full-snapshot uploads (D24) become too slow or large |
| **Compaction history scanning** | Harvest paths from Codex `compacted.replacement_history` / `retained_context` | Path-recall audits show meaningful misses there (02, "Path harvesting") |

Principle (D2): every component must fix a limit that was actually observed in use.

## Built since the MVP

- **GitHub Copilot source** (D22, D23): Chat-panel op logs, Copilot agent sessions and server-side transcripts, in
  `atlaslib/sources/copilot.py`. The VS Code agent-host store (`agentSessionData/*/session.db`) is deliberately not
  read.
- **Client-side Copilot uploader** (D24): `tools/copilot_sync.py` + `atlas.py import-copilot`.
- **Per-session review ledger** (D25), **section-aware `find`** (D26).
