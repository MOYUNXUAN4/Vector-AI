# Independent review of staged_patches_v2_20261019

Date: 2026-10-20. Read-only review. No apply/revert script was run. Unity source, normal game binary, model and settings were not modified. Scope: 11 files in parallel_20261019/staged_patches_v2_20261019. Reproduction harness is reproduce.py in this review directory; it imports the Python modules and uses in-memory synthetic inputs.

## Decision

Do not approve the package as a whole for production use or routine scientific evaluation. Its placement and advertised target paths are correct, and v1 is marked deprecated. There are substantive safety and evaluation defects below. Current P02 standalone runs already demonstrate improved continuity without either Unity patch; do not attribute those results to this unapplied package.

## Findings, prioritized

### P1: successful sessions excluded from warning analysis

patch_3_warning_episodes/cluster_warning_episodes_v2.py:31,162 excludes sessions with outcome calibration_completed unless --include-calibration. In this project that outcome is ordinary completion of a configured collection session, not a pre-game board-calibration-only session. Running its default CLI against P02 skips all three completed runs and retains only the fall run (27 clusters). This selection makes recovery/completion warning burden unreportable and can bias comparisons. Include completed gameplay by default, classify actual preparation intervals from explicit evidence, and count all excluded sessions with reasons.

### P1: unsafe backup and rollback

patch_1_terminal_delivery/apply.ps1:26-28 and patch_2_uimanager_style_cache/apply.ps1:20-22 create a backup only when it does not already exist; no source hash binds the backup to the current target. Both revert.ps1:5-6 unconditionally Copy-Item -Force over the current source. This can destroy edits made after application or restore an obsolete backup. If an already-patched target has no backup, apply first backs up patched content then returns already applied; revert no longer removes the patch. Postwrite failure recovery also trusts that backup. Require a per-application before/after hash receipt, unique immutable backup, and refusal to revert a target whose hash has changed. Current scripts also lack transactional file replacement and a compilation gate. PowerShell syntax parsing is clean; syntax is not runtime acceptance.

### P1: receive-latency profile does not validate Unity clock alignment

patch_4_clock_profile/piecewise_clock_profile.py:59 computes backend receive epoch minus Unity source epoch, not epoch minus Unity Time.time. These are different quantities. At :63 segments split only when source gaps exceed 0.4s; a latency step or drift inside a continuous segment is not tested. The :136 claim that NO_STEP means a single global offset is sufficient is unsupported for Unity/epoch alignment and can even miss a receive-latency step. In-memory reproduction with continuous 20ms source samples and latency changing from 5ms to 105ms returns step_detected=false and max_adjacent_step_ms=0. Keep this tool as a clearly bounded receive-latency summary only; retain separate dual-clock provenance and interval/gap treatment for lead-time evaluation.

### P2: episode grouping and channel identity not reliable for experimental warning evaluation

patch_3_warning_episodes/cluster_warning_episodes_v2.py:76-90 ignores false warning rows and groups only positive rows by a 0.5s time gap. It does not split on run, platform, layer, geometry version, source sequence discontinuity, explicit clear, or warning channel; :100 assigns the last run_id to the file's episodes. A two-row fixture from different runs/layers is merged into one group. An explicit CLEAR between two warnings is also bridged. Such groups may be a descriptive gap-cluster if labeled that way, but are not accepted client-state episodes. The CSV warning fields are not orange model or purple TTE acceptance logs. Do not label this output as their alarm counts or burden. Short episodes are listed but omitted from --out CSV (:195), so the exported dataset is incomplete when --min-duration is used.

### P2: closure audit assigns cause from end timestamps and overstates packet evidence

tools/session_closure_audit.py:127 accepts any nonempty outcome as CLOSED_OK without terminal-state/sequence consistency. :134 labels simultaneous source stop as RECEIVER_BLACKOUT; :136 labels all other cases UNITY_STOPPED_FIRST, including missing Wii evidence or Wii stopping earlier. End timestamps alone cannot establish process death, writer blocking, network loss, or which source failed first. :148's terminal sequence minus last CSV sequence is an unpersisted sequence span, not proof that every intervening packet was sent; frozen sequence alone is weaker than a send-return record, and a send return is still not an ACK. Use neutral observations and unknown cause, validate terminal/run identity, and preserve provenance. It is not an acceptance gate as written.

### P2: Wii preflight is a descriptive loaded-still-window heuristic

patch_5_wii_preflight/wii_cop_preflight_v2.py:76 accepts average window load, not sustained per-sample valid load. It does not check board_loaded, center_applied, control validity/age, controller/center generation, source gaps or time duration. It removes invalid rows before constructing a consecutive index window, potentially bridging missing evidence. A first stationary off-center posture is not proof that the operator must tare/re-zero; a later arbitrary quiet gameplay interval is not necessarily a baseline calibration interval. Returning OK for weight+COP arrays alone is confirmed by the in-memory fixture. Keep the output descriptive; require protocol-marked stationary calibration and continuous valid input before treating it as a preflight gate. Distinguish not-stationary from insufficient-load failure.

### P2: GUIStyle cache uses a hash as identity

patch_2_uimanager_style_cache/apply.ps1:77-104 uses Dictionary<int,GUIStyle> with a combined 32-bit hash, not a structured key with equality. Distinct style inputs can collide and return a wrong style. Use a value key containing size, Color, font style, alignment and padding. Current mutation sites are handled more carefully than v1 (chat styles cloned, balance/box properties separated), and HUD visibility is preserved. However identical pixels and zero allocation are not established: chat styles still allocate clones and strings remain. Require compile/regression/visual/allocation tests after any separately approved implementation.

### P2: terminal retransmit timing does not match its success message

patch_1_terminal_delivery/apply.ps1:57-60 waits 0.12s then another 0.36s, so nominal sends occur at +120ms and +480ms (or later), not +120/+360ms as :95 states. It is a MonoBehaviour coroutine and is not guaranteed to survive scene destruction or process exit. Backend duplicate-terminal handling has not been verified by this package. This is optional delivery hardening, not a fix for a multi-second receiver/persistence outage. Defer because current P02 terminal delivery is complete without it.

## Documentation concerns

README correctly warns against v1, confirms no v2 apply_all script, and points backups to patch directories outside Assets. Two additional reviews contain historical causal claims that should not be copied into a thesis: current registry values do not establish every historical sensitivity; allocating N bytes between collections does not establish live heap size or GC pause ownership; a negative synthetic Player test does not prove all Player gameplay is stall-free. The current normal Player uses real default ports, unlike the separate synthetic probe. Keep those populations distinct.

## Suggested disposition

1. Keep production and the normal standalone build unchanged.
2. Repair staged-tool scientific semantics, add synthetic regression cases, and re-audit P02 including all completion sessions before routine use.
3. Make apply/revert hash-bound and transactional before considering any Unity patch.
4. Consider GUIStyle caching separately only if measured need remains; do not merge terminal retransmit speculatively.

No new board collection is necessary to fix these tool and packaging defects. This review is not authorization to apply them.
