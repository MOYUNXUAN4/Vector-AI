# Independent v6 review (2026-10-20)

Scope: ../staged_patches_v6_20261020. No candidate tools, Unity sources, scenes, game builds, models or thresholds changed. Tests use temporary fixtures/copies, not production apply/revert.

## Reproduced results

- Main test_v6_suite.py: 66 checks, 66 passed, 0 failed, exit 0. It also invokes the latency self-test (10 successful checks).
- Re-ran tests/check_boundaries_v6.py: 1020ms source gap with continuous receive time -> NO_ELIGIBLE_WINDOW; nonfinite timestamp -> UNKNOWN_EVIDENCE; lifecycle-only and incomplete manually constructed diagnostic entries -> unavailable, not corroborated.
- Source-clock selection is now explicit per file, ISO timestamps parse, receive-only input cannot certify source continuity, and explicit source gap/sequence barriers are tested.
- Actual terminal_snapshot_frozen records can corroborate outcomes; ordinary bookkeeping cannot. Unknown send completion remains distinct from failure.
- Test suite reproduced P01 22 terminal-validated/corroborated and P02 4 terminal-validated/corroborated runs; P02 90 descriptive warning groups remains unchanged. This is not model performance acceptance.
- v5/v6 receive_latency_profile_v5.py SHA256 matches exactly: c40c65282b9be04d295199680511a024ef6339da3ac15025c61f08841ce2c9cf.

## One additional hard-gate blocker: final-row identity is inherited

tools/session_closure_audit_v6.py:132-151 maintains last_seq only when the current row has a nonempty parseable sequence and obtains run_id from the last nonempty ID anywhere in the file. It does not require the final ended/outcome row itself to have a valid run_id and sequence. The stronger terminal-evidence branch then compares the inherited values to diagnostics.

Reproduction: check_terminal_identity.py (isolated temporary CSV, no source changes):

1. CSV row A: run_id=r1, sequence=10, run_state=running, no outcome.
2. CSV final row B: run_id blank, sequence blank, run_state=ended, outcome=edge_exit.
3. Diagnostic for r1: actual terminal-present flag, sequence=10, outcome=edge_exit, send completed.
4. Actual result: TERMINAL_OUTCOME_VALIDATED/corroborated, run_id=r1, last_seq=10, unpersisted_sequence_span=0.

This does not prove a same-run identified terminal row was persisted: row A was still running and row B has no identity. `--require-corroboration` would not reject this because the returned evidence is corroborated. Treat terminal-row identity as unknown/invalid, do not inherit it. Require a nonempty run ID on that exact row and a strictly parsed valid integer sequence; reject missing, fractional/nonfinite and conflicting values. Use that row's identity for diagnostic comparisons. Add independent blank-ID and blank-sequence fixtures as well as this combined case. This is a narrow offline-tool correction, not a reason to change game code or recollect board data.

## Use boundaries

The board tool remains a descriptive selected-window check. Its --window counts recorded rows; repeated source pairs may yield fewer unique samples and shorter source duration, which must be reported instead of claiming a fixed stationary duration or a completed calibration procedure. Source/control timestamps originate in the Wii host telemetry implementation; continuity is not direct proof of hardware sampling health. Do not silently convert the descriptive check into a general participant preflight acceptance criterion.

The source/geometry offset gate remains specific to the observed pair/span and predefined numerical QC rules; it is not an event-interval alignment repair. No GC cause, model upgrade, automatic relabeling, or frozen-results replacement follows from these tests.

## Production checks

UDPManager.cs SHA256: 096c5ffa591e8b5d98b24f51ba4902d8e4c38699c36301589d7b512c3eb35a90.

UIManager.cs SHA256: 03c9765ed598d19f6721f851f9cf378808ed0056aab7fac905ccd9b9d240b488.

Both remain at the expected unapplied source versions. Candidate C# is not compiled or visually accepted. P02 actual rows already have proper terminal identities, so the synthetic counterexample does not overturn their corroboration.

## PowerShell verification completed

Luna reviewed then ran the supplied test_ps_lifecycle.ps1 against temporary copies only: 98 passed / 0 failed, P1/P2 49 each, process exit 0. Kept workdir: %TEMP%/v5_ps_lifecycle_900f127e (test naming retains v5). The previously identified commit-write failure, recovery-write failure and truncated committed JSON paths reproduce the advertised exit12/pending preservation/recovery and exit11 refusal behaviors. Production source hashes still match.

One additional static safety boundary remains: pending recovery validates target and intended-post hash but does not validate the complete rollback record before committing it. P1 apply:189-195,221-237; P2 apply:175-181,199-222; related revert recovery branches approximately :79-108/:74-104. A readable target-bound pending with correct current post hash but missing/corrupt backup_file or pre_patch_hash can be promoted to a committed receipt without first verifying that the backup exists and hashes to the declared pre-state. Revert later refuses before modifying the target, so this is loss of assured rollback capability, not observed source destruction. This is a static-path finding; the supplied 98 tests use valid pending metadata and backups and do not inject this corruption. Require complete receipt-schema validation and pre-backup hash verification before recovery commits or declares success; add missing/damaged backup pending fixtures on disposable copies.

Disposition: the three previously requested fixes and their tests are independently reproduced. v6 remains usable as manually reviewed descriptive analysis, not a blanket unattended acceptance or safe-deployment certificate until exact terminal-row identity and rollback-evidence validation are closed. No additional board collection or Unity changes are needed for those two narrow fixes.
