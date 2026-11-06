# Experiments

Current status first in each entry.

### exp013: BEATs fine-tuning
- **Status:** current best.
- **Result:** macro-F1 0.78 on the leave-one-site-out split. [copilot:c41e9b07 2026-03-15]
- **Data:** labels v2, split `BS/data/splits/site_folds.json` ✓ 2026-03-16.
- **Output:** `BS/experiments/exp013_beats_finetune` ✓ 2026-03-16 [file:experiments/exp013_beats_finetune/results.json]

### exp012: CNN baseline
- **Status:** needs a rerun. Its 0.71 used a random split, so it is not comparable with exp013.
  [copilot:c41e9b07 2026-03-15]
- **Result:** macro-F1 0.71 (random split). [claude:8d2f4c1a 2026-03-09]
- **Output:** `BS/experiments/exp012_cnn_baseline` ✓ 2026-03-16 [file:experiments/exp012_cnn_baseline/results.json]
