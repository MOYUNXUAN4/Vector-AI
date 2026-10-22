# Five-layer compatibility fix and bounded verification

2026-10-20. Prospective runtime compatibility only. Historical P03 exposure is not rewritten.

## Change

The sole runtime-code change is `parallel_20261010/backend/runtime_adapter.py`: supported session totals `(3, 8, 10)` become `(3, 5, 8, 10)`. Model, features, thresholds, confirmation, recovery, input, geometry checks, clock/gap contracts and Unity are unchanged. No standalone rebuild or overwrite occurred.

Original adapter SHA-256: `0c4f638ac84b9aa1e1bddbf2b031a3fda497fe363cba808e2beee76444dfe7ff`.
New adapter SHA-256: `2afc653b2b19f3243c8b32ecbf235b1dae3a7ae98c90fb93d27055d4fcd70d16`.
Byte-exact original is saved as `luna_tests/runtime_adapter.py.original`; the old lock is `pre_change/preflight_lock.json`.

After reviewing the one-line diff, primary updated ONLY this adapter's expected hash in `parallel_20261016/pilot_readiness/tools/preflight_lock.json`. There remain 24 entries. All 24 pinned contents match; no other lock entry changed and no check was bypassed.

## Tests independently rerun by primary

| Suite | Total | Passed | Skipped |
|---|---:|---:|---:|
| Existing backend tests (adapter, guard, policy, features, artifact/runtime) | 92 | 91 | 1 |
| Existing realtime integration | 41 | 41 | 0 |
| Existing proximity shadow | 8 | 8 | 0 |
| Existing proximity reply | 11 | 11 | 0 |
| Existing preflight synthetic tests | 16 | 16 | 0 |
| Added scoped five-layer compatibility | 7 | 7 | 0 |
| Added primary three-channel checks | 3 | 3 | 0 |
| Total | 178 | 177 | 1 |

One existing symlink-escape test was skipped because symlinks are unavailable, not counted as a pass. Existing bridge tests include read-only native artifact loading with synthetic input; no retraining or inference on participant data occurred. No network service was launched. Injected local-log-failure messages in the proximity tests are expected negative-case fixtures, not a live backend failure.

Five-layer tests retain default-off calibration compatibility, reject out-of-range/malformed totals and layers, wrong ownership/version and invalid measurements, and preserve gap/warmup behavior. Primary independently tested five-layer confirmed model state with a mock predictor, real geometry-rule CRITICAL while model is synthetically unavailable, and TTE APPROACH followed by stale fail-closed. These exercise protocol generation, not Unity rendering or real participant benefit. None of these mock probabilities are live model-performance evidence.

Static preflight executed with the four expected flags in the child inspection process and the pinned Python, without starting servers. It passed: `preflight_receipts/preflight_071b738eaa2c429caf65599f85b9349e.json`. This is not live runtime acceptance.

## Historical data condition

P03 keeps its intended experimental-on assignment AND an actual-unavailability condition. User observed no experimental banners and matched shadow evidence is uniformly unavailable. Do not count these six runs as normally functioning warning-on exposure, relabel them as randomized controls, erase them from system coverage, or substitute post-fix replay for historical display. Sidecar: `../p03_banner_review_primary/CONDITION_RECEIPT.json`. Raw files and prior evidence remain intact.

## Run check still required

Close any old backend manually, then use the SAME `Start_Pilot_10P_Experimental.cmd` and existing normal standalone VectorAI.exe. Choose sensitivity display 0.55, difficulty 3 and 5 layers, old separate banners. Use an operator-only short run, not a participant ID. Observe one safe approach/recovery; do not force a fall or require all three cue types. Save to `OPERATOR_D3_L5_CHECK` and verify CSV/run identity, backend availability and actual client activation/display before resuming fixed-condition participant collection.

No service was auto-started, no process was killed, and no user setting was changed. Restart is needed so a future backend process loads the new adapter.
