# Post-q handoff audit

## Scope and assumptions

This read-only audit uses the frozen 31-session replay and original `INPUT055_CHECK` Unity telemetry. It reads no P01/P02 or holdout sources and does not train or select a threshold. The TTE withdrawal set contains 49 q<=0 domain exits. Each exit is joined to the saved orange replay at the exact session/run/source-sequence/physical-row/layer/platform/version key, then checked against the raw CSV row.

The CSV does not carry the Unity geometry query timestamp plus backend receive timestamp needed by `GeometryDanger` to establish freshness. Therefore `clearance <= 0` is reported as a numeric red predicate, with logged geometry identity/query/ownership validity flags shown separately. It is not called a confirmed runtime warning. The audit does not fabricate packet age. It also does not interpolate orange between sampled decisions.

`q = d - 2r` is the TTE model's positive-domain boundary. It is not a support-loss or fall label. Censored, invalid, missing, and numeric-zero evidence remain distinct. Raw warning and attention columns are reported only descriptively.

## Counts

- Exact q<=0 exits: 49
- Raw files SHA-256 checked against the exact 31-session manifest: 31/31
- Orange decision classes at exits: {"orange_eligible_but_inactive": 12, "orange_orange_active": 37}
- Numeric clearance: 0 c<=0; 49 c>0
- Raw geometry identity/query/ownership validity flags all true at exit: 49; flags not all true: 0
- Same-context q-entry/crossing brackets with observed c<=0: 11; conservative interval totals are in `postq_samecontext_spans.csv` and are source-observation bounds, not certified UI/display gaps.
- Sampled q<=0, c>0 decisions with TTE inactive and orange eligible-but-inactive: 166
- Adjacent-decision ZOH proxy across those samples: 7.594001s over 124 intervals <= 0.1s. This is not factual displayed-warning duration.

## Follow-up and censoring

Each exit's same-context raw sequence was followed until first q>0 recovery, context change, source sequence/time discontinuity, invalid geometry flags/data, end of available raw rows, or the declared 2s observation cap. Stop categories and observed rows are in `postq_exit_audit.csv` and `postq_raw_timeline.csv`. Raw sample times only bound observations; they do not reconstruct UDP receive timing or UI state.

All source hashes before and after the audit match. Details are in `summary.json`.
