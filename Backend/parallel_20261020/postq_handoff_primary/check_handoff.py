"""Independent source-level handoff audit. No runtime simulation or edits."""
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PREV = ROOT / 'parallel_20261020/dev_withdrawal_primary'
MAN = ROOT / 'parallel_20261014/command055_fit_luna/session_manifest.csv'


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def num(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def yes(value):
    return str(value).lower() in ('true', '1')


def ctx(r):
    return tuple(r[k] for k in ('session_id', 'run_id', 'segment_id', 'layer', 'platform_id', 'geometry_version_id'))


def key(r):
    return tuple(r[k] for k in ('session_id', 'run_id', 'source_sequence', 'csv_row', 'segment_id'))


def source_flags(r):
    """Necessary source conditions only. Query and receive age remain unknown."""
    for f in ('directional_edge_valid', 'geometry_query_valid', 'geometry_ownership_valid'):
        if not yes(r.get(f)):
            return False
    pid = num(r.get('geometry_platform_instance_id'))
    active = num(r.get('geometry_active_platform_instance_id'))
    ver = r.get('geometry_version_id', '')
    return bool(r.get('run_state') == 'running' and r.get('run_id') and pid is not None
                and pid.is_integer() and pid not in (-1, 0, -2147483648) and active == pid
                and ver and ver.lower() not in ('unknown', 'nan', 'none')
                and ver == r.get('geometry_active_version_id')
                and num(r.get('platform_level')) is not None
                and num(r.get('platform_level')) > 0
                and num(r.get('directional_edge_distance')) is not None
                and num(r.get('ball_radius')) is not None and num(r.get('ball_radius')) > 0)


def output(path, records):
    with path.open('w', encoding='utf-8', newline='') as stream:
        fields = list(dict.fromkeys(k for r in records for k in r))
        w = csv.DictWriter(stream, fields)
        w.writeheader()
        w.writerows(records)


def main():
    manifest = rows(MAN)
    sources = [MAN, PREV / 'tte_trace.csv', PREV / 'locked24_trace.csv', PREV / 'tte_withdrawals.csv',
               PREV / 'independent_results.json',
               ROOT / 'parallel_20261011/realtime_integration/geometry_danger.py',
               ROOT / 'parallel_20261014/proximity_shadow_backend_luna/proximity_shadow.py',
               ROOT / 'parallel_20261010/backend/warning_runtime.py',
               ROOT / 'parallel_20261010/backend/stream_guard.py']
    raw = {}
    for s in manifest:
        path = ROOT / 'telemetry_logs/INPUT055_CHECK' / s['session_id'] / 'raw.csv'
        assert sha(path) == s['raw_sha256']
        sources.append(path)
        raw[s['session_id']] = rows(path)
    before = {str(p): sha(p) for p in sources}
    purple = rows(PREV / 'tte_trace.csv')
    orange_rows = rows(PREV / 'locked24_trace.csv')
    orange = {key(r): r for r in orange_rows}
    reference = json.loads((PREV / 'independent_results.json').read_text(encoding='utf-8'))
    assert len(purple) == len(orange_rows) == len(orange) == reference['decision_rows'] == 7553
    assert sum(yes(r['active']) for r in purple) == reference['tte']['active_decisions'] == 699
    assert sum(yes(r['active']) for r in orange_rows) == reference['locked24']['active_decisions'] == 394
    joined = []
    for r in purple:
        o = orange[key(r)]
        sr = raw[r['session_id']][int(r['csv_row']) - 2]
        assert sr['run_id'] == r['run_id'] and int(sr['sequence']) == int(r['source_sequence'])
        d, radius = num(sr['directional_edge_distance']), num(sr['ball_radius'])
        q, c = d - 2 * radius, d - radius
        assert abs(q - float(r['q'])) <= 1e-12
        assert abs(c - float(r['clearance'])) <= 1e-12
        conditional = source_flags(sr)
        band = 'before_q' if q > 0 else 'between_q_and_c' if c > 0 else 'c_nonpositive'
        joined.append(dict(session_id=r['session_id'], run_id=r['run_id'], source_sequence=r['source_sequence'],
                           csv_row=r['csv_row'], segment_id=r['segment_id'], layer=r['layer'],
                           platform_id=r['platform_id'], geometry_version_id=r['geometry_version_id'],
                           timestamp=r['timestamp'], q=q, clearance=c, band=band,
                           purple_active=yes(r['active']), purple_available=yes(r['available']),
                           orange_active=yes(o['active']), orange_available=yes(o['available']),
                           orange_probability=float(o['probability']),
                           red_numeric_predicate=c <= 0, necessary_source_flags=conditional,
                           red_runtime_validity='unknown_query_and_receive_age',
                           visible_banner_state='not_reconstructed'))
    output(OUT / 'source_decision_channels.csv', joined)
    index = {key(r): r for r in joined}
    exits = [index[key(r)] for r in rows(PREV / 'tte_withdrawals.csv')
             if r['withdrawal_kind'] == 'observed_inactive_decision' and r['mechanism'] == 'q_nonpositive_domain_exit']
    assert len(exits) == 49
    output(OUT / 'domain_exit_channels.csv', exits)
    band = [r for r in joined if r['band'] == 'between_q_and_c']
    no_condition = [r for r in band if not r['purple_active'] and not r['orange_active'] and r['necessary_source_flags']]
    zoh = 0.
    endpoints = 0.
    for a, b in zip(joined, joined[1:]):
        dt = float(b['timestamp']) - float(a['timestamp'])
        if ctx(a) != ctx(b) or not 0 < dt <= .1:
            continue
        off_a = a['band'] == 'between_q_and_c' and not a['orange_active'] and a['necessary_source_flags']
        off_b = b['band'] == 'between_q_and_c' and not b['orange_active'] and b['necessary_source_flags']
        if off_a:
            zoh += dt
        if off_a and off_b:
            endpoints += dt
    result = {'cohort': 'INPUT055_CHECK original 31 development sessions', 'decisions': len(joined),
              'source_flags_valid_rows': sum(r['necessary_source_flags'] for r in joined),
              'domain_exits': len(exits),
              'exit_band_counts': dict(collections.Counter(r['band'] for r in exits)),
              'orange_at_exit': dict(collections.Counter('active' if r['orange_active'] else 'eligible_inactive' if r['orange_available'] else 'unavailable' for r in exits)),
              'exit_red_numeric_true': sum(r['red_numeric_predicate'] for r in exits),
              'exit_source_flags_valid': sum(r['necessary_source_flags'] for r in exits),
              'between_q_and_c_decisions': len(band),
              'between_q_and_c_orange_active': sum(r['orange_active'] for r in band),
              'between_q_and_c_orange_available': sum(r['orange_available'] for r in band),
              'between_q_and_c_conditional_no_channel_decisions': len(no_condition),
              'start_state_zoh_proxy_seconds': zoh,
              'both_endpoint_proxy_seconds': endpoints,
              'proxy_definition': 'Same-context adjacent decisions <=0.1s. Not physical or rendered gap duration.',
              'source_sha_before': before}
    after = {str(p): sha(p) for p in sources}
    assert before == after
    result['sources_unchanged'] = True
    (OUT / 'primary_counts.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'source_sha_before'}, indent=2))


if __name__ == '__main__':
    main()
