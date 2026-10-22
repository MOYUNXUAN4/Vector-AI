# Normal Player retest: 10:04 and 10:06, 2026-10-20

## Result

No >100ms Unity source gaps occurred in either recorded run. Terminal records now match local diagnostics and backend CSV, unlike the earlier incomplete tail. This supports the standalone path as the current testing path. It does not certify universal GC elimination or board/model performance.

| Session | Unity rows | Source span | Max source gap | Max backend receive gap | Terminal |
|---|---:|---:|---:|---:|---|
| session_20261020_100423_350121 | 7043 | 117.364s | 50ms | 69.384ms | edge_exit, sequence 7043 |
| session_20261020_100624_879840 | 9097 | 151.539s | 30ms | 115.353ms | user_exit, sequence 9097 |

Both Unity source sequence ranges are exactly 1..N with no missing, repeated, or reversed values. Both source-gap P95 values are 21ms. Timing statistics separate Wii and Unity rows.

Run IDs: 423445ed25fb4e4c8dbdef9e5193ee4c and dcdcca1ad62348c4b3352cdb389a2f46. Player.log points to the normal VectorAI_Normal_Game/6F1E9B5F-1F20-4BB7-BCB4-6E8B23795054 package and contains those start_session IDs.

First run includes layers 1 and 2. Local lifecycle before/after records are at Unity 115.537567, epoch 1792461976.397/.398. Edge-exit terminal is at Unity 119.862534, epoch 1792461980.717; local send returns at .718; CSV terminal source timestamp is .718 and backend timestamp .724971.

Second run remains layer 1. User-exit terminal freezes at Unity 273.718323, epoch 1792462136.413; local send returns at .414; CSV terminal source timestamp is .414 and backend timestamp .420210. This closes terminal persistence for this run.

## Remaining observations

- Second run has one backend receive interval of 115.353ms at Unity source sequence 1023, while its corresponding source interval is only 15ms. Wii also has one 114.761ms receive interval. This is not evidence of the old Unity source stall. Exact scheduling/transport/backend cause is not assigned by this audit.
- Local diagnostics show no sampled unscaled frame >100ms; maximum is 15.008ms and 15.006ms respectively. Diagnostic snapshots sample frames and cannot certify every rendered frame.
- Ordinary diagnostic offset range is 31.582ms in run 1 (maximum adjacent change 20.560ms). Run 2 contains an approximately 975.038ms offset jump only in its final terminal sample. No sampled unscaled-frame spike accompanies that terminal offset jump. UIManager changes Time.timeScale for pause/menu state; do not interpret an exit-time Time.time/epoch offset change alone as a GC stall. Exact user actions are not established here.
- A formal all-session CLEAN clock certificate is not issued. Terminal lead-time calculations must not bridge the terminal discontinuity using a whole-session median offset.
- Both runs use difficulty 3 and selected 3 layers. `calibration_mode=true` denotes configured collection-session mode, not the pre-game calibration screen. Prior report wording was corrected accordingly.
- Board occupancy, sensitivity runtime value, cue visibility, and model prediction correctness were not established by this continuity audit. No model metrics or new performance acceptance are claimed.

## Provenance

Backend CSV under telemetry_logs/P01:

- session_20261020_100423_350121/raw.csv SHA256 6e2e018c019a7d55112a4f8daae319478438bbd45938c6579877d8d3429bf9b2
- session_20261020_100624_879840/raw.csv SHA256 1ac0b1fbc12c413b99a7709a81e58f1624aeeb7ae2eb87642ef71d24565e00a2

Diagnostic directory C:/Users/QIYUXUAN/AppData/LocalLow/QI YUXUAN/VectorAI/EndlessFallingDiagnostics:

- samples_20261020_020421_469_23ea9cbb.jsonl SHA256 f1d3126fd683fb51cb3cd83d6255469cc25993b8242d708e09645643dd6d59c4; 7671 parsed records.
- samples_20261020_020624_014_1ebb2b91.jsonl SHA256 676388a3676fbf6686736f5441782b0ad1765d325c5ea4f93ee26f3740de0e4d; 9901 parsed records.

CSV mechanical analysis by Luna, cross-checked by primary using exact terminal values and context. Reused read-only diagnostic inspector from ../retest_0952/inspect_diagnostics.py. Original sources, game, model, and configuration were not changed.
