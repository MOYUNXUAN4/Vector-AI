"""Interpretable time-based baseline detector for pre-exit windows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


EXIT_GROUPS = {"directional_edge_exit", "sway_then_edge_exit"}
BASE_STEP_SECONDS = 0.25


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--telemetry-root", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    return p.parse_args()


def load_folders(root: Path) -> dict[str, Path]:
    folders = {}
    for qpath in root.glob("*/session_*/quality.json"):
        q = json.loads(qpath.read_text(encoding="utf-8"))
        sid = q.get("session_id") or qpath.parent.name
        folders[sid] = qpath.parent
    return folders


def load_sessions(manifest: pd.DataFrame, folders: dict[str, Path]) -> dict[str, pd.DataFrame]:
    sessions = {}
    for row in manifest.loc[manifest.included.astype(str).str.lower().eq("true")].itertuples(index=False):
        windows = pd.read_csv(folders[row.session_id] / "windows.csv").sort_values("window_end").reset_index(drop=True)
        if windows.empty:
            continue
        windows["distance_rate"] = windows.distance_mean.diff() / windows.window_end.diff()
        windows["distance_rate"] = windows.distance_rate.replace([np.inf, -np.inf], np.nan)
        windows["group"] = row.group
        windows["session_id"] = row.session_id
        windows["session_is_exit"] = row.group in EXIT_GROUPS
        sessions[row.session_id] = windows
    return sessions


def rolling_rule(
    windows: pd.DataFrame,
    distance_threshold: float,
    window_seconds: float,
    move_seconds: float,
    no_return_seconds: float,
    rate_threshold: float = 0.25,
    return_tolerance: float = 0.5,
) -> pd.Series:
    """Return one prediction per base window, using only current/past windows."""
    n_window = max(1, round(window_seconds / BASE_STEP_SECONDS))
    n_move = max(1, round(move_seconds / BASE_STEP_SECONDS))
    n_return = max(1, round(no_return_seconds / BASE_STEP_SECONDS))
    d = windows.distance_mean.astype(float)
    r = windows.distance_rate.astype(float)
    distance_level = d.rolling(n_window, min_periods=n_window).mean()
    # Separate condition 2 and condition 3 in time. The sustained movement
    # segment ends before the recent no-return segment, so the two conditions
    # are not mathematically redundant.
    prior_rate = r.shift(n_return).rolling(n_move, min_periods=n_move).mean()
    prior_positive_fraction = r.gt(0).shift(n_return).rolling(n_move, min_periods=n_move).mean()
    sustained = prior_rate.ge(rate_threshold) & prior_positive_fraction.ge(.75)
    recent_change = d - d.shift(n_return)
    no_return = recent_change.ge(-return_tolerance)
    return distance_level.ge(distance_threshold) & sustained & no_return


def score_config(sessions: dict[str, pd.DataFrame], **params: float) -> tuple[dict, pd.DataFrame]:
    rows = []
    for sid, windows in sessions.items():
        prediction = rolling_rule(windows, **params)
        actual = windows.failure_label.astype(bool)
        for i, row in windows.iterrows():
            pred = bool(prediction.iloc[i])
            truth = bool(actual.iloc[i])
            rows.append(
                {
                    "session_id": sid,
                    "group": row.group,
                    "window_end": row.window_end,
                    "failure_label": int(truth),
                    "predicted_positive": int(pred),
                    "tp": int(pred and truth),
                    "fp": int(pred and not truth),
                    "fn": int((not pred) and truth),
                    "tn": int((not pred) and (not truth)),
                }
            )
    detail = pd.DataFrame(rows)
    tp, fp, fn, tn = [int(detail[x].sum()) for x in ["tp", "fp", "fn", "tn"]]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0

    delay_rows = []
    non_exit_alarm_count = 0
    non_exit_session_count = 0
    for sid, s in detail.groupby("session_id"):
        source = sessions[sid]
        event = bool(source.session_is_exit.iloc[0])
        if not event:
            non_exit_session_count += 1
            non_exit_alarm_count += int(s.predicted_positive.any())
            continue
        # The actual event timestamp is stored in clean.csv; use the first fall_event.
        clean = pd.read_csv(folders_global[sid] / "clean.csv", usecols=["backend_timestamp", "source", "fall_event"])
        flags = clean.fall_event.astype(str).str.lower().eq("true")
        event_times = clean.loc[clean.source.eq("unity") & flags, "backend_timestamp"].dropna().to_numpy(float)
        if len(event_times) == 0:
            continue
        event_time = float(event_times[0])
        # Detection delay is based on the first true-positive alert inside the
        # labelled pre-exit horizon. Earlier alerts are false positives, not
        # legitimate extra-early detections.
        detections = s.loc[s.predicted_positive.eq(1) & s.failure_label.eq(1), "window_end"]
        if len(detections):
            first = float(detections.iloc[0])
            delay_rows.append({"session_id": sid, "detected": True, "lead_time_seconds": event_time - first})
        else:
            delay_rows.append({"session_id": sid, "detected": False, "lead_time_seconds": np.nan})
    delays = pd.DataFrame(delay_rows)
    detected = int(delays.detected.sum()) if len(delays) else 0
    sessions_total = int(len(delays))
    metrics = {
        **params,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fpr,
        "exit_sessions": sessions_total,
        "exit_sessions_detected": detected,
        "session_detection_rate": detected / sessions_total if sessions_total else 0.0,
        "non_exit_sessions": non_exit_session_count,
        "non_exit_sessions_with_alarm": non_exit_alarm_count,
        "non_exit_session_false_alarm_rate": non_exit_alarm_count / non_exit_session_count if non_exit_session_count else 0.0,
        "mean_detection_delay_seconds": float(delays.loc[delays.detected, "lead_time_seconds"].mean()) if detected else np.nan,
        "median_detection_delay_seconds": float(delays.loc[delays.detected, "lead_time_seconds"].median()) if detected else np.nan,
    }
    return metrics, delays


def main() -> None:
    global folders_global
    a = parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(a.manifest)
    folders_global = load_folders(a.telemetry_root)
    sessions = load_sessions(manifest, folders_global)

    configs = []
    for window_seconds in [1.0, 1.5, 2.0]:
        for distance_threshold in [3.0, 5.0, 7.0, 9.0]:
            for move_seconds in [0.5, 1.0, 1.5, 2.0]:
                for no_return_seconds in [0.5, 1.0]:
                    configs.append(
                        {
                            "window_seconds": window_seconds,
                            "distance_threshold": distance_threshold,
                            "move_seconds": move_seconds,
                            "no_return_seconds": no_return_seconds,
                            "rate_threshold": 0.25,
                            "return_tolerance": 0.5,
                        }
                    )

    metric_rows, delay_rows = [], []
    for config_id, config in enumerate(configs):
        metrics, delays = score_config(sessions, **config)
        metrics["config_id"] = config_id
        metric_rows.append(metrics)
        delays["config_id"] = config_id
        delay_rows.append(delays)
    metrics = pd.DataFrame(metric_rows).sort_values(["f1", "recall", "precision"], ascending=False).reset_index(drop=True)
    metrics.insert(0, "rank", np.arange(1, len(metrics) + 1))
    metrics.to_csv(a.output_dir / "baseline_threshold_results.csv", index=False)
    if delay_rows:
        pd.concat(delay_rows, ignore_index=True).to_csv(a.output_dir / "baseline_detection_delays.csv", index=False)

    best = metrics.iloc[0].to_dict()
    best_by_distance = (
        metrics.sort_values(["distance_threshold", "f1"], ascending=[True, False])
        .groupby("distance_threshold", as_index=False)
        .first()
    )
    best_by_distance.to_csv(a.output_dir / "baseline_best_by_distance_threshold.csv", index=False)
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11})
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), constrained_layout=True)
    axes[0].plot(best_by_distance.distance_threshold, best_by_distance.f1, marker="o", color="#1764A0", label="F1")
    axes[0].plot(best_by_distance.distance_threshold, best_by_distance.recall, marker="s", color="#2F8F57", label="Recall")
    axes[0].plot(best_by_distance.distance_threshold, best_by_distance.precision, marker="^", color="#C73E36", label="Precision")
    axes[0].set_xlabel("Distance threshold")
    axes[0].set_ylabel("Window-level score")
    axes[0].set_title("Best rule at each distance threshold")
    axes[0].grid(axis="y", color="#D8D8D8", linewidth=.5)
    axes[0].spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False)
    axes[1].plot(best_by_distance.distance_threshold, best_by_distance.false_positive_rate, marker="o", color="#C73E36", label="Window FPR")
    axes[1].plot(best_by_distance.distance_threshold, best_by_distance.non_exit_session_false_alarm_rate, marker="s", color="#7E52A0", label="Non-exit session alarm rate")
    axes[1].plot(best_by_distance.distance_threshold, best_by_distance.session_detection_rate, marker="^", color="#2F8F57", label="Exit-session detection rate")
    axes[1].set_xlabel("Distance threshold")
    axes[1].set_ylabel("Rate")
    axes[1].set_ylim(-.03, 1.05)
    axes[1].set_title("Detection–false-alarm trade-off")
    axes[1].grid(axis="y", color="#D8D8D8", linewidth=.5)
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle("Time-rule baseline: threshold sensitivity", fontsize=13)
    fig.savefig(a.output_dir / "baseline_threshold_tradeoffs.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(a.output_dir / "baseline_threshold_tradeoffs.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    (a.output_dir / "baseline_best_config.json").write_text(json.dumps(best, indent=2, default=str), encoding="utf-8")
    report = [
        "# 周三：时间型 baseline 检测规则",
        "",
        "规则按 session 的时间顺序逐窗口运行，不使用神经网络。每个预测时刻必须同时满足：",
        "",
        "1. 最近指定时间窗的平均 `distance_mean` 达到边缘距离阈值；",
        "2. 在最近 no-return 区间之前的指定持续时间内，平均 `distance_rate` 至少为 0.25，且至少 75% 的变化率为正；",
        "3. 最近 0.5 或 1.0 秒内，`distance_mean` 没有下降超过 0.5，作为“没有明显回中心动作”的宽松判据。",
        "",
        f"共测试 {len(metrics)} 组参数：distance window = 1/1.5/2 s，距离阈值 = 3/5/7/9，持续移动时间 = 0.5/1/1.5/2 s，no-return 时间 = 0.5/1 s。",
        "",
        "## 指标定义",
        "",
        "- Precision、Recall、F1、False-positive rate 均按窗口级 failure_label 计算。",
        "- Detection delay 定义为：真实 Unity fall_event 时间减去该 session 第一次触发规则的时间；正值表示提前预警秒数。",
        "- 另外报告 exit-session detection rate，避免窗口级重叠造成结果看起来过度乐观。",
        "",
        "## 当前最优配置（按 F1 排序）",
        "",
        "| 参数 | 值 |",
        "|---|---:|",
    ]
    for key in ["window_seconds", "distance_threshold", "move_seconds", "no_return_seconds", "rate_threshold", "return_tolerance", "precision", "recall", "f1", "false_positive_rate", "session_detection_rate", "non_exit_session_false_alarm_rate", "mean_detection_delay_seconds"]:
        value = best.get(key)
        report.append(f"| {key} | {value:.4f} |" if isinstance(value, float) else f"| {key} | {value} |")
    report.extend(
        [
            "",
            "## 各距离阈值的最佳结果",
            "",
            "| Distance threshold | Window (s) | Move (s) | Precision | Recall | F1 | Window FPR | Exit-session detection | Non-exit session alarm | Mean lead time (s) |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in best_by_distance.itertuples(index=False):
        report.append(
            f"| {row.distance_threshold:.1f} | {row.window_seconds:.1f} | {row.move_seconds:.1f} | "
            f"{row.precision:.3f} | {row.recall:.3f} | {row.f1:.3f} | {row.false_positive_rate:.3f} | "
            f"{row.session_detection_rate:.3f} | {row.non_exit_session_false_alarm_rate:.3f} | "
            f"{row.mean_detection_delay_seconds:.3f} |"
        )
    report.extend(
        [
            "",
            "完整参数表见 `baseline_threshold_results.csv`；每个坠出 session 的首次触发和提前量见 `baseline_detection_delays.csv`。",
            "",
            "## 注意",
            "",
            "该 baseline 可以运行且可解释，但当前不能作为可靠预警器：F1 很低，而且低到中等距离阈值会使全部非坠出 session 至少触发一次警报。提高阈值可以降低误报，但同时几乎失去检出能力。",
            "窗口级指标不能替代 session-level 结论；相邻窗口重叠，因此后续正式评估应以 session 划分训练/验证/测试，并报告 session detection rate 和 detection delay。",
            "",
        ]
    )
    (a.output_dir / "baseline_report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({"configs": len(metrics), "sessions": len(sessions), "best": best}, indent=2, default=str))


if __name__ == "__main__":
    folders_global: dict[str, Path] = {}
    main()
