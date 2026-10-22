from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent / "telemetry_logs" / "tte_lgbm_targeted_20261002_corrected"

def main():
    t = pd.read_csv(ROOT / "development_tte_grid.csv")
    l = pd.read_csv(ROOT / "development_lightgbm_temporal_grid.csv")
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5})
    fig, ax = plt.subplots(1, 2, figsize=(10, 4.4), constrained_layout=True)
    sc = ax[0].scatter(t.nonfall_false_alarm_rate * 100, t.last_warning_lead_median_s, c=t.horizon_s, cmap="viridis", s=28, alpha=.8)
    ax[0].set_title("Time-to-edge: development trade-off")
    ax[0].set_xlabel("Non-fall session false-alarm rate (%)")
    ax[0].set_ylabel("Median last-warning lead (s)")
    fig.colorbar(sc, ax=ax[0], label="Horizon (s)")
    for k, g in l.groupby("consecutive_windows"):
        ax[1].scatter(g.nonfall_false_alarm_rate * 100, g.last_warning_lead_median_s, s=28, alpha=.75, label=f"{k} consecutive")
    ax[1].set_title("LightGBM: threshold and temporal filter")
    ax[1].set_xlabel("Non-fall session false-alarm rate (%)")
    ax[1].set_ylabel("Median last-warning lead (s)")
    ax[1].legend(frameon=False)
    for a in ax:
        a.grid(alpha=.25); a.spines[["top", "right"]].set_visible(False)
    fig.savefig(ROOT / "figure_targeted_tradeoff.png", dpi=300, bbox_inches="tight")
    fig.savefig(ROOT / "figure_targeted_tradeoff.pdf", bbox_inches="tight")
    plt.close(fig)

if __name__ == "__main__":
    main()
