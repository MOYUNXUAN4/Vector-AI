# Offline GRU temporal-filter experiment

The GRU was trained once on complete development sessions from TEST9282, TEST930 and TEST931. The calibrated probability threshold was fixed at 0.75; TEST929 was held out until the final frozen evaluation and was not used for training or rule selection.

Windows use horizon=0.5s, window=1s, stride=0.25s and sequence_length=60. `raw_gru` is the thresholded probability stream. `consecutive_kN` emits only after N adjacent positive windows (within one segment). Cancellation methods reset the consecutive counter after a continuous inward radial velocity run (`< 0`) reaches the configured duration, so a new warning must satisfy the consecutive condition again.

Velocity comes from `target_edge_radial_velocity` when finite, with a row-level fallback to `ball_radial_velocity`. Sessions with neither field are explicitly marked `review_required_velocity_unavailable` in `config.json` and `session_metrics.csv`; no substitute field is guessed.

`comparison.csv` contains aggregate window and session metrics, including session precision/recall/F1, non-fall false-alarm rate, median last valid warning lead, non-fall warning duration and cancellation counts. `session_metrics.csv` retains each `session_id` and per-method detection/lead details; `warning_experience.csv` retains warning duration and cancellation counts per session. Figures are provided as PNG and PDF. No Unity, manifest or raw telemetry file was modified.
