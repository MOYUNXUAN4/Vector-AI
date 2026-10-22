#!/usr/bin/env python3
"""wii_cop_preflight_v6.py  (supersedes wii_cop_preflight_v5.py)

v5 defect found by the 2026-10-20 review of v5:
  * TIME_COLUMNS preferred `backend_timestamp`, i.e. the backend RECEIVE clock, and
    `_time` could only parse bare numbers. The real Wii source clock is written as
    ISO-8601 (`wii_control_timestamp`, `source_timestamp`), so on real files the
    window measured receive-time continuity while claiming source continuity. A
    1020 ms gap in the board's own clock with 1 ms receive spacing therefore
    scored OK.
  * `_num` used `x == x`, which rejects NaN but accepts +/-Infinity. An all-`inf`
    timestamp column produced verdict OK with `window_duration_s: NaN`, and the
    JSON was written with a non-standard NaN literal.
  * no control-sequence evidence was retained, and the time column could switch
    per row without the chosen domain being recorded.

v6:
  * one declared Wii source clock is selected ONCE from the header, in this order:
        wii_control_timestamp  (board-side sample time, ISO-8601)
        source_timestamp       (record-side ISO-8601)
        backend_timestamp      (receive time -- NOT a source clock)
    A file that only carries receive time is SOURCE_CLOCK_UNAVAILABLE, never OK.
    The selected domain is reported as `time_domain` and is also written into the
    window output. Rows that cannot be placed on that clock are ineligible; there
    is no per-row fallback.
  * continuity is judged on the source clock: repeated timestamps are collapsed
    (the logger writes the same control sample onto several telemetry rows), and
    the distinct samples must be strictly increasing with 0 < dt <= --max-gap.
  * `wii_control_sequence` is required and checked: non-decreasing, and every
    step between distinct samples must be <= --max-seq-gap. A reversal or a skip
    is a barrier. A skipped sequence with a flat clock is exactly the case the
    receive-time check could not see.
  * every numeric field must be finite. A non-finite value anywhere in a
    timestamp / age / load / CoP field makes the file UNKNOWN_EVIDENCE, because
    the evidence itself is corrupt; NaN is never serialised as an accepted value.
  * receive timing is reported separately (`window_receive_duration_s`,
    `receive_max_dt_ms`) as a descriptive statistic and never used as the
    continuity evidence.

Scope: DESCRIPTIVE check on recorded telemetry. A loaded, still window inside
ordinary gameplay is not proof that a protocol calibration interval occurred.

Exit codes
  0 OK
  2 INSUFFICIENT_LOAD
  3 SKEWED
  4 LOADED_NOT_STATIONARY
  5 NO_ELIGIBLE_WINDOW
  6 UNKNOWN_EVIDENCE   required columns absent or non-finite evidence
  8 SOURCE_CLOCK_UNAVAILABLE   only receive time exists; source continuity unknowable
  1 input error / invalid CLI setting
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import math
import os
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

W = "wii_"

FLAG_COLUMNS = (W + "control_valid", W + "board_loaded", W + "center_applied")
VALUE_COLUMNS = ("total_weight", "cop_x", "cop_z")
IDENTITY_COLUMNS = (W + "center_generation", W + "controller_instance_id")
AGE_COLUMN = W + "control_age_seconds"
SEQ_COLUMN = W + "control_sequence"
RECEIVE_COLUMN = "backend_timestamp"

# (column, domain label, is_source_clock). Order is the selection priority.
TIME_DOMAINS: Tuple[Tuple[str, str, bool], ...] = (
    (W + "control_timestamp", "board_control", True),
    ("source_timestamp", "record_source", True),
    (RECEIVE_COLUMN, "receive", False),
)

REQUIRED_COLUMNS = (VALUE_COLUMNS + FLAG_COLUMNS + (AGE_COLUMN, SEQ_COLUMN)
                    + IDENTITY_COLUMNS)


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


NONFINITE: List[str] = []  # (column, value) pairs found while loading


def _num(row: dict, key: str) -> Optional[float]:
    """Finite float, or None when absent / unparseable. Infinity is recorded."""
    v = row.get(key)
    if v is None or str(v).strip() == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        NONFINITE.append("%s=%s" % (key, v))
        return None
    return x


def _iso(s: Any) -> Optional[float]:
    """Parse an ISO-8601 timestamp (with or without fraction / trailing Z)."""
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    if t[-1:] in ("Z", "z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    x = dt.timestamp()
    return x if math.isfinite(x) else None


def _time_from(row: dict, column: str, domain: str) -> Optional[float]:
    """Parse one declared column only. ISO for source domains, number otherwise."""
    if column == RECEIVE_COLUMN:
        return _num(row, column)
    x = _iso(row.get(column))
    if x is not None:
        return x
    # A source column carrying a bare epoch number is accepted only when it is
    # plausibly an epoch, otherwise the row simply has no reading on that clock.
    n = _num(row, column)
    if n is not None and n > 1e8:
        return n
    return None


def select_domain(header: List[str]) -> Tuple[str, str, bool]:
    """First declared clock that exists in the header. ('', 'absent', False) if none."""
    for column, domain, is_source in TIME_DOMAINS:
        if column in header:
            return column, domain, is_source
    return "", "absent", False


def load_wii(path: str) -> Dict[str, Any]:
    cols: Dict[str, Any] = {
        "ts": [], "recv": [], "w": [], "x": [], "z": [],
        "valid": [], "loaded": [], "centered": [],
        "age": [], "gen": [], "instance": [], "seq": [],
        "csv_line": [],
    }
    header: List[str] = []
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        column, domain, is_source = select_domain(header)
        for lineno, row in enumerate(reader, start=2):
            if row.get("source") != "wii":
                continue
            cols["ts"].append(_time_from(row, column, domain) if column else None)
            cols["recv"].append(_num(row, RECEIVE_COLUMN))
            cols["w"].append(_num(row, "total_weight"))
            cols["x"].append(_num(row, "cop_x"))
            cols["z"].append(_num(row, "cop_z"))
            cols["valid"].append(_flag(row, W + "control_valid"))
            cols["loaded"].append(_flag(row, W + "board_loaded"))
            cols["centered"].append(_flag(row, W + "center_applied"))
            cols["age"].append(_num(row, AGE_COLUMN))
            cols["gen"].append((row.get(W + "center_generation") or "").strip())
            cols["instance"].append((row.get(W + "controller_instance_id") or "").strip())
            seq = _num(row, SEQ_COLUMN)
            cols["seq"].append(int(seq) if seq is not None else None)
            cols["csv_line"].append(lineno)

    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if not column:
        missing.append("a time column (%s)" % ", ".join(c for c, _, _ in TIME_DOMAINS))
    cols["columns"] = header
    cols["missing_columns"] = missing
    cols["time_column"] = column
    cols["time_domain"] = domain
    cols["clock_is_source"] = is_source
    cols["nonfinite"] = list(NONFINITE)
    return cols


def _median(vals: List[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def audit(path: str, window: int = 50, min_load: float = 20.0, still_cm: float = 1.0,
          tol_cm: float = 1.5, max_gap_s: float = 0.15, max_age_s: float = 0.25,
          max_seq_gap: int = 1) -> Dict[str, Any]:
    NONFINITE.clear()
    d = load_wii(path)
    n = len(d["w"])
    out: Dict[str, Any] = {
        "path": path,
        "wii_rows": n,
        "evidence_level": "descriptive",
        "required_window": window,
        "time_column": d["time_column"],
        "time_domain": d["time_domain"],
        "clock_is_source": d["clock_is_source"],
        "flag_columns_present": dict(
            (f[len(W):] if f.startswith(W) else f, f in d["columns"]) for f in FLAG_COLUMNS
        ),
        "evidence": {
            "missing_columns": d["missing_columns"],
            "nonfinite_values": d["nonfinite"][:10],
            "nonfinite_count": len(d["nonfinite"]),
            "complete": not d["missing_columns"] and not d["nonfinite"],
            "note": "a missing column is UNKNOWN, never a pass",
        },
        "note": ("A still loaded window is not proof of a protocol calibration interval. "
                 "Missing evidence is reported as unknown, not as satisfied."),
    }

    if d["nonfinite"]:
        out.update(verdict="UNKNOWN_EVIDENCE",
                   reason="non-finite numeric evidence: %s" % ", ".join(d["nonfinite"][:5]),
                   evidence_complete=False,
                   source_continuity_verified=False)
        return out

    if d["missing_columns"]:
        out.update(verdict="UNKNOWN_EVIDENCE",
                   reason="required column(s) absent: %s" % ", ".join(d["missing_columns"]),
                   evidence_complete=False,
                   source_continuity_verified=False)
        return out

    if not d["clock_is_source"]:
        out.update(
            verdict="SOURCE_CLOCK_UNAVAILABLE",
            reason=("only the receive clock (%s) is present; receive spacing cannot "
                    "establish uninterrupted source control" % (d["time_column"] or "none")),
            evidence_complete=False,
            source_continuity_verified=False,
        )
        return out

    if n == 0:
        out.update(verdict="INSUFFICIENT_LOAD", reason="no wii rows",
                   source_continuity_verified=False)
        return out

    weights = [w for w in d["w"] if w is not None]
    out.update(
        weight_median_kg=round(_median(weights), 2) if weights else None,
        weight_max_kg=round(max(weights), 2) if weights else None,
        weight_min_kg=round(min(weights), 2) if weights else None,
    )
    if n < window:
        out.update(verdict="INSUFFICIENT_LOAD",
                   reason="fewer than %d wii samples (%d)" % (window, n),
                   source_continuity_verified=False)
        return out

    # Per-row eligibility. Rows are never removed: an invalid row stays at its
    # index and blocks any window that spans it.
    eligible: List[bool] = []
    reasons = {"flag_missing": 0, "flag_false": 0, "age_missing": 0, "age_stale": 0,
               "identity_missing": 0, "no_timestamp": 0, "no_sequence": 0,
               "load_missing": 0, "cop_missing": 0}
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
        if d["seq"][i] is None:
            row_reasons.append("no_sequence")
        if d["w"][i] is None:
            row_reasons.append("load_missing")
        if d["x"][i] is None or d["z"][i] is None:
            row_reasons.append("cop_missing")
        for r_name in row_reasons:
            reasons[r_name] += 1
        eligible.append(not row_reasons)

    out["ineligible_rows"] = {k: v for k, v in reasons.items() if v}
    out["eligible_rows"] = sum(eligible)

    def distinct_samples(a: int, b: int) -> Tuple[List[float], List[int]]:
        """Collapse repeated (timestamp, sequence) pairs onto the source clock.

        The logger writes the same control sample onto more than one telemetry
        row, so an exact repeat is the same sample, not a new one. A repeat with
        a *different* sequence is a contradiction and is reported by the caller.
        """
        ts: List[float] = []
        seq: List[int] = []
        for j in range(a, b):
            t, s = d["ts"][j], d["seq"][j]
            if ts and t == ts[-1] and s == seq[-1]:
                continue
            ts.append(t)
            seq.append(s)
        return ts, seq

    def window_problem(i: int) -> str:
        """Return '' when the window is usable, else the blocking reason."""
        a, b = i, i + window
        if not all(eligible[a:b]):
            return "row_evidence_incomplete"
        ts, seq = distinct_samples(a, b)
        if len(ts) < 2:
            return "no_source_progress"
        for j in range(1, len(ts)):
            dt = ts[j] - ts[j - 1]
            if dt <= 0:
                return "source_time_not_increasing"
            if dt > max_gap_s:
                return "source_time_gap"
        for j in range(1, len(seq)):
            step = seq[j] - seq[j - 1]
            if step < 0:
                return "sequence_reversal"
            if step > max_seq_gap:
                return "sequence_gap"
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
                   reason="no %d-sample window where every sample carried >= %.1f kg" % (window, min_load),
                   source_continuity_verified=False)
        return out

    if start_found < 0:
        if eligible_windows == 0:
            out.update(verdict="NO_ELIGIBLE_WINDOW",
                       reason="load present but no window passed evidence checks (%s)" % (best_problem or "unknown"),
                       source_continuity_verified=False)
        else:
            out.update(verdict="LOADED_NOT_STATIONARY",
                       reason="sustained load in %d eligible windows, smallest CoP std %.3f cm > %.2f cm"
                              % (eligible_windows, best_std, still_cm),
                       source_continuity_verified=True)
        return out

    i = start_found
    mx = statistics.fmean(d["x"][i:i + window])
    mz = statistics.fmean(d["z"][i:i + window])
    radial = (mx * mx + mz * mz) ** 0.5
    ts, seq = distinct_samples(i, i + window)
    recv = [t for t in d["recv"][i:i + window] if t is not None]
    recv_steps = [b - a for a, b in zip(recv, recv[1:])]
    out.update(
        window_start_index=i,
        window_start_csv_line=d["csv_line"][i],
        window_end_csv_line=d["csv_line"][i + window - 1],
        window_start_ts=ts[0],
        window_duration_s=round(ts[-1] - ts[0], 3),
        window_unique_samples=len(ts),
        window_max_dt_ms=round(max(b - a for a, b in zip(ts, ts[1:])) * 1000.0, 1),
        window_sequence_first=seq[0],
        window_sequence_last=seq[-1],
        window_sequence_max_step=max(b - a for a, b in zip(seq, seq[1:])),
        window_receive_duration_s=(round(recv[-1] - recv[0], 3) if len(recv) > 1 else None),
        receive_max_dt_ms=(round(max(recv_steps) * 1000.0, 1) if recv_steps else None),
        receive_note="receive timing is descriptive; it is not the continuity evidence",
        window_weight_kg=round(statistics.fmean(d["w"][i:i + window]), 2),
        cop_x_cm=round(mx, 2), cop_z_cm=round(mz, 2),
        cop_std_x_cm=round(statistics.pstdev(d["x"][i:i + window]), 3),
        cop_std_z_cm=round(statistics.pstdev(d["z"][i:i + window]), 3),
        radial_cm=round(radial, 2),
        center_generation=d["gen"][i],
        controller_instance_id=d["instance"][i],
        source_continuity_verified=True,
    )
    if out["window_duration_s"] <= 0:
        out.update(verdict="NO_ELIGIBLE_WINDOW", reason="non-positive window duration",
                   source_continuity_verified=False)
        return out
    if radial > tol_cm:
        out.update(verdict="SKEWED",
                   reason="baseline radial offset %.2f cm exceeds %.2f cm" % (radial, tol_cm))
    else:
        out.update(verdict="OK", reason="eligible loaded still window within tolerance")
    return out


def _finite_arg(name: str, value: float, lo: float, hi: float) -> None:
    if not math.isfinite(value) or value < lo or value > hi:
        raise ValueError("%s must be finite and within [%g, %g], got %r" % (name, lo, hi, value))


def main() -> int:
    ap = argparse.ArgumentParser(description="Balance-board baseline pre-flight (v6, source-clock strict).")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--window", type=int, default=50)
    ap.add_argument("--min-load-kg", type=float, default=20.0)
    ap.add_argument("--still-cm", type=float, default=1.0)
    ap.add_argument("--tolerance-cm", type=float, default=1.5)
    ap.add_argument("--max-gap", type=float, default=0.15)
    ap.add_argument("--max-age-s", type=float, default=0.25)
    ap.add_argument("--max-seq-gap", type=int, default=1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    try:
        _finite_arg("--min-load-kg", args.min_load_kg, 0.0, 1000.0)
        _finite_arg("--still-cm", args.still_cm, 1e-9, 1e6)
        _finite_arg("--tolerance-cm", args.tolerance_cm, 1e-9, 1e6)
        _finite_arg("--max-gap", args.max_gap, 1e-9, 3600.0)
        _finite_arg("--max-age-s", args.max_age_s, 1e-9, 3600.0)
        if args.window < 2 or args.window > 100000:
            raise ValueError("--window must be within [2, 100000], got %d" % args.window)
        if args.max_seq_gap < 1 or args.max_seq_gap > 100000:
            raise ValueError("--max-seq-gap must be within [1, 100000], got %d" % args.max_seq_gap)
    except ValueError as exc:
        print("invalid setting: %s" % exc, file=sys.stderr)
        return 1

    if not os.path.isfile(args.csv):
        print("missing: %s" % args.csv, file=sys.stderr)
        return 1

    r = audit(args.csv, args.window, args.min_load_kg, args.still_cm, args.tolerance_cm,
              args.max_gap, args.max_age_s, args.max_seq_gap)

    print("=== Wii baseline pre-flight (v6): %s ===" % os.path.basename(args.csv))
    print("wii rows %d | weight median %s kg | max %s kg | eligible rows %d"
          % (r["wii_rows"], r.get("weight_median_kg"), r.get("weight_max_kg"), r.get("eligible_rows", 0)))
    print("source clock: %s (%s)" % (r.get("time_column") or "none", r.get("time_domain")))
    print("evidence complete: %s" % ("yes" if r["evidence"]["complete"] else "NO"))
    if r["evidence"]["missing_columns"]:
        print("missing columns: %s" % ", ".join(r["evidence"]["missing_columns"]))
    if r["evidence"].get("nonfinite_count"):
        print("non-finite values: %d e.g. %s"
              % (r["evidence"]["nonfinite_count"], ", ".join(r["evidence"]["nonfinite_values"])))
    if r.get("ineligible_rows"):
        print("ineligible rows: %s" % json.dumps(r["ineligible_rows"], sort_keys=True))

    verdict = r["verdict"]
    if verdict == "UNKNOWN_EVIDENCE":
        print("\n[UNKNOWN_EVIDENCE] %s" % r.get("reason", ""))
        print("  Nothing can be verified from this file. This is not a pass.")
        rc = 6
    elif verdict == "SOURCE_CLOCK_UNAVAILABLE":
        print("\n[SOURCE_CLOCK_UNAVAILABLE] %s" % r.get("reason", ""))
        print("  Receive spacing is not evidence of uninterrupted source control.")
        rc = 8
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
        print("\n[OK] window at samples %d-%d (csv lines %d-%d), load %.1f kg"
              % (r["window_start_index"], r["window_start_index"] + args.window - 1,
                 r["window_start_csv_line"], r["window_end_csv_line"], r["window_weight_kg"]))
        print("  source clock %s: %.2f s over %d distinct samples, max step %.1f ms; "
              "sequence %d..%d (max step %d)"
              % (r["time_domain"], r["window_duration_s"], r["window_unique_samples"],
                 r["window_max_dt_ms"], r["window_sequence_first"], r["window_sequence_last"],
                 r["window_sequence_max_step"]))
        print("  receive span %.2f s (descriptive only), CoP X=%+.2f Z=%+.2f cm (std %.2f / %.2f cm)"
              % (r["window_receive_duration_s"], r["cop_x_cm"], r["cop_z_cm"],
                 r["cop_std_x_cm"], r["cop_std_z_cm"]))
        rc = 0

    print("\nNote: descriptive only. A still loaded window in gameplay is not proof that a")
    print("      protocol calibration interval was executed.")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2, allow_nan=False)
        print("written: %s" % args.out)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
