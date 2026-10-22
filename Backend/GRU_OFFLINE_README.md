# Offline GRU fall-warning prototype

`train_gru_offline.py` trains a small CPU PyTorch GRU from the existing Unity
rows in each session's `raw.csv`. It defines the target at the end of each
causal window: the target is one only when a real `fall_event` occurs strictly
after that timestamp and no later than `--horizon-seconds`, in the same session
and contiguous `(run_id, platform_level)` segment. Rows at or after the first
fall event are excluded, so post-fall transitions cannot become negative
training examples or leak across a platform boundary.

The default command uses TEST9282, TEST930, and the included-clean TEST931
sessions for training and evaluates once on all TEST929 sessions. The split is
by complete session. To make a deterministic session split from custom
manifests, use `--random-session-split`; otherwise repeat
`--train-manifest` and `--heldout-manifest`.

```powershell
python train_gru_offline.py --out-dir gru_offline_results
```

The scaler stores feature medians and IQR (or standard deviation for a
constant-IQR feature) fit on training windows only. Missing and non-finite
telemetry is imputed with those training medians. The script reports both
window and session precision/recall/F1, the non-fall session false-alarm rate,
and first/last warning lead times. `baseline_comparison.csv` evaluates the
current Unity yellow warning and the frozen development-pool TTE rule on the
same held-out windows as the GRU.

Outputs are written to `gru_offline_results/`: `metrics.json`,
`baseline_comparison.csv`, `session_metrics.csv`, `session_split.csv`,
`training_history.csv`, `config.json`, and a copy of this run's assumptions in
`README.md`. If PyTorch is unavailable, labels and both baselines are still
replayed and the report records a clear install message while skipping only
the GRU fit.
