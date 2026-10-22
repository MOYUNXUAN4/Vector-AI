# Native LightGBM deployment artifact export

This isolated tool exports an already-refit `lightgbm.Booster` as native `model.txt`, plus the strict schema-v1 `manifest.json` consumed by the `parallel_20261010/backend/model_artifact.py` loader. It does not fit a model, calibrate a threshold, derive medians, or serialize Python objects. Supply an explicit threshold and exactly 24 finite medians.

The exporter imports the reviewed contract from the explicit backend copy at `C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\parallel_20261010\backend`. `build_evidence.json` records that exact copy and SHA-256 digests of its loader, feature, and alarm-policy source files, so similarly named backend copies are not silently mixed.

The required provenance values are declarations only. The exporter checks that `artifact_role=deployment_refit`, dataset IDs and development session IDs are present, `threshold_selection_scope=development_grouped_oof`, and `independent_test_used=false`; it rejects declarations naming known frozen datasets `TEST929`, `TEST1001`, or `TEST1006` (case-insensitive). These checks cannot establish the Booster's actual training history, dataset identity, or test-set isolation. No real project model or test data is included in this package.

Before publishing a package, the exporter stages it in a temporary sibling directory, loads its native model through the strict `ModelArtifact.load` implementation pinned to the computed model digest, exercises `ModelArtifact.predict_probability` with a legal finite feature sample, then atomically renames the staged directory. On failure, cleanup is limited to a resolved sibling directory matching the exact staging prefix. The manifest approves experimental runtime use only. Evidence explicitly sets `experimental_only=true` and `performance_validated=false`; the production runtime remains default-off. Record both returned `model_sha256` and `manifest_sha256` in the primary review log. The manifest hash is audit evidence and is not a runtime pin.

The tests train a tiny eight-row synthetic `TEST_FIXTURE_ONLY` booster solely to exercise the export format. Run them with the configured Python 3.14 environment where LightGBM 4.7 is installed:

```powershell
python -m unittest -v test_native_export.py
```
