"""Create a compact frozen-set comparison figure from comparison_metrics.csv."""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


OUT = Path(__file__).resolve().parent / "telemetry_logs" / "tree_model_comparison_20261002"
METRICS = OUT / "comparison_metrics.csv"


def main() -> None:
    frame = pd.read_csv(METRICS)
    methods = [
        ("current_geometric_warning", "Geometry rule"),
        ("time_to_edge", "Time-to-edge"),
        ("lightgbm", "LightGBM"),
        ("random_forest", "Random forest"),
        ("gru", "GRU"),
    ]
    rows = frame[frame["dataset"].isin(["TEST929", "TEST1001"])].copy()
    rows["label"] = rows["method"].map(dict(methods))
    rows = rows.dropna(subset=["label"])
    order = [label for _, label in methods]
    rows["label"] = pd.Categorical(rows["label"], categories=order, ordered=True)

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 7.0), constrained_layout=True)
    panels = [
        ("session_f1", "Session F1", (0, 1)),
        ("session_precision", "Session precision", (0, 1)),
        ("session_nonfall_false_alarm_rate", "Non-fall false-alarm rate", (0, 1)),
        ("session_last_warning_lead_median_s", "Median last-warning lead (s)", (0, None)),
    ]
    colors = {"TEST929": "#2f6db0", "TEST1001": "#d17a22"}
    for ax, (column, title, ylim) in zip(axes.flat, panels):
        pivot = rows.pivot(index="label", columns="dataset", values=column).reindex(order)
        x = range(len(order))
        width = 0.36
        for offset, dataset in [(-width / 2, "TEST929"), (width / 2, "TEST1001")]:
            values = pivot[dataset].to_numpy(dtype=float)
            ax.bar([i + offset for i in x], values, width=width, label=dataset, color=colors[dataset])
        ax.set_title(title)
        ax.set_xticks(list(x), order, rotation=25, ha="right")
        if ylim[1] is not None:
            ax.set_ylim(*ylim)
        ax.grid(axis="y", alpha=0.25)
    axes[0, 0].legend(frameon=False, ncol=2, loc="upper right")
    fig.suptitle("Frozen evaluation: TEST929 and TEST1001", fontsize=13, fontweight="bold")
    fig.savefig(OUT / "figure_model_comparison_frozen.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / "figure_model_comparison_frozen.pdf", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
