"""Source-side anchors and cross-channel ordering; no clock interpolation."""
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
BACKEND=HERE.parents[1]
P02=BACKEND/'telemetry_logs/P02'
SHADOW=BACKEND/'telemetry_logs/proximity_shadow.jsonl'

def num(v):
    try: x=float(v)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None

def truth(v): return str(v).lower()=='true'
def context(r): return tuple(r.get(k,'') for k in ['run_id','platform_level','geometry_platform_instance_id','geometry_version_id'])
def point(r):
    d,b=num(r.get('directional_edge_distance')),num(r.get('ball_radius'))
    return d-2*b if d is not None and b is not None and b>0 else None
def valid(r):
    return all(truth(r.get(k)) for k in ['directional_edge_valid','geometry_query_valid','geometry_ownership_valid']) and point(r) is not None

def source_anchor_analysis():
    episodes=json.loads((HERE/'client_luna/client_warning_episodes.json').read_text())
    inputs={}
    for p in sorted(P02.glob('session_*/raw.csv')):
        data=p.read_bytes()
        rows=[]
        for line,r in enumerate(csv.DictReader(data.decode('utf-8-sig').splitlines()),2):
            if r.get('source')=='unity':
                r['_csv_line']=line
                rows.append(r)
        run=rows[0]['run_id']; byseq={int(r['sequence']):r for r in rows}
        crossings=[]
        for a,b in zip(rows,rows[1:]):
            dt=float(b['source_timestamp'])-float(a['source_timestamp'])
            if valid(a) and valid(b) and context(a)==context(b) and int(b['sequence'])==int(a['sequence'])+1 and 0<dt<=.1 and point(a)>0>=point(b):
                crossings.append(dict(last_positive_sequence=int(a['sequence']),first_nonpositive_sequence=int(b['sequence']),epoch_interval=[float(a['source_timestamp']),float(b['source_timestamp'])],context=context(b),csv_lines=[a['_csv_line'],b['_csv_line']]))
        fall_rows=[r for r in rows if truth(r.get('fall_event'))]
        fall=fall_rows[-1] if fall_rows else None
        purple=[]
        for e in episodes:
            if e['run_id']!=run or e['channel']!='proximity':continue
            r=byseq.get(int(e['start_sequence']))
            if r is None: raise ValueError('missing purple onset source sequence')
            purple.append(dict(client_episode_start_line=e['start_log_line'],source_csv_line=r['_csv_line'],input_sequence=int(r['sequence']),source_epoch=float(r['source_timestamp']),context=context(r),q_at_source=point(r),radial_velocity_at_source=num(r.get('ball_radial_velocity')),client_local_monotonic_s=e['start_local_monotonic_s'],client_duration_proxy_s=e['duration_s'],client_revoke_reason=e['revocation_reason']))
        item=dict(session=p.parent.name,run_id=run,csv_sha256=hashlib.sha256(data).hexdigest(),outcome=rows[-1]['session_outcome'],source_span_s=float(rows[-1]['source_timestamp'])-float(rows[0]['source_timestamp']),crossings=crossings,purple_accepted_onsets=purple)
        if fall:
            anchor=float(fall['fall_event_backend_timestamp']); contact=num(fall.get('edge_contact_backend_timestamp'))
            final_context=context(fall)
            candidates=[x for x in purple if x['context']==final_context and x['source_epoch']<anchor]
            last=candidates[-1] if candidates else None
            crossing_candidates=[x for x in crossings if x['context']==final_context and x['epoch_interval'][1]<=anchor]
            cross=crossing_candidates[-1] if crossing_candidates else None
            item['fall_detail']=dict(fall_epoch=anchor,edge_contact_epoch=contact,final_context=final_context,last_purple_onset=last,last_q_crossing=cross)
            if last:
                detail=item['fall_detail']; detail['purple_input_onset_to_fall_s']=anchor-last['source_epoch']
                detail['purple_input_onset_to_contact_s']=contact-last['source_epoch'] if contact is not None else None
                if cross:detail['purple_input_onset_to_qcross_interval_s']=[t-last['source_epoch'] for t in cross['epoch_interval']]
                model=[e for e in episodes if e['run_id']==run and e['channel']=='model' and e['start_local_monotonic_s']>=last['client_local_monotonic_s']]
                if model:
                    m=model[0]
                    detail['subsequent_orange_episode']=m
                    detail['orange_after_purple_onset_monotonic_s']=m['start_local_monotonic_s']-last['client_local_monotonic_s']
        inputs[run]=item

    shadow_records={run:[] for run in inputs}
    digest=hashlib.sha256()
    with SHADOW.open('rb') as f:
        for line_no,line in enumerate(f,1):
            digest.update(line)
            if not any(run.encode() in line for run in inputs):continue
            r=json.loads(line)
            if r.get('run_id') in inputs:
                r['_shadow_line']=line_no
                shadow_records[r['run_id']].append(r)
    for run,item in inputs.items():
        shadow=shadow_records[run]
        byseq=collections.defaultdict(list)
        for r in shadow:byseq[r.get('input_sequence')].append(r)
        matches=[]
        for onset in item['purple_accepted_onsets']:
            m=[r for r in byseq[onset['input_sequence']] if r.get('active') and r.get('valid') and r.get('input_source_timestamp')==onset['source_epoch'] and str(r.get('platform_instance_id'))==onset['context'][2] and r.get('geometry_version_id')==onset['context'][3]]
            matches.append(dict(input_sequence=onset['input_sequence'],active_valid_exact_match_count=len(m),shadow_lines=[r['_shadow_line'] for r in m]))
            if m:
                end=next((r for r in shadow if r['_shadow_line']>m[0]['_shadow_line'] and not r.get('active')),None)
                if end:
                    onset['first_shadow_inactive']={k:end.get(k) for k in ['_shadow_line','input_sequence','input_source_timestamp','platform_instance_id','geometry_version_id','q','outward_velocity','reason','causal_available','joint_recovery','recovery_cancelled']}
                    onset['source_active_until_inactive_s']=end['input_source_timestamp']-onset['source_epoch'] if num(end.get('input_source_timestamp')) is not None else None
        item['shadow_onset_matches']=matches
        item['shadow_records']=len(shadow)
        item['shadow_reasons']=dict(collections.Counter(r.get('reason') for r in shadow))
        if 'fall_detail' in item and item['fall_detail']['last_purple_onset']:
            onset=item['fall_detail']['last_purple_onset']['input_sequence']
            tail=[r for r in shadow if isinstance(r.get('input_sequence'),int) and r['input_sequence']>=onset]
            after=[r for r in tail if not r.get('active')]
            if after:
                r=after[0]
                item['fall_detail']['first_shadow_inactive_after_last_purple_onset']={k:r.get(k) for k in ['_shadow_line','input_sequence','input_source_timestamp','q','outward_velocity','state','reason','causal_available','joint_recovery','recovery_cancelled']}
    return dict(scope='descriptive source lead; not rendered warning lead or model acceptance',shadow_sha256=digest.hexdigest(),sessions=list(inputs.values()))

if __name__=='__main__':
    result=source_anchor_analysis()
    (HERE/'source_anchor_results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    for r in result['sessions']:
        print(r['session'],r['outcome'],'crossings',len(r['crossings']),'accepted_purple_onsets',len(r['purple_accepted_onsets']),'exact_shadow_matches',sum(bool(x['active_valid_exact_match_count']) for x in r['shadow_onset_matches']))
        if 'fall_detail' in r:print(json.dumps(r['fall_detail'],indent=2))
