# Fixed-score development comparison: two-low exit

Predeclared before execution. This is a single-factor offline display-policy test, not new model training, threshold selection, or independent evaluation. Do not use TEST1012/1012TEST, TEST929, TEST1001 or TEST1006 for selection.

Inputs: locked TEST1009 30-session development OOF scores in parallel_20261011/deployment_refit/output/oof_probabilities.csv, original prepared labels/geometry anchors, and existing baseline evaluation functions. Entry threshold remains 0.65, original two-point entry confirmation, forecast horizon 0.75 s, original features/weights and joint recovery rule unchanged.

Baseline: original immediate raw-OFF exit. Candidate: once ACTIVE, require two consecutive NEW valid evaluations below 0.65 before exiting. A new valid above-threshold evaluation resets the low counter. Entry raw continuity and entry confirmation remain the original rule. Joint physical recovery immediately exits. Nonpositive clearance, missing scores, bad identity, segment/run/layer/version change or gap >0.1 s immediately clear; do not carry activity across missing data. No minimum-show time, added hysteresis threshold, score imputation, synthetic evaluations or infinite hold. Low evaluations do not count repeated reads of the same packet.

Geometric danger is NOT included in this comparison. It is a separate current-condition output and must not be counted as improved model precision/F1.

Report paired session precision/recall/F1, completed-session alarm rate and mean duration, conservative geometry lead >=0.4 s coverage with missing-anchor denominator, first/last pre-event warning leads, episode count, episodes shorter than0.2s, and added active time caused solely by pending low exit. First activation times must not become earlier because of holding; any apparent early improvement must be traced to continuity rather than claimed better prediction. State reasons and raw/confirmed flags remain distinguishable.

Screening rule for possible further validation (NOT automatic deployment): recall and >=0.4s geometry coverage no lower than baseline; session F1 and completed-session alarm rate no worse than baseline; completed-session mean alarm burden may increase by at most 0.05s; short-episode count must strictly decrease. If exact geometry anchors/masks cannot be reproduced or baseline replay does not match locked selected metrics, do not declare a pass. Missing metrics remain unavailable, not zero.

These development OOF scores already selected the deployment threshold, so outputs are calibration/engineering diagnostics, not unbiased generalization. Report that limitation. No probability grid, entry-threshold changes, retraining, weight changes, new features or production policy changes in this experiment. A candidate that fails is rejected without a second adjustment.
