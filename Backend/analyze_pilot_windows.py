"""Compare normal versus pre-fall telemetry windows for the pilot dataset.

Outputs are exploratory only: thresholds are estimated from the same included
pilot data.  Final model evaluation must fit thresholds on training data only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


HORIZON_SECONDS = 2.0


def included_sessions(user_dirs: list[Path]) -> list[tuple[Path, str]]:
    result = []
    seen = set()
    for user_dir in user_dirs:
        for folder in sorted(user_dir.glob("session_*")):
            if folder in seen:
                continue
            quality_path = folder / "quality.json"
            if not quality_path.exists():
                continue
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            status = quality.get("analysis_status")
            if status in ("included", "included_normal_only"):
                result.append((folder, status))
                seen.add(folder)
    return result


def window_features(folder: Path, analysis_status: str = "included") -> tuple[pd.DataFrame, pd.DataFrame]:
    aligned = pd.read_csv(folder / "aligned_60hz.csv")
    windows = pd.read_csv(folder / "windows.csv")
    if analysis_status == "included_normal_only":
        windows = windows[windows["failure_label"].eq(0)].copy()
    raw = pd.read_csv(folder / "raw.csv")
    raw["fall_event"] = raw["fall_event"].astype(str).str.strip().str.lower().eq("true")
    fall_times = raw.loc[
        raw["source"].astype(str).str.lower().eq("unity") & raw["fall_event"],
        "backend_timestamp",
    ].to_numpy(float)
    rows = []
    audits = []
    for i, row in windows.iterrows():
        segment = aligned[
            (aligned.backend_timestamp >= row.window_start)
            & (aligned.backend_timestamp <= row.window_end)
        ]
        if len(segment) < 2:
            continue
        duration = float(segment.backend_timestamp.iloc[-1] - segment.backend_timestamp.iloc[0])
        distance_rate = (
            float(segment.distance_to_hole.iloc[-1] - segment.distance_to_hole.iloc[0]) / duration
            if duration > 0 else np.nan
        )
        dx = segment.cop_x.to_numpy(float) - segment.cop_x.mean()
        dz = segment.cop_z.to_numpy(float) - segment.cop_z.mean()
        cop_stability_rmse = float(np.sqrt(np.mean(dx * dx + dz * dz)))
        next_fall = fall_times[fall_times > row.window_end]
        seconds_to_fall = float(next_fall[0] - row.window_end) if len(next_fall) else np.nan
        expected = int(np.isfinite(seconds_to_fall) and seconds_to_fall <= HORIZON_SECONDS)
        audits.append({
            "session_id": folder.name,
            "window_index": int(i),
            "window_end": row.window_end,
            "failure_label": int(row.failure_label),
            "expected_label": expected,
            "seconds_to_next_fall": seconds_to_fall,
            "label_matches_event_rule": int(row.failure_label) == expected,
        })
        rows.append({
            **row.to_dict(),
            "session_id": folder.name,
            "cop_stability_rmse": cop_stability_rmse,
            "distance_rate": distance_rate,
            "abs_distance_rate": abs(distance_rate),
        })
    return pd.DataFrame(rows), pd.DataFrame(audits)


def metrics(y: pd.Series, predicted: pd.Series) -> dict:
    tp = int(((y == 1) & (predicted == 1)).sum())
    fp = int(((y == 0) & (predicted == 1)).sum())
    tn = int(((y == 0) & (predicted == 0)).sum())
    fn = int(((y == 1) & (predicted == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def plot_boxplots(features: pd.DataFrame, output: Path) -> None:
    columns = [
        ("cop_speed_mean", "COP speed (mean)"),
        ("cop_stability_rmse", "COP stability RMSE"),
        ("abs_distance_rate", "Absolute distance-change rate"),
    ]
    plt.rcParams.update({
        "font.family": "DejaVu Serif",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "figure.dpi": 160,
    })
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.6), constrained_layout=True)
    labels = [
        f"Normal\n(n={int((features.failure_label == 0).sum()):,})",
        f"Pre-fall\n(n={int((features.failure_label == 1).sum()):,})",
    ]
    for ax, (column, title) in zip(axes, columns):
        values = [
            features.loc[features.failure_label == label, column].dropna().to_numpy()
            for label in (0, 1)
        ]
        box = ax.boxplot(
            values,
            tick_labels=labels,
            showfliers=False,
            patch_artist=True,
            widths=0.58,
            medianprops={"color": "#222222", "linewidth": 1.2},
            whiskerprops={"color": "#555555", "linewidth": 0.9},
            capprops={"color": "#555555", "linewidth": 0.9},
        )
        for patch, color in zip(box["boxes"], ("#B8C7D9", "#D99A99")):
            patch.set_facecolor(color)
            patch.set_edgecolor("#444444")
            patch.set_linewidth(0.9)
        ax.set_title(title)
        ax.set_ylabel("Metric value")
        ax.grid(axis="y", color="#D9D9D9", linewidth=0.7, alpha=0.8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#666666")
        ax.spines["bottom"].set_color("#666666")
    fig.suptitle("Normal and pre-fall window feature distributions", fontsize=13)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_timeline(features: pd.DataFrame, output: Path) -> None:
    sessions = features.loc[features.failure_label == 1, "session_id"].unique()
    if not len(sessions):
        return
    plt.rcParams.update({
        "font.family": "DejaVu Serif",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
    })
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True, constrained_layout=True)
    for session in sessions:
        subset = features[features.session_id == session].copy()
        if not len(subset):
            continue
        relative_time = subset.window_end - subset.window_end.max()
        positive = subset.failure_label == 1
        for ax, col, label in zip(
            axes,
            ("cop_speed_mean", "cop_stability_rmse", "distance_rate"),
            ("COP speed", "COP stability RMSE", "Distance-change rate"),
        ):
            ax.plot(relative_time, subset[col], color="#4C78A8", alpha=0.42, linewidth=0.9)
            ax.scatter(relative_time[positive], subset.loc[positive, col], color="#B44C4C", s=16, zorder=3)
            ax.set_ylabel(label)
            ax.grid(color="#D9D9D9", linewidth=0.7, alpha=0.8)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
    axes[-1].set_xlabel("Window end relative to session end (s)")
    fig.suptitle("Feature trajectories in sessions containing pre-fall windows", fontsize=13)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_dirs", type=Path, nargs="+", help="one or more username directories for the same participant")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output = args.output_dir or args.user_dirs[0] / "pilot_analysis"
    output.mkdir(parents=True, exist_ok=True)
    session_entries = included_sessions(args.user_dirs)
    session_dirs = [folder for folder, _ in session_entries]
    feature_frames, audit_frames = zip(*(
        window_features(folder, status) for folder, status in session_entries
    ))
    features = pd.concat(feature_frames, ignore_index=True)
    audits = pd.concat(audit_frames, ignore_index=True)
    features.to_csv(output / "included_window_features.csv", index=False)
    audits.to_csv(output / "failure_label_audit.csv", index=False)

    normal = features[features.failure_label == 0]
    thresholds = {
        "cop_stability_rmse": float(normal.cop_stability_rmse.quantile(0.95)),
        "cop_speed_mean": float(normal.cop_speed_mean.quantile(0.95)),
        "abs_distance_rate": float(normal.abs_distance_rate.quantile(0.95)),
    }
    features["heuristic_alert"] = (
        (features.cop_stability_rmse >= thresholds["cop_stability_rmse"])
        | (features.cop_speed_mean >= thresholds["cop_speed_mean"])
        | (features.abs_distance_rate >= thresholds["abs_distance_rate"])
    ).astype(int)
    features.to_csv(output / "included_window_features.csv", index=False)
    summary_rows = []
    for col in ("cop_speed_mean", "cop_speed_max", "cop_x_std", "cop_z_std", "cop_stability_rmse", "distance_rate", "abs_distance_rate"):
        for label, name in ((0, "normal"), (1, "pre_fall")):
            values = features.loc[features.failure_label == label, col].dropna()
            summary_rows.append({"feature": col, "group": name, "n": len(values), "mean": values.mean(), "median": values.median(), "std": values.std()})
    pd.DataFrame(summary_rows).to_csv(output / "feature_summary.csv", index=False)
    baseline = metrics(features.failure_label.astype(int), features.heuristic_alert.astype(int))
    audit_ok = bool(audits.label_matches_event_rule.all())
    report = {
        "included_sessions": [folder.name for folder in session_dirs],
        "excluded_sessions_not_used": sorted([
            folder.name for user_dir in args.user_dirs for folder in user_dir.glob("session_*")
            if folder.is_dir() and folder not in session_dirs
        ]),
        "windows": int(len(features)),
        "normal_windows": int((features.failure_label == 0).sum()),
        "pre_fall_windows": int((features.failure_label == 1).sum()),
        "failure_label_audit": {"all_match_event_rule": audit_ok, "matching_windows": int(audits.label_matches_event_rule.sum()), "windows_checked": int(len(audits))},
        "exploratory_heuristic": {"definition": "alert if any feature exceeds its 95th percentile among normal pilot windows", "thresholds": thresholds, "metrics": baseline},
        "important_note": "Exploratory pilot result only. Thresholds were estimated from the same included sessions; future validation must fit thresholds on training sessions only.",
    }
    (output / "analysis_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    plot_boxplots(features, output / "normal_vs_pre_fall_boxplots.png")
    plot_timeline(features, output / "pre_fall_feature_timelines.png")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
