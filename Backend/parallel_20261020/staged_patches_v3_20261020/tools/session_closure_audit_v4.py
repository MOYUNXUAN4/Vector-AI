#!/usr/bin/env python3
"""session_closure_audit_v4.py  (supersedes session_closure_audit_v3.py)

v3 defects addressed here:
  * it accepted any non-empty `session_outcome` as TERMINAL_OUTCOME_RECORDED
    without checking `run_state`. A session that wrote an outcome while still
    `running` would pass. v4 requires both, and flags the mismatch separately.
  * `diag_send_completed` defaulted to False when the diagnostic record was
    absent, which reads as "send failed" when the truth is "not observed".
    v4 keeps it tri-state (True / False / null).
  * it still named the sequence difference in a way that invites reading it as
    proof about the network. v4 calls it `unpersisted_sequence_span` and states
    in the payload that it is the distance between the last persisted sequence
    and the terminal snapshot, not a per-packet delivery record.

Labels are observational. `cause` is always "unknown": end timestamps and local
send-completion cannot distinguish a receiver stall, a writer block, a process
exit, or packet loss.

Read-only. Writes nothing unless --out is passed.

Exit codes
  0  completed run (no report needed)
  1  input error
  7  one or more sessions ended without a validated terminal outcome
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional

SAME_INSTANT_S = 0.25


def index_diagnostics(diag_dir: Optional[str]) -> Dict[str, Any]:
    index: Dict[str, Any] = {}
    if not diag_dir or not os.path.isdir(diag_dir):
        return index
    for path in sorted(glob.glob(os.path.join(diag_dir, "samples_*.jsonl"))):
        try:
            fh = open(path, "r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line or '"lifecycle"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                run_id = rec.get("run_id")
                if not run_id:
                    continue
                e = index.setdefault(run_id, {"files": set()})
                e["files"].add(os.path.basename(path))
                ev = rec.get("lifecycle_event") or ""
                if ev == "terminal_snapshot_frozen":
                    e["terminal_seq"] = rec.get("sequence")
                    e["terminal_backend_ts"] = rec.get("backend_timestamp")
                    e["terminal_outcome"] = rec.get("session_outcome")
                elif ev == "terminal_udp_send_call_completed":
                    e["terminal_send_completed"] = True
                elif ev == "terminal_udp_send_call_failed":
                    e["terminal_send_completed"] = False
                ts = rec.get("unity_time")
                if isinstance(ts, (int, float)):
                    e["last_sample_ts"] = max(e.get("last_sample_ts", -1e18), ts)
    for e in index.values():
        e["files"] = sorted(e["files"])
    return index


def audit_session(session_dir: str, diag_index: Dict[str, Any]) -> Dict[str, Any]:
    raw = os.path.join(session_dir, "raw.csv")
    out: Dict[str, Any] = {
        "session": os.path.basename(session_dir.rstrip("/\\")),
        "raw_csv": raw,
        "unity_rows": 0, "wii_rows": 0,
        "first_unity_ts": None, "last_unity_ts": None, "last_wii_ts": None,
        "last_seq": None, "run_id": "", "run_state": "", "session_outcome": "",
        "cause": "unknown",
    }
    if not os.path.isfile(raw):
        out["verdict"] = "MISSING_CSV"
        return out

    with open(raw, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh):
            src = row.get("source")
            try:
                bts = float(row.get("backend_timestamp") or "nan")
            except (TypeError, ValueError):
                bts = float("nan")
            if src == "unity":
                out["unity_rows"] += 1
                if bts == bts:
                    if out["first_unity_ts"] is None:
                        out["first_unity_ts"] = bts
                    out["last_unity_ts"] = bts
                seq = row.get("sequence")
                if seq not in (None, ""):
                    try:
                        out["last_seq"] = int(float(seq))
                    except ValueError:
                        pass
                if row.get("run_id"):
                    out["run_id"] = row["run_id"]
                if row.get("run_state"):
                    out["run_state"] = row["run_state"]
                if row.get("session_outcome"):
                    out["session_outcome"] = row["session_outcome"]
            elif src == "wii":
                out["wii_rows"] += 1
                if bts == bts:
                    out["last_wii_ts"] = bts

    if out["unity_rows"] == 0:
        out["verdict"] = "EMPTY"
        return out

    if out["first_unity_ts"] is not None and out["last_unity_ts"] is not None:
        out["csv_span_s"] = round(out["last_unity_ts"] - out["first_unity_ts"], 3)

    both = out["last_unity_ts"] is not None and out["last_wii_ts"] is not None
    delta = abs(out["last_unity_ts"] - out["last_wii_ts"]) if both else None
    out["source_stop_delta_s"] = round(delta, 3) if delta is not None else None

    outcome = out["session_outcome"].strip()
    ended = out["run_state"].strip().lower() == "ended"

    if outcome and ended:
        out["verdict"] = "TERMINAL_OUTCOME_VALIDATED"
    elif outcome and not ended:
        out["verdict"] = "OUTCOME_WITHOUT_ENDED_STATE"
    elif not outcome and delta is not None and delta <= SAME_INSTANT_S:
        out["verdict"] = "BOTH_STREAMS_CEASE_TOGETHER"
    elif not outcome and both and out["last_unity_ts"] < out["last_wii_ts"]:
        out["verdict"] = "UNITY_CEASES_BEFORE_WII"
    elif not outcome and both and out["last_wii_ts"] < out["last_unity_ts"]:
        out["verdict"] = "WII_CEASES_BEFORE_UNITY"
    else:
        out["verdict"] = "INCOMPLETE_NO_OUTCOME"

    diag = diag_index.get(out["run_id"]) if out["run_id"] else None
    if diag:
        out["diag_files"] = diag.get("files", [])
        out["diag_terminal_outcome"] = diag.get("terminal_outcome")
        out["diag_send_completed"] = diag.get("terminal_send_completed")  # tri-state
        term_seq = diag.get("terminal_seq")
        if isinstance(term_seq, int) and out["last_seq"] is not None:
            out["unpersisted_sequence_span"] = term_seq - out["last_seq"]
            out["unpersisted_span_meaning"] = (
                "terminal_snapshot sequence minus last persisted CSV sequence; "
                "an unpersisted span, not a per-packet delivery record and not network proof"
            )
        term_ts = diag.get("terminal_backend_ts")
        if isinstance(term_ts, (int, float)) and out["last_unity_ts"] is not None:
            out["tail_silence_s"] = round(term_ts - out["last_unity_ts"], 3)
        if outcome and out.get("diag_terminal_outcome"):
            out["outcome_match"] = (outcome == out["diag_terminal_outcome"])

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Observational session closure audit (v4).")
    ap.add_argument("--root", required=True)
    ap.add_argument("--diag-dir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--only-problems", action="store_true")
    args = ap.parse_args()

    sessions = sorted(glob.glob(os.path.join(args.root, "session_*")))
    if not sessions:
        print("no session_* under %s" % args.root, file=sys.stderr)
        return 1

    diag_index = index_diagnostics(args.diag_dir)
    results = [audit_session(s, diag_index) for s in sessions]

    order = ["TERMINAL_OUTCOME_VALIDATED", "OUTCOME_WITHOUT_ENDED_STATE",
             "BOTH_STREAMS_CEASE_TOGETHER", "UNITY_CEASES_BEFORE_WII",
             "WII_CEASES_BEFORE_UNITY", "INCOMPLETE_NO_OUTCOME", "EMPTY", "MISSING_CSV"]
    results.sort(key=lambda r: (order.index(r["verdict"]) if r["verdict"] in order else 99, r["session"]))

    print("=== Session closure audit (v4): %s ===" % args.root)
    print("%-34s %-30s %7s %7s %9s %12s" % ("session", "verdict", "unity", "wii", "last_seq", "unpersisted"))
    for r in results:
        if args.only_problems and r["verdict"] == "TERMINAL_OUTCOME_VALIDATED":
            continue
        print("%-34s %-30s %7d %7d %9s %12s" % (
            r["session"], r["verdict"], r["unity_rows"], r["wii_rows"],
            "-" if r["last_seq"] is None else r["last_seq"],
            r.get("unpersisted_sequence_span", "-")))

    counts: Dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\nsummary: %s" % json.dumps(counts, sort_keys=True))

    bad = [r for r in results if r["verdict"] != "TERMINAL_OUTCOME_VALIDATED"]
    if bad:
        print("\n%d session(s) did not validate a terminal outcome:" % len(bad))
        for r in bad:
            extra = ""
            if r.get("unpersisted_sequence_span") is not None:
                extra = " | unpersisted seq span %d, send_completed=%s" % (
                    r["unpersisted_sequence_span"], r.get("diag_send_completed"))
            print("  - %s: %s%s" % (r["session"], r["verdict"], extra))
        print("  cause is unknown for all of the above; these labels describe what the")
        print("  files show, not why it happened.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"root": args.root, "diag_dir": args.diag_dir,
                       "counts": counts, "sessions": results}, fh, indent=2, ensure_ascii=False)
        print("\nwritten: %s" % args.out)
    return 0 if not bad else 7


if __name__ == "__main__":
    raise SystemExit(main())
