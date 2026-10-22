# Experimental model artifact format, schema version 1

The loader consumes a UTF-8 JSON manifest beside a native LightGBM text model.
It accepts no pickle/joblib files and never trains or chooses a threshold. The
runtime must separately supply the SHA-256 digest it trusts and explicitly set
`allow_experimental=True`; the manifest approval field alone is not authority.

Required manifest keys (no extras):

| Key | Required value |
| --- | --- |
| `schema_version` | integer `1` |
| `model_id` | nonempty string |
| `target` | `"strong"` |
| `prediction_horizon_seconds` | `0.75` |
| `features` | exact ordered list from `backend.causal_features.FEATURE_NAMES` |
| `medians` | object with exactly the 24 feature names and finite numeric values |
| `threshold` | explicitly supplied finite number in `[0, 1]` |
| `confirmation_points` | integer `2` |
| `decision_interval_seconds` | `0.05` |
| `max_decision_gap_seconds` | `0.1` |
| `recovery_policy` | `"joint_ball_inward_and_clearance_gain_v1"` |
| `approved_for_experimental_runtime` | JSON `true` |
| `model_file` | relative filename contained within the manifest directory |
| `model_sha256` | SHA-256 matching both model bytes and caller-pinned digest |

Example threshold syntax only (the value is illustrative, is not selected or
endorsed, and must be supplied from the independently approved evaluation):

```json
"threshold": 0.83
```

The loader rejects duplicate manifest keys, nonstandard JSON constants, path
escapes, mismatched hashes (checked both before and after loading), feature
order/count differences, and non-binary LightGBM objectives. It accepts the
native dump form `binary sigmoid:1`; metrics such as `binary_logloss` are not
accepted as objectives. Package imports and Stage1-style script imports are
supported. Inference passes a `(1, 24)` NumPy `float64` array to LightGBM and
requires all 24 feature keys plus finite physical
geometry (`directional_edge_distance`, `clearance`, radial velocity, and
positive radii); nonpositive clearance is ineligible. Optional NaN feature
values are replaced only with the fixed manifest medians. The prediction method
returns a probability; it does not make control or recovery decisions.
