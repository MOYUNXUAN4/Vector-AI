"""Independent source/median/session/ranking/native-inference checks; never fits."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/baseline_fixed'


def verify(out):
    config = json.loads((BASE / 'config.json').read_text(encoding='utf-8'))
    features = pd.read_csv(BASE / 'prepared_inputs/features.csv')
    labels = pd.read_csv(BASE / 'training_labels.csv')
    labels = labels[labels.target.eq('strong')].copy()
    labels['eligible'] = labels.eligible.map(lambda x: str(x).lower() == 'true')
    data = features.merge(labels[['session_id', 'timestamp', 'label', 'eligible']],
                          on=['session_id', 'timestamp'], validate='one_to_one')
    train = data[data.eligible & data.label.notna()].copy()
    assert len(data) == 6898 and data.session_id.nunique() == 30
    assert len(train) == 5558 and train.label.eq(1).sum() == 108 and train.label.eq(0).sum() == 5450
    names = config['strong_features']
    medians = train[names].apply(pd.to_numeric, errors='coerce').median().fillna(0)
    fit = json.loads((out / 'final_fit.json').read_text(encoding='utf-8'))
    assert fit['train_rows'] == len(train)
    assert set(fit['train_sessions']) == set(train.session_id)
    assert fit['model_params'] == config['model_params']
    assert np.allclose([fit['train_medians'][n] for n in names], medians, rtol=0, atol=1e-12)
    counts = train.label.value_counts().to_dict()
    base_weights = train.label.map({k: len(train)/(2*v) for k,v in counts.items()})
    base_weights = base_weights / base_weights.groupby(train.session_id).transform('sum')
    equal_weights = 1 / train.session_id.map(train.session_id.value_counts())
    weights = .5 * base_weights + .5 * equal_weights
    diag = fit['weight_diagnostics']
    assert np.isclose(diag['sum'], weights.sum(), rtol=0, atol=1e-10)
    assert np.isclose(diag['min'], weights.min(), rtol=0, atol=1e-12)
    assert np.isclose(diag['max'], weights.max(), rtol=0, atol=1e-12)
    assert np.isclose(diag['midpoint_positive_fraction'], weights[train.label.eq(1)].sum()/weights.sum(), rtol=0, atol=1e-12)
    for relpath, expected in fit['input_sha256'].items():
        assert hashlib.sha256((ROOT/relpath).read_bytes()).hexdigest() == expected
    records = json.loads((out / 'fit_records.json').read_text(encoding='utf-8'))
    oof = [r for r in records if r.get('test_sessions')]
    assert len(oof) == 3
    test_ids = []
    for r in oof:
        assert not set(r['train_sessions']) & set(r['test_sessions'])
        assert set(r['train_sessions']) | set(r['test_sessions']) == set(data.session_id)
        test_ids.extend(r['test_sessions'])
        fold_train = train[train.session_id.isin(r['train_sessions'])]
        fold_medians = fold_train[names].apply(pd.to_numeric, errors='coerce').median().fillna(0)
        assert r['train_rows'] == len(fold_train)
        assert np.allclose([r['train_medians'][n] for n in names], fold_medians, rtol=0, atol=1e-12)
    assert len(test_ids) == 30 and len(set(test_ids)) == 30
    probability_rows = pd.read_csv(out / 'oof_probabilities.csv')
    assert len(probability_rows) == len(data)
    assert not probability_rows.duplicated(['session_id', 'timestamp']).any()
    assert set(zip(probability_rows.session_id, probability_rows.timestamp)) == set(zip(data.session_id, data.timestamp))
    assert probability_rows.outer_fold.tolist() == [config['outer_folds'][s] for s in probability_rows.session_id]
    candidates = json.loads((out / 'candidate_metrics.json').read_text(encoding='utf-8'))
    assert sorted(c['threshold'] for c in candidates) == sorted(config['thresholds'])
    feasible = [c for c in candidates if c['metrics']['conservative_recall'] >= .6
                and c['metrics']['guaranteed_geometry_early_coverage'] >= .4]
    assert feasible, 'No feasible threshold: export must remain unapproved'
    winner = min(feasible, key=lambda c: (c['metrics']['completed_alarm_rate'],
        c['metrics']['completed_observed_alarm_seconds_per_session'],
        -(c['metrics']['precision'] or 0), -c['threshold']))
    selection = json.loads((out / 'selection.json').read_text(encoding='utf-8'))
    assert selection['threshold'] == winner['threshold']
    exporter_path = ROOT / 'parallel_20261011/deployment/native_export.py'
    spec = importlib.util.spec_from_file_location('primary_export_contract', exporter_path)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    manifest_path = out / 'artifact/manifest.json'
    model_path = out / 'artifact/model.txt'
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    artifact = exporter._contract()[0].ModelArtifact.load(manifest_path,
        expected_model_sha256=digest, allow_experimental=True)
    assert artifact.threshold == winner['threshold']
    assert list(artifact.config['features']) == names
    assert np.allclose([artifact.config['medians'][n] for n in names], medians, rtol=0, atol=1e-12)
    # Independently exercise public inference with source rows, not a fixture.
    sample = data[data.clearance.gt(0)].iloc[::max(1, len(data)//40)]
    probabilities = [artifact.predict_probability(dict(row, ready=True)) for row in sample[names].to_dict('records')]
    assert probabilities and all(np.isfinite(p) and 0 <= p <= 1 for p in probabilities)
    result = {'status': 'passed', 'sessions': 30, 'fit_rows': 5558, 'positives': 108,
              'threshold': winner['threshold'], 'public_prediction_rows': len(probabilities),
              'model_sha256': digest, 'performance_acceptance': False}
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    verify(parser.parse_args().output)
