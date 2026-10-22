from pathlib import Path
import pandas as pd, numpy as np, json
import matplotlib.pyplot as plt

ROOT = Path(r'C:/Users/QIYUXUAN/Desktop/fyp_Backend (3)/fyp_Backend/telemetry_logs/TEST922')
LABELS = {
'session_20260922_134208_171926':('normal','near rear edge, completed'), 'session_20260922_134711_827508':('normal','completed'), 'session_20260922_135035_982972':('normal','completed'),
'session_20260922_135325_344571':('ambiguous','reported warning after initial fall; later edge exit'), 'session_20260922_135723_905790':('normal','completed'), 'session_20260922_140024_769006':('recovery','warning and recovered'),
'session_20260922_140839_992480':('normal','near rear edge, completed'), 'session_20260922_141144_788744':('edge_exit','yellow then red, forward'), 'session_20260922_142048_895193':('edge_exit','yellow then red, left'),
'session_20260922_142228_141511':('recovery','forward offset and recovery'), 'session_20260922_143740_750957':('unknown','no operator description'), 'session_20260922_144323_896766':('recovery','left offset and recovery'),
'session_20260922_145004_049520':('recovery','right offset and recovery'), 'session_20260922_145823_485525':('edge_exit','backward, no noticeable yellow'), 'session_20260922_150015_684346':('recovery','repeated offset and recovery; duplicate description'),
'session_20260922_150452_620987':('unknown','no operator description'), 'session_20260922_151016_119161':('recovery','left offset and recovery'), 'session_20260922_151800_216849':('recovery','right offset and recovery'),
'session_20260922_152729_759806':('edge_exit','backward'), 'session_20260922_153004_962293':('recovery','backward offset and recovery'), 'session_20260922_154445_096248':('edge_exit','forward with yellow'),
'session_20260922_155353_441200':('edge_exit','left'), 'session_20260922_160031_148438':('edge_exit','right')}

def num(s): return pd.to_numeric(s, errors='coerce')
def summarize(path):
    raw=pd.read_csv(path/'raw.csv',low_memory=False); u=raw[raw.source.eq('unity')].copy()
    for c in ['backend_timestamp','directional_edge_distance','target_edge_radial_velocity','edge_warning_distance_threshold','platform_radius','active_platform_difficulty','passed_count']:
        u[c]=num(u[c])
    u['fall']=u.fall_event.fillna(False).astype(bool); u['warning']=u.edge_warning_state.fillna(False).astype(bool)
    et=float(u.loc[u.fall,'backend_timestamp'].min()) if u.fall.any() else np.inf; pre=u[u.backend_timestamp<=et] if np.isfinite(et) else u
    w=pre[pre.warning]; ft=float(w.backend_timestamp.min()) if len(w) else np.nan; lt=float(w.backend_timestamp.max()) if len(w) else np.nan
    grp,note=LABELS.get(path.name,('unknown',''))
    return {'session_id':path.name,'operator_group':grp,'operator_note':note,'raw_rows':len(raw),'unity_rows':len(u),'run_id_count':u.run_id.dropna().nunique(),'session_outcome':';'.join(map(str,u.session_outcome.dropna().unique())),'fall_event_count':int(u.fall.sum()),'fall_direction':';'.join(map(str,u.loc[u.fall,'fall_direction'].dropna().unique())),'event_backend_timestamp':None if not np.isfinite(et) else et,'warning_rows_before_event':len(w),'first_warning_backend_timestamp':ft,'last_warning_backend_timestamp':lt,'warning_duration_seconds':lt-ft if np.isfinite(ft) else np.nan,'warning_lead_seconds':et-ft if np.isfinite(et) and np.isfinite(ft) else np.nan,'min_directional_edge_distance':pre.directional_edge_distance.min(),'max_target_edge_radial_velocity':pre.target_edge_radial_velocity.max(),'warning_threshold_median':pre.edge_warning_distance_threshold.median(),'difficulty_min':pre.active_platform_difficulty.min(),'difficulty_max':pre.active_platform_difficulty.max(),'platform_radius_min':pre.platform_radius.min(),'platform_radius_max':pre.platform_radius.max(),'passed_count_at_end':pre.passed_count.dropna().iloc[-1] if pre.passed_count.notna().any() else np.nan,'post_event_unity_rows':int((u.backend_timestamp>et).sum()) if np.isfinite(et) else 0}

def main():
    detail=pd.DataFrame([summarize(p) for p in sorted(ROOT.glob('session_*'))]); detail.to_csv(ROOT/'TEST922_session_audit.csv',index=False,encoding='utf-8-sig')
    sens=[]
    for th in [1,1.25,1.5,2,2.5,3]:
        ex=[]; co=[]
        for p in sorted(ROOT.glob('session_*')):
            u=pd.read_csv(p/'raw.csv',low_memory=False); u=u[u.source.eq('unity')].copy(); u['ts']=num(u.backend_timestamp); u['edge']=num(u.directional_edge_distance); ev=u.loc[u.fall_event.fillna(False).astype(bool),'ts']; et=float(ev.min()) if len(ev) else np.inf; hit=u.loc[u.ts.le(et)&u.edge.le(th),'ts']; x=(len(hit)>0,(et-float(hit.min())) if len(hit) and np.isfinite(et) else np.nan); (ex if detail.loc[detail.session_id.eq(p.name),'session_outcome'].eq('edge_exit').any() else co).append(x)
        ex=pd.DataFrame(ex,columns=['hit','lead']); co=pd.DataFrame(co,columns=['hit','lead']); sens.append({'geometric_threshold':th,'edge_exit_detection_rate':ex.hit.mean(),'edge_exit_n':len(ex),'median_lead_seconds':ex.lead.median(),'completed_session_false_alarm_rate':co.hit.mean(),'completed_n':len(co)})
    pd.DataFrame(sens).to_csv(ROOT/'TEST922_threshold_sensitivity.csv',index=False,encoding='utf-8-sig')
    report={'session_count':len(detail),'operator_labeled_count':int((detail.operator_group!='unknown').sum()),'telemetry_edge_exit_count':int((detail.session_outcome=='edge_exit').sum()),'telemetry_completed_count':int((detail.session_outcome=='completed').sum()),'all_edge_exits_have_warning_before_event':bool(detail.loc[detail.session_outcome=='edge_exit','warning_rows_before_event'].gt(0).all()),'median_edge_exit_warning_lead_seconds':float(detail.loc[detail.session_outcome=='edge_exit','warning_lead_seconds'].median()),'edge_exits_with_warning_lead_under_0_5s':int(detail.loc[detail.session_outcome=='edge_exit','warning_lead_seconds'].lt(.5).sum()),'post_event_rows_total':int(detail.post_event_unity_rows.sum()),'threshold_sensitivity':sens}
    (ROOT/'TEST922_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))
    plot_diagnostics(detail)

def plot_diagnostics(detail):
    exits=detail[detail.session_outcome.eq('edge_exit')].sort_values('warning_lead_seconds').copy()
    fig,ax=plt.subplots(1,2,figsize=(11,4.2),constrained_layout=True)
    labels=[x.replace('session_20260922_','') for x in exits.session_id]
    colors=['#c23b32' if x<.5 else '#1f6f8b' for x in exits.warning_lead_seconds]
    ax[0].barh(labels,exits.warning_lead_seconds,color=colors)
    ax[0].axvline(.5,color='#555',lw=1,ls='--'); ax[0].set_xlabel('First warning lead (s)'); ax[0].set_title('Edge-exit warning lead')
    groups=['completed','edge_exit']; data=[detail.loc[detail.session_outcome.eq(g),'min_directional_edge_distance'].dropna() for g in groups]
    ax[1].boxplot(data,tick_labels=['Completed','Edge exit'],showmeans=True); ax[1].axhline(1.0,color='#c23b32',lw=1,ls='--',label='Current threshold = 1.0')
    ax[1].set_ylabel('Minimum directional edge distance (world units)'); ax[1].set_title('Closest approach by outcome'); ax[1].legend(frameon=False,fontsize=8)
    for a in ax: a.spines[['top','right']].set_visible(False); a.grid(axis='x',alpha=.25)
    fig.suptitle('TEST922 telemetry audit',fontsize=13)
    fig.savefig(ROOT/'TEST922_warning_diagnostics.png',dpi=300,bbox_inches='tight'); fig.savefig(ROOT/'TEST922_warning_diagnostics.pdf',bbox_inches='tight'); plt.close(fig)
if __name__=='__main__': main()
