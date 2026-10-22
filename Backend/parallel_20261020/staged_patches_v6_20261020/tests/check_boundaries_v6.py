"""The 2026-10-20 v5-review boundary fixtures, re-pointed at the v6 package.

This is `staged_v5_review/check_boundaries.py` with exactly two changes:
  * ROOT now resolves to ../staged_patches_v6_20261020
  * the module filenames are the v6 ones
No fixture, assertion or print statement was altered, so the output is a direct
before/after comparison against the v5 run. It only creates and removes an
isolated temporary CSV.
"""
import csv
import datetime
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(name,relative):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m
w=load('boundary_wii','patch_5_wii_preflight/wii_cop_preflight_v6.py')
c=load('boundary_closure','tools/session_closure_audit_v6.py')
with tempfile.TemporaryDirectory(prefix='v6_boundary_') as td:
    path=Path(td)/'raw.csv'
    def write(rows):
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,sorted(set().union(*(r.keys() for r in rows))))
            writer.writeheader();writer.writerows(rows)
    rows=[]
    for i in range(50):
        src=1_700_000_000+i*.02+(1 if i>=25 else 0)
        rows.append(dict(source='wii',backend_timestamp=str(1_700_000_002+i*.001),
            source_timestamp=datetime.datetime.fromtimestamp(src,datetime.timezone.utc).isoformat(),
            sequence=str(i+1),wii_control_sequence=str(i+1),total_weight='80',cop_x='0',cop_z='0',
            wii_control_valid='true',wii_board_loaded='true',wii_center_applied='true',
            wii_control_age_seconds='.01',wii_center_generation='1',wii_controller_instance_id='board-a'))
    write(rows)
    r=w.audit(str(path))
    print('source_gap_1020ms_receive_continuous',r['verdict'],'reported_duration',r.get('window_duration_s'))
    for row in rows:row['backend_timestamp']='inf'
    write(rows)
    r=w.audit(str(path))
    print('nonfinite_timestamp',r['verdict'],'reported_duration',r.get('window_duration_s'))
    write([dict(source='unity',backend_timestamp='100',sequence='10',run_id='r1',run_state='ended',session_outcome='edge_exit')])
    for label,diag in [('new_run_lifecycle_only',{'files':['samples.jsonl'],'last_sample_ts':1.}),
                       ('incomplete_terminal',{'files':['samples.jsonl'],'terminal_outcome':'edge_exit','terminal_seq':10})]:
        r=c.audit_session(td,{'r1':diag})
        print(label,r['verdict'],r['terminal_evidence'],'send_completed',r.get('diag_send_completed'))
