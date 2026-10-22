"""Read-only diagnostic for geometry-threshold versus Unity warning-state rows."""
from pathlib import Path
import pandas as pd

BASE = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs")
DATASETS = ("TEST9282", "TEST929", "TEST930", "TEST931", "TEST1001")
rows = []
for dataset in DATASETS:
    for path in sorted((BASE / dataset).glob("session_*/raw.csv")):
        raw = pd.read_csv(path, low_memory=False)
        unity = raw.loc[raw["source"].astype(str).str.lower().eq("unity")].copy()
        if unity.empty:
            continue
        edge = pd.to_numeric(unity["directional_edge_distance"], errors="coerce")
        threshold = pd.to_numeric(unity["edge_warning_distance_threshold"], errors="coerce")
        warning = unity["edge_warning_state"].astype(str).str.lower().isin({"true", "1", "yes"})
        running = ~unity["run_state"].astype(str).str.lower().eq("ended")
        expected_warning = edge.le(threshold + 1e-4)
        mismatch = expected_warning & ~warning & running
        for index in unity.index[mismatch]:
            row = unity.loc[index]
            rows.append({
                "dataset": dataset,
                "session_id": path.parent.name,
                "sequence": row.get("sequence"),
                "backend_timestamp": row.get("backend_timestamp"),
                "platform_level": row.get("platform_level"),
                "directional_edge_distance": edge.loc[index],
                "edge_warning_distance_threshold": threshold.loc[index],
                "edge_warning_state": row.get("edge_warning_state"),
                "prediction_state": row.get("prediction_state"),
                "fall_event": row.get("fall_event"),
            })
result = pd.DataFrame(rows)
out = BASE / "analysis_geometry_consistency_20261002_corrected"
out.mkdir(parents=True, exist_ok=True)
result.to_csv(out / "warning_state_mismatch_rows.csv", index=False, encoding="utf-8-sig")
print(f"mismatch_rows={len(result)}")
if not result.empty:
    print(result.groupby("dataset").size().to_string())
    print(result.head(20).to_string(index=False))
