# Realtime backend integration review

Scope: experimental Falling warning output, default OFF. No Unity edits, service launch, new training, threshold changes, or frozen-set evaluation.

## Implemented

`UDPRecevier.py` initializes the opt-in bridge, binds explicit `start_session.run_id`, ingests Unity telemetry before the first-layer early-return, and adds `model_warning` at both existing realtime reply sites. Existing COP, RMSE and difficulty outputs remain separate. Default OFF returns the original response unchanged and does not import/load LightGBM.

Artifact: `deployment_refit/output/artifact/manifest.json`; model SHA-256 `01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068`. Strong threshold remains 0.65; horizon remains 0.75 s; 24 features, two-point confirmation and physical recovery cancellation are unchanged. This is NOT a performance-accepted model.

The bridge rejects foreign/closed runs and delayed terminal packets. Invalid geometry resets the segment without permanently closing its owner. New runs and context changes require fresh warmup. Stale input, model/hash/load/predict failures and bridge exceptions produce UNKNOWN, not a safe claim. An exception in experimental ingestion does not interrupt legacy packet processing. A missing start run ID cannot leave an old STRONG alert visible, including when lifecycle cleanup raises.

## Independent primary review

| Check | Result |
|---|---|
| Existing runtime regression suite | 86 passed; 1 skipped |
| New bridge suite, rerun by primary | 10 passed |
| Primary native-load/policy/failure/hook tests | 6 passed |
| Receiver/bridge syntax compilation | Passed |
| Primary raw-to-feature audit | 239 rows in first/last session; all 24 features and platform/layer/version match |
| Primary source/artifact integrity check | All 30 original CSV hashes and pinned native model hash verified |

Total unit tests: 103 executed, 102 passed, 1 skipped. Some policy/fault tests override scores locally to force a STRONG state; these are not model quality measurements. The actual pinned model is loaded first, and no artifact is altered.

Raw stream replay uses 30 TEST1009 development sessions and 37,087 Unity rows. The compatible runtime pass accepted 28,061 rows and produced 24,748 valid warning outputs. All 6,898 prepared feature identities were matched, with zero feature mismatches under 1e-6 absolute/relative tolerance. The 6,667 same-model probability comparisons were exactly equal. Ninety-three prepared vectors were ineligible due to nonpositive clearance or physical radius; other unmatched probability comparisons do not imply a feature mismatch. Original raw hashes were unchanged. Replay is an implementation-parity check on development data, not an independent performance test.

The prepared and runtime history windows also agree: 95 segments map one-to-one to 95 runtime generations, with no split/merge and zero history-start/span deltas across all 6,898 rows. The new bridge produced exactly matching warning outputs on all 28,061 accepted rows. Nine separately labelled synthetic failure probes passed; the prediction-exception probe records exactly one injected predictor call before UNKNOWN/prediction_failed.

Final bridge-only verification also checked all 9,026 rejected real rows: every row was UNKNOWN, valid=false and probability_valid=false, with zero alert leaks. Invalid-owner/calibration-phase packets (8,996) and ended packets (30) are reported separately; rejection reason text is not claimed identical to the direct runtime. The main agent independently checked the final JSON acceptance counters and all-pass failure-probe flag. Strict/compatible runtime results were preserved from the earlier pass; the latest bridge verification used the final bridge code and rechecked all original CSV hashes.

Local runtime ingest-plus-warning timing was P50 1.724 ms, P95 2.8033 ms and P99 3.2697 ms in the reported pass. These are process-local measurements, not Unity display or network latency, and not a guarantee for all hardware or gameplay loads.

Strict calibration exclusion accepted zero historical rows: these runs retain `calibration_mode=true`. The explicit three-layer gameplay compatibility option is required for this collection mode; it still excludes the separate calibration phase using layer/scale checks. Do not clear or relabel the raw flag.

## Starting an experimental check

Use the project Python environment containing LightGBM. In the SAME terminal/process environment used to launch the existing backend:

```powershell
$env:FALLING_WARNING_MODEL_ENABLED = "1"
$env:FALLING_WARNING_ALLOW_CALIBRATION_GAMEPLAY = "1"
```

The second option is specifically for the audited three-layer calibration-session gameplay mode, not a blanket calibration override. Start/restart the backend via its existing entry point, then use Unity's normal Start UI. No backend has been started by this review.

Disable/rollback by removing both environment variables and restarting the backend. No Unity gameplay or original yellow rule change is needed for backend ownership: Unity already sends `start_session.run_id`.

## Remaining end-to-end acceptance

1. Unity display adapter must treat UNKNOWN/invalid/mismatched run or stale output as unavailable. Keep experimental output separate from the original yellow rule. Do not implement autonomous ball control.
2. Receiver-local no-update timeout is necessary: this backend replies on incoming traffic and does not send heartbeats. When traffic stops entirely, there is no new UNKNOWN packet to clear a client display.
3. Run real gameplay Start/Restart/layer transition/recovery/edge-exit checks and inject backend stop/disconnection. Measure device/network/Unity-display latency, not only local inference time.
4. Keep thresholds/model fixed during this acceptance. No new mass data collection is needed before the connection check.

The spreadsheet analysis skill was used for read-only CSV identity/feature verification. No spreadsheet artifact, source CSV, label or telemetry schema was rewritten.
