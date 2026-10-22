# Warning-response analysis

Input: telemetry_logs\TEST931

Attention and strong warning channels are analyzed independently. Attention
uses attention_state or ATTENTION/yellow prediction states. Strong uses
edge_warning_state or EDGE WARNING/contact/critical prediction states. When
warning state fields are absent, a threshold crossing is reported as
geometry_derived and flagged for review.

Rows at or after the first fall event are excluded from causal warnings.
Relative fall_event_time values are anchored to run_start_backend_timestamp
when available. lead_time_s is event minus warning start. reaction_time_s is
the first two-sample radial velocity response (threshold -0.1) minus
warning start. safe_return_time is the first SAFE row after warning clear and
is confirmed after 0.3 seconds; recovery_time_s is the delay
from warning end to that first SAFE row.

Outcomes are recovered, fall_after_warning, no_response, false_alarm, and
ambiguous. outcome_subtype distinguishes near_miss_recovered from safe_normal,
so a recovered warning is not automatically a false alarm. Missing or
ambiguous values are listed in review_flags and review_required.

Outputs: warning_response_episodes.csv, warning_response_sessions.csv,
warning_response_conditions.csv, metrics.json, and this README.md.

Sessions: 53; episodes: 525;
review episodes: 28.
