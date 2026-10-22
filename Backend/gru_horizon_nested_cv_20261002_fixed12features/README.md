# Nested session-grouped GRU horizon comparison

This offline experiment uses only the clean development manifests for TEST9282, TEST930, and TEST931. It compares 0.5, 0.75, 1.0, and 1.5 second target horizons. Each eligible complete session is assigned to exactly one outer test fold, with folds balanced by dataset and fall-session label.

For each outer fold and horizon, threshold selection uses only inner out-of-fold probabilities from the outer-training sessions. It searches 0.05 through 0.95 in 0.05 increments and applies the established 25% non-fall FAR / 60% recall rule. The outer fold is evaluated once after a fresh fit on the complete outer-training sessions. Every scaler is fit on the corresponding model-training windows only.

`pooled_outer_oof_metrics.csv` is the primary per-horizon summary. Session-level lead summaries include detected fall sessions only and use first target-positive warning onset; the last target-positive onset summaries are also recorded in `summary.json`. `missed_falls.csv`, split assignments, threshold grids, fold metrics, and fit audit are retained for review. No TEST1001, raw telemetry edits, or Unity edits are part of this run.
