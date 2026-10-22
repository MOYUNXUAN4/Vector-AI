"""Read-only P03 source timing and cross-check of separately reviewed sidecars."""
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
REVIEW = BASE / 'parallel_20261020/p03_postfix_review_primary'


def number(x):
    if isinstance(x, bool):
        return None
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (TypeError, ValueError):
        return None


def yes(x):
    return str(x).lower() == 'true'


def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def context(r):
    return tuple(r.get(k) for k in ('run_id', 'platform_level', 'geometry_platform_instance_id', 'geometry_version_id'))


def join_active(ev, rows):
    """No neighboring-row, prediction-sequence or cross-clock substitution."""
    f = ev.get('fields', {})
    seq = f.get('input_sequence')
    matches = [r for r in rows if r.get('run_id') == ev.get('run_id') and r.get('sequence') == seq]
    if seq is None or len(matches) != 1:
        return None
    r = matches[0]
    if f.get('layer') != r.get('platform_level') or f.get('platform') != r.get('geometry_platform_instance_id'):
        return None
    if 'version' in f and f['version'] != r.get('geometry_version_id'):
        return None
    return r


def latest_same_context(evts, channel, rows, anchor):
    eligible = []
    for ev in evts:
        if ev.get('channel') != channel or ev.get('state') != 'ACTIVE':
            continue
        r = join_active(ev, rows)
        if r is not None and context(r) == context(anchor):
            t, end = number(r.get('source_timestamp')), number(anchor.get('fall_event_backend_timestamp'))
            if t is not None and end is not None and t <= end:
                eligible.append((t, ev, r))
    if not eligible:
        return None
    t, ev, r = max(eligible, key=lambda z: z[0])
    return {'input_sequence': r['sequence'], 'csv_line': r['_csv_line'],
            'source_timestamp': t, 'fall_commit_minus_onset_source_s': number(anchor['fall_event_backend_timestamp'])-t,
            'client_log_line': ev['line'], 'version_explicit_in_client_log': 'version' in ev['fields']}


def native_onset(rows, anchor, key):
    """Return a sampled false-to-true onset bracket; never reuse a prior platform."""
    end = number(anchor.get('fall_event_backend_timestamp'))
    candidates = []
    for a, b in zip(rows, rows[1:]):
        ta, tb = number(a.get('source_timestamp')), number(b.get('source_timestamp'))
        if (context(a) == context(b) == context(anchor) and a.get(key) == 'False' and b.get(key) == 'True'
                and ta is not None and tb is not None and end is not None and 0 < tb-ta <= .1 and tb <= end):
            candidates.append({'left_sequence': a['sequence'], 'right_sequence': b['sequence'],
                               'fall_commit_minus_onset_source_interval_s': [end-tb, end-ta]})
    return candidates[-1] if candidates else None


def analyze():
    client = json.loads((REVIEW/'client_result.json').read_text(encoding='utf-8'))
    receipt = json.loads((REVIEW/'CONDITION_RECEIPT.json').read_text(encoding='utf-8'))
    burden = json.loads((BASE/'parallel_20261020/p03_analysis_client_luna/client_burden_report.json').read_text(encoding='utf-8'))
    assert {s['session_id'] for s in client['sessions']} == set(receipt['session_ids'])
    results, before, target_runs = [], {}, set()
    for sess in client['sessions']:
        sid, run = sess['session_id'], sess['run_id']
        p = BASE/'telemetry_logs/P03'/sid/'raw.csv'
        before[str(p)] = digest(p)
        expected = next(v for k,v in client['source_sha256_before'].items() if k.replace('\\','/').endswith('/'+sid+'/raw.csv'))
        assert before[str(p)] == expected
        with p.open(encoding='utf-8-sig', newline='') as f:
            rows = [dict(r, _csv_line=i) for i, r in enumerate(csv.DictReader(f), 2) if r.get('source') == 'unity' and r.get('run_id') == run]
        seq = [int(r['sequence']) for r in rows]
        ts = [number(r['source_timestamp']) for r in rows]
        assert all(t is not None for t in ts)
        evts = [e for e in client['state_records'] if e['run_id'] == run]
        b = next(r for r in burden['runs'] if r['run_id'] == run)
        out = {'session_id':sid, 'run_id':run, 'unity_rows':len(rows), 'outcome':rows[-1]['session_outcome'],
               'terminal_state':rows[-1]['run_state'], 'source_duration_s':ts[-1]-ts[0],
               'max_source_gap_s':max(y-x for x,y in zip(ts,ts[1:])),
               'source_gaps_over_0_1s':sum(y-x > .1 for x,y in zip(ts,ts[1:])),
               'sequence_contiguous':seq == list(range(seq[0],seq[-1]+1)),
               'difficulty_values':sorted({r['selected_difficulty'] for r in rows}),
               'layer_setting_values':sorted({r['selected_session_layers'] for r in rows}),
               'burden':b['channels']}
        falls = [r for r in rows if yes(r.get('fall_event')) and (number(r.get('fall_event_backend_timestamp')) or 0) > 0]
        falltimes = {number(r['fall_event_backend_timestamp']) for r in falls}
        assert len(falltimes) <= 1
        if falls:
            anchor = falls[0]
            end = number(anchor['fall_event_backend_timestamp'])
            contextrows = [r for r in rows if context(r) == context(anchor) and number(r['source_timestamp']) <= end]
            out['fall'] = {'source_event_epoch':end, 'first_observation_csv_line':anchor['_csv_line'],
                           'context':context(anchor), 'context_observed_lifetime_before_fall_s':end-number(contextrows[0]['source_timestamp']),
                           'purple_source_onset':latest_same_context(evts,'ExperimentalProximityWarning',rows,anchor),
                           'red_source_onset':latest_same_context(evts,'ExperimentalGeometryWarning',rows,anchor),
                           'orange_source_lead':None,
                           'orange_source_lead_reason':'client log has no input sequence or source time',
                           'native_yellow_source_onset':native_onset(rows,anchor,'edge_warning_state'),
                           'native_blue_source_onset':native_onset(rows,anchor,'attention_state')}
            target_runs.add(run)
        results.append(out)
    shadow_reasons = {run:Counter() for run in target_runs}
    final_context_spans = {run:[] for run in target_runs}
    sp = BASE/'telemetry_logs/proximity_shadow.jsonl'
    shadow_before = digest(sp)
    parse_errors = 0
    with sp.open(encoding='utf-8-sig') as f:
        for line in f:
            try:
                x = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            run=x.get('run_id')
            if run in target_runs:
                fall = next(r['fall'] for r in results if r['run_id']==run)
                # Retain full context labels for manual interpretation; no guessed schema aliases.
                shadow_reasons[run][str((x.get('layer'), x.get('reason')))] += 1
                ctx = (run,str(x.get('layer')),str(x.get('platform_instance_id')),x.get('geometry_version_id'))
                if ctx == tuple(fall['context']):
                    spans = final_context_spans[run]
                    if not spans or spans[-1]['reason'] != x.get('reason'):
                        spans.append({'reason':x.get('reason'),'first_input_sequence':x.get('input_sequence'),
                                      'first_source_epoch':x.get('input_source_timestamp'),'records':0,'q_min':None,'q_max':None})
                    s=spans[-1];s['records']+=1
                    s['last_input_sequence']=x.get('input_sequence');s['last_source_epoch']=x.get('input_source_timestamp')
                    q=number(x.get('q'))
                    if q is not None:
                        s['q_min']=q if s['q_min'] is None else min(q,s['q_min'])
                        s['q_max']=q if s['q_max'] is None else max(q,s['q_max'])
    shadow_after = digest(sp)
    assert shadow_before == shadow_after
    after = {p:digest(Path(p)) for p in before}
    assert before == after
    groups = {}
    for outcome in ('calibration_completed','edge_exit'):
        subset = [r for r in results if r['outcome']==outcome]
        groups[outcome] = {'sessions':len(subset), 'channels':{}}
        for ch in ('orange_model','purple_tte','red_geometry'):
            c=[r['burden'][ch] for r in subset]
            groups[outcome]['channels'][ch] = {'sessions_with_activation':sum(x['episode_count']>0 for x in c),
                'episodes':sum(x['episode_count'] for x in c),
                'closed_accepted_state_duration_s':sum(x['closed_duration_s'] for x in c) if ch!='red_geometry' else None,
                'unknown_duration_episodes':sum(x['unknown_duration_episode_count'] for x in c)}
    return {'method':'METHOD.md','raw_sha256_before':before,'raw_sha256_after':after,'sources_unchanged':before==after,
            'groups':groups,'sessions':results,'shadow_reasons_by_logged_layer':{k:dict(v) for k,v in shadow_reasons.items()},
            'shadow_sha256_before':shadow_before,'shadow_sha256_after':shadow_after,
            'final_fall_context_shadow_spans':final_context_spans,
            'shared_shadow_parse_error_lines':parse_errors,
            'limits':['Source observation leads exclude reply transport and rendering delay.',
                      'Orange source lead unavailable; no neighbor-log interpolation.',
                      'Ordinary q brackets are not strict full-query geometric anchors.',
                      'One participant with prompts enabled; not independent performance acceptance.']}


if __name__ == '__main__':
    result=analyze()
    (HERE/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'groups':result['groups'],'falls':[r['fall'] for r in result['sessions'] if 'fall' in r]},indent=2))
