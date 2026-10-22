"""Malformed diagnostic-sequence boundary in isolated temporary CSV."""
import csv
import importlib.util
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'staged_patches_v7_20261020'
spec=importlib.util.spec_from_file_location('v7_diag_sequence',root/'tools/session_closure_audit_v7.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix='v7_diag_seq_') as directory:
    with (Path(directory)/'raw.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,['source','backend_timestamp','sequence','run_id','run_state','session_outcome'])
        writer.writeheader();writer.writerow(dict(source='unity',backend_timestamp='100',sequence='10',run_id='r1',run_state='ended',session_outcome='edge_exit'))
    for value in [10,None,'10','bad',10.5]:
        try:
            r=module.audit_session(directory,{'r1':dict(terminal_present=True,terminal_seq=value,terminal_outcome='edge_exit',terminal_send_completed=True)})
            print(repr(value),'->',r['verdict'],r['terminal_evidence'])
        except Exception as error:
            print(repr(value),'->',type(error).__name__,str(error))
