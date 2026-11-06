# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-06

### Added
- Benchmark results for smaller models (Claude Haiku 5.5 and gpt-6-luna) in the benchmark report.

### Changed
- Benchmark report: corrected the first run's answer key for A3's database status and regraded that item; excluded
  one run that saw an expected answer. Figures updated.

## [0.1.0] - 2026-11-06

First public release.

### Added
- `researchatlas` CLI, installable with pip (Python 3.11+, no dependencies), also runnable as `python atlas.py`
  from a source checkout. Config, generated files and knowledge bases live in one atlas home
  (`$RESEARCHATLAS_HOME`, the source checkout, or `~/.researchatlas`); `researchatlas init` creates it.
- `extract`: select a project's sessions from OpenAI Codex CLI, Claude Code and GitHub Copilot (VS Code Chat,
  Copilot agent and VS Code Server) transcripts, condense them to Markdown and harvest the absolute paths they
  mention. Incremental: unchanged transcripts are reused.
- `paths`: aggregate harvested paths and verify each one on disk, with per-path timeouts for network mounts.
- `refresh` and `mark-reviewed`: report sessions to review, cited paths that broke, new uncited paths and sessions
  that found the atlas wrong; a review ledger records what the knowledge base covers.
- `find`: search the knowledge base by section, then verified paths, then condensed sessions.
- `import-copilot` and `tools/copilot_sync.py`: preview and upload selected VS Code Chat logs from a client PC
  over SSH.
- Agent prompts for building the first knowledge base and for applying a refresh report.
- Documentation by reader: getting started, refresh guide, CLI, configuration and knowledge-format references,
  transcript formats, architecture, design decisions, background and scope, and a benchmark report.
- End-to-end demo on a fictional project (`examples/demo`).
- CI on Ubuntu and macOS with Python 3.11 to 3.13.

[Unreleased]: https://github.com/benedictdavon/ResearchAtlas/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/benedictdavon/ResearchAtlas/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/benedictdavon/ResearchAtlas/releases/tag/v0.1.0
