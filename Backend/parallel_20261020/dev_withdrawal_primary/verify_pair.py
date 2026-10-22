"""Independent cross-check of primary and delegated descriptive replay outputs."""
import collections
import csv
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
LUNA = OUT.parent / 'dev_withdrawal_replay_luna'


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def key(r):
    return tuple(r[x] for x in ('session_id', 'run_id', 'source_sequence', 'csv_row', 'segment_id'))


def yes(v):
    return str(v).lower() in ('1', 'true')


def main():
    a = {key(r): r for r in rows(OUT / 'tte_trace.csv')}
    b = {key(r): r for r in rows(LUNA / 'decision_traces.csv')}
    assert len(a) == len(b) == 7553 and a.keys() == b.keys()
    for k, r in a.items():
        s = b[k]
        for name in ('active', 'policy_reason', 'confirmed'):
            if name == 'confirmed':
                continue  # Primary raw trace does not serialize this redundant field.
            assert r[name] == s[name], (k, name)
        assert yes(r['raw']) == yes(s['fixed_tte_raw_on']), (k, 'raw')
        assert float(r['q']) == float(s['q']), (k, 'q')
    observed = [r for r in rows(OUT / 'tte_withdrawals.csv') if r['withdrawal_kind'] == 'observed_inactive_decision']
    delegates = rows(LUNA / 'episode_withdrawals.csv')
    assert len(observed) == len(delegates) == 77
    ka = {(r['session_id'], r['source_sequence'], r['csv_row']): r for r in observed}
    kb = {(r['session_id'], r['current_source_sequence'], r['current_identity'].split('|')[3]): r for r in delegates}
    assert ka.keys() == kb.keys()
    remap = {'q_nonpositive_domain_exit': 'domain_q_nonpositive', 'raw_off': 'normal_raw_off'}
    for k in ka:
        assert remap[ka[k]['mechanism']] == kb[k]['withdrawal_mechanism']
    full = rows(OUT / 'tte_trace.csv')
    by_sid = collections.defaultdict(list)
    for r in full:
        by_sid[r['session_id']].append(r)
    independent_followup = []
    for w in delegates:
        if w['withdrawal_mechanism'] != 'normal_raw_off':
            continue
        group = by_sid[w['session_id']]
        i = next(i for i, r in enumerate(group) if r['source_sequence'] == w['current_source_sequence'])
        current = group[i]
        ctx = tuple(current[n] for n in ('run_id', 'segment_id', 'layer', 'platform_id', 'geometry_version_id'))
        last = current
        horizon = float(current['timestamp']) + .4
        selected = []
        complete = False
        for r in group[i+1:]:
            if tuple(r[n] for n in ('run_id', 'segment_id', 'layer', 'platform_id', 'geometry_version_id')) != ctx:
                break
            t = float(r['timestamp'])
            if not 0 < t - float(last['timestamp']) <= .100000001:
                break
            if t > horizon:
                complete = True
                break
            selected.append(r)
            last = r
            if t >= horizon - 1e-9:
                complete = True
                break
        expected = {'future_0_4s_complete': complete,
                    'future_0_4s_any_active': any(yes(r['active']) for r in selected),
                    'future_0_4s_any_saved_joint_recovery': any(yes(r['joint_recovery']) for r in selected),
                    'future_0_4s_any_q_nonpositive': any(float(r['q']) <= 0 for r in selected)}
        for k, value in expected.items():
            assert yes(w[k]) == value, (w['session_id'], w['current_source_sequence'], k)
        independent_followup.append(expected)
    result = {'decision_keys_matched': len(a), 'active_policy_reason_raw_q_identical': True,
              'observed_withdrawal_keys_and_mechanisms_identical': len(ka),
              'future_rows_independently_checked': len(independent_followup),
              'followup_counts': {k: sum(r[k] for r in independent_followup) for k in independent_followup[0]}}
    (OUT / 'pair_verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
