# P02 warning-effects audit, 2026-10-20

## Main result

The later three P02 runs show real model/proximity client acceptance and withdrawal, not just backend shadow activity. The fall run's final proximity warning begins on an input 0.430–0.445s before the observed q=0 approach boundary, but 1.312s before the terminal fall. Those are different endpoints and must not be presented as the same lead time. Orange begins 0.114006s after purple in the client's monotonic clock. Exact screen-visible lead and guaranteed >=0.4s coverage are unavailable from this log set; do not claim performance acceptance.

The final purple withdrawal is traceable to outside_proximity_domain, not a source stream gap or observed recovery. Red geometry acceptance follows later in log order. The model withdrawal only says backend_unknown, so its precise backend reason is not established by this audit. The next research question is early discrimination and domain handoff, not holding an old score on screen longer.

No training, selection, threshold/model/UI/physics changes, or new data collection occurred. This remains existing 24-feature-model/separate-proximity channel analysis, not evidence that a fused predictor has been deployed or accepted.

## Configuration and population

There are four sessions. User explicitly reported first-run sensitivity was not 0.55 and manually adjusted it afterward. Exact numeric runtime values are absent from CSV. First run stays separate; later runs are described as user-adjusted rather than independently verified exact 0.55. Do not pool the first run into a fixed-sensitivity performance cohort, infer history from current preferences, or discard it from the evidence inventory.

| Run/session start | Outcome | Orange episodes | Orange proxy duration | Purple episodes | Purple proxy duration |
|---|---|---:|---:|---:|---:|
| 10:19:29, sensitivity mismatch (separate) | completed | 3 | 0.221s | 23 | 7.075s |
| 10:20:58, user-adjusted | completed | 1 | 0.117s | 2 | 0.494s |
| 10:22:22, user-adjusted | edge_exit | 7 | 2.114s | 10 | 5.198s |
| 10:23:49, user-adjusted | completed | 2 | 0.584s | 6 | 2.284s |

Durations are logged receive-to-clear proxies, not render-verified screen exposure. ACTIVE logs use packet-receive monotonic time; REVOKED logs use clear-call monotonic time. A new accepted prediction while already ACTIVE renews state, not another episode or proof of flicker. No arbitrary merging of separate episodes was used. A total of 144 state records yields 55 channel episodes (13 model, 41 proximity, 1 geometry), no orphan revocations or censored episodes. Geometry lines lack local_monotonic_s; geometry duration remains unknown, not zero. Counts describe accepted state, not eye tracking, screen visibility verification, or successful interventions.

## Final fall approach: anchors and ordering

Run 9cde97e123d240268311b479d55a83eb, layer 2, platform -5378, ordinary geometry version -5378-g1.

Define q=directional_edge_distance-2*ball_radius. This is the proximity rule's existing approach-domain boundary, not a newly approved final-fall training label. The packet-source crossing bracket is not a certified continuous collider-capture interval.

| Evidence | Value |
|---|---|
| Last accepted purple onset input | sequence 4962, epoch 1792463025.529 |
| Geometry/velocity at onset | q=1.085684, outward radial velocity=2.447740 |
| Last positive q packet | sequence 4988, epoch 1792463025.959, q=0.023845 |
| First nonpositive q packet | sequence 4989, epoch 1792463025.974, q=-0.012937 |
| Input-onset to q-crossing bracket | 0.430–0.445s |
| Explicit edge-contact epoch | 1792463026.179; input-onset lead 0.650s |
| Explicit terminal-fall epoch | 1792463026.841; input-onset lead 1.312s |
| Client purple ACTIVE -> REVOKED | monotonic 281.132291 -> 281.564100; proxy 0.431809s |
| Client orange ACTIVE -> REVOKED | monotonic 281.246297 -> 281.769066; proxy 0.522769s |
| Orange onset after purple onset | 0.114006s, same client clock, no conversion |
| Final purple backend withdrawal | input 4989; outside_proximity_domain; q<0; outward velocity 2.454648; joint_recovery=false; recovery_cancelled=false |
| Final orange withdrawal | backend_unknown; detailed backend invalidity reason not present in client log |
| Red geometry acceptance | Player.log snapshot line 1987, input 5001, clearance_nonpositive |
| Red geometry revocation | snapshot line 2013, input 5040, run_ended:edge_exit |

All purple input-onset matches are exact across run, input_sequence, source timestamp, platform and ordinary geometry version in CSV and shadow logs: 41/41 overall, 18/18 in the later three runs. Adjacent q-crossing samples are valid, owned, same-context, consecutive sequence with 15ms source interval. No interpolation or old-cache fill was used. Diagnostic fingerprint strings are not compared to ordinary geometry version as if identical.

The last accepted purple onset has a later timestamp than earlier layer-1 warnings, so an arbitrary early warning elsewhere in the run is not credited to this final approach. Do not use the 1.312s terminal lead to claim 1.312s of warning before approach-boundary entry. Also do not subtract 0.114006s from source lead and call it a measured orange display lead: client/epoch paired-clock evidence and packet-to-render latency are not logged. Exact screen onset requires a different evidence chain; it is N/A here, not zero or a miss.

The red event follows the orange withdrawal in actual Player.log order. There is no red monotonic timestamp, so neither a seamless handoff nor a quantified blank-display interval is established. No timeout/invalid prediction is held artificially to manufacture continuity.

## Completion-group burden versus observed recovery

Among the two later completed sessions, both channels activate at least once in both sessions. Under a final-fall prediction task those completed-session alarms cannot be removed from the false-positive population just because a player might have recovered. Under a descriptive risk task the same events may have useful context, but no causal benefit is demonstrated with prompts enabled throughout.

- Orange: 3 episodes total, receive-to-clear proxy duration 0.700365s; average 0.350183s per completed session. All three withdraw as backend_safe. All three are shorter than 0.5s (descriptive count only).
- Purple: 8 episodes total, proxy duration 2.777501s; average 1.388751s per completed session. Six episodes are shorter than 0.5s. Client revoke reasons: 6 backend_clear, 2 backend_unknown.
- Exact source shadow matching shows the two unknowns are outside_proximity_domain, not verified recovery.
- Of six available->inactive source transitions, one already has inward radial velocity; five still have positive outward velocity, reduced from their onset values. All six still have positive q. `joint_recovery` and `recovery_cancelled` are false in these first inactive records. Those flags do not establish the absence of later recovery.

Thus clearance/time-to-edge improvement or a raw threshold dropping out is not synonymous with completed inward recovery. Continued outward motion likewise does not alone prove withdrawal was incorrect: with reduced speed, q/outward_velocity can move beyond the rule's horizon. Review the source traces as trajectories, not automatic correct/incorrect labels. The current evidence does not justify adding persistence or lowering a threshold.

These two completed sessions are NOT independently annotated recovery clips, so the quantities above are completed-session burden, not a measured recovery-only false-positive rate. With one fall and two later completions, no population recall/F1 claim, participant-generalization claim, or guaranteed >=0.4s coverage claim is made. Sensitivity provenance and channel/clock limits stay visible.

## Next bounded action

Preserve P02 as observation data, with first-run configuration mismatch separate. Keep the deployed model/rule/config unchanged. Next offline replay should inspect the source scores/velocity and control behavior around these specific clear/unknown transitions using existing compatible development data. Distinguish: entering an unsupported danger region, slowing while still outward, genuine inward recovery, and invalid evidence. Do not use P02 to select a new threshold or silently turn it into a training/calibration set. No immediate new board collection is required to finish this descriptive audit.

## Reproducibility and sources

Protocol/definitions: METHOD.md. Source-side script: analyze_source_anchors.py; output source_anchor_results.json. Client extractor, self-test, immutable Player.log snapshot, per-record physical line evidence, episodes and summaries are under client_luna/. Source logs were not edited.

Player.log snapshot SHA256 ff14afc5d5f9822cc6df5a0bd94d5ff8e59aedf8d3999123d8e3e3a37dd1b9c6. Raw CSV hashes and exact run/context/line keys are retained in source_anchor_results.json; full shadow SHA256 also retained there. Player.log path is preserved via snapshot because the live log can be overwritten at the next launch. The local inspector's existing p02_retest/REPORT.md separately covers telemetry continuity and terminal persistence. Mechanical client extraction by Luna, independently reviewed against receiver logging semantics and source-side anchor matching by the primary agent.
