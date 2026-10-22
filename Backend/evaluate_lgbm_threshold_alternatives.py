from pathlib import Path
import numpy as np
import pandas as pd
import compare_tree_models as tree
import train_gru_offline as gru
from optimize_tte_lgbm_targeted import temporal_filter

OUT = Path(__file__).resolve().parent / "telemetry_logs" / "tte_lgbm_targeted_20261002_corrected"

def main():
    dev, _ = tree.load_development()
    test929, test1001 = tree.load_test929(), tree.load_test1001()
    names = {n: i for i, n in enumerate(gru.FEATURE_CANDIDATES)}
    indices = [names[n] for n in tree.SELECTED_FEATURES if n in names and any(np.isfinite(s["feature_table"][:, names[n]]).any() for s in dev)]
    tree.prepare_sessions(dev + test929 + test1001, indices)
    dev_rows = tree.examples(dev)
    records = []
    for dataset, group in [("TEST929", test929), ("TEST1001", test1001)]:
        rows = tree.examples(group)
        prob, _, _ = tree.tree_probabilities("lightgbm", dev_rows, rows, 20261002)
        for threshold in (0.75, 0.80, 0.85, 0.90):
            for consecutive in (1, 2):
                pred = temporal_filter(rows, prob, threshold, consecutive)
                result, _ = gru.metrics_from_predictions(rows, pred, "lightgbm")
                sm = result["session"]
                records.append({"dataset": dataset, "threshold": threshold, "consecutive_windows": consecutive, **sm})
    pd.DataFrame(records).to_csv(OUT / "lightgbm_threshold_alternatives_frozen.csv", index=False, encoding="utf-8-sig")

if __name__ == "__main__":
    main()
