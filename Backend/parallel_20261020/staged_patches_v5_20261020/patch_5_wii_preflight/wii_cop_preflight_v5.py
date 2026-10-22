#!/usr/bin/env python3
"""wii_cop_preflight_v5.py  (supersedes wii_cop_preflight_v4.py)

v4 defects found by an independent adversarial review (2026-10-20):
  * a missing flag column was coerced to True (`True if v is None else v`), so a
    file with no board flags at all returned OK while the payload simultaneously
    reported `flag_columns_present: {..: False}`. Absence of evidence was scored
    as evidence of absence of a problem.
  * a missing `wii_control_age_seconds` was accepted; empty
    `wii_center_generation` / `wii_controller_instance_id` strings formed a
    constant set and therefore satisfied the "identity unchanged" test.
  * `gap_ok` accepted `b - a <= 0`, so a file with decreasing timestamps passed
    and reported a NEGATIVE window duration.
  * rows with a missing weight/CoP were dropped before indexing, which silently
    closed a hole the contiguity test was supposed to catch.

v5:
  * all required columns must exist, and every flag must be explicitly true.
    A missing column yields UNKNOWN_EVIDENCE, never OK;
  * age must be present, finite, non-negative and <= --max-age-s;
  * generation and controller identity must be present and non-empty;
  * source time must be strictly increasing with 0 < dt <= --max-gap. A
    reversal, a duplicate timestamp or a gap is a barrier;
  * invalid rows are KEPT at their index and marked ineligible, so a hole can
    never be bridged;
  * every window reports `csv_line` provenance (1-based physical line).

Scope: DESCRIPTIVE check on recorded telemetry. A loaded, still window inside
ordinary gameplay is not proof that a protocol calibration interval occurred.

Exit codes
  0 OK
  2 INSUFFICIENT_LOAD
  3 SKEWED
  4 LOADED_NOT_STATIONARY
  5 NO_ELIGIBLE_WINDOW
  6 UNKNOWN_EVIDENCE   required columns absent; nothing can be verified
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

FLAG_COLUMNS = (W + "control_valid", W + "board_loaded", W + "center_applied")
VALUE_COLUMNS = ("total_weight", "cop_x", "cop_z")
IDENTITY_COLUMNS = (W + "center_generation", W + "controller_instance_id")
AGE_COLUMN = W + "control_age_seconds"
TIME_COLUMNS = ("backend_timestamp", W + "timestamp", "source_timestamp")

REQUIRED_COLUMNS = VALUE_COLUMNS + FLAG_COLUMNS + (AGE_COLUMN,) + IDENTITY_COLUMNS


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _flag(row: dict, name: str) -> Optional[bool]:
    """True/False when the column is present and non-empty, else None (unknown)."""
    v = row.get(name)
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    return _truthy(s)


def _num(row: dict, key: str) -> Optional[float]:
    v = row.get(key)
    if v is None or str(v).strip() == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _time(row: dict) -> Tuple[Optional[float], str]:
    for key in TIME_COLUMNS:
        x = _num(row, key)
        if x is not None:
            return x, key
    return None, ""


def load_wii(path: str) -> Dict[str, Any]:
    cols: Dict[str, Any] = {
        "ts": [], "w": [], "x": [], "z": [],
        "valid": [], "loaded": [], "centered": [],
        "age": [], "gen": [], "instance": [],
        "csv_line": [], "time_column": [],
    }
    header: List[str] = []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        for lineno, row in enumerate(reader, start=2):
            if row.get("source") != "wii":
                continue
            ts, tcol = _time(row)
            cols["ts"].append(ts)
            cols["time_column"].append(tcol)
            cols["w"].append(_num(row, "total_weight"))
            cols["x"].append(_num(row, "cop_x"))
            cols["z"].append(_num(row, "cop_z"))
            cols["valid"].append(_flag(row, W + "control_valid"))
            cols["loaded"].append(_flag(row, W + "board_loaded"))
            cols["centered"].append(_flag(row, W + "center_applied"))
            cols["age"].append(_num(row, AGE_COLUMN))
            cols["gen"].append((row.get(W + "center_generation") or "").strip())
            cols["instance"].append((row.get(W + "controller_instance_id") or "").strip())
            cols["csv_line"].append(lineno)

    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if not any(c in header for c in TIME_COLUMNS):
        missing.append("a time column (%s)" % ", ".join(TIME_COLUMNS))
    cols["columns"] = header
    cols["missing_columns"] = missing
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
        "required_window": window,
        # Auditable record of which flag columns the file actually had. Unlike v4
        # this is not defaulted to True and is not the basis of a pass.
        "flag_columns_present": dict(
            (f[len(W):] if f.startswith(W) else f, f in d["columns"]) for f in FLAG_COLUMNS
        ),
        "evidence": {
            "missing_columns": d["missing_columns"],
            "complete": not d["missing_columns"],
            "note": "a missing column is UNKNOWN, never a pass",
        },
        "note": ("A still loaded window is not proof of a protocol calibration interval. "
                 "Missing evidence is reported as unknown, not as satisfied."),
    }

    if d["missing_columns"]:
        out.update(
            verdict="UNKNOWN_EVIDENCE",
            reason="required column(s) absent: %s" % ", ".join(d["missing_columns"]),
            evidence_complete=False,
        )
        return out

    if n == 0:
        out.update(verdict="INSUFFICIENT_LOAD", reason="no wii rows")
        return out

    weights = [w for w in d["w"] if w is not None]
    out.update(
        weight_median_kg=round(_median(weights), 2) if weights else None,
        weight_max_kg=round(max(weights), 2) if weights else None,
        weight_min_kg=round(min(weights), 2) if weights else None,
    )
    if n < window:
        out.update(verdict="INSUFFICIENT_LOAD", reason="fewer than %d wii samples (%d)" % (window, n))
        return out

    # Per-row eligibility. Rows are never removed: an invalid row stays at its
    # index and blocks any window that spans it.
    eligible: List[bool] = []
    reasons = {"flag_missing": 0, "flag_false": 0, "age_missing": 0, "age_stale": 0,
               "identity_missing": 0, "no_timestamp": 0, "load_missing": 0, "cop_missing": 0}
    for i in range(n):
        row_reasons = []
        flags = (("valid", d["valid"][i]), ("loaded", d["loaded"][i]),
                 ("centered", d["centered"][i]))
        if any(val is None for _, val in flags):
            row_reasons.append("flag_missing")
        if any(val is False for _, val in flags):
            row_reasons.append("flag_false")
        age = d["age"][i]
        if age is None:
            row_reasons.append("age_missing")
        elif age < 0 or age > max_age_s:
            row_reasons.append("age_stale")
        if not d["gen"][i] or not d["instance"][i]:
            row_reasons.append("identity_missing")
        if d["ts"][i] is None:
            row_reasons.append("no_timestamp")
        if d["w"][i] is None:
            row_reasons.append("load_missing")
        if d["x"][i] is None or d["z"][i] is None:
            row_reasons.append("cop_missing")
        for r_name in row_reasons:
            reasons[r_name] += 1
        eligible.append(not row_reasons)

    out["ineligible_rows"] = {k: v for k, v in reasons.items() if v}
    out["eligible_rows"] = sum(eligible)

    def window_problem(i: int) -> str:
        """Return '' when the window is usable, else the blocking reason."""
        a, b = i, i + window
        if not all(eligible[a:b]):
            return "row_evidence_incomplete"
        for j in range(a + 1, b):
            dt = d["ts"][j] - d["ts"][j - 1]
            if dt is None:
                return "timestamp_missing"
            if dt <= 0:
                return "time_not_increasing"
            if dt > max_gap_s:
                return "time_gap"
        if len(set(d["gen"][a:b])) > 1:
            return "generation_changed"
        if len(set(d["instance"][a:b])) > 1:
            return "instance_changed"
        return ""

    loaded_windows = 0
    eligible_windows = 0
    best_std = float("inf")
    best_problem = ""
    start_found = -1

    for i in range(0, n - window + 1):
        seg_w = d["w"][i:i + window]
        if any(w is None for w in seg_w) or min(seg_w) < min_load:
            continue
        loaded_windows += 1

        problem = window_problem(i)
        if problem:
            best_problem = best_problem or problem
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
                       reason="load present but no window passed evidence checks (%s)" % (best_problem or "unknown"))
        else:
            out.update(verdict="LOADED_NOT_STATIONARY",
                       reason="sustained load in %d eligible windows, smallest CoP std %.3f cm > %.2f cm"
                              % (eligible_windows, best_std, still_cm))
        return out

    i = start_found
    mx = statistics.fmean(d["x"][i:i + window])
    mz = statistics.fmean(d["z"][i:i + window])
    radial = (mx * mx + mz * mz) ** 0.5
    durations = [d["ts"][j] - d["ts"][j - 1] for j in range(i + 1, i + window)]
    out.update(
        window_start_index=i,
        window_start_csv_line=d["csv_line"][i],
        window_end_csv_line=d["csv_line"][i + window - 1],
        window_start_ts=d["ts"][i],
        window_duration_s=round(d["ts"][i + window - 1] - d["ts"][i], 3),
        window_max_dt_ms=round(max(durations) * 1000.0, 1),
        window_weight_kg=round(statistics.fmean(d["w"][i:i + window]), 2),
        cop_x_cm=round(mx, 2), cop_z_cm=round(mz, 2),
        cop_std_x_cm=round(statistics.pstdev(d["x"][i:i + window]), 3),
        cop_std_z_cm=round(statistics.pstdev(d["z"][i:i + window]), 3),
        radial_cm=round(radial, 2),
        center_generation=d["gen"][i],
        controller_instance_id=d["instance"][i],
    )
    if out["window_duration_s"] <= 0:
        out.update(verdict="NO_ELIGIBLE_WINDOW", reason="non-positive window duration")
        return out
    if radial > tol_cm:
        out.update(verdict="SKEWED",
                   reason="baseline radial offset %.2f cm exceeds %.2f cm" % (radial, tol_cm))
    else:
        out.update(verdict="OK", reason="eligible loaded still window within tolerance")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Balance-board baseline pre-flight (v5, evidence-strict).")
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

    print("=== Wii baseline pre-flight (v5): %s ===" % os.path.basename(args.csv))
    print("wii rows %d | weight median %s kg | max %s kg | eligible rows %d"
          % (r["wii_rows"], r.get("weight_median_kg"), r.get("weight_max_kg"), r.get("eligible_rows", 0)))
    print("evidence complete: %s" % ("yes" if r["evidence"]["complete"] else "NO"))
    if r["evidence"]["missing_columns"]:
        print("missing columns: %s" % ", ".join(r["evidence"]["missing_columns"]))
    if r.get("ineligible_rows"):
        print("ineligible rows: %s" % json.dumps(r["ineligible_rows"], sort_keys=True))

    verdict = r["verdict"]
    if verdict == "UNKNOWN_EVIDENCE":
        print("\n[UNKNOWN_EVIDENCE] %s" % r.get("reason", ""))
        print("  Nothing can be verified from this file. This is not a pass.")
        rc = 6
    elif verdict == "INSUFFICIENT_LOAD":
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
        print("\n[SKEWED] window at samples %d-%d (csv lines %d-%d), load %.1f kg"
              % (r["window_start_index"], r["window_start_index"] + args.window - 1,
                 r["window_start_csv_line"], r["window_end_csv_line"], r["window_weight_kg"]))
        print("  CoP X=%+.2f cm Z=%+.2f cm radial=%.2f cm (tolerance %.1f cm)"
              % (r["cop_x_cm"], r["cop_z_cm"], r["radial_cm"], args.tolerance_cm))
        rc = 3
    else:
        print("\n[OK] window at samples %d-%d (csv lines %d-%d), load %.1f kg, "
              "duration %.2f s, CoP X=%+.2f Z=%+.2f cm (std %.2f / %.2f cm)"
              % (r["window_start_index"], r["window_start_index"] + args.window - 1,
                 r["window_start_csv_line"], r["window_end_csv_line"], r["window_weight_kg"],
                 r["window_duration_s"], r["cop_x_cm"], r["cop_z_cm"],
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
