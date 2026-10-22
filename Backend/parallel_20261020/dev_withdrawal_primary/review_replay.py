"""Fixed-weight decision replay; descriptive withdrawals, never a fit or UI test."""
from __future__ import annotations

import collections
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
INPUT = ROOT / 'parallel_20261014/command055_fit_luna/ordered_features.csv'
MANIFEST = ROOT / 'parallel_20261014/command055_fit_luna/session_manifest.csv'
LABELS = ROOT / 'parallel_20261014/risk_windows_luna/window_feasibility.csv'
POLICY = ROOT / 'parallel_20261010/backend/alarm_policy.py'
ART = ROOT / 'parallel_20261011/deployment_refit/output/artifact'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def truth(value):
    return str(value).lower() in ('true', '1')


def key(row):
    return tuple(row[k] for k in ('session_id', 'run_id', 'source_sequence', 'csv_row', 'segment_id'))


def context(row):
    return tuple(row[k] for k in ('session_id', 'run_id', 'segment_id', 'layer', 'platform_id', 'geometry_version_id'))


def movement(current, previous):
    v, pv = number(current.get('radial_outward_velocity')), number(previous.get('radial_outward_velocity'))
    if v is None or pv is None:
        return 'insufficient'
    if v < -.05:
        return 'inward_instantaneous'
    if v > 0:
        return 'outward_slower_than_previous' if v < pv else 'outward_not_slower_than_previous'
    return 'near_zero_or_weak_inward'


def replay(frame, probs, threshold, Policy, *, tte=False):
    trace, endings = [], []
    policy = Policy(threshold)
    previous = None
    active_start = None
    for source, prob in zip(frame, probs):
        r = dict(source)
        t, c = float(r['timestamp']), number(r['clearance'])
        v = number(r['radial_outward_velocity'])
        d, radius = number(r['directional_edge_distance']), number(r['ball_radius'])
        q = d - 2 * radius if d is not None and radius is not None else None
        available = truth(r['causal_prediction_available']) and c is not None and c > 0
        if tte:
            available = available and q is not None and q > 0 and radius is not None and radius > 0 and v is not None
        r.update(q=q, tte_seconds=q / v if q is not None and q > 0 and v is not None and v > 0 else None,
                 probability=prob, available=available)
        same = previous is not None and context(r) == context(previous)
        dt = t - float(previous['timestamp']) if previous else None
        continuous = same and 0 < dt <= .100000001
        if previous is not None and not continuous and previous['active']:
            boundary = ('end_of_session_decision_boundary' if previous['session_id'] != r['session_id']
                        else 'context_changed' if not same else 'decision_gap')
            endings.append(dict(previous, withdrawal_kind='boundary_censored',
                                mechanism=boundary,
                                next_source_sequence=r['source_sequence'], movement='not_comparable'))
            active_start = None
        if not same:
            policy.reset()
        result = policy.step(prob if available else math.nan, c, t, context(r), truth(r['joint_recovery']))
        r.update(active=result['active'], policy_reason=result['reason'], raw=result['raw'],
                 recovery_cancelled=result['canceled'])
        if r['active'] and (previous is None or not continuous or not previous['active']):
            active_start = r['source_sequence']
        r['episode_onset_sequence'] = active_start
        trace.append(r)
        if continuous and previous['active'] and not r['active']:
            if not available:
                mechanism = 'q_nonpositive_domain_exit' if tte and q is not None and q <= 0 else 'invalid_or_nonpositive_clearance'
            else:
                mechanism = result['reason']
            ending = dict(r, withdrawal_kind='observed_inactive_decision', mechanism=mechanism,
                          movement=movement(r, previous), previous_velocity=number(previous['radial_outward_velocity']),
                          previous_q=previous['q'], previous_source_sequence=previous['source_sequence'],
                          episode_onset_sequence=previous['episode_onset_sequence'], previous_probability=previous['probability'])
            endings.append(ending)
            active_start = None
        previous = r
    if previous and previous['active']:
        endings.append(dict(previous, withdrawal_kind='boundary_censored', mechanism='end_of_decision_file', movement='not_comparable'))
    return trace, endings


def csv_out(path, records):
    fields = list(dict.fromkeys(k for r in records for k in r))
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(records)


def main():
    import lightgbm as lgb
    import numpy as np
    spec = importlib.util.spec_from_file_location('withdrawal_review_policy', POLICY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    inputs = [INPUT, MANIFEST, LABELS, POLICY, ART / 'manifest.json', ART / 'model.txt', Path(__file__)]
    sessions = rows(MANIFEST)
    for s in sessions:
        p = ROOT / 'telemetry_logs/INPUT055_CHECK' / s['session_id'] / 'raw.csv'
        assert sha(p) == s['raw_sha256'], str(p)
        inputs.append(p)
    before = {str(p): sha(p) for p in inputs}
    frame = sorted(rows(INPUT), key=lambda r: (r['session_id'], float(r['timestamp']), int(r['source_sequence'])))
    lab = {key(r): r['status'] for r in rows(LABELS)}
    assert len(frame) == 7553 and len(sessions) == 31 and len(lab) == len(frame)
    for r in frame:
        r['frozen_status'] = lab[key(r)]
    raw_by_session = {s['session_id']: rows(ROOT / 'telemetry_logs/INPUT055_CHECK' / s['session_id'] / 'raw.csv') for s in sessions}
    source_alignment = {'rows_checked': 0, 'max_numeric_difference': {}}
    for r in frame:
        raw = raw_by_session[r['session_id']][int(r['csv_row']) - 2]
        assert raw['source'].lower() == 'unity'
        assert raw['run_id'] == r['run_id'] and int(raw['sequence']) == int(r['source_sequence'])
        assert raw['geometry_version_id'] == r['geometry_version_id']
        for field, original in [('timestamp', 'source_timestamp'), ('layer', 'platform_level'),
                                ('platform_id', 'geometry_platform_instance_id'),
                                ('directional_edge_distance', 'directional_edge_distance'),
                                ('ball_radius', 'ball_radius'), ('radial_outward_velocity', 'ball_radial_velocity')]:
            diff = abs(float(r[field]) - float(raw[original]))
            assert diff <= 1e-12, (key(r), field, diff)
            source_alignment['max_numeric_difference'][field] = max(source_alignment['max_numeric_difference'].get(field, 0.), diff)
        source_alignment['rows_checked'] += 1
    artifact = json.loads((ART / 'manifest.json').read_text())
    assert sha(ART / 'model.txt') == artifact['model_sha256']
    assert artifact['threshold'] == .65 and len(artifact['features']) == 24
    model = lgb.Booster(model_file=str(ART / 'model.txt'))
    matrix = np.array([[number(r[k]) if number(r[k]) is not None else artifact['medians'][k]
                        for k in artifact['features']] for r in frame])
    probabilities = model.predict(matrix, num_threads=1)
    assert np.array_equal(probabilities[:32], model.predict(matrix[:32], num_threads=1))
    binary = []
    for r in frame:
        q = float(r['directional_edge_distance']) - 2 * float(r['ball_radius'])
        v = float(r['radial_outward_velocity'])
        binary.append(float(q > 0 and v > 0 and q / v <= .75))
    summary = {'sessions': 31, 'decision_rows': len(frame), 'model_id': artifact['model_id'],
               'model_sha256': artifact['model_sha256'], 'threshold': .65,
               'trained': False, 'threshold_selection': False, 'source_hashes_before': before,
               'raw_current_sample_alignment': source_alignment,
               'method': 'Saved source-epoch decision inputs only. No new alignment or labels; no UDP/UI timing replay.'}
    for name, probs, threshold, tte in [('tte', binary, .5, True), ('locked24', probabilities, .65, False)]:
        played, ends = replay(frame, probs, threshold, mod.StrongAlarmPolicy, tte=tte)
        csv_out(OUT / f'{name}_trace.csv', played)
        csv_out(OUT / f'{name}_withdrawals.csv', ends)
        active_seconds = 0.
        for a, b in zip(played, played[1:]):
            dt = float(b['timestamp']) - float(a['timestamp'])
            if a['active'] and context(a) == context(b) and 0 < dt <= .1:
                active_seconds += dt
        observed = [r for r in ends if r['withdrawal_kind'] == 'observed_inactive_decision']
        summary[name] = {'active_decisions': sum(r['active'] for r in played),
                         'bounded_active_seconds': active_seconds,
                         'endings': len(ends), 'observed_withdrawals': len(observed),
                         'boundary_censored': len(ends) - len(observed),
                         'mechanisms': dict(collections.Counter(r['mechanism'] for r in ends)),
                         'mechanism_movement': dict(collections.Counter(r['mechanism'] + '|' + r['movement'] for r in observed)),
                         'joint_recovery_on_withdrawal': sum(truth(r['joint_recovery']) for r in observed)}
    after = {str(p): sha(p) for p in inputs}
    assert before == after
    summary['sources_unchanged'] = before == after
    (OUT / 'independent_results.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_hashes_before'}, indent=2))


if __name__ == '__main__':
    main()
