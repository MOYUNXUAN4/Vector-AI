"""Offline experiment: causally align Wii COP telemetry to Unity samples.

The existing loader intentionally keeps Unity rows for event/geometry labels,
but the raw logs store COP position on separate ``wii`` rows.  This script
creates an in-memory feature augmentation only: for every Unity timestamp it
uses the latest Wii COP sample at or before that timestamp (within 0.10 s),
then derives causal COP velocity and speed.  Raw files and manifests are never
written.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

import calibrate_gru_threshold as calibration
import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "gru_cop_alignment_experiment"


def _causal_wii_features(session: dict[str, Any], max_lag_s: float = 0.10) -> dict[str, Any]:
    raw = pd.read_csv(session["path"], low_memory=False)
    if "source" not in raw.columns:
        return {"matched_rows": 0, "unity_rows": 0, "match_rate": 0.0}
    source = raw["source"].astype(str).str.strip().str.lower()
    wii = raw.loc[source.eq("wii")].copy()
    if wii.empty or "backend_timestamp" not in wii.columns:
        return {"matched_rows": 0, "unity_rows": len(session["timestamps"]), "match_rate": 0.0}
    wii_ts = pd.to_numeric(wii["backend_timestamp"], errors="coerce").to_numpy(dtype=float)
    cop_x = pd.to_numeric(wii.get("cop_x", np.nan), errors="coerce").to_numpy(dtype=float)
    cop_z = pd.to_numeric(wii.get("cop_z", np.nan), errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(wii_ts) & np.isfinite(cop_x) & np.isfinite(cop_z)
    if not finite.any():
        return {"matched_rows": 0, "unity_rows": len(session["timestamps"]), "match_rate": 0.0}
    wii_ts = wii_ts[finite]
    cop_x = cop_x[finite]
    cop_z = cop_z[finite]
    order = np.argsort(wii_ts, kind="mergesort")
    wii_ts, cop_x, cop_z = wii_ts[order], cop_x[order], cop_z[order]
    unity_ts = np.asarray(session["timestamps"], dtype=float)
    indices = np.searchsorted(wii_ts, unity_ts, side="right") - 1
    valid = (indices >= 0) & np.isfinite(unity_ts)
    lag = np.full(len(unity_ts), np.nan, dtype=float)
    lag[valid] = unity_ts[valid] - wii_ts[indices[valid]]
    valid &= np.isfinite(lag) & (lag >= 0.0) & (lag <= max_lag_s)
    aligned_x = np.full(len(unity_ts), np.nan, dtype=float)
    aligned_z = np.full(len(unity_ts), np.nan, dtype=float)
    aligned_x[valid] = cop_x[indices[valid]]
    aligned_z[valid] = cop_z[indices[valid]]
    velocity_x = np.full(len(unity_ts), np.nan, dtype=float)
    velocity_z = np.full(len(unity_ts), np.nan, dtype=float)
    finite_pair = valid & np.r_[False, valid[:-1]] & np.isfinite(unity_ts)
    dt = np.diff(unity_ts, prepend=np.nan)
    finite_pair &= np.isfinite(dt) & (dt > 0)
    velocity_x[finite_pair] = np.diff(aligned_x, prepend=np.nan)[finite_pair] / dt[finite_pair]
    velocity_z[finite_pair] = np.diff(aligned_z, prepend=np.nan)[finite_pair] / dt[finite_pair]
    speed = np.sqrt(velocity_x**2 + velocity_z**2)

    column_indices = {name: index for index, name in enumerate(gru.FEATURE_CANDIDATES)}
    for name, values in {
        "cop_x": aligned_x,
        "cop_z": aligned_z,
        "cop_velocity_x": velocity_x,
        "cop_velocity_z": velocity_z,
        "cop_speed": speed,
    }.items():
        session["feature_table"][:, column_indices[name]] = values.astype(np.float32)
    return {
        "matched_rows": int(valid.sum()),
        "unity_rows": int(len(unity_ts)),
        "match_rate": float(valid.mean()) if len(valid) else 0.0,
        "velocity_rows": int(np.isfinite(speed).sum()),
        "median_lag_s": float(np.nanmedian(lag)) if np.isfinite(lag).any() else np.nan,
    }


def augment(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for session in sessions:
        session["cop_alignment"] = _causal_wii_features(session)
    return sessions


def model_args(args: argparse.Namespace, horizon: float) -> SimpleNamespace:
    return SimpleNamespace(
        horizon_seconds=horizon,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
        sequence_length=args.sequence_length,
        hidden_size=args.hidden_size,
        epochs=args.epochs,
        batch_size=args.batch_size,
        seed=args.seed,
    )


def flatten(result: dict[str, Any], method: str, threshold: float, feature_group: str) -> dict[str, Any]:
    row = {"method": method, "threshold": threshold, "feature_group": feature_group}
    row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
    row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
    return row


def select_threshold(table: pd.DataFrame, target_far: float, min_recall: float) -> tuple[dict[str, Any], str]:
    feasible = table.loc[
        table.session_nonfall_false_alarm_rate.le(target_far + 1e-12)
        & table.session_recall.ge(min_recall)
    ].copy()
    if not feasible.empty:
        feasible = feasible.sort_values(["session_f1", "session_last_warning_lead_median_s", "threshold"], ascending=[False, False, False])
        return feasible.iloc[0].to_dict(), "max F1 with FAR <= target and recall >= minimum"
    fallback = table.loc[table.session_recall.ge(min_recall)].copy()
    if not fallback.empty:
        fallback = fallback.sort_values(["session_nonfall_false_alarm_rate", "session_f1", "threshold"], ascending=[True, False, False])
        return fallback.iloc[0].to_dict(), "minimum FAR with recall >= minimum (target FAR not reached)"
    fallback = table.sort_values(["session_nonfall_false_alarm_rate", "session_f1", "session_recall"], ascending=[True, False, False])
    return fallback.iloc[0].to_dict(), "minimum FAR fallback"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--horizon-seconds", type=float, default=0.5)
    parser.add_argument("--window-seconds", type=float, default=1.0)
    parser.add_argument("--stride-seconds", type=float, default=0.25)
    parser.add_argument("--sequence-length", type=int, default=60)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--validation-fraction", type=float, default=0.20)
    parser.add_argument("--target-far", type=float, default=0.25)
    parser.add_argument("--minimum-recall", type=float, default=0.60)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)
    np.random.seed(args.seed)

    development: list[dict[str, Any]] = []
    for manifest in gru.DEFAULT_TRAIN_MANIFESTS:
        loaded, _ = gru.load_manifest_sessions(Path(manifest), None, True, False)
        development.extend(loaded)
    frozen: list[dict[str, Any]] = []
    for manifest in gru.DEFAULT_HELDOUT_MANIFESTS:
        loaded, _ = gru.load_manifest_sessions(Path(manifest), None, False, False)
        frozen.extend(loaded)
    augment(development)
    augment(frozen)
    alignment = pd.DataFrame(
        [{"dataset": s["dataset"], "session_id": s["session_id"], **s["cop_alignment"]} for s in development + frozen]
    )
    alignment.to_csv(args.out_dir / "cop_alignment_manifest.csv", index=False, encoding="utf-8-sig")

    model_train, calibration_sessions = gru.session_split(development, args.validation_fraction, args.seed)
    feature_names = {
        "edge_kinematic": (
            "ball_radial_distance", "ball_radial_velocity", "target_edge_distance", "target_edge_radial_velocity",
            "directional_edge_distance", "platform_tilt", "platform_level", "difficulty", "platform_radius",
            "ball_radius", "edge_warning_margin", "edge_warning_radius",
        ),
        "edge_kinematic_cop": (
            "ball_radial_distance", "ball_radial_velocity", "target_edge_distance", "target_edge_radial_velocity",
            "directional_edge_distance", "platform_tilt", "platform_level", "difficulty", "platform_radius",
            "ball_radius", "edge_warning_margin", "edge_warning_radius", "cop_x", "cop_z", "cop_velocity_x",
            "cop_velocity_z", "cop_speed",
        ),
    }
    name_to_index = {name: index for index, name in enumerate(gru.FEATURE_CANDIDATES)}
    calibration_rows: list[dict[str, Any]] = []
    selected_by_group: dict[str, dict[str, Any]] = {}
    for group, names in feature_names.items():
        indices = [name_to_index[name] for name in names if any(np.isfinite(s["feature_table"][:, name_to_index[name]]).any() for s in model_train)]
        run_args = model_args(args, args.horizon_seconds)
        train_examples = calibration.prepare_examples(model_train, indices, run_args)
        eval_examples = calibration.prepare_examples(calibration_sessions, indices, run_args)
        probabilities, _, _ = calibration.train_probabilities(train_examples, eval_examples, run_args)
        rows: list[dict[str, Any]] = []
        for threshold in np.round(np.arange(0.05, 0.951, 0.05), 2):
            result, _ = gru.metrics_from_predictions(eval_examples, probabilities >= threshold, f"gru_{group}")
            row = flatten(result, f"gru_{group}", float(threshold), group)
            rows.append(row)
            calibration_rows.append(row)
        selected, rule = select_threshold(pd.DataFrame(rows), args.target_far, args.minimum_recall)
        selected_by_group[group] = {"selected": selected, "selection_rule": rule, "feature_names": [gru.FEATURE_CANDIDATES[i] for i in indices]}

    calibration_frame = pd.DataFrame(calibration_rows)
    calibration_frame.to_csv(args.out_dir / "calibration_threshold_grid.csv", index=False, encoding="utf-8-sig")
    selections = pd.DataFrame([
        {
            "feature_group": group,
            "selected_threshold": value["selected"]["threshold"],
            "session_precision": value["selected"]["session_precision"],
            "session_recall": value["selected"]["session_recall"],
            "session_f1": value["selected"]["session_f1"],
            "session_nonfall_false_alarm_rate": value["selected"]["session_nonfall_false_alarm_rate"],
            "session_last_warning_lead_median_s": value["selected"]["session_last_warning_lead_median_s"],
            "selection_rule": value["selection_rule"],
            "feature_names": ";".join(value["feature_names"]),
        }
        for group, value in selected_by_group.items()
    ])
    selections.to_csv(args.out_dir / "calibration_selections.csv", index=False, encoding="utf-8-sig")

    final_rows: list[dict[str, Any]] = []
    for group, names in feature_names.items():
        selected = selected_by_group[group]["selected"]
        threshold = float(selected["threshold"])
        indices = [name_to_index[name] for name in names if any(np.isfinite(s["feature_table"][:, name_to_index[name]]).any() for s in development)]
        run_args = model_args(args, args.horizon_seconds)
        train_examples = calibration.prepare_examples(development, indices, run_args)
        frozen_examples = calibration.prepare_examples(frozen, indices, run_args)
        probabilities, _, _ = calibration.train_probabilities(train_examples, frozen_examples, run_args)
        result, _ = gru.metrics_from_predictions(frozen_examples, probabilities >= threshold, f"gru_{group}")
        final_rows.append(flatten(result, f"gru_{group}", threshold, group))
    for method, predictions in (
        ("current_yellow_rule", np.array([example["current_yellow"] for example in frozen_examples], dtype=bool)),
        ("time_to_edge", np.array([example["tte_prediction"] for example in frozen_examples], dtype=bool)),
    ):
        result, _ = gru.metrics_from_predictions(frozen_examples, predictions, method)
        final_rows.append(flatten(result, method, np.nan, "reference"))
    final_frame = pd.DataFrame(final_rows)
    final_frame.to_csv(args.out_dir / "frozen_TEST929_comparison.csv", index=False, encoding="utf-8-sig")
    summary = {
        "development_sessions": len(development),
        "calibration_sessions": len(calibration_sessions),
        "frozen_TEST929_sessions": len(frozen),
        "alignment_rule": "latest Wii COP sample at or before Unity timestamp, lag <= 0.10 s",
        "cop_alignment_rate_mean": float(alignment.match_rate.mean()),
        "cop_velocity_rows_total": int(alignment.velocity_rows.sum()),
        "calibration_selections": selected_by_group,
        "frozen_TEST929_metrics": final_rows,
        "raw_files_modified": False,
        "unity_modified": False,
    }
    (args.out_dir / "summary.json").write_text(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
