# v8 scoped verification (2026-10-20)

Scope: F from staged_v7_review/REPORT.md: strict diagnostic sequence/outcome/timestamp handling and per-session isolation. D/E are not reopened; unchanged executable files are checked by hash. No Unity patch applied, no candidate tool/runtime/model/settings/raw source changed.

## Python verification

Independently ran tests/test_v8_suite.py with bundled Python, -B -u: 111 checks, 111 passed, 0 failed, exit 0. Included latency self-test: 10 checks passed. Also ran tests/check_boundaries_v8.py: normal JSON integer diagnostic sequence corroborates, missing/string/fractional/integral-float/bool/nonfinite inputs become partial with named defects rather than the v7 TypeError. The diagnostic sequence fixtures use real JSONL and index_diagnostics, which is the supported normal path. audit_session consumes that typed index, not an arbitrary unvalidated hand-built dictionary.

Code review confirms parse_diag_sequence is invoked before the index stores terminal_seq; rejected values become None, retain type/defect evidence and are not subtracted. Bool is rejected before int. Non-string/empty diagnostic outcome is partial instead of a spurious outcome contradiction. Diagnostic timestamp subtraction requires a finite non-bool numeric value.

The suite's real CSV parser-error fixture (field exceeds csv's field-size limit) reproduced exit7, one TERMINAL_OUTCOME_VALIDATED session plus one AUDIT_ERROR, with the exception named. This validates per-session CSV audit isolation, not universal malformed-log resilience. Diagnostic indexing runs before that per-session loop. Invalid JSON parse lines are still skipped under existing policy, as disclosed by the package. Do not claim arbitrary malformed diagnostic documents are isolated/reported per session or that every unreadable line is accounted for.

## Preserved real-data conclusions

The same run reproduced P01 22 terminal-validated/corroborated sessions, P02 4/4 terminal-validated/corroborated sessions and P02 90 descriptive CSV groups. Model metrics, prior training splits, labels and frozen decisions were not recomputed or changed. Ninety groups are not model alarm counts or false-alarm denominators. Earlier P01 missing tails are not evidence of failure in later P02 runs.

## Production source unchanged

- UDPManager.cs SHA256 096c5ffa591e8b5d98b24f51ba4902d8e4c38699c36301589d7b512c3eb35a90
- UIManager.cs SHA256 03c9765ed598d19f6721f851f9cf378808ed0056aab7fac905ccd9b9d240b488

C# compilation, render equivalence, allocation improvement and Unity-patch runtime behavior remain unverified and are not authorized by this scoped audit. Continue using the unchanged normal standalone Player.

## PowerShell and unchanged-file verification completed

Luna reviewed the test isolation before executing test_ps_lifecycle.ps1 -KeepWorkDir: 138 passed / 0 failed, exit0. Workdir %TEMP%/v8_ps_lifecycle_6a3d4f40. TargetOverride refers only to Reset-Target temporary copies; revert obtains the same temporary target from their receipts. Added pending-byte-preservation assertions passed. No production apply/revert invoked.

Four apply/revert scripts and patch3/4/5 executables have SHA256 identical to v7:

- P1 apply eab60ad0c9c4b9759b86eefa78faf14dd5c669fe8d43a80a1dbbd1f9eaca669b
- P1 revert f0cb61aae95af3f2b112ca763611e37db0afc8e9f3559986f2a1f346e9e843d1
- P2 apply 6ca418e2294ae6cde6013a8292dc8fd3689cc04109867ee9676caa6aa793ac95
- P2 revert f624fd9767241653afba72e2aa0e852ecdb1464bdd50faee1a2ab5459ea1e2f8
- patch3 5249d0c533cb25302bf18e65939f4b42c6e0976d44668c59a0dd7f95ea7444da
- patch4 c40c65282b9be04d295199680511a024ef6339da3ac15025c61f08841ce2c9cf
- patch5 af2f76a56fc586451b4b6668273b8c97d65abdb2b38538b620a5532dcc3e790c

## Disposition

F passes the agreed bounded verification. Retain v8 as the current reviewed baseline for manual descriptive quality checks of the supported logs, with per-session CSV audit error reporting. This closes the current patch-tool review chain; no new blocking issue found within F. The explicitly disclosed malformed-JSON indexing limitation remains a scope limit, not a newly claimed universal guarantee. No board recollection, Unity patch application or model changes follow automatically. Return to the main research workflow separately: compatible-data warning lead time, misses and recovery burden, keeping experimental channels and performance definitions separate.
