# Knowledge format

The knowledge base is a folder of Markdown files, `projects/<project>/knowledge/` in the atlas home. It is the
product: coding agents read it, and `refresh` and `find` parse it. A coding agent writes and updates it, following
the [agent prompts](prompts/); this page is the format those prompts produce. A complete small example is in
[examples/demo/knowledge/](../examples/demo/knowledge/).

## Files

Agents read the short `INDEX.md` first and open topic files only as needed (D10). One large file would cost every
session context and tends to be skipped.

| File | Contents |
|---|---|
| `INDEX.md` | At most ~60 lines: what each file holds, the main datasets at a glance, path abbreviations, how to search (`researchatlas find`, `grep -n`), when to run `refresh` |
| `datasets.md` | One section per logical dataset: name and aliases, type, verified paths with their roles (raw data, references, labels, configs), database tables if any, caveats, sources |
| `experiments.md` | Conventions, where the authoritative logs are, and an index of the track files |
| `experiments_<track>.md` | One `###` entry per experiment that matters: status, purpose, data, method, result, sources (D27) |
| `decisions.md` | Accepted and rejected hypotheses, baselines and rules, dated, with superseded markers |
| `recipes.md` | Short loaders for the main datasets. Each code block was run read-only before it was added and says which interpreter to use (D27) |
| `open_questions.md` | §1 questions for the user, §3 conflicts between sources; other sections as the project needs |

A small project can keep all experiments in `experiments.md`; split into track files when entries for one topic
start to scatter.

## Entries

```markdown
## Species labels
- **Current:** `BS/data/labels/v2/labels.csv` ✓ 2026-03-16, columns `clip,species`. [claude:8d2f4c1a 2026-03-09]
- **Superseded:** `BS/data/labels/v1/labels.csv` ✗ 2026-03-16, removed after the `site_b` relabel.
  [claude:8d2f4c1a 2026-03-09]
```

- **One entry per thing.** Each dataset and each experiment has exactly one section. New evidence updates it.
- **Current status first.** When a result or path is replaced, keep the old one, mark it **superseded** with the
  date and by what, and don't delete it. Agents then see both the answer and why an older one is wrong.
- **Specific and exact.** Copy numbers, dates and paths exactly from the source; don't round or merge.
- **Unsure means open.** Anything unclear, or two sources that disagree, goes to `open_questions.md` instead of
  being guessed.

## Citations

Every claim ends with at least one source:

| Form | Source |
|---|---|
| `[codex:0190abcd-1234 2026-01-02]` | Codex session, 13-character id (D15), date of the message that says it |
| `[claude:1a2b3c4d 2026-01-02]` | Claude Code session, 8-character id |
| `[copilot:5e6f7a8b 2026-01-02]` | GitHub Copilot session, 8-character id (D22) |
| `[file:experiments/run_01/README.md]` | A file in the research repo |

The condensed transcript for a session citation is `work/<project>/sessions/<source>_<id>.md`;
`researchatlas find <id>` locates it too.

When sources disagree, higher-ranked evidence wins (D13), and within a rank the newer one:

1. The current filesystem or project database (verified facts)
2. Recent transcripts and the experiment folders' own files (results, READMEs, logs)
3. Handoff or summary documents maintained in the research repo
4. Older transcripts
5. Documents known to be outdated

## Paths

| Mark | Meaning |
|---|---|
| `` `path` ✓ 2026-03-16 `` | Checked on disk on that date |
| `` `path` ✗ 2026-03-16 `` | Known to be gone since that date (kept so agents don't rediscover it) |
| `` `path` ? lead `` | Mentioned in a session, not verified |

Write paths in backticks. `refresh` re-checks every backticked path in `knowledge/*.md` and reports those that
broke, except `✗` ones ([cli.md](cli.md#refresh) has the exact rules). Long prefixes can be abbreviated, e.g.
`DP/experiments/run_01/`, with `DP` defined in `[knowledge].abbreviations`
([configuration.md](configuration.md#knowledge)); list the abbreviations in `INDEX.md` too.
