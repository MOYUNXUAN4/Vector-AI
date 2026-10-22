# Unity handoff: ordered experimental warning replies

This is an additive transport change, not a new model or alarm policy. Backend and Unity work remain separate; the Unity agent needs only this protocol and synthetic examples, not backend filesystem access.

## Contract

`realtime.model_warning.warning_update_sequence` is a JSON integer, represented by C# `long`. Values are positive, up to 9223372036854775807. Every enabled bridge `attach()` constructing a reply advances the counter, including identical predictions, SAFE, UNKNOWN, invalid packets and model/runtime failure replies. The counter orders reply construction, NOT inference, terminal telemetry, or successful UDP delivery. Network loss can leave gaps.

The counter starts at 1 in a fresh backend bridge instance and does NOT reset on Start, Restart, layer transition, model state changes or duplicate Start. Unity accepts the first positive value for a new run; do not assume it equals 1. Counter exhaustion omits model_warning and preserves the legacy reply; it never wraps. Default-off replies remain unchanged, without model_warning.

On a backend restart the counter resets. Start a NEW Unity run with a fresh run_id after restarting the backend; transparent same-run recovery across backend restarts is not supported by this protocol. No automatic backend-instance adoption is permitted.

`prediction_sequence` still counts model decisions and may remain unchanged when UNKNOWN revokes an alarm. `input_sequence` and `input_source_timestamp` refer to the known model input identity, NOT reply creation order. UNKNOWN may use the last known input identity. Failed paths with no known layer use layer=0, not a guessed layer; unknown run ownership uses an empty run_id. No STRONG is valid without matching, known ownership.

Failure replies retain the existing warning keys: schema_version, experimental, enabled, model_id, model_sha256, run_id, layer, platform_instance_id, geometry_version_id, prediction_sequence, input_sequence, input_source_timestamp, feature_age_seconds, state, valid, probability_valid, strong_probability, reason, raw, confirmed, recovery_cancelled. Unknown identity uses neutral fields and remains invalid. Normal prediction payloads and identities are not rewritten.

## Receiver requirements

1. Handle current run ownership before changing its display. Foreign old-run replies must not clear a valid current-run warning. Keep layer lifecycle clearing and old-layer filtering.
2. Within the current run, reject missing/noninteger/nonpositive update sequence for the experimental display (fail closed), and ignore replies whose update sequence is <= the highest accepted update sequence. Do not update the high-water mark from foreign-run replies.
3. A newer current-run/current-layer UNKNOWN, SAFE or invalid reply revokes the display even if prediction_sequence/input sequence/source timestamp are unchanged. Do NOT require those older input fields to advance before processing revocation. Unknown layer=0 current-run failures revoke fail-closed; they cannot activate STRONG. Handle ownership-neutral/missing-warning failures fail-closed without guessing identity.
4. Only a NEW valid STRONG prediction can activate or renew the display. A newer reply sequence containing the same prediction is not a new decision, cannot renew its expiry, and cannot revive that prediction after revocation. Keep a revoked-prediction barrier.
5. Expiry remains feature_age_seconds at UDP arrival plus elapsed local monotonic time; >0.3 s revokes even with no packets. Distinguish receive-thread arrival time from later Update processing time. Neither duplicate messages nor reply sequence growth grants a fresh lifetime to old evidence.
6. New run clears display and sequence watermarks. On a layer transition clear display but preserve the current run's reply high-water mark; retain old-layer/input barriers against reactivation. Do not reset reply ordering merely because a layer changed.
7. Keep two-point confirmation and physical recovery cancellation in the backend. No client re-confirmation, model refit, extra hold/hysteresis or alteration of the original yellow rule.

## Self-contained fixture

Use CURRENT_RUN and CURRENT_LAYER matching the test fixture. Other required fields are held valid and constant; use a recent receive clock and feature_age_seconds=0.01. These are synthetic protocol values, not observations from gameplay.

| Packet | update sequence | prediction sequence | input sequence | state | valid/probability_valid |
|---|---:|---:|---:|---|---|
| A | 10 | 5 | 100 | STRONG | true/true |
| B | 11 | 5 | 100 | UNKNOWN | false/false |
| Late A | 10 | 5 | 100 | STRONG | true/true |
| Repeated old evidence | 12 | 5 | 100 | STRONG | true/true |
| New decision | 13 | 6 | 104 | STRONG | true/true |

A activates; B immediately revokes despite identical input/prediction identity; Late A is ignored; update 12 does not revive prediction 5; update 13 may activate if still valid, fresh and in the current layer. Also test duplicate update 11, SAFE revocation, current-run layer=0 failure, old run/layer, missing field, no-update expiry, new-run reset, and a layer transition retaining the reply waterline.

## Real acceptance still required

After Unity adaptation, enable the existing backend experimental options and perform real UDP STRONG activation, recovery, Restart/layer transition and backend-stop checks. The ordering unit tests do not establish real HUD appearance, end-to-end latency or model performance.
