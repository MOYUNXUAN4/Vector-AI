"""Boundary fixtures for the v7 package.

Two sections, both read-only and both confined to an isolated temporary CSV:

  1. the 2026-10-20 v5-review fixtures, re-pointed at the v7 tools with no
     change to their bodies, so the printout is a direct before/after against
     the v5 and v6 runs;
  2. the 2026-10-20 v6-review terminal-identity counterexample, plus the two
     independent variants the review asked for (blank run_id, blank sequence)
     and one fractional-sequence variant.

Expected: section 1 keeps the v6 labels; section 2 is
TERMINAL_ROW_IDENTITY_UNRESOLVED / unavailable in every case, and never
corroborated.
"""
import csv
import datetime
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


w = load('boundary_wii', 'patch_5_wii_preflight/wii_cop_preflight_v6.py')
c = load('boundary_closure', 'tools/session_closure_audit_v7.py')

with tempfile.TemporaryDirectory(prefix='v7_boundary_') as td:
    path = Path(td) / 'raw.csv'

    def write(rows):
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, sorted(set().union(*(r.keys() for r in rows))))
            writer.writeheader()
            writer.writerows(rows)

    # --- 1. the v5-review fixtures, unchanged ------------------------------
    rows = []
    for i in range(50):
        src = 1_700_000_000 + i * .02 + (1 if i >= 25 else 0)
        rows.append(dict(
            source='wii', backend_timestamp=str(1_700_000_002 + i * .001),
            source_timestamp=datetime.datetime.fromtimestamp(src, datetime.timezone.utc).isoformat(),
            sequence=str(i + 1), wii_control_sequence=str(i + 1), total_weight='80',
            cop_x='0', cop_z='0', wii_control_valid='true', wii_board_loaded='true',
            wii_center_applied='true', wii_control_age_seconds='.01',
            wii_center_generation='1', wii_controller_instance_id='board-a'))
    write(rows)
    r = w.audit(str(path))
    print('source_gap_1020ms_receive_continuous', r['verdict'], 'reported_duration', r.get('window_duration_s'))
    for row in rows:
        row['backend_timestamp'] = 'inf'
    write(rows)
    r = w.audit(str(path))
    print('nonfinite_timestamp', r['verdict'], 'reported_duration', r.get('window_duration_s'))
    write([dict(source='unity', backend_timestamp='100', sequence='10', run_id='r1',
                run_state='ended', session_outcome='edge_exit')])
    for label, diag in [('new_run_lifecycle_only', {'files': ['samples.jsonl'], 'last_sample_ts': 1.}),
                        ('incomplete_terminal', {'files': ['samples.jsonl'],
                                                 'terminal_outcome': 'edge_exit', 'terminal_seq': 10})]:
        r = c.audit_session(td, {'r1': diag})
        print(label, r['verdict'], r['terminal_evidence'], 'send_completed', r.get('diag_send_completed'))

    # --- 2. the v6-review terminal-identity fixtures -----------------------
    running = dict(source='unity', backend_timestamp='100', sequence='10',
                   run_id='r1', run_state='running', session_outcome='')
    diag = {'r1': dict(terminal_present=True, terminal_seq=10, terminal_outcome='edge_exit',
                       terminal_send_completed=True)}

    def terminal(rows):
        write(rows)
        r = c.audit_session(td, diag)
        return '%s evidence=%s run_id=%r term_seq=%r defect=%s span=%s' % (
            r['verdict'], r.get('terminal_evidence'), r.get('run_id'),
            r.get('terminal_row_sequence'), r.get('identity_defect'),
            r.get('unpersisted_sequence_span'))

    blank = dict(source='unity', backend_timestamp='100.02', sequence='',
                 run_id='', run_state='ended', session_outcome='edge_exit')
    print('terminal_identity_inherited      ', terminal([running, blank]))
    print('terminal_identity_blank_run_id   ', terminal([running, dict(blank, sequence='11')]))
    print('terminal_identity_blank_sequence ', terminal([running, dict(blank, run_id='r1')]))
    print('terminal_identity_fractional_seq ', terminal([running, dict(blank, run_id='r1', sequence='10.7')]))
    print('terminal_identity_healthy        ', terminal([running, dict(blank, run_id='r1', sequence='10')]))
