# birdsong: research atlas

Species classification from field recordings. Read this before guessing paths or asking the user.

| File | What it holds |
|---|---|
| [datasets.md](datasets.md) | Recordings, labels and splits, with verified paths and caveats |
| [experiments.md](experiments.md) | Experiments, results and their current status |
| [decisions.md](decisions.md) | Accepted and rejected choices, with dates |

**At a glance**
- Raw recordings (March field campaign): `BS/data/raw/2026-03-field` ✓ 2026-03-16
- Current labels: `BS/data/labels/v2/labels.csv` ✓ 2026-03-16 (v1 is superseded)
- Evaluation split: `BS/data/splits/site_folds.json` ✓ 2026-03-16 (leave one site out)

Abbreviations: `BS` = the birdsong repo, `ARCH` = the archive share (see `config.toml`).
Search: `researchatlas find <words>`. Paths marked ✓ were verified on disk on that date; `refresh` re-checks them.
