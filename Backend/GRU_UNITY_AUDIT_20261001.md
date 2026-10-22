# GRU prototype and Unity warning audit — 2026-10-01

## Evaluation target

At telemetry time `t`, a window is positive only when the same session and the
same contiguous `(run_id, platform_level)` segment contains a real Unity
`fall_event` in `(t, t + H]`. Rows at or after the first event are excluded.
All splits are by complete session.  Session recall therefore means that at
least one alarm landed on a positive future-horizon window; an alarm elsewhere
in a fall session is recorded as off-target instead of being counted as a true
positive.

## Frozen TEST929 comparison

The model was trained on the included clean scope of TEST9282, TEST930 and
TEST931 (117 usable sessions, 48 fall sessions) and evaluated once on TEST929
(30 sessions, 10 fall sessions).  The threshold was kept at 0.5 for this
prototype; it was not tuned on TEST929.  The current-yellow comparator uses the
user-visible `prediction_state=EDGE WARNING`, not only the lower-level
`edge_warning_state` transition flag.

| Forecast horizon | Method | Session precision | Recall | F1 | Non-fall false-alarm rate | Median last valid lead |
|---:|---|---:|---:|---:|---:|---:|
| 0.3 s | Current Unity yellow | 55.6% | 50.0% | 52.6% | 20.0% | 0.135 s |
| 0.3 s | Time-to-edge | 66.7% | 60.0% | 63.2% | 15.0% | 0.152 s |
| 0.3 s | GRU | 50.0% | 60.0% | 54.5% | 30.0% | 0.185 s |
| 0.5 s | Current Unity yellow | 55.6% | 50.0% | 52.6% | 20.0% | 0.150 s |
| 0.5 s | Time-to-edge | 70.0% | 70.0% | 70.0% | 15.0% | 0.152 s |
| 0.5 s | GRU | 53.3% | 80.0% | 64.0% | 35.0% | 0.378 s |
| 1.0 s | GRU | 42.1% | 80.0% | 55.2% | 55.0% | 0.894 s |
| 2.0 s | GRU | 30.8% | 80.0% | 44.4% | 90.0% | 1.429 s |

Interpretation: GRU has started to learn an earlier signal, especially at
`H=0.5 s`, but it is not ready for Unity integration.  It gains roughly 0.23 s
of median lead over the current warning at H=0.5, while adding 15 percentage
points of non-fall session false alarms.  Longer horizons mainly increase
false alarms.

Files:

- `train_gru_offline.py`
- `gru_offline_h03_corrected/`, `gru_offline_h05_corrected/`, `gru_offline_h10_corrected/`, `gru_offline_h20_corrected/`
- `gru_offline_comparison/corrected_session_comparison.csv`
- `gru_offline_comparison/figure_corrected_gru_comparison.png`

## Unity warning audit

Read-only audit of all fall-event sessions in TEST9282, TEST929, TEST930 and
TEST931 found 63 fall sessions (16/10/15/22 by dataset). Every one had at least
one pre-event `prediction_state=EDGE WARNING` row and at least one
`edge_warning_state=true` row. Thus the logs do not show a true “yellow never
emitted” failure. They show a warning that is usually too late to notice:

- median onset of the last yellow episode: about 0.20 s before `fall_event`;
- 40 of 63 fall sessions had less than 0.20 s of last-episode lead;
- 24 of 63 had a backend timestamp gap above 0.10 s somewhere before the
  event, so short episodes can still be visually easy to miss;
- 13 sessions had one stale packet where geometry had crossed the threshold
  but `edge_warning_state` was still false; the next packet was yellow.  This
  is an update-order/state-consistency issue, not a complete missing warning.

The current yellow band is approximately `platform_radius - 2 * ball_radius`.
The controller and telemetry both use an inscribed AABB approximation
(`min(radiusX, radiusZ)`) rather than a directional closest-point distance.
Platform replacement also clears warning state and timestamps; three audited
sessions showed a new-platform packet resetting the warning timestamp at the
fall event.

The hole/blue-attention suppression is not the cause of these edge-warning
misses: fall-event packets had no terminal `AT_HOLE` or `APPROACHING_HOLE`
state.

## Next actions

1. Keep the GRU offline.  Calibrate its threshold on complete development-side
   validation sessions and target a non-fall false-alarm rate no higher than
   20–25% before claiming an improvement.
2. Make `prediction_state`/HUD yellow the canonical evaluated warning field;
   keep `edge_warning_state` as the controller transition state, but log both.
3. In Unity, evaluate the player edge state before the telemetry send (or send
   in `LateUpdate` with an explicit script execution order) and emit one
   transition packet after platform replacement.
4. Replace the duplicated radial/AABB geometry calculation with one shared
   directional collider query used by controller, telemetry and HUD.
5. Add platform-transition marker, warning reset reason and warning episode
   counters to the backend logger.  Then collect a small post-fix TEST932 with
   controlled recoveries and real exits before considering GRU integration.

Raw CSV files, Unity files and existing cleaning outputs were not modified by
the offline analyses.
