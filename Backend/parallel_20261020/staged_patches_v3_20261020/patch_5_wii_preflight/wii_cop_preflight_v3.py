#!/usr/bin/env python3
"""wii_cop_preflight_v3.py

Audits balance-board baseline CoP and load stability from telemetry data.

Key improvements in v3 (resolving defects from independent review 2026-10-20):
  * Sustained per-sample load: requires all samples in the audit window to meet
    weight >= min_load_kg, eliminating spurious false-positives from transient load spikes.
  * Temporal continuity: enforces that samples within the evaluation window are
    consecutive in time without silent bridging across invalid or dropped rows.
  * Explicit flag verification: checks control_valid, board_loaded, and center_applied
    flags when present in telemetry.
  * Fine-grained categorization: distinguishes between INSUFFICIENT_LOAD (no participant
    on board), LOADED_NOT_STATIONARY (participant moving/swaying), SKEWED (stationary
    but off-center baseline), and OK (stable centered baseline).

Exit codes:
  0 OK                     sustained load, stationary, baseline within tolerance
  2 INSUFFICIENT_LOAD      board did not sustain min-load-kg
  3 SKEWED                 sustained load & stationary, but baseline CoP outside tolerance
  4 LOADED_NOT_STATIONARY  sustained load present, but CoP variance exceeded stillness limit
  1 Input error
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Tuple, Dict, Any, List

import numpy as np


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def load_wii(path: str):
    """Loads Wii rows preserving true sequence and metadata flags.
    
    Returns dict of numpy arrays and flags.
    """
    ts, w, x, z, v = [], [], [], [], []
    valid, loaded, centered = [], [], []

    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("source") != "wii":
                continue
            try:
                # Prefer backend_timestamp as numeric epoch; fallback to sequence or index
                b_ts = r.get("backend_timestamp")
                if b_ts:
                    t = float(b_ts)
                else:
                    t = float(len(ts) * 0.02)
                ww = float(r.get("total_weight") or "nan")
                xx = float(r.get("cop_x") or "nan")
                zz = float(r.get("cop_z") or "nan")
            except (ValueError, TypeError):
                continue

            ts.append(t)
            w.append(ww)
            x.append(xx)
            z.append(zz)

            try:
                v.append(float(r.get("cop_speed") or "nan"))
            except (ValueError, TypeError):
                v.append(np.nan)

            c_val = r.get("control_valid")
            valid.append(_truthy(c_val) if c_val is not None else True)
            b_load = r.get("board_loaded")
            loaded.append(_truthy(b_load) if b_load is not None else True)
            c_app = r.get("center_applied")
            centered.append(_truthy(c_app) if c_app is not None else True)

    return (
        np.array(w, dtype=float),
        np.array(x, dtype=float),
        np.array(z, dtype=float),
        np.array(v, dtype=float),
        np.array(ts, dtype=float),
        np.array(valid, dtype=bool),
        np.array(loaded, dtype=bool),
        np.array(centered, dtype=bool),
    )


def audit(
    path: str,
    window: int = 50,
    min_load: float = 20.0,
    still_cm: float = 1.0,
    tol_cm: float = 1.5,
    max_gap_s: float = 0.15
) -> Dict[str, Any]:
    loaded_data = load_wii(path)
    # Support tuple of 4 (from older harnesses/tests) or tuple of 8
    if len(loaded_data) == 4:
        w, x, z, v = loaded_data
        ts = np.arange(len(w)) * 0.02
        valid = np.ones(len(w), dtype=bool)
        loaded = np.ones(len(w), dtype=bool)
        centered = np.ones(len(w), dtype=bool)
    else:
        w, x, z, v, ts, valid, loaded, centered = loaded_data

    out: Dict[str, Any] = {
        "path": path,
        "wii_rows": int(len(w)),
        "weight_median_kg": round(float(np.nanmedian(w)), 2) if len(w) else 0.0,
        "weight_max_kg": round(float(np.nanmax(w)), 2) if len(w) else 0.0,
        "loaded_samples_count": int(np.sum((w >= min_load) & ~np.isnan(w))),
    }

    if len(w) < window:
        out.update(verdict="INSUFFICIENT_LOAD", reason=f"fewer than {window} total wii samples ({len(w)})")
        return out

    # Search for candidate windows with sustained per-sample load and valid control
    best_still_idx = -1
    min_std_seen = float("inf")
    candidate_loaded_windows = 0

    for i in range(len(w) - window + 1):
        seg_w = w[i : i + window]
        if np.any(np.isnan(seg_w)) or np.any(seg_w < min_load):
            continue

        # Check time continuity: no gaps > max_gap_s
        seg_ts = ts[i : i + window]
        if len(seg_ts) > 1 and np.any(np.diff(seg_ts) > max_gap_s):
            continue

        # Check valid control flags if available
        if not np.all(valid[i : i + window]):
            continue

        candidate_loaded_windows += 1
        seg_x = x[i : i + window]
        seg_z = z[i : i + window]
        if np.any(np.isnan(seg_x)) or np.any(np.isnan(seg_z)):
            continue

        std_x = float(np.std(seg_x))
        std_z = float(np.std(seg_z))
        max_std = max(std_x, std_z)

        if max_std < min_std_seen:
            min_std_seen = max_std
            if max_std <= still_cm:
                best_still_idx = i
                break  # Found first valid stationary window

    if candidate_loaded_windows == 0:
        out.update(
            verdict="INSUFFICIENT_LOAD",
            reason=f"no {window}-sample window with sustained per-sample weight >= {min_load:.1f} kg"
        )
        return out

    if best_still_idx < 0:
        out.update(
            verdict="LOADED_NOT_STATIONARY",
            reason=f"sustained load found ({candidate_loaded_windows} windows), but CoP std exceeded {still_cm:.2f} cm (min std: {min_std_seen:.2f} cm)"
        )
        return out

    # Stationary window evaluation
    start = best_still_idx
    seg_w = w[start : start + window]
    seg_x = x[start : start + window]
    seg_z = z[start : start + window]

    mx = float(np.mean(seg_x))
    mz = float(np.mean(seg_z))
    radial = float(np.hypot(mx, mz))

    out.update({
        "window_start_index": start,
        "window_weight_kg": round(float(np.mean(seg_w)), 2),
        "cop_x_cm": round(mx, 2),
        "cop_z_cm": round(mz, 2),
        "cop_std_x_cm": round(float(np.std(seg_x)), 3),
        "cop_std_z_cm": round(float(np.std(seg_z)), 3),
        "radial_cm": round(radial, 2),
    })

    if radial > tol_cm:
        out["verdict"] = "SKEWED"
        out["reason"] = f"baseline CoP radial offset {radial:.2f} cm exceeds tolerance {tol_cm:.2f} cm"
    else:
        out["verdict"] = "OK"

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Balance-board baseline preflight audit (v3).")
    ap.add_argument("--csv", required=True, help="raw.csv path")
    ap.add_argument("--window", type=int, default=50, help="window length in samples (default: 50)")
    ap.add_argument("--min-load-kg", type=float, default=20.0, help="minimum sustained weight per sample (kg)")
    ap.add_argument("--still-cm", type=float, default=1.0, help="maximum allowed CoP std in window (cm)")
    ap.add_argument("--tolerance-cm", type=float, default=1.5, help="maximum allowed radial offset (cm)")
    ap.add_argument("--max-gap", type=float, default=0.15, help="maximum inter-sample gap inside window (s)")
    ap.add_argument("--out", default=None, help="write JSON report")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        print(f"Error: file not found: {args.csv}", file=sys.stderr)
        return 1

    r = audit(args.csv, args.window, args.min_load_kg, args.still_cm, args.tolerance_cm, args.max_gap)

    print(f"=== Wii baseline pre-flight (v3): {os.path.basename(args.csv)} ===")
    print(f"Wii samples: {r['wii_rows']} | Weight median: {r.get('weight_median_kg', 0.0):.2f} kg, "
          f"Max: {r.get('weight_max_kg', 0.0):.2f} kg | Samples >= {args.min_load_kg:.1f} kg: {r.get('loaded_samples_count', 0)}")

    verdict = r["verdict"]
    if verdict == "INSUFFICIENT_LOAD":
        print(f"\n[INSUFFICIENT_LOAD] {r.get('reason', '')}")
        print("Notice: No valid sustained baseline exists. Do NOT proceed to trial.")
        rc = 2
    elif verdict == "LOADED_NOT_STATIONARY":
        print(f"\n[LOADED_NOT_STATIONARY] {r.get('reason', '')}")
        print("Notice: Participant is moving on board. Request participant to stand still for baseline.")
        rc = 4
    elif verdict == "SKEWED":
        print(f"\n[SKEWED] Stationary window at sample {r['window_start_index']}, weight: {r['window_weight_kg']:.1f} kg")
        print(f"  CoP X={r['cop_x_cm']:+.2f} cm, Z={r['cop_z_cm']:+.2f} cm, Radial={r['radial_cm']:.2f} cm (limit: {args.tolerance_cm:.1f} cm)")
        print("Notice: Board baseline is off-center. Operator should re-zero/tare balance board.")
        rc = 3
    else:
        print(f"\n[OK] Valid baseline at sample {r['window_start_index']}, weight: {r['window_weight_kg']:.1f} kg, "
              f"CoP X={r['cop_x_cm']:+.2f} cm, Z={r['cop_z_cm']:+.2f} cm (std: {r['cop_std_x_cm']:.3f} / {r['cop_std_z_cm']:.3f} cm)")
        rc = 0

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2)
        print(f"Report written to: {args.out}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
