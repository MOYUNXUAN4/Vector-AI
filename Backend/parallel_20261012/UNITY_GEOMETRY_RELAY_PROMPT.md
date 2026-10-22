# Unity-only implementation request: independent geometric danger relay

Only access the Unity project. Do not access, run or modify the backend. Do not change physics, input, sensitivity, platform recycling, death/layer predicates, ordinary UDP rate, original yellow warning, or model thresholds/cancellation policy.

The backend now adds `geometry_warning` to the realtime reply, independently of `model_warning`. This is an experimental geometric rule, NOT a model prediction. Do not turn geometric risk into a model probability or claim performance improvements.

## Payload contract

`schema_version=1`, `experimental=true`, `enabled=true`, `source="geometry_rule"`, `policy_id="outer_clearance_nonpositive_v1"`.

Identity: `run_id`, `layer`, `platform_instance_id`, `geometry_version_id`, `input_sequence`, `input_source_timestamp`.

Ordering: `warning_update_sequence` is a positive signed 64-bit integer. The two warning objects in ONE reply share this value. Use separate model and geometry watermarks, or parse both atomically before advancing one shared watermark; never discard the second object as a duplicate of the first. Keep run-level watermarks across layer changes; reset only for a new run. Do not admit old-run/old-layer activations.

Geometry: `clearance`, `clearance_valid`, `state`, `valid`, `reason`, `sample_age_seconds`, `query_age_seconds`, `geometry_age_seconds`.

`clearance = directional_edge_distance - ball_radius`.

* `CRITICAL`: valid fresh geometry, clearance <= 0. The ball surface reaches/passes the radial outer edge. This is danger, not certainty of falling.
* `CLEAR`: valid fresh geometry, clearance > 0. Only clears this geometric condition; does NOT prove the whole situation safe.
* `UNKNOWN`: geometry invalid/stale/unavailable. Clear any geometric claim.

No geometric probability or prediction_sequence exists. Unknown identity values may be neutral (layer/platform/sequence 0, empty version); they must not activate anything.

## Display and expiry

1. Add an independently labelled experimental indicator, e.g. `EDGE DANGER (geometry rule)`. Keep the original yellow rule intact. Distinguish it visibly from `EXPERIMENTAL AI WARNING`.
2. Fresh current-context CRITICAL can remain visible even while model_warning is UNKNOWN. It must NOT keep an invalid model prediction alive.
3. CLEAR/UNKNOWN only clear geometric display. They must not clear a separately valid model STRONG solely because the geometric relay is absent.
4. Track total age as received `geometry_age_seconds` plus elapsed local monotonic time. Clear at >0.3s, even if no more packets arrive. Reject invalid/negative/nonfinite ages. Never renew the underlying sample lifetime merely because reply-update sequence increases. Repeated input sequence/time must not reset query age; reject inconsistent repeated-sample freshness.
5. On new run, end, restart, layer/context change, invalidate displayed old-context danger. An old-layer packet can advance ordering watermarks, but cannot activate/renew current display.
6. Missing/invalid geometry object must not break ordinary realtime parsing. If its run cannot be established, do not let an unidentified old packet clear a current lease; rely on <=0.3s expiry. Identifiably current invalid geometry fails closed.
7. Backend sequence restarts require a fresh Unity run; never lower a run's watermark to accept a restarted process.

## Acceptance criteria

Add synthetic tests for model UNKNOWN + geometric CRITICAL, model STRONG + geometric CLEAR, CRITICAL -> CLEAR/UNKNOWN, >0.3s disconnect expiry, duplicate/reordered packets, same update sequence in BOTH channels, increasing reply sequence but identical stale input sample, old run/layer, malformed ages/sequence, and ordinary realtime compatibility.

Compile and run tests first. Then ask the user to perform a short real run: approach edge -> geometric relay appears if clearance crosses zero -> recover -> relay clears; restart -> no old warning. A separate disconnect run is only needed if current end-to-end expiry behavior has changed.

Report changed Unity files, test counts and real-runtime evidence separately. Synthetic tests are not real UDP acceptance. Do not modify or deploy the two-low exit experiment: it failed the backend's offline screening and is NOT enabled.
