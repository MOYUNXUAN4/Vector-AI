"""Read-only TEST1009 development replay; no fitting or validation-set access."""
from pathlib import Path
from collections import Counter, deque
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
from causal_features import compute_latest_features, FEATURE_NAMES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else float('nan')
    except (ValueError, TypeError):
        return float('nan')


def canonical_id(x):
    v = num(x)
    return str(int(v)) if math.isfinite(v) and v.is_integer() else str(x).strip()


def main():
    expected = pd.read_csv(PREP / 'features.csv', low_memory=False)
    associations = pd.read_csv(PREP / 'session_associations_and_splits.csv', low_memory=False)
    assert len(associations) == 30 and len(expected) == 6898
    maximum = {k: 0.0 for k in FEATURE_NAMES}
    matched = 0
    mismatches, sessions, calibration = [], [], Counter()
    raw_unchanged = True
    for association in associations.to_dict('records'):
        sid = str(association['session_id'])
        path = Path(association['raw_path'])
        before = digest(path)
        raw = pd.read_csv(path, low_memory=False)
        u = raw[raw.source.astype(str).str.lower().eq('unity')].copy()
        u['t'] = pd.to_numeric(u.source_timestamp, errors='coerce')
        u['seq'] = pd.to_numeric(u.sequence, errors='coerce')
        u['layer_n'] = pd.to_numeric(u.platform_level, errors='coerce')
        valid = (u.run_state.astype(str).str.lower().eq('running') & u.t.notna()
                 & u.layer_n.between(1, 3)
                 & pd.to_numeric(u.platform_scale, errors='coerce').le(2)
                 & u.directional_edge_valid.astype(str).str.lower().isin(['true', '1']))
        for key in ('directional_edge_distance', 'ball_radial_velocity', 'ball_radius', 'platform_radius'):
            valid &= np.isfinite(pd.to_numeric(u[key], errors='coerce'))
        eligible = u[valid]
        calibration.update(eligible.calibration_mode.astype(str).str.lower())
        exp = {int(r['source_sequence']): r for r in expected[expected.session_id.eq(sid)].to_dict('records')}
        previous, context, buffer = None, None, deque(maxlen=128)
        generated_sequences, observed = [], 0
        first_eval, last_eval = None, -math.inf
        for row in eligible.to_dict('records'):
            key = (str(row['run_id']), int(row['layer_n']), canonical_id(row['geometry_platform_instance_id']), str(row['geometry_version_id']))
            if (previous is None or key != context or not 0 < row['t'] - previous['t'] <= .1
                    or row['seq'] - previous['seq'] != 1):
                buffer.clear()
                first_eval = row['t'] + .5
                last_eval = -math.inf
            sample = dict(row, source_timestamp=row['t'])
            buffer.append(sample)
            previous, context = row, key
            if row['t'] < first_eval or row['t'] - last_eval < .05 - 1e-9:
                continue
            last_eval = row['t']
            features = compute_latest_features(list(buffer))
            if not features['ready']:
                continue
            seq = int(row['seq'])
            generated_sequences.append(seq)
            baseline = exp.get(seq)
            if baseline is None:
                mismatches.append({'session_id': sid, 'sequence': seq, 'reason': 'unexpected_decision'})
                continue
            observed += 1
            matched += 1
            for name in FEATURE_NAMES:
                actual, target = float(features[name]), num(baseline[name])
                if math.isnan(actual) and math.isnan(target):
                    continue
                if math.isfinite(actual) and math.isfinite(target):
                    maximum[name] = max(maximum[name], abs(actual-target))
                if not np.isclose(actual, target, rtol=1e-10, atol=1e-10, equal_nan=True):
                    mismatches.append({'session_id': sid, 'sequence': seq, 'feature': name,
                                       'actual': actual if math.isfinite(actual) else None,
                                       'expected': target if math.isfinite(target) else None})
        missing = sorted(set(exp) - set(generated_sequences))
        mismatches.extend({'session_id': sid, 'sequence': seq, 'reason': 'missing_decision'} for seq in missing)
        unchanged = digest(path) == before
        raw_unchanged &= unchanged
        sessions.append({'session_id': sid, 'expected_decisions': len(exp), 'matched': observed,
                         'missing_decisions': len(missing), 'raw_sha256': before, 'raw_unchanged': unchanged})
    report = {'scope': 'TEST1009 development only; raw CSV read-only; no model or alarm evaluation',
              'sessions': len(sessions), 'feature_rows_expected': len(expected),
              'feature_rows_matched': matched, 'feature_columns': len(FEATURE_NAMES),
              'feature_cells_compared': matched * len(FEATURE_NAMES),
              'mismatch_count': len(mismatches), 'mismatches_first_20': mismatches[:20],
              'absolute_error_max_by_feature': maximum, 'tolerance': {'rtol': 1e-10, 'atol': 1e-10},
              'eligible_raw_calibration_mode_counts': dict(calibration),
              'raw_files_unchanged': raw_unchanged, 'sessions_detail': sessions,
              'limitations': ['This tests the causal feature kernel and original decision spacing, not live sockets or Unity.',
                              'Eligibility mirrors training; StreamGuard/packet adapter stricter exclusions need separate checks.',
                              'calibration_mode is session configuration, not a sufficient calibration-phase flag in this cohort.']}
    (HERE / 'feature_parity.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('sessions', 'feature_rows_matched', 'feature_cells_compared', 'mismatch_count', 'eligible_raw_calibration_mode_counts', 'raw_files_unchanged')}, ensure_ascii=False))
    if mismatches or matched != len(expected) or not raw_unchanged:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
