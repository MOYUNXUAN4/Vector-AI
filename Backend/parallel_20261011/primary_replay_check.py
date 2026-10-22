"""Independent review of replay identities and causal features; no model tuning."""
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'stream_replay'))
import replay_real_data as replay

Runtime, compute = replay.load_runtime()
_, ids, manifest, prepared, hashes, files = replay.load_sources()
expected = {replay.feature_identity(row): row for row in prepared}
checks = []
for sid in (ids[0], ids[-1]):
    rt = Runtime(allow_calibration_session_gameplay=True)
    assert rt.load(replay.MANIFEST, replay.PINNED_HASH, allow_experimental=True)
    rt.enable()
    rt.begin_run(manifest[sid]['run_id'])
    before = replay.sha256(files[sid])
    matched = 0
    first_receipt = None
    with files[sid].open(encoding='utf-8-sig', newline='') as f:
        for raw in csv.DictReader(f):
            if raw['source'] != 'unity':
                continue
            receipt = float(raw['backend_timestamp'])
            if first_receipt is None:
                first_receipt = receipt
            receipt -= first_receipt
            packet = replay.inverse_logger_mapping(raw)
            rt.ingest(packet, receipt)
            snap = rt.guard.snapshot(receipt)
            if not snap.get('ready'):
                continue
            latest = snap['samples'][-1]['telemetry']
            ident = (sid, latest['sequence'], latest['source_timestamp'])
            if ident not in expected:
                continue
            ref = expected[ident]
            features = compute([x['telemetry'] for x in snap['samples']])
            assert features['ready']
            assert int(ref['layer']) == latest['layer']
            assert int(ref['platform_id']) == latest['platform_instance_id']
            assert ref['geometry_version_id'] == latest['geometry_version_id']
            for name in replay.FEATURE_COLUMNS:
                a, b = replay.number(ref[name]), replay.number(features[name])
                if a is None or b is None or math.isnan(a) or math.isnan(b):
                    assert (a is None or math.isnan(a)) and (b is None or math.isnan(b)), (sid, ident, name)
                else:
                    assert math.isclose(a, b, abs_tol=1e-6, rel_tol=1e-6), (sid, ident, name, a, b)
            matched += 1
    assert before == replay.sha256(files[sid])
    target = sum(row['session_id'] == sid for row in prepared)
    assert matched == target, (sid, matched, target)
    checks.append({'session_id': sid, 'matched_feature_rows': matched, '24_features_equal': True, 'raw_unchanged': True})
print(json.dumps({'independent_primary_subset_review': checks}, indent=2))
