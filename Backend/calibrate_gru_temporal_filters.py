"""Select GRU temporal post-processing on development sessions only.

TEST929 remains frozen: it is evaluated only after the temporal rule has been
chosen on a development-side calibration split.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import calibrate_gru_threshold as threshold_calibration
import evaluate_gru_temporal_filters as temporal
import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "gru_temporal_filter_calibration_h05"
DEFAULT_THRESHOLD_FILE = ROOT / "gru_threshold_calibration_h05" / "selected_threshold.json"


def flatten(result: dict[str, Any], method: str, k: int, cancel_s: float | None, cancel_flags: int) -> dict[str, Any]:
    row = {
        "method": method,
        "consecutive_k": int(k),
        "cancel_duration_s": cancel_s,
        "cancel_flag_windows": int(cancel_flags),
    }
    row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
    row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
    return row


def choose(table: pd.DataFrame, target_far: float, minimum_recall: float) -> tuple[dict[str, Any], str]:
    feasible = table.loc[
        table.session_nonfall_false_alarm_rate.le(target_far + 1e-12)
        & table.session_recall.ge(minimum_recall)
    ].copy()
    if not feasible.empty:
        feasible = feasible.sort_values(
            ["session_f1", "session_last_warning_lead_median_s", "session_precision", "consecutive_k", "cancel_duration_s"],
            ascending=[False, False, False, True, True],
        )
        return feasible.iloc[0].to_dict(), "max F1 with FAR <= target and recall >= minimum"
    fallback = table.loc[table.session_recall.ge(minimum_recall)].copy()
    if not fallback.empty:
        fallback = fallback.sort_values(
            ["session_nonfall_false_alarm_rate", "session_f1", "session_last_warning_lead_median_s"],
            ascending=[True, False, False],
        )
        return fallback.iloc[0].to_dict(), "minimum FAR with recall >= minimum (target FAR not reached)"
    fallback = table.sort_values(
        ["session_nonfall_false_alarm_rate", "session_f1", "session_recall"],
        ascending=[True, False, False],
    )
    return fallback.iloc[0].to_dict(), "minimum FAR fallback (recall target not reached)"


def run(args: argparse.Namespace) -> dict[str, Any]:
    random.seed(args.seed)
    np.random.seed(args.seed)
    threshold = float(json.loads(args.threshold_file.read_text(encoding="utf-8"))["selected_threshold"])
    development: list[dict[str, Any]] = []
    for manifest_value in gru.DEFAULT_TRAIN_MANIFESTS:
        loaded, _ = gru.load_manifest_sessions(Path(manifest_value), None, True, False)
        development.extend(loaded)
    model_train, calibration_sessions = gru.session_split(development, args.validation_fraction, args.seed)
    indices = threshold_calibration.feature_indices(model_train)
    train_examples = threshold_calibration.prepare_examples(model_train, indices, args)
    calibration_examples = threshold_calibration.prepare_examples(calibration_sessions, indices, args)
    calibration_prob, _, calibration_training = threshold_calibration.train_probabilities(train_examples, calibration_examples, args)
    calibration_by_id = {str(session["session_id"]): session for session in calibration_sessions}

    rows: list[dict[str, Any]] = []
    durations = [None] + sorted({round(float(value), 6) for value in args.cancel_durations if float(value) > 0})
    for k in (1, 2, 3, 4):
        for cancel_s in durations:
            if cancel_s is None:
                cancel_flags = None
                cancel_count = 0
            else:
                cancel_flags, _ = temporal._inward_flags(calibration_examples, calibration_by_id, cancel_s)
                cancel_count = int(cancel_flags.sum())
            predictions = temporal._temporal_predictions(
                calibration_examples,
                calibration_prob >= threshold,
                args.stride_seconds,
                k=k,
                cancel_flags=cancel_flags,
            )
            result, _ = gru.metrics_from_predictions(calibration_examples, predictions, f"k{k}_cancel{cancel_s}")
            rows.append(flatten(result, f"k{k}_cancel{cancel_s}", k, cancel_s, cancel_count))
    table = pd.DataFrame(rows)
    selected, selection_rule = choose(table, args.target_far, args.minimum_recall)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out_dir / "calibration_grid.csv", index=False, encoding="utf-8-sig")

    # Retrain on all development sessions, then evaluate frozen TEST929 once.
    final_train_examples = threshold_calibration.prepare_examples(development, indices, args)
    frozen: list[dict[str, Any]] = []
    for manifest_value in gru.DEFAULT_HELDOUT_MANIFESTS:
        loaded, _ = gru.load_manifest_sessions(Path(manifest_value), None, False, False)
        frozen.extend(loaded)
    frozen_examples = threshold_calibration.prepare_examples(frozen, indices, args)
    frozen_prob, _, final_training = threshold_calibration.train_probabilities(final_train_examples, frozen_examples, args)
    frozen_by_id = {str(session["session_id"]): session for session in frozen}
    selected_k = int(selected["consecutive_k"])
    selected_cancel = selected["cancel_duration_s"]
    selected_cancel = None if pd.isna(selected_cancel) else float(selected_cancel)
    selected_flags = None if selected_cancel is None else temporal._inward_flags(frozen_examples, frozen_by_id, selected_cancel)[0]
    selected_pred = temporal._temporal_predictions(
        frozen_examples,
        frozen_prob >= threshold,
        args.stride_seconds,
        k=selected_k,
        cancel_flags=selected_flags,
    )
    baseline_rows: list[dict[str, Any]] = []
    for method, pred, k, cancel in (
        ("current_yellow_rule", np.array([example["current_yellow"] for example in frozen_examples], dtype=bool), 0, None),
        ("time_to_edge", np.array([example["tte_prediction"] for example in frozen_examples], dtype=bool), 0, None),
        ("gru_calibrated_raw", frozen_prob >= threshold, 1, None),
        (f"gru_selected_k{selected_k}_cancel{selected_cancel}", selected_pred, selected_k, selected_cancel),
    ):
        result, details = gru.metrics_from_predictions(frozen_examples, pred, method)
        row = flatten(result, method, k, cancel, int(selected_flags.sum()) if method.startswith("gru_selected") and selected_flags is not None else 0)
        baseline_rows.append(row)
        if method.startswith("gru_selected"):
            pd.DataFrame(details).to_csv(args.out_dir / "frozen_TEST929_selected_session_metrics.csv", index=False, encoding="utf-8-sig")
    comparison = pd.DataFrame(baseline_rows)
    comparison.to_csv(args.out_dir / "frozen_TEST929_comparison.csv", index=False, encoding="utf-8-sig")
    summary = {
        "threshold": threshold,
        "selection_rule": selection_rule,
        "target_false_alarm_rate": args.target_far,
        "minimum_recall": args.minimum_recall,
        "development_sessions": len(development),
        "model_train_sessions": len(model_train),
        "calibration_sessions": len(calibration_sessions),
        "frozen_TEST929_sessions": len(frozen),
        "selected_filter": {
            "consecutive_k": selected_k,
            "cancel_duration_s": selected_cancel,
            "cancel_velocity_rule": "preferred radial velocity < 0",
            "calibration_cancel_flag_windows": int(selected.get("cancel_flag_windows", 0)),
        },
        "calibration_metrics_selected": selected,
        "frozen_TEST929_metrics": baseline_rows,
        "raw_files_modified": False,
        "unity_modified": False,
        "calibration_training": calibration_training,
        "final_training": final_training,
    }
    (args.out_dir / "selected_temporal_filter.json").write_text(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_dir / "README.md").write_text(
        "# GRU temporal filter calibration\n\n"
        "Temporal rule selection uses only a development-side calibration split. TEST929 is evaluated once after retraining on all development sessions. "
        "No Unity or raw telemetry file was modified.\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--threshold-file", type=Path, default=DEFAULT_THRESHOLD_FILE)
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
    parser.add_argument("--cancel-durations", type=float, nargs="+", default=[0.2, 0.25, 0.3, 0.5, 0.75])
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    print(json.dumps(gru.finite_json(run(args)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
