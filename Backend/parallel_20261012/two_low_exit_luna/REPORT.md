# Two-low active-exit comparison

## Decision

The single candidate fails the predeclared screening rule and should not be advanced as a deployment policy. The baseline replay exactly reproduced the locked selected-threshold metrics, so the comparison is reportable. The candidate kept recall, geometric coverage, session F1, completed-session alarm rate, and first activation times unchanged, and reduced short episodes by four. Its completed-session warning burden rose by 0.07195 seconds per session, exceeding the allowed 0.05 seconds.

This uses development OOF scores that already selected the 0.65 threshold. It is an engineering calibration diagnostic, not independent efficacy or generalization evidence, and does not authorize deployment.

## Method and review correction

The script imports `deployment_refit.setup()` and its existing replay/evaluation functions, loads the locked 30-session OOF CSV and baseline prepared labels/manifest/anchors, and does not call fitting, calibration, or `main()`. The baseline and candidate both use the same `candidate_metrics(per_session, events, "strong")` and strict event matcher.

The first implementation was corrected after primary review because it had reset raw-entry continuity differently at recovery/context boundaries. Final results below are from the corrected script: the original `threshold_policy` now supplies raw and two-point entry confirmation unchanged; only an already-active warning's exit is held through one low evaluation. Synthetic checks verify row-by-row baseline parity across recovery followed by high scores, platform context change, and a gap, and separately verify first-low hold / second-low exit. A full 6,898-row parity control with exit count set to one matched the baseline on all rows (0 mismatches).

## Results

| Measure | Immediate raw-OFF baseline | Two-low candidate |
|---|---:|---:|
| Precision | 0.35294 | 0.35294 |
| Recall | 0.60 (6/10 exits) | 0.60 (6/10 exits) |
| F1 | 0.44444 | 0.44444 |
| Guaranteed geometry lead ≥0.4 s | 0.40 (4/10 formal exits) | 0.40 (4/10 formal exits) |
| Formal exits with missing geometry anchor | 0/10 | 0/10 |
| Completed-session alarm rate | 0.55 (11/20) | 0.55 (11/20) |
| Completed-session mean alarm duration | 0.26855 s | 0.34050 s |
| Alarm-duration increase | — | +0.07195 s/session (fails +0.05 s cap) |
| Episodes | 31 | 31 |
| Episodes shorter than 0.2 s | 17 | 13 |
| First activations earlier than baseline | — | 0 sessions |

The pending first-low interval added 1.557 seconds of active display across the cohort. Active exits recorded 26 second-consecutive-low exits and 5 immediate exits for invalid/nonpositive clearance. All 30 session-by-session baseline/candidate records, including paired event counts, episode and duration differences, first activation, completion duration, and first/last pre-event lead, are in `two_low_exit_report.json`.

The lead fields use the original strict actual-ON, exact-identity event matcher and distinguish first from last qualifying pre-event episodes. They do not reinterpret longer display continuity as earlier prediction; the first activation time was unchanged in every session. Candidate event matching and per-session outcomes are retained in the report for audit.

## Integrity

Before/after SHA-256 hashes for the OOF file, model artifact, and prepared input files are recorded in the JSON report; no hash changed during the run. No model fitting, score grid, threshold adjustment, source-file edit, or production policy change was performed. The JSON contains the exact baseline replay gate, candidate metrics, paired session details, exit reasons, synthetic checks, hashes, and screening gates.
