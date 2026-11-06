# Contributing

Thanks for your interest in ResearchAtlas. Bug reports, transcript-format updates and focused pull requests are
welcome.

## Development setup

```bash
git clone https://github.com/benedictdavon/ResearchAtlas.git
cd ResearchAtlas
python -m venv .venv && . .venv/bin/activate
pip install -e . ruff==0.17.4
```

Run the checks before opening a pull request:

```bash
python -m unittest discover -s tests   # unit tests + demo smoke test, about a second
ruff check . && ruff format --check .
python examples/demo/run_demo.py       # optional: the end-to-end workflow
```

## Guidelines

- **Standard library only** at runtime, Python 3.11+. Development tools (ruff) are fine.
- **Synthetic test data only.** Never commit real transcripts, paths or knowledge files. They can contain private
  research, credentials or personal data. Build fixtures with the helpers in `tests/`.
- **Transcript formats change between agent versions.** If a parser misses something, add a test with a minimal
  synthetic record of the new shape and describe it in [docs/transcript-formats.md](docs/transcript-formats.md).
- **Design changes get a decision entry.** Add a numbered entry to
  [docs/design-decisions.md](docs/design-decisions.md) (decision, alternatives, why) and cite it in code comments
  where the behavior isn't obvious.
- **Keep it small.** New components start in [docs/roadmap.md](docs/roadmap.md) with the trigger that would justify
  them.
- Keep the docs and [CHANGELOG.md](CHANGELOG.md) in step with behavior changes. Commit subjects are short and
  imperative ("Add X", "Fix Y").

## Reporting bugs

Open an issue with the command, the full output and your Python and agent versions. Redact paths and transcript
content first. For security issues, see [SECURITY.md](SECURITY.md).
