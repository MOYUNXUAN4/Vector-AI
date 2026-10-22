#!/usr/bin/env python3
"""receive_latency_profile_v5.py  (supersedes receive_latency_profile_v4.py)

v4 defect found by an independent adversarial review (2026-10-20):
  * `single_global_offset_sufficient` was set to `len(jumps) == 0`, i.e. "no
    >50 ms single-sample jump was seen, therefore one constant offset is
    enough". A gradual drift, or many jumps below the 50 ms detector, walks
    straight through that test. Fixture: 240 samples, +1 ms per row of
    source-minus-geometry drift -> spread 239 ms, and v4 still said the global
    offset was sufficient.
  * `row_index` was the index inside the filtered Unity array, not the physical
    CSV line, so a reported jump could not be opened in the file directly.

v5:
  * the sufficiency claim is a predeclared rule, and the default answer is
    UNKNOWN, not True:

        sufficient   coverage >= 0.90, >= 200 paired samples, no discrete jump,
                     detrended spread <= 20 ms, |drift| <= 20 ms
        insufficient any of those violated with enough evidence
        unknown      coverage or sample count too low to decide at all

    20 ms is one nominal 50 Hz sample interval: a global offset claim is only
    allowed when the pair varies by less than one sample. The numbers are module
    constants so they cannot be tuned after seeing a result;
  * `detrended_gradual_drift_ms` is reported separately from the discrete
    jumps, so slow drift is visible even when no jump fires;
  * every reported row carries `csv_line` (1-based physical line, header = 1)
    as well as the filtered array index.

Scope: this measures backend receive latency (transport + queue + receive epoch
delta) and the source/geometry pair. It does NOT establish Unity Time.time
alignment; a sufficient verdict only says a single offset is acceptable for
THIS pair over THIS span.
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

# Predeclared sufficiency rules (see module docstring). Do not tune per file.
GLOBAL_OFFSET_MAX_SPREAD_MS = 20.0
GLOBAL_OFFSET_MAX_DRIFT_MS = 20.0
GLOBAL_OFFSET_MIN_COVERAGE = 0.90
GLOBAL_OFFSET_MIN_SAMPLES = 200
DISCRETE_JUMP_S = 0.05


def load(path: str) -> Tuple[List[float], List[float], List[float], List[int]]:
    src, bck, geom, lines = [], [], [], []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        for lineno, r in enumerate(csv.DictReader(fh), start=2):
            if r.get("source") != "unity":
                continue
            try:
                s = float(r["source_timestamp"])
                b = float(r["backend_timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            src.append(s)
            bck.append(b)
            lines.append(lineno)
            g = r.get("geometry_source_timestamp") or ""
            try:
                geom.append(float(g) if g else float("nan"))
            except ValueError:
                geom.append(float("nan"))
    return src, bck, geom, lines


def detect_block_step(vals: List[float], min_block: int = MIN_BLOCK,
                      max_block: int = MAX_BLOCK,
                      stability_s: float = 0.005) -> Tuple[float, int, int]:
    """PERSISTENT level change, in ms. Returns (step_ms, index, block_size).

    Four consecutive blocks of size B are used:  left2 | left | right | later.
    A step is only accepted when BOTH sides are internally stable and the two
    sides differ, which is what rejects a sub-second burst.
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
    bounds = [i for i in range(1, len(src)) if src[i] - src[i - 1] > max_gap_s]
    starts = [0] + bounds
    ends = bounds + [len(src)]
    return list(zip(starts, ends))


def _gradual_drift_ms(detrended: List[float]) -> float:
    """Drift as the difference between the first and last decile medians."""
    n = len(detrended)
    if n < 20:
        return 0.0
    k = max(1, n // 10)
    return round((statistics.median(detrended[-k:]) - statistics.median(detrended[:k])) * 1000.0, 3)


def assess_global_offset(spread_ms: float, drift_ms: float, jumps: int,
                         paired: int, total: int) -> Dict[str, Any]:
    """Predeclared sufficiency rule. Default answer is UNKNOWN, never True."""
    coverage = (paired / total) if total else 0.0
    reasons: List[str] = []
    if paired < GLOBAL_OFFSET_MIN_SAMPLES:
        return {
            "verdict": "unknown",
            "single_global_offset_sufficient": None,
            "reason": "only %d paired samples (< %d)" % (paired, GLOBAL_OFFSET_MIN_SAMPLES),
            "coverage": round(coverage, 3),
            "rules": _rules(),
        }
    if coverage < GLOBAL_OFFSET_MIN_COVERAGE:
        return {
            "verdict": "unknown",
            "single_global_offset_sufficient": None,
            "reason": "geometry timestamp present on %.1f%% of rows (< %.0f%%)"
                      % (coverage * 100.0, GLOBAL_OFFSET_MIN_COVERAGE * 100.0),
            "coverage": round(coverage, 3),
            "rules": _rules(),
        }
    if jumps > 0:
        reasons.append("%d discrete jump(s) of > %.0f ms" % (jumps, DISCRETE_JUMP_S * 1000.0))
    if spread_ms > GLOBAL_OFFSET_MAX_SPREAD_MS:
        reasons.append("spread %.1f ms > %.1f ms" % (spread_ms, GLOBAL_OFFSET_MAX_SPREAD_MS))
    if abs(drift_ms) > GLOBAL_OFFSET_MAX_DRIFT_MS:
        reasons.append("gradual drift %.1f ms > %.1f ms" % (drift_ms, GLOBAL_OFFSET_MAX_DRIFT_MS))
    if reasons:
        return {
            "verdict": "insufficient",
            "single_global_offset_sufficient": False,
            "reason": "; ".join(reasons),
            "coverage": round(coverage, 3),
            "rules": _rules(),
        }
    return {
        "verdict": "sufficient",
        "single_global_offset_sufficient": True,
        "reason": "no jump, spread %.1f ms and drift %.1f ms within %.1f ms"
                  % (spread_ms, drift_ms, GLOBAL_OFFSET_MAX_SPREAD_MS),
        "coverage": round(coverage, 3),
        "rules": _rules(),
    }


def _rules() -> Dict[str, Any]:
    return {
        "max_spread_ms": GLOBAL_OFFSET_MAX_SPREAD_MS,
        "max_gradual_drift_ms": GLOBAL_OFFSET_MAX_DRIFT_MS,
        "min_coverage": GLOBAL_OFFSET_MIN_COVERAGE,
        "min_samples": GLOBAL_OFFSET_MIN_SAMPLES,
        "discrete_jump_threshold_ms": DISCRETE_JUMP_S * 1000.0,
        "note": "predeclared; 'sufficient' is only claimed when every rule passes",
    }


def analyse_arrays(src: List[float], bck: List[float], geom: List[float],
                   max_gap_s: float = 0.4, step_threshold_ms: float = 5.0,
                   name: str = "in-memory",
                   lines: Optional[List[int]] = None) -> Dict[str, Any]:
    n = len(src)
    if n < 10:
        return {"error": "too few unity rows (<10)", "path": name}
    lines = lines or [0] * n

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
        med = statistics.median(seg)
        spike = (max(seg) - med) * 1000.0
        max_intra_peak = max(max_intra_peak, spike)
        gaps = [src[j + 1] - src[j] for j in range(a, b - 1)]
        segments.append({
            "index": idx,
            "rows": b - a,
            "csv_line_first": lines[a],
            "csv_line_last": lines[b - 1],
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
        spread = (max(detrended) - min(detrended)) * 1000.0
        drift = _gradual_drift_ms(detrended)

        jumps = []
        for k in range(1, len(diff)):
            delta = diff[k] - diff[k - 1]
            if abs(delta) <= DISCRETE_JUMP_S:
                continue
            i = paired_idx[k]
            prev_i = paired_idx[k - 1]
            gap = src[i] - src[prev_i] if i != prev_i else 0.0
            jumps.append({
                "row_index": i,
                "csv_line": lines[i],
                "delta_ms": round(delta * 1000.0, 1),
                "source_gap_ms": round(gap * 1000.0, 1),
                "coincides_with_source_gap": bool(gap > 0.3),
            })

        gate = assess_global_offset(round(spread, 3), drift, len(jumps), len(paired_idx), n)
        dual = {
            "geometry_clock_domain": "relative",
            "origin_offset_s": round(origin, 3),
            "origin_offset_note": "arbitrary origin distance between a Unix-epoch clock and a relative clock; not an alignment error",
            "paired_samples": len(paired_idx),
            "total_samples": n,
            "detrended_spread_ms": round(spread, 3),
            "detrended_std_ms": round(statistics.pstdev(detrended) * 1000.0, 3),
            "detrended_gradual_drift_ms": drift,
            "detrended_persistent_step_ms": step,
            "detrended_step_index": at,
            "step_block": B,
            "discrete_jump_count": len(jumps),
            "discrete_jumps": jumps,
            "cumulative_jump_ms": round(sum(j["delta_ms"] for j in jumps), 1),
            "global_offset_verdict": gate["verdict"],
            "global_offset_reason": gate["reason"],
            "global_offset_coverage": gate["coverage"],
            "global_offset_rules": gate["rules"],
            "single_global_offset_sufficient": gate["single_global_offset_sufficient"],
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
        "scope": "backend receive latency + source/geometry pair; not Unity Time.time alignment",
    }


def analyse(path: str, max_gap_s: float = 0.4, step_threshold_ms: float = 5.0) -> Dict[str, Any]:
    src, bck, geom, lines = load(path)
    return analyse_arrays(src, bck, geom, max_gap_s, step_threshold_ms, path, lines)


def self_test() -> int:
    base = 1_700_000_000.0
    src = [base + i * 0.02 for i in range(200)]
    results = []

    def run(label, bck, geom, expect, src_override=None):
        use = src_override if src_override is not None else src
        r = analyse_arrays(use, bck, geom, name=label)
        dual = r.get("unity_dual_clock_stats", {})
        verdict = dual.get("global_offset_verdict", "not-assessed")
        ok = (verdict == expect) if expect is not None else (not dual)
        results.append(ok)
        print("[%s] %-38s global_offset=%-13s expect=%s"
              % ("PASS" if ok else "FAIL", label, verdict, expect or "not-assessed"))
        return r

    step_lat = [0.005] * 100 + [0.105] * 100
    r = run("100ms persistent latency step", [s + l for s, l in zip(src, step_lat)],
            [float("nan")] * 200, None)
    ok_step = r["step_detected"] and r["max_adjacent_step_ms"] > 90
    print("[%s] 100 ms persistent step detected (%.3f ms)"
          % ("PASS" if ok_step else "FAIL", r["max_adjacent_step_ms"]))
    results.append(ok_step)

    burst_lat = [0.005] * 200
    for i in range(90, 120):
        burst_lat[i] = 0.155
    r = run("600ms burst (not a step)", [s + l for s, l in zip(src, burst_lat)],
            [float("nan")] * 200, None)
    ok_burst = not r["step_detected"]
    print("[%s] burst NOT a step (spike %.3f ms)" % ("PASS" if ok_burst else "FAIL",
                                                     r["max_within_segment_spike_ms"]))
    results.append(ok_burst)

    flat_lat = [0.005 + 0.001 * ((i % 7) - 3) for i in range(200)]
    run("flat latency, no geometry", [s + l for s, l in zip(src, flat_lat)],
        [float("nan")] * 200, None)

    geom_flat = [i * 0.02 for i in range(200)]
    run("geometry constant offset", [s + 0.005 for s in src], geom_flat, "sufficient")

    geom_jump = list(geom_flat)
    for i in range(120, 200):
        geom_jump[i] -= 0.150
    run("geometry single 150ms jump", [s + 0.005 for s in src], geom_jump, "insufficient")

    src_long = [base + i * 0.02 for i in range(240)]
    geom_drift = [i * 0.02 - i * 0.001 for i in range(240)]
    r = run("geometry 1ms/row drift (239ms)", [t + 0.005 for t in src_long],
            geom_drift, "insufficient", src_override=src_long)
    d = r["unity_dual_clock_stats"]
    print("      spread %.1f ms, gradual drift %.1f ms, jumps %d"
          % (d["detrended_spread_ms"], d["detrended_gradual_drift_ms"], d["discrete_jump_count"]))
    ok_drift = abs(d["detrended_spread_ms"] - 239.0) < 5 and d["global_offset_verdict"] == "insufficient"
    print("[%s] gradual drift is reported and blocks the offset claim" % ("PASS" if ok_drift else "FAIL"))
    results.append(ok_drift)

    geom_short = [i * 0.02 for i in range(60)]
    r = analyse_arrays(src[:60], [t + 0.005 for t in src[:60]], geom_short, name="short")
    d = r["unity_dual_clock_stats"]
    ok_short = d["global_offset_verdict"] == "unknown"
    print("[%s] 60 paired samples -> unknown (not sufficient)" % ("PASS" if ok_short else "FAIL"))
    results.append(ok_short)

    return 0 if all(results) else 6


def main() -> int:
    ap = argparse.ArgumentParser(description="Receive-latency profile with predeclared "
                                             "global-offset sufficiency rules (v5).")
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

    print("=== Receive-latency profile (v5): %s ===" % os.path.basename(args.csv))
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
        print("\nsource vs geometry clock: origin_offset %.3f s (arbitrary), "
              "paired %d/%d, spread %.3f ms, gradual drift %.3f ms"
              % (dual["origin_offset_s"], dual["paired_samples"], dual["total_samples"],
                 dual["detrended_spread_ms"], dual["detrended_gradual_drift_ms"]))
        print("  origin_offset is the distance between a Unix-epoch clock and a relative run")
        print("  clock, NOT an alignment error. Only detrended variation is interpretable.")
        verdict = dual["global_offset_verdict"]
        if verdict == "sufficient":
            print("\n  [SUFFICIENT] one global offset is acceptable for this pair over this span:")
            print("    %s" % dual["global_offset_reason"])
        elif verdict == "insufficient":
            print("\n  [INSUFFICIENT] a single global offset is NOT sufficient:")
            print("    %s" % dual["global_offset_reason"])
        else:
            print("\n  [UNKNOWN] not enough paired evidence to decide: %s"
                  % dual["global_offset_reason"])
        print("    rules: spread<=%.0f ms, |drift|<=%.0f ms, coverage>=%.0f%%, paired>=%d"
              % (GLOBAL_OFFSET_MAX_SPREAD_MS, GLOBAL_OFFSET_MAX_DRIFT_MS,
                 GLOBAL_OFFSET_MIN_COVERAGE * 100, GLOBAL_OFFSET_MIN_SAMPLES))
        jumps = dual.get("discrete_jumps", [])
        if jumps:
            print("\n  %d discrete jump(s) in (source - geometry), cumulative %.1f ms:"
                  % (len(jumps), dual["cumulative_jump_ms"]))
            for j in jumps[:20]:
                print("    csv line %-6d array idx %-6d delta %+8.1f ms   source gap %7.1f ms   %s"
                      % (j["csv_line"], j["row_index"], j["delta_ms"], j["source_gap_ms"],
                         "on long frame" if j["coincides_with_source_gap"] else "no gap"))
            if len(jumps) > 20:
                print("    ... %d more" % (len(jumps) - 20))

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
