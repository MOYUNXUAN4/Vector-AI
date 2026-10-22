# Early fall versus recovery review — 2026-10-12

## Decision

The existing development data do not yet establish a stable new discriminator 0.6–0.8 seconds before geometric edge crossing. At 0.4 seconds there is a repeatable local direction for the 0.4-second acceleration difference, but this feature has already failed a controlled model experiment. Do not rerun that candidate, lower thresholds, extend display duration or deploy a new model on this evidence.

This turn audited existing paired records, rather than repeating the previously independently checked raw extraction. Primary and Luna independently recomputed pair counts and signal direction. No fitting, new feature search or alarm replay was performed. No Unity, backend, model, source CSV or frozen datasets were modified. TEST1012/1012TEST functional runs are excluded.

## Inputs and matching

TEST1009: `telemetry_logs/TEST1009/training_20261009/matched_early_signal_20261009/recovery_state_matched_pairs.csv`.

DEV_MATCHED_A: `telemetry_logs/DEV_MATCHED_A/analysis_20261009/pairing/matched_pairs.csv`.

Use the existing matching rules: same difficulty and layer, direction difference <=30 degrees, clearance difference <=0.5 units, outward-velocity difference <=0.75 units/s. TEST1009 uses only `same_layer`, not `layer_relaxed_sensitivity`; DEV_MATCHED_A uses first-layer pairs. Each session can be selected once per group. No caliper was changed to obtain a desirable answer.

Fall inputs are available at decisions 0.4/0.6/0.8 seconds before the lower or upper geometric event bound. Recovery controls are matched at a comparable current outward-moving state, not aligned to future recovery completion. Future recovery is only a retrospective group label. Thus this is an outcome-conditioned descriptive comparison, not an online detector which already knows the event time. Historical source/identity/causality reviews remain the extraction evidence; no new raw reconstruction is claimed.

## Pair coverage

| Seconds before crossing | TEST1009 lower / upper | DEV_MATCHED_A lower / upper |
|---|---:|---:|
| 0.8 | 2 / 4 | 3 / 2 |
| 0.6 | 5 / 4 | 2 / 2 |
| 0.4 | 4 / 5 | 3 / 5 |

The 24 TEST1009 group rows represent only 8 distinct session-pair identities, involving 7 fall and 8 completed sessions. The 17 DEV_MATCHED_A rows represent 5 pair identities, involving 5 fall and 5 completed sessions. Pairs themselves can share a session across groups; neither row totals nor unique pair totals are independent sample sizes. Lower/upper are uncertainty sensitivity analyses, not separate validation experiments.

## Signal consistency

Counts below describe the fraction of pairs with a particular direction, NOT classifier accuracy.

| Signal at 0.4 seconds | TEST1009 lower / upper | DEV_MATCHED_A lower / upper | Interpretation |
|---|---:|---:|---|
| Fall-side acceleration difference is smaller | 4/4, 4/5 | 2/3, 4/5 | Local direction persists, but does not extend reliably to 0.6–0.8 seconds |
| Fall-side COP amplitude is larger | 1/4, 2/5 | 3/3, 4/5 | Batch/group composition sensitivity; not a stable universal rule |
| Fall-side current acceleration is smaller | 4/4, 4/5 | 1/3, 2/5 | Opposite tendency between cohorts |

COP speed is mixed across offsets and bounds. Continuous inward duration equals zero on both sides of every matched comparison; waiting for sustained inward motion cannot by itself discriminate these early points. Acceleration history has missing comparisons: TEST1009 3 missing and DEV_MATCHED_A 1 missing among the four reviewed signals across groups. Missing values remain unknown, not zero.

Luna independently recomputed fall-minus-recovery differences from both sides of the stored pairs: 93 finite TEST1009 and 67 finite DEV_MATCHED_A comparisons agree with stored difference columns. Primary independently reproduced pair counts and sign summaries, checked uniqueness and matching limits in the available columns, and reviewed the pre-existing causality audits. Differences across cohorts may reflect difficulty/layer/control composition as well as sampling; no causal explanation of the discrepancy is established.

The earlier acceleration-difference experiment retained F1 0.556, completed-session alarm rate 16/20 and guaranteed >=0.4s coverage 6/10 under its historical nested baseline. Those are historical development results, not the deployment threshold 0.65's metrics and not new scores produced by this review.

## Next action

Do not start a new model fit solely from these small matched differences. The most useful next data would improve overlap at 0.6 seconds: matched outward speed, clearance and direction, followed by attempted recovery versus continued outward motion, with actual outcomes retained. Fix sensitivity, board orientation and feedback configuration before collecting. Keep the existing geometric fallback separately labelled; do not count it as early model prediction.

For a home pilot, the previously proposed 16-session block (four directions x two approach speeds x two intended responses) can be used after configuration is fixed. These are intended conditions, not guaranteed outcomes or guaranteed matched pairs. First inspect actual pair eligibility using the unchanged limits; supplement only missing conditions, rather than automatically training or collecting large random completion sets. Avoid physical imbalance or stepping off the board; only the virtual ball should be allowed to fall.

When a new causal signal is supported, preregister one controlled candidate and calibrate within grouped training folds. Require preservation/improvement of guaranteed early coverage and recall together with reduced recovery alarm burden. Independent acceptance data are collected after the candidate is fixed. No new F1 or lead-time improvement is claimed now.
