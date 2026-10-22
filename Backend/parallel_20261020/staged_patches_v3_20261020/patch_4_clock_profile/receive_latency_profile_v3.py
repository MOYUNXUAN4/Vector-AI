#!/usr/bin/env python3
"""receive_latency_profile_v3.py

Measures and profiles backend receive latency (backend_timestamp - source_timestamp)
and detects latency steps both across source gaps and within continuous sampling streams.

Key improvements in v3 (resolving defects from independent review 2026-10-20):
  * Correct scope & provenance: explicitly scopes measurements as backend receive
    latency (transport + queue + receive epoch delta), NOT Unity Time.time dual-clock
    alignment.
  * In-stream step detection: detects latency jumps/steps occurring inside continuous
    streams (without requiring an inter-packet gap > max-gap). Catches abrupt changes
    such as 5ms -> 105ms steps in continuous 20ms streams.
  * Dual-clock separation: if geometry_source_timestamp is present, evaluates Unity
    internal clock stability separately from network receive latency.
  * Honest reporting: eliminates unproven claims that NO_STEP validates a single
    global offset for Unity/UTC clock domain alignment.

Exit codes:
  0  NO_STEP          receive latency stable within tolerance
  3  STEP_DETECTED    latency step exceeding threshold detected (between or within segments)
  4  DOMAIN_ERROR     timestamps appear crossed or outside reasonable Unix epoch
  1  Input error
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Tuple, List, Dict, Any

import numpy as np


def load(path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, list]:
    src, bck, geom, seq = [], [], [], []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("source") != "unity":
                continue
            try:
                s = float(r["source_timestamp"])
                b = float(r["backend_timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            src.append(s)
            bck.append(b)
            g = r.get("geometry_source_timestamp") or ""
            try:
                geom.append(float(g) if g else np.nan)
            except ValueError:
                geom.append(np.nan)
            try:
                seq.append(int(float(r.get("sequence") or "nan")))
            except ValueError:
                seq.append(None)
    return np.array(src), np.array(bck), np.array(geom, dtype=float), seq


def detect_in_segment_step(latency: np.ndarray, min_window: int = 10) -> Tuple[float, int]:
    """Detects abrupt step within a continuous latency array using adjacent sliding windows.
    
    Returns (max_step_ms, step_index).
    """
    n = len(latency)
    if n < min_window * 2:
        return 0.0, -1

    w = max(min_window, min(25, n // 4))
    max_step = 0.0
    best_idx = -1

    # Compare rolling median of left window vs right window
    for i in range(w, n - w + 1):
        left_med = np.median(latency[i - w : i])
        right_med = np.median(latency[i : i + w])
        step = abs(right_med - left_med) * 1000.0  # ms
        if step > max_step:
            max_step = float(step)
            best_idx = i

    return round(max_step, 3), best_idx


def analyse(path: str, max_gap_s: float = 0.4, step_threshold_ms: float = 5.0) -> Dict[str, Any]:
    src, bck, geom, seq = load(path)
    if len(src) < 10:
        return {"error": "too few unity rows (<10)", "path": path}

    latency = bck - src
    domain_ok = bool(np.nanmean(src) > 1e8 and (np.all(np.isnan(geom)) or np.nanmean(geom) < 1e6))

    # Segment boundaries by source time gaps
    dt = np.diff(src)
    bounds = np.where(dt > max_gap_s)[0]
    starts = [0] + list(bounds + 1)
    ends = list(bounds + 1) + [len(src)]

    segments: List[Dict[str, Any]] = []
    max_intra_step = 0.0

    for i, (a, b) in enumerate(zip(starts, ends)):
        seg_lat = latency[a:b]
        gaps_inside = dt[a:b - 1] if b - 1 > a else np.array([])
        intra_step, intra_idx = detect_in_segment_step(seg_lat)
        if intra_step > max_intra_step:
            max_intra_step = intra_step

        segments.append({
            "index": i,
            "rows": int(b - a),
            "duration_s": round(float(src[b - 1] - src[a]), 3),
            "median_ms": round(float(np.median(seg_lat)) * 1000.0, 3),
            "mean_ms": round(float(np.mean(seg_lat)) * 1000.0, 3),
            "p95_ms": round(float(np.percentile(seg_lat, 95)) * 1000.0, 3),
            "std_ms": round(float(np.std(seg_lat)) * 1000.0, 3),
            "max_gap_inside_ms": round(float(gaps_inside.max()) * 1000.0, 3) if gaps_inside.size else 0.0,
            "max_intra_step_ms": intra_step,
        })

    medians = np.array([s["median_ms"] for s in segments])
    inter_steps = np.abs(np.diff(medians)) if len(medians) > 1 else np.array([0.0])
    max_inter_step = float(inter_steps.max()) if inter_steps.size else 0.0

    overall_max_step = max(max_inter_step, max_intra_step)
    step_detected = bool(overall_max_step > step_threshold_ms)

    # Dual-clock drift within Unity if geom is present
    unity_dual_clock: Dict[str, Any] = {}
    valid_geom = ~np.isnan(geom)
    if np.sum(valid_geom) >= 10:
        unity_clock_diff = src[valid_geom] - geom[valid_geom]
        unity_dual_clock = {
            "unity_clock_offset_median_s": round(float(np.median(unity_clock_diff)), 6),
            "unity_clock_offset_spread_ms": round(float(np.ptp(unity_clock_diff)) * 1000.0, 3),
            "unity_clock_offset_std_ms": round(float(np.std(unity_clock_diff)) * 1000.0, 3),
        }

    return {
        "path": path,
        "unity_rows": int(len(src)),
        "latency_median_ms": round(float(np.median(latency)) * 1000.0, 3),
        "latency_p95_ms": round(float(np.percentile(latency, 95)) * 1000.0, 3),
        "latency_max_ms": round(float(latency.max()) * 1000.0, 3),
        "segment_count": len(segments),
        "segment_median_spread_ms": round(float(medians.max() - medians.min()), 3) if len(medians) > 1 else 0.0,
        "max_inter_segment_step_ms": round(max_inter_step, 3),
        "max_intra_segment_step_ms": round(max_intra_step, 3),
        "max_adjacent_step_ms": round(overall_max_step, 3),
        "step_detected": step_detected,
        "domain_ok": domain_ok,
        "segments": segments,
        "unity_dual_clock_stats": unity_dual_clock,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Receive-latency profiling and step detection (v3).")
    ap.add_argument("--csv", required=True, help="raw.csv file path")
    ap.add_argument("--out", default=None, help="write JSON report to output file")
    ap.add_argument("--max-gap", type=float, default=0.4,
                    help="split segments on source time gaps > this threshold (s) (default: 0.4)")
    ap.add_argument("--step-threshold-ms", type=float, default=5.0,
                    help="latency change threshold (ms) that flags a step (default: 5.0)")
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        print(f"Error: file not found: {args.csv}", file=sys.stderr)
        return 1

    r = analyse(args.csv, args.max_gap, args.step_threshold_ms)
    if "error" in r:
        print(f"Error: {r['error']}", file=sys.stderr)
        return 1

    print(f"=== Receive-latency profile (v3): {os.path.basename(args.csv)} ===")
    print(f"Unity rows: {r['unity_rows']} | Latency median: {r['latency_median_ms']:.3f} ms, "
          f"P95: {r['latency_p95_ms']:.3f} ms, Max: {r['latency_max_ms']:.3f} ms")

    print("\n%-4s %6s %9s %11s %9s %9s %12s %14s" %
          ("seg", "rows", "dur_s", "median_ms", "p95_ms", "std_ms", "maxgap_ms", "intra_step_ms"))
    for s in r["segments"]:
        print("%-4d %6d %9.2f %11.3f %9.3f %9.3f %12.3f %14.3f" % (
            s["index"] + 1, s["rows"], s["duration_s"], s["median_ms"],
            s["p95_ms"], s["std_ms"], s["max_gap_inside_ms"], s["max_intra_step_ms"]
        ))

    print(f"\nMax inter-segment step: {r['max_inter_segment_step_ms']:.3f} ms | "
          f"Max intra-segment step: {r['max_intra_segment_step_ms']:.3f} ms | "
          f"Max combined step: {r['max_adjacent_step_ms']:.3f} ms (threshold {args.step_threshold_ms:.1f} ms)")

    if r["unity_dual_clock_stats"]:
        udc = r["unity_dual_clock_stats"]
        print(f"Unity dual-clock (source_ts - geom_ts): median offset {udc['unity_clock_offset_median_s']}s, "
              f"spread {udc['unity_clock_offset_spread_ms']:.3f} ms, std {udc['unity_clock_offset_std_ms']:.3f} ms")

    if not r["domain_ok"]:
        print("\n[DOMAIN_ERROR] Source timestamps outside expected Unix epoch domain.")
        rc = 4
    elif r["step_detected"]:
        print(f"\n[STEP_DETECTED] Receive latency step ({r['max_adjacent_step_ms']:.3f} ms) exceeds threshold ({args.step_threshold_ms:.1f} ms).")
        rc = 3
    else:
        print("\n[NO_STEP] Receive latency remained stable within tolerance.")
        print("Note: This evaluates network transport/queue receive latency, not Unity Time.time clock alignment.")
        rc = 0

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2)
        print(f"Report written to: {args.out}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
