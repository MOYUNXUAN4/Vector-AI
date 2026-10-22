# Primary review — 2026-10-11

## Scope and status

This stage repairs experiment closure and prepares native LightGBM export. It does not retrain the project model, change thresholds, improve reported performance, modify Unity, or attach inference to the live backend loop.

The baseline remains experimental: final-fall recall 10/10, guaranteed geometry lead >=0.4 s coverage 6/10, completed-session alarm rate 16/20, mean alarm burden 1.302 s, session F1 0.556. Risk followed by recovery is descriptive only, not a correction to false positives or proof of intervention benefit.

## Two distinct backend copies

- Experiment source: `C:/Users/QIYUXUAN/Desktop/fyp_Backend`.
- Reviewed runtime/export: `C:/Users/QIYUXUAN/Desktop/fyp_Backend (3)/fyp_Backend`.

The copies were not merged. Baseline config, metrics, training labels, prepared features, and prepared session manifest were byte-identical across these copies when checked during this review. Export evidence records the exact runtime contract path and source hashes.

## Closure repair — verified

`run_low_burden_prereg.py` now validates all three inner folds, selection flags and sources, finite metrics, fallback decisions, and the pooled outer four gates. Missing or malformed inputs fail before writing completion output. Both normal and finalize-only paths are covered by tests.

- Primary rerun: 15 closure unit tests passed.
- Executed `--finalize-only` against persisted experiment outputs; no fit occurred.
- New completion record retains the rejected decision: zero feasible inner candidates, all three fallback thresholds 0.35, pooled outer gates failed.
- Strong metrics equal both the previous completion-record metrics and their corresponding entries in `metrics.json`.
- Persisted outcomes remain recall 9/10, early coverage 4/10, completed alarms 16/20, mean burden 1.01405005455 s.
- Previous completion and flagged-candidate files are recoverable as `.before_primary_20261011` siblings.
- Historical missing-0.20 grid deviation is retained. The outer recall change must not be attributed solely to tightened burden gates.

## Runtime regression — verified

Primary rerun with the user's Python and LightGBM installed: 87 tests executed, 86 passed, one platform-dependent symlink test skipped. This includes native fixture loading, causal features, stream identity guards, two-point confirmation, physical recovery cancellation, and default-off output behavior.

These tests do not establish real-player performance or live end-to-end Unity latency.

## Native export — verified

`deployment/native_export.py` exports an already-refit Booster without fitting or selecting thresholds. It requires the exact 24-feature contract, finite training medians, explicit threshold, and development-only provenance declarations; declared TEST929/TEST1001/TEST1006 training datasets are rejected. It writes native text, a strict manifest, and build evidence into a sibling staging directory, loads through the existing hash-pinned loader, tests the public probability interface, then publishes without overwriting an existing destination. Failed loading or inference does not publish a package. Cleanup is restricted to the validated staging directory.

Primary rerun: five exporter tests passed using eight synthetic `TEST_FIXTURE_ONLY` rows only. No real project artifact was generated. Caller provenance declarations are not proof of actual training/test isolation; that must be independently audited during final refit.

## Deployment sequence

1. Finalize a single development-only calibration protocol and deployment threshold. The three nested OOF thresholds are not a single deployment setting and must not simply be averaged or picked using outer scores.
2. Refit the locked baseline on its approved development sessions; record session IDs, feature order, training medians, configuration, and threshold provenance.
3. Export native `model.txt`, strict manifest, and build evidence; pin hashes and independently replay inference and alarm transitions.
4. Attach the default-off runtime to the backend loop, then make a minimal Unity display integration. Preserve the existing yellow rule and gameplay.
5. Test restart, layer transitions, stale/missing inputs, model failures, and end-to-end latency before participant collection.

TEST929, TEST1001, and TEST1006 remain excluded from parameter selection and refit. No additional data collection is requested at this stage. The intended Unity release is an experimental build, not a claim that model performance acceptance has passed.
