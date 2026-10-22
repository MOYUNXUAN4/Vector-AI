"""Read-only post-q<=0 geometric handoff audit for the frozen 31-session replay.

This is a source-epoch join, not a UDP or displayed-warning reconstruction.
The Unity CSV has no packet query/receive timing, so runtime freshness cannot be
certified here. No model fitting or threshold selection is performed.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REPLAY = ROOT / 'parallel_20261020' / 'dev_withdrawal_primary'
MANIFEST = ROOT / 'parallel_20261014' / 'command055_fit_luna' / 'session_manifest.csv'
RAW_ROOT = ROOT / 'telemetry_logs' / 'INPUT055_CHECK'
CAP_SECONDS = 2.0
MAX_DT = 0.1


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def num(row: dict, key: str):
    try:
        x = float(row.get(key, ''))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def truth(row: dict, key: str) -> bool | None:
    value = str(row.get(key, '')).strip().lower()
    if value in ('true', '1'):
        return True
    if value in ('false', '0'):
        return False
    return None


def raw_context(r: dict) -> tuple:
    return (r.get('run_id', ''), r.get('platform_level', ''),
            r.get('geometry_platform_instance_id', ''), r.get('geometry_version_id', ''))


def valid_geometry(r: dict) -> bool:
    d, radius = num(r, 'directional_edge_distance'), num(r, 'ball_radius')
    return (truth(r, 'geometry_query_valid') is True and
            truth(r, 'geometry_ownership_valid') is True and
            truth(r, 'directional_edge_valid') is True and d is not None and
            radius is not None and radius > 0 and bool(r.get('geometry_version_id')) and
            num(r, 'geometry_platform_instance_id') is not None)


def qclear(r: dict):
    if not valid_geometry(r):
        return None, None
    d, radius = num(r, 'directional_edge_distance'), num(r, 'ball_radius')
    return d - 2 * radius, d - radius


def identity_key(r: dict) -> tuple:
    return (r['session_id'], r['run_id'], r['source_sequence'], r['csv_row'],
            r['layer'], r['platform_id'], r['geometry_version_id'])


def raw_match_key(session: str, replay: dict) -> tuple:
    return (session, replay['run_id'], replay['source_sequence'], replay['csv_row'],
            replay['layer'], replay['platform_id'], replay['geometry_version_id'])


def classify_orange(r: dict) -> str:
    # Frozen 24-feature replay availability is based on causal model inputs and c>0.
    if r.get('available', '').lower() != 'true':
        return 'invalid_or_ineligible'
    return 'orange_active' if r.get('active', '').lower() == 'true' else 'eligible_but_inactive'


def write_csv(path: Path, records: list[dict]) -> None:
    fields = list(dict.fromkeys(k for row in records for k in row))
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(records)


def _find_exact_replay(r, index):
    k = raw_match_key(r['session_id'], r)
    found = index.get(k, [])
    if len(found) != 1:
        raise AssertionError(f'exact replay join cardinality {len(found)} for {k}')
    return found[0]


def audit_rows(exit_rows, raw_sessions, orange_index):
    exit_details, segment_rows, timeline_rows = [], [], []
    summary = Counter()
    context_spans = []
    for ex_id, exit_row in enumerate(exit_rows, 1):
        session = exit_row['session_id']
        raw_all = raw_sessions[session]
        raw_pos = int(exit_row['csv_row']) - 2
        if raw_pos < 0 or raw_pos >= len(raw_all):
            raise AssertionError(('raw csv_row offset out of bounds', exit_row))
        r0 = raw_all[raw_pos]
        if r0.get('source', '').lower() != 'unity':
            raise AssertionError(('exit raw row is not Unity', exit_row, r0.get('source')))
        if (r0['run_id'] != exit_row['run_id'] or r0['sequence'] != exit_row['source_sequence'] or
                r0['geometry_version_id'] != exit_row['geometry_version_id'] or
                str(r0['platform_level']) != str(exit_row['layer']) or
                str(r0['geometry_platform_instance_id']) != str(exit_row['platform_id'])):
            raise AssertionError(('exit raw alignment mismatch', exit_row))
        orange = _find_exact_replay(exit_row, orange_index)
        q0, c0 = qclear(r0)
        assert q0 is not None and q0 <= 0, (ex_id, q0)
        orange_class = classify_orange(orange)
        raw_valid = valid_geometry(r0)
        red_numeric = c0 is not None and c0 <= 0
        flags = {k: truth(r0, k) for k in ('geometry_query_valid', 'geometry_ownership_valid', 'directional_edge_valid')}
        detail = {
            'exit_id': ex_id, 'session_id': session, 'run_id': exit_row['run_id'],
            'source_sequence': exit_row['source_sequence'], 'csv_row': exit_row['csv_row'],
            'timestamp': exit_row['timestamp'], 'layer': exit_row['layer'],
            'platform_id': exit_row['platform_id'], 'geometry_version_id': exit_row['geometry_version_id'],
            'q': q0, 'clearance_c': c0, 'red_numeric_c_le_0': red_numeric,
            'raw_geometry_identity_valid_flags_all_true': raw_valid,
            **flags, 'orange_class_at_exact_decision': orange_class,
            'orange_available': orange.get('available'), 'orange_active': orange.get('active'),
            'orange_probability': orange.get('probability'),
            'raw_warning_source': r0.get('warning_source'), 'raw_warning_type': r0.get('warning_type'),
            'raw_warning_active': r0.get('warning_active'), 'raw_visible_warning_state': r0.get('visible_warning_state'),
            'freshness_certified': False,
        }

        # Continue over adjacent raw Unity rows only within the same captured context.
        # Raw packet sequence and backend time are used only as ordering/gap checks.
        stop_reason, endpos = 'endfile', raw_pos
        prev = r0
        first_c_nonpos = raw_pos if c0 is not None and c0 <= 0 else None
        q_recovery_pos = None
        invalid_pos = None
        for j in range(raw_pos + 1, len(raw_all)):
            r = raw_all[j]
            if r.get('source', '').lower() != 'unity':
                continue
            if raw_context(r) != raw_context(r0):
                stop_reason, endpos = 'contextchange', j
                break
            t, pt = num(r, 'source_timestamp'), num(prev, 'source_timestamp')
            seq, pseq = num(r, 'sequence'), num(prev, 'sequence')
            if seq is None or pseq is None or seq <= pseq:
                stop_reason, endpos = 'nonincreasing_sequence', j
                break
            if seq != pseq + 1:
                stop_reason, endpos = 'sequence_gap', j
                break
            if t is None or pt is None or t <= pt:
                stop_reason, endpos = 'nonincreasing_time', j
                break
            if t - pt > MAX_DT + 1e-9:
                stop_reason, endpos = 'source_dt_over_0.1', j
                break
            elapsed = t - num(r0, 'source_timestamp')
            if elapsed > CAP_SECONDS:
                stop_reason, endpos = 'cap_2s', j
                break
            endpos = j
            q, c = qclear(r)
            if q is None:
                invalid_pos, stop_reason = j, 'invalid_geometry_evidence'
                break
            if first_c_nonpos is None and c is not None and c <= 0:
                first_c_nonpos = j
            if q > 0:
                q_recovery_pos, stop_reason = j, 'q_domain_recovered'
                break
            prev = r
        else:
            stop_reason = 'endfile'
        endpos = min(endpos, len(raw_all) - 1)
        endrow = raw_all[endpos]
        elapsed_end = num(endrow, 'source_timestamp') - num(r0, 'source_timestamp')
        detail.update({'follow_stop_reason': stop_reason, 'follow_end_sequence': endrow.get('sequence'),
                       'follow_end_elapsed_seconds': elapsed_end,
                       'first_clearance_c_le_0_sequence': raw_all[first_c_nonpos].get('sequence') if first_c_nonpos is not None else '',
                       'first_q_positive_recovery_sequence': raw_all[q_recovery_pos].get('sequence') if q_recovery_pos is not None else '',
                       'invalid_geometry_sequence': raw_all[invalid_pos].get('sequence') if invalid_pos is not None else ''})
        exit_details.append(detail)
        summary['exit_count'] += 1
        summary[f'orange_{orange_class}'] += 1
        summary['red_numeric_c_le_0' if red_numeric else 'red_numeric_c_positive'] += 1
        summary['raw_identity_flags_all_true' if raw_valid else 'raw_identity_flags_not_all_true'] += 1
        summary[f'follow_stop_{stop_reason}'] += 1

        # Timeline contains observed source rows only; no interpolation and no assertion
        # that a warning was shown between decision points.
        for j in range(raw_pos, endpos + 1):
            r = raw_all[j]
            if r.get('source', '').lower() != 'unity':
                continue
            q, c = qclear(r)
            timeline_rows.append({
                'exit_id': ex_id, 'session_id': session, 'run_id': r.get('run_id'),
                'source_sequence': r.get('sequence'), 'source_timestamp': r.get('source_timestamp'),
                'elapsed_from_q_exit_s': (num(r, 'source_timestamp') - num(r0, 'source_timestamp')),
                'layer': r.get('platform_level'), 'platform_id': r.get('geometry_platform_instance_id'),
                'geometry_version_id': r.get('geometry_version_id'), 'q': q, 'clearance_c': c,
                'raw_geometry_identity_valid_flags_all_true': valid_geometry(r),
                'geometry_query_valid': r.get('geometry_query_valid'),
                'geometry_ownership_valid': r.get('geometry_ownership_valid'),
                'directional_edge_valid': r.get('directional_edge_valid'),
                'raw_warning_source': r.get('warning_source'), 'raw_warning_type': r.get('warning_type'),
                'raw_warning_active': r.get('warning_active'), 'raw_visible_warning_state': r.get('visible_warning_state'),
                'warning_freshness_certified': False,
            })
        # Estimate interval for q crossing bracket and c crossing bracket only when both
        # are observed in this same context and before a censoring/gap stop.
        if first_c_nonpos is not None and first_c_nonpos <= endpos:
            q_left = raw_pos - 1
            while q_left >= 0:
                rr = raw_all[q_left]
                if rr.get('source', '').lower() == 'unity' and raw_context(rr) == raw_context(r0):
                    qprev, _ = qclear(rr)
                    if qprev is not None:
                        break
                q_left -= 1
            c_left = first_c_nonpos - 1
            while c_left >= raw_pos:
                rr = raw_all[c_left]
                if rr.get('source', '').lower() == 'unity' and raw_context(rr) == raw_context(r0):
                    _, cprev = qclear(rr)
                    if cprev is not None:
                        break
                c_left -= 1
            if q_left >= 0 and c_left >= raw_pos:
                q_before, _ = qclear(raw_all[q_left])
                _, c_before = qclear(raw_all[c_left])
                if q_before is not None and q_before > 0 and c_before is not None and c_before > 0:
                    q_lo = num(raw_all[q_left], 'source_timestamp')
                    q_hi = num(r0, 'source_timestamp')
                    c_lo = num(raw_all[c_left], 'source_timestamp')
                    c_hi = num(raw_all[first_c_nonpos], 'source_timestamp')
                    lo = max(0.0, c_lo - q_hi)
                    hi = max(0.0, c_hi - q_lo)
                    span = {'exit_id': ex_id, 'session_id': session, 'run_id': exit_row['run_id'],
                            'context': '|'.join(map(str, raw_context(r0))),
                            'q_positive_bracket_left_sequence': raw_all[q_left].get('sequence'),
                            'q_nonpositive_bracket_right_sequence': r0.get('sequence'),
                            'c_positive_bracket_left_sequence': raw_all[c_left].get('sequence'),
                            'c_nonpositive_bracket_right_sequence': raw_all[first_c_nonpos].get('sequence'),
                            'conservative_same_context_span_lower_s': lo,
                            'conservative_same_context_span_upper_s': hi,
                            'freshness_or_display_gap_claim': False}
                    context_spans.append(span)

    return exit_details, timeline_rows, context_spans, dict(summary)


def selftest():
    q, c = qclear({'geometry_query_valid': 'True', 'geometry_ownership_valid': 'True',
                   'directional_edge_valid': 'True', 'directional_edge_distance': '0.8',
                   'ball_radius': '0.5', 'geometry_version_id': 'v',
                   'geometry_platform_instance_id': '2'})
    assert math.isclose(q, -0.2) and math.isclose(c, 0.3)
    assert qclear({'geometry_query_valid': 'False', 'geometry_ownership_valid': 'True',
                   'directional_edge_valid': 'True', 'directional_edge_distance': '0.8',
                   'ball_radius': '0.5', 'geometry_version_id': 'v',
                   'geometry_platform_instance_id': '2'}) == (None, None)
    assert classify_orange({'available': 'False', 'active': 'False'}) == 'invalid_or_ineligible'
    assert classify_orange({'available': 'True', 'active': 'False'}) == 'eligible_but_inactive'
    assert classify_orange({'available': 'True', 'active': 'True'}) == 'orange_active'


def main():
    selftest()
    manifest = rows(MANIFEST)
    raw_paths = {s['session_id']: RAW_ROOT / s['session_id'] / 'raw.csv' for s in manifest}
    tracked = [REPLAY / 'tte_trace.csv', REPLAY / 'locked24_trace.csv',
               REPLAY / 'tte_withdrawals.csv', REPLAY / 'independent_results.json', MANIFEST]
    tracked.extend(raw_paths.values())
    hashes_before = {str(p): sha(p) for p in tracked}
    for s in manifest:
        assert hashes_before[str(raw_paths[s['session_id']])] == s['raw_sha256'], s['session_id']
    tte_trace = rows(REPLAY / 'tte_trace.csv')
    orange_trace = rows(REPLAY / 'locked24_trace.csv')
    exits = [r for r in rows(REPLAY / 'tte_withdrawals.csv') if r.get('mechanism') == 'q_nonpositive_domain_exit']
    assert len(manifest) == 31 and len(exits) == 49
    orange_index = defaultdict(list)
    for r in orange_trace:
        orange_index[raw_match_key(r['session_id'], r)].append(r)
    # Ensure this audit only receives the requested q exits and every frozen orange decision is unique.
    assert len(tte_trace) == len(orange_trace) == 7553
    assert all(len(v) == 1 for v in orange_index.values())
    raw_sessions = {session: rows(path) for session, path in raw_paths.items()}
    details, timelines, spans, counts = audit_rows(exits, raw_sessions, orange_index)

    # Sampled decision noncoverage: q<=0, valid positive c, orange and purple both off.
    tte_by_key = {raw_match_key(r['session_id'], r): r for r in tte_trace}
    orange_by_key = {raw_match_key(r['session_id'], r): r for r in orange_trace}
    noncoverage = []
    for tr in tte_trace:
        q = num(tr, 'q')
        if q is None or q > 0 or tr.get('active', '').lower() != 'false':
            continue
        c = num(tr, 'clearance')
        if c is None or c <= 0:
            continue
        orange = orange_by_key[raw_match_key(tr['session_id'], tr)]
        if orange.get('available', '').lower() == 'true' and orange.get('active', '').lower() == 'false':
            noncoverage.append({'session_id': tr['session_id'], 'run_id': tr['run_id'],
                                'source_sequence': tr['source_sequence'], 'csv_row': tr['csv_row'],
                                'layer': tr['layer'], 'platform_id': tr['platform_id'],
                                'geometry_version_id': tr['geometry_version_id'],
                                'timestamp': tr['timestamp'], 'q': q, 'clearance_c': c,
                                'tte_active': tr['active'], 'orange_available': orange['available'],
                                'orange_active': orange['active'], 'purple_orange_both_off': True})
    # ZOH proxy only across adjacent exact saved decisions; it does not establish displayed duration.
    noncoverage_keys = {raw_match_key(r['session_id'], r) for r in noncoverage}
    proxy_seconds = 0.0
    proxy_intervals = 0
    by_context = defaultdict(list)
    for tr in tte_trace:
        k = raw_match_key(tr['session_id'], tr)
        if k in noncoverage_keys:
            by_context[(tr['session_id'], tr['run_id'], tr['segment_id'], tr['layer'], tr['platform_id'], tr['geometry_version_id'])].append(tr)
    for group in by_context.values():
        group.sort(key=lambda r: (num(r, 'timestamp') or 0, int(r['source_sequence'])))
        for a, b in zip(group, group[1:]):
            dt = num(b, 'timestamp') - num(a, 'timestamp')
            if 0 < dt <= MAX_DT + 1e-9:
                proxy_seconds += dt
                proxy_intervals += 1

    source_hashes_after = {str(p): sha(p) for p in tracked}
    assert hashes_before == source_hashes_after, 'source mutation detected'
    raw_verified = sum(1 for s in manifest if hashes_before[str(raw_paths[s['session_id']])] == s['raw_sha256'])
    write_csv(OUT / 'postq_exit_audit.csv', details)
    write_csv(OUT / 'postq_raw_timeline.csv', timelines)
    write_csv(OUT / 'postq_samecontext_spans.csv', spans)
    write_csv(OUT / 'sampled_both_off_q_nonpositive_c_positive.csv', noncoverage)
    summary = {
        'scope': 'Original-development 31-session source-level q<=0 handoff audit',
        'sessions': len(manifest), 'q_nonpositive_domain_exits': len(exits),
        'raw_files_sha256_verified': raw_verified, 'raw_files_total': len(manifest),
        'exit_categories': counts,
        'samecontext_span_rows_with_observed_brackets': len(spans),
        'samecontext_span_lower_seconds_sum': sum(x['conservative_same_context_span_lower_s'] for x in spans),
        'samecontext_span_upper_seconds_sum': sum(x['conservative_same_context_span_upper_s'] for x in spans),
        'sampled_decisions_q_le_0_c_positive_both_purple_and_orange_off': len(noncoverage),
        'zoh_proxy_seconds_adjacent_sampled_both_off_decisions_dt_le_0.1': proxy_seconds,
        'zoh_proxy_adjacent_intervals': proxy_intervals,
        'freshness_certified_runtime_warning_count': None,
        'source_hashes_before': hashes_before, 'source_hashes_after': source_hashes_after,
        'sources_unchanged': hashes_before == source_hashes_after,
        'constraints': [
            'Raw telemetry has no Unity packet query/receive timestamp pair; no age was fabricated.',
            'Numeric c<=0 and logged query/ownership/directional validity are reported separately from a fully valid runtime warning.',
            'Orange states are joined only at exact saved decision keys; no warning state was interpolated between decisions.',
            'Raw warning/attention fields are descriptive only and were not substituted for orange or purple.',
            'q<=0 denotes the TTE model proximity-domain boundary, not support loss or a fall label.',
            'Censored, invalid, missing, and numeric-zero evidence remain distinct.'
        ]
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    report = f"""# Post-q handoff audit\n\n## Scope and assumptions\n\nThis read-only audit uses the frozen 31-session replay and original `INPUT055_CHECK` Unity telemetry. It reads no P01/P02 or holdout sources and does not train or select a threshold. The TTE withdrawal set contains {len(exits)} q<=0 domain exits. Each exit is joined to the saved orange replay at the exact session/run/source-sequence/physical-row/layer/platform/version key, then checked against the raw CSV row.\n\nThe CSV does not carry the Unity geometry query timestamp plus backend receive timestamp needed by `GeometryDanger` to establish freshness. Therefore `clearance <= 0` is reported as a numeric red predicate, with logged geometry identity/query/ownership validity flags shown separately. It is not called a confirmed runtime warning. The audit does not fabricate packet age. It also does not interpolate orange between sampled decisions.\n\n`q = d - 2r` is the TTE model's positive-domain boundary. It is not a support-loss or fall label. Censored, invalid, missing, and numeric-zero evidence remain distinct. Raw warning and attention columns are reported only descriptively.\n\n## Counts\n\n- Exact q<=0 exits: {len(exits)}\n- Raw files SHA-256 checked against the exact 31-session manifest: {raw_verified}/{len(manifest)}\n- Orange decision classes at exits: {json.dumps({k:v for k,v in counts.items() if k.startswith('orange_')}, sort_keys=True)}\n- Numeric clearance: {counts.get('red_numeric_c_le_0',0)} c<=0; {counts.get('red_numeric_c_positive',0)} c>0\n- Raw geometry identity/query/ownership validity flags all true at exit: {counts.get('raw_identity_flags_all_true',0)}; flags not all true: {counts.get('raw_identity_flags_not_all_true',0)}\n- Same-context q-entry/crossing brackets with observed c<=0: {len(spans)}; conservative interval totals are in `postq_samecontext_spans.csv` and are source-observation bounds, not certified UI/display gaps.\n- Sampled q<=0, c>0 decisions with TTE inactive and orange eligible-but-inactive: {len(noncoverage)}\n- Adjacent-decision ZOH proxy across those samples: {proxy_seconds:.6f}s over {proxy_intervals} intervals <= 0.1s. This is not factual displayed-warning duration.\n\n## Follow-up and censoring\n\nEach exit's same-context raw sequence was followed until first q>0 recovery, context change, source sequence/time discontinuity, invalid geometry flags/data, end of available raw rows, or the declared 2s observation cap. Stop categories and observed rows are in `postq_exit_audit.csv` and `postq_raw_timeline.csv`. Raw sample times only bound observations; they do not reconstruct UDP receive timing or UI state.\n\nAll source hashes before and after the audit match. Details are in `summary.json`.\n"""
    (OUT / 'REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps({'output_dir': str(OUT), 'summary': {k:v for k,v in summary.items() if k not in ('source_hashes_before','source_hashes_after')}}))


if __name__ == '__main__':
    main()
