# Instructions for coding agents

You are working on ResearchAtlas itself (not using an atlas). Read [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/README.md](docs/README.md) first.

- Python 3.11+, standard library only at runtime. The package is `atlaslib/`; the CLI entry is `atlaslib/cli.py`.
- After any code change run `python -m unittest discover -s tests` and `ruff check . && ruff format --check .`.
- Tests and examples use synthetic data only. Never read, copy or commit real transcripts from `~/.codex`,
  `~/.claude`, `~/.copilot` or VS Code storage, or anything from a user's atlas home.
- Parsing rules live in [docs/transcript-formats.md](docs/transcript-formats.md) and design choices in
  [docs/design-decisions.md](docs/design-decisions.md) (cited as D<n>). Update them with behavior changes.
- Path checks must keep their timeouts: network mounts can hang.
