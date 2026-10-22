"""Independent raw source-packet q/c bracket check; no UI/capture-time claims."""
import collections
import json
import statistics
from pathlib import Path

from check_handoff import MAN, OUT, ROOT, num, output, rows, sha, source_flags


def raw_ctx(r):
    return tuple(r[k] for k in ('run_id', 'platform_level', 'geometry_platform_instance_id', 'geometry_version_id'))


def qc(r):
    return num(r['directional_edge_distance']) - 2 * num(r['ball_radius']), num(r['directional_edge_distance']) - num(r['ball_radius'])


def adjacent(a, b):
    return (raw_ctx(a) == raw_ctx(b) and source_flags(a) and source_flags(b)
            and int(b['sequence']) == int(a['sequence']) + 1
            and 0 < float(b['source_timestamp']) - float(a['source_timestamp']) <= .1 + 1e-9)


def track(group, pos, cap=2.):
    anchor = group[pos]
    lo_pos, hi_pos = None, pos
    while hi_pos > 0:
        a, b = group[hi_pos - 1], group[hi_pos]
        if not adjacent(a, b):
            break
        if qc(a)[0] > 0:
            lo_pos = hi_pos - 1
            break
        hi_pos -= 1
    result = {'exit_source_sequence': anchor['sequence'], 'q_bracket_available': lo_pos is not None,
              'q_low_line': group[lo_pos]['_line'] if lo_pos is not None else None,
              'q_high_line': group[hi_pos]['_line'] if lo_pos is not None else None,
              'q_low_time': float(group[lo_pos]['source_timestamp']) if lo_pos is not None else None,
              'q_high_time': float(group[hi_pos]['source_timestamp']) if lo_pos is not None else None,
              'source_flags_only': True, 'runtime_freshness_certified': False}
    previous = hi_pos
    stop = 'end_of_available_source'
    red_pos = None
    last_valid = hi_pos
    for i in range(hi_pos, len(group)):
        current = group[i]
        if current.get('run_state') != 'running':
            stop = 'terminal_or_nonrunning'
            break
        if raw_ctx(current) != raw_ctx(anchor):
            stop = 'context_changed'
            break
        if not source_flags(current):
            stop = 'invalid_source_evidence'
            break
        if i > hi_pos and not adjacent(group[i - 1], current):
            stop = 'source_discontinuity'
            break
        if float(current['source_timestamp']) - float(group[hi_pos]['source_timestamp']) > cap:
            stop = 'observation_cap'
            break
        last_valid = i
        q, c = qc(current)
        if c <= 0:
            red_pos, previous, stop = i, max(hi_pos, i - 1), 'first_c_nonpositive'
            break
        if q > 0:
            stop = 'q_positive_again'
            break
    result.update(stop_reason=stop, last_valid_line=group[last_valid]['_line'],
                  last_valid_time=float(group[last_valid]['source_timestamp']))
    if red_pos is not None:
        result.update(c_low_line=group[previous]['_line'], c_high_line=group[red_pos]['_line'],
                      c_low_time=float(group[previous]['source_timestamp']),
                      c_high_time=float(group[red_pos]['source_timestamp']))
        if lo_pos is not None and qc(group[previous])[1] > 0:
            result.update(packet_bracket_span_lower_s=max(0., result['c_low_time'] - result['q_high_time']),
                          packet_bracket_span_upper_s=max(0., result['c_high_time'] - result['q_low_time']))
    return result


def main():
    inputs = [MAN, OUT / 'domain_exit_channels.csv']
    raw = {}
    for s in rows(MAN):
        path = ROOT / 'telemetry_logs/INPUT055_CHECK' / s['session_id'] / 'raw.csv'
        assert sha(path) == s['raw_sha256']
        inputs.append(path)
        raw[s['session_id']] = [dict(r, _line=i) for i, r in enumerate(rows(path), 2) if r['source'].lower() == 'unity']
    before = {str(p): sha(p) for p in inputs}
    result = []
    for ex in rows(OUT / 'domain_exit_channels.csv'):
        group = raw[ex['session_id']]
        pos = next(i for i, r in enumerate(group) if r['_line'] == int(ex['csv_row']))
        assert group[pos]['sequence'] == ex['source_sequence']
        result.append(dict(session_id=ex['session_id'], run_id=ex['run_id'],
                           exit_csv_line=int(ex['csv_row']), **track(group, pos)))
    output(OUT / 'raw_source_brackets.csv', result)
    decisions = rows(OUT / 'source_decision_channels.csv')
    covered_keys = set()
    segment_coverage = []
    for span in result:
        points = [r for r in decisions if r['session_id'] == span['session_id']
                  and span['q_high_line'] is not None
                  and span['q_high_line'] <= int(r['csv_row']) <= span['last_valid_line']
                  and r['band'] == 'between_q_and_c']
        active = sum(r['orange_active'] == 'True' for r in points)
        for r in points:
            k = (r['session_id'], r['source_sequence'], r['csv_row'])
            assert k not in covered_keys
            covered_keys.add(k)
        segment_coverage.append(dict(session_id=span['session_id'], exit_source_sequence=span['exit_source_sequence'],
                                     stop_reason=span['stop_reason'], sampled_band_points=len(points),
                                     orange_active_points=active, orange_inactive_points=len(points)-active,
                                     any_inactive_sample=len(points)>active, any_active_sample=active>0))
    output(OUT / 'postq_segment_decision_coverage.csv', segment_coverage)
    native_states = collections.Counter()
    native_active = collections.Counter()
    for r in decisions:
        if r['band'] != 'between_q_and_c' or r['orange_active'] == 'True':
            continue
        sr = next(x for x in raw[r['session_id']] if x['_line'] == int(r['csv_row']))
        native_states[sr.get('visible_warning_state', '')] += 1
        native_active[sr.get('warning_active', '')] += 1
    complete = [r for r in result if r.get('packet_bracket_span_lower_s') is not None]
    summary = {'exits': len(result), 'stop_reasons': dict(collections.Counter(r['stop_reason'] for r in result)),
               'available_q_brackets': sum(r['q_bracket_available'] for r in result),
               'q_to_c_brackets': len(complete),
               'q_to_c_packet_span_lower_median': statistics.median(r['packet_bracket_span_lower_s'] for r in complete),
               'q_to_c_packet_span_upper_median': statistics.median(r['packet_bracket_span_upper_s'] for r in complete),
               'q_to_c_packet_span_lower_min': min(r['packet_bracket_span_lower_s'] for r in complete),
               'q_to_c_packet_span_upper_max': max(r['packet_bracket_span_upper_s'] for r in complete),
               'tracked_exit_band_decisions': len(covered_keys),
               'tracked_exit_segments_any_inactive_orange_sample': sum(r['any_inactive_sample'] for r in segment_coverage),
               'segments_by_stop_and_orange_sample_pattern': dict(collections.Counter(
                   r['stop_reason'] + '|' + ('mixed' if r['any_inactive_sample'] and r['any_active_sample']
                                             else 'all_inactive' if r['any_inactive_sample'] else 'all_active') for r in segment_coverage)),
               'native_visible_warning_state_at_166_experimental_noncoverage_samples': dict(native_states),
               'native_warning_active_at_166_experimental_noncoverage_samples': dict(native_active),
               'sources_unchanged': before == {str(p): sha(p) for p in inputs},
               'clock': 'source_timestamp of raw Unity packet rows; not physical geometry capture or client display time',
               'source_sha_before': before}
    assert summary['sources_unchanged']
    (OUT / 'raw_bracket_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_sha_before'}, indent=2))


if __name__ == '__main__':
    main()
