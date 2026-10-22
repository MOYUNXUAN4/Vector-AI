#!/usr/bin/env python3
"""wii_cop_preflight_v4.py  (supersedes wii_cop_preflight_v3.py)

v3 defect found by re-running it on real telemetry: it read the flag columns as
`control_valid`, `board_loaded`, `center_applied`, but the CSV actually names
them `wii_control_valid`, `wii_board_loaded`, `wii_center_applied`. Every lookup
returned None, every flag defaulted to True, so the advertised "explicit flag
verification" never ran. On session_20261020_101929 there are 476 rows with
`wii_board_loaded=False`; v3 reported all 5685 rows as loaded.

v4:
  * reads the real column names (with the short names as a fallback);
  * records which flag columns were actually present, so "checked" is auditable;
  * enforces wii_control_age_seconds <= --max-age-s inside the window;
  * requires wii_center_generation and wii_controller_instance_id to be constant
    across the window (a re-tare or controller swap mid-window invalidates it);
  * never drops rows before indexing, so a gap cannot be bridged;
  * separates INSUFFICIENT_LOAD from LOADED_NOT_STATIONARY from NO_ELIGIBLE_WINDOW.

Scope: this is a DESCRIPTIVE check on recorded telemetry. A loaded, still window
inside ordinary gameplay is not proof that a protocol calibration interval
occurred. It reports what the data shows, not that the operator did anything.

Exit codes
  0 OK                     eligible sustained load, stationary, |CoP| within tolerance
  2 INSUFFICIENT_LOAD      board never carried --min-load-kg over a full window
  3 SKEWED                 eligible stationary window, baseline outside tolerance
  4 LOADED_NOT_STATIONARY  eligible sustained load, but CoP variance too large
  5 NO_ELIGIBLE_WINDOW     load exists but no window passes flag/age/gap checks
  1 input error
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

W = "wii_"


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _flag(row: dict, names: Tuple[str, ...]) -> Optional[bool]:
    """Return the first present boolean column, or None when the column is absent."""
    for name in names:
        v = row.get(name)
        if v is None:
            continue
        s = str(v).strip()
        if s == "":
            continue
        return _truthy(s)
    return None


def _num(row: dict, key: str) -> Optional[float]:
    v = row.get(key)
    if v is None or str(v).strip() == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def load_wii(path: str) -> Dict[str, Any]:
    cols = {
        "ts": [], "w": [], "x": [], "z": [],
        "valid": [], "loaded": [], "centered": [], "age": [],
        "gen": [], "instance": [], "seq": [],
    }
    present = {"control_valid": False, "board_loaded": False, "center_applied": False}

    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("source") != "wii":
                continue
            w = _num(row, "total_weight")
            x = _num(row, "cop_x")
            z = _num(row, "cop_z")
            if w is None or x is None or z is None:
                continue

            ts = _num(row, "backend_timestamp")
            if ts is None:
                ts = _num(row, "source_timestamp")

            v = _flag(row, (W + "control_valid", "control_valid"))
            l = _flag(row, (W + "board_loaded", "board_loaded"))
            c = _flag(row, (W + "center_applied", "center_applied"))
            for key, val in (("control_valid", v), ("board_loaded", l), ("center_applied", c)):
                if val is not None:
                    present[key] = True

            cols["ts"].append(ts)
            cols["w"].append(w)
            cols["x"].append(x)
            cols["z"].append(z)
            cols["valid"].append(True if v is None else v)
            cols["loaded"].append(True if l is None else l)
            cols["centered"].append(True if c is None else c)
            cols["age"].append(_num(row, W + "control_age_seconds"))
            cols["gen"].append((row.get(W + "center_generation") or "").strip())
            cols["instance"].append((row.get(W + "controller_instance_id") or "").strip())
            seq = row.get(W + "control_sequence")
            try:
                cols["seq"].append(int(float(seq)) if seq not in (None, "") else None)
            except ValueError:
                cols["seq"].append(None)

    cols["flags_present"] = present
    return cols


def _median(vals: List[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def audit(path: str, window: int = 50, min_load: float = 20.0, still_cm: float = 1.0,
          tol_cm: float = 1.5, max_gap_s: float = 0.15, max_age_s: float = 0.25) -> Dict[str, Any]:
    d = load_wii(path)
    n = len(d["w"])
    out: Dict[str, Any] = {
        "path": path,
        "wii_rows": n,
        "evidence_level": "descriptive",
        "flag_columns_present": d["flags_present"],
        "required_window": window,
        "note": ("Flags that are absent from the CSV are treated as unknown, not as pass. "
                 "A still loaded window is not proof of a protocol calibration interval."),
    }
    if n == 0:
        out.update(verdict="INSUFFICIENT_LOAD", reason="no usable wii rows")
        return out

    out.update(
        weight_median_kg=round(_median(d["w"]), 2),
        weight_max_kg=round(max(d["w"]), 2),
        weight_min_kg=round(min(d["w"]), 2),
    )
    if n < window:
        out.update(verdict="INSUFFICIENT_LOAD", reason="fewer than %d wii samples (%d)" % (window, n))
        return out

    # Per-row eligibility. Rows are never removed before indexing, so a dropped
    # row leaves a hole that the contiguity test below will catch.
    eligible: List[bool] = []
    reasons = {"flag_false": 0, "stale": 0, "no_timestamp": 0}
    for i in range(n):
        ok = True
        if not (d["valid"][i] and d["loaded"][i] and d["centered"][i]):
            ok = False
            reasons["flag_false"] += 1
        age = d["age"][i]
        if age is not None and age > max_age_s:
            ok = False
            reasons["stale"] += 1
        if d["ts"][i] is None:
            ok = False
            reasons["no_timestamp"] += 1
        eligible.append(ok)

    out["ineligible_rows"] = reasons
    out["eligible_rows"] = sum(eligible)

    def gap_ok(i: int) -> bool:
        if i == 0:
            return True
        a, b = d["ts"][i - 1], d["ts"][i]
        if a is None or b is None:
            return False
        return (b - a) <= max_gap_s or (b - a) <= 0

    loaded_windows = 0
    eligible_windows = 0
    best_std = float("inf")
    best_ineligible_reason = ""

    start_found = -1
    for i in range(0, n - window + 1):
        seg_w = d["w"][i:i + window]
        if min(seg_w) < min_load:
            continue
        loaded_windows += 1

        if not all(eligible[i:i + window]):
            best_ineligible_reason = best_ineligible_reason or "flags_or_age"
            continue
        if not all(gap_ok(j) for j in range(i + 1, i + window)):
            best_ineligible_reason = best_ineligible_reason or "time_gap"
            continue
        if len(set(d["gen"][i:i + window])) > 1 or len(set(d["instance"][i:i + window])) > 1:
            best_ineligible_reason = best_ineligible_reason or "generation_or_instance_changed"
            continue

        eligible_windows += 1
        sx = d["x"][i:i + window]
        sz = d["z"][i:i + window]
        m = max(statistics.pstdev(sx), statistics.pstdev(sz))
        if m < best_std:
            best_std = m
        if m <= still_cm:
            start_found = i
            break

    out["loaded_windows"] = loaded_windows
    out["eligible_windows"] = eligible_windows

    if loaded_windows == 0:
        out.update(verdict="INSUFFICIENT_LOAD",
                   reason="no %d-sample window where every sample carried >= %.1f kg" % (window, min_load))
        return out

    if start_found < 0:
        if eligible_windows == 0:
            out.update(verdict="NO_ELIGIBLE_WINDOW",
                       reason="load present but no window passed evidence checks (%s)" % (best_ineligible_reason or "unknown"))
        else:
            out.update(verdict="LOADED_NOT_STATIONARY",
                       reason="sustained load in %d eligible windows, smallest CoP std %.3f cm > %.2f cm"
                              % (eligible_windows, best_std, still_cm))
        return out

    i = start_found
    mx = statistics.fmean(d["x"][i:i + window])
    mz = statistics.fmean(d["z"][i:i + window])
    radial = (mx * mx + mz * mz) ** 0.5
    out.update(
        window_start_index=i,
        window_start_ts=d["ts"][i],
        window_duration_s=round(d["ts"][i + window - 1] - d["ts"][i], 3),
        window_weight_kg=round(statistics.fmean(d["w"][i:i + window]), 2),
        cop_x_cm=round(mx, 2), cop_z_cm=round(mz, 2),
        cop_std_x_cm=round(statistics.pstdev(d["x"][i:i + window]), 3),
        cop_std_z_cm=round(statistics.pstdev(d["z"][i:i + window]), 3),
        radial_cm=round(radial, 2),
        center_generation=d["gen"][i],
        controller_instance_id=d["instance"][i],
    )
    if radial > tol_cm:
        out.update(verdict="SKEWED",
                   reason="baseline radial offset %.2f cm exceeds %.2f cm" % (radial, tol_cm))
    else:
        out.update(verdict="OK", reason="eligible loaded still window within tolerance")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Balance-board baseline pre-flight (v4, flag-aware, descriptive).")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--window", type=int, default=50)
    ap.add_argument("--min-load-kg", type=float, default=20.0)
    ap.add_argument("--still-cm", type=float, default=1.0)
    ap.add_argument("--tolerance-cm", type=float, default=1.5)
    ap.add_argument("--max-gap", type=float, default=0.15)
    ap.add_argument("--max-age-s", type=float, default=0.25)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.csv):
        print("missing: %s" % args.csv, file=sys.stderr)
        return 1

    r = audit(args.csv, args.window, args.min_load_kg, args.still_cm, args.tolerance_cm,
              args.max_gap, args.max_age_s)

    print("=== Wii baseline pre-flight (v4): %s ===" % os.path.basename(args.csv))
    print("wii rows %d | weight median %.2f kg | max %.2f kg | eligible rows %d"
          % (r["wii_rows"], r.get("weight_median_kg", 0.0), r.get("weight_max_kg", 0.0), r.get("eligible_rows", 0)))
    print("flag columns present: %s" % json.dumps(r["flag_columns_present"], sort_keys=True))
    if r.get("ineligible_rows"):
        print("ineligible rows: %s" % json.dumps(r["ineligible_rows"], sort_keys=True))

    verdict = r["verdict"]
    if verdict == "INSUFFICIENT_LOAD":
        print("\n[INSUFFICIENT_LOAD] %s" % r.get("reason", ""))
        rc = 2
    elif verdict == "NO_ELIGIBLE_WINDOW":
        print("\n[NO_ELIGIBLE_WINDOW] %s" % r.get("reason", ""))
        print("  Load was present but the evidence needed for a baseline was not.")
        rc = 5
    elif verdict == "LOADED_NOT_STATIONARY":
        print("\n[LOADED_NOT_STATIONARY] %s" % r.get("reason", ""))
        rc = 4
    elif verdict == "SKEWED":
        print("\n[SKEWED] window at sample %d, load %.1f kg" % (r["window_start_index"], r["window_weight_kg"]))
        print("  CoP X=%+.2f cm Z=%+.2f cm radial=%.2f cm (tolerance %.1f cm)"
              % (r["cop_x_cm"], r["cop_z_cm"], r["radial_cm"], args.tolerance_cm))
        rc = 3
    else:
        print("\n[OK] window at sample %d, load %.1f kg, CoP X=%+.2f cm Z=%+.2f cm (std %.2f / %.2f cm)"
              % (r["window_start_index"], r["window_weight_kg"], r["cop_x_cm"], r["cop_z_cm"],
                 r["cop_std_x_cm"], r["cop_std_z_cm"]))
        rc = 0

    print("\nNote: descriptive only. A still loaded window in gameplay is not proof that a")
    print("      protocol calibration interval was executed.")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2)
        print("written: %s" % args.out)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
