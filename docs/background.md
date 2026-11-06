# Background and scope

## Why it exists

ResearchAtlas was built for one long-running research project, where the same problem kept costing time: every new
coding-agent session started without knowing where anything was.

The project has a shape common in experimental research:

- **One repository, one folder per experiment.** Each experiment is a dated folder with its own scripts,
  notebooks, README and results files. New folders appear every week, and old ones are rarely cleaned up.
- **Data outside the repository.** Raw recordings live on network mounts and in a project database, at long
  absolute paths. Datasets have nicknames ("the October recordings") that no file records, and some paths move
  when data is archived.
- **Months of agent-driven work.** Most work happened in coding-agent sessions (Codex CLI, GitHub Copilot in VS
  Code, Claude Code), often several in parallel with subagents. Conclusions were revised as experiments
  continued: baselines were replaced, and earlier results were superseded.

The history of what was learned existed, but only inside hundreds of transcripts. A fresh session searched the
disk, guessed paths, picked a superseded dataset, or asked the user. Handwritten notes went stale. ResearchAtlas
turns the transcripts into a small, cited, verified knowledge base that sessions read first, and keeps it current
as work continues.

## Use so far

On that project, at the time of the first release (2026-11):

| | |
|---|---|
| Sessions indexed | 261 (183 top-level, the rest subagents and forks), March to November 2026 |
| Sources | Codex CLI 131, GitHub Copilot 109 (Chat panel and agent), Claude Code 21 |
| Transcripts | 5.1 GB raw, 19 MB after condensing |
| Paths harvested | ~31,000 unique, each verified on disk |
| Knowledge base | 11 Markdown files, ~490 KB |
| In daily use | since 2026-10-22 |

The [benchmark](benchmark.md) measures its effect on that project: with the atlas, both agents tested used about
half the tokens and wall time and answered as well or better.

## What it assumes

ResearchAtlas works best when a project looks like the one above. It fits well if:

- the research has a history spread over many agent sessions, not just a few;
- questions are about **data and results**: where things are, which version is current, what was concluded;
- data lives at absolute paths (local disks, network mounts) that agents mention in their sessions;
- experiments are organised as folders with their own results files, which the agent uses to check claims.

It helps less, or not at all, when:

- the project is mostly software, where code search already answers the questions (the benchmark's control
  questions showed the atlas costs nothing there, but also gains nothing);
- little of the work happened in coding-agent sessions;
- data is reached only through URLs or APIs rather than paths.

## Not yet tested

ResearchAtlas has been used on one project, by one person. These are open:

- **Several projects.** The config describes a single project, and the layout leaves room for more
  (`projects/<name>/`), but multi-project use has not been tried.
- **Memory across projects.** Whether knowledge from one project, such as a dataset shared by two repositories,
  helps agents in another is unknown. Nothing links knowledge bases today.
- **Other project shapes.** Flat repositories, notebook-only work, or projects without a folder per experiment.
- **Teams.** A shared atlas with several people's sessions, reviews and conflicting edits.
- **Other synthesis models.** The knowledge base was written by a frontier model orchestrating smaller subagents.
  Quality with smaller models alone is unmeasured.
- **Other platforms.** Real use was on a Linux server with a Windows client for Copilot Chat. CI runs the tests on
  Linux and macOS; Windows is supported only for the uploader script.
- **Other agent versions.** Transcript formats are undocumented and change. Parsers were written against Codex CLI
  0.117 to 0.161, Claude Code 2.1, and the Copilot formats of late 2026
  ([transcript-formats.md](transcript-formats.md)).

The [roadmap](roadmap.md) lists what would be built if these turn out to matter. Reports of use on other projects
are welcome.
