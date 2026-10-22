"""Read-only v6 terminal-row identity boundary; temporary fixture only."""
import csv
import importlib.util
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'staged_patches_v6_20261020'
spec=importlib.util.spec_from_file_location('v6_identity',root/'tools/session_closure_audit_v6.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix='v6_terminal_identity_') as temp:
    path=Path(temp)/'raw.csv'
    fields=['source','backend_timestamp','sequence','run_id','run_state','session_outcome']
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fields);writer.writeheader()
        writer.writerow(dict(source='unity',backend_timestamp='100',sequence='10',run_id='r1',run_state='running',session_outcome=''))
        writer.writerow(dict(source='unity',backend_timestamp='100.02',sequence='',run_id='',run_state='ended',session_outcome='edge_exit'))
    result=module.audit_session(temp,{'r1':dict(terminal_present=True,terminal_seq=10,terminal_outcome='edge_exit',terminal_send_completed=True)})
    print({key:result.get(key) for key in ['verdict','terminal_evidence','run_id','last_seq','unpersisted_sequence_span']})
    print('Actual final CSV row has blank run_id and sequence; values above were inherited from preceding running row.')
