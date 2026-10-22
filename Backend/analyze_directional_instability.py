"""Explore directional, recoverable, and pre-edge-exit window behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def sessions(user_dirs: list[Path]):
    for user_dir in user_dirs:
        for folder in sorted(user_dir.glob("session_*")):
            qpath = folder / "quality.json"
            if not qpath.exists() or not (folder / "aligned_60hz.csv").exists():
                continue
            q = json.loads(qpath.read_text(encoding="utf-8"))
            if q.get("analysis_status") in ("included", "included_normal_only"):
                yield folder, q


def window_features(folder: Path, quality: dict) -> pd.DataFrame:
    aligned = pd.read_csv(folder / "aligned_60hz.csv")
    windows = pd.read_csv(folder / "windows.csv")
    if quality.get("analysis_status") == "included_normal_only":
        windows = windows[windows.failure_label.eq(0)].copy()
    rows = []
    for _, w in windows.iterrows():
        s = aligned[(aligned.backend_timestamp >= w.window_start) & (aligned.backend_timestamp <= w.window_end)].copy()
        s = s[s.valid_sensor_sample.eq(True) & s.unity_aligned.eq(True)]
        if len(s) < 5:
            continue
        x = s.cop_x.to_numpy(float)
        z = s.cop_z.to_numpy(float)
        d = s.distance_to_hole.to_numpy(float)
        dx = np.diff(x)
        dz = np.diff(z)
        step = np.sqrt(dx * dx + dz * dz)
        net_x, net_z = x[-1] - x[0], z[-1] - z[0]
        net = float(np.hypot(net_x, net_z))
        path = float(step.sum())
        direction_consistency = float(np.mean((dx * net_x + dz * net_z) >= 0)) if len(step) else np.nan
        duration = float(s.backend_timestamp.iloc[-1] - s.backend_timestamp.iloc[0])
        distance_slope = float(np.polyfit(s.backend_timestamp.to_numpy(float), d, 1)[0]) if duration > 0 else np.nan
        half = max(2, len(s) // 2)
        recent_duration = float(s.backend_timestamp.iloc[-1] - s.backend_timestamp.iloc[-half])
        recent_slope = float(np.polyfit(s.backend_timestamp.iloc[-half:].to_numpy(float), d[-half:], 1)[0]) if recent_duration > 0 else np.nan
        rows.append({
            "session_id": folder.name,
            "condition": quality.get("condition", "unknown"),
            "fall_direction": quality.get("fall_direction", "unknown"),
            "failure_label": int(w.failure_label),
            "window_start": float(w.window_start),
            "window_end": float(w.window_end),
            "cop_net_displacement": net,
            "cop_path_length": path,
            "cop_straightness": net / path if path > 0 else 0.0,
            "cop_direction_consistency": direction_consistency,
            "cop_signed_x_displacement": float(net_x),
            "cop_signed_z_displacement": float(net_z),
            "distance_delta": float(d[-1] - d[0]),
            "distance_start": float(d[0]),
            "distance_end": float(d[-1]),
            "distance_mean": float(np.mean(d)),
            "distance_max": float(np.max(d)),
            "distance_slope": distance_slope,
            "recent_distance_slope": recent_slope,
            "cop_speed_mean": float(step.mean() * 60.0),
        })
    return pd.DataFrame(rows)


def summary(features: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "cop_net_displacement", "cop_straightness", "cop_direction_consistency",
        "distance_delta", "distance_slope", "recent_distance_slope", "cop_speed_mean",
    ]
    rows = []
    for col in cols:
        for label, name in ((0, "normal"), (1, "pre_fall")):
            v = features.loc[features.failure_label.eq(label), col].dropna()
            rows.append({"feature": col, "group": name, "n": len(v), "mean": v.mean(), "median": v.median(), "std": v.std()})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("user_dirs", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    frames = [window_features(folder, q) for folder, q in sessions(args.user_dirs)]
    features = pd.concat(frames, ignore_index=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    features.to_csv(args.output_dir / "directional_window_features.csv", index=False)
    summary(features).to_csv(args.output_dir / "directional_feature_summary.csv", index=False)
    normal = features[features.failure_label.eq(0)]
    candidates = ["cop_net_displacement", "cop_straightness", "cop_direction_consistency", "distance_slope", "recent_distance_slope"]
    result = {"windows": int(len(features)), "normal_windows": int(len(normal)), "pre_fall_windows": int((features.failure_label == 1).sum()), "features": {}}
    for col in candidates:
        n = normal[col].dropna()
        p = features.loc[features.failure_label.eq(1), col].dropna()
        threshold = float(n.quantile(0.95))
        result["features"][col] = {
            "normal_median": float(n.median()), "pre_fall_median": float(p.median()),
            "normal_mean": float(n.mean()), "pre_fall_mean": float(p.mean()),
            "normal_p95": threshold,
            "pre_fall_above_normal_p95": float((p >= threshold).mean()) if len(p) else 0.0,
        }
    (args.output_dir / "directional_analysis_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
