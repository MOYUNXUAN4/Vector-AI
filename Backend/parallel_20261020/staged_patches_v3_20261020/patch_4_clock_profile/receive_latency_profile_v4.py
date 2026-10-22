#!/usr/bin/env python3
"""receive_latency_profile_v4.py  (supersedes receive_latency_profile_v3.py)

v3 defects found by re-running it on session_20261019_161529:
  * its in-stream detector compared two adjacent 25-sample medians. The known
    ~500 ms stall produces a burst of high-latency packets, which moved a
    25-sample median by 139 ms, so v3 reported STEP_DETECTED on a session that
    has no persistent latency step (the segment medians agree to 0.317 ms).
    A transient burst is not a step.
  * its "Unity dual-clock" block printed `source_ts - geom_ts` = 1792397728 s
    and called that an offset. That is the arbitrary origin distance between a
    Unix-epoch clock and a relative run clock, not an alignment error.

v4:
  * a step must be a PERSISTENT level change: block medians of block size B,
    with B = clamp(n/4, 10, 100). A 0.5 s burst cannot move a 2 s block median,
    while a real level change moves every block after the boundary;
  * the same block test runs on source/geometry detrended difference;
  * the absolute source-vs-geometry distance is reported as `origin_offset_s`
    and explicitly labelled arbitrary, never as an alignment error;
  * --self-test runs the 100 ms injection and the 500 ms burst case.

Scope: this measures backend receive latency (transport + queue + receive
epoch delta). It does NOT measure Unity Time.time alignment, and a NO_STEP
result here says nothing about epoch<->Time.time consistency.

Exit codes
  0  NO_STEP
  3  STEP_DETECTED
  4  DOMAIN_ERROR
  1  input error
  6  SELF_TEST_FAILED
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

MIN_BLOCK = 10
MAX_BLOCK = 100


def load(path: str) -> Tuple[List[float], List[float], List[float]]:
    src, bck, geom = [], [], []
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
                geom.append(float(g) if g else float("nan"))
            except ValueError:
                geom.append(float("nan"))
    return src, bck, geom


def detect_block_step(vals: List[float], min_block: int = MIN_BLOCK,
                      max_block: int = MAX_BLOCK,
                      stability_s: float = 0.005) -> Tuple[float, int, int]:
    """PERSISTENT level change, in ms. Returns (step_ms, index, block_size).

    Four consecutive blocks of size B are used:

        left2 | left | right | later

    A step is only accepted when BOTH sides are internally stable
    (|left-left2| <= stability_s and |right-later| <= stability_s) and the two
    sides differ. The stability requirement is what rejects a burst: at the
    rising edge `right` is elevated but `later` is back to baseline, and at the
    falling edge `left` is elevated but `left2` is not. Neither edge is stable
    on both sides, so neither scores.

    B = n/6 so the four blocks always fit.
    """
    n = len(vals)
    if n < 5 * min_block:
        return 0.0, -1, 0
    B = max(min_block, min(max_block, n // 6))
    stride = max(1, B // 4)
    best, best_idx = 0.0, -1
    for i in range(2 * B, n - 2 * B + 1, stride):
        left2 = statistics.median(vals[i - 2 * B:i - B])
        left = statistics.median(vals[i - B:i])
        right = statistics.median(vals[i:i + B])
        later = statistics.median(vals[i + B:i + 2 * B])
        if abs(left - left2) > stability_s or abs(right - later) > stability_s:
            continue
        d = abs(right - left) * 1000.0
        if d > best:
            best, best_idx = d, i
    return round(best, 3), best_idx, B


def _segments(src: List[float], max_gap_s: float) -> List[Tuple[int, int]]:
    starts, bounds = [0], []
    for i in range(1, len(src)):
        if src[i] - src[i - 1] > max_gap_s:
            bounds.append(i)
    starts += bounds
    ends = bounds + [len(src)]
    return list(zip(starts, ends))


def analyse_arrays(src: List[float], bck: List[float], geom: List[float],
                   max_gap_s: float = 0.4, step_threshold_ms: float = 5.0,
                   name: str = "in-memory") -> Dict[str, Any]:
    n = len(src)
    if n < 10:
        return {"error": "too few unity rows (<10)", "path": name}

    latency = [(bck[i] - src[i]) for i in range(n)]
    finite_geom = [g for g in geom if g == g]
    domain_ok = bool(
        statistics.fmean(src) > 1e8
        and (not finite_geom or max(finite_geom) < 1e6)
    )

    segments = []
    max_intra_peak = 0.0
    max_intra_step = 0.0
    intra_block = 0
    for idx, (a, b) in enumerate(_segments(src, max_gap_s)):
        seg = latency[a:b]
        step, at, B = detect_block_step(seg)
        if step > max_intra_step:
            max_intra_step, intra_block = step, B
        # `spike` is descriptive only: max excursion above the segment median.
        med = statistics.median(seg)
        spike = (max(seg) - med) * 1000.0
        max_intra_peak = max(max_intra_peak, spike)
        gaps = [src[j + 1] - src[j] for j in range(a, b - 1)]
        segments.append({
            "index": idx,
            "rows": b - a,
            "duration_s": round(src[b - 1] - src[a], 3),
            "median_ms": round(med * 1000.0, 3),
            "p95_ms": round(sorted(seg)[max(0, int(0.95 * (len(seg) - 1)))] * 1000.0, 3),
            "std_ms": round(statistics.pstdev(seg) * 1000.0, 3),
            "max_single_packet_ms": round(max(seg) * 1000.0, 3),
            "spike_above_median_ms": round(spike, 3),
            "max_gap_inside_ms": round(max(gaps) * 1000.0, 3) if gaps else 0.0,
            "persistent_step_ms": step,
            "persistent_step_index": at,
            "step_block": B,
        })

    medians = [s["median_ms"] for s in segments]
    inter = [abs(medians[i] - medians[i - 1]) for i in range(1, len(medians))]
    max_inter = max(inter) if inter else 0.0
    overall = max(max_inter, max_intra_step)

    dual: Dict[str, Any] = {}
    paired_idx = [i for i in range(n) if geom[i] == geom[i]]
    if len(paired_idx) >= 2 * MIN_BLOCK:
        diff = [src[i] - geom[i] for i in paired_idx]
        origin = statistics.median(diff)
        detrended = [d - origin for d in diff]
        step, at, B = detect_block_step(detrended)

        # Discrete jumps: a staircase, not drift. On P01 16:15 these land
        # exactly on the 484-511 ms long frames and each adds 139-175 ms.
        jumps = []
        for k in range(1, len(diff)):
            delta = diff[k] - diff[k - 1]
            if abs(delta) <= 0.05:
                continue
            i = paired_idx[k]
            prev_i = paired_idx[k - 1]
            gap = src[i] - src[prev_i] if i != prev_i else 0.0
            jumps.append({
                "row_index": i,
                "delta_ms": round(delta * 1000.0, 1),
                "source_gap_ms": round(gap * 1000.0, 1),
                "coincides_with_source_gap": bool(gap > 0.3),
            })

        dual = {
            "geometry_clock_domain": "relative",
            "origin_offset_s": round(origin, 3),
            "origin_offset_note": "arbitrary origin distance between a Unix-epoch clock and a relative clock; not an alignment error",
            "detrended_spread_ms": round((max(detrended) - min(detrended)) * 1000.0, 3),
            "detrended_std_ms": round(statistics.pstdev(detrended) * 1000.0, 3),
            "detrended_persistent_step_ms": step,
            "detrended_step_index": at,
            "step_block": B,
            "discrete_jumps": jumps,
            "cumulative_drift_ms": round(sum(j["delta_ms"] for j in jumps), 1),
            "single_global_offset_sufficient": len(jumps) == 0,
        }

    return {
        "path": name,
        "unity_rows": n,
        "latency_median_ms": round(statistics.median(latency) * 1000.0, 3),
        "latency_max_ms": round(max(latency) * 1000.0, 3),
        "segment_count": len(segments),
        "segment_median_spread_ms": round(max(medians) - min(medians), 3) if len(medians) > 1 else 0.0,
        "max_inter_segment_step_ms": round(max_inter, 3),
        "max_within_segment_persistent_step_ms": round(max_intra_step, 3),
        "max_within_segment_spike_ms": round(max_intra_peak, 3),
        "step_block": intra_block,
        "max_adjacent_step_ms": round(overall, 3),
        "step_detected": bool(overall > step_threshold_ms),
        "domain_ok": domain_ok,
        "segments": segments,
        "unity_dual_clock_stats": dual,
        "scope": "backend receive latency only; not Unity Time.time alignment",
    }


def analyse(path: str, max_gap_s: float = 0.4, step_threshold_ms: float = 5.0) -> Dict[str, Any]:
    src, bck, geom = load(path)
    return analyse_arrays(src, bck, geom, max_gap_s, step_threshold_ms, path)


def self_test() -> int:
    base = 1_700_000_000.0
    src = [base + i * 0.02 for i in range(200)]

    step_lat = [0.005] * 100 + [0.105] * 100
    r_step = analyse_arrays(src, [s + l for s, l in zip(src, step_lat)], [float("nan")] * 200,
                            name="synthetic_100ms_step")
    ok_step = r_step["step_detected"] and r_step["max_adjacent_step_ms"] > 90

    burst_lat = [0.005] * 200
    for i in range(90, 120):          # 0.6 s burst of +150 ms, like a stall
        burst_lat[i] = 0.155
    r_burst = analyse_arrays(src, [s + l for s, l in zip(src, burst_lat)], [float("nan")] * 200,
                             name="synthetic_600ms_burst")
    ok_burst = not r_burst["step_detected"]

    flat_lat = [0.005 + 0.001 * ((i % 7) - 3) for i in range(200)]
    r_flat = analyse_arrays(src, [s + l for s, l in zip(src, flat_lat)], [float("nan")] * 200,
                            name="synthetic_flat")
    ok_flat = not r_flat["step_detected"]

    print("[%s] 100 ms persistent step detected: %.3f ms"
          % ("PASS" if ok_step else "FAIL", r_step["max_adjacent_step_ms"]))
    print("[%s] 600 ms burst NOT reported as step: %.3f ms (spike %.3f ms)"
          % ("PASS" if ok_burst else "FAIL", r_burst["max_adjacent_step_ms"],
             r_burst["max_within_segment_spike_ms"]))
    print("[%s] flat series reports no step: %.3f ms"
          % ("PASS" if ok_flat else "FAIL", r_flat["max_adjacent_step_ms"]))
    return 0 if (ok_step and ok_burst and ok_flat) else 6


def main() -> int:
    ap = argparse.ArgumentParser(description="Receive-latency profile with persistent-step detection (v4).")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-gap", type=float, default=0.4)
    ap.add_argument("--step-threshold-ms", type=float, default=5.0)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.csv:
        print("--csv is required unless --self-test", file=sys.stderr)
        return 1
    if not os.path.isfile(args.csv):
        print("missing: %s" % args.csv, file=sys.stderr)
        return 1

    r = analyse(args.csv, args.max_gap, args.step_threshold_ms)
    if "error" in r:
        print(r["error"], file=sys.stderr)
        return 1

    print("=== Receive-latency profile (v4): %s ===" % os.path.basename(args.csv))
    print("unity rows %d | latency median %.3f ms  max %.3f ms | scope: %s"
          % (r["unity_rows"], r["latency_median_ms"], r["latency_max_ms"], r["scope"]))
    print("\n%-4s %6s %9s %11s %9s %12s %14s %13s"
          % ("seg", "rows", "dur_s", "median_ms", "p95_ms", "spike_ms", "persist_step", "block"))
    for s in r["segments"]:
        print("%-4d %6d %9.2f %11.3f %9.3f %12.3f %14.3f %13d"
              % (s["index"] + 1, s["rows"], s["duration_s"], s["median_ms"], s["p95_ms"],
                 s["spike_above_median_ms"], s["persistent_step_ms"], s["step_block"]))

    print("\ninter-segment %.3f ms | within-segment persistent %.3f ms | within-segment spike %.3f ms"
          % (r["max_inter_segment_step_ms"], r["max_within_segment_persistent_step_ms"],
             r["max_within_segment_spike_ms"]))
    print("combined step %.3f ms (threshold %.1f ms, block %d)"
          % (r["max_adjacent_step_ms"], args.step_threshold_ms, r["step_block"]))

    dual = r["unity_dual_clock_stats"]
    if dual:
        print("\nsource vs geometry clock: origin_offset %.3f s (arbitrary), detrended spread %.3f ms, "
              "detrended persistent step %.3f ms"
              % (dual["origin_offset_s"], dual["detrended_spread_ms"], dual["detrended_persistent_step_ms"]))
        print("  origin_offset is the distance between a Unix-epoch clock and a relative run clock,")
        print("  NOT an alignment error. Only the detrended variation is interpretable.")
        jumps = dual.get("discrete_jumps", [])
        if jumps:
            print("\n  %d discrete jump(s) in (source - geometry), cumulative drift %.1f ms:"
                  % (len(jumps), dual["cumulative_drift_ms"]))
            for j in jumps[:20]:
                print("    row %-6d delta %+8.1f ms   source gap %7.1f ms   %s"
                      % (j["row_index"], j["delta_ms"], j["source_gap_ms"],
                         "on long frame" if j["coincides_with_source_gap"] else "no gap"))
            if len(jumps) > 20:
                print("    ... %d more" % (len(jumps) - 20))
            print("  A single global offset is NOT sufficient for source/geometry alignment.")
        else:
            print("  No discrete jumps: a single global offset is sufficient for this pair.")

    if not r["domain_ok"]:
        print("\n[DOMAIN_ERROR] source_timestamp and geometry_source_timestamp appear to be crossed.")
        rc = 4
    elif r["step_detected"]:
        print("\n[STEP_DETECTED] persistent receive-latency level change of %.3f ms." % r["max_adjacent_step_ms"])
        print("  This is a transport/queue level change, not a Unity clock-alignment result.")
        rc = 3
    else:
        print("\n[NO_STEP] no persistent receive-latency level change above %.1f ms." % args.step_threshold_ms)
        print("  Transient spikes up to %.3f ms were seen but are not a level change." % r["max_within_segment_spike_ms"])
        print("  This says nothing about Unity Time.time / epoch alignment.")
        rc = 0

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2)
        print("written: %s" % args.out)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
