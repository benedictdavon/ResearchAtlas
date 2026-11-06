# Documentation

ResearchAtlas mines coding-agent transcripts (OpenAI Codex CLI, Claude Code, GitHub Copilot), condenses them,
harvests absolute filesystem paths, verifies those paths against disk, and supports a curated, citation-backed
knowledge base (`projects/<project>/knowledge/*.md`) that coding agents read before guessing where data lives.

| File | What it gives you |
|------|-------------------|
| [transcript-formats.md](transcript-formats.md) | Where each agent stores transcripts, their record formats, and the parsing rules `extract` implements (what to keep, drop and scan; forks and subagents; path harvesting) |
| [design-decisions.md](design-decisions.md) | Decision log (D1–D29): what was decided, alternatives, and why. Code comments cite these numbers |
| [architecture.md](architecture.md) | Goal, layout, configuration, the CLI components (§1–§5), agent integration (§6), and acceptance tests |
| [roadmap.md](roadmap.md) | Deferred components and the trigger that would justify building each |
| [refresh-guide.md](refresh-guide.md) | How to keep the atlas current after new agent sessions |
| [prompts/incremental-update.md](prompts/incremental-update.md) | Agent prompt for applying a refresh report to the knowledge files |

## Design principles

1. **Keep it simple.** Build a deferred component only when its trigger in roadmap.md actually happens.
2. **Read-only toward everything outside the atlas home**: research repos, data mounts, databases. The only
   external edit is the agent pointer line (architecture.md §6).
3. **Transcripts are leads, not truth.** A past agent saying "the data is at X" stays a lead until a check against
   the filesystem confirms it. Path checks run with timeouts, because network mounts can hang.
4. **Every knowledge claim cites its source**: `[codex:<id13> <date>]`, `[claude:<id8> <date>]`,
   `[copilot:<id8> <date>]` or `[file:<path>]`.
5. **Python 3.11+, stdlib only.** After changing `atlaslib/`, run
   `python -m unittest discover -s tests` (synthetic data only, well under a second).
6. `work/` is generated and gitignored. `projects/<project>/knowledge/` and
   `projects/<project>/reviewed_sessions.jsonl` are the curated product. This public repo ignores `projects/`
   because it holds your research; keep it in a private repo or a private fork.
