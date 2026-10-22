# Independent v4 follow-up review (2026-10-20)

Scope: current files under ../staged_patches_v3_20261020. Read-only review and isolated fixtures, no apply/revert execution and no changes to candidate tools or Unity. Additional runnable counterexamples: reproduce_remaining.py.

## Confirmed improvements and reproduced results

- Existing test_v4_suite.py runs successfully: 29 PASS lines, not 30. These are Python checks, not PowerShell lifecycle or Unity compilation tests.
- P02 now includes the completed sessions and yields 90 descriptive CSV groups. These are not orange/purple accepted-client episodes or independent events.
- session_20261019_161529_760840: receive_step=false; transient receive-latency excursion 204.239ms; six source-minus-geometry difference jumps sum to 948.8ms. This reproduces the ledger's numbers. It supports avoiding a global clock offset, not claiming precise alignment automatically. Geometry query freshness/identity and pause state still matter. This is consistent with the already-known maximumDeltaTime/epoch-vs-scaled-clock concern, not proof of a new model failure.
- Correct wii_* flag names now detect explicit false values on real files; cumulative per-sample load, age, and generation checks improve the former heuristic.
- Strongly typed GUIStyle key and corrected .12/.24 sequential retransmit waits address the v2 issues at source level. No C# compile or visual verification was attempted.
- Source hashes remain UDPManager 096c5ffa591e8b5d98b24f51ba4902d8e4c38699c36301589d7b512c3eb35a90 and UIManager 03c9765ed598d19f6721f851f9cf378808ed0056aab7fac905ccd9b9d240b488.

## Remaining blockers

### 1. Missing board evidence still becomes a pass; reversed time also passes

patch_5_wii_preflight/wii_cop_preflight_v4.py:107-109 explicitly turns missing/empty flags into True, contradicting the output note that unknown does not pass. Missing age at :163 is not rejected; empty generation and controller identity strings also form a constant set. load_wii:85-90 still drops rows with missing weight/COP before indexing, contradicting the claim that rows are never dropped. gap_ok:180 accepts nonpositive timestamp differences and does not use the parsed sequence. It also prefers backend receive time over Wii ISO source time, which it does not parse.

Counterexamples:

- 60 loaded/still rows with timestamp but no board/center/control flags -> OK; all flag_columns_present values False.
- 60 otherwise valid loaded rows with timestamps decreasing by 20ms -> OK, window_duration_s=-0.98.

Require finite values, explicit evidence eligibility (or a separate UNKNOWN/descriptive-only status), positive monotonic source time and duration, sequence/identity continuity, and preserve invalid rows as barriers. Add missing-column/empty-field/reverse-time fixtures.

### 2. Global clock sufficiency still falsely asserted for gradual drift

patch_4_clock_profile/receive_latency_profile_v4.py:201 sets single_global_offset_sufficient to len(jumps)==0, and CLI prints this as a positive claim. Discrete jumps require a >50ms single adjacent change; gradual drift and repeated smaller jumps can evade it. Counterexample: 240 consecutive 20ms source samples with a 1ms-per-row dual-clock drift -> measured spread 239ms, but single_global_offset_sufficient=True. NO_STEP or absence of detected jumps is not proof of a sufficient offset. Gate sufficiency on predeclared spread/drift/coverage/identity rules, otherwise UNKNOWN; require physical CSV line/run provenance. The current row_index is a filtered Unity-array index, not physical CSV line.

### 3. Closure contradictions do not block the validated verdict

tools/session_closure_audit_v4.py:139 sets TERMINAL_OUTCOME_VALIDATED before diagnostics, then :168 only attaches outcome_match. An ended CSV edge_exit at seq10 plus same-run diagnostic terminal user_exit at seq20 still returns TERMINAL_OUTCOME_VALIDATED, outcome_match=False and unpersisted_sequence_span=10. The CLI consequently hides the inconsistency under --only-problems and returns success. Require same-row terminal validation, known outcome semantics, single-run ownership, and explicit conflict statuses when diagnostic outcome/sequence contradicts the persisted terminal. Keep missing diagnostic evidence distinct from contradiction.

### 4. Episode context and CLI controls incomplete

patch_3_warning_episodes/cluster_warning_episodes_v4.py:136 uses platform_level as platform identity; actual geometry_platform_instance_id and geometry_version_id are not keys. Same-layer platform/version changes merge (reproduced). Decreasing timestamps/sequences merge too (reproduced). --seq-tolerance is parsed at :231 but not passed by :252 to episodes_for_session/group_episodes, so changing that CLI argument has no effect. File-wide outcome and first fall are still assigned across possible multiple runs. Split or reject ambiguous identity, order and mixed-run evidence; propagate CLI options and define whether tolerance means missing packets or sequence delta. Do not treat a fallback edge_warning_state channel name as proof of an independent warning system: it may be another field representation of the same rule.

warning_episode_id not being an attention-channel counter does not by itself establish a broken field. UDPManager serializes player.WarningEpisodeId; attention uses separate attention_episode fields. The correct bounded finding is that this ID is not a universal per-channel key, which v4 already avoids using.

### 5. Apply/revert safer but not fully target-bound or failure-transactional

Independent Luna static review confirmed: baseline hash checks, posthash idempotency, changed-target refusal and backup hash checks before revert are improvements. Still:

- P1 apply:40-49/P2 apply:37-46 do not require normalized current target == receipt.target. Revert -TargetOverride similarly bypasses target identity. Same-content alternate files can therefore be treated as the receipt target.
- P1 apply:69-76/P2 apply:66-73 accept an existing named backup without verifying its hash before changing the target. A corrupt backup can yield a successful apply whose revert later cannot work.
- Target replacement precedes receipt persistence (P1 :149-160; P2 :254-266). A failure between them leaves changed source with no receipt. Move-Item -Force alone does not establish atomic replacement guarantees on all failure paths. Use pending/commit recovery and explicit backup verification, not a stronger atomicity claim than has been tested.
- Default apply targets production Unity files; DEFERRED is documentation, not an executable guard. This is intentional apply semantics, not evidence those files were already changed. Sandbox commands must always provide the intended override.
- No PowerShell lifecycle regression tests are present in the supplied Python suite. Add disposable-copy tests covering target mismatch, corrupt existing backup, receipt write failure and no-receipt state. Do not run them against production.

## Historical-tail wording

P01 09:28:57 and 09:52:25 incomplete tails were already identified before the later clean standalone retests. Sequence spans 76 and 50 describe those earlier runs; they do not establish that terminal delivery still fails in the subsequent 10:04/10:06 or P02 runs. Keep chronology and versions separate. Send-return and sequence difference are not per-packet delivery proofs.

## Disposition

Accept v4 as an improved staged candidate, not a routine acceptance gate. Repair the remaining offline unknown/ordering/conflict handling and safety boundaries, add adversarial fixtures, then re-review. Keep normal Player, models and settings unchanged; no board recollection is required for these fixes. This audit did not apply or compile candidate C#.
