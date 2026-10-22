# P01 normal Windows Player retest, 2026-10-20

## Interpretation correction after source review

`calibration_mode=true` is the configurable collection-session mode (selected difficulty/layer count), not evidence that the game remains in a pre-game calibration phase. Earlier wording "idle/calibration" must not be read as proof of a calibration screen. Idle scope here is supported by limited position changes and earlier test instructions, not that boolean. New 10:04/10:06 retests are documented separately in ../retest_1004_1006/REPORT.md.

## Decision

Normal Player idle/calibration telemetry is materially more continuous than the earlier Editor retest. This is a promising environment comparison, not proof that the underlying allocation/GC issue is fixed, nor active-board/gameplay acceptance. Do not pool these tests with participant/model performance data.

| Run | Source span | Unity rows | Max source gap | Gaps >100ms | Gaps >400ms |
|---|---:|---:|---:|---:|---:|
| Editor 09:28:57 | 82.711s | 4868 | 550ms | 3 | 3 |
| Player 09:52:12 | 7.759s | 466 | 54ms | 0 | 0 |
| Player 09:52:25 | 210.745s | 12649 | 42ms | 0 | 0 |

Source gaps are consecutive Unity source_timestamp differences within each CSV, not mixed Wii/Unity row gaps. Source sequences are consecutive in both new files. Long-run receive gap max is 89.375ms. Wii source max is 32.012ms and receive max is 83.934ms in the long run. P95 Unity source gap is 21ms.

## Identity and scope

Player.log names the normal package VectorAI_Normal_Game/6F1E9B5F-1F20-4BB7-BCB4-6E8B23795054/VectorAI_Data/Managed and contains both exact start_session run IDs. The long run is 0d1abbf010104e429027b661b4d0ba05. The short run is 542dcdcbb4db47f89ba369de8e30e82f.

Short run: Auto / active difficulty 1 / selected 25 layers; terminal user_exit is in CSV. Long run: difficulty 3 / selected 3 layers. Both remain layer 1 and calibration_mode=true for all CSV Unity rows. All Wii rows report board_loaded=false and center_applied=false. Sensitivity is not recorded in CSV and is not inferred from current settings. This is an idle/calibration comparison, not an edge/recovery/fall/transition test.

## Tail anomaly must remain visible

Long-run CSV ends at epoch 1792461355.814 (09:55:55.814 local), sequence 12649. Local diagnostics continue to epoch 1792461361.328 (09:56:01.328), terminal user_exit and terminal send-return sequence 12699. The CSV does not contain that terminal or the final 50 source sequence values. A successful local Send return is not proof of backend persistence.

Diagnostic ordinary sample 2018, Unity 250.188751, epoch 1792461360.476 shows the wall-clock/Unity offset step. Sample 2019, Unity 250.557068, epoch 1792461360.506 records an unscaled frame of 4635.013ms and scaled frame of 333.333ms. It is one observed long frame, not repeated snapshot copies. No profiler trace exists here to assign GC or CPU ownership. User confirmation of focus/menu/exit/backend-stop actions is pending; do not silently exclude or attribute it.

Before the CSV endpoint, 2017 ordinary diagnostic samples have maximum sampled unscaled frame 15.005ms and offset range 42.025ms. Diagnostic sampling is not a per-frame census. The 42ms range exceeds the earlier 20ms historical drift gate, so this is not a formal CLEAN clock certificate. Across the entire long diagnostic file the offset range is 4.632071s. Global median clock alignment is not valid across this tail discontinuity.

## Next step

Resolve tail action provenance first. Then use the same standalone package for a foreground, normally calibrated board run and preserve normal terminal processing: finish/quit the run first and leave backend alive until it has flushed. Test real movement and transition separately; do not change models, thresholds, StreamGuard, or gameplay to make continuity pass.

## Immutable sources

CSV under telemetry_logs/P01:

- session_20261020_095212_942873/raw.csv: SHA256 f1f0e6fd7dacd65956182f3444a1a3940078abbfbe83a41528b65c823907580c
- session_20261020_095225_074273/raw.csv: SHA256 38b67e63eab11e654657b3414d3162654e204da3ea251c0cdf38c129c749a9c3
- session_20261020_092857_539658/raw.csv: SHA256 138ebc4339150247580ac483557d27ef56b9f60248830fbd8a9d416433ed6fee

Diagnostic directory: C:/Users/QIYUXUAN/AppData/LocalLow/QI YUXUAN/VectorAI/EndlessFallingDiagnostics

- samples_20261020_015211_872_f15778bf.jsonl: SHA256 c0bb551df6c06441bce133f1d3dc43633f1a3048101c73b4cf5d4376ece7f1d6 (158 parsed records)
- samples_20261020_015221_391_47236862.jsonl: SHA256 53251ab551aa4034823cb407cb260dfa286b7a7c93f4087c43ae15258fa2fd41 (14045 parsed records)

CSV mechanical statistics were independently checked by Luna and the primary reviewer. Source files and runtime settings were not modified.
