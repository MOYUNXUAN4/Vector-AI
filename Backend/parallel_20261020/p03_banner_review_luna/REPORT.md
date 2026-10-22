# P03 warning evidence review

Read-only review of the six specified P03 `raw.csv` files and exact Unity run IDs in `telemetry_logs/proximity_shadow.jsonl`. No source data, code, or configuration was changed; no service or model was started.

## Findings

All six sessions contain one Unity run, with commanded and active platform difficulty 3 and selected session layers 5. Unity sequence numbers start at 1 and are continuous through the final record in every run. Four runs terminate as `calibration_completed`; two terminate as `edge_exit` (the terminal sequence carries the end outcome). The CSV `calibration_mode` field is true in the sampled Unity rows, and the shadow log marks every matched record `unsupported_or_calibration_phase`; this limits interpreting the warning telemetry as proof of an experimental banner.

| Session | Unity run ID | Unity samples | terminal | `warning_active=True` | `edge_warning_state=True` | prediction states (SAFE / ATTENTION / EDGE WARNING / EDGE CONTACT / FALL) | min q = directional distance − 2r | min clearance = directional distance − r | target edge radial velocity min…max |
|---|---|---:|---|---:|---:|---|---:|---:|---:|
| 20261020_204207_908174 | `31a01c3b932e40b186f88beb06bdc513` | 2031 | calibration_completed | 321 | 53 | 1710 / 268 / 53 / 0 / 0 | -0.8123 | -0.3123 | -2.4567…3.4751 |
| 20261020_204245_310354 | `c967d0e27c2347959f38d295ea738887` | 1936 | calibration_completed | 433 | 62 | 1503 / 370 / 63 / 0 / 0 | -0.7375 | -0.2375 | -3.3938…3.4588 |
| 20261020_204323_779285 | `1b3beda2a3f047b9af4b5a3dedc75644` | 780 | edge_exit | 359 | 36 | 409 / 334 / 25 / 11 / 1 | -1.4644 | -0.9644 | -3.1989…2.8516 |
| 20261020_204340_783591 | `4ffbc7c05beb42599c5183fab2ba4329` | 2462 | calibration_completed | 640 | 80 | 1822 / 560 / 80 / 0 / 0 | -0.6332 | -0.1332 | -3.4372…3.4580 |
| 20261020_204429_025778 | `dae0729f4cb240d2bd5188279c724c68` | 2259 | edge_exit | 480 | 151 | 1724 / 382 / 98 / 54 / 1 | -1.4519 | -0.9519 | -3.3502…3.1150 |
| 20261020_204511_543162 | `23eb44ad157a42aabbac1d70e6c2163f` | 2118 | calibration_completed | 711 | 342 | 1407 / 366 / 345 / 0 / 0 | -0.9502 | -0.4502 | -4.2162…4.1094 |

The minima are computed only where both `directional_edge_distance` and `ball_radius` are finite. The velocity range is `target_edge_radial_velocity` over finite values, retaining both inward and outward signs; it is not an outward-only summary. `warning_active`, `visible_warning_state`, `edge_warning_state`, `attention_state`, and `prediction_state` are recorded fields and do not independently establish what was displayed to the participant. In particular, the raw `visible_warning_state` values `ATTENTION` and `EDGE_WARNING` are not proof of a physical experiment banner. A blank field or absent log record also does not prove absence of danger.

## Shadow log

Exact matching by the six Unity `run_id` values found respectively 2030, 1935, 779, 2461, 2258, and 2117 records. Every matched record has `active=false`, `causal_available=false`, and `reason=unsupported_or_calibration_phase`. The actual common record schema includes `run_id`, `active`, `causal_available`, `reason`, `q`, `raw_rule_on`, `state`, `valid`, `source`, `layer`, `input_sequence`, `input_source_timestamp`, `shadow_sequence`, `platform_instance_id`, `geometry_version_id`, `schema_version`, `shadow_only`, and `receive_monotonic`. It does not contain an `available` key; availability was assessed via `causal_available`. A broader file scan showed additional schemas, but those records were not attributed to P03 because they did not match these exact run IDs.

## Provenance

`input_sha256.json` records SHA-256 hashes for the six raw CSVs and shared shadow log before/after analysis. The hashes match. This check does not include `Player.log`, a shortcut, or the physical receiver/display path; those require the primary agent's separate inspection.
