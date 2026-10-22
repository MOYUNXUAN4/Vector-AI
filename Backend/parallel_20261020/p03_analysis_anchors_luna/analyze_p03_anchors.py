"""Read-only P03 post-fix source/geometry/event anchor audit. No model metrics."""
import csv, hashlib, json, math
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
RECEIPT = BACKEND / 'parallel_20261020/p03_postfix_review_primary/CONDITION_RECEIPT.json'
DATA = BACKEND / 'telemetry_logs/P03'

def n(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError): return None
def b(v): return str(v).strip().lower() == 'true'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(r): return tuple(r.get(k,'') for k in ('run_id','layer_id','geometry_platform_instance_id','geometry_version_id'))
def qval(r):
    d,rad=n(r.get('directional_edge_distance')),n(r.get('ball_radius'))
    return d-2*rad if d is not None and rad is not None else None
def epoch_iso(s):
    try: return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
    except (ValueError,AttributeError): return None
def eligible_crossing(a, c):
    """Strict adjacent source-row q bracket; missing time/flag blocks interpolation."""
    ta,tc=n(a.get('source_timestamp')),n(c.get('source_timestamp'))
    if ta is None or tc is None: return None
    dt=tc-ta
    qa,qc=qval(a),qval(c)
    good=all(b(x.get(k)) for x in (a,c) for k in ('directional_edge_valid','geometry_query_valid','geometry_ownership_valid'))
    if qa is not None and qc is not None and qa>0>=qc and ident(a)==ident(c) and int(c['sequence'])==int(a['sequence'])+1 and 0<dt<=.1 and good:
        return {'q_lastpositive':qa,'q_firstnonpositive':qc,'bracket_source_dt_s':dt}
    return None
def valid_fall_anchor(r):
    t=n(r.get('fall_event_backend_timestamp'))
    return b(r.get('fall_event')) and t is not None and t>0
def wii_partition_stats(records):
    fields=('wii_board_loaded','wii_center_applied','wii_control_valid')
    out={'records':len(records),'field_counts':{}}
    for k in fields:
        vals=[str(r.get(k,'')).strip().lower() for r in records]
        out['field_counts'][k]={'present':sum(v not in ('','nan','none') for v in vals),'true':sum(v=='true' for v in vals),'false':sum(v=='false' for v in vals),'missing':sum(v in ('','nan','none') for v in vals)}
    return out

def analyze():
    receipt=json.loads(RECEIPT.read_text(encoding='utf-8'))
    sessions=[]; hashes={}
    for sid in receipt['session_ids']:
        p=DATA/sid/'raw.csv'; before=sha(p)
        with p.open(encoding='utf-8-sig',newline='') as f: allrows=list(csv.DictReader(f))
        after=sha(p); hashes[sid]={'before':before,'after':after,'stable':before==after}
        unity=[(i+2,r) for i,r in enumerate(allrows) if r.get('source')=='unity']
        wii=[(i+2,r) for i,r in enumerate(allrows) if r.get('source')=='wii']
        if not unity: raise ValueError('No Unity rows: '+sid)
        runs={r.get('run_id') for _,r in unity}
        if len(runs)!=1: raise ValueError('Expected exactly one run per session: '+sid)
        run=next(iter(runs)); seqs=[int(r['sequence']) for _,r in unity]
        gaps=[]
        for (la,a),(lb,c) in zip(unity,unity[1:]):
            ds=int(c['sequence'])-int(a['sequence'])
            ta,tc=n(a.get('source_timestamp')),n(c.get('source_timestamp'))
            dt=tc-ta if ta is not None and tc is not None else None
            if ds!=1 or dt is None or dt<=0 or dt>.1: gaps.append({'csv_lines':[la,lb],'sequence_delta':ds,'source_dt_s':dt})
        def ranges(vals):
            vals=sorted(set(vals)); out=[]
            for x in vals:
                if not out or x>out[-1][-1]+1: out.append([x,x])
                else: out[-1][-1]=x
            return out
        by_layer={}
        for line,r in unity: by_layer.setdefault((r.get('platform_level',''),r.get('layer_id','')),[]).append((line,r))
        layer_stats=[]
        for (platform,layer),rs in by_layer.items():
            flags={k:sum(b(r.get(k)) for _,r in rs) for k in ('directional_edge_valid','geometry_query_valid','geometry_ownership_valid')}
            flags['all_three_valid']=sum(all(b(r.get(k)) for k in ('directional_edge_valid','geometry_query_valid','geometry_ownership_valid')) and qval(r) is not None for _,r in rs)
            for field in ('directional_edge_valid','geometry_query_valid','geometry_ownership_valid'):
                vals=[str(r.get(field,'')).strip().lower() for _,r in rs]
                flags[field+'_false']=sum(v=='false' for v in vals)
                flags[field+'_missing']=sum(v not in ('true','false') for v in vals)
            layer_stats.append({'platform_level':platform,'layer_id':layer,'rows':len(rs),'sequence_ranges':ranges([int(r['sequence']) for _,r in rs]),'geometry_flag_true_counts':flags,
             'identity_pairs_match_counts':{'platform_instance_vs_active':sum(r.get('geometry_platform_instance_id')==r.get('geometry_active_platform_instance_id') for _,r in rs),'version_vs_active':sum(r.get('geometry_version_id')==r.get('geometry_active_version_id') for _,r in rs)},
             'query_age':{'status':'unavailable: no Unity-time field co-domain with geometry_source_timestamp was found; source_timestamp is Unix epoch while geometry_source_timestamp is Unity-relative'},
             'geometry_source_timestamp_range':([min(x for _,r in rs if (x:=n(r.get('geometry_source_timestamp'))) is not None),max(x for _,r in rs if (x:=n(r.get('geometry_source_timestamp'))) is not None)] if any(n(r.get('geometry_source_timestamp')) is not None for _,r in rs) else None)})
        # Establish observed Wii-source time overlap with run span from backend epoch. This is contextual only.
        run_start=n(unity[0][1].get('source_timestamp')); run_end=n(unity[-1][1].get('source_timestamp'))
        wii_epochs=[epoch_iso(r.get('source_timestamp')) for _,r in wii]
        timed_wii=[(pair[0],pair[1],ts) for pair,ts in zip(wii,wii_epochs) if ts is not None]
        overlap_rows=[(line,r,ts) for line,r,ts in timed_wii if run_start is not None and run_end is not None and run_start<=ts<=run_end]
        outside_rows=[(line,r,ts) for line,r,ts in timed_wii if not (run_start is not None and run_end is not None and run_start<=ts<=run_end)]
        overlap=[ts for _,_,ts in overlap_rows]
        # q crossings only between adjacent Unity rows with stable identity, valid flags, and bounded contiguous source gap.
        crossings=[]
        for (la,a),(lb,c) in zip(unity,unity[1:]):
            bracket=eligible_crossing(a,c)
            if bracket:
                crossings.append({'lastpositive':{'csv_line':la,'sequence':int(a['sequence']),'source_timestamp':a['source_timestamp'],'q':bracket['q_lastpositive'],'fall_event':b(a.get('fall_event')),'fall_event_backend_timestamp':a.get('fall_event_backend_timestamp'),'edge_contact_backend_timestamp':a.get('edge_contact_backend_timestamp')},
                 'firstnonpositive':{'csv_line':lb,'sequence':int(c['sequence']),'source_timestamp':c['source_timestamp'],'q':bracket['q_firstnonpositive'],'fall_event':b(c.get('fall_event')),'fall_event_backend_timestamp':c.get('fall_event_backend_timestamp'),'edge_contact_backend_timestamp':c.get('edge_contact_backend_timestamp')},'context':dict(run_id=c.get('run_id'),platform_level=c.get('platform_level'),layer_id=c.get('layer_id'),platform_instance_id=c.get('geometry_platform_instance_id'),geometry_version_id=c.get('geometry_version_id')),'bracket_source_dt_s':bracket['bracket_source_dt_s']})
        falls=[]
        for line,r in unity:
            if valid_fall_anchor(r):
                falls.append({'csv_line':line,'sequence':int(r['sequence']),'fall_event_backend_timestamp':r.get('fall_event_backend_timestamp'),'source_timestamp':r.get('source_timestamp'),'platform_level':r.get('platform_level'),'layer_id':r.get('layer_id'),'platform_instance_id':r.get('geometry_platform_instance_id'),'geometry_version_id':r.get('geometry_version_id'),'q':qval(r),'edge_contact_backend_timestamp':r.get('edge_contact_backend_timestamp'),'support_lost_backend_timestamp':r.get('support_lost_backend_timestamp')})
        # C# FallEventBackendTimestamp is sourced from DateTimeOffset.UtcNow Unix seconds.
        # Compare that UTC event instant directly with Unity source_timestamp (also UTC epoch).
        # Do not use backend receive timestamp or estimate/apply a global clock offset.
        for fall in falls:
            ft=n(fall['fall_event_backend_timestamp']); ctx=(run,fall['layer_id'],fall['platform_instance_id'],fall['geometry_version_id'])
            fall['nearest_same_context_q_cross_bracket_before_or_at_fall_utc_source_time']=None
            if ft is not None:
                cs=[]
                for c in crossings:
                    if (c['context']['run_id'],c['context']['layer_id'],c['context']['platform_instance_id'],c['context']['geometry_version_id'])!=ctx: continue
                    ta,tb=n(c['lastpositive']['source_timestamp']),n(c['firstnonpositive']['source_timestamp'])
                    if ta is not None and tb is not None and ta<=ft: cs.append(c)
                if cs: fall['nearest_same_context_q_cross_bracket_before_or_at_fall_utc_source_time']=cs[-1]
        scale_values=[n(r.get('platform_scale')) for _,r in unity if n(r.get('platform_scale')) is not None]
        prep=[(line,r) for line,r in unity if (n(r.get('platform_scale')) or 0)>2]
        sessions.append({'session_id':sid,'run_id':run,'rows_total':len(allrows),'unity_rows':len(unity),'wii_rows':len(wii),'unity_sequence_range':[min(seqs),max(seqs)],'unity_source_timestamp_range_epoch':[run_start,run_end],'unity_seq_or_source_gap_pairs_over_100ms_or_nonmonotonic':gaps,'scale_gt_2_preparation_segment':{'row_count':len(prep),'sequence_ranges':ranges([int(r['sequence']) for _,r in prep]),'platform_level_values':sorted(set(r.get('platform_level','') for _,r in prep)),'platform_scale_min_max':[min([n(r.get('platform_scale')) for _,r in prep if n(r.get('platform_scale')) is not None]),max([n(r.get('platform_scale')) for _,r in prep if n(r.get('platform_scale')) is not None])] if any(n(r.get('platform_scale')) is not None for _,r in prep) else None,'note':'Preparation observations are reported separately and not folded into gameplay summaries.'},'platform_scale_min_max_all_unity':[min(scale_values),max(scale_values)] if scale_values else None,'run_layer_contexts':layer_stats,'wii_observation_during_unity_runtime':{'interpretation':'conditional time overlap only; not evidence of exact control application','wii_source_timestamp_utc_range':[datetime.fromtimestamp(min(ts for _,_,ts in timed_wii),tz=__import__('datetime').timezone.utc).isoformat().replace('+00:00','Z'),datetime.fromtimestamp(max(ts for _,_,ts in timed_wii),tz=__import__('datetime').timezone.utc).isoformat().replace('+00:00','Z')] if timed_wii else None,'records_with_source_time_inside_unity_epoch_span':len(overlap_rows),'unity_run_overlap_epoch_s':[max(run_start,min(overlap)),min(run_end,max(overlap))] if overlap else None,'actual_wii_fields_overlap_only':wii_partition_stats([r for _,r,_ in overlap_rows]),'actual_wii_fields_outside_or_unavailable_time':{'outside_run_time':wii_partition_stats([r for _,r,_ in outside_rows]),'missing_or_invalid_source_time_rows':len(wii)-len(timed_wii)},'note':'Wii source_timestamp is UTC; overlap with Unity epoch range is conditional context only, not proof of exact control application.'},'q_crossings':crossings,'finalfall_rows':falls,'q_interpretation':'q=directional_edge_distance-2*ball_radius is a geometry-derived bracket; q=0 is not asserted as actual fall/edge exit.'})
    shadow=BACKEND/'telemetry_logs/proximity_shadow.jsonl'; sb=sha(shadow)
    out={'scope':'P03 post-fix nine sessions in CONDITION_RECEIPT only; source/geometry/event anchors, no model loading, no F1, no label edits','session_ids_from_receipt':receipt['session_ids'],'fix_version':receipt['fix_version'],'source_sha256':hashes,'shared_proximity_shadow_sha256':sb,'all_source_hashes_stable':all(x['stable'] for x in hashes.values()),'clock_policy':'Source timestamps preserved in their native representation. No global clock offset is applied. Unity source epoch timestamps and Wii UTC source timestamps are compared only for conditional runtime overlap. geometry_source_timestamp is not subtracted from Unix epoch source_timestamp. C# FallEventBackendTimestamp is assigned from DateTimeOffset.UtcNow Unix time and compared with Unity source_timestamp UTC epoch; backend receive time is not substituted.','sessions':sessions}
    return out
if __name__=='__main__':
    result=analyze(); (HERE/'p03_anchor_quality.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print('sessions',len(result['sessions']),'stable hashes',result['all_source_hashes_stable'])
    for s in result['sessions']: print(s['session_id'],s['run_id'],'unity',s['unity_rows'],'layers',len(s['run_layer_contexts']),'qcross',len(s['q_crossings']),'fall events',len(s['finalfall_rows']))
