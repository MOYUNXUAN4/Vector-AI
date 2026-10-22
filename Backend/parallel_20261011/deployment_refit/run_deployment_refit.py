"""Development-only grouped OOF threshold calibration and gated full refit.

Default mode performs a read-only preflight and writes only this directory's
output/preflight.json. Fitting requires --primary-approved. The grouped OOF
probabilities are calibration diagnostics, not an independent evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP = ROOT / "telemetry_logs" / "TEST1009" / "training_20261009" / "cop_single_factor_20261009"
BASELINE = EXP / "baseline_fixed"
PREP = BASELINE / "prepared_inputs"
DRIVER_PATH = EXP / "runner" / "run_cop_single_factor.py"
LABEL_PATH = BASELINE / "training_labels.csv"
MEMBERSHIP_PATH = BASELINE / "outer_membership.csv"
SOURCE_PATH = ROOT / "telemetry_logs" / "nested_calibration_20261008" / "calibration" / "run_nested_calibration.py"
EVALUATION_PATH = ROOT / "telemetry_logs" / "TEST1009" / "training_20261009" / "evaluation_fixed_20261009" / "fixed_evaluation.py"
COHORT_DRIVER = ROOT / "telemetry_logs" / "TEST1009" / "training_20261009" / "run_nested.py"
EXPORTER_PATH = ROOT / "parallel_20261011" / "deployment" / "native_export.py"
OUT = HERE / "output"
THRESHOLDS = [0.20, 0.35, 0.50, 0.65, 0.80, 0.95]
EXPECTED = {"rows": 6898, "sessions": 30, "eligible": 5558, "positive": 108, "negative": 5450, "ineligible": 1340}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def setup():
    sys.dont_write_bytecode = True
    patch_driver = load_module("deployment_refit_patch_driver", DRIVER_PATH)
    cohort_driver = load_module("deployment_refit_cohort_driver", COHORT_DRIVER)
    cohort_driver.adapt_fit_guard()
    runner = cohort_driver.runner
    runner.ACTIVE_PREP = PREP.resolve()
    runner.ACTIVE_LEDGER = (PREP / "risk_episode_ledger.csv").resolve()
    runner.OUT = OUT.resolve()
    runner.build_outer_map = cohort_driver.build_outer_map
    source_text = SOURCE_PATH.read_text(encoding="utf-8")
    patch_driver.install_patches(runner, cohort_driver, source_text, list(runner.cmp.FEATURES), "baseline")
    runner.cmp.SEED = 20261009
    runner.cmp.MODEL_PARAMS = dict(runner.cmp.MODEL_PARAMS, random_state=20261009)
    runner.THRESHOLDS = list(THRESHOLDS)
    return patch_driver, runner


def label_signature(frame):
    keys = ["target", "session_id", "timestamp"]
    cols = keys + ["label", "eligible", "label_reason"]
    x = frame[cols].copy()
    x["session_id"] = x.session_id.astype(str)
    return x.sort_values(keys, kind="stable").reset_index(drop=True).fillna("")


def preflight():
    required = [SOURCE_PATH, DRIVER_PATH, COHORT_DRIVER, EVALUATION_PATH, EXPORTER_PATH,
                PREP / "features.csv", PREP / "session_manifest.csv", PREP / "event_anchors.csv",
                PREP / "recovery_points.csv", PREP / "source_hashes.json", PREP / "summary.json",
                PREP / "risk_episode_ledger.csv", EXP.parent / "session_associations_and_splits.csv",
                LABEL_PATH, MEMBERSHIP_PATH, BASELINE / "config.json"]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        result = {"status": "FAIL", "fit_started": False, "missing": missing}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "preflight.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"required locked inputs missing: {missing}")

    driver, runner = setup()
    features, joined, formal, outer_map, anchors, labels = runner.load_inputs()
    config = json.loads((BASELINE / "config.json").read_text(encoding="utf-8"))
    stored_labels = pd.read_csv(LABEL_PATH, low_memory=False)
    labels_match = label_signature(labels).equals(label_signature(stored_labels))
    stored_membership = pd.read_csv(MEMBERSHIP_PATH, low_memory=False)
    stored_membership = stored_membership[["session_id", "outer_fold"]].copy()
    stored_membership["session_id"] = stored_membership.session_id.astype(str)
    generated_membership = pd.DataFrame([{"session_id": str(s), "outer_fold": int(f)} for s, f in outer_map.items()])
    membership_match = generated_membership.sort_values("session_id").reset_index(drop=True).equals(
        stored_membership.sort_values("session_id").reset_index(drop=True))
    strong = labels[labels.target.eq("strong")].copy()
    eligible = strong.eligible.astype(bool) & strong.label.notna()
    y = pd.to_numeric(strong.loc[eligible, "label"], errors="coerce").astype(int)
    counts = {"rows": int(len(strong)), "sessions": int(strong.session_id.astype(str).nunique()),
              "eligible": int(eligible.sum()), "positive": int((y == 1).sum()),
              "negative": int((y == 0).sum()), "ineligible": int((~eligible).sum())}
    input_hashes = {str(p.relative_to(ROOT)): sha(p) for p in required if p.is_file()}
    input_hashes_by_name = {Path(k).name: v for k, v in input_hashes.items()}
    locked_hashes = {Path(k).name: v for k, v in config.get("source_hashes_after", {}).items()}
    source_hashes_match = all(input_hashes_by_name.get(name) == digest for name, digest in locked_hashes.items())
    config_match = (list(runner.cmp.FEATURES) == config.get("strong_features") and
                    runner.cmp.MODEL_PARAMS == config.get("model_params") and
                    runner.cmp.POLICIES["strong"].get("horizon") == 0.75)
    fold_counts = {str(k): int(v) for k, v in pd.Series(outer_map).value_counts().items()}
    result = {
        "status": "PASS" if labels_match and membership_match and counts == EXPECTED and source_hashes_match and config_match and fold_counts == {"1": 10, "2": 10, "3": 10} else "FAIL",
        "fit_started": False,
        "locked_dataset": str(BASELINE.relative_to(ROOT)),
        "counts": counts,
        "expected_counts": EXPECTED,
        "label_signature_matches_baseline_training_labels": bool(labels_match),
        "outer_membership_matches_baseline": bool(membership_match),
        "outer_fold_counts": fold_counts,
        "baseline_config_match": bool(config_match),
        "config_source_hashes_match_by_basename": bool(source_hashes_match),
        "feature_count": len(runner.cmp.FEATURES),
        "feature_order": list(runner.cmp.FEATURES),
        "threshold_grid": THRESHOLDS,
        "input_sha256": input_hashes,
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in [SOURCE_PATH, DRIVER_PATH, COHORT_DRIVER, EVALUATION_PATH, EXPORTER_PATH]},
        "threshold_rule": "baseline None-safe rank_candidates: feasible recall>=0.60 and guaranteed geometry early coverage>=0.40; then min completed alarm rate, min burden, max precision, higher threshold; if none, diagnostic fallback and no artifact",
        "interpretation": "Recomputed grouped development OOF is threshold-calibration data, not a new independent evaluation.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "preflight.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    if result["status"] != "PASS":
        raise RuntimeError("deployment refit preflight failed closed")
    return driver, runner, (features, joined, formal, outer_map, anchors, labels), result


def fit_and_calibrate(driver, runner, data, preflight_report):
    features, joined, formal, outer_map, anchors, labels = data
    OUT.mkdir(parents=True, exist_ok=True)
    existing = [p.name for p in OUT.iterdir() if p.name != "preflight.json"]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing fit outputs: {existing}")
    fold_predictions = []
    fit_records = []
    session_ids = set(formal.session_id.astype(str))
    for fold in (1, 2, 3):
        train_ids = sorted(s for s, f in outer_map.items() if f != fold)
        test_ids = sorted(s for s, f in outer_map.items() if f == fold)
        if set(train_ids) & set(test_ids) or set(train_ids) | set(test_ids) != session_ids:
            raise RuntimeError(f"outer membership exclusion failed for fold {fold}")
        train = joined[joined.session_id.astype(str).isin(train_ids)]
        test = joined[joined.session_id.astype(str).isin(test_ids)].copy()
        probability, record = runner.fit_subset(train, test, "strong")
        if record.get("status") != "fit" or set(record.get("train_sessions", [])) != set(train_ids) or set(record.get("test_sessions", [])) != set(test_ids):
            raise RuntimeError(f"OOF fit did not match locked memberships for fold {fold}")
        test["prob_strong"] = probability
        test["mask_strong"] = np.isfinite(probability)
        test["outer_fold"] = fold
        fold_predictions.append(test)
        record.update(scope="development_grouped_oof_calibration", outer_fold=fold)
        fit_records.append(record)
    oof = pd.concat(fold_predictions, ignore_index=True)
    if len(oof) != EXPECTED["rows"] or oof.session_id.astype(str).nunique() != EXPECTED["sessions"]:
        raise RuntimeError("OOF ownership table did not cover all locked rows exactly")
    oof.to_csv(OUT / "oof_probabilities.csv", index=False, na_rep="")
    candidate_records = []
    for threshold in THRESHOLDS:
        _, episodes, per_session, events = runner.strict_replay(oof, formal, anchors, "strong", threshold)
        metrics = runner.candidate_metrics(per_session, events, "strong")
        candidate_records.append({"threshold": threshold, "metrics": metrics})
    ranked, selected, rule, feasible = runner.rank_candidates(candidate_records, "strong")
    serial_ranked = [{"threshold": r["threshold"], "metrics": r["metrics"], "rank": i + 1,
                      "feasible": bool(r["metrics"]["conservative_recall"] >= .60 and r["metrics"]["guaranteed_geometry_early_coverage"] >= .40)}
                     for i, r in enumerate(ranked)]
    (OUT / "candidate_metrics.json").write_text(json.dumps(candidate_records, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    selection = {"threshold": float(selected["threshold"]), "qualified": bool(feasible), "ranking_rule": rule,
                 "fallback": not bool(feasible), "calibration_diagnostic": True,
                 "independent_evaluation": False, "candidates_ranked": serial_ranked}
    (OUT / "selection.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (OUT / "fit_records.json").write_text(json.dumps(fit_records, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n", encoding="utf-8")
    if not feasible:
        raise RuntimeError("no threshold passed baseline gates; diagnostic fallback recorded and artifact export is prohibited pending primary review")

    eligible = joined.eligible_strong.astype(bool) & joined.label_strong.notna()
    train = joined.loc[eligible].copy()
    y = train.label_strong.astype(int).to_numpy()
    xraw = train[runner.cmp.FEATURES].apply(pd.to_numeric, errors="coerce")
    medians = {}
    xtrain = xraw.copy()
    for col in runner.cmp.FEATURES:
        values = pd.to_numeric(xraw[col], errors="coerce")
        med = float(values.median()) if values.notna().any() else 0.0
        medians[col] = med
        xtrain[col] = values.fillna(med)
    weights, class_counts, class_weights, weight_diag = driver.midpoint_weights(train, y, runner.cmp)
    model = runner.lgb.LGBMClassifier(**runner.cmp.MODEL_PARAMS)
    model.fit(xtrain, y, sample_weight=weights)
    booster = model.booster_
    final_record = {"train_rows": len(train), "positives": int((y == 1).sum()), "negatives": int((y == 0).sum()),
                    "train_sessions": sorted(train.session_id.astype(str).unique()), "train_medians": medians,
                    "model_params": runner.cmp.MODEL_PARAMS, "weight_diagnostics": weight_diag,
                    "class_counts": {str(k): int(v) for k, v in class_counts.items()}, "class_weights": class_weights,
                    "feature_order": list(runner.cmp.FEATURES), "calibration_threshold": selection["threshold"],
                    "threshold_selection_scope": "development_grouped_oof", "input_sha256": preflight_report["input_sha256"]}
    (OUT / "final_fit.json").write_text(json.dumps(final_record, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n", encoding="utf-8")
    fit_records.append({"scope": "final_refit_all_development", "train_sessions": final_record["train_sessions"], "test_sessions": [],
                        "train_rows": final_record["train_rows"], "positives": final_record["positives"],
                        "negatives": final_record["negatives"], "train_medians": medians,
                        "weight_diagnostics": weight_diag, "model_params": runner.cmp.MODEL_PARAMS})
    (OUT / "fit_records.json").write_text(json.dumps(fit_records, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n", encoding="utf-8")
    exporter = load_module("deployment_native_export", EXPORTER_PATH)
    provenance = {"artifact_role": "deployment_refit", "training_dataset_ids": ["TEST1009"],
                  "development_session_ids": sorted(session_ids), "threshold_selection_scope": "development_grouped_oof",
                  "independent_test_used": False}
    export_result = exporter.export_native(booster, OUT / "artifact", model_id="test1009-strong-deployment-refit-20261011",
                                           medians=medians, threshold=selection["threshold"], provenance=provenance)
    from lightgbm import Booster
    reloaded = Booster(model_file=export_result["model"])
    native = reloaded.predict(xtrain)
    fitted = model.predict_proba(xtrain)[:, list(model.classes_).index(1)]
    if not np.allclose(native, fitted, rtol=0, atol=1e-12):
        raise RuntimeError("native reload predictions differ from fitted model on eligible rows")
    artifact_module, _, _ = exporter._contract()
    loaded = artifact_module.ModelArtifact.load(export_result["manifest"], expected_model_sha256=export_result["model_sha256"], allow_experimental=True)
    geometry_valid = np.ones(len(xraw), dtype=bool)
    for col in ("directional_edge_distance", "clearance", "radial_outward_velocity", "ball_radius", "platform_radius"):
        vals = pd.to_numeric(xraw[col], errors="coerce").to_numpy(float)
        geometry_valid &= np.isfinite(vals)
    geometry_valid &= (pd.to_numeric(xraw.clearance, errors="coerce").to_numpy(float) > 0)
    geometry_valid &= (pd.to_numeric(xraw.ball_radius, errors="coerce").to_numpy(float) > 0)
    geometry_valid &= (pd.to_numeric(xraw.platform_radius, errors="coerce").to_numpy(float) > 0)
    geometry_valid &= ~np.isinf(xraw.to_numpy(dtype=float)).any(axis=1)
    public_prob = np.asarray([loaded.predict_probability({**{name: row[name] for name in runner.cmp.FEATURES}, "ready": True})
                              for _, row in xraw.loc[geometry_valid].iterrows()], dtype=float)
    public_native = native[geometry_valid]
    if not np.allclose(public_prob, public_native, rtol=0, atol=1e-12):
        raise RuntimeError("public artifact inference differs from native Booster on geometry-valid eligible rows")
    after_hashes = {key: sha(ROOT / key) for key in preflight_report["input_sha256"]}
    sources_unchanged = after_hashes == preflight_report["input_sha256"]
    if not sources_unchanged:
        raise RuntimeError("locked source/input hashes changed during deployment fit")
    evidence = {"export": export_result, "eligible_prediction_rows": int(len(xtrain)), "reload_prediction_max_abs_error": float(np.max(np.abs(native - fitted))),
                "public_geometry_valid_rows": int(geometry_valid.sum()), "public_wrapper_max_abs_error": float(np.max(np.abs(public_prob - public_native))) if len(public_prob) else None,
                "prediction_tolerance": {"rtol": 0, "atol": 1e-12}, "preflight_input_sha256": preflight_report["input_sha256"]}
    evidence["sources_unchanged"] = sources_unchanged
    evidence["postfit_input_sha256"] = after_hashes
    (OUT / "native_reload_evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return selection, final_record, evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-approved", action="store_true", help="authorize development grouped-OOF calibration and all-development refit")
    args = parser.parse_args()
    setup_result = preflight()
    if not args.primary_approved:
        print(json.dumps(setup_result[3], ensure_ascii=False, indent=2))
        return
    result = fit_and_calibrate(*setup_result[:3], setup_result[3])
    print(json.dumps({"status": "completed", "selection": result[0], "final_fit": result[1], "native_reload": result[2]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
