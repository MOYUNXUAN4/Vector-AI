"""Offline comparison of sequence GRU, tree models, and telemetry baselines.

The script reuses :mod:`train_gru_offline` for raw loading, causal labels,
window construction, and session metrics. Development sessions are limited to
TEST9282/TEST930/TEST931. Thresholds are selected from grouped out-of-fold
development predictions, then each model is refit on all development sessions
and evaluated on frozen TEST929 and TEST1001 sessions.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
import pandas as pd

import train_gru_offline as gru

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    SKLEARN_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - optional dependency
    RandomForestClassifier = None  # type: ignore[assignment]
    SimpleImputer = None  # type: ignore[assignment]
    Pipeline = None  # type: ignore[assignment]
    StandardScaler = None  # type: ignore[assignment]
    SKLEARN_ERROR = exc

try:
    from lightgbm import LGBMClassifier
    LIGHTGBM_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - optional dependency
    LGBMClassifier = None  # type: ignore[assignment]
    LIGHTGBM_ERROR = exc


ROOT = Path(__file__).resolve().parent
TELEMETRY_ROOT = ROOT / "telemetry_logs"
DEFAULT_OUT = TELEMETRY_ROOT / "tree_model_comparison_20261002"
HORIZON_SECONDS = 0.5
WINDOW_SECONDS = 1.0
STRIDE_SECONDS = 0.25
SEQUENCE_LENGTH = 60
SEED = 20261002
DEV_DATASETS = {"TEST9282", "TEST930", "TEST931"}
EVAL_DATASETS = ("TEST929", "TEST1001")

SELECTED_FEATURES = (
    "ball_radial_distance", "ball_radial_velocity", "target_edge_distance",
    "target_edge_radial_velocity", "directional_edge_distance", "platform_tilt",
    "platform_level", "difficulty", "platform_radius", "ball_radius",
    "edge_warning_margin", "edge_warning_radius",
)


def is_fall(session: dict[str, Any]) -> bool:
    return bool(np.isfinite(session["first_event_ts"]))


def key(session: dict[str, Any]) -> tuple[str, str]:
    return str(session["dataset"]), str(session["session_id"])


def load_development() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sessions: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for manifest in gru.DEFAULT_TRAIN_MANIFESTS:
        loaded, note = gru.load_manifest_sessions(Path(manifest), None, True, False)
        sessions.extend(loaded)
        notes.append(note)
    if {str(s["dataset"]) for s in sessions} != DEV_DATASETS:
        raise RuntimeError("Development pool must contain exactly TEST9282, TEST930, TEST931")
    if len({key(s) for s in sessions}) != len(sessions):
        raise RuntimeError("Duplicate development session key")
    return sessions, notes


def load_test929() -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for manifest in gru.DEFAULT_HELDOUT_MANIFESTS:
        loaded, _ = gru.load_manifest_sessions(Path(manifest), None, False, False)
        sessions.extend(loaded)
    return sessions


def load_test1001() -> list[dict[str, Any]]:
    dataset = TELEMETRY_ROOT / "TEST1001"
    sessions: list[dict[str, Any]] = []
    # TEST1001 contains one nested session directory; recurse only below the
    # dataset's session_* roots so analysis artifacts cannot be mistaken for
    # telemetry sessions.
    for raw_path in sorted(dataset.glob("session_*/**/raw.csv")):
        sid = raw_path.parent.name
        loaded = gru.load_session(raw_path, sid, "TEST1001")
        if loaded is not None:
            sessions.append(loaded)
    return sessions


def prepare_sessions(sessions: list[dict[str, Any]], indices: list[int]) -> list[dict[str, Any]]:
    for session in sessions:
        gru.tte_rule_mask(session, gru.DEFAULT_TTE)
        gru.build_examples(session, indices, HORIZON_SECONDS, WINDOW_SECONDS, STRIDE_SECONDS, SEQUENCE_LENGTH)
        # Keep the lower-level geometric controller transition separate from
        # the user-visible prediction_state/yellow alias used by GRU helpers.
        for example in session["examples"]:
            example["current_geometric_warning"] = bool(session["controller_warning"][int(example["row_index"])])
    return sessions


def stratified_folds(sessions: list[dict[str, Any]], n_folds: int, seed: int) -> dict[tuple[str, str], int]:
    """Assign complete sessions to folds within dataset/label strata."""
    rng = np.random.default_rng(seed)
    strata: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for session in sessions:
        strata.setdefault((str(session["dataset"]), is_fall(session)), []).append(session)
    result: dict[tuple[str, str], int] = {}
    for stratum in sorted(strata):
        members = strata[stratum]
        order = rng.permutation(len(members))
        for position, index in enumerate(order):
            result[key(members[int(index)])] = position % n_folds
    if len(result) != len(sessions):
        raise RuntimeError("Fold assignment omitted a session")
    return result


def examples(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return gru.flatten_examples(sessions)


def summarize_sequences(rows: list[dict[str, Any]]) -> np.ndarray:
    """Summarize each causal sequence with last/mean/std/min/max/slope."""
    if not rows:
        return np.empty((0, 0), dtype=np.float32)
    sequences = np.stack([np.asarray(row["sequence"], dtype=np.float32) for row in rows])
    n, length, features = sequences.shape
    finite = np.isfinite(sequences)
    safe = np.where(finite, sequences, np.nan)
    last = safe[:, -1, :]
    mean = np.nanmean(safe, axis=1)
    std = np.nanstd(safe, axis=1)
    minimum = np.nanmin(safe, axis=1)
    maximum = np.nanmax(safe, axis=1)
    x = np.arange(length, dtype=np.float64)
    x_center = x - x.mean()
    denom = float(np.sum(x_center * x_center))
    centered = np.where(finite, sequences, np.nan)
    y_center = centered - np.nanmean(centered, axis=1, keepdims=True)
    slope = np.nansum(y_center * x_center.reshape(1, -1, 1), axis=1) / denom
    count = np.sum(finite, axis=1)
    slope = np.where(count >= 2, slope, np.nan)
    result = np.concatenate([last, mean, std, minimum, maximum, slope], axis=1)
    return np.nan_to_num(result, nan=np.nan, posinf=np.nan, neginf=np.nan).astype(np.float32)


def tree_pipeline(model: Any) -> Any:
    if Pipeline is None or SimpleImputer is None or StandardScaler is None:
        raise RuntimeError(f"scikit-learn unavailable: {SKLEARN_ERROR}")
    # Both imputation and scaling are fit inside each training fold only.
    return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", model)])


def fit_tree(name: str, train_x: np.ndarray, train_y: np.ndarray, seed: int) -> Any:
    if name == "random_forest":
        if RandomForestClassifier is None:
            raise RuntimeError(f"scikit-learn unavailable: {SKLEARN_ERROR}")
        model = RandomForestClassifier(
            n_estimators=300, max_features="sqrt", min_samples_leaf=2,
            class_weight="balanced", random_state=seed, n_jobs=-1,
        )
    elif name == "lightgbm":
        if LGBMClassifier is None:
            raise RuntimeError(f"LightGBM unavailable: {LIGHTGBM_ERROR}")
        model = LGBMClassifier(
            n_estimators=250, learning_rate=0.04, num_leaves=15,
            max_depth=-1, min_child_samples=20, subsample=0.9,
            colsample_bytree=0.85, reg_lambda=1.0, class_weight="balanced",
            random_state=seed, n_jobs=-1, verbosity=-1,
        )
    else:
        raise ValueError(name)
    pipeline = tree_pipeline(model)
    pipeline.fit(train_x, train_y)
    return pipeline


def tree_probabilities(name: str, train_rows: list[dict[str, Any]], eval_rows: list[dict[str, Any]], seed: int) -> tuple[np.ndarray, float, Any]:
    train_x = summarize_sequences(train_rows)
    eval_x = summarize_sequences(eval_rows)
    train_y = np.asarray([int(row["label"]) for row in train_rows], dtype=int)
    if len(np.unique(train_y)) < 2:
        return np.full(len(eval_rows), np.nan), 0.0, None
    started = time.perf_counter()
    model = fit_tree(name, train_x, train_y, seed)
    fit_s = time.perf_counter() - started
    started = time.perf_counter()
    probability = model.predict_proba(eval_x)[:, 1] if len(eval_rows) else np.empty(0)
    infer_ms = (time.perf_counter() - started) * 1000.0 / max(len(eval_rows), 1)
    return np.asarray(probability, dtype=float), fit_s, {"model": model, "inference_ms_per_window": infer_ms}


def choose_threshold(prob: np.ndarray, rows: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for threshold in np.round(np.arange(0.05, 0.951, 0.05), 2):
        result, _ = gru.metrics_from_predictions(rows, prob >= threshold, "calibration")
        table.append({"threshold": float(threshold), **{f"session_{k}": v for k, v in result["session"].items() if k != "method"}})
    frame = pd.DataFrame(table)
    feasible = frame.loc[(frame.session_nonfall_false_alarm_rate <= 0.25) & (frame.session_recall >= 0.60)]
    if feasible.empty:
        feasible = frame.loc[frame.session_recall >= 0.60]
    if feasible.empty:
        feasible = frame
    selected = feasible.sort_values(["session_f1", "session_last_warning_lead_median_s", "session_nonfall_false_alarm_rate"], ascending=[False, False, True]).iloc[0]
    return float(selected.threshold), selected.to_dict()


def grouped_oof_tree(name: str, sessions: list[dict[str, Any]], n_folds: int, seed: int) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, Any]]:
    fold_map = stratified_folds(sessions, n_folds, seed)
    all_rows = examples(sessions)
    probabilities = np.full(len(all_rows), np.nan, dtype=float)
    row_by_identity = {id(row): i for i, row in enumerate(all_rows)}
    fit_seconds: list[float] = []
    inference_ms: list[float] = []
    for fold in range(n_folds):
        train = [s for s in sessions if fold_map[key(s)] != fold]
        valid = [s for s in sessions if fold_map[key(s)] == fold]
        train_rows, valid_rows = examples(train), examples(valid)
        prob, fit_s, meta = tree_probabilities(name, train_rows, valid_rows, seed + fold)
        fit_seconds.append(fit_s)
        if meta:
            inference_ms.append(float(meta["inference_ms_per_window"]))
        for row, value in zip(valid_rows, prob):
            probabilities[row_by_identity[id(row)]] = value
    if not np.isfinite(probabilities).all():
        raise RuntimeError(f"{name}: grouped OOF predictions incomplete")
    threshold, selected = choose_threshold(probabilities, all_rows)
    return probabilities, all_rows, {"threshold": threshold, "selected_calibration": selected, "folds": n_folds, "fit_seconds": fit_seconds, "inference_ms_per_window": inference_ms}


def gru_oof_and_fit(sessions: list[dict[str, Any]], args: argparse.Namespace) -> tuple[float, dict[str, Any]]:
    fold_map = stratified_folds(sessions, args.folds, args.seed)
    all_rows = examples(sessions)
    oof = np.full(len(all_rows), np.nan, dtype=float)
    row_by_identity = {id(row): i for i, row in enumerate(all_rows)}
    fit_info: list[dict[str, Any]] = []
    for fold in range(args.folds):
        train = [s for s in sessions if fold_map[key(s)] != fold]
        valid = [s for s in sessions if fold_map[key(s)] == fold]
        train_rows, valid_rows = examples(train), examples(valid)
        scaler = gru.TrainOnlyScaler.fit(np.stack([r["sequence"] for r in train_rows]))
        model_args = SimpleNamespace(sequence_length=SEQUENCE_LENGTH, hidden_size=32, layers=1, dropout=0.0, batch_size=256, learning_rate=1e-3, weight_decay=1e-5, epochs=args.gru_epochs, device="cpu", seed=args.seed + fold)
        started = time.perf_counter()
        prob, result, _ = gru.fit_gru(train_rows, valid_rows, scaler, model_args)
        fit_info.append({"fold": fold, "fit_seconds": time.perf_counter() - started, "status": result.get("status")})
        for row, value in zip(valid_rows, prob):
            oof[row_by_identity[id(row)]] = value
    if not np.isfinite(oof).all():
        raise RuntimeError("GRU grouped OOF predictions incomplete")
    threshold, selected = choose_threshold(oof, all_rows)
    info = {"threshold": threshold, "selected_calibration": selected, "fit_info": fit_info}
    return threshold, info


def method_metrics(rows: list[dict[str, Any]], predictions: np.ndarray, method: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result, details = gru.metrics_from_predictions(rows, np.asarray(predictions, dtype=bool), method)
    result["session"]["warning_episodes"] = result["session"].get("warning_episode_mean_per_session")
    return result, details


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--gru-epochs", type=int, default=8, help="GRU epochs per fit (default: 8; use a smaller value only for a smoke test)")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    if args.folds < 3:
        raise ValueError("--folds must be at least 3")
    if args.out_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing output directory: {args.out_dir}")
    args.out_dir.mkdir(parents=True)
    np.random.seed(args.seed)

    development, manifest_notes = load_development()
    test929 = load_test929()
    test1001 = load_test1001()
    name_to_index = {name: i for i, name in enumerate(gru.FEATURE_CANDIDATES)}
    indices = [name_to_index[name] for name in SELECTED_FEATURES if name in name_to_index and any(np.isfinite(s["feature_table"][:, name_to_index[name]]).any() for s in development)]
    if len(indices) != len(SELECTED_FEATURES):
        missing = [name for name in SELECTED_FEATURES if name not in {gru.FEATURE_CANDIDATES[i] for i in indices}]
        print(f"[note] selected features unavailable in development: {missing}", file=sys.stderr)
    prepare_sessions(development + test929 + test1001, indices)
    eval_sets = {"TEST929": test929, "TEST1001": test1001}
    split_rows = [{"dataset": s["dataset"], "session_id": s["session_id"], "split": "development", "is_fall_session": is_fall(s), "windows": len(s["examples"])} for s in development]
    split_rows += [{"dataset": s["dataset"], "session_id": s["session_id"], "split": dataset, "is_fall_session": is_fall(s), "windows": len(s["examples"])} for dataset, group in eval_sets.items() for s in group]
    pd.DataFrame(split_rows).to_csv(args.out_dir / "session_split.csv", index=False, encoding="utf-8-sig")

    all_comparison: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    model_notes: dict[str, Any] = {}
    for model_name in ("lightgbm", "random_forest"):
        try:
            _, dev_rows, calibration = grouped_oof_tree(model_name, development, args.folds, args.seed)
            threshold = float(calibration["threshold"])
            calibration_rows.append({"model": model_name, **calibration["selected_calibration"]})
            model_notes[model_name] = calibration
            for dataset, sessions in eval_sets.items():
                eval_rows = examples(sessions)
                probabilities, fit_s, meta = tree_probabilities(model_name, dev_rows, eval_rows, args.seed)
                result, details = method_metrics(eval_rows, probabilities >= threshold, model_name)
                result["probability_threshold"] = threshold
                result["fit_seconds"] = fit_s
                result["inference_ms_per_window"] = meta["inference_ms_per_window"] if meta else math.nan
                all_comparison.append({"dataset": dataset, "method": model_name, **{f"window_{k}": v for k, v in result["window"].items() if k != "method"}, **{f"session_{k}": v for k, v in result["session"].items() if k != "method"}, "probability_threshold": threshold, "fit_seconds": fit_s, "inference_ms_per_window": result["inference_ms_per_window"]})
                detail_rows.extend([{**row, "dataset_evaluation": dataset} for row in details])
        except Exception as exc:
            model_notes[model_name] = {"status": "skipped", "error": str(exc)}

    gru_threshold, gru_info = gru_oof_and_fit(development, args)
    # Keep the GRU calibration row alongside the tree-model rows so the
    # threshold-selection audit is complete and directly comparable.
    calibration_rows.append({"model": "gru", **gru_info["selected_calibration"]})
    development_rows = examples(development)
    # Refit GRU once more for each frozen set so evaluation remains explicit and independent.
    for dataset, sessions in eval_sets.items():
        eval_rows = examples(sessions)
        scaler = gru.TrainOnlyScaler.fit(np.stack([r["sequence"] for r in development_rows]))
        model_args = SimpleNamespace(sequence_length=SEQUENCE_LENGTH, hidden_size=32, layers=1, dropout=0.0, batch_size=256, learning_rate=1e-3, weight_decay=1e-5, epochs=args.gru_epochs, device="cpu", seed=args.seed)
        started = time.perf_counter()
        probabilities, fit_result, _ = gru.fit_gru(development_rows, eval_rows, scaler, model_args)
        fit_s = time.perf_counter() - started
        result, details = method_metrics(eval_rows, probabilities >= gru_threshold, "gru")
        result["probability_threshold"] = gru_threshold
        all_comparison.append({"dataset": dataset, "method": "gru", **{f"window_{k}": v for k, v in result["window"].items() if k != "method"}, **{f"session_{k}": v for k, v in result["session"].items() if k != "method"}, "probability_threshold": gru_threshold, "fit_seconds": fit_s, "inference_ms_per_window": math.nan})
        detail_rows.extend([{**row, "dataset_evaluation": dataset} for row in details])
    model_notes["gru"] = gru_info

    for dataset, sessions in eval_sets.items():
        rows = examples(sessions)
        for method, pred in (("current_yellow_rule", np.asarray([r["current_yellow"] for r in rows], bool)), ("current_geometric_warning", np.asarray([r["current_geometric_warning"] for r in rows], bool)), ("time_to_edge", np.asarray([r["tte_prediction"] for r in rows], bool))):
            result, details = method_metrics(rows, pred, method)
            all_comparison.append({"dataset": dataset, "method": method, **{f"window_{k}": v for k, v in result["window"].items() if k != "method"}, **{f"session_{k}": v for k, v in result["session"].items() if k != "method"}, "probability_threshold": math.nan, "fit_seconds": math.nan, "inference_ms_per_window": math.nan})
            detail_rows.extend([{**row, "dataset_evaluation": dataset} for row in details])

    pd.DataFrame(all_comparison).to_csv(args.out_dir / "comparison_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(detail_rows).to_csv(args.out_dir / "session_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(calibration_rows).to_csv(args.out_dir / "development_threshold_calibration.csv", index=False, encoding="utf-8-sig")
    config = {
        "status": "complete", "horizon_seconds": HORIZON_SECONDS, "window_seconds": WINDOW_SECONDS,
        "stride_seconds": STRIDE_SECONDS, "sequence_length": SEQUENCE_LENGTH,
        "features": [gru.FEATURE_CANDIDATES[i] for i in indices],
        "tree_summary": "last, mean, std, min, max, slope per selected feature",
        "development_datasets": sorted(DEV_DATASETS), "frozen_evaluation_datasets": list(EVAL_DATASETS),
        "development_sessions": len(development), "TEST929_sessions": len(test929), "TEST1001_sessions": len(test1001),
        "folds": args.folds, "seed": args.seed, "gru_epochs": args.gru_epochs,
        "manifest_notes": manifest_notes,
        "models": model_notes, "raw_files_modified": False, "unity_modified": False,
        "dependencies": {"sklearn": str(SKLEARN_ERROR) if SKLEARN_ERROR else "available", "lightgbm": str(LIGHTGBM_ERROR) if LIGHTGBM_ERROR else "available", "torch": str(gru.TORCH_IMPORT_ERROR) if gru.TORCH_IMPORT_ERROR else "available"},
    }
    (args.out_dir / "metrics.json").write_text(json.dumps(gru.finite_json(config), indent=2), encoding="utf-8")
    (args.out_dir / "README.md").write_text("\n".join([
        "# Tree model comparison (2026-10-02)", "",
        "Causal labels are `fall_event` in `(t, t + 0.5s]` within the same contiguous session segment. Development-only grouped folds use TEST9282, TEST930, and TEST931. TEST929 and TEST1001 are frozen evaluation sets and do not affect feature, model, or threshold selection.", "",
        "Tree inputs summarize each one-second sequence using last/mean/std/min/max/slope for every selected feature. Imputation and standardization are fit within each training fold. `comparison_metrics.csv` reports session precision, recall, F1, non-fall false-alarm rate, lead summaries, warning episodes, and timing.", "",
        "Raw telemetry and existing scripts were not modified. Missing optional dependencies are recorded in `metrics.json`.", "",
    ]), encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir), "rows": len(all_comparison), "development_sessions": len(development), "TEST929_sessions": len(test929), "TEST1001_sessions": len(test1001)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
