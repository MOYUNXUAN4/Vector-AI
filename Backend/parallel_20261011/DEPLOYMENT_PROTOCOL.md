# Locked development-only deployment refit

Locked before generating deployment calibration probabilities. This is preparation of an experimental build, not a new performance evaluation.

## Inputs and model

Use only the 30 approved TEST1009 sessions in `telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/baseline_fixed`. Preserve all 6,898 prepared rows, original strong eligibility and labels, original 24-feature order, strong horizon 0.75 s, and baseline model parameters. Train only eligible labeled rows. Use the original 50/50 midpoint between inverse-class/session-normalized weights and equal-per-session-row weights. Calculate medians within each training subset only, with the original all-missing-column fallback.

TEST929, TEST1001, TEST1006 and all other datasets are excluded. No added COP feature, weighting ablation, horizon search, or alarm-policy change is authorized.

## Single threshold

Recompute grouped development OOF probabilities using the existing three session memberships and seed 20261009. Each session is predicted by a model trained without that session; every calibration fitting subset has approximately 20 sessions. Do not read previous stored outer probabilities, candidate metrics, or selected thresholds to choose this threshold.

Use only the original grid: 0.20, 0.35, 0.50, 0.65, 0.80, 0.95. Replay the existing two-point confirmation and physical recovery cancellation, with the corrected actual-ON geometric matching evaluator.

Reuse baseline strong `rank_candidates`: qualifying candidates require conservative recall >=0.60 and guaranteed geometry lead >=0.4 s coverage >=0.40. Among those, minimize completed-session alarm rate, then burden, then maximize precision, then prefer a higher threshold. If none qualifies, record the existing diagnostic fallback explicitly and do not publish an approved deployment artifact without primary review. Do not add the rejected low-burden gates to this baseline protocol.

The development OOF rows are being used for calibration here. Their resulting metrics are calibration diagnostics, not an unbiased independent-test result. Existing nested evaluation results remain separately labeled; their three thresholds are not averaged to produce deployment settings.

## Refit and export

Lock the chosen threshold and calibration evidence before the final fit. Refit the same baseline on all approved eligible development rows. Export with the reviewed native exporter: `model.txt`, strict `manifest.json`, and `build_evidence.json`. Include full session IDs, fit counts, medians, weights, feature order, configuration and input/source hashes. Native reload predictions must match the fitted model on eligible rows within a declared numerical tolerance.

Only strong is exported. Attention remains disabled. Runtime remains default-off. No Unity, live service, schema, original CSV, or existing experimental output is changed.

## Primary acceptance

Verify session exclusion for every OOF fit, exact label/mask identity, source hashes before/after, independently recompute threshold ranking and training medians/weights, and compare native reload predictions. A successful export establishes packaging/inference compatibility, not higher F1, player benefit, or performance acceptance. Final-refit training scores must never replace OOF or independent-test scores in the main result table.
