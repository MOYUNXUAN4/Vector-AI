"""Offline GRU feature-set and future-horizon experiment.

All feature/horizon choices are scored on a development-side calibration
split.  Only the selected configuration is retrained on all development
sessions and evaluated once on frozen TEST929.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import calibrate_gru_threshold as calibration
import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "gru_feature_horizon_experiment"

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "all_current": tuple(gru.FEATURE_CANDIDATES),
    "edge_kinematic": (
        "ball_radial_distance",
        "ball_radial_velocity",
        "target_edge_distance",
        "target_edge_radial_velocity",
        "directional_edge_distance",
        "cop_velocity_x",
        "cop_velocity_z",
        "cop_speed",
        "platform_tilt",
        "platform_level",
        "difficulty",
        "platform_radius",
        "ball_radius",
        "edge_warning_margin",
        "edge_warning_radius",
    ),
    "motion_control": (
        "ball_velocity_x",
        "ball_velocity_z",
        "ball_radial_velocity",
        "target_edge_radial_velocity",
        "cop_velocity_x",
        "cop_velocity_z",
        "cop_speed",
        "platform_tilt",
        "difficulty",
        "platform_level",
    ),
}


def model_args(args: argparse.Namespace, horizon: float) -> SimpleNamespace:
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
        horizon_seconds=horizon,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
    )


def load_pool(manifests: list[Path], training: bool) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for manifest in manifests:
        loaded, _ = gru.load_manifest_sessions(manifest, None, training, False)
        sessions.extend(loaded)
    return sessions


def flatten(result: dict[str, Any], feature_group: str, horizon: float, threshold: float) -> dict[str, Any]:
    row = {"feature_group": feature_group, "horizon_s": horizon, "threshold": threshold}
    row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
    row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
    return row


def choose_threshold(table: pd.DataFrame, target_far: float, min_recall: float) -> tuple[dict[str, Any], str]:
    feasible = table.loc[
        table.session_nonfall_false_alarm_rate.le(target_far + 1e-12)
        & table.session_recall.ge(min_recall)
    ].copy()
    if not feasible.empty:
        feasible = feasible.sort_values(
            ["session_f1", "session_last_warning_lead_median_s", "session_precision", "threshold"],
            ascending=[False, False, False, False],
        )
        return feasible.iloc[0].to_dict(), "max F1 with FAR <= target and recall >= minimum"
    fallback = table.loc[table.session_recall.ge(min_recall)].copy()
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


def plot_calibration(grid: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.0), constrained_layout=True)
    for feature_group, marker, color in zip(FEATURE_GROUPS, ["o", "s", "^"], ["#2A7F9E", "#C73E36", "#6A3D9A"]):
        subset = grid.loc[grid.feature_group.eq(feature_group)]
        axes[0].plot(subset.horizon_s, subset.session_f1, marker=marker, color=color, linewidth=1.8, label=feature_group)
        axes[1].plot(subset.horizon_s, subset.session_nonfall_false_alarm_rate * 100, marker=marker, color=color, linewidth=1.8, label=feature_group)
    axes[0].set_title("Development calibration F1")
    axes[0].set_ylabel("Session F1")
    axes[0].set_ylim(0, 1)
    axes[1].set_title("Development non-fall FAR")
    axes[1].set_ylabel("Sessions (%)")
    axes[1].set_ylim(0, 100)
    for ax in axes:
        ax.set_xlabel("Future prediction horizon (s)")
        ax.grid(color="#D8D8D8", linewidth=0.5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle("GRU feature-set and horizon calibration", color="#23395B", fontweight="bold")
    fig.savefig(out / "figure_feature_horizon_calibration.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(out / "figure_feature_horizon_calibration.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--horizons", type=float, nargs="+", default=[0.5, 0.75, 1.0])
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
    random.seed(args.seed)
    np.random.seed(args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    development = load_pool([Path(path) for path in gru.DEFAULT_TRAIN_MANIFESTS], True)
    model_train, calibration_sessions = gru.session_split(development, args.validation_fraction, args.seed)
    frozen = load_pool([Path(path) for path in gru.DEFAULT_HELDOUT_MANIFESTS], False)
    threshold_grid = np.round(np.arange(0.05, 0.951, 0.05), 2)
    calibration_rows: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []

    for feature_group, names in FEATURE_GROUPS.items():
        name_to_index = {name: index for index, name in enumerate(gru.FEATURE_CANDIDATES)}
        indices = [name_to_index[name] for name in names if name in name_to_index and any(np.isfinite(session["feature_table"][:, name_to_index[name]]).any() for session in model_train)]
        if not indices:
            continue
        for horizon in sorted(set(float(value) for value in args.horizons)):
            run_args = model_args(args, horizon)
            train_examples = calibration.prepare_examples(model_train, indices, run_args)
            calibration_examples = calibration.prepare_examples(calibration_sessions, indices, run_args)
            probabilities, _, _ = calibration.train_probabilities(train_examples, calibration_examples, run_args)
            rows: list[dict[str, Any]] = []
            for threshold in threshold_grid:
                result, _ = gru.metrics_from_predictions(calibration_examples, probabilities >= threshold, "gru_calibration")
                row = flatten(result, feature_group, horizon, float(threshold))
                rows.append(row)
                calibration_rows.append(row)
            selected, selection_rule = choose_threshold(pd.DataFrame(rows), args.target_far, args.minimum_recall)
            selections.append({
                "feature_group": feature_group,
                "horizon_s": horizon,
                "feature_names": [gru.FEATURE_CANDIDATES[index] for index in indices],
                "selection_rule": selection_rule,
                "selected": selected,
            })

    grid = pd.DataFrame(calibration_rows)
    grid.to_csv(args.out_dir / "calibration_threshold_grid.csv", index=False, encoding="utf-8-sig")
    selection_frame = pd.DataFrame([
        {
            "feature_group": item["feature_group"],
            "horizon_s": item["horizon_s"],
            "selected_threshold": item["selected"]["threshold"],
            "selection_rule": item["selection_rule"],
            "session_precision": item["selected"]["session_precision"],
            "session_recall": item["selected"]["session_recall"],
            "session_f1": item["selected"]["session_f1"],
            "session_nonfall_false_alarm_rate": item["selected"]["session_nonfall_false_alarm_rate"],
            "session_last_warning_lead_median_s": item["selected"]["session_last_warning_lead_median_s"],
        }
        for item in selections
    ])
    selection_frame.to_csv(args.out_dir / "calibration_selections.csv", index=False, encoding="utf-8-sig")
    plot_calibration(selection_frame, args.out_dir)

    # Select only from development calibration results, then touch TEST929.
    feasible = selection_frame.loc[
        selection_frame.session_nonfall_false_alarm_rate.le(args.target_far + 1e-12)
        & selection_frame.session_recall.ge(args.minimum_recall)
    ].copy()
    if not feasible.empty:
        selected_combo = feasible.sort_values(["session_f1", "session_last_warning_lead_median_s"], ascending=[False, False]).iloc[0]
        combo_rule = "best calibration F1 under FAR and recall constraints"
    else:
        selected_combo = selection_frame.loc[selection_frame.session_recall.ge(args.minimum_recall)].sort_values(["session_nonfall_false_alarm_rate", "session_f1"], ascending=[True, False]).iloc[0]
        combo_rule = "minimum calibration FAR with recall constraint"
    feature_group = str(selected_combo.feature_group)
    horizon = float(selected_combo.horizon_s)
    threshold = float(selected_combo.selected_threshold)
    names = FEATURE_GROUPS[feature_group]
    name_to_index = {name: index for index, name in enumerate(gru.FEATURE_CANDIDATES)}
    indices = [name_to_index[name] for name in names if name in name_to_index and any(np.isfinite(session["feature_table"][:, name_to_index[name]]).any() for session in development)]
    run_args = model_args(args, horizon)
    final_train_examples = calibration.prepare_examples(development, indices, run_args)
    frozen_examples = calibration.prepare_examples(frozen, indices, run_args)
    probabilities, final_scaler, final_training = calibration.train_probabilities(final_train_examples, frozen_examples, run_args)
    final_rows: list[dict[str, Any]] = []
    for method, predictions in (
        ("current_yellow_rule", np.array([example["current_yellow"] for example in frozen_examples], dtype=bool)),
        ("time_to_edge", np.array([example["tte_prediction"] for example in frozen_examples], dtype=bool)),
        (f"gru_selected_{feature_group}_h{horizon:g}", probabilities >= threshold),
    ):
        result, _ = gru.metrics_from_predictions(frozen_examples, predictions, method)
        row = {"method": method, "feature_group": feature_group, "horizon_s": horizon, "threshold": threshold if method.startswith("gru_") else np.nan}
        row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
        row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
        final_rows.append(row)
    final_frame = pd.DataFrame(final_rows)
    final_frame.to_csv(args.out_dir / "frozen_TEST929_comparison.csv", index=False, encoding="utf-8-sig")
    summary = {
        "development_sessions": len(development),
        "model_train_sessions": len(model_train),
        "calibration_sessions": len(calibration_sessions),
        "frozen_TEST929_sessions": len(frozen),
        "combo_selection_rule": combo_rule,
        "selected_feature_group": feature_group,
        "selected_horizon_s": horizon,
        "selected_threshold": threshold,
        "selected_feature_names": [gru.FEATURE_CANDIDATES[index] for index in indices],
        "calibration_selected_metrics": selected_combo.to_dict(),
        "frozen_TEST929_metrics": final_rows,
        "raw_files_modified": False,
        "unity_modified": False,
        "training": final_training,
        "train_only_scaler": final_scaler.to_json(),
    }
    (args.out_dir / "selected_configuration.json").write_text(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_dir / "README.md").write_text(
        "# Offline GRU feature and horizon experiment\n\n"
        "Feature groups and prediction horizons were selected on development-side calibration sessions. TEST929 was evaluated once after retraining the selected configuration on the full development pool. No Unity or raw telemetry file was modified.\n",
        encoding="utf-8",
    )
    print(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
