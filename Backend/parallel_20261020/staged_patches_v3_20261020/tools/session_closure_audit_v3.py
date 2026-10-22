#!/usr/bin/env python3
"""session_closure_audit_v3.py

Descriptive audit of session lifecycle closure across disk telemetry and local diagnostics.

Key improvements in v3 (resolving defects from independent review 2026-10-20):
  * Neutral descriptive taxonomy: avoids asserting speculative causal claims
    (e.g. "RECEIVER_BLACKOUT", "network loss", or "process death") from timestamp
    coincidence alone.
  * Rigorous outcome validation: checks consistency between terminal outcome in raw.csv
    and terminal lifecycle records in Unity diagnostics (samples_*.jsonl).
  * Sequence span precision: labels unpersisted packet span as `unpersisted_sequence_span`
    and explicitly notes whether UdpClient.Send returned in diagnostics, distinguishing
    local send-completion from verified backend receipt (no network ACK exists in UDP).
  * Asymmetric cessation handling: identifies whether Unity or Wii stopped earlier
    without presuming sender failure.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from typing import Dict, Any, List, Optional

BLACKOUT_TOLERANCE_S = 0.25


def index_diagnostics(diag_dir: str) -> Dict[str, Any]:
    """Indexes Unity diagnostic JSONL files by run_id."""
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
                entry = index.setdefault(run_id, {"files": set()})
                entry["files"].add(os.path.basename(path))

                event = rec.get("lifecycle_event") or ""
                if event == "terminal_snapshot_frozen":
                    entry["terminal_seq"] = rec.get("sequence")
                    entry["terminal_backend_ts"] = rec.get("backend_timestamp")
                    entry["terminal_outcome"] = rec.get("session_outcome")
                elif event == "terminal_udp_send_call_completed":
                    entry["terminal_send_completed"] = True
                elif event == "terminal_udp_send_call_failed":
                    entry["terminal_send_completed"] = False

                ts = rec.get("unity_time")
                if isinstance(ts, (int, float)):
                    entry["last_sample_ts"] = max(entry.get("last_sample_ts", -1e18), ts)

    for entry in index.values():
        entry["files"] = sorted(entry["files"])
    return index


def audit_session(session_dir: str, diag_index: Dict[str, Any]) -> Dict[str, Any]:
    raw_path = os.path.join(session_dir, "raw.csv")
    out: Dict[str, Any] = {
        "session": os.path.basename(session_dir.rstrip("/\\")),
        "raw_csv": raw_path,
        "unity_rows": 0,
        "wii_rows": 0,
        "last_seq": None,
        "last_unity_backend_ts": None,
        "last_wii_backend_ts": None,
        "first_unity_backend_ts": None,
        "run_id": "",
        "run_state": "",
        "session_outcome": "",
    }

    if not os.path.isfile(raw_path):
        out["verdict"] = "MISSING_CSV"
        return out

    with open(raw_path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh):
            src = row.get("source")
            try:
                bts = float(row.get("backend_timestamp") or "nan")
            except (ValueError, TypeError):
                bts = float("nan")

            if src == "unity":
                out["unity_rows"] += 1
                if out["first_unity_backend_ts"] is None and bts == bts:
                    out["first_unity_backend_ts"] = bts
                if bts == bts:
                    out["last_unity_backend_ts"] = bts
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
                    out["last_wii_backend_ts"] = bts

    if out["unity_rows"] == 0:
        out["verdict"] = "EMPTY"
        return out

    # Determine classification
    both_present = (out["last_wii_backend_ts"] is not None and out["last_unity_backend_ts"] is not None)
    delta_s = abs(out["last_unity_backend_ts"] - out["last_wii_backend_ts"]) if both_present else None
    out["source_stop_delta_s"] = round(delta_s, 3) if delta_s is not None else None

    if out["session_outcome"]:
        out["verdict"] = "TERMINAL_OUTCOME_RECORDED"
    else:
        if delta_s is not None and delta_s <= BLACKOUT_TOLERANCE_S:
            out["verdict"] = "SIMULTANEOUS_CESSATION_WITHOUT_OUTCOME"
            out["notes"] = "Both sources ceased at approximately same backend timestamp. Candidate causes: receiver stall, writer blocking, process exit, network interface down."
        elif both_present and out["last_unity_backend_ts"] < out["last_wii_backend_ts"]:
            out["verdict"] = "UNITY_CEASED_BEFORE_WII"
            out["notes"] = f"Unity stopped logging {out['source_stop_delta_s']}s before Wii."
        elif both_present and out["last_wii_backend_ts"] < out["last_unity_backend_ts"]:
            out["verdict"] = "WII_CEASED_BEFORE_UNITY"
            out["notes"] = f"Wii stopped logging {out['source_stop_delta_s']}s before Unity."
        else:
            out["verdict"] = "INCOMPLETE_WITHOUT_OUTCOME"

    if out["first_unity_backend_ts"] and out["last_unity_backend_ts"]:
        out["csv_span_s"] = round(out["last_unity_backend_ts"] - out["first_unity_backend_ts"], 3)

    # Diagnostic cross-verification
    diag = diag_index.get(out["run_id"]) if out["run_id"] else None
    if diag:
        out["diag_files"] = diag.get("files", [])
        out["diag_terminal_outcome"] = diag.get("terminal_outcome")
        out["diag_send_completed"] = diag.get("terminal_send_completed", False)
        term_seq = diag.get("terminal_seq")
        if isinstance(term_seq, int) and out["last_seq"] is not None:
            out["unpersisted_sequence_span"] = term_seq - out["last_seq"]
        term_bts = diag.get("terminal_backend_ts")
        if isinstance(term_bts, (int, float)) and out["last_unity_backend_ts"]:
            out["tail_silence_s"] = round(term_bts - out["last_unity_backend_ts"], 3)

        # Cross-check outcome match
        if out["session_outcome"] and out["diag_terminal_outcome"]:
            out["outcome_match"] = (out["session_outcome"] == out["diag_terminal_outcome"])

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Session closure and lifecycle audit (v3).")
    ap.add_argument("--root", required=True, help="directory containing session_* directories")
    ap.add_argument("--diag-dir", default=None, help="Unity diagnostics dir (samples_*.jsonl)")
    ap.add_argument("--out", default=None, help="write JSON report to output path")
    ap.add_argument("--only-problems", action="store_true", help="only print incomplete sessions")
    args = ap.parse_args()

    sessions = sorted(glob.glob(os.path.join(args.root, "session_*")))
    if not sessions:
        print(f"No session_* directories found under: {args.root}", file=sys.stderr)
        return 1

    diag_index = index_diagnostics(args.diag_dir) if args.diag_dir else {}
    results = [audit_session(s, diag_index) for s in sessions]

    order = {
        "TERMINAL_OUTCOME_RECORDED": 0,
        "SIMULTANEOUS_CESSATION_WITHOUT_OUTCOME": 1,
        "UNITY_CEASED_BEFORE_WII": 2,
        "WII_CEASED_BEFORE_UNITY": 3,
        "INCOMPLETE_WITHOUT_OUTCOME": 4,
        "EMPTY": 5,
        "MISSING_CSV": 6
    }
    results.sort(key=lambda r: (order.get(r["verdict"], 9), r["session"]))

    print(f"=== Session closure audit (v3): {args.root} ===")
    print("%-34s %-38s %7s %7s %9s %11s %9s" %
          ("session", "verdict", "unity", "wii", "last_seq", "unpersisted", "silence_s"))

    for r in results:
        if args.only_problems and r["verdict"] == "TERMINAL_OUTCOME_RECORDED":
            continue
        print("%-34s %-38s %7d %7d %9s %11s %9s" % (
            r["session"], r["verdict"], r["unity_rows"], r["wii_rows"],
            r.get("last_seq") or "-",
            r.get("unpersisted_sequence_span") if r.get("unpersisted_sequence_span") is not None else "-",
            r.get("tail_silence_s") if r.get("tail_silence_s") is not None else "-"
        ))

    counts: Dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    print("\nSummary counts:")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")

    bad = [r for r in results if r["verdict"] != "TERMINAL_OUTCOME_RECORDED"]
    if bad:
        print(f"\n{len(bad)} session(s) ended without an explicit terminal outcome:")
        for r in bad:
            extra = ""
            if r.get("unpersisted_sequence_span") is not None:
                extra = f" (Unity diagnostics recorded seq {r.get('last_seq', 0) + r['unpersisted_sequence_span']} with send_completed={r.get('diag_send_completed')})"
            print(f"  - {r['session']}: {r['verdict']}{extra}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({
                "root": args.root,
                "diag_dir": args.diag_dir,
                "counts": counts,
                "sessions": results
            }, fh, indent=2, ensure_ascii=False)
        print(f"\nReport written to: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
