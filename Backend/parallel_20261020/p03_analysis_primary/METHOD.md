# P03 post-fix nine-session analysis: fixed scope

Only the nine IDs in `p03_postfix_review_primary/CONDITION_RECEIPT.json` are included. The earlier six no-banner sessions remain a separate failed experimental-exposure condition. No training or parameter selection is authorized.

1. Count Unity rows only, with exact run identity, source timestamp and sequence; hash raw inputs before/after.
2. Outcomes are recorded session outcomes, not inferred from warning state. Six completed sessions and three edge-exit sessions are summarized separately.
3. Client ACTIVE starts an episode; repeated ACTIVE refreshes do not start another. REVOKED closes it. Only two finite endpoints in the same local monotonic clock yield accepted-state duration. Red logs without this clock have unknown duration, not zero exposure.
4. For source timing, an experimental ACTIVE log must join an exact run + input sequence to a unique Unity row and match its layer/platform (and version where supplied). Only the final fall's context is eligible; an old-layer warning never counts toward the new-layer fall. The last eligible onset is descriptive, not automatically a qualifying prediction within the deployed 0.75s horizon.
5. `fall_event_backend_timestamp` and telemetry `source_timestamp` both come from Unity DateTimeOffset.UtcNow (UDPManager.GetBackendUnixTimestamp and SendTelemetry). Their difference is a source-observation-to-fall-commit interval, NOT client presentation lead. No median Unity-time/epoch offset is fitted. Orange logs have no input sequence/time, so orange source lead remains unavailable.
6. Ordinary telemetry q = directional_edge_distance - 2*ball_radius crossings are descriptive brackets only. They do NOT replace the registered full-query geometric anchor protocol, the old event denominator, or old model metrics.
7. Report activation incidence, accepted-state burden, missing anchors/clocks and coverage limitations separately. No causal intervention benefit, cross-participant generalization, formal F1, or original-protocol recall is claimed.

This method is written before computing the new source-lead table; no thresholds are searched.
