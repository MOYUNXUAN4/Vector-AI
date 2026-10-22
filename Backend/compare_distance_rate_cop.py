"""Compare absolute distance, signed distance rate, and COP speed by session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from audit_monday_absolute_distance import COLORS, GROUP_LABELS, load_fall_times

GROUPS = [
    "normal_control",
    "recoverable_directional_shift",
    "directional_edge_exit",
    "sway_then_edge_exit",
]
METRICS = [
    ("distance_mean", "Absolute distance (distance_mean)"),
    ("distance_rate", "Distance change rate (units/s)"),
    ("cop_speed_mean", "COP speed (units/s)"),
]


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--telemetry-root", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    return p.parse_args()


def folders(telemetry_root: Path) -> dict[str, Path]:
    result = {}
    for qpath in telemetry_root.glob("*/session_*/quality.json"):
        q = json.loads(qpath.read_text(encoding="utf-8"))
        sid = q.get("session_id") or qpath.parent.name
        result[sid] = qpath.parent
    return result


def load_trajectories(manifest: pd.DataFrame, folder_map: dict[str, Path]) -> pd.DataFrame:
    rows = []
    for meta in manifest[manifest.included.astype(str).str.lower().eq("true")].itertuples(index=False):
        folder = folder_map[meta.session_id]
        windows = pd.read_csv(folder / "windows.csv").sort_values("window_end").reset_index(drop=True)
        if windows.empty:
            continue
        fall_times = load_fall_times(folder)
        if meta.group in ("directional_edge_exit", "sway_then_edge_exit"):
            reference = float(fall_times[0])
            reference_rule = "Unity fall_event timestamp"
        else:
            reference = float(windows.loc[windows.distance_mean.idxmax(), "window_end"])
            reference_rule = "maximum distance_mean window_end"
        rate = windows.distance_mean.diff() / windows.window_end.diff()
        out = pd.DataFrame(
            {
                "session_id": meta.session_id,
                "group": meta.group,
                "window_start": windows.window_start,
                "window_end": windows.window_end,
                "relative_time": windows.window_end - reference,
                "failure_label": windows.failure_label.astype(int),
                "distance_mean": windows.distance_mean,
                "distance_rate": rate,
                "abs_distance_rate": rate.abs(),
                "cop_speed_mean": windows.cop_speed_mean,
                "reference_rule": reference_rule,
            }
        )
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def aggregate(trajectories: pd.DataFrame, group: str, metric: str, grid: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mats = []
    for sid in trajectories.loc[trajectories.group.eq(group), "session_id"].unique():
        s = trajectories[(trajectories.session_id == sid) & trajectories[metric].notna()].sort_values("relative_time")
        if len(s) < 2:
            continue
        x = s.relative_time.to_numpy(float)
        y = s[metric].to_numpy(float)
        keep = np.r_[True, np.diff(x) > 1e-8]
        x, y = x[keep], y[keep]
        v = np.interp(grid, x, y, left=np.nan, right=np.nan)
        v[(grid < x.min() - .01) | (grid > x.max() + .01)] = np.nan
        mats.append(v)
    matrix = np.asarray(mats, float)
    n = np.sum(np.isfinite(matrix), axis=0)
    valid = n >= max(2, int(np.ceil(len(mats) * .5)))
    med = np.full(len(grid), np.nan)
    q25 = np.full(len(grid), np.nan)
    q75 = np.full(len(grid), np.nan)
    if valid.any():
        med[valid] = np.nanmedian(matrix[:, valid], axis=0)
        q25[valid] = np.nanquantile(matrix[:, valid], .25, axis=0)
        q75[valid] = np.nanquantile(matrix[:, valid], .75, axis=0)
    return med, q25, q75, valid


def plot_group_medians(trajectories: pd.DataFrame, output_dir: Path) -> None:
    grid = np.arange(-3.0, 2.001, .25)
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11})
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 10.0), sharex=True, constrained_layout=True)
    for ax, (metric, label) in zip(axes, METRICS):
        for group in GROUPS:
            med, q25, q75, valid = aggregate(trajectories, group, metric, grid)
            ax.fill_between(grid[valid], q25[valid], q75[valid], color=COLORS[group], alpha=.14, linewidth=0)
            ax.plot(grid[valid], med[valid], color=COLORS[group], lw=2.0, label=GROUP_LABELS[group])
        ax.axvline(0, color="#444444", lw=.8, ls=(0, (4, 3)))
        ax.set_ylabel(label)
        ax.grid(axis="y", color="#D8D8D8", lw=.5)
        ax.spines[["top", "right"]].set_visible(False)
    axes[-1].set_xlabel("Time relative to reference (s); non-exit reference = maximum distance_mean")
    axes[0].legend(frameon=False, ncol=2, loc="upper left")
    fig.suptitle("Group-level median trajectories with session-level interquartile bands", fontsize=13)
    fig.savefig(output_dir / "group_median_feature_trajectories.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output_dir / "group_median_feature_trajectories.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_individual(trajectories: pd.DataFrame, output_dir: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 8.5, "axes.titlesize": 10})
    for metric, label in METRICS:
        fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.8), sharex=True, sharey=False, constrained_layout=True)
        for ax, group in zip(axes.flat, GROUPS):
            sgroup = trajectories[trajectories.group.eq(group)]
            for sid, s in sgroup.groupby("session_id"):
                s = s.sort_values("relative_time")
                ax.plot(s.relative_time, s[metric], color=COLORS[group], alpha=.35, lw=.75)
            ax.axvline(0, color="#555555", lw=.7, ls=(0, (4, 3)))
            ax.set_title(f"{GROUP_LABELS[group]} (n={sgroup.session_id.nunique()})", loc="left")
            ax.set_xlabel("Relative time (s)")
            ax.set_ylabel(label)
            ax.grid(axis="y", color="#D8D8D8", lw=.45)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"Individual session trajectories: {label}", fontsize=12)
        safe = metric.replace("_", "-")
        fig.savefig(output_dir / f"individual_{safe}_trajectories.png", dpi=260, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def plot_exit_zoom(trajectories: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    zoom = trajectories[
        trajectories.group.isin(["directional_edge_exit", "sway_then_edge_exit"])
        & trajectories.relative_time.between(-2.05, .05)
    ].copy()
    summary = []
    for (group, sid), s in zoom.groupby(["group", "session_id"]):
        s = s.sort_values("relative_time")
        d = s.distance_mean.dropna()
        r = s.distance_rate.dropna()
        summary.append(
            {
                "group": group,
                "session_id": sid,
                "windows_last_2s": len(s),
                "distance_first": float(d.iloc[0]) if len(d) else np.nan,
                "distance_last": float(d.iloc[-1]) if len(d) else np.nan,
                "distance_change": float(d.iloc[-1] - d.iloc[0]) if len(d) >= 2 else np.nan,
                "negative_distance_rate_fraction": float((r < 0).mean()) if len(r) else np.nan,
                "positive_distance_rate_fraction": float((r > 0).mean()) if len(r) else np.nan,
                "mean_distance_rate": float(r.mean()) if len(r) else np.nan,
                "mean_cop_speed": float(s.cop_speed_mean.mean()) if len(s) else np.nan,
                "recenter_signal": bool((r < 0).mean() >= .40) if len(r) else False,
            }
        )
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(output_dir / "exit_last_2s_session_summary.csv", index=False)

    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11})
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 9.5), sharex=True, constrained_layout=True)
    for ax, (metric, label) in zip(axes, METRICS):
        for group in ["directional_edge_exit", "sway_then_edge_exit"]:
            sub = zoom[zoom.group.eq(group)]
            for sid, s in sub.groupby("session_id"):
                s = s.sort_values("relative_time")
                ax.plot(s.relative_time, s[metric], color=COLORS[group], alpha=.28, lw=.8)
            med, q25, q75, valid = aggregate(zoom, group, metric, np.arange(-2.0, .001, .25))
            g = np.arange(-2.0, .001, .25)
            ax.fill_between(g[valid], q25[valid], q75[valid], color=COLORS[group], alpha=.12, linewidth=0)
            ax.plot(g[valid], med[valid], color=COLORS[group], lw=2.1, label=GROUP_LABELS[group])
        ax.axvline(0, color="#444444", lw=.8, ls=(0, (4, 3)))
        ax.set_ylabel(label)
        ax.grid(axis="y", color="#D8D8D8", lw=.5)
        ax.spines[["top", "right"]].set_visible(False)
    axes[-1].set_xlabel("Time before Unity edge-exit event (s)")
    axes[0].legend(frameon=False, ncol=2, loc="upper left")
    fig.suptitle("Final 2 s before edge exit: session trajectories and group medians", fontsize=13)
    fig.savefig(output_dir / "exit_last_2s_feature_zoom.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output_dir / "exit_last_2s_feature_zoom.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return summary_df


def write_report(trajectories: pd.DataFrame, exit_summary: pd.DataFrame, output_dir: Path) -> None:
    lines = [
        "# 正常 vs 恢复 vs 坠出：特征比较结果",
        "",
        "本次比较以 session 为独立单位，窗口只用于描述每个 session 内的连续变化。使用的三个特征是：`distance_mean`、有符号 `distance_rate`（正值=远离中心，负值=回中心）和 `cop_speed_mean`。",
        "",
        "## 结果摘要",
        "",
        "- 正常组：以最大 `distance_mean` 对齐时，曲线在参考点附近整体较低，但组内 session 差异明显；该上升部分受峰值对齐规则影响，不能单独解释为风险信号。",
        "- 恢复组：多数 session 在达到较高距离后出现下降或负的 distance_rate，说明存在回中心动作；但恢复幅度和速度在 session 之间不一致。",
        "- 坠出组：在事件前最后 2 秒，distance_mean 通常维持在较高或继续上升的状态；相比恢复组，负 distance_rate 的持续比例较低。",
        "- COP speed：坠出组往往伴随更高或更不稳定的 COP speed，尤其是剧烈摇晃坠出组；但该组 n=3，只能作为描述性结果。",
        "",
        "## 回中心动作的 session-level 判据",
        "",
        "在坠出前最后 2 秒内，将 `negative_distance_rate_fraction >= 0.40` 作为一个宽松的回中心信号（不是正式分类阈值）。详细结果见 `exit_last_2s_session_summary.csv`。",
        "",
        "| 组别 | session 数 | 有回中心信号的 session | 中位数 negative-rate fraction | 中位数 distance change |",
        "|---|---:|---:|---:|---:|",
    ]
    for group in ["directional_edge_exit", "sway_then_edge_exit"]:
        s = exit_summary[exit_summary.group.eq(group)]
        lines.append(
            f"| {GROUP_LABELS[group]} | {len(s)} | {int(s.recenter_signal.sum())} | "
            f"{s.negative_distance_rate_fraction.median():.2f} | {s.distance_change.median():.2f} |"
        )
    lines.extend(
        [
            "",
            "## 图表",
            "",
            "- `group_median_feature_trajectories.png`：每组中位数曲线和 session-level 四分位带。",
            "- `individual_distance-mean_trajectories.png`、`individual_distance-rate_trajectories.png`、`individual_cop-speed-mean_trajectories.png`：每个 session 单独曲线。",
            "- `exit_last_2s_feature_zoom.png`：坠出前最后 2 秒放大图。",
            "",
            "## 限制",
            "",
            "- 正常/恢复组当前主图的参考点是 session maximum `distance_mean`；因此非坠出组的上升趋势可能部分由对齐规则造成。",
            "- 坠出组使用真实 Unity `fall_event` 作为 0 秒，事件之后没有纳入比较。",
            "- 三组的 session 数量不平衡，剧烈摇晃坠出组只有 3 个 session。",
            "- 所有结论以 session 轨迹和描述性汇总为主，不能把重叠窗口当作独立样本。",
            "",
        ]
    )
    (output_dir / "feature_comparison_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    a = args()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(a.manifest)
    fmap = folders(a.telemetry_root)
    trajectories = load_trajectories(manifest, fmap)
    trajectories.to_csv(a.output_dir / "session_feature_trajectories.csv", index=False)
    plot_group_medians(trajectories, a.output_dir)
    plot_individual(trajectories, a.output_dir)
    exit_summary = plot_exit_zoom(trajectories, a.output_dir)
    write_report(trajectories, exit_summary, a.output_dir)
    print({"sessions": int(trajectories.session_id.nunique()), "rows": int(len(trajectories)), "metric_count": 3})


if __name__ == "__main__":
    main()
