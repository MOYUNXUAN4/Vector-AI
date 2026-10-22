"""Read-only lifecycle/terminal reconciliation for the eight acceptance runs."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'telemetry_logs' / '1012TEST'
DIAG = Path('C:/Users/QIYUXUAN/AppData/LocalLow/QI YUXUAN/VectorAI/EndlessFallingDiagnostics')
sessions = {}
for path in sorted(DATA.glob('session_*/raw.csv')):
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['source'] == 'unity']
    owners = {r['run_id'] for r in rows if r['run_id']}
    assert len(owners) == 1, (path, owners)
    rid = next(iter(owners))
    sessions[rid] = {'session_id': path.parent.name, 'run_id': rid,
                     'unity_rows': len(rows), 'last_sequence': int(rows[-1]['sequence']),
                     'csv_last_state': rows[-1]['run_state'],
                     'csv_last_outcome': rows[-1]['session_outcome'],
                     'csv_layers': sorted({r['platform_level'] for r in rows}),
                     'lifecycle': [], 'diagnostic_files': [], 'event_names': Counter()}
    sessions[rid]['source_gaps_over_0_1s'] = [
        {'seconds': float(b['source_timestamp']) - float(a['source_timestamp']),
         'sequence_before': a['sequence'], 'sequence_after': b['sequence'],
         'layer_before': a['platform_level'], 'layer_after': b['platform_level'],
         'state_before': a['run_state'], 'state_after': b['run_state'],
         'time_after': b['source_timestamp']}
        for a, b in zip(rows, rows[1:])
        if float(b['source_timestamp']) - float(a['source_timestamp']) > .1]

for path in sorted(DIAG.glob('samples_20261012_*.jsonl')):
    seen = set()
    with path.open(encoding='utf-8-sig') as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            rid = record.get('run_id')
            if rid not in sessions:
                continue
            s = sessions[rid]
            seen.add(rid)
            name = record.get('lifecycle_event') or record.get('event_name')
            if name:
                s['event_names'][name] += 1
            if record.get('record_type') == 'lifecycle':
                event = {k: record.get(k) for k in ('lifecycle_event', 'sequence', 'backend_timestamp',
                                                   'run_state', 'session_outcome', 'detail')}
                event['line'] = lineno
                if record.get('payload_json'):
                    packet = json.loads(record['payload_json'])
                    event['terminal_packet_sequence'] = packet.get('sequence')
                    event['terminal_packet_outcome'] = packet.get('session_outcome')
                    event['terminal_packet_layer'] = packet.get('platformLevel')
                s['lifecycle'].append(event)
    for rid in seen:
        sessions[rid]['diagnostic_files'].append(str(path))

if __name__ == '__main__':
    print(json.dumps(list(sessions.values()), indent=2, allow_nan=False))
