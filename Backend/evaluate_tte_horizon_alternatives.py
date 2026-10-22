from pathlib import Path
import pandas as pd
import compare_tree_models as tree
import train_gru_offline as gru
from optimize_tte_lgbm_targeted import tte_mask, event_rule_metrics

OUT = Path(__file__).resolve().parent / "telemetry_logs" / "tte_lgbm_targeted_20261002_corrected"

def main():
    dev, _ = tree.load_development()
    test929, test1001 = tree.load_test929(), tree.load_test1001()
    names = {n: i for i, n in enumerate(gru.FEATURE_CANDIDATES)}
    indices = [names[n] for n in tree.SELECTED_FEATURES if n in names]
    tree.prepare_sessions(dev + test929 + test1001, indices)
    records = []
    for dataset, group in [("TEST929", test929), ("TEST1001", test1001)]:
        for h in (0.3, 0.4, 0.5, 0.6):
            masks = [tte_mask(s, h, 0.2, 0.05, 0.0) for s in group]
            sm = event_rule_metrics(group, masks)
            records.append({"dataset": dataset, "horizon_s": h, "persistence_s": 0.2, "min_outward_velocity": 0.05, "cancel_window_s": 0.0, **sm})
    pd.DataFrame(records).to_csv(OUT / "tte_horizon_alternatives_frozen.csv", index=False, encoding="utf-8-sig")

if __name__ == "__main__":
    main()
