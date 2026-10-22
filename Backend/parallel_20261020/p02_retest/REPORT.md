# P02 normal Player engineering retest, 2026-10-20

## Scope and configuration provenance

Read-only audit of four P02 sessions. User reports first run sensitivity was too high and was not 0.55; exact value unknown. User manually adjusted sensitivity for subsequent runs. CSV has no sensitivity field; do not claim independently verified 0.55, infer historical values from present settings, pool run 1 with a fixed-0.55 cohort, or silently discard run 1. This is an engineering retest, not model performance acceptance or automatic training-set inclusion.

Player.log identifies the normal desktop package VectorAI_Normal_Game/6F1E9B5F-1F20-4BB7-BCB4-6E8B23795054/VectorAI_Data/Managed and the four exact run IDs below.

## Continuity and terminal results

| Session suffix | Run ID | Unity rows | Source span | Max source gap | Max receive gap | Outcome |
|---|---|---:|---:|---:|---:|---|
| 101929_120829 | 358796c34dff4bc1bd095becdcaec003 | 4851 | 80.850s | 52ms | 110.557ms | calibration_completed |
| 102058_768764 | 510db1f687b34b2193ce0113d70e7262 | 1790 | 29.797s | 27ms | 89.775ms | calibration_completed |
| 102222_863869 | 9cde97e123d240268311b479d55a83eb | 5041 | 83.982s | 39ms | 81.659ms | edge_exit |
| 102349_100467 | 8e4f5a963d0f4ec48e382cf129ab0eb8 | 1637 | 27.243s | 29ms | 98.002ms | calibration_completed |

Source and receive gaps use adjacent same-source CSV rows. Four Unity source sequences are each 1..N without missing/repeated/reversed values. All source P95 gaps are 21ms. No source gaps >100ms or >400ms, and no receive gap >400ms. The first run has one >100ms receive interval; Wii also has one receive interval of 114.938ms. Scheduling/transport ownership is not established.

All four CSV terminal sequences and outcomes match local frozen terminal/send-return lifecycle records. Terminal sequence counts are 4851, 1790, 5041, 1637. `calibration_completed` is completion of the configured 3-layer session, not evidence of merely completing balance-board calibration. All runs have selected difficulty 3 and selected 3 layers; `calibration_mode=true` is the collection-session configuration mode, not a statement that gameplay never began.

## Board control

Wii source sequences remain continuous across all four files. All Wii rows have control_valid=true, and control age P95 is 30ms in every file; maxima are 49/41/73/38ms.

Restricting Wii source timestamps to each Unity source interval avoids treating post-terminal unloading as a gameplay failure. Within those intervals, the first three runs have unloaded/unapplied flags only in their initial approximately 1.073/0.870/1.057s, respectively. Remaining in-run rows report board_loaded=true and center_applied=true. The fourth run has those flags true throughout. All four last five in-run Wii rows report both true. No mid-run unload is established in these four records. This validates recorded input availability, not exact human action or sensitivity.

## Transition and client warning evidence

Seven before/after transition pairs are present: 2/2/1/2 per run. Every associated full snapshot is completed, and each pair explicitly changes layer, platform and diagnostic geometry version:

- Run 1: 1/-3322/-3322-g2 -> 2/-3346/-3346-g3 -> 3/-3370/-3370-g4
- Run 2: 1/-5192/-5192-g2 -> 2/-5216/-5216-g3 -> 3/-5240/-5240-g4
- Run 3: 1/-5354/-5354-g2 -> 2/-5378/-5378-g3
- Run 4: 1/-5518/-5518-g2 -> 2/-5544/-5544-g3 -> 3/-5568/-5568-g4

Player.log contains accepted ACTIVE and REVOKED records for orange model and purple proximity channels in all four runs. Counting transitions into ACTIVE (not every renewed ACTIVE log) gives model 3/1/7/2 entries and proximity 23/2/10/6 entries. Every logged channel ends REVOKED. These counts are client-state evidence, not visual exposure confirmation, false-alarm counts, or verified early-warning success. Hint burden and lead time were not evaluated here.

## Frame and clock limits

Diagnostic files parse successfully. Sampled unscaled-frame maxima are 15.004/15.005/20.000/10.005ms, with no sampled frame >100ms. These diagnostics do not observe every frame. Ordinary diagnostic offset ranges are 25.521/11.940/20.259/13.694ms; the first/third exceed the historical 20ms gate, so do not grant a blanket formal CLEAN clock certificate or use a global median to claim precise lead-time acceptance. No half-second offset step was observed in these samples.

## Decision

The old approximately half-second source-gap signature was not reproduced in these four real-input runs, including movement, seven transitions, three completions and one fall. Continue using the normal standalone Player. Keep the first sensitivity-mismatched run separate; freeze and verify settings before future collection. Do not change model thresholds or relax StreamGuard. Universal bug elimination and model performance remain unclaimed.

## Source hashes

CSV directory: C:/Users/QIYUXUAN/Desktop/fyp_Backend (3)/fyp_Backend/telemetry_logs/P02

- session_20261020_101929_120829/raw.csv: 2abbad6a20cadce120eeae7bba30689c4b30a10bce94cc3f5261c6fbe4d54d18
- session_20261020_102058_768764/raw.csv: 62098ae37d4c1e2ce741ba7313e44f053d5f8e8319a90bab2bc273e25fa6255e
- session_20261020_102222_863869/raw.csv: 24b4fc27ae686992a28342efa24976aec01d21003fafa913e97a39bfe1ac4120
- session_20261020_102349_100467/raw.csv: 481ea5bcb2fe12383fc149d2320e90748c3595b7cfc00020515b57883bc69bb7

Diagnostic directory: C:/Users/QIYUXUAN/AppData/LocalLow/QI YUXUAN/VectorAI/EndlessFallingDiagnostics

- samples_20261020_021927_561_f9e34a78.jsonl: f75382d6bac8cc4d492a4412c992795822cc90b33ed51b1a2585bbf4b6faaade
- samples_20261020_022058_088_0e86a744.jsonl: 0e3c5ece8a302a038a0725631df3d93eaac3b9f6c94e9a11e4606d4fbccc99d7
- samples_20261020_022222_407_0f5a9126.jsonl: 768fff237961644e7c3ded799740fecc5956b39cf9e6807235d1d8019c9f05cc
- samples_20261020_022348_542_0173df1e.jsonl: c8e84d60612559bda5badc4942ef6e5220c953e88762407c91c3987f9fc75b79

Mechanical CSV audit by Luna, independently checked by primary. No raw source, runtime, scene, model, threshold or settings changed.
