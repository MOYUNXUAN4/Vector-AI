"""Replay recorded development CSV through normalized runtime feature stream.

CSV-to-live adapter is explicit. Recorded backend wall timestamps are replay
receipt-time proxies, not evidence of real live monotonic-clock performance.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import math
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREP = ROOT / 'telemetry_logs/TEST1009/training_20261009'
sys.path.insert(0, str(HERE.parent / 'backend'))
from runtime_adapter import FeatureRuntimePrototype
from causal_features import FEATURE_NAMES


def boolean(x):
    return {'true': True, 'false': False}.get(str(x).lower())


def csv_packet(row):
    # Mixed Wii/Unity CSV timestamps may import as text. Restore the numeric
    # Unity JSON timestamp here only; the live adapter still rejects strings.
    p = dict(row, type='unity_game', timestamp=float(row['source_timestamp']),
             platformLevel=row['platform_level'], platformTilt=row['platform_tilt'])
    for k in ('calibration_mode','geometry_query_valid','geometry_ownership_valid','directional_edge_valid'):
        p[k] = boolean(row.get(k))
    return p


def main():
    expected = pd.read_csv(PREP / 'features.csv', low_memory=False)
    associations = pd.read_csv(PREP / 'session_associations_and_splits.csv', low_memory=False)
    missing, mismatch, sessions = [], [], []
    tested = 0
    safe_warning_count = 0
    raw_unchanged = True
    for a in associations.to_dict('records'):
        path = Path(a['raw_path'])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        raw = pd.read_csv(path, low_memory=False)
        unity = raw[raw.source.astype(str).str.lower().eq('unity')].copy()
        sid = str(a['session_id'])
        baselines = {int(r['source_sequence']):r for r in expected[expected.session_id.eq(sid)].to_dict('records')}
        first_receive = float(unity.backend_timestamp.iloc[0])
        run_id = str(unity.run_id.iloc[0])
        r = FeatureRuntimePrototype(allow_calibration_session_gameplay=True)
        r.begin_run(run_id)
        accepted, compared, reasons = 0, 0, Counter()
        for row in unity.to_dict('records'):
            receipt = float(row['backend_timestamp']) - first_receive
            ok = r.ingest(csv_packet(row), receipt)
            accepted += int(ok)
            seq = int(row['sequence'])
            if seq not in baselines:
                continue
            output = r.inspect(receipt)
            json.dumps(output['model_warning'], allow_nan=False)
            safe_warning_count += int(output['model_warning']['state'] == 'UNKNOWN'
                                      and output['model_warning']['valid'] is False
                                      and output['model_warning']['enabled'] is False)
            if not ok or not output['feature_ready']:
                reason = output['model_warning']['reason']
                reasons[reason] += 1
                missing.append({'session_id':sid,'source_sequence':seq,'reason':reason})
                continue
            compared += 1
            tested += 1
            for name in FEATURE_NAMES:
                actual = float(output['features'][name])
                target = float(baselines[seq][name])
                if not np.isclose(actual,target,rtol=1e-10,atol=1e-10,equal_nan=True):
                    mismatch.append({'session_id':sid,'source_sequence':seq,'feature':name,
                                     'actual':actual if math.isfinite(actual) else None,
                                     'expected':target if math.isfinite(target) else None})
        unchanged = hashlib.sha256(path.read_bytes()).hexdigest() == before
        raw_unchanged &= unchanged
        sessions.append({'session_id':sid,'unity_packets':len(unity),'accepted_packets':accepted,
                         'baseline_decisions':len(baselines),'runtime_feature_decisions':compared,
                         'unknown_decision_reasons':dict(reasons),'raw_unchanged':unchanged})
    report = {'scope':'TEST1009 raw development packets; runtime adapter and guard; no inference',
              'sessions':len(sessions),'expected_decisions':len(expected),'runtime_ready_decisions':tested,
              'missing_decision_count':len(missing),'missing_first_20':missing[:20],
              'feature_mismatch_count':len(mismatch),'feature_mismatch_first_20':mismatch[:20],
              'unknown_disabled_warning_decisions':safe_warning_count,'raw_files_unchanged':raw_unchanged,
              'calibration_session_gameplay_compatibility':'explicit opt-in; raw flag retained; small platform + three-layer configured gameplay required',
              'limitations':['Recorded backend wall time replay proxy is not live monotonic performance validation.',
                             'No model, threshold, state policy, live service, socket or Unity display tested.',
                             'Missing or invalid evidence returns UNKNOWN; no frozen validation set was read.'],
              'session_details':sessions}
    (HERE/'runtime_parity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('sessions','expected_decisions','runtime_ready_decisions','missing_decision_count','feature_mismatch_count','unknown_disabled_warning_decisions','raw_files_unchanged')},ensure_ascii=False))
    if missing or mismatch or tested != len(expected) or not raw_unchanged:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
