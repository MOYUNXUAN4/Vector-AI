"""Calibrate a GRU probability threshold without touching Unity or TEST929.

The model is trained on one part of the development pool and the threshold is
selected on complete validation sessions from that same development pool.  A
fresh model is then trained on all development sessions and evaluated once on
frozen TEST929 with the selected threshold.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "gru_threshold_calibration_h05"


def feature_indices(sessions: list[dict[str, Any]]) -> list[int]:
    return [
        index
        for index, _ in enumerate(gru.FEATURE_CANDIDATES)
        if any(np.isfinite(session["feature_table"][:, index]).any() for session in sessions)
    ]


def prepare_examples(sessions: list[dict[str, Any]], indices: list[int], args: argparse.Namespace) -> list[dict[str, Any]]:
    for session in sessions:
        gru.tte_rule_mask(session, gru.DEFAULT_TTE)
        gru.build_examples(
            session,
            indices,
            args.horizon_seconds,
            args.window_seconds,
            args.stride_seconds,
            args.sequence_length,
        )
    return gru.flatten_examples(sessions)


def model_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        sequence_length=args.sequence_length,
        hidden_size=args.hidden_size,
        layers=1,
        dropout=0.0,
        batch_size=args.batch_size,
        learning_rate=1e-3,
        weight_decay=1e-5,
        epochs=args.epochs,
        device="cpu",
        seed=args.seed,
    )


def train_probabilities(train_examples: list[dict[str, Any]], eval_examples: list[dict[str, Any]], args: argparse.Namespace) -> tuple[np.ndarray, gru.TrainOnlyScaler, dict[str, Any]]:
    scaler = gru.TrainOnlyScaler.fit(np.stack([example["sequence"] for example in train_examples]))
    probabilities, result, history = gru.fit_gru(train_examples, eval_examples, scaler, model_args(args))
    result["history"] = history
    return probabilities, scaler, result


def flatten_session_metric(result: dict[str, Any], threshold: float) -> dict[str, Any]:
    row = {"threshold": threshold}
    row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
    row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
    return row


def choose_threshold(table: pd.DataFrame, target_far: float, min_recall: float) -> tuple[float, str]:
    feasible = table.loc[
        table.session_nonfall_false_alarm_rate.le(target_far + 1e-12)
        & table.session_recall.ge(min_recall)
    ].copy()
    if not feasible.empty:
        feasible = feasible.sort_values(
            ["session_f1", "session_last_warning_lead_median_s", "session_precision", "threshold"],
            ascending=[False, False, False, False],
        )
        return float(feasible.iloc[0].threshold), "max F1 with FAR <= target and recall >= minimum"
    fallback = table.loc[table.session_recall.ge(min_recall)].copy()
    if not fallback.empty:
        fallback = fallback.sort_values(
            ["session_nonfall_false_alarm_rate", "session_f1", "session_last_warning_lead_median_s"],
            ascending=[True, False, False],
        )
        return float(fallback.iloc[0].threshold), "minimum FAR with recall >= minimum (target FAR not reached)"
    fallback = table.sort_values(
        ["session_nonfall_false_alarm_rate", "session_f1", "session_recall"],
        ascending=[True, False, False],
    )
    return float(fallback.iloc[0].threshold), "minimum FAR fallback (recall target not reached)"


def write_plot(table: pd.DataFrame, threshold: float, target_far: float, out: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11, "axes.labelsize": 10})
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 4.0), constrained_layout=True)
    axes[0].plot(table.threshold, table.session_f1, color="#2A7F9E", linewidth=2, label="Session F1")
    axes[0].plot(table.threshold, table.session_recall, color="#6A3D9A", linewidth=2, label="Recall")
    axes[0].axvline(threshold, color="#C73E36", linestyle="--", linewidth=1.5, label=f"Selected {threshold:.2f}")
    axes[0].set_title("Quality vs threshold"); axes[0].set_xlabel("GRU probability threshold"); axes[0].set_ylabel("Metric"); axes[0].set_ylim(0, 1)
    axes[1].plot(table.threshold, table.session_nonfall_false_alarm_rate * 100, color="#C73E36", linewidth=2)
    axes[1].axhline(target_far * 100, color="#555555", linestyle=":", linewidth=1.3, label=f"Target {target_far:.0%}")
    axes[1].axvline(threshold, color="#C73E36", linestyle="--", linewidth=1.5)
    axes[1].set_title("Non-fall false alarms"); axes[1].set_xlabel("GRU probability threshold"); axes[1].set_ylabel("Sessions (%)"); axes[1].set_ylim(0, 105); axes[1].legend(frameon=False, fontsize=8)
    axes[2].plot(table.threshold, table.session_last_warning_lead_median_s, color="#1764A0", linewidth=2)
    axes[2].axvline(threshold, color="#C73E36", linestyle="--", linewidth=1.5)
    axes[2].set_title("Lead time"); axes[2].set_xlabel("GRU probability threshold"); axes[2].set_ylabel("Median valid lead (s)")
    for ax in axes:
        ax.grid(color="#D8D8D8", linewidth=0.5); ax.spines[["top", "right"]].set_visible(False); ax.set_axisbelow(True)
    fig.suptitle("Development-session GRU threshold calibration (H=0.5 s)", color="#23395B", fontweight="bold")
    fig.savefig(out / "figure_threshold_calibration.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(out / "figure_threshold_calibration.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


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
    if not 0 < args.validation_fraction < 1:
        raise ValueError("validation fraction must be in (0, 1)")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed); np.random.seed(args.seed)

    train_manifests = [Path(path) for path in gru.DEFAULT_TRAIN_MANIFESTS]
    development: list[dict[str, Any]] = []
    manifest_notes: list[dict[str, Any]] = []
    for manifest in train_manifests:
        loaded, note = gru.load_manifest_sessions(manifest, None, True, False)
        development.extend(loaded); manifest_notes.append(note)
    if not development:
        raise RuntimeError("No usable development sessions")
    model_train, calibration_sessions = gru.session_split(development, args.validation_fraction, args.seed)
    indices = feature_indices(model_train)
    if not indices:
        raise RuntimeError("No usable telemetry features")
    train_examples = prepare_examples(model_train, indices, args)
    calibration_examples = prepare_examples(calibration_sessions, indices, args)
    if not train_examples or not calibration_examples:
        raise RuntimeError("Training or calibration split produced no windows")
    calibration_prob, scaler, train_result = train_probabilities(train_examples, calibration_examples, args)

    rows: list[dict[str, Any]] = []
    for threshold in np.round(np.arange(0.05, 0.951, 0.01), 2):
        result, _ = gru.metrics_from_predictions(calibration_examples, calibration_prob >= threshold, "gru_calibration")
        rows.append(flatten_session_metric(result, float(threshold)))
    table = pd.DataFrame(rows)
    selected, selection_rule = choose_threshold(table, args.target_far, args.minimum_recall)
    table.to_csv(args.out_dir / "threshold_grid.csv", index=False, encoding="utf-8-sig")
    write_plot(table, selected, args.target_far, args.out_dir)
    selected_row = table.loc[np.isclose(table.threshold, selected)].iloc[0].to_dict()

    # Retrain once on every development session; only now touch frozen TEST929.
    all_dev = development
    test_sessions: list[dict[str, Any]] = []
    for manifest in [Path(path) for path in gru.DEFAULT_HELDOUT_MANIFESTS]:
        loaded, _ = gru.load_manifest_sessions(manifest, None, False, False)
        test_sessions.extend(loaded)
    final_train_examples = prepare_examples(all_dev, indices, args)
    test_examples = prepare_examples(test_sessions, indices, args)
    test_prob, final_scaler, final_result = train_probabilities(final_train_examples, test_examples, args)
    final_rows: list[dict[str, Any]] = []
    for method, predictions in (
        ("current_yellow_rule", np.array([example["current_yellow"] for example in test_examples], dtype=bool)),
        ("time_to_edge", np.array([example["tte_prediction"] for example in test_examples], dtype=bool)),
        ("gru_calibrated", test_prob >= selected),
    ):
        result, details = gru.metrics_from_predictions(test_examples, predictions, method)
        final_rows.append({"method": method, **flatten_session_metric(result, selected if method == "gru_calibrated" else math.nan)})
        if method == "gru_calibrated":
            pd.DataFrame(details).to_csv(args.out_dir / "frozen_TEST929_session_metrics.csv", index=False, encoding="utf-8-sig")
    final_frame = pd.DataFrame(final_rows)
    final_frame.to_csv(args.out_dir / "frozen_TEST929_comparison.csv", index=False, encoding="utf-8-sig")
    selected_payload = {
        "horizon_seconds": args.horizon_seconds,
        "selected_threshold": selected,
        "selection_rule": selection_rule,
        "target_false_alarm_rate": args.target_far,
        "minimum_recall": args.minimum_recall,
        "calibration_sessions": len(calibration_sessions),
        "calibration_fall_sessions": int(sum(np.isfinite(s["first_event_ts"]) for s in calibration_sessions)),
        "calibration_metrics_at_selected_threshold": selected_row,
        "test_set_used_for_selection": False,
        "frozen_test_dataset": "TEST929",
        "raw_files_modified": False,
    }
    (args.out_dir / "selected_threshold.json").write_text(json.dumps(gru.finite_json(selected_payload), indent=2, ensure_ascii=False), encoding="utf-8")
    config = {
        "features": [gru.FEATURE_CANDIDATES[i] for i in indices],
        "development_sessions": len(development),
        "model_train_sessions": len(model_train),
        "calibration_sessions": len(calibration_sessions),
        "frozen_TEST929_sessions": len(test_sessions),
        "train_only_scaler": True,
        "manifest_notes": manifest_notes,
        "calibration_training": train_result,
        "final_training": final_result,
    }
    (args.out_dir / "config.json").write_text(json.dumps(gru.finite_json(config), indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_dir / "README.md").write_text(
        "# GRU threshold calibration\n\n"
        "The threshold was selected only on complete development-side validation sessions. "
        "TEST929 was not used for selection and was evaluated once after retraining on all development sessions. "
        "No Unity or raw telemetry file was modified.\n\n"
        f"Horizon: {args.horizon_seconds:g}s. Target non-fall false-alarm rate: {args.target_far:.0%}. "
        f"Minimum recall: {args.minimum_recall:.0%}. Selected threshold: {selected:.2f}.\n",
        encoding="utf-8",
    )
    print(json.dumps({"selected_threshold": selected, "selection_rule": selection_rule, "calibration": selected_row, "frozen_TEST929": final_rows}, indent=2, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
