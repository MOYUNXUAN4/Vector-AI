"""Estimate sway amplitude and reversal frequency from aligned COP telemetry."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def metrics(folder: Path) -> dict:
    data = pd.read_csv(folder / "aligned_60hz.csv")
    data = data[data.valid_sensor_sample.eq(True) & data.unity_aligned.eq(True)].copy()
    results = []
    for start in range(0, len(data) - 60, 15):
        s = data.iloc[start:start + 60]
        x, z = s.cop_x.to_numpy(float), s.cop_z.to_numpy(float)
        dx, dz = np.diff(x), np.diff(z)
        speed = np.hypot(dx, dz) * 60.0
        threshold = 0.01
        sx = np.sign(np.where(np.abs(dx) >= threshold, dx, 0))
        sz = np.sign(np.where(np.abs(dz) >= threshold, dz, 0))
        sx = sx[sx != 0]
        sz = sz[sz != 0]
        reversals = int((np.diff(sx) != 0).sum() + (np.diff(sz) != 0).sum())
        results.append({
            "cop_range": float(np.hypot(np.ptp(x), np.ptp(z))),
            "cop_rmse": float(np.sqrt(np.mean((x-x.mean())**2 + (z-z.mean())**2))),
            "speed_mean": float(speed.mean()),
            "speed_max": float(speed.max()),
            "reversals_per_second": reversals,
        })
    frame = pd.DataFrame(results)
    out = {"session_id": folder.name, "window_count": len(frame)}
    for col in frame.columns:
        out[f"{col}_median"] = float(frame[col].median())
        out[f"{col}_p95"] = float(frame[col].quantile(.95))
        out[f"{col}_max"] = float(frame[col].max())
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dirs", type=Path, nargs="+")
    args = parser.parse_args()
    result = pd.DataFrame([metrics(folder) for folder in args.session_dirs])
    print(result.to_csv(index=False))


if __name__ == "__main__":
    main()
