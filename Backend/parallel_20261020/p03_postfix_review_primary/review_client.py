"""Read-only exact-run Player log audit; accepted states are not rendered episodes."""
import collections
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
LOG = Path('C:/Users/QIYUXUAN/AppData/LocalLow/QI YUXUAN/VectorAI/Player.log')
IDS = (
    'session_20261020_214022_086000', 'session_20261020_214100_600233',
    'session_20261020_214112_191029', 'session_20261020_214149_759405',
    'session_20261020_214210_571969', 'session_20261020_214244_551605',
    'session_20261020_214320_667777', 'session_20261020_214354_584139',
    'session_20261020_214437_062477')
CHANNELS = ('ExperimentalModelWarning', 'ExperimentalProximityWarning', 'ExperimentalGeometryWarning')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    before = {}
    sessions = {}
    for session in IDS:
        path = ROOT / 'telemetry_logs/P03' / session / 'raw.csv'
        data = path.read_bytes()
        before[str(path)] = sha(data)
        rows = list(csv.DictReader(data.decode('utf-8-sig').splitlines()))
        run_ids = {row.get('run_id') for row in rows if row.get('source') == 'unity' and row.get('run_id')}
        if len(run_ids) != 1:
            raise ValueError('Not one exact Unity run: ' + session)
        run = run_ids.pop()
        if run in sessions:
            raise ValueError('Duplicate run across sessions')
        sessions[run] = session
    log_data = LOG.read_bytes()
    before[str(LOG)] = sha(log_data)
    records, starts, errors = [], [], []
    for line_number, line in enumerate(log_data.decode('utf-8-sig', errors='replace').splitlines(), 1):
        run_match = re.search(r'\brun(?:_id)?=([A-Za-z0-9_-]+)', line)
        if not run_match or run_match[1] not in sessions:
            continue
        run = run_match[1]
        if line.startswith('[UDP] Sent start_session'):
            starts.append({'line': line_number, 'run_id': run, 'text': line})
        channel = next((name for name in CHANNELS if line.startswith('['+name+']')), None)
        if channel:
            fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
            state = fields.get('state') or line.split('] ',1)[1].split()[0].upper()
            records.append({'line': line_number, 'run_id': run, 'session_id': sessions[run],
                            'channel': channel, 'state': state.upper(), 'fields': fields, 'text': line})
        if line.startswith('[ExperimentalGeometryWarningValidation] rejected'):
            errors.append({'line':line_number, 'run_id':run, 'text':line})
    summary = []
    for run, session in sessions.items():
        summary.append({'session_id':session, 'run_id':run,
            'start_session_player_P03': any(s['run_id']==run and 'player=P03,' in s['text'] for s in starts),
            'client_state_log_counts': {name:dict(collections.Counter(
                r['state'] for r in records if r['run_id']==run and r['channel']==name)) for name in CHANNELS},
            'geometry_validation_rejections': sum(e['run_id']==run for e in errors)})
    after = {path: sha(Path(path).read_bytes()) for path in before}
    if before != after:
        raise ValueError('Inputs changed during audit; do not treat as final snapshot')
    result = {'scope':'P03 nine post-fix exact-run accepted/revoked client states, not episode/performance counts',
        'source_sha256_before':before, 'source_sha256_after':after, 'sources_unchanged':True,
        'session_count':len(summary), 'sessions':summary, 'starts':starts, 'state_records':records,
        'exact_run_geometry_validation_rejections':errors,
        'user_confirmed_same_participant':True, 'user_reported_experimental_banners_seen':True,
        'user_declared_sensitivity':0.55, 'sensitivity_measured_in_csv':False,
        'pixel_render_evidence_collected':False,
        'limitations':['Model ACTIVE may repeat for consecutive prediction sequences; do not count as episodes.',
                       'No source/monotonic/Unity clock subtraction or causal intervention claim.']}
    (OUT/'client_result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()
