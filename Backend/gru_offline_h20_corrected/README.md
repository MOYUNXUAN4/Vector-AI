# Offline GRU prototype results

Labels use a real telemetry `fall_event` strictly after the window endpoint and no more than `H` seconds later, with the event in the same session and contiguous `(run_id, platform_level)` segment. Rows at or after the first event in each session are excluded. All scaling statistics are fit on training-session windows only.

GRU status: **trained**.

`baseline_comparison.csv` contains window and session metrics for the current Unity yellow warning and the selected development-pool time-to-edge rule on the same held-out windows. `session_metrics.csv` contains first and last warning leads per session; `metrics.json` contains aggregate non-fall false-alarm rates and lead summaries.

The generated files are replay outputs. Raw telemetry, Unity files, and existing analysis scripts are not modified.
