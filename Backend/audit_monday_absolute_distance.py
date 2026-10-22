"""Audit the four experimental groups and produce the final absolute-distance figure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd


GROUPS = [
    "normal_control",
    "recoverable_directional_shift",
    "directional_edge_exit",
    "sway_then_edge_exit",
]
GROUP_LABELS = {
    "normal_control": "Normal control",
    "recoverable_directional_shift": "Recovered edge approach",
    "directional_edge_exit": "Directional edge exit",
    "sway_then_edge_exit": "Intense sway then edge exit",
}
GROUP_SHORT = {
    "normal_control": "Normal",
    "recoverable_directional_shift": "Recovered",
    "directional_edge_exit": "Directional exit",
    "sway_then_edge_exit": "Sway exit",
}
COLORS = {
    "normal_control": "#1764A0",
    "recoverable_directional_shift": "#2F8F57",
    "directional_edge_exit": "#C73E36",
    "sway_then_edge_exit": "#7E52A0",
}
EXPECTED_FAILURE = {
    "normal_control": 0,
    "recoverable_directional_shift": 0,
    "directional_edge_exit": 1,
    "sway_then_edge_exit": 1,
}
RNG_SEED = 20260921


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_metadata(telemetry_root: Path) -> tuple[pd.DataFrame, dict[str, Path], pd.DataFrame]:
    rows: list[dict] = []
    excluded_rows: list[dict] = []
    folders: dict[str, Path] = {}
    for quality_path in telemetry_root.glob("*/session_*/quality.json"):
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        session_id = quality.get("session_id") or quality_path.parent.name
        group = quality.get("analysis_group")
        if group not in GROUPS:
            continue
        positive_windows = int(quality.get("positive_windows", 0))
        if group in ("directional_edge_exit", "sway_then_edge_exit") and positive_windows == 0:
            excluded_rows.append(
                {
                    "session_id": session_id,
                    "analysis_group": group,
                    "analysis_status": quality.get("analysis_status", ""),
                    "data_role": quality.get("data_role", ""),
                    "positive_windows": positive_windows,
                    "reason": quality.get("analysis_status_reason", "no valid positive pre-exit window"),
                    "folder": str(quality_path.parent),
                }
            )
            continue
        if session_id in folders:
            raise ValueError(f"Duplicate session id: {session_id}")
        folders[session_id] = quality_path.parent
        rows.append(
            {
                "session_id": session_id,
                "analysis_group": group,
                "condition": quality.get("condition", ""),
                "fall_direction": quality.get("fall_direction", ""),
                "analysis_status": quality.get("analysis_status", ""),
                "physical_off_board": bool(quality.get("physical_off_board", False)),
                "reported_fall_events": int(quality.get("fall_events", 0)),
                "reported_windows": int(quality.get("windows", 0)),
                "reported_positive_windows": positive_windows,
                "horizon_seconds": float(quality.get("horizon_seconds", 2.0)),
                "window_seconds": float(quality.get("window_seconds", 1.0)),
                "step_seconds": float(quality.get("step_seconds", 0.25)),
                "folder": str(quality_path.parent),
            }
        )
    frame = pd.DataFrame(rows).sort_values(["analysis_group", "session_id"]).reset_index(drop=True)
    excluded = pd.DataFrame(excluded_rows)
    return frame, folders, excluded


def load_fall_times(folder: Path) -> np.ndarray:
    clean = pd.read_csv(folder / "clean.csv", usecols=["backend_timestamp", "source", "fall_event"])
    fall_flag = clean["fall_event"].astype(str).str.lower().eq("true")
    times = clean.loc[clean["source"].eq("unity") & fall_flag, "backend_timestamp"]
    return np.sort(times.dropna().to_numpy(float))


def expected_failure_labels(window_end: np.ndarray, fall_times: np.ndarray, horizon: float) -> np.ndarray:
    return np.array(
        [int(np.any((fall_times > end) & (fall_times <= end + horizon))) for end in window_end],
        dtype=int,
    )


def choose_reference(group: str, windows: pd.DataFrame, fall_times: np.ndarray) -> tuple[float, str]:
    if group in ("directional_edge_exit", "sway_then_edge_exit"):
        if len(fall_times) != 1:
            raise ValueError(f"Expected exactly one Unity fall event, found {len(fall_times)}")
        return float(fall_times[0]), "Unity fall_event timestamp"
    row = windows.loc[windows["distance_mean"].idxmax()]
    return float(row["window_end"]), "maximum distance_mean window_end"


def recompute_distance_error(folder: Path, windows: pd.DataFrame) -> float:
    aligned = pd.read_csv(
        folder / "aligned_60hz.csv",
        usecols=["backend_timestamp", "distance_to_hole"],
    ).dropna()
    timestamp = aligned["backend_timestamp"].to_numpy(float)
    distance = aligned["distance_to_hole"].to_numpy(float)
    errors = []
    for row in windows.itertuples(index=False):
        mask = (timestamp >= float(row.window_start) - 1e-7) & (timestamp <= float(row.window_end) + 1e-7)
        if mask.sum() != int(row.sample_count):
            errors.append(np.nan)
            continue
        errors.append(abs(float(distance[mask].mean()) - float(row.distance_mean)))
    finite = np.asarray(errors, float)
    return float(np.nanmax(finite)) if np.isfinite(finite).any() else np.nan


def audit_sessions(metadata: pd.DataFrame, folders: dict[str, Path]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    audits: list[dict] = []
    curves: dict[str, pd.DataFrame] = {}
    for meta in metadata.itertuples(index=False):
        folder = folders[meta.session_id]
        windows = pd.read_csv(folder / "windows.csv").sort_values("window_end").reset_index(drop=True)
        fall_times = load_fall_times(folder)
        expected = expected_failure_labels(
            windows["window_end"].to_numpy(float), fall_times, float(meta.horizon_seconds)
        )
        actual = windows["failure_label"].to_numpy(int)
        reference, reference_rule = choose_reference(meta.analysis_group, windows, fall_times)
        curve = windows[[
            "window_start", "window_end", "sample_count", "failure_label", "distance_mean"
        ]].copy()
        curve["relative_time"] = curve["window_end"] - reference
        curve["session_id"] = meta.session_id
        curve["analysis_group"] = meta.analysis_group
        curves[meta.session_id] = curve

        delta = np.diff(windows["distance_mean"].to_numpy(float))
        delta_t = np.diff(windows["window_end"].to_numpy(float))
        local_delta = np.abs(delta[delta_t <= 0.51]) if len(delta) else np.array([])
        reference_distance = float(
            windows.iloc[(windows["window_end"] - reference).abs().argmin()]["distance_mean"]
        )
        pre3_index = (windows["window_end"] - (reference - 3.0)).abs().argmin()
        pre3_row = windows.iloc[pre3_index]
        pre3_distance = (
            float(pre3_row["distance_mean"])
            if abs(float(pre3_row["window_end"]) - (reference - 3.0)) <= 0.30
            else np.nan
        )
        first_t = float(windows["window_end"].min())
        last_t = float(windows["window_end"].max())
        audits.append(
            {
                "session_id": meta.session_id,
                "analysis_group": meta.analysis_group,
                "condition": meta.condition,
                "fall_direction": meta.fall_direction,
                "window_count": int(len(windows)),
                "positive_window_count": int(actual.sum()),
                "unity_fall_event_count": int(len(fall_times)),
                "failure_label_mismatch_count": int(np.sum(expected != actual)),
                "expected_group_failure_event": EXPECTED_FAILURE[meta.analysis_group],
                "group_failure_event_ok": int(len(fall_times) > 0) == EXPECTED_FAILURE[meta.analysis_group],
                "timestamps_strictly_increasing": bool(np.all(np.diff(windows["window_end"]) > 0)),
                "distance_all_finite": bool(np.isfinite(windows["distance_mean"]).all()),
                "distance_all_nonnegative": bool((windows["distance_mean"] >= 0).all()),
                "distance_min": float(windows["distance_mean"].min()),
                "distance_max": float(windows["distance_mean"].max()),
                "largest_adjacent_change_le_0_5s": float(local_delta.max()) if len(local_delta) else np.nan,
                "reference_time": reference,
                "reference_rule": reference_rule,
                "reference_distance_mean": reference_distance,
                "distance_mean_3s_before_reference": pre3_distance,
                "reference_seconds_from_first_window": reference - first_t,
                "reference_seconds_to_last_window": last_t - reference,
                "reference_near_start_or_end": bool((reference - first_t < 3.0) or (last_t - reference < 0.5)),
                "reported_window_count_matches": int(meta.reported_windows) == int(len(windows)),
                "reported_positive_count_matches": int(meta.reported_positive_windows) == int(actual.sum()),
                "reported_fall_count_matches": int(meta.reported_fall_events) == int(len(fall_times)),
                "physical_off_board": bool(meta.physical_off_board),
            }
        )
    return pd.DataFrame(audits), curves


def sample_sessions(metadata: pd.DataFrame) -> list[str]:
    rng = np.random.default_rng(RNG_SEED)
    chosen: list[str] = []
    for group in GROUPS:
        candidates = metadata.loc[metadata["analysis_group"].eq(group), "session_id"].to_numpy()
        chosen.extend(rng.choice(candidates, size=min(2, len(candidates)), replace=False).tolist())
    return chosen


def add_recomputation_audit(audit: pd.DataFrame, sample: list[str], folders: dict[str, Path]) -> pd.DataFrame:
    sampled = audit[audit["session_id"].isin(sample)].copy()
    errors = {}
    for session_id in sample:
        windows = pd.read_csv(folders[session_id] / "windows.csv")
        errors[session_id] = recompute_distance_error(folders[session_id], windows)
    sampled["distance_mean_recompute_max_abs_error"] = sampled["session_id"].map(errors)
    sampled["absolute_distance_curve_check"] = np.where(
        sampled["distance_all_finite"]
        & sampled["distance_all_nonnegative"]
        & sampled["timestamps_strictly_increasing"]
        & sampled["distance_mean_recompute_max_abs_error"].fillna(np.inf).lt(1e-8),
        "pass",
        "review",
    )
    order = {sid: idx for idx, sid in enumerate(sample)}
    sampled["sample_order"] = sampled["session_id"].map(order)
    return sampled.sort_values("sample_order").drop(columns="sample_order")


def plot_sample_curves(curves: dict[str, pd.DataFrame], sampled: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 8.5})
    fig, axes = plt.subplots(4, 2, figsize=(11.0, 11.8), sharex=False, constrained_layout=True)
    for ax, row in zip(axes.flat, sampled.itertuples(index=False)):
        curve = curves[row.session_id]
        ax.plot(curve["window_end"] - curve["window_end"].iloc[0], curve["distance_mean"], color=COLORS[row.analysis_group], lw=1.25)
        positive = curve["failure_label"].eq(1)
        if positive.any():
            ax.scatter(
                curve.loc[positive, "window_end"] - curve["window_end"].iloc[0],
                curve.loc[positive, "distance_mean"],
                s=8,
                color=COLORS[row.analysis_group],
                edgecolor="none",
                alpha=.75,
            )
        ax.set_title(f"{GROUP_SHORT[row.analysis_group]} — {row.session_id.replace('session_', '')}", loc="left")
        ax.set_xlabel("Time from first valid window (s)")
        ax.set_ylabel("distance_mean")
        ax.grid(axis="y", color="#D8D8D8", linewidth=.45)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Deterministic random audit: absolute-distance curves (2 sessions per group)", fontsize=12)
    fig.savefig(output, dpi=240, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_final_figure(curves: dict[str, pd.DataFrame], metadata: pd.DataFrame, output_png: Path, output_pdf: Path) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Serif",
            "font.size": 9.5,
            "axes.titlesize": 10.5,
            "axes.labelsize": 10,
            "legend.fontsize": 8.5,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
        }
    )
    fig, axes = plt.subplots(2, 2, figsize=(10.6, 8.1), sharex=True, sharey=True)
    common_time = np.arange(-3.0, 0.001, 0.25)
    panel_letters = ["A", "B", "C", "D"]

    for ax, group, letter in zip(axes.flat, GROUPS, panel_letters):
        session_ids = metadata.loc[metadata["analysis_group"].eq(group), "session_id"].tolist()
        interpolated = []
        for session_id in session_ids:
            local = curves[session_id]
            local = local[(local["relative_time"] >= -3.05) & (local["relative_time"] <= 0.05)].copy()
            if local.empty:
                continue
            x = local["relative_time"].to_numpy(float)
            y = local["distance_mean"].to_numpy(float)
            keep = np.r_[True, np.diff(x) > 1e-8]
            x, y = x[keep], y[keep]
            values = np.interp(common_time, x, y, left=np.nan, right=np.nan)
            values[(common_time < x.min() - .01) | (common_time > x.max() + .01)] = np.nan
            interpolated.append(values)
            ax.plot(x, y, color=COLORS[group], alpha=.16, linewidth=.65)

        matrix = np.asarray(interpolated, float)
        valid_n = np.sum(np.isfinite(matrix), axis=0)
        valid = valid_n >= max(2, int(np.ceil(len(session_ids) * .5)))
        valid_matrix = matrix[:, valid]
        median = np.nanmedian(valid_matrix, axis=0)
        q25 = np.nanquantile(valid_matrix, .25, axis=0)
        q75 = np.nanquantile(valid_matrix, .75, axis=0)
        ax.fill_between(common_time[valid], q25, q75, color=COLORS[group], alpha=.18, linewidth=0)
        ax.plot(common_time[valid], median, color=COLORS[group], linewidth=2.25)
        ax.axvline(0, color="#333333", linewidth=.9, linestyle=(0, (4, 3)))
        ax.text(.015, .96, letter, transform=ax.transAxes, va="top", ha="left", fontweight="bold")
        ax.set_title(f"{GROUP_LABELS[group]} (n={len(session_ids)})")
        ax.grid(axis="y", color="#D7D7D7", linewidth=.5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlim(-3.0, 0.05)
        ax.set_ylim(bottom=0)

    axes[1, 0].set_xlabel("Time relative to reference (s)")
    axes[1, 1].set_xlabel("Time relative to reference (s)")
    axes[0, 0].set_ylabel("Absolute ball-to-centre distance")
    axes[1, 0].set_ylabel("Absolute ball-to-centre distance")
    legend = [
        Line2D([0], [0], color="#777777", lw=.8, alpha=.45, label="Individual session"),
        Line2D([0], [0], color="#222222", lw=2.2, label="Group median"),
        Line2D([0], [0], color="#777777", lw=7, alpha=.18, label="Interquartile range"),
    ]
    fig.suptitle("Absolute distance in the 3 s preceding the reference moment", fontsize=13, y=.985)
    fig.subplots_adjust(left=.09, right=.985, top=.90, bottom=.15, hspace=.25, wspace=.08)
    fig.legend(handles=legend, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(.5, .055))
    fig.text(
        .5,
        .022,
        "Reference: session maximum distance_mean for non-exit groups; Unity fall_event for exit groups.",
        ha="center",
        va="bottom",
        fontsize=8.5,
    )
    fig.savefig(output_png, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output_pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fmt_range(series: pd.Series) -> str:
    return f"{series.min():.2f}–{series.max():.2f}"


def write_report(
    metadata: pd.DataFrame,
    audit: pd.DataFrame,
    sampled: pd.DataFrame,
    excluded: pd.DataFrame,
    output: Path,
    figure_name: str,
) -> None:
    counts = metadata.groupby("analysis_group")["session_id"].nunique().to_dict()
    ref_stats = audit.groupby("analysis_group")["reference_distance_mean"].agg(["min", "median", "max", "std"])
    boundary_counts = audit.groupby("analysis_group")["reference_near_start_or_end"].sum().to_dict()
    mismatch_total = int(audit["failure_label_mismatch_count"].sum())
    sampled_pass = int(sampled["absolute_distance_curve_check"].eq("pass").sum())

    lines = [
        "# 周一数据与 absolute-distance 图核查记录",
        "",
        "## 结论",
        "",
        f"- 四个目标组共 {len(metadata)} 个 session：正常组 {counts.get('normal_control', 0)}、恢复组 {counts.get('recoverable_directional_shift', 0)}、方向坠出组 {counts.get('directional_edge_exit', 0)}、剧烈摇晃坠出组 {counts.get('sway_then_edge_exit', 0)}。",
        f"- 另有 {len(excluded)} 个 metadata 候选 session 因没有有效的正标签窗口而不进入坠出组统计；其排除理由保存在 excluded_group_candidates.csv。",
        f"- failure_label 逐窗口重算后共发现 {mismatch_total} 个不一致；定义确认是：窗口结束后的 2 秒内发生 Unity fall_event 时为 1，且坠出后的过渡窗口不进入 windows.csv。",
        "- 最终图的纵轴数据明确为 windows.csv 中的 distance_mean；没有使用 distance_slope 或 recent_distance_slope。",
        "- 参考时间：正常组与恢复组采用各 session 的最大 distance_mean 窗口结束时间；两个坠出组采用 clean.csv 中真实 Unity fall_event 时间。",
        f"- 固定随机种子 {RNG_SEED}，每组抽 2 个，共抽查 {len(sampled)} 个 session；其中 {sampled_pass}/{len(sampled)} 个通过时间顺序、非负有限值及从 aligned_60hz.csv 重算 distance_mean 的一致性检查。",
        "",
        "## 四组定义",
        "",
        "| 组别 | metadata analysis_group | 纳入规则 | session 数 |",
        "|---|---|---|---:|",
        f"| 正常组 | normal_control | 无 Unity fall_event，作为正常完成对照 | {counts.get('normal_control', 0)} |",
        f"| 恢复组 | recoverable_directional_shift | 明显向边缘移动后恢复，且无 Unity fall_event | {counts.get('recoverable_directional_shift', 0)} |",
        f"| 方向坠出组 | directional_edge_exit | 明确方向性接近边缘并发生 Unity fall_event | {counts.get('directional_edge_exit', 0)} |",
        f"| 剧烈摇晃坠出组 | sway_then_edge_exit | 多方向/剧烈摇晃后发生 Unity fall_event | {counts.get('sway_then_edge_exit', 0)} |",
        "",
        "注意：这里的坠出是 Unity 游戏中的 edge exit；physical_off_board 是另一类传感器事件，不属于这四组。",
        "",
        "## failure_label 与参考时间",
        "",
        "- failure_label 的计算区间为 (window_end, window_end + 2.0 s]。事件必须晚于窗口结束；正好落在 2 秒边界内仍标为 1。",
        "- 正常/恢复组没有 fall_event，所有 failure_label 应为 0。",
        "- 方向坠出/摇晃坠出组均各有 1 个 Unity fall_event；最终图直接以事件时间为 0，而不是以最后一个正标签窗口代替事件时间。",
        "- 图仅展示参考点前 3 秒。每条细线是一个 session，粗线是组中位数，阴影是四分位范围。",
        "",
        "## 随机抽查 session",
        "",
        "| 组别 | session | 窗口数 | 正标签数 | distance 范围 | 重算最大误差 | 结果 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in sampled.itertuples(index=False):
        lines.append(
            f"| {GROUP_SHORT[row.analysis_group]} | {row.session_id} | {row.window_count} | "
            f"{row.positive_window_count} | {row.distance_min:.2f}–{row.distance_max:.2f} | "
            f"{row.distance_mean_recompute_max_abs_error:.3g} | {row.absolute_distance_curve_check} |"
        )

    lines.extend(
        [
            "",
            "## 当前数据问题",
            "",
            f"- 组间样本量明显不平衡：方向坠出组 n={counts.get('directional_edge_exit', 0)}，但剧烈摇晃坠出组仅 n={counts.get('sway_then_edge_exit', 0)}；后者的中位数和四分位带不稳定，不宜做强结论。",
            "- session_20260918_142021_053952 虽标记为 directional_edge_exit，但事件前传感器样本失效，positive_windows=0，metadata 已注明 included_normal_only；因此不计入 19 个方向坠出 session。",
            f"- 正常组内部曲线差异明显：在参考点前约 3 秒，具有完整覆盖的 session 的 distance_mean 范围为 {fmt_range(audit.loc[audit.analysis_group.eq('normal_control'), 'distance_mean_3s_before_reference'].dropna())}；恢复组对应范围为 {fmt_range(audit.loc[audit.analysis_group.eq('recoverable_directional_shift'), 'distance_mean_3s_before_reference'].dropna())}。绝对距离受每次 session 的起始位置和轨迹影响。",
            f"- 正常组有 {int(boundary_counts.get('normal_control', 0))} 个、恢复组有 {int(boundary_counts.get('recoverable_directional_shift', 0))} 个 session 的最大 distance_mean 参考点靠近可用数据边界，因此部分曲线在 -3 秒处不完整。",
            "- 方向坠出组内部 condition 包含 direct、turning、normal-play、repeated-approach 和 accidental edge exit，机制并不完全同质。",
            "- windows.csv 使用 1 秒窗口、0.25 秒步长，相邻窗口高度重叠；窗口不能作为独立样本。统计推断仍应以 session 为单位。",
            "- failure_label 只表示未来 2 秒内的 Unity edge exit，不表示现实中从 Wii Balance Board 上掉落。",
            "- 以最大 distance_mean 作为正常/恢复组参考点属于数据驱动对齐，适合描述性图，但会把峰值对齐并放大峰前上升形态；正式比较时应在图注中明确。",
            "",
            "## 输出",
            "",
            f"- 最终期刊风格图：{figure_name}",
            "- 完整 session 核查表：session_audit.csv",
            "- 随机抽查表：sampled_session_audit.csv",
            "- 抽查曲线总览：sampled_absolute_distance_curves.png",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata, folders, excluded = read_metadata(args.telemetry_root)
    audit, curves = audit_sessions(metadata, folders)
    sampled_ids = sample_sessions(metadata)
    sampled = add_recomputation_audit(audit, sampled_ids, folders)

    audit.to_csv(args.output_dir / "session_audit.csv", index=False)
    sampled.to_csv(args.output_dir / "sampled_session_audit.csv", index=False)
    metadata.drop(columns="folder").to_csv(args.output_dir / "group_session_manifest.csv", index=False)
    excluded.to_csv(args.output_dir / "excluded_group_candidates.csv", index=False)

    plot_sample_curves(curves, sampled, args.output_dir / "sampled_absolute_distance_curves.png")
    plot_final_figure(
        curves,
        metadata,
        args.output_dir / "four_group_absolute_distance_final.png",
        args.output_dir / "four_group_absolute_distance_final.pdf",
    )
    write_report(
        metadata,
        audit,
        sampled,
        excluded,
        args.output_dir / "monday_data_check_record.md",
        "four_group_absolute_distance_final.png / .pdf",
    )

    result = {
        "sessions": int(len(metadata)),
        "group_counts": metadata.groupby("analysis_group")["session_id"].nunique().to_dict(),
        "failure_label_mismatches": int(audit["failure_label_mismatch_count"].sum()),
        "sampled_sessions": sampled_ids,
        "sample_checks_passed": int(sampled["absolute_distance_curve_check"].eq("pass").sum()),
        "figure_metric": "distance_mean",
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "audit_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
