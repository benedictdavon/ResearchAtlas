# Datasets

## March 2026 field recordings
- **Type:** raw audio, 16 kHz mono WAV, one folder per recording site (`site_a`, `site_b`).
- **Path:** `BS/data/raw/2026-03-field` ✓ 2026-03-16 [codex:019c3a1e-5b2f 2026-03-02]
- **Caveat:** `site_b` clips 40-80 were mislabeled in the first label set; use labels v2.
  [codex:019c3a1e-5b2f 2026-03-02] [claude:8d2f4c1a 2026-03-09]

## Species labels
- **Current:** `BS/data/labels/v2/labels.csv` ✓ 2026-03-16, columns `clip,species`. [claude:8d2f4c1a 2026-03-09]
- **Superseded:** `BS/data/labels/v1/labels.csv` ✗ 2026-03-16, removed after the `site_b` relabel.
  [claude:8d2f4c1a 2026-03-09]

## Evaluation split
- **Leave-one-site-out folds:** `BS/data/splits/site_folds.json` ✓ 2026-03-16. Use it for every comparison; a
  random split leaks site acoustics into the test set. [copilot:c41e9b07 2026-03-15]
