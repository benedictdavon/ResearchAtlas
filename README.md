# ResearchAtlas

A small, stdlib-only tool for building a **verified, citation-backed knowledge base from your past coding-agent
sessions**. Coding agents can then find datasets, scripts and research history without you supplying paths.

Long-running research leaves its context scattered across hundreds of Codex, Claude Code and GitHub Copilot
transcripts: which dataset lives where, which experiment produced which result, why a decision was made. A fresh
agent session knows none of it, so it guesses paths or asks you. ResearchAtlas mines those transcripts, checks every
path they mention against the filesystem, and supports a curated `knowledge/` folder that agents read first.

Principles:

- **Transcripts are leads, not truth.** A past agent saying "the data is at X" is only a lead until a timeout-guarded
  check confirms that X exists.
- **Every claim cites its source**: `[codex:<id13> <date>]`, `[claude:<id8> <date>]`, `[copilot:<id8> <date>]` or
  `[file:<path>]`, so you can trace it back and re-verify it.
- **Small and simple.** Python 3.11+, standard library only, plain Markdown and JSONL, no database or service.

## How it works

```
Codex / Claude Code / Copilot transcripts
        │  researchatlas extract   select sessions for your project, condense them, harvest absolute paths
        ▼
work/<project>/sessions/*.md   + sessions.jsonl + per-session path hits
        │  researchatlas paths     aggregate paths, verify each on disk (with timeouts)
        ▼
work/<project>/paths.jsonl
        │  synthesis (an agent, guided by docs/prompts/)  →  curated, cited knowledge
        ▼
projects/<project>/knowledge/INDEX.md, datasets.md, experiments.md, decisions.md, ...
        │  researchatlas refresh / mark-reviewed   incremental updates as new sessions arrive
        │  researchatlas find <words>              agents search knowledge, paths and sessions
```

The deterministic steps (`extract`, `paths`, `refresh`, `find`) use no LLM. Writing `knowledge/` is done by a coding
agent following the prompts in [docs/prompts/](docs/prompts/), and every claim must carry a citation.

## Quick start

```bash
pip install git+https://github.com/benedictdavon/ResearchAtlas.git   # Python 3.11+, no dependencies
researchatlas init                        # writes ~/.researchatlas/config.toml (or $RESEARCHATLAS_HOME)
$EDITOR ~/.researchatlas/config.toml      # transcript locations, project roots, data mounts
researchatlas extract                     # condense + index matching sessions into work/
researchatlas paths                       # verify harvested paths → work/<project>/paths.jsonl
researchatlas find "dataset" "train"      # search (all words in one section / path / message)
```

Working from a clone instead? `python atlas.py <command>` runs the same CLI, and the checkout itself is the atlas
home, so `config.toml`, `work/` and `projects/` sit next to the code (all gitignored).

Then have an agent write `projects/<project>/knowledge/` in the atlas home from the condensed sessions and verified paths. The format
and rules are in [docs/04_mvp_spec.md](docs/04_mvp_spec.md) §3. Once the knowledge exists, keep it current:

```bash
researchatlas refresh | tee work/<project>/refresh_$(date +%Y%m%d).txt   # sessions to review, broken cited paths, new paths
# an agent applies the report to knowledge/ (docs/prompts/incremental_update.md), then:
researchatlas mark-reviewed --report work/<project>/refresh_<YYYYMMDD>.txt
```

See [docs/REFRESH.md](docs/REFRESH.md) for the full workflow.

### Point your agents at it

Add a few lines to your global agent instructions (`~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`) or to the research
repo's `AGENTS.md`:

```markdown
For <project> data locations and research history, read
~/.researchatlas/projects/<project>/knowledge/INDEX.md before guessing paths or asking the user.
Search with: researchatlas find <words>
```

### Copilot chats from a Windows PC (optional)

VS Code Chat logs live on the client machine. [tools/copilot_sync.py](tools/copilot_sync.py) (Python 3.9+, stdlib)
previews and uploads only the chat logs of the workspaces under `--root` over SSH. The server side receives them
with `researchatlas import-copilot`. Preview is the default:

```bash
python tools/copilot_sync.py --root /home/user/research/demo_project
python tools/copilot_sync.py --root /home/user/research/demo_project --upload --host user@server --atlas-dir /home/user/.researchatlas
```

## Does it help? (benchmark summary)

A sandboxed four-arm benchmark (method in [docs/03_decisions.md](docs/03_decisions.md), D28) ran Claude Code and
Codex non-interactively on 9 research questions about a real project, plus 2 control questions. The arms were:
- `none`: no atlas
- `atlas`: the pointer line
- `dump`: read the whole knowledge dir
- `hint`: a user-typed folder hint

Ratios are relative to `none`: the geometric mean over questions, with bootstrap 95% CIs.

| agent | arm | tokens × none | cost × none | wall time × none | pass rate |
|---|---|---|---|---|---|
| Claude Code | none | – | – | – | 20/27 |
| Claude Code | **atlas** | **0.49** (0.41–0.58) | **0.65** (0.55–0.75) | 0.42 | **26/27** |
| Claude Code | dump | 1.57 | 2.62 | 0.47 | 17/18 |
| Claude Code | hint | 1.05 | 1.06 | 0.74 | 13/18 |
| Codex | none | – | – | – | 13/15 |
| Codex | **atlas** | **0.42** (0.34–0.53) | **0.59** (0.50–0.68) | 0.43 | **15/15** |
| Codex | dump | 3.74 | 2.35 | 1.87 | 12/13 |
| Codex | hint | 0.92 | 0.98 | 0.99 | 10/15 |

- The atlas pointer roughly **halved token use** and **cut wall time by more than half**, with the same or better
  answer quality.
- On control questions that don't need the atlas, the pointer cost nothing measurable (0.96× and 1.00× tokens).
- Dumping the whole knowledge base into context gave similar quality at 1.6–3.7× the tokens.
- A folder hint did not substitute for the atlas.

These numbers are from one project with 9 questions, so treat them as indicative.

## Repository layout

| Path | What |
|---|---|
| `atlaslib/` | CLI and library: `sources/` (Codex, Claude Code, Copilot parsers), `extract`, `paths`, `refresh`, `review`, `find` |
| `tools/copilot_sync.py` | Client-side Copilot chat uploader |
| `atlas.py` | Runs the CLI from a source checkout |
| `tests/` | Unit tests on synthetic transcripts: `python -m unittest discover -s tests` |
| `docs/` | Transcript formats, design decisions, spec, refresh guide, agent prompts ([index](docs/README.md)) |
| `atlaslib/config.example.toml` | Template that `researchatlas init` copies to `config.toml` |
| `work/`, `projects/` | Generated intermediates and your knowledge bases. Both are gitignored here: they contain your private research |

## License

[MIT](LICENSE)
