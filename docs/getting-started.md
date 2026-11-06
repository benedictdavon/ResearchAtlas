# Getting started

From installation to agents that answer "where is the data?" from a verified knowledge base. To see the whole
cycle first, run the [demo](../examples/demo/); it needs no configuration.

## 1. Install

Python 3.11 or newer, no other dependencies:

```bash
pip install git+https://github.com/benedictdavon/ResearchAtlas.git
researchatlas --version
```

Or work from a clone: `python atlas.py <command>` is the same CLI, and the checkout itself becomes the atlas home.

## 2. Create and configure the atlas home

```bash
researchatlas init                       # writes ~/.researchatlas/config.toml (or $RESEARCHATLAS_HOME)
$EDITOR ~/.researchatlas/config.toml
```

Set at least:

- `[sources]`: where your agents keep transcripts. The defaults match standard installs of Codex, Claude Code and
  Copilot; delete the keys of agents you don't use.
- `[project].name` and `roots`: the research repo(s). Sessions started there, or mentioning them, are selected.
- `[paths].roots`: the project folders plus your data mounts. Only paths under these are harvested and verified.

Every key is described in [configuration.md](configuration.md). Run all commands below from the atlas home
(`cd ~/.researchatlas`).

## 3. Index your sessions

```bash
researchatlas extract
researchatlas paths
```

Check the summaries:

- `extract` prints how many sessions were selected and why (`by cwd`, `by parent`, `by mention`). Too few: widen
  `roots` or add `cwd_also`. Unrelated sessions: narrow `roots`, or add `exclude_cwd` / `exclude_ids`.
- `paths` lists the most-used paths and how many exist. Many `missing` paths usually mean scratch files or data that
  has since moved, which is exactly what the knowledge base will sort out.

Skim a condensed session in `work/<project>/sessions/` to see what the agent in the next step will read.

## 4. Build the first knowledge base

Save a refresh report. At this point it lists every session as new:

```bash
researchatlas refresh > work/<project>/refresh_$(date +%Y%m%d).txt
```

Then start Claude Code, Codex or Copilot **in the atlas home** and say:

> Follow `<prompts>/initial-build.md` with the report `work/<project>/refresh_<YYYYMMDD>.txt`.

`<prompts>` is [`docs/prompts/`](prompts/) in your clone; with a pip install, download the four prompt files from
the repository first. The agent reads the sessions (or has subagents extract cited claims from them, for larger
projects), checks results against the experiment folders' own files, writes the knowledge files in the
[knowledge format](knowledge-format.md), verifies every cited path and records the sessions it covered with
`mark-reviewed`. Sessions started in the atlas home are never indexed (D16), so this work isn't mistaken for
research.

Then review the result: read `INDEX.md` and `datasets.md`, and answer the questions in `open_questions.md` §1 in
the chat. This review is where you catch what transcripts got wrong. Keep the atlas home in a private git repository
so every later update is a reviewable diff.

## 5. Point your agents at the atlas

Agents need to know the atlas exists. Add a few lines to each agent's global instruction file, such as
`~/.codex/AGENTS.md` (Codex) or `~/.claude/CLAUDE.md` (Claude Code), or the equivalent for other agents:

```markdown
For <project> data locations and research history, read
~/.researchatlas/projects/<project>/knowledge/INDEX.md before guessing paths or asking the user.
Search with: researchatlas find <words>
```

Optionally add the same lines to the research repo's own `AGENTS.md`, with the repo owner's approval; this is the
only change ResearchAtlas suggests outside its home. In a shared repo, keep the line local (for example, list the
file in `.git/info/exclude`).

Check that each agent actually loads its global file: ask a fresh session what its instructions say about
`<project>`.

## 6. Check that it works

Ask real questions in a fresh session started in the research repo, without giving any paths. Use a session that
isn't saved (`codex exec --ephemeral`, `claude -p --no-session-persistence`), or add its id to
`[project].exclude_ids` afterwards, so the test answers never become evidence (D20).

| Ask | Pass if |
|---|---|
| "Where is the raw data for <main dataset>, and what are its references or labels?" | Correct, verified paths, and database tables if any |
| "Which recordings pair with which reference files, and which pairings are validated?" | Paths, pairings and caveats stated correctly |
| "Where is the <month> data?" | Correct paths, distinguished from similar datasets |
| "Which experiments tested <method>, and what was concluded? Is <baseline> still current?" | Correct folders, conclusions and current vs. superseded status, with sources |
| Ask about a dataset that doesn't exist | The agent says it isn't known and doesn't invent a path |
| Rename a cited test path, then run `refresh` | The path is reported missing, not silently kept as verified |

## 7. Keep it current

After sessions that produce results or move data, run `refresh`, have an agent apply the report with
`incremental-update.md`, and review the diff. The [refresh guide](refresh-guide.md) has the full workflow, including
uploading Copilot chats from a client PC.
