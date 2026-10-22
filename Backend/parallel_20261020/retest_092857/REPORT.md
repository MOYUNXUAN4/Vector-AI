# 2026-10-20 09:28:57 — Editor idle retest

## Decision

**Editor-path continuity retest failed.** Three half-second-class Unity stalls remain. This is consistent with the old P0 symptom, not proof of a newly introduced bug. The previous isolated Player and full-scene synthetic Player results remain valid within their own scopes; they did not establish an Editor fix.

The user confirmed this run used Unity Editor Play and **no person stood on the board**. Treat it as an idle diagnostic, not a real-board or participant acceptance run. Do not collect additional training data to address this measurement issue.

Only one new session was found in the inspected backend telemetry tree, under P01 rather than RETEST1020_A. No source files were moved, renamed, filtered or edited. No gameplay, model, threshold, backend, scene or diagnostic configuration was changed during this audit.

## Source integrity and identity

- CSV: `C:/Users/QIYUXUAN/Desktop/fyp_Backend (3)/fyp_Backend/telemetry_logs/P01/session_20261020_092857_539658/raw.csv`
  - Stable before/after SHA-256: `138ebc4339150247580ac483557d27ef56b9f60248830fbd8a9d416433ed6fee`.
- Local diagnostics: `C:/Users/QIYUXUAN/AppData/LocalLow/QI YUXUAN/VectorAI/EndlessFallingDiagnostics/samples_20261020_012856_576_35123544.jsonl`
  - SHA-256: `88e8fb09c578c65fd1b8cc1f720473105640677f60c2e6192e6b33f51df5273f`.
  - 5,277 parsed records, no parse errors, one run ID.
- Run: `d7694e6d3eae41f6986542cf157c0bfc`. Editor.log's scene/start_session/diagnostic paths match this run; user independently confirmed Editor Play.
- Current receiver source hash remains `5dd7769a0ef488e95e592f4ee85193e9a4508791fc12e2cb06c62ef0db8efcda`, matching yesterday's optimized source. This read-only check is not an independent loaded-binary provenance check.

## Source-separated timing

10,127 CSV data records: 5,259 Wii and 4,868 Unity. Do not calculate gaps on the mixed interleaved row stream.

| Source | Source-clock span | Source gap P95 | Maximum source gap | >100 ms / >400 ms |
|---|---:|---:|---:|---:|
| Wii | 82.729 s | 16.3 ms | 31.7 ms | 0 / 0 |
| Unity | 82.711 s | 21.0 ms | 550 ms | 3 / 3 |

Unity backend-receive maximum was 549.806 ms; Wii backend-receive maximum was 45.3 ms. Both sources have consecutive unique sequences: Wii 11273–16531, Unity 1–4868. Thus sequence continuity does **not** imply time continuity: Unity failed to produce/send a timely sample rather than skipping its own sequence numbers.

| Local time (UTC+8), diagnostic observation | CSV Unity source gap | Unscaled diagnostic frame | Scaled frame | Adjacent diagnostic sample offset jump |
|---|---:|---:|---:|---:|
| 09:29:09.800 | 476 ms | 463.084 ms | 333.333 ms | +0.131458 s |
| 09:29:35.423 | 536 ms | 527.297 ms | 333.333 ms | +0.197057 s |
| 09:30:00.972 | 550 ms | 546.755 ms | 333.333 ms | +0.214288 s |

CSV physical line pairs: 1459→1489, 4590→4624, 7713→7749. Intervening rows are Wii records, not missing CSV records. Diagnostic ordinary samples are 78 (line 492), 323 (2193), 567 (3885).

The JSONL repeats the frame values in full snapshots. Counting all six >400 ms records as six different stalls would double-count: the three unique ordinary samples above identify three observed long frames. The scaled 333 ms values again cannot measure actual long-frame duration. Offset changes approximately match the unscaled/scaled difference; current data support the same clock-truncation signature as the old issue. No CPU/GC trace for these exact frames was supplied, so their blocking owner and GC attribution remain unproven.

The ordinary-sample `backend_timestamp - unity_time` full-run range is 0.618844 s. Do not align this run with a single global median offset or use it to publish lead-time improvements. Event windows crossing gaps/steps require conservative ambiguity handling.

## Query cost and backend shadow evidence

The complete ordinary diagnostic costs on the three stalled frames were only 0.1391, 0.1351 and 0.1315 ms. Full-snapshot query maximum across the run was 2.0009 ms. This does not explain a 463–547 ms stall; it does not independently rule out unrelated UI, GC, Editor or other work on those frames.

There were 759 full snapshots: status completed/valid 756, skipped 3 (one required geometry/support invalid, two deferred platform/version mismatch). `query_completed` was true on 757 snapshots, illustrating that completion and required-result validity are separate fields. Three completed queries exceeded budget. No skipped result was reclassified as valid.

In `telemetry_logs/proximity_shadow.jsonl`, this run has 4,871 matching records: SAFE 4,447, UNKNOWN 424, active 0. Reasons: available 4,447; unsupported/calibration 298; insufficient_0_5s_history 123; stale geometry sample 3.

The history-insufficient episodes include initial post-calibration history acquisition and three post-gap recoveries, approximately 0.49–0.50 seconds each. These confirm TTE shadow continuity disruption. They do not establish an orange-model warning acceptance test, actual risk miss, or warning lead time: no TTE active episode occurred in this near-center idle run.

## Configuration and terminal limitations

- CSV consistently records selected difficulty 3, commanded/active difficulty 3, selected layers 3. Runtime sensitivity is not stored in this CSV and has not been independently confirmed; do not infer 0.55 from a current Inspector value.
- The user confirmed no board occupancy. All Wii rows record board_loaded=false and center_applied=false, with control_valid=true; 4,410 rows still have positive total_weight and 849 zero. These values must not be treated as evidence of human loading, successful calibration, or a new disconnection. Board/input behavior was not accepted by this test.
- Ball remained near center: radial distance at most 0.2486 world units. This was not an edge/recovery/transition test.
- CSV contains only running rows and no terminal outcome. Its last Unity source timestamp was 09:30:20.255. The local lifecycle records user_exit and terminal send-call completion at 09:30:21.557–.559, about 1.3 seconds later. A successful local Send return does not establish backend receipt or CSV persistence. Do not label this a completed three-layer run.
- Foreground/Profiler state and exact backend launcher were not independently established by these files. No diagnosis relies on assuming either.

## Next action

Do not repeat the remaining two Editor collection tasks or expand participant collection yet. Prepare/use a **normal standalone game build**, not yesterday's synthetic auto-start diagnostic executable, and perform one approximately 90-second idle comparison with the real backend. Confirm and record effective sensitivity 0.55, difficulty 3/3 layers, display configuration, foreground status and binary provenance first. Board use is not required for that initial continuity comparison. Only after this gate should normal movement/transition/real-board checks proceed. Do not relax StreamGuard or alter the model to hide the missing samples.
