"""Complete the Monday follow-up: manifest, alignment sensitivity, and fixed rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from audit_monday_absolute_distance import (
    COLORS,
    GROUPS,
    GROUP_LABELS,
    load_fall_times,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--telemetry-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    return p.parse_args()


def session_folders(telemetry_root: Path) -> dict[str, Path]:
    result = {}
    for qpath in telemetry_root.glob("*/session_*/quality.json"):
        quality = json.loads(qpath.read_text(encoding="utf-8"))
        sid = str(quality.get("session_id") or qpath.parent.name)
        result[sid] = qpath.parent
    return result


def make_manifest(output_dir: Path) -> pd.DataFrame:
    audit = pd.read_csv(output_dir / "session_audit.csv")
    excluded = pd.read_csv(output_dir / "excluded_group_candidates.csv")
    included = pd.DataFrame(
        {
            "session_id": audit.session_id,
            "group": audit.analysis_group,
            "included": True,
            "exclusion_reason": "",
            "failure_label_count": audit.positive_window_count.astype(int),
            "reference_rule": audit.reference_rule,
            "data_quality": np.where(
                audit.failure_label_mismatch_count.eq(0)
                & audit.timestamps_strictly_increasing
                & audit.distance_all_finite
                & audit.distance_all_nonnegative,
                "pass",
                "review",
            ),
        }
    )
    excluded_rows = pd.DataFrame(
        {
            "session_id": excluded.session_id,
            "group": excluded.analysis_group,
            "included": False,
            "exclusion_reason": excluded.reason,
            "failure_label_count": excluded.positive_windows.astype(int),
            "reference_rule": "",
            "data_quality": "excluded: sensor failure/no valid positive window",
        }
    )
    manifest = pd.concat([included, excluded_rows], ignore_index=True).sort_values("session_id")
    manifest.to_csv(output_dir / "session_manifest.csv", index=False)
    return manifest


def reference_times(metadata: pd.DataFrame, folders: dict[str, Path]) -> dict[str, tuple[float, float]]:
    refs = {}
    for row in metadata.itertuples(index=False):
        windows = pd.read_csv(folders[row.session_id] / "windows.csv").sort_values("window_end")
        first = float(windows.window_end.iloc[0])
        if row.analysis_group in ("directional_edge_exit", "sway_then_edge_exit"):
            peak_or_event = float(load_fall_times(folders[row.session_id])[0])
        else:
            peak_or_event = float(windows.loc[windows.distance_mean.idxmax(), "window_end"])
        refs[row.session_id] = (peak_or_event, first)
    return refs


def interpolate_group(
    metadata: pd.DataFrame,
    folders: dict[str, Path],
    refs: dict[str, tuple[float, float]],
    group: str,
    alignment: str,
    times: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    values = []
    for sid in metadata.loc[metadata.analysis_group.eq(group), "session_id"]:
        windows = pd.read_csv(folders[sid] / "windows.csv").sort_values("window_end")
        peak_ref, first_ref = refs[sid]
        ref = peak_ref if alignment == "peak" else first_ref
        x = windows.window_end.to_numpy(float) - ref
        y = windows.distance_mean.to_numpy(float)
        keep = np.r_[True, np.diff(x) > 1e-8]
        x, y = x[keep], y[keep]
        if len(x) < 2:
            continue
        v = np.interp(times, x, y, left=np.nan, right=np.nan)
        v[(times < x.min() - .01) | (times > x.max() + .01)] = np.nan
        values.append(v)
    matrix = np.asarray(values, float)
    n = np.sum(np.isfinite(matrix), axis=0)
    valid = n >= max(2, int(np.ceil(len(values) * .5)))
    median = np.full(len(times), np.nan)
    q25 = np.full(len(times), np.nan)
    q75 = np.full(len(times), np.nan)
    if valid.any():
        median[valid] = np.nanmedian(matrix[:, valid], axis=0)
        q25[valid] = np.nanquantile(matrix[:, valid], .25, axis=0)
        q75[valid] = np.nanquantile(matrix[:, valid], .75, axis=0)
    return median, q25, q75, valid


def plot_sensitivity(metadata: pd.DataFrame, folders: dict[str, Path], output_dir: Path) -> pd.DataFrame:
    refs = reference_times(metadata, folders)
    time_grid = {
        "peak": np.arange(-3.0, 0.001, .25),
        "fixed": np.arange(0.0, 3.001, .25),
    }
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11})
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.9), sharey=True)
    summary = []
    for ax, alignment in zip(axes, ["peak", "fixed"]):
        times = time_grid[alignment]
        for group in GROUPS:
            median, q25, q75, valid = interpolate_group(metadata, folders, refs, group, alignment, times)
            ax.fill_between(times[valid], q25[valid], q75[valid], color=COLORS[group], alpha=.15, linewidth=0)
            ax.plot(times[valid], median[valid], color=COLORS[group], linewidth=2.1, label=f"{GROUP_LABELS[group]} (n={(metadata.analysis_group == group).sum()})")
            if valid.any():
                first_i = np.flatnonzero(valid)[0]
                last_i = np.flatnonzero(valid)[-1]
                summary.append(
                    {
                        "alignment": alignment,
                        "group": group,
                        "start_time": float(times[first_i]),
                        "end_time": float(times[last_i]),
                        "median_start_distance_mean": float(median[first_i]),
                        "median_end_distance_mean": float(median[last_i]),
                        "median_change": float(median[last_i] - median[first_i]),
                    }
                )
        ax.axvline(0, color="#444444", linewidth=.8, linestyle=(0, (4, 3)))
        ax.set_title("A  Peak-based reference" if alignment == "peak" else "B  Fixed session-start reference")
        ax.set_xlabel("Time relative to reference (s)" if alignment == "peak" else "Time from first valid window (s)")
        ax.grid(axis="y", color="#D8D8D8", linewidth=.5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlim(times.min(), times.max())
    axes[0].set_ylabel("Absolute distance (distance_mean)")
    handles = [Line2D([0], [0], color=COLORS[g], lw=2.1, label=GROUP_LABELS[g]) for g in GROUPS]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(.5, .025))
    fig.suptitle("Sensitivity of absolute-distance trajectories to reference-time alignment", fontsize=13, y=.99)
    fig.subplots_adjust(left=.08, right=.99, top=.86, bottom=.22, wspace=.08)
    fig.savefig(output_dir / "absolute_distance_alignment_sensitivity.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output_dir / "absolute_distance_alignment_sensitivity.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(output_dir / "alignment_sensitivity_summary.csv", index=False)
    return summary_df


def append_rules(output_dir: Path, manifest: pd.DataFrame, summary: pd.DataFrame) -> None:
    report_path = output_dir / "monday_data_check_record.md"
    text = report_path.read_text(encoding="utf-8")
    marker = "## 周一补充：session manifest、对齐敏感性与后续固定规则"
    if marker in text:
        text = text.split(marker, 1)[0].rstrip()
    lines = [
        "",
        "## 周一补充：session manifest、对齐敏感性与后续固定规则",
        "",
        "### 1. Session manifest",
        "",
        "已建立 `session_manifest.csv`。每行包含 session_id、group、included、exclusion_reason、failure_label_count、reference_rule 和 data_quality。被排除 session 的理由已明确记录，不再依赖记忆。",
        "",
        "### 2. 峰值对齐敏感性",
        "",
        "对照图包含两种时间原点：",
        "",
        "- A：原分析规则。正常/恢复组以该 session 的最大 `distance_mean` 窗口为 0；坠出组以 Unity `fall_event` 为 0。",
        "- B：固定 session-start 规则。所有 session 都以第一个有效窗口为 0，纵轴仍然是同一个 `distance_mean`。",
        "",
        "如果非坠出组只有在 A 中出现明显上升，而 B 中没有同样趋势，则说明该上升至少部分来自 peak-based alignment，而不是单独的生理/行为效应。该限制应在正式图注和方法部分说明：",
        "",
        "> The pre-reference increase in non-exit groups may partly reflect the peak-based alignment rule.",
        "",
        "对照数值见 `alignment_sensitivity_summary.csv`；图见 `absolute_distance_alignment_sensitivity.png` 和 `.pdf`。",
        "",
        "### 3. 后续分析固定规则",
        "",
        "1. 分析单位是 session，不是单独窗口。",
        "2. 1 秒窗口、0.25 秒步长产生的重叠窗口不增加独立样本量。",
        "3. 训练、验证和测试必须按 session 划分，不能按窗口随机拆分。",
        "4. 正常组和恢复组使用统一的参考规则；当前描述性图采用 session maximum `distance_mean`，并在图注中标明峰值对齐限制。",
        "5. 坠出组使用 Unity edge-exit 前的参考时间，最终图使用真实 `fall_event` 时间作为 0。",
        "6. 没有有效正标签窗口的 session 不作为坠出训练样本；此类 session 只能单独记录为 excluded/normal-only 质量问题。",
        "",
    ]
    report_path.write_text(text.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata = pd.read_csv(args.output_dir / "group_session_manifest.csv")
    folders = session_folders(args.telemetry_root)
    manifest = make_manifest(args.output_dir)
    summary = plot_sensitivity(metadata, folders, args.output_dir)
    append_rules(args.output_dir, manifest, summary)
    print({"manifest_rows": len(manifest), "sensitivity_rows": len(summary), "figure_metric": "distance_mean"})


if __name__ == "__main__":
    main()
