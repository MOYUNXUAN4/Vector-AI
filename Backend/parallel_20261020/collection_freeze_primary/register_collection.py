"""Sidecar registration only: no runtime settings, raw files or locks are changed."""
import collections
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def classify(session, annotations):
    participant = session in annotations['participant_sessions']
    operator = session in annotations['operator_sessions']
    if participant and operator:
        raise ValueError('Conflicting participant/operator assignment: ' + session)
    if operator:
        return 'operator_technical_test', None
    if participant and session in annotations['equipment_exclusions']:
        return 'participant_equipment_excluded', annotations['participant_id']
    if participant:
        return 'participant_retained_pending_qc', annotations['participant_id']
    return 'unresolved_quarantined', None


def main():
    annotations_path = HERE / 'session_annotations.json'
    inventory_path = HERE / 'p01_inventory/output/inventory.json'
    annotations = json.loads(annotations_path.read_text(encoding='utf-8-sig'))
    inventory = json.loads(inventory_path.read_text(encoding='utf-8-sig'))
    seen = set()
    records = []
    hashes = {str(p): sha(p) for p in (annotations_path, inventory_path)}
    for item in inventory['sessions']:
        session = item['session']
        if session in seen:
            raise ValueError('Duplicate session: ' + session)
        seen.add(session)
        role, participant_id = classify(session, annotations)
        raw = next((f for f in item['files'] if Path(f['path']).name == 'raw.csv'), None)
        if raw:
            current = sha(Path(raw['path']))
            if current != raw['sha256_before'] or current != raw['sha256_after']:
                raise ValueError('Raw changed since inventory: ' + session)
        terminal = item.get('unity_terminal_row')
        input_evidence = annotations['input_mode_evidence'].get(session)
        records.append({
            'session_id': session, 'run_ids': item['run_ids'], 'role': role,
            'participant_id': participant_id, 'raw_path': item['raw_path'],
            'raw_sha256': raw['sha256_before'] if raw else None,
            'raw_rows': item['raw_rows'], 'input_mode_evidence': input_evidence,
            'input_mode_if_not_explicit': 'unknown',
            'equipment_exclusion': annotations['equipment_exclusions'].get(session),
            'unity_terminal_row': terminal, 'unity_continuity': item['unity_source'],
            'configuration_distributions_by_source': item.get('distributions_by_source'),
            'automatic_training_inclusion': False, 'automatic_performance_inclusion': False,
            'historical_condition': annotations['historical_participant_configuration'] if participant_id else None,
            'qc_disposition': 'equipment_excluded' if role == 'participant_equipment_excluded' else
                'technical_only' if role == 'operator_technical_test' else 'pending_segment_and_task_role_review'
        })
    annotated = set(annotations['participant_sessions']) | set(annotations['operator_sessions'])
    missing_annotated = sorted(annotated - seen)
    if missing_annotated:
        raise ValueError('Annotated sessions not found: ' + str(missing_annotated))
    if any(sha(Path(path)) != value for path, value in hashes.items()):
        raise ValueError('Registration inputs changed during read')
    output = {
        'schema': 1, 'snapshot_date': '2026-10-20',
        'scope': 'Purpose/identity register, not model acceptance or complete valid-window labels',
        'source_root': inventory['source_root'], 'session_count': len(records),
        'participant_count_confirmed': len({r['participant_id'] for r in records if r['participant_id']}),
        'role_counts': dict(collections.Counter(r['role'] for r in records)),
        'input_sha256': hashes, 'raw_files_rehashed_unchanged': True,
        'raw_files_moved_or_deleted': False, 'records': records
    }
    (HERE / 'P01_SESSION_REGISTER.json').write_text(json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')
    for role, name in (
        ('participant_retained_pending_qc', 'P01_RETAINED_PENDING_QC_IDS.txt'),
        ('participant_equipment_excluded', 'P01_EQUIPMENT_EXCLUDED_IDS.txt'),
        ('operator_technical_test', 'P01_OPERATOR_TEST_IDS.txt'),
        ('unresolved_quarantined', 'P01_UNRESOLVED_IDS.txt')):
        ids = [r['session_id'] for r in records if r['role'] == role]
        (HERE / name).write_text(''.join(s+'\n' for s in ids), encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k in ('session_count','participant_count_confirmed','role_counts','raw_files_rehashed_unchanged')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
