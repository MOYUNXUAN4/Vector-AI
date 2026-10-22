"""Direction-aware, session-level baseline for impending platform edge exits.

The Unity controller declares an edge exit from the ball's radial displacement
from the current circular platform centre.  The telemetry does not contain the
runtime collider radius, so this analysis uses x/z radial motion directly and
reports an empirical edge radius estimated from observed exit events.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BASE_STEP_SECONDS = 0.25
EXIT_GROUP = "directional_edge_exit"
RECOVERY_GROUP = "recoverable_directional_shift"
NORMAL_GROUP = "normal_control"
SWAY_GROUP = "sway_then_edge_exit"
SCALE_BY_DIFFICULTY = {1: 1.20, 2: 1.00, 3: 0.85, 4: 0.70, 5: 0.60}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--old-baseline-dir", type=Path)
    return parser.parse_args()


def as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def load_session_folders(root: Path) -> dict[str, Path]:
    folders: dict[str, Path] = {}
    for quality_path in root.glob("*/session_*/quality.json"):
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        session_id = quality.get("session_id") or quality_path.parent.name
        folders[session_id] = quality_path.parent
    return folders


def event_information(folder: Path) -> tuple[float | None, float | None]:
    clean = pd.read_csv(folder / "clean.csv")
    is_event = clean.source.eq("unity") & as_bool(clean.fall_event)
    events = clean.loc[is_event].sort_values("backend_timestamp")
    if events.empty:
        return None, None
    event = events.iloc[0]
    radius = float(np.hypot(event.ball_pos_x, event.ball_pos_z))
    return float(event.backend_timestamp), radius


def max_true_run(values: np.ndarray) -> int:
    best = current = 0
    for value in values.astype(bool):
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def trajectory_features(history: pd.DataFrame) -> dict[str, float]:
    history = history.dropna(subset=["backend_timestamp", "ball_pos_x", "ball_pos_z"])
    history = history.sort_values("backend_timestamp").drop_duplicates("backend_timestamp")
    if len(history) < 8:
        return {}

    t = history.backend_timestamp.to_numpy(float)
    x = history.ball_pos_x.to_numpy(float)
    z = history.ball_pos_z.to_numpy(float)
    r = np.hypot(x, z)
    dt = np.diff(t)
    valid = dt > 1e-4
    if valid.sum() < 4:
        return {}

    dx = np.diff(x)[valid]
    dz = np.diff(z)[valid]
    dt = dt[valid]
    x0 = x[:-1][valid]
    z0 = z[:-1][valid]
    r0 = np.maximum(np.hypot(x0, z0), 1e-6)
    vx = dx / dt
    vz = dz / dt
    projected_speed = vx * x0 / r0 + vz * z0 / r0
    displacement = np.hypot(dx, dz)
    path_length = float(displacement.sum())
    net_x = float(x[-1] - x[0])
    net_z = float(z[-1] - z[0])
    direction_consistency = float(np.hypot(net_x, net_z) / path_length) if path_length > 1e-6 else 0.0
    end_radius = max(float(r[-1]), 1e-6)
    outward_alignment = float((net_x * x[-1] + net_z * z[-1]) / (end_radius * path_length)) if path_length > 1e-6 else 0.0

    # Correction logic is evaluated on 0.25 s bins, matching the base window step.
    bins = np.floor((t - t[-1]) / BASE_STEP_SECONDS).astype(int)
    radial_steps = pd.DataFrame({"bin": bins, "radius": r}).groupby("bin").radius.mean().sort_index().diff()
    inward_steps = radial_steps.lt(-0.10).fillna(False).to_numpy()

    recent_start = t[-1] - 1.0
    recent = r[t >= recent_start]
    net_change_1s = float(recent[-1] - recent[0]) if len(recent) >= 2 else float(r[-1] - r[0])
    return {
        "radial_distance": float(r[-1]),
        "radial_distance_mean": float(np.mean(r)),
        "outward_projected_speed": float(np.nanmedian(projected_speed)),
        "outward_fraction": float(np.mean(projected_speed > 0.05)),
        "inward_fraction": float(np.mean(projected_speed < -0.10)),
        "direction_consistency": direction_consistency,
        "outward_alignment": float(np.clip(outward_alignment, -1.0, 1.0)),
        "net_radial_change_1s": net_change_1s,
        "max_inward_run": float(max_true_run(inward_steps)),
    }


def build_feature_table(
    manifest: pd.DataFrame,
    folders: dict[str, Path],
    lookbacks: list[float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_rows: list[dict] = []
    session_rows: list[dict] = []
    included = manifest.loc[as_bool(manifest.included)].copy()
    for manifest_row in included.itertuples(index=False):
        folder = folders[manifest_row.session_id]
        windows = pd.read_csv(folder / "windows.csv").sort_values("window_end").reset_index(drop=True)
        aligned = pd.read_csv(
            folder / "aligned_60hz.csv",
            usecols=["backend_timestamp", "ball_pos_x", "ball_pos_z", "valid_sensor_sample"],
        )
        aligned = aligned.dropna(subset=["backend_timestamp", "ball_pos_x", "ball_pos_z"])
        event_time, event_radius = event_information(folder)
        if event_time is not None:
            # A pre-exit detector must not score windows after the first exit event.
            windows = windows.loc[windows.window_end <= event_time + 1e-6].copy()
            aligned = aligned.loc[aligned.backend_timestamp <= event_time + 1e-6].copy()
        aligned = aligned.sort_values("backend_timestamp").reset_index(drop=True)
        aligned_times = aligned.backend_timestamp.to_numpy(float)
        window_times = windows.window_end.to_numpy(float)
        metadata_path = folder / "session_metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        session_rows.append(
            {
                "session_id": manifest_row.session_id,
                "group": manifest_row.group,
                "fall_direction_metadata": metadata.get("fall_direction", ""),
                "condition_source": metadata.get("condition_source", ""),
                "event_time": event_time,
                "event_radius": event_radius,
                "event_difficulty": int(windows.difficulty.iloc[-1]) if len(windows) else np.nan,
                "scored_windows": len(windows),
            }
        )
        for lookback in lookbacks:
            for window_index, row in enumerate(windows.itertuples(index=False)):
                aligned_left = int(np.searchsorted(aligned_times, row.window_end - lookback, side="left"))
                aligned_right = int(np.searchsorted(aligned_times, row.window_end, side="right"))
                history = aligned.iloc[aligned_left:aligned_right]
                features = trajectory_features(history)
                if not features:
                    continue
                window_left = int(np.searchsorted(window_times, row.window_end - lookback, side="left"))
                recent_windows = windows.iloc[window_left : window_index + 1]
                cop_x = recent_windows.cop_x_mean.to_numpy(float)
                cop_z = recent_windows.cop_z_mean.to_numpy(float)
                if len(cop_x) >= 2:
                    cop_dx = np.diff(cop_x)
                    cop_dz = np.diff(cop_z)
                    cop_path = float(np.hypot(cop_dx, cop_dz).sum())
                    cop_straightness = float(np.hypot(cop_x[-1] - cop_x[0], cop_z[-1] - cop_z[0]) / cop_path) if cop_path > 1e-9 else 0.0
                else:
                    cop_straightness = np.nan
                feature_rows.append(
                    {
                        "session_id": manifest_row.session_id,
                        "group": manifest_row.group,
                        "window_end": float(row.window_end),
                        "event_time": event_time,
                        "failure_label": int(row.failure_label),
                        "lookback_seconds": lookback,
                        "distance_mean": float(row.distance_mean),
                        "difficulty": int(row.difficulty),
                        "cop_speed_mean": float(recent_windows.cop_speed_mean.mean()),
                        "cop_path_straightness": cop_straightness,
                        **features,
                    }
                )
    return pd.DataFrame(feature_rows), pd.DataFrame(session_rows)


def empirical_edge_radius(session_info: pd.DataFrame) -> tuple[float, pd.DataFrame]:
    exits = session_info.loc[
        session_info.group.eq(EXIT_GROUP) & session_info.event_radius.notna(), ["session_id", "event_radius"]
    ].copy()
    difficulty_by_session = session_info.set_index("session_id")["event_difficulty"]
    exits["event_difficulty"] = exits.session_id.map(difficulty_by_session).astype(int)
    exits["platform_scale"] = exits.event_difficulty.map(SCALE_BY_DIFFICULTY)
    exits["base_radius_estimate"] = exits.event_radius / exits.platform_scale
    median = float(exits.base_radius_estimate.median())
    mad = float(np.median(np.abs(exits.base_radius_estimate - median)))
    if mad > 0:
        exits["robust_z"] = 0.6745 * (exits.base_radius_estimate - median) / mad
        retained = exits.loc[exits.robust_z.abs() <= 3.5]
    else:
        exits["robust_z"] = 0.0
        retained = exits
    radius = float(retained.base_radius_estimate.median())
    exits["used_for_empirical_radius"] = exits.session_id.isin(retained.session_id)
    return radius, exits


def add_risk_score(features: pd.DataFrame, edge_radius: float, proximity_start: float, speed_scale: float) -> pd.DataFrame:
    scored = features.copy()
    scored["platform_scale"] = scored.difficulty.map(SCALE_BY_DIFFICULTY).fillna(SCALE_BY_DIFFICULTY[5])
    scored["empirical_edge_radius"] = edge_radius * scored.platform_scale
    scored["distance_to_empirical_edge"] = scored.empirical_edge_radius - scored.radial_distance
    scored["radial_edge_fraction"] = scored.radial_distance / scored.empirical_edge_radius
    scored["edge_proximity_score"] = ((scored.radial_edge_fraction - proximity_start) / (1.0 - proximity_start)).clip(0, 1)
    scored["outward_speed_score"] = (scored.outward_projected_speed / speed_scale).clip(0, 1)
    scored["direction_score"] = scored.outward_alignment.clip(0, 1)
    correction_from_change = (-scored.net_radial_change_1s / 0.50).clip(0, 1)
    scored["corrective_movement_score"] = np.maximum.reduce(
        [
            scored.inward_fraction.fillna(0).to_numpy(float),
            correction_from_change.fillna(0).to_numpy(float),
            scored.max_inward_run.ge(2).astype(float).to_numpy(),
        ]
    )
    scored["risk_score"] = (
        0.35 * scored.edge_proximity_score
        + 0.30 * scored.outward_fraction
        + 0.20 * scored.direction_score
        + 0.15 * scored.outward_speed_score
        - 0.30 * scored.corrective_movement_score
    ).clip(0, 1)
    return scored


def persistent_alarm(scores: pd.Series, threshold: float, hold_windows: int) -> pd.Series:
    above = scores.ge(threshold)
    return above.rolling(hold_windows, min_periods=hold_windows).sum().eq(hold_windows)


def alarm_episode_count(prediction: pd.Series) -> int:
    prediction = prediction.astype(bool)
    return int((prediction & ~prediction.shift(fill_value=False)).sum())


def evaluate(scored: pd.DataFrame, threshold: float, hold_windows: int) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    details: list[pd.DataFrame] = []
    session_rows: list[dict] = []
    for session_id, session in scored.groupby("session_id", sort=False):
        session = session.sort_values("window_end").copy()
        session["predicted_positive"] = persistent_alarm(session.risk_score, threshold, hold_windows).astype(int)
        details.append(session)
        group = str(session.group.iloc[0])
        truth = session.failure_label.astype(bool)
        pred = session.predicted_positive.astype(bool)
        valid_detection = pred & truth
        lead_time = np.nan
        if valid_detection.any():
            event_times = session.event_time.dropna()
            if len(event_times):
                lead_time = float(event_times.iloc[0]) - float(session.loc[valid_detection, "window_end"].iloc[0])
        session_rows.append(
            {
                "session_id": session_id,
                "group": group,
                "has_alarm": int(pred.any()),
                "detected_in_labelled_horizon": int(valid_detection.any()),
                "alarm_episodes": alarm_episode_count(pred),
                "alarm_windows": int(pred.sum()),
                "lead_time_seconds": lead_time,
                "max_risk_score": float(session.risk_score.max()),
            }
        )
    detail = pd.concat(details, ignore_index=True)
    sessions = pd.DataFrame(session_rows)
    actual = detail.failure_label.astype(bool)
    predicted = detail.predicted_positive.astype(bool)
    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0

    def group_rate(group: str, column: str) -> float:
        values = sessions.loc[sessions.group.eq(group), column]
        return float(values.mean()) if len(values) else np.nan

    non_exit = sessions.loc[sessions.group.isin([NORMAL_GROUP, RECOVERY_GROUP])]
    exits = sessions.loc[sessions.group.eq(EXIT_GROUP)]
    detected = exits.detected_in_labelled_horizon.astype(bool)
    metrics = {
        "threshold": threshold,
        "hold_windows": hold_windows,
        "hold_seconds": hold_windows * BASE_STEP_SECONDS,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "window_false_positive_rate": fpr,
        "directional_exit_session_detection_rate": float(detected.mean()) if len(exits) else np.nan,
        "directional_exit_sessions_detected": int(detected.sum()),
        "directional_exit_sessions": len(exits),
        "recovery_session_false_alarm_rate": group_rate(RECOVERY_GROUP, "has_alarm"),
        "normal_session_false_alarm_rate": group_rate(NORMAL_GROUP, "has_alarm"),
        "sway_session_detection_rate": group_rate(SWAY_GROUP, "detected_in_labelled_horizon"),
        "non_exit_session_false_alarm_rate": float(non_exit.has_alarm.mean()) if len(non_exit) else np.nan,
        "mean_non_exit_alarm_episodes": float(non_exit.alarm_episodes.mean()) if len(non_exit) else np.nan,
        "mean_recovery_alarm_episodes": group_rate(RECOVERY_GROUP, "alarm_episodes"),
        "mean_normal_alarm_episodes": group_rate(NORMAL_GROUP, "alarm_episodes"),
        "mean_lead_time_seconds": float(exits.loc[detected, "lead_time_seconds"].mean()) if detected.any() else np.nan,
        "median_lead_time_seconds": float(exits.loc[detected, "lead_time_seconds"].median()) if detected.any() else np.nan,
    }
    return metrics, detail, sessions


def make_plots(results: pd.DataFrame, selected: pd.Series, output_dir: Path) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Serif",
            "font.size": 9.5,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
        }
    )
    subset = results.loc[
        results.lookback_seconds.eq(selected.lookback_seconds)
        & results.proximity_start.eq(selected.proximity_start)
        & results.speed_scale.eq(selected.speed_scale)
        & results.hold_windows.eq(selected.hold_windows)
    ].sort_values("threshold")
    fig, axes = plt.subplots(1, 2, figsize=(10.7, 4.4), constrained_layout=True)
    axes[0].plot(subset.recall, subset.precision, marker="o", color="#1764A0", linewidth=1.4)
    axes[0].scatter([selected.recall], [selected.precision], color="#C73E36", s=55, zorder=5, label="Selected")
    axes[0].set_xlabel("Window recall")
    axes[0].set_ylabel("Window precision")
    axes[0].set_title("Precision–recall trade-off")
    axes[0].legend(frameon=False)
    axes[0].grid(color="#D8D8D8", linewidth=0.5)
    axes[1].scatter(
        results.recovery_session_false_alarm_rate,
        results.directional_exit_session_detection_rate,
        c=results.precision,
        cmap="viridis",
        s=24,
        alpha=0.65,
    )
    axes[1].scatter(
        [selected.recovery_session_false_alarm_rate],
        [selected.directional_exit_session_detection_rate],
        color="#C73E36",
        marker="*",
        s=130,
        label="Selected",
    )
    axes[1].axhspan(0.40, 0.60, color="#2F8F57", alpha=0.08, label="Target detection band")
    axes[1].set_xlabel("Recovery session false-alarm rate")
    axes[1].set_ylabel("Directional-exit session detection rate")
    axes[1].set_title("Session-level operating points")
    axes[1].set_xlim(-0.03, 1.03)
    axes[1].set_ylim(-0.03, 1.03)
    axes[1].grid(color="#D8D8D8", linewidth=0.5)
    axes[1].legend(frameon=False, fontsize=8)
    for axis in axes:
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Direction-aware edge-exit risk baseline", fontsize=13)
    fig.savefig(output_dir / "directional_risk_tradeoffs.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output_dir / "directional_risk_tradeoffs.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_report(
    output_dir: Path,
    selected: pd.Series,
    edge_radius: float,
    edge_events: pd.DataFrame,
    old_best: dict | None,
) -> None:
    lines = [
        "# 周三第二版：方向感知风险 baseline",
        "",
        "## 方法结论",
        "",
        "Unity 的实际坠出判定使用球相对当前圆形平台中心的径向距离和运行时 collider 外半径。日志没有保存 collider 外半径，因此本分析不把 `distance_to_hole` 当作平台边缘距离，而是用 `ball_pos_x`、`ball_pos_z` 计算球相对平台中心的径向位置和朝最近径向边缘的投影速度。",
        "",
        f"方向坠出事件按 Unity 的 `scaleByDifficulty` 还原后，估计基础 prefab 的稳健外半径为 {edge_radius:.3f}。每个窗口的经验边缘半径 = 基础半径 × 当前 difficulty scale。它只用于构造 proximity score，不声称等于每一层运行时 collider 的精确半径。共 {int(edge_events.used_for_empirical_radius.sum())}/{len(edge_events)} 个方向坠出事件进入稳健估计。",
        "",
        "风险分数：",
        "",
        "```text",
        "0.35 × edge proximity",
        "+ 0.30 × outward movement fraction",
        "+ 0.20 × outward direction consistency",
        "+ 0.15 × outward projected speed",
        "− 0.30 × corrective movement",
        "```",
        "",
        "报警还必须连续超过阈值一段时间。最近 1 秒内出现至少两个 0.25 秒径向回中心步，或净径向变化明显为负，会提高 corrective movement penalty。",
        "",
        "阈值选择优先满足方向坠出 session 检出率约 40%–60%，再降低恢复组 session false alarm rate；没有使用 accuracy 排序。所有结果仍是在同一小数据集上调参与评估，属于 exploratory baseline。",
        "",
        "## 选定工作点",
        "",
        "| 指标/参数 | 值 |",
        "|---|---:|",
    ]
    keys = [
        "lookback_seconds",
        "proximity_start",
        "speed_scale",
        "threshold",
        "hold_seconds",
        "precision",
        "recall",
        "f1",
        "window_false_positive_rate",
        "directional_exit_session_detection_rate",
        "recovery_session_false_alarm_rate",
        "normal_session_false_alarm_rate",
        "non_exit_session_false_alarm_rate",
        "mean_non_exit_alarm_episodes",
        "mean_lead_time_seconds",
    ]
    for key in keys:
        value = selected.get(key, np.nan)
        lines.append(f"| {key} | {float(value):.4f} |")
    lines.extend(
        [
            "",
            "## 与第一版的解释性比较",
            "",
            "第一版使用 `distance_mean`（实际是到 hole 的距离）及其变化率。第二版直接使用球相对平台中心的 x/z 径向运动，增加了 outward fraction、方向一致性、连续报警和更严格的回中心惩罚。",
            "",
        ]
    )
    if old_best:
        lines.extend(
            [
                "| Baseline | Window precision | Window recall | Exit-session detection | Non-exit session false alarm |",
                "|---|---:|---:|---:|---:|",
                f"| 第一版 distance rule | {float(old_best.get('precision', np.nan)):.4f} | {float(old_best.get('recall', np.nan)):.4f} | {float(old_best.get('session_detection_rate', np.nan)):.4f} | {float(old_best.get('non_exit_session_false_alarm_rate', np.nan)):.4f} |",
                f"| 第二版 directional risk | {float(selected.precision):.4f} | {float(selected.recall):.4f} | {float(selected.directional_exit_session_detection_rate):.4f} | {float(selected.non_exit_session_false_alarm_rate):.4f} |",
                "",
                "注意：第二版在首次 fall_event 截止，不把坠出后的窗口计入 pre-exit 评估；第一版旧结果没有做这一截止，因此并排数字用于方向判断，不是严格同协议模型竞赛。",
                "",
            ]
        )
    lines.extend(
        [
            "## 数据限制",
            "",
            "- 恢复组只有 8 个 session，方向坠出组只有 19 个有效 session，session-level 比率每个样本都会造成明显跳变。",
            "- 日志缺少每层运行时 collider 半径和平台中心字段。当前场景代码把平台生成在世界 x/z 原点，但若以后平台中心变化，必须把 platform center 一并写入 telemetry。",
            "- 部分早期 session 的人工方向标签与事件坐标不一致，因此当前规则用实际轨迹的最近径向边缘，不依赖 left/right/front/back 文本标签。",
            "- 阈值是在同一批 session 上选择的，不能视为泛化性能。下一步必须按 session 做留一法或训练/验证划分。",
            "- sway 组只有 3 个 session，其中包含 unknown direction，只作为外部检查，不参与工作点选择。",
            "",
            "## 输出说明",
            "",
            "- `directional_risk_threshold_results.csv`：全部风险阈值和持续时间工作点。",
            "- `directional_risk_session_summary.csv`：选定工作点下每个 session 的报警次数、是否检出和提前时间。",
            "- `directional_risk_window_predictions.csv`：逐窗口特征、风险分数和预测。",
            "- `directional_risk_tradeoffs.png/.pdf`：Precision–Recall 与 session 检出/误报权衡。",
        ]
    )
    (output_dir / "directional_risk_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(args.manifest)
    folders = load_session_folders(args.telemetry_root)
    missing = sorted(set(manifest.loc[as_bool(manifest.included), "session_id"]) - set(folders))
    if missing:
        raise FileNotFoundError(f"Missing session folders: {missing}")

    lookbacks = [1.0, 1.5, 2.0]
    features, session_info = build_feature_table(manifest, folders, lookbacks)
    edge_radius, edge_events = empirical_edge_radius(session_info)
    session_info.to_csv(args.output_dir / "directional_risk_session_inputs.csv", index=False)
    edge_events.to_csv(args.output_dir / "empirical_edge_radius_events.csv", index=False)

    result_rows: list[dict] = []
    evaluated: dict[tuple, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for lookback in lookbacks:
        feature_subset = features.loc[features.lookback_seconds.eq(lookback)].copy()
        for proximity_start in [0.55, 0.65, 0.75, 0.85]:
            for speed_scale in [0.5, 1.0, 1.5]:
                scored = add_risk_score(feature_subset, edge_radius, proximity_start, speed_scale)
                for threshold in np.round(np.arange(0.30, 0.86, 0.05), 3):
                    for hold_windows in [1, 2, 3, 4]:
                        metrics, detail, sessions = evaluate(scored, float(threshold), hold_windows)
                        metrics.update(
                            {
                                "lookback_seconds": lookback,
                                "proximity_start": proximity_start,
                                "speed_scale": speed_scale,
                            }
                        )
                        result_rows.append(metrics)
                        evaluated[(lookback, proximity_start, speed_scale, float(threshold), hold_windows)] = (detail, sessions)

    results = pd.DataFrame(result_rows)
    target = results.loc[results.directional_exit_session_detection_rate.between(0.40, 0.60)].copy()
    if target.empty:
        target = results.assign(target_distance=(results.directional_exit_session_detection_rate - 0.50).abs())
    else:
        target["target_distance"] = (target.directional_exit_session_detection_rate - 0.50).abs()
    selected = target.sort_values(
        [
            "recovery_session_false_alarm_rate",
            "normal_session_false_alarm_rate",
            "precision",
            "mean_non_exit_alarm_episodes",
            "target_distance",
            "f1",
        ],
        ascending=[True, True, False, True, True, False],
    ).iloc[0]
    results["selected"] = False
    selection_mask = np.ones(len(results), dtype=bool)
    for key in ["lookback_seconds", "proximity_start", "speed_scale", "threshold", "hold_windows"]:
        selection_mask &= np.isclose(results[key].astype(float), float(selected[key]))
    results.loc[selection_mask, "selected"] = True
    results = results.sort_values(
        ["selected", "recovery_session_false_alarm_rate", "precision"], ascending=[False, True, False]
    ).reset_index(drop=True)
    results.insert(0, "rank", np.arange(1, len(results) + 1))
    results.to_csv(args.output_dir / "directional_risk_threshold_results.csv", index=False)

    selected_key = (
        float(selected.lookback_seconds),
        float(selected.proximity_start),
        float(selected.speed_scale),
        float(selected.threshold),
        int(selected.hold_windows),
    )
    detail, sessions = evaluated[selected_key]
    detail.to_csv(args.output_dir / "directional_risk_window_predictions.csv", index=False)
    sessions.to_csv(args.output_dir / "directional_risk_session_summary.csv", index=False)
    selected_dict = selected.to_dict()
    selected_dict["empirical_edge_radius"] = edge_radius
    (args.output_dir / "directional_risk_selected_config.json").write_text(
        json.dumps(selected_dict, indent=2, default=float), encoding="utf-8"
    )
    make_plots(results, selected, args.output_dir)

    old_best = None
    if args.old_baseline_dir:
        old_path = args.old_baseline_dir / "baseline_best_config.json"
        if old_path.exists():
            old_best = json.loads(old_path.read_text(encoding="utf-8"))
    if old_best:
        pd.DataFrame(
            [
                {
                    "baseline": "v1_distance_rule",
                    "window_precision": old_best.get("precision"),
                    "window_recall": old_best.get("recall"),
                    "window_f1": old_best.get("f1"),
                    "window_false_positive_rate": old_best.get("false_positive_rate"),
                    "exit_session_detection_rate": old_best.get("session_detection_rate"),
                    "non_exit_session_false_alarm_rate": old_best.get("non_exit_session_false_alarm_rate"),
                    "mean_lead_time_seconds": old_best.get("mean_detection_delay_seconds"),
                },
                {
                    "baseline": "v2_directional_risk",
                    "window_precision": selected.precision,
                    "window_recall": selected.recall,
                    "window_f1": selected.f1,
                    "window_false_positive_rate": selected.window_false_positive_rate,
                    "exit_session_detection_rate": selected.directional_exit_session_detection_rate,
                    "non_exit_session_false_alarm_rate": selected.non_exit_session_false_alarm_rate,
                    "mean_lead_time_seconds": selected.mean_lead_time_seconds,
                },
            ]
        ).to_csv(args.output_dir / "baseline_v1_v2_comparison.csv", index=False)
    write_report(args.output_dir, selected, edge_radius, edge_events, old_best)


if __name__ == "__main__":
    main()
