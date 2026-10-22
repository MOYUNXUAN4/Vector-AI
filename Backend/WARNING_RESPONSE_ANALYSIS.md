# Warning response analysis

Run analyze_warning_response.py with a raw.csv file, a session directory, or
a dataset root:

    python analyze_warning_response.py --input telemetry_logs/TEST931 --out-dir analysis_warning_response

Optional manual annotations use a CSV with session_id, layer, condition,
intended_action, and manual_outcome columns. The command accepts
--manual-csv, --min-inward-speed (default -0.1), and --min-safe-duration
(default 0.3).

The analyzer emits warning_response_episodes.csv, one row per attention or
strong episode; warning_response_sessions.csv, one row per session ID;
warning_response_conditions.csv, condition/channel aggregates; metrics.json;
and a run-specific README.md. Attention is the blue ATTENTION state and strong
is the yellow EDGE WARNING state. Explicit warning_type, warning_active,
visible_warning_state, response_condition, experiment_id, trial_id, layer_id,
and attention episode transition fields are accepted when present.

Rows at or after the first fall event are excluded from causal pre-event
episodes. Outcomes are recovered, fall_after_warning, no_response, false_alarm,
or ambiguous. outcome_subtype distinguishes near_miss_recovered from
safe_normal, and review_flags identifies missing or contradictory telemetry.
