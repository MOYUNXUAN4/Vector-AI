"""Compare control, recoverable approach, directional exit, and sway-to-exit groups."""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu


GROUPS = ["normal_control", "recoverable_shift", "directional_exit", "sway_then_exit"]
LABELS = {
    "normal_control": "Normal control",
    "recoverable_shift": "Recovered edge approach",
    "directional_exit": "Directional pre-exit",
    "sway_then_exit": "Sway pre-exit",
}
COLORS = {
    "normal_control": "#4C78A8",
    "recoverable_shift": "#59A14F",
    "directional_exit": "#E15759",
    "sway_then_exit": "#B279A2",
}
FEATURES = [
    "distance_slope", "recent_distance_slope", "cop_speed_mean",
    "cop_net_displacement", "cop_straightness", "cop_direction_consistency",
]


def metadata_map(user_dirs: list[Path]) -> dict[str, dict]:
    result = {}
    for user_dir in user_dirs:
        for folder in user_dir.glob("session_*"):
            qpath = folder / "quality.json"
            if qpath.exists():
                result[folder.name] = json.loads(qpath.read_text(encoding="utf-8"))
    return result


def assign_group(row: pd.Series, metadata: dict[str, dict]) -> str | None:
    q = metadata.get(row.session_id, {})
    group = q.get("analysis_group")
    if group == "normal_control" and row.failure_label == 0:
        return "normal_control"
    if group == "recoverable_directional_shift" and row.failure_label == 0:
        return "recoverable_shift"
    if group == "directional_edge_exit" and row.failure_label == 1:
        return "directional_exit"
    if group == "sway_then_edge_exit" and row.failure_label == 1:
        return "sway_then_exit"
    return None


def select_comparison_windows(frame: pd.DataFrame) -> pd.DataFrame:
    selected = []
    for (group, sid), subset in frame.groupby(["comparison_group", "session_id"]):
        if group in ("normal_control", "recoverable_shift"):
            cutoff = subset.distance_slope.quantile(.90)
            subset = subset[subset.distance_slope >= cutoff].copy()
            subset["selection_rule"] = "top 10% edgeward distance slope within session"
        else:
            subset = subset[subset.failure_label.eq(1)].copy()
            subset["selection_rule"] = "within 2 seconds before Unity edge exit"
        selected.append(subset)
    return pd.concat(selected, ignore_index=True)


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    if not len(a) or not len(b):
        return np.nan
    return float((np.sum(a[:, None] > b[None, :]) - np.sum(a[:, None] < b[None, :])) / (len(a) * len(b)))


def holm_adjust(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = np.empty(len(pvalues), float)
    running = 0.0
    m = len(pvalues)
    for rank, idx in enumerate(order):
        value = min(1.0, (m-rank) * pvalues[idx])
        running = max(running, value)
        adjusted[idx] = running
    return adjusted.tolist()


def statistics(session_summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    omnibus, pairwise = [], []
    for feature in FEATURES:
        arrays = [session_summary.loc[session_summary.comparison_group.eq(g), feature].dropna().to_numpy() for g in GROUPS]
        stat, p = kruskal(*arrays)
        omnibus.append({"feature": feature, "test": "Kruskal-Wallis", "statistic": stat, "p_value": p,
                         "group_session_counts": json.dumps({g: int(len(a)) for g, a in zip(GROUPS, arrays)})})
        feature_rows = []
        for ga, gb in combinations(GROUPS, 2):
            a = session_summary.loc[session_summary.comparison_group.eq(ga), feature].dropna().to_numpy()
            b = session_summary.loc[session_summary.comparison_group.eq(gb), feature].dropna().to_numpy()
            u, raw_p = mannwhitneyu(a, b, alternative="two-sided")
            feature_rows.append({"feature": feature, "group_a": ga, "group_b": gb, "n_a": len(a), "n_b": len(b),
                                 "median_a": np.median(a), "median_b": np.median(b), "u_statistic": u,
                                 "p_value_raw": raw_p, "cliffs_delta_a_vs_b": cliffs_delta(a, b)})
        adjusted = holm_adjust([r["p_value_raw"] for r in feature_rows])
        for row, p_adj in zip(feature_rows, adjusted):
            row["p_value_holm"] = p_adj
            pairwise.append(row)
    return pd.DataFrame(omnibus), pd.DataFrame(pairwise)


def boxplot(session_summary: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9})
    plot_features = [
        ("distance_slope", "Full-window distance slope"),
        ("recent_distance_slope", "Recent-half distance slope"),
        ("cop_speed_mean", "Mean COP speed"),
        ("cop_net_displacement", "COP net displacement"),
        ("cop_straightness", "COP path straightness"),
        ("cop_direction_consistency", "COP direction consistency"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), constrained_layout=True)
    rng = np.random.default_rng(20260918)
    for ax, (feature, title) in zip(axes.flat, plot_features):
        vals = [session_summary.loc[session_summary.comparison_group.eq(g), feature].dropna().to_numpy() for g in GROUPS]
        boxes = ax.boxplot(vals, showfliers=False, patch_artist=True, widths=.58,
                           medianprops={"color": "#222222", "linewidth": 1.2},
                           whiskerprops={"color": "#555555"}, capprops={"color": "#555555"})
        for patch, group in zip(boxes["boxes"], GROUPS):
            patch.set_facecolor(COLORS[group]); patch.set_alpha(.55); patch.set_edgecolor("#444444")
        for i, (group, values) in enumerate(zip(GROUPS, vals), start=1):
            jitter = rng.uniform(-.10, .10, len(values))
            ax.scatter(i+jitter, values, s=25, color=COLORS[group], edgecolor="#333333", linewidth=.35, alpha=.9, zorder=3)
        short = {"normal_control": "Normal", "recoverable_shift": "Recovered", "directional_exit": "Directional exit", "sway_then_exit": "Sway exit"}
        ax.set_xticks(range(1, 5), [f"{short[g]}\n(n={len(v)})" for g, v in zip(GROUPS, vals)])
        ax.tick_params(axis="x", labelsize=8)
        ax.set_title(title)
        ax.set_ylabel("Session median of selected windows")
        ax.grid(axis="y", color="#D9D9D9", linewidth=.7)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Session-level comparison of the most edgeward or pre-exit windows", fontsize=13)
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)


def recovery_plot(session_summary: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 10})
    fig, ax = plt.subplots(figsize=(8.4, 6.5), constrained_layout=True)
    for group in GROUPS:
        s = session_summary[session_summary.comparison_group.eq(group)]
        ax.scatter(s.distance_slope, s.recent_distance_slope, s=56, color=COLORS[group], label=f"{LABELS[group]} (n={len(s)})",
                   edgecolor="#333333", linewidth=.45, alpha=.9)
    ax.axhline(0, color="#666666", linewidth=.8)
    ax.axvline(0, color="#666666", linewidth=.8)
    ax.plot([-2, 10], [-2, 10], color="#888888", linewidth=.8, linestyle="--", label="Recent trend = full-window trend")
    ax.set_xlim(left=min(-2, session_summary.distance_slope.min()-.5))
    ax.set_xlabel("Full-window distance slope")
    ax.set_ylabel("Recent-half distance slope")
    ax.set_title("Continuation versus correction of edgeward motion")
    ax.grid(color="#D9D9D9", linewidth=.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)


def aligned_trajectories(eligible: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    traces, persistence = [], []
    for (group, sid), subset in eligible.groupby(["comparison_group", "session_id"]):
        subset = subset.sort_values("window_end").copy()
        if group in ("directional_exit", "sway_then_exit"):
            positive = subset[subset.failure_label.eq(1)]
            if positive.empty:
                continue
            reference = float(positive.window_end.max())
            reference_rule = "last pre-exit window"
            max_after = 0.0
        else:
            reference = float(subset.loc[subset.distance_mean.idxmax(), "window_end"])
            reference_rule = "maximum distance-from-hole window"
            max_after = 2.0
        local = subset[(subset.window_end >= reference-3.0) & (subset.window_end <= reference+max_after)].copy()
        local["relative_time"] = np.round((local.window_end-reference) * 4) / 4
        local["reference_rule"] = reference_rule
        traces.append(local[["comparison_group", "session_id", "relative_time", "distance_slope", "recent_distance_slope", "reference_rule"]])
        pre = local[(local.relative_time >= -2) & (local.relative_time <= 0)]
        post = local[(local.relative_time > 0) & (local.relative_time <= 2)]
        persistence.append({
            "comparison_group": group, "session_id": sid, "reference_rule": reference_rule,
            "pre_reference_positive_fraction": float((pre.distance_slope > 0).mean()) if len(pre) else np.nan,
            "pre_reference_mean_slope": float(pre.distance_slope.mean()) if len(pre) else np.nan,
            "post_reference_negative_fraction": float((post.distance_slope < 0).mean()) if len(post) else np.nan,
            "post_reference_mean_slope": float(post.distance_slope.mean()) if len(post) else np.nan,
            "post_minus_pre_slope": float(post.distance_slope.mean()-pre.distance_slope.mean()) if len(post) and len(pre) else np.nan,
        })
    return pd.concat(traces, ignore_index=True), pd.DataFrame(persistence)


def trajectory_plot(traces: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 10})
    fig, ax = plt.subplots(figsize=(9.2, 6.2), constrained_layout=True)
    session_time = traces.groupby(["comparison_group", "session_id", "relative_time"], as_index=False).distance_slope.mean()
    for group in GROUPS:
        g = session_time[session_time.comparison_group.eq(group)]
        pivot = g.pivot(index="session_id", columns="relative_time", values="distance_slope")
        times = np.array(sorted(pivot.columns), float)
        values = pivot[times].to_numpy(float)
        median = np.nanmedian(values, axis=0)
        q25 = np.nanquantile(values, .25, axis=0)
        q75 = np.nanquantile(values, .75, axis=0)
        ax.plot(times, median, color=COLORS[group], linewidth=2, label=f"{LABELS[group]} (n={len(pivot)})")
        ax.fill_between(times, q25, q75, color=COLORS[group], alpha=.14, linewidth=0)
    ax.axvline(0, color="#555555", linewidth=1, linestyle="--")
    ax.axhline(0, color="#777777", linewidth=.8)
    ax.set_xlabel("Time relative to closest-edge or pre-exit reference (s)")
    ax.set_ylabel("Distance-from-hole slope")
    ax.set_title("Edgeward motion before and after the reference moment")
    ax.grid(color="#D9D9D9", linewidth=.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("features_csv", type=Path)
    parser.add_argument("user_dirs", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    metadata = metadata_map(args.user_dirs)
    features = pd.read_csv(args.features_csv)
    features["comparison_group"] = features.apply(assign_group, axis=1, metadata=metadata)
    eligible = features[features.comparison_group.notna()].copy()
    selected = select_comparison_windows(eligible)
    session_summary = selected.groupby(["comparison_group", "session_id"], as_index=False)[FEATURES].median()
    window_summary = selected.groupby("comparison_group")[FEATURES].agg(["count", "mean", "median", "std"])
    omnibus, pairwise = statistics(session_summary)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    eligible.to_csv(args.output_dir / "four_group_all_eligible_windows.csv", index=False)
    selected.to_csv(args.output_dir / "four_group_selected_windows.csv", index=False)
    session_summary.to_csv(args.output_dir / "four_group_session_summary.csv", index=False)
    window_summary.to_csv(args.output_dir / "four_group_window_summary.csv")
    omnibus.to_csv(args.output_dir / "four_group_omnibus_tests.csv", index=False)
    pairwise.to_csv(args.output_dir / "four_group_pairwise_tests.csv", index=False)
    traces, persistence = aligned_trajectories(eligible)
    traces.to_csv(args.output_dir / "four_group_aligned_trajectories.csv", index=False)
    persistence.to_csv(args.output_dir / "four_group_persistence_summary.csv", index=False)
    boxplot(session_summary, args.output_dir / "four_group_session_comparison.png")
    recovery_plot(session_summary, args.output_dir / "four_group_recovery_dynamics.png")
    trajectory_plot(traces, args.output_dir / "four_group_aligned_distance_trajectories.png")
    report = {
        "comparison_groups": {g: int((session_summary.comparison_group == g).sum()) for g in GROUPS},
        "selected_window_counts": {g: int((selected.comparison_group == g).sum()) for g in GROUPS},
        "selection_rule": {
            "normal_and_recoverable": "top 10% edgeward distance-slope windows within each session",
            "exit_groups": "failure_label=1 windows ending within 2 seconds before Unity edge exit",
        },
        "unit_of_inference": "session-level medians; windows are overlapping and are not treated as independent experimental units",
        "omnibus_significant_at_0.05": omnibus.loc[omnibus.p_value < .05, "feature"].tolist(),
    }
    (args.output_dir / "four_group_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
