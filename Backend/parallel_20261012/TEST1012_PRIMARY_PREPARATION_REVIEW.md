# TEST1012 preparation review

Scope: current TEST1012 development cohort only. No model fitting, probability threshold selection, deployment replacement, Unity changes or service changes were performed.

## Verified preparation

- 15 sessions: 8 calibration_completed and 7 edge_exit. Completion is normalized only for analysis; original outcomes remain unchanged.
- 3,849 decision rows, 24 model inputs, 34 history segments. Rows are not independent sessions.
- Independent causal-kernel replay compared 92,376 feature cells with zero mismatches at rtol/atol 1e-10. Decision sequences and contexts also matched.
- All 7 edge exits have terminal event/platform/last-support/layer corroboration. Both diagnostic crossing metrics have 7 observed query brackets.
- Primary surface-clearance crossing bracket widths: 0.100494–0.103546 seconds. Auxiliary ball-centre crossing widths: 0.100891–0.106659 seconds. These are sampled bounds, not exact continuous-contact times. Do not use the descriptive interpolation as ground truth.
- Diagnostic fingerprint versions and ordinary geometry generations remain separate. Feature history breaks at source gaps and context changes; layer 4 and post-terminal input are excluded.
- 1,461 joint-recovery points are sample-level flags, not 1,461 independent recoveries or successful interventions.
- Source hashes were unchanged during preparation and independent replay. Raw records were not modified.

## Configuration and interpretation

The user confirmed sensitivity 0.55, previously 0.66. Both experimental AI and geometry banners were visible, and the original yellow/attention configuration was unchanged. Sensitivity and display context are user-provided metadata, not historical telemetry measurements. calibration_mode=True is retained as recorded.

This is development data, not an independent test set or a no-feedback control. It does not establish that lower sensitivity caused better outcomes, that alerts caused recovery, or that the current model meets performance targets.

## Next step

Keep the existing deployed model locked. First replay it on this cohort as a descriptive new-configuration check; these results must not be called independent acceptance metrics. Any subsequent retraining should use a predefined controlled comparison with configuration-compatible development data, session-grouped evaluation, and thresholds selected only inside training folds. Do not silently pool old bounds geometry or different sensitivity configurations.

Changing sensitivity does not require discarding old data or starting over. It changes the input-to-motion/recovery relationship, so applicability must be checked. If 0.55 is the intended permanent setting, a separately versioned calibration/retraining candidate may be appropriate; improvement must be demonstrated, not assumed. A fixed candidate then needs a new independent evaluation batch under the same configuration.

Evidence: test1012_formal_prepare/summary.json, event_anchors.csv, metadata.json; test1012_formal_review/formal_review.json.

Final independent preparation review: PASS. All 14 prepared anchor rows match independently reconstructed query bounds and narrowness flags. An initial fast CSV float-parser rounding discrepancy was resolved using round-trip parsing in the review script; original diagnostic line/event identities and prepared data were unchanged. This approves preparation only, not model performance or deployment.
