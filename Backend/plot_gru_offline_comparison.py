"""Create a compact journal-style comparison from corrected GRU replays."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
RUNS = [(0.3, ROOT / "gru_offline_h03_corrected"), (0.5, ROOT / "gru_offline_h05_corrected"), (1.0, ROOT / "gru_offline_h10_corrected"), (2.0, ROOT / "gru_offline_h20_corrected")]
OUT = ROOT / "gru_offline_comparison"


def session_rows(run: Path) -> dict[str, dict]:
    report = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    return {name: value["session"] for name, value in report["baselines"].items()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for horizon, run in RUNS:
        for method, metric in session_rows(run).items():
            rows.append({
                "horizon_s": horizon,
                "method": method,
                "precision": metric.get("precision"),
                "recall": metric.get("recall"),
                "f1": metric.get("f1"),
                "false_alarm_rate": metric.get("nonfall_false_alarm_rate"),
                "median_last_lead_s": metric.get("last_warning_lead_median_s"),
                "p25_last_lead_s": metric.get("last_warning_lead_p25_s"),
                "off_target_alarm_sessions": metric.get("off_target_alarm_sessions"),
            })
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "corrected_session_comparison.csv", index=False, encoding="utf-8-sig")
    frame.to_json(OUT / "corrected_session_comparison.json", orient="records", indent=2, force_ascii=False)
    labels = {"current_yellow_rule": "Current Unity yellow", "time_to_edge": "Time-to-edge", "gru": "GRU"}
    colors = {"current_yellow_rule": "#C73E36", "time_to_edge": "#2A7F9E", "gru": "#6A3D9A"}
    methods = ["current_yellow_rule", "time_to_edge", "gru"]
    horizons = [0.3, 0.5, 1.0, 2.0]
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11, "axes.labelsize": 10})
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 4.15), constrained_layout=True)
    for method in methods:
        sub = frame.loc[frame.method.eq(method)].set_index("horizon_s").reindex(horizons)
        axes[0].plot(horizons, sub.f1, marker="o", linewidth=2, label=labels[method], color=colors[method])
        axes[1].plot(horizons, sub.false_alarm_rate * 100, marker="o", linewidth=2, label=labels[method], color=colors[method])
        axes[2].plot(horizons, sub.median_last_lead_s, marker="o", linewidth=2, label=labels[method], color=colors[method])
    axes[0].set_title("Corrected session F1"); axes[0].set_ylabel("F1"); axes[0].set_ylim(0, 1); axes[0].set_xlabel("Forecast horizon H (s)")
    axes[1].set_title("Non-fall false alarms"); axes[1].set_ylabel("Sessions (%)"); axes[1].set_ylim(0, 100); axes[1].set_xlabel("Forecast horizon H (s)")
    axes[2].set_title("Last valid warning lead"); axes[2].set_ylabel("Seconds before fall_event"); axes[2].set_xlabel("Forecast horizon H (s)")
    for ax in axes:
        ax.set_xticks(horizons); ax.grid(color="#D8D8D8", linewidth=0.5); ax.spines[["top", "right"]].set_visible(False); ax.set_axisbelow(True)
    axes[0].legend(frameon=False, fontsize=8, loc="best")
    fig.suptitle("TEST929 frozen validation: session-safe GRU comparison", color="#23395B", fontweight="bold")
    fig.savefig(OUT / "figure_corrected_gru_comparison.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / "figure_corrected_gru_comparison.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
