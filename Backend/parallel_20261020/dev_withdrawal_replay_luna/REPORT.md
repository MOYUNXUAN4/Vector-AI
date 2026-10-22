# Original development TTE withdrawal replay

This is a decision-level descriptive replay of the fixed TTE benchmark over the saved 31-session INPUT055_CHECK development manifest. It uses the exact saved feature inputs and feasibility labels, the fixed benchmark rule, and the existing pure replay_prediction_stream and build_alarm_episodes functions. It does not fit a model, select a threshold, or change policy settings.

## Integrity and replay

- 31 sessions, 7,553 decisions, 699 active decisions, and 80 episodes.
- All 31 raw.csv SHA-256 values under telemetry_logs/INPUT055_CHECK match the raw_sha256 field in the saved manifest.
- The derived feature, label, manifest, benchmark, scorer, replay, policy, and saved-reference hashes are recorded before and after in summary.json; they are unchanged.
- Replay matches the saved fixed-TTE aggregate reference on episode count (80), observed-nonentry active exposure (8.06000018 seconds), and total active exposure (42.34000015 seconds). The reference has 48 event labels and 40 event hits, but contains no saved decision-level withdrawal trace.
- The fixed rule remains q = directional_edge_distance - 2 * ball_radius, q > 0, outward velocity > 0, q / velocity <= 0.75, probability threshold 0.5, two-point confirmation, immediate raw OFF, and saved joint-recovery input.

## Withdrawals and censoring

There are 77 observed active-to-inactive decisions with a same-context next decision. Three active episodes are boundary-censored separately: two at context changes and one at game end. The context-change rows are not counted as withdrawals, including a row where the next context has a joint-recovery flag. The policy reset at the context boundary, so that flag did not cancel the old episode.

Among the 77 observed withdrawals, 49 are invalid inputs because q <= 0; the policy reason is invalid_input. The other 28 are normal raw_off decisions. Movement at the withdrawal decision is recorded independently: 12 inward, 26 outward slower than the previous sample, and 39 outward in the other category. Movement is not treated as proof of recovery. No active episode was canceled by the policy joint-recovery rule.

For the 28 normal raw_off decisions only, episode_withdrawals.csv also includes a descriptive next-0.4-second trace. It stops at the first context change or gap above 0.1 seconds and marks incomplete horizons. The future fields are explicitly noncausal and do not affect withdrawal classes or labels; aggregate counts are in summary.json.

Exposure status is copied from saved labels and retained by class, including unknown, already_inside, and controller_active. No exposure class is relabeled, and completion is not treated as evidence of human recovery.

## Limits

This replay describes saved decision inputs and policy outputs. It does not reconstruct Unity/network/display timing. The raw CSV has no Unity display age, so no age is inferred or fabricated. Inward instantaneous velocity is only descriptive; genuine recovery is recognized only through the saved joint-recovery flag and actual policy cancellation. No lead/F1 upgrade, threshold sweep, or hold experiment is performed.

## Files

- replay_withdrawals.py: standalone replay generator.
- test_replay_withdrawals.py: helper and policy self-tests.
- decision_traces.csv: one row per saved decision with identifiers, status, q, velocity, TTE, recovery inputs, policy state, and previous identity.
- episode_withdrawals.csv: 77 observed transitions with actual policy reason, current/previous identities, velocities, TTE, recovery flag, and movement class.
- boundary_censored_episodes.csv: three context- and game-end-censored episodes, including the boundary row where available.
- summary.json: counts, saved-reference comparison, exposure classes, and source hashes.
