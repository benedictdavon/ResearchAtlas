# Documentation

ResearchAtlas mines coding-agent transcripts (OpenAI Codex CLI, Claude Code, GitHub Copilot), condenses them,
harvests absolute filesystem paths, verifies those paths against disk, and supports a curated, citation-backed
knowledge base (`projects/<project>/knowledge/*.md`) that coding agents read before guessing where data lives.

### Guides

| Page | Read it to |
|------|------------|
| [getting-started.md](getting-started.md) | Install, configure, build the first knowledge base and connect your agents |
| [refresh-guide.md](refresh-guide.md) | Keep the atlas current after new agent sessions |

### Reference

| Page | Contents |
|------|----------|
| [cli.md](cli.md) | Every command, its options, output and exit codes |
| [configuration.md](configuration.md) | The atlas home and every `config.toml` key |
| [knowledge-format.md](knowledge-format.md) | The knowledge files, entry rules, citations and path marks |
| [transcript-formats.md](transcript-formats.md) | Where each agent stores transcripts, their record formats, and the parsing rules `extract` implements |

### Design

| Page | Contents |
|------|----------|
| [background.md](background.md) | Why ResearchAtlas exists, the kind of project it was built for, and what hasn't been tested |
| [architecture.md](architecture.md) | Goal, non-goals, layout, the transcript-source interface and the generated data files |
| [design-decisions.md](design-decisions.md) | Decision log (D1–D29): what was decided, alternatives, and why. Code comments cite these numbers |
| [roadmap.md](roadmap.md) | Deferred components and the trigger that would justify building each |

### Evaluation

| Page | Contents |
|------|----------|
| [benchmark.md](benchmark.md) | Tokens, cost, time and answer quality with and without the atlas, for Claude Code and Codex |

### Agent prompts

Give these to a coding agent started in the atlas home.

| Prompt | Use |
|--------|-----|
| [initial-build.md](prompts/initial-build.md) | Build the first knowledge base from all indexed sessions |
| [incremental-update.md](prompts/incremental-update.md) | Apply a refresh report to the knowledge files |
| [claim-extraction.md](prompts/claim-extraction.md) | Subagent task: extract cited claims from a batch of sessions |
| [digest.md](prompts/digest.md) | Subagent task: condense the claims of one research track into a digest |

## Design principles

1. **Keep it simple.** Build a deferred component only when its trigger in roadmap.md actually happens.
2. **Read-only toward everything outside the atlas home**: research repos, data mounts, databases. The only
   external edit is the agent pointer line ([getting-started.md](getting-started.md#5-point-your-agents-at-the-atlas)).
3. **Transcripts are leads, not truth.** A past agent saying "the data is at X" stays a lead until a check against
   the filesystem confirms it. Path checks run with timeouts, because network mounts can hang.
4. **Every knowledge claim cites its source**: `[codex:<id13> <date>]`, `[claude:<id8> <date>]`,
   `[copilot:<id8> <date>]` or `[file:<path>]`.
5. **Python 3.11+, stdlib only.** After changing `atlaslib/`, run
   `python -m unittest discover -s tests` (synthetic data only, well under a second).
6. `work/` is generated and gitignored. `projects/<project>/knowledge/` and
   `projects/<project>/reviewed_sessions.jsonl` are the curated product. This public repo ignores `projects/`
   because it holds your research; keep it in a private repo or a private fork.
