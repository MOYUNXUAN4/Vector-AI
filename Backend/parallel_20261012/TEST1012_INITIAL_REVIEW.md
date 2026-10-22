# TEST1012 initial audit — 2026-10-12

## Configuration and status

User-confirmed Falling sensitivity is 0.55, previously 0.66. The latest clarification confirms both experimental AI and geometry banners were ON; the earlier OFF answer is superseded. Original yellow/attention settings are reported unchanged. CSV does not record sensitivity or experimental display configuration, so these are user-confirmed metadata, not telemetry measurements. Inspector values do not establish historical runtime settings.

This is a new-configuration DEVELOPMENT cohort, separate from 1012TEST functional acceptance and from the old development pools. It is not a frozen independent validation cohort. No model fitting, threshold tuning, Unity/backend change or old-data mixing has been performed.

## Records

There are 15 session folders and raw.csv files, not the planned 16. Each has a unique run ID and an ended Unity terminal record. Eight have raw outcome calibration_completed with selected_session_layers=3 and passed_count=3; analysis can describe those as three-layer completion without rewriting the raw outcome. Seven are edge_exit: six in layer 1, one in layer 2. All use recorded difficulty 3. Layer 4 rows in completed runs are terminal completion rows, not an additional training gameplay layer.

Primary independently reconciled each CSV terminal sequence/outcome with the exact run's JSONL terminal frozen snapshot and UDP send payload: 15/15 agree. All 15 also have an ended-run restart request. A send-call completion alone is not backend receipt; here the matching CSV terminal provides independent receipt/persistence evidence.

| Session ID | Analysis outcome | Terminal layer | Unity rows |
|---|---|---:|---:|
| session_20261012_201501_583328 | complete | 4 | 1939 |
| session_20261012_201537_424286 | complete | 4 | 1736 |
| session_20261012_201610_080573 | complete | 4 | 2097 |
| session_20261012_201647_039319 | complete | 4 | 2320 |
| session_20261012_201728_372912 | complete | 4 | 1361 |
| session_20261012_201753_282830 | edge_exit | 1 | 641 |
| session_20261012_201806_185949 | complete | 4 | 1474 |
| session_20261012_201832_486360 | complete | 4 | 1668 |
| session_20261012_201902_617504 | complete | 4 | 1532 |
| session_20261012_201929_389058 | edge_exit | 1 | 958 |
| session_20261012_201948_796111 | edge_exit | 1 | 936 |
| session_20261012_202006_528702 | edge_exit | 1 | 643 |
| session_20261012_202019_348109 | edge_exit | 1 | 540 |
| session_20261012_202031_072605 | edge_exit | 1 | 706 |
| session_20261012_202045_661325 | edge_exit | 2 | 1008 |

Raw sources: `telemetry_logs/TEST1012/<session_id>/raw.csv`. Full absolute paths, run IDs, hashes and exact JSONL paths/line numbers are preserved in `TEST1012_session_audit.json` beside this report.

## Quality and evidence limits

No Unity sequence duplicates, reversals or missing sequence numbers were found; geometry query/ownership/directional validity flags are true and active platform/version identities agree. There are four source-time gaps around 0.6 seconds: session 201501 at layer 2, and 201610, 201647, 201832 at layer 3. Do not interpolate through them or use cross-gap feature history. The first-layer pilot is not affected by these later-layer gaps.

The last raw.csv is still receiving Wii samples after its Unity run ended. Source hashes are read snapshots, not frozen input hashes; 14 files were stable during the audit read, the last was not. Raw files were not written by this analysis. Post-terminal Wii samples must not enter causal inputs or response labels. Close the logger normally before final immutable preprocessing; do not delete or truncate the raw file.

Receiver activation logs are not visual frame captures, but are consistent with the user's latest ON clarification. This feedback condition must be retained as cohort metadata. Improvements cannot be attributed solely to lower sensitivity; observed recoveries do not prove AI-caused rescue. Final-outcome FP remains FP under the original metric policy.

## Pairing scope

First-layer matching uses only the six layer-1 terminal falls and observed recovery states in the eight completed sessions. The layer-2 fall remains in the dataset and any eventual whole-session fall denominator; exclusion here is only from the first-layer terminal matching diagnostic.

The preliminary clearance crossing is a raw-CSV sampled proxy, not an approved continuous geometric/PhysX anchor. Primary found last positive-to-nonpositive crossing sequence pairs 615/616, 934/935, 912/913, 619/620, 516/517 and 681/682 in the six layer-1 falls. Their sampled widths are approximately 0.016–0.019 seconds. As-of decisions at lower minus 0.4/0.6/0.8 seconds have ages <=0.02 seconds.

Session 201753 is inward-moving at the 0.6- and 0.8-second decision points, so it cannot be forced into a currently-outward matched comparison at those points. It is still a real fall, not discarded from model evaluation.

Match only by current risk: same difficulty/layer, ball-centre radial direction within 30 degrees, clearance within 0.5 units and outward velocity within 0.75 units/s. One session per side per offset. Recovery candidates are currently outward, positive-clearance states followed within 1.5 seconds by observed joint inward motion/clearance gain in continuous same-context data. Future recovery is only a group label, not an input or a time origin for the control point.

Formal geometry-anchor reconciliation and causal feature preprocessing are required before training. No model accuracy, F1 or lead-time improvement is claimed in this initial audit.

## Reviewed pairing pilot result

| Offset before sampled clearance crossing | Matched layer-1 fall sessions | Distinct completed control sessions |
|---|---:|---:|
| 0.8 seconds | 5 / 6 | 5 / 8 |
| 0.6 seconds | 5 / 6 | 5 / 8 |
| 0.4 seconds | 6 / 6 | 6 / 8 |

These are descriptive MATCHING coverage counts, not model recall or early-warning coverage. The same sessions are reused across offsets: 16 matched rows are not 16 independent pairs. Session 201753 remains in the six-fall denominator at all offsets; its inward-moving earlier points simply have no eligible currently-outward match.

Primary reran the corrected pilot and independently checked all 16 selected comparisons against the original Unity rows: difficulty/layer, direction, clearance, velocity, additive normalized matching cost, unique session selection per offset, and future recovery timing/physical recovery evidence agree. Earlier candidate implementations that aligned recovery controls to a future label or changed the cost definition were rejected and are not used in this report. Full IDs and exact sequences are retained in `TEST1012_pair_pilot_review.json`.

Do not require another session merely to reach the planned count of 16. Close the ongoing logger first, retain the current 15 runs and confirmed feedback/sensitivity metadata, then prepare formal independently supported geometry anchors and causal features under this new configuration. Keep missing/unsupported anchors unknown. A subsequent training experiment must be defined separately; old data do not become compatible solely because the CSV schema matches, and the existing deployed model is not replaced by this audit.
