"""Additional counterexamples; source package and Unity remain untouched."""
import csv
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'staged_patches_v3_20261020'
def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

w = load('remaining_wii', 'patch_5_wii_preflight/wii_cop_preflight_v4.py')
c = load('remaining_closure', 'tools/session_closure_audit_v4.py')
p = load('remaining_profile', 'patch_4_clock_profile/receive_latency_profile_v4.py')
e = load('remaining_episodes', 'patch_3_warning_episodes/cluster_warning_episodes_v4.py')

with tempfile.TemporaryDirectory(prefix='v4_review_') as temp:
    path = Path(temp)/'raw.csv'
    def write_rows(rows):
        fields = sorted(set().union(*(r.keys() for r in rows)))
        with path.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fields)
            writer.writeheader()
            writer.writerows(rows)
    rows = [dict(source='wii',backend_timestamp=str(100+i*.02),total_weight='80',cop_x='0',cop_z='0') for i in range(60)]
    write_rows(rows)
    result = w.audit(str(path))
    print('missing_board_flags',result['verdict'],result['flag_columns_present'])
    for i, r in enumerate(rows):
        r.update(backend_timestamp=str(100-i*.02),wii_control_valid='true',wii_board_loaded='true',wii_center_applied='true',wii_control_age_seconds='.01',wii_center_generation='1',wii_controller_instance_id='board-a')
    write_rows(rows)
    result=w.audit(str(path))
    print('reversed_clock',result['verdict'],'duration',result.get('window_duration_s'))

    write_rows([dict(source='unity', backend_timestamp='100',sequence='10',run_id='r1',run_state='ended',session_outcome='edge_exit')])
    result=c.audit_session(temp,{'r1':dict(terminal_seq=20,terminal_outcome='user_exit',terminal_send_completed=True)})
    print('contradictory_terminal',result['verdict'],'outcome_match',result.get('outcome_match'),'unpersisted',result.get('unpersisted_sequence_span'))

src=[1_700_000_000+i*.02 for i in range(240)]
geom=[i*.02-i*.001 for i in range(240)]
result=p.analyse_arrays(src,[t+.005 for t in src],geom)
d=result['unity_dual_clock_stats']
print('239ms_gradual_dual_clock_drift','spread_ms',d['detrended_spread_ms'],'global_offset_sufficient',d['single_global_offset_sufficient'])

base=dict(source_timestamp='10',sequence='10',warning_active='true',warning_source='attention',run_id='a',platform_level='1',layer_id='1',geometry_platform_instance_id='-1',geometry_version_id='-1-g1')
other=dict(base,source_timestamp='10.02',sequence='11',geometry_platform_instance_id='-2',geometry_version_id='-2-g2')
print('same_layer_platform_swap_groups',len(e.group_episodes([base,other])))
back=dict(base,source_timestamp='9.98',sequence='9')
print('time_sequence_reversal_groups',len(e.group_episodes([base,back])))

backend = ROOT.parents[1]
real = p.analyse(str(backend/'telemetry_logs/P01/session_20261019_161529_760840/raw.csv'))
d=real['unity_dual_clock_stats']
print('real_161529','receive_step',real['step_detected'],'spike_ms',real['max_within_segment_spike_ms'],'dual_jumps',len(d['discrete_jumps']),'jump_sum_ms',d['cumulative_drift_ms'])
total=0
for raw in sorted((backend/'telemetry_logs/P02').glob('*/raw.csv')):
    kept,short=e.episodes_for_session(str(raw),.5,0.)
    total+=len(kept)+len(short)
print('P02_descriptive_groups',total)
