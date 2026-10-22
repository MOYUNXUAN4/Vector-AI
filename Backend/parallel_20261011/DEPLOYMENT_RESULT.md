# Experimental deployment model — primary review passed

Only the locked 30 TEST1009 development sessions were used. Frozen TEST929, TEST1001 and TEST1006 were not loaded for selection, fitting or evaluation. Unity and the live backend loop were not modified.

## Locked artifact

- Model ID: `test1009-strong-deployment-refit-20261011`
- Feature order: original 24 strong features, no added COP feature.
- Forecast horizon: 0.75 s. This is a target definition, not achieved warning lead.
- Threshold: **0.65**, selected from the original six-point grid by the preregistered baseline ranking on newly recomputed session-grouped development OOF predictions.
- Confirmation/recovery: original two-point confirmation and joint physical recovery cancellation, no added hold/hysteresis.
- Final fit: 5,558 eligible rows, 108 positive and 5,450 negative; 1,340 original ineligible rows remain excluded.
- Runtime approval: experimental only. Runtime remains default-off; attention is not exported.

## Calibration diagnostics, not independent performance

| Metric | Selected threshold 0.65 |
|---|---:|
| Conservative final-fall recall | 6/10 (60%) |
| Guaranteed geometry lead >=0.4 s coverage | 4/10 (40%) |
| Completed-session alarm rate | 11/20 (55%) |
| Mean completed-session alarm burden | 0.269 s |
| Final-fall session precision | 35.3% |
| Final-fall session F1 | 44.4% |

These same development OOF predictions selected the threshold. They are calibration diagnostics, not a new unbiased evaluation, and not measured final-refit generalization. The old nested strategy's 10/10 recall and F1 0.556 must not be attributed to this single-threshold deployment artifact. The rejected low-burden criteria (alarm rate <=50%, burden <=0.25 s) remain unmet. This is not a performance upgrade claim.

## Verification

- Labels, eligibility and original three session memberships match the baseline; each fold has ten held-out sessions, with no train/test session intersection.
- Primary independently recalculated final medians, midpoint weight statistics, eligible counts, session coverage and threshold ranking.
- All 60 original CSV/diagnostic source hashes matched before fitting. Locked prepared inputs and recorded source-script hashes were unchanged during fitting.
- Native reload versus fitted classifier: all 5,558 eligible rows, maximum absolute probability error 0.
- Public runtime prediction wrapper versus native Booster: all 5,558 valid eligible rows, maximum absolute error 0. Primary independently exercised another 40 representative rows through the public wrapper.
- Model SHA-256: `01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068`
- Manifest SHA-256: `b75cac3173496171a9e2c17906938fc5bdac22243ff7f8ce5cee75b96900d29e`

Package: `deployment_refit/output/artifact/`, containing native `model.txt`, `manifest.json`, and `build_evidence.json`. Reproducible fit/calibration evidence resides in the adjacent output directory. Primary checker: `primary_verify_refit.py`.

## Next

Integrate this hash-pinned artifact into a default-off backend path, replay actual streams and check feature/state parity, stale-input failures, restart/layer resets and latency. Only then enable minimal Unity visualization as an experimental build. Do not silently replace the existing geometric yellow warning. No additional data collection is needed before this integration check.
