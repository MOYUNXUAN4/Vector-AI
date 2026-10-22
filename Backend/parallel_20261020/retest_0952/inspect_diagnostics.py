"""Read-only standalone retest diagnostic summary; no source mutations."""
import collections
import hashlib
import json
import math
from pathlib import Path

ROOT = Path('C:/Users/QIYUXUAN/AppData/LocalLow/QI YUXUAN/VectorAI')

def finite(v):
    return isinstance(v, (int, float)) and math.isfinite(v)

def audit(path):
    data = path.read_bytes()
    rows = [json.loads(x) for x in data.splitlines() if x.strip()]
    ordinary = [r for r in rows if 'sample_sequence' in r and not r.get('record_type')]
    frames = {}
    for r in rows:
        if finite(r.get('frame_unscaled_delta_time_ms')) and finite(r.get('unity_time',r.get('query_start_unity_time'))):
            key = (r.get('run_id'), r.get('unity_time',r.get('query_start_unity_time')))
            if key not in frames or r['frame_unscaled_delta_time_ms'] > frames[key]['frame_unscaled_delta_time_ms']:
                frames[key] = r
    long = [{k:r.get(k) for k in ['run_id','unity_time','query_start_unity_time','frame_unscaled_delta_time_ms','frame_delta_time_ms','sample_sequence','diagnostic_total_cost_ms']} for r in frames.values() if r['frame_unscaled_delta_time_ms']>100]
    offsets = [r['backend_timestamp']-r['unity_time'] for r in ordinary if finite(r.get('backend_timestamp')) and finite(r.get('unity_time'))]
    return dict(path=str(path),sha256=hashlib.sha256(data).hexdigest(),records=len(rows),run_ids=sorted(set(r.get('run_id','') for r in rows)), ordinary_samples=len(ordinary),
        record_types=dict(collections.Counter(r.get('record_type','sample') for r in rows)),
        lifecycles=[{k:r.get(k) for k in ['lifecycle_event','run_id','unity_time','backend_timestamp','session_outcome','sequence']} for r in rows if r.get('record_type')=='lifecycle'],
        frame_observations=len(frames),frame_max_ms=max((r['frame_unscaled_delta_time_ms'] for r in frames.values()), default=None),long_frames_over_100ms=long,
        ordinary_offset_range_seconds=max(offsets)-min(offsets) if offsets else None,
        ordinary_offset_max_jump_seconds=max((abs(b-a) for a,b in zip(offsets,offsets[1:])),default=None))

if __name__=='__main__':
    results=[audit(ROOT/'EndlessFallingDiagnostics'/n) for n in ['samples_20261020_015211_872_f15778bf.jsonl','samples_20261020_015221_391_47236862.jsonl']]
    print(json.dumps(results,indent=2,allow_nan=False))
