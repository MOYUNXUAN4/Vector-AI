#!/usr/bin/env python3
"""session_closure_audit_v5.py  (supersedes session_closure_audit_v4.py)

v4 defect found by an independent adversarial review (2026-10-20):
  * the verdict TERMINAL_OUTCOME_VALIDATED was assigned from the CSV alone
    (outcome + run_state=ended) BEFORE the diagnostics were consulted. The
    diagnostic block could then only attach `outcome_match: false`; it could not
    change the verdict. Fixture: CSV says edge_exit at sequence 10, the same
    run's diagnostic terminal snapshot says user_exit at sequence 20 -> v4 still
    returned TERMINAL_OUTCOME_VALIDATED, and --only-problems hid it.

v5:
  * the terminal row itself must carry both a non-empty outcome and
    run_state=ended (same row, not "some row had each");
  * the outcome must be one of the four outcomes the Unity source can emit
    (`LevelManager.GetCompletionOutcome`, `MarkRunEnded` call sites):
    completed / calibration_completed / edge_exit / user_exit. Anything else is
    OUTCOME_SEMANTICS_UNKNOWN, not a pass;
  * a file containing more than one run_id is MIXED_RUN: ownership of the
    terminal row is ambiguous;
  * diagnostics are classified, not merely attached:
        corroborated  same outcome, terminal snapshot already persisted, send not failed
        partial       same outcome, but terminal_snapshot sequence is ahead of the
                      last persisted row (the terminal row itself is missing)
        unavailable   no diagnostic record for this run
        contradicted  outcome mismatch / frozen sequence behind a persisted row /
                      send reported failed
    `contradicted` supersedes VALIDATED and is therefore never hidden;
  * `cause` stays "unknown". None of these labels say WHY.

Read-only. Writes nothing unless --out is passed.

Exit codes
  0  every session validated (evidence may be unavailable/partial)
  1  input error
  7  one or more sessions did not validate a terminal outcome
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

# Outcomes the Unity source can actually emit. Anything else is unknown
# semantics, not a validated terminal state.
KNOWN_OUTCOMES = {"completed", "calibration_completed", "edge_exit", "user_exit"}

VALIDATED = "TERMINAL_OUTCOME_VALIDATED"


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
        "run_ids": [], "terminal_evidence": "not_applicable",
        "cause": "unknown",
    }
    if not os.path.isfile(raw):
        out["verdict"] = "MISSING_CSV"
        return out

    run_ids: List[str] = []
    last_row: Optional[dict] = None
    outcome_anywhere = ""

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
                rid = (row.get("run_id") or "").strip()
                if rid and rid not in run_ids:
                    run_ids.append(rid)
                if (row.get("session_outcome") or "").strip():
                    outcome_anywhere = row["session_outcome"].strip()
                last_row = row
            elif src == "wii":
                out["wii_rows"] += 1
                if bts == bts:
                    out["last_wii_ts"] = bts

    out["run_ids"] = run_ids
    out["run_id"] = run_ids[-1] if run_ids else ""

    if out["unity_rows"] == 0 or last_row is None:
        out["verdict"] = "EMPTY"
        return out

    # The terminal row itself must carry BOTH fields.
    out["run_state"] = (last_row.get("run_state") or "").strip()
    out["session_outcome"] = (last_row.get("session_outcome") or "").strip()
    out["terminal_row_has_outcome"] = bool(out["session_outcome"])
    out["terminal_row_has_ended_state"] = out["run_state"].lower() == "ended"
    out["outcome_seen_on_any_row"] = outcome_anywhere or None

    if out["first_unity_ts"] is not None and out["last_unity_ts"] is not None:
        out["csv_span_s"] = round(out["last_unity_ts"] - out["first_unity_ts"], 3)

    both = out["last_unity_ts"] is not None and out["last_wii_ts"] is not None
    delta = abs(out["last_unity_ts"] - out["last_wii_ts"]) if both else None
    out["source_stop_delta_s"] = round(delta, 3) if delta is not None else None

    outcome = out["session_outcome"]
    ended = out["terminal_row_has_ended_state"]

    diag = diag_index.get(out["run_id"]) if out["run_id"] else None
    term_seq = None
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

    # ---- verdict -----------------------------------------------------------
    if len(run_ids) > 1:
        out["verdict"] = "MIXED_RUN"
        out["reason"] = "file contains %d run_ids; terminal row ownership is ambiguous" % len(run_ids)
        return out

    if not outcome:
        if delta is not None and delta <= SAME_INSTANT_S:
            out["verdict"] = "BOTH_STREAMS_CEASE_TOGETHER"
        elif both and out["last_unity_ts"] < out["last_wii_ts"]:
            out["verdict"] = "UNITY_CEASES_BEFORE_WII"
        elif both and out["last_wii_ts"] < out["last_unity_ts"]:
            out["verdict"] = "WII_CEASES_BEFORE_UNITY"
        else:
            out["verdict"] = "INCOMPLETE_NO_OUTCOME"
        if outcome_anywhere:
            out["outcome_not_on_terminal_row"] = outcome_anywhere
            out["reason"] = ("an outcome appears earlier in the file but the terminal row "
                             "carries none; the row is not a terminal state")
        return out

    if not ended:
        out["verdict"] = "OUTCOME_WITHOUT_ENDED_STATE"
        out["reason"] = "outcome %r on the terminal row but run_state=%r" % (outcome, out["run_state"])
        return out

    if outcome not in KNOWN_OUTCOMES:
        out["verdict"] = "OUTCOME_SEMANTICS_UNKNOWN"
        out["reason"] = "%r is not one of the outcomes the Unity source emits (%s)" % (
            outcome, ", ".join(sorted(KNOWN_OUTCOMES)))
        return out

    conflicts: List[str] = []
    if diag:
        if out.get("diag_terminal_outcome") and outcome != out["diag_terminal_outcome"]:
            conflicts.append("outcome_mismatch: csv=%r diag=%r"
                             % (outcome, out["diag_terminal_outcome"]))
        if isinstance(term_seq, int) and out["last_seq"] is not None and term_seq < out["last_seq"]:
            conflicts.append("terminal_snapshot_sequence_%d_behind_persisted_%d"
                             % (term_seq, out["last_seq"]))
        if diag.get("terminal_send_completed") is False:
            conflicts.append("diagnostic reports the terminal send call failed")
    if conflicts:
        out["verdict"] = "TERMINAL_OUTCOME_CONTRADICTED"
        out["terminal_evidence"] = "contradicted"
        out["conflicts"] = conflicts
        out["reason"] = "; ".join(conflicts)
        return out

    out["verdict"] = VALIDATED
    if not diag:
        out["terminal_evidence"] = "unavailable"
    elif isinstance(term_seq, int) and out["last_seq"] is not None and term_seq > out["last_seq"]:
        out["terminal_evidence"] = "partial"
    else:
        out["terminal_evidence"] = "corroborated"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Observational session closure audit (v5).")
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

    order = [VALIDATED, "TERMINAL_OUTCOME_CONTRADICTED", "OUTCOME_SEMANTICS_UNKNOWN",
             "MIXED_RUN", "OUTCOME_WITHOUT_ENDED_STATE", "BOTH_STREAMS_CEASE_TOGETHER",
             "UNITY_CEASES_BEFORE_WII", "WII_CEASES_BEFORE_UNITY",
             "INCOMPLETE_NO_OUTCOME", "EMPTY", "MISSING_CSV"]
    results.sort(key=lambda r: (order.index(r["verdict"]) if r["verdict"] in order else 99, r["session"]))

    print("=== Session closure audit (v5): %s ===" % args.root)
    print("%-34s %-31s %7s %7s %8s %9s %-13s" % ("session", "verdict", "unity", "wii",
                                                 "last_seq", "unpersist", "evidence"))
    for r in results:
        if args.only_problems and r["verdict"] == VALIDATED:
            continue
        print("%-34s %-31s %7d %7d %8s %9s %-13s" % (
            r["session"], r["verdict"], r["unity_rows"], r["wii_rows"],
            "-" if r["last_seq"] is None else r["last_seq"],
            r.get("unpersisted_sequence_span", "-"),
            r.get("terminal_evidence", "-")))

    counts: Dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\nsummary: %s" % json.dumps(counts, sort_keys=True))

    ev: Dict[str, int] = {}
    for r in results:
        if r["verdict"] == VALIDATED:
            ev[r["terminal_evidence"]] = ev.get(r["terminal_evidence"], 0) + 1
    if ev:
        print("evidence for validated sessions: %s" % json.dumps(ev, sort_keys=True))
        if ev.get("unavailable"):
            print("  unavailable = no diagnostic record for that run; validated on the CSV alone,")
            print("  which is weaker than corroborated and must be labelled as such in any report.")

    bad = [r for r in results if r["verdict"] != VALIDATED]
    if bad:
        print("\n%d session(s) did not validate a terminal outcome:" % len(bad))
        for r in bad:
            extra = ""
            if r.get("reason"):
                extra = " | %s" % r["reason"]
            elif r.get("unpersisted_sequence_span") is not None:
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
