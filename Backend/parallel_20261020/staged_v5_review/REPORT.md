# v5 verification and bounded disposition (2026-10-20)

Package: ../staged_patches_v5_20261020. Review only. Candidate tools and production source unchanged. Unity source hashes verified at completion: UDPManager 096c5ffa591e8b5d98b24f51ba4902d8e4c38699c36301589d7b512c3eb35a90; UIManager 03c9765ed598d19f6721f851f9cf378808ed0056aab7fac905ccd9b9d240b488.

## Verified improvements

- Original six v4 counterexamples are addressed by the existing fixtures. Main Python suite: 38/38, exit 0; the latency self-test's 10 checks also pass.
- Luna read the PowerShell test and apply/revert implementations before running tests/test_ps_lifecycle.ps1 -KeepWorkDir against disposable copies only: 54 passed, 0 failed, P1/P2 27 each. Workdir %TEMP%/v5_ps_lifecycle_127bc222. Production files only read/copied/hashed; no production apply/revert invocation.
- Baseline/source hash checking, receipt-target checking before marker detection, pre-apply backup verification, changed-target refusal and pending recovery in ordinary tested states improve safety materially.
- Main suite reproduced P01 22 terminal-validated sessions and P02 all four terminal-validated sessions. P02 still has 90 descriptive CSV warning groups. Those are not model episodes or performance denominators.
- Main suite reproduced the old 16:15 session's six source/geometry difference jumps totaling 948.8ms and an insufficient global-offset verdict. Keep the historical-pair scope and no-causal-GC claim.
- 20ms/coverage/sample-count rules are explicit engineering QC rules. They do not certify capture-time intervals or upgrade frozen model performance conclusions. Geometry query validity, ownership, order, run and gaps still need separate checks when used in evaluation.

## Remaining gate blockers (do not expand to new model experiments)

### A. Wii continuity still evaluates receive time, not source continuity; nonfinite timestamps pass

patch_5_wii_preflight/wii_cop_preflight_v5.py: TIME_COLUMNS prefers backend_timestamp. `_time` only parses numeric values and cannot parse actual Wii ISO source_timestamp. The window therefore measures receive-time continuity even when source time is available. No source or control sequence is retained/checked. It also may switch time column per row without recording the selected domain in the final window output.

Additional fixture in check_boundaries.py: valid loaded/centered rows have a 1020ms ISO source gap, while receive timestamps advance by 1ms. audit returns OK with window_duration_s=0.049. Queued/rapidly drained packets do not establish uninterrupted source control. Parse/select one declared Wii source clock, preserve domain and source/control-sequence evidence, reject barriers, and report receive timing separately. If intentionally retained as a receive-only descriptive statistic, remove claims of source continuity and do not use as a preflight acceptance gate.

`_num` tests x==x, which rejects NaN but accepts Infinity. The second fixture sets all backend timestamps to inf: audit still returns OK with window_duration_s=NaN. Require math.isfinite for timestamps, ages, load and COP and validate numerical CLI settings. This directly contradicts the stated finite-evidence boundary; do not silently serialize NaN as accepted JSON evidence.

### B. Closure evidence is overstated when diagnostics contain no terminal

tools/session_closure_audit_v5.py sets corroborated in its final fallback whenever any diagnostic entry exists, unless conflicts or a positive sequence span intervene. index_diagnostics also creates entries from new_run_created/restart lifecycle records, so existence of an entry is not existence of terminal corroboration.

Fixture: ended CSV edge_exit at seq10, diag entry contains only files and last_sample_ts (no frozen terminal, no outcome, no seq, no send result). Result: TERMINAL_OUTCOME_VALIDATED/corroborated. CSV-only validation can remain a weaker status, but terminal_evidence must be unavailable/partial, not corroborated. Require explicit same-run matching frozen outcome and sequence before that stronger label. Unknown send completion alone need not be treated as failed; distinguish missing terminal from unknown send. The four real P02 runs have matching actual terminal evidence, so this defect does not invalidate their demonstrated closure.

### C. Commit-write failure can defeat pending recovery

P1 apply.ps1:119-122 / P2:109-112 write committed JSON then remove pending without a guarded verified commit. Both scripts use ErrorActionPreference=Continue. A write failure can allow execution to proceed to removing recovery evidence and exit 0. Normal commit P1:294-302 / P2:390-398 catches a write error but still exits 0 with pending; a partially written/truncated committed JSON takes priority over the valid pending file in subsequent apply/revert reads. Thus the documented automatic recovery is not complete for receipt-write failures.

This is a static failure-path finding, not a reproduced disk-full/partial-write event. Existing T5 fails before target replacement by blocking the receipt root; T6/T8 manufacture a successful pending state. They do not exercise commit partial writes or recovery-commit failure. Write/validate a temporary receipt and replace the committed file only when verified; on failure retain a verified pending record and return a distinct non-success/recovery-required status. Treat malformed committed JSON with valid pending as a recoverable state, rather than discarding pending. Add fault injection for initial commit and recovery commit, entirely on temporary copies.

## Disposition

The intended v4 fixes are genuinely improved and the reported 38/54/10 results reproduce. Accept v5 for exploratory descriptive use with the documented scope, not as an unattended data-quality/preflight gate. Only the above boundaries need closing before routine acceptance use. Do not repeatedly re-tune models or collect more board data to fix these tooling defects. Keep both Unity patches deferred: no C# compilation, render comparison or allocation test has been performed, and no active-board regression from this review is claimed.

Executable additional counterexamples: check_boundaries.py in this directory. It creates and removes isolated temporary CSV fixtures only. No candidate tool/source was edited.
