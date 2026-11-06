# ResearchAtlas — Docs Index

ResearchAtlas mines coding-agent transcripts (OpenAI Codex CLI, Claude Code, GitHub Copilot), condenses them,
harvests absolute filesystem paths, verifies those paths against disk, and supports a curated, citation-backed
knowledge base (`projects/<project>/knowledge/*.md`) that coding agents read before guessing where data lives.

| File | What it gives you |
|------|-------------------|
| [02_transcript_formats.md](02_transcript_formats.md) | Where each agent stores transcripts, their record formats, and the parsing rules `extract` implements (what to keep, drop and scan; forks and subagents; path harvesting) |
| [03_decisions.md](03_decisions.md) | Decision log (D1–D29): what was decided, alternatives, and why. Code comments cite these numbers |
| [04_mvp_spec.md](04_mvp_spec.md) | Goal, layout, configuration, the CLI components (§1–§5), agent integration (§6), and acceptance tests |
| [06_future_work.md](06_future_work.md) | Deferred components and the trigger that would justify building each |
| [REFRESH.md](REFRESH.md) | How to refresh the atlas after new agent sessions (user guide) |
| [prompts/incremental_update.md](prompts/incremental_update.md) | Agent prompt for applying a refresh report to the knowledge files |

## Ground rules

1. **Keep it simple.** Build a deferred component only when its trigger in 06 actually happens.
2. **Read-only toward everything outside the atlas folder**: research repos, data mounts, databases. The only
   external edit is the agent pointer line (04 §6).
3. **Transcripts are leads, not truth.** A past agent saying "the data is at X" stays a lead until a check against
   the filesystem confirms it. Path checks run with timeouts, because network mounts can hang.
4. **Every knowledge claim cites its source**: `[codex:<id13> <date>]`, `[claude:<id8> <date>]`,
   `[copilot:<id8> <date>]` or `[file:<path>]`.
5. **Python 3.11+, stdlib only.** After changing `atlaslib/`, run
   `python -m unittest discover -s tests` (synthetic data only, well under a second).
6. `work/` is generated and gitignored. `projects/<project>/knowledge/` and
   `projects/<project>/reviewed_sessions.jsonl` are the curated product. This public repo ignores `projects/`
   because it holds your research; keep it in a private repo or a private fork.
