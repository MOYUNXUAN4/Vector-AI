"""Describe seven preselected handoff cases without changing rules or labels."""
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
HANDOFF = ROOT / 'parallel_20261020/postq_handoff_primary'
PREVIOUS = ROOT / 'parallel_20261020/dev_withdrawal_primary'
MANIFEST = ROOT / 'parallel_20261014/command055_fit_luna/session_manifest.csv'


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yes(v):
    return str(v).lower() in ('true', '1')


def numeric(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def classify(points):
    """Labels describe observed policy sequences, not final-fall correctness."""
    if not points:
        return 'insufficient_decisions'
    active = [yes(r['active']) for r in points]
    reasons = [r['policy_reason'] for r in points]
    if any(active) and any(active[i-1] and not active[i] and reasons[i] == 'raw_off'
                           for i in range(1, len(points))):
        return 'score_drop_after_active'
    if not any(active):
        return 'inactive_with_late_confirmation_pending' if 'raw_on' in reasons else 'inactive_low_score'
    if not active[0] and reasons[0] == 'raw_on' and any(active[1:]):
        return 'initial_confirmation_then_active'
    return 'other_or_unresolved'


def dump_csv(path, records):
    fields = list(dict.fromkeys(k for r in records for k in r))
    with path.open('w', encoding='utf-8', newline='') as stream:
        w = csv.DictWriter(stream, fields)
        w.writeheader()
        w.writerows(records)


def main():
    sources = [HANDOFF / 'postq_segment_decision_coverage.csv', HANDOFF / 'raw_source_brackets.csv',
               PREVIOUS / 'locked24_trace.csv', PREVIOUS / 'tte_trace.csv', MANIFEST]
    manifest = {r['session_id']: r for r in rows(MANIFEST)}
    picks = [r for r in rows(sources[0]) if r['stop_reason'] == 'first_c_nonpositive' and yes(r['any_inactive_sample'])]
    assert len(picks) == 7 and len({r['session_id'] for r in picks}) == 7
    raw_paths = {r['session_id']: ROOT / 'telemetry_logs/INPUT055_CHECK' / r['session_id'] / 'raw.csv' for r in picks}
    for sid, path in raw_paths.items():
        assert sha(path) == manifest[sid]['raw_sha256']
        sources.append(path)
    before = {str(p): sha(p) for p in sources}
    spans = {(r['session_id'], r['exit_source_sequence']): r for r in rows(sources[1])}
    orange = rows(sources[2])
    case_rows, raw_timeline, decision_timeline = [], [], []
    for case_no, pick in enumerate(picks, 1):
        sid = pick['session_id']
        span = spans[sid, pick['exit_source_sequence']]
        lo, hi = int(span['q_high_line']), int(span['c_high_line'])
        raw = [(line, r) for line, r in enumerate(rows(raw_paths[sid]), 2)
               if lo <= line <= hi and r['source'].lower() == 'unity']
        assert len(raw) >= 2
        context = tuple(raw[0][1][k] for k in ('run_id', 'platform_level', 'geometry_platform_instance_id', 'geometry_version_id'))
        assert all(tuple(r[k] for k in ('run_id', 'platform_level', 'geometry_platform_instance_id', 'geometry_version_id')) == context for _, r in raw)
        assert all(int(b['sequence']) == int(a['sequence']) + 1 and 0 < float(b['source_timestamp']) - float(a['source_timestamp']) <= .1
                   for (_, a), (_, b) in zip(raw, raw[1:]))
        velocities = [float(r['ball_radial_velocity']) for _, r in raw]
        clearances = [float(r['directional_edge_distance']) - float(r['ball_radius']) for _, r in raw]
        qvalues = [float(r['directional_edge_distance']) - 2 * float(r['ball_radius']) for _, r in raw]
        assert all(q <= 0 for q in qvalues) and clearances[-1] <= 0 and all(c > 0 for c in clearances[:-1])
        points = [r for r in orange if r['session_id'] == sid and lo <= int(r['csv_row']) < hi and float(r['clearance']) > 0]
        assert len(points) == int(pick['sampled_band_points'])
        assert all(yes(r['available']) for r in points)
        assert all(r['run_id'] == context[0] and r['platform_id'] == context[2] and r['geometry_version_id'] == context[3] for r in points)
        for point in points:
            sr = next(r for line, r in raw if line == int(point['csv_row']))
            assert int(sr['sequence']) == int(point['source_sequence'])
            assert abs(float(point['timestamp']) - float(sr['source_timestamp'])) <= 1e-12
            assert abs(float(point['radial_outward_velocity']) - float(sr['ball_radial_velocity'])) <= 1e-12
        source_flags_ok = all(yes(r['geometry_query_valid']) and yes(r['geometry_ownership_valid']) and yes(r['directional_edge_valid'])
                              and r['geometry_active_platform_instance_id'] == context[2]
                              and r['geometry_active_version_id'] == context[3] for _, r in raw)
        assert source_flags_ok
        pattern = classify(points)
        inactive = [r for r in points if not yes(r['active'])]
        first = inactive[0]
        first_time = float(first['timestamp'])
        next_active = next((r for r in points if float(r['timestamp']) > first_time and yes(r['active'])), None)
        case_id = f'C{case_no:02d}'
        stage_start = float(span['q_high_time'])
        previous = [r for r in orange if r['session_id'] == sid and r['segment_id'] == points[0]['segment_id']
                    and float(r['timestamp']) < float(points[0]['timestamp'])]
        prior = previous[-1] if previous else {}
        case_rows.append(dict(case_id=case_id, session_id=sid, run_id=context[0], layer=context[1],
                              platform_id=context[2], geometry_version_id=context[3], exit_sequence=pick['exit_source_sequence'],
                              pattern=pattern, source_packet_span_lower_s=float(span['packet_bracket_span_lower_s']),
                              source_packet_span_upper_s=float(span['packet_bracket_span_upper_s']),
                              q_start_line=lo, c_boundary_line=hi, raw_rows=len(raw),
                              outward_velocity_min=min(velocities), outward_velocity_max=max(velocities),
                              raw_inward_samples=sum(v < -.05 for v in velocities),
                              raw_clearance_increases=sum(b > a + 1e-9 for a, b in zip(clearances, clearances[1:])),
                              orange_decisions=len(points), orange_inactive_decisions=len(inactive),
                              orange_active_decisions=len(points)-len(inactive),
                              first_inactive_sequence=first['source_sequence'], first_inactive_line=first['csv_row'],
                              first_inactive_policy_reason=first['policy_reason'],
                              first_inactive_probability=float(first['probability']),
                              first_inactive_velocity=float(first['radial_outward_velocity']),
                              first_inactive_clearance=float(first['clearance']),
                              first_inactive_to_c_source_packet_lower_s=float(span['c_low_time'])-first_time,
                              first_inactive_to_c_source_packet_upper_s=float(span['c_high_time'])-first_time,
                              next_active_source_decision_delta_s=float(next_active['timestamp'])-first_time if next_active else None,
                              duration_interpretation='source-clock observations only, not certified visible gaps',
                              previous_to_stage_sequence=prior.get('source_sequence'),
                              previous_to_stage_policy_reason=prior.get('policy_reason'),
                              joint_recovery_at_inactive_count=sum(yes(r['joint_recovery']) for r in inactive),
                              native_yellow_active_all=all(yes(r['warning_active']) and r['visible_warning_state']=='EDGE_WARNING' for _, r in raw),
                              source_flags_match_all=source_flags_ok,
                              terminal_outcome_descriptive_only=manifest[sid]['actual_terminal_outcome'],
                              query_receive_age_verified=False, actual_display_gap_seconds=None))
        for line, r in raw:
            raw_timeline.append(dict(case_id=case_id, session_id=sid, physical_csv_line=line, sequence=r['sequence'],
                                     source_timestamp=r['source_timestamp'], offset_from_first_q_nonpositive=float(r['source_timestamp'])-stage_start,
                                     run_id=r['run_id'], layer=r['platform_level'], platform=r['geometry_platform_instance_id'],
                                     version=r['geometry_version_id'], outward_velocity=r['ball_radial_velocity'],
                                     q=float(r['directional_edge_distance'])-2*float(r['ball_radius']),
                                     clearance=float(r['directional_edge_distance'])-float(r['ball_radius']),
                                     native_warning_active=r['warning_active'], native_visible_warning_state=r['visible_warning_state']))
        for r in points:
            decision_timeline.append(dict(case_id=case_id, offset_from_first_q_nonpositive=float(r['timestamp'])-stage_start,
                                          **{k:r[k] for k in ('session_id','run_id','source_sequence','csv_row','segment_id','layer','platform_id',
                                                             'geometry_version_id','timestamp','q','clearance','radial_outward_velocity','probability',
                                                             'available','active','policy_reason','joint_recovery','continuous_inward_duration','clearance_gain_0_1s')}))
    dump_csv(OUT / 'seven_cases.csv', case_rows)
    dump_csv(OUT / 'raw_timelines.csv', raw_timeline)
    dump_csv(OUT / 'orange_decision_timelines.csv', decision_timeline)
    after = {str(p): sha(p) for p in sources}
    assert before == after
    summary = dict(cases=len(case_rows), sessions=len(raw_paths), raw_rows=len(raw_timeline), orange_decisions=len(decision_timeline),
                   patterns=dict(collections.Counter(r['pattern'] for r in case_rows)),
                   raw_inward_samples=sum(r['raw_inward_samples'] for r in case_rows),
                   raw_clearance_increases=sum(r['raw_clearance_increases'] for r in case_rows),
                   joint_recovery_at_inactive_count=sum(r['joint_recovery_at_inactive_count'] for r in case_rows),
                   native_yellow_all_cases=all(r['native_yellow_active_all'] for r in case_rows),
                   source_identity_flags_all_cases=all(r['source_flags_match_all'] for r in case_rows),
                   outcomes_descriptive_only=dict(collections.Counter(r['terminal_outcome_descriptive_only'] for r in case_rows)),
                   actual_display_gap_seconds=None, sources_unchanged=before==after, source_sha_before=before,
                   source_sha_after=after)
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if not k.startswith('source_sha')}, indent=2))


if __name__ == '__main__':
    main()
