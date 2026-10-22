# Streaming validity scaffold

`stream_guard.py` is a standard-library-only, import-safe guard for normalized Unity telemetry dictionaries. A caller must explicitly claim a run with `begin_run(run_id)`; packets cannot take ownership by changing `run_id`. Platform instance IDs must be integers other than Unity sentinels `-1`, `0`, and `-2147483648`; negative IDs are accepted. Layers must be positive integers. Pass receive timestamps from a monotonic clock to `ingest(sample, receive_time)` and `snapshot(now_monotonic)`. Source timestamps are checked only for ordering, gap, and warmup span; they are never subtracted from receive time.

The guard retains at most `max_samples` accepted packets. It resets history on invalid input, context changes (run, platform instance, layer, or geometry version), source gaps above the configured limit, sequence discontinuities, calibration, or terminal run states. Duplicate or older packets in the active run are rejected, including packets from an older platform context. A stale stream becomes unknown and its history is cleared. `snapshot` returns deep-copied dictionaries, readiness, and a reason. `status()` emits only a strict JSON-safe UNKNOWN status with the predictor disabled.

Raw `calibration_mode=True` packets are rejected by default. The experimental `allow_calibration_session_gameplay=True` option accepts them only when the caller also supplies strict boolean `gameplay_phase_valid=True`; it preserves the raw calibration flag. The caller must derive this phase flag from its reviewed session, platform, and layer rules. The guard does not determine gameplay phase itself.

As of 2026-10-19, the shared `runtime_adapter.py` admits explicitly selected session totals 3, 8 or 10, with integer-normalized current layers from 1 through that total and finite platform scale in `(0, 2]`. Initial large calibration platforms, terminal states, invalid geometry and unsupported totals are not admitted. This expands experimental execution compatibility only; it does not validate predictor performance in extended sessions. Unity currently offers 10 (not 8) in its layer menu. Three-layer and ten-layer collection conditions must be recorded separately. See `parallel_20261019/multilayer_backend/REPORT.md` for verification and restart instructions.

Defaults (`warmup_seconds=0.5`, `stale_timeout=0.3`, `max_source_gap=0.1`, `max_samples=128`) are scaffold parameters, not validated operating thresholds. This module does not implement feature construction, a predictor, a state machine, probability estimates, or full runtime parity. It makes no inference and does not establish safety.

Run the focused checks from this directory:

```powershell
python -m unittest -v test_stream_guard.py
```
