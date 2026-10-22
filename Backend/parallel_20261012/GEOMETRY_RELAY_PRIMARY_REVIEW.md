# Geometry relay and cancellation review — 2026-10-12

## Implementation decision

Backend independent geometric output is implemented in `parallel_20261011/realtime_integration/bridge.py` and `geometry_danger.py`. No Unity files, physics, labels, model features, weights, thresholds or model state machine were changed. No server was launched by this review.

The relay is experimental, not a prediction: valid fresh `directional_edge_distance - ball_radius <= 0` produces CRITICAL. Positive clearance produces CLEAR; missing/invalid/stale geometry produces UNKNOWN. CLEAR is not a general safety guarantee. Geometry never supplies a probability and is excluded from model F1. It can cover late geometric danger after model UNKNOWN, but does not improve early model detection.

Freshness uses Unity `time - geometry_source_timestamp` plus backend monotonic receipt age, with a total 0.3s maximum. Unix `timestamp` is used for source ordering, not subtracted from the Unity query clock. Explicit start_session ownership, geometry platform/version validity, layer lifecycle, duplicate/reordered data and fault isolation are enforced. Missing query-clock fields affect only geometry, not the existing model input contract.

Each reply shares a positive signed-64-bit warning_update_sequence across both objects. The Unity consumer must not drop the second object as a duplicate. Its disconnect timeout must add local monotonic elapsed time to the supplied geometry age, not reset the age with every repeated reply.

## Verification

Primary reran runtime tests: 87 executed, 86 passed, 1 skipped. Realtime integration tests: 41 passed, including five independent primary-review tests. Master startup and primary live regressions: 14 passed. Total: 142 executed, 141 passed, 1 skipped. These are automated tests, not live Unity UDP display acceptance.

Model.txt, manifest.json and warning_runtime.py SHA256 remain respectively:

* 01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068
* b75cac3173496171a9e2c17906938fc5bdac22243ff7f8ce5cee75b96900d29e
* a95cb6def1101e67b1c3c63c35e0924d36606caa7d076e241bc2b72b453672b3

## Separate offline cancellation experiment

Only existing TEST1009 development OOF was replayed: 6,898 rows, 30 sessions, 10 falls and 20 completed. This OOF already selected the deployment threshold; results are engineering/calibration diagnostics, not independent validation. No fitting or threshold search was performed. Primary reran the candidate script and verified the pinned model hash.

| Metric | Immediate low-score exit | Two consecutive low-score exit |
|---|---:|---:|
| Fall recall | 6/10 | 6/10 |
| Guaranteed geometric lead >=0.4s coverage | 4/10 | 4/10 |
| Completed-session alarm rate | 11/20 | 11/20 |
| Session F1 | 0.444 | 0.444 |
| Mean completed-session alarm duration | 0.26855s | 0.34050s |
| Episodes shorter than 0.2s | 17 | 13 |

Original entry logic is retained; one-low control matches the original strict replay across all 6,898 rows. Recovery, context and gap boundary controls also pass. Candidate first activation was not earlier in any session. Fewer short episodes are not evidence of earlier prediction.

Decision: reject this exit candidate. Completed-session burden increases by 0.07195s, above the preregistered 0.05s allowance. Keep the original cancellation and 0.3s stale invalidation. No second tuning attempt and no deployment of this candidate.

## Remaining work

Give `UNITY_GEOMETRY_RELAY_PROMPT.md` to the front-end-only Unity agent. Implement and test the independent display, then collect a short edge-approach/recovery run and restart run for real UDP acceptance. There is no need for a new large training batch for this functional change. Real display behavior remains unverified until then.
