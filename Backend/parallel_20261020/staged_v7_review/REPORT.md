# v7 bounded acceptance review (2026-10-20)

Package: ../staged_patches_v7_20261020. Target scope: previous review's D (exact terminal-row identity) and E (rollback evidence before pending recovery). No Unity patch applied; candidate files, game, settings, models and raw data unchanged.

## Verified Python results

test_v7_suite.py independently rerun: 85 checks, 85 passed, 0 failed, exit 0. Latency self-test's 10 checks also passed. Missing CSV terminal run/sequence, fractional/nonfinite CSV sequences and combined inherited-identity fixtures now return unresolved/unavailable. Correct identified terminals still corroborate. The old D counterexample is fixed.

The same suite independently reproduces P01 22 validated/corroborated plus 5 not validated, P02 4/4 corroborated and 90 descriptive warning groups. These results preserve chronology; older incomplete P01 tails do not establish failure of later P02 runs. None are model alarm counts or accuracy/lead-time acceptance results.

## Additional abnormal-input robustness observation (outside D's CSV-only parser)

tools/session_closure_audit_v7.py:311-312 subtracts diag terminal_seq from CSV terminal_row_sequence whenever neither is None, before :347 verifies that the diagnostic sequence is an integer. index_diagnostics copies the JSON sequence without validating its type.

Isolated check_diagnostic_sequence.py results:

- diagnostic sequence 10 -> validated/corroborated;
- diagnostic sequence None -> validated/partial;
- diagnostic sequence "10" or "bad" -> uncaught TypeError at subtraction;
- diagnostic sequence 10.5 -> validated/partial.

The quoted-string case is a malformed diagnostic input, not a defect found in the current real integer-sequence logs. It does not undo D's successful CSV-identity fix. Before claiming resilient unattended bulk auditing of arbitrary malformed logs, validate diagnostic sequence type BEFORE every comparison/subtraction (exclude bool as integer), report malformed evidence as partial/invalid per session and keep processing the other sessions. Add string/fractional/bool fixtures; do not silently coerce an invalid diagnostic identity. No production/model change or board recollection is required.

## Production state

Expected source SHA256 remains:

- UDPManager.cs: 096c5ffa591e8b5d98b24f51ba4902d8e4c38699c36301589d7b512c3eb35a90
- UIManager.cs: 03c9765ed598d19f6721f851f9cf378808ed0056aab7fac905ccd9b9d240b488

C# compilation, visual equivalence, allocation measurements and runtime patch behavior are not established by these file-level checks. Continue using the existing normal standalone build, with no patch application inferred from this review.

## PowerShell E verification completed

Luna read the updated scripts and test harness, then ran test_ps_lifecycle.ps1 against temporary copies only: 134 passed / 0 failed, exit 0. Kept workdir %TEMP%/v7_ps_lifecycle_76611c4d. Production hashes remained unchanged. Test-RollbackRecord checks 64-hex pre/post values, current target post hash, backup existence/readability and actual backup hash==pre before committing pending recovery or reverting a pending-only state. Missing/altered/incomplete rollback evidence refuses with exit13, retains pending and does not write a committed receipt. Repairing the backup enables retry. T15 explicitly verifies byte-identical pending preservation; the related T16-T18 refusal paths do not all independently assert pending-byte equality, but static review confirms no pending mutation in those refusal branches. No blocker found within the agreed E scope.

## Decision

Previous D and E acceptance criteria pass. v7 may be retained as the reviewed staged baseline for manual descriptive QC of schema-conforming current records. No need to relaunch the board or replace the normal Player. Do not promote this scoped pass to permission to apply Unity patches, a universal safe-deployment certificate, model-performance acceptance, or a claim of robustness to arbitrary malformed diagnostic JSON. The diagnostic-sequence type guard above is a small, reproducible follow-up before unattended bulk use; it is not a reason to restart the entire audit chain or re-label current P02 data.
