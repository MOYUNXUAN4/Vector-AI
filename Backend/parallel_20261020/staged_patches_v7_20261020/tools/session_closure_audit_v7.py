#!/usr/bin/env python3
"""session_closure_audit_v7.py  (supersedes session_closure_audit_v6.py)

v7 defect found by the 2026-10-20 review of v6:
  * terminal-row identity was inherited. `last_seq` was updated for every row
    that carried a parseable sequence, and `run_id` was taken from the last row
    in the file that carried a non-empty one, so a final row with
    run_state=ended + outcome but a BLANK run_id and BLANK sequence was audited
    under the identity of the preceding `running` row. Fixture: row A
    (run_id=r1, seq=10, running) then row B (blank, blank, ended, edge_exit)
    with a diagnostic for r1 -> TERMINAL_OUTCOME_VALIDATED / corroborated.
    No row that was both identified and terminal had actually been persisted.
  * `int(float(seq))` silently truncated a fractional sequence ("10.7" -> 10)
    and raised an uncaught OverflowError on "inf", killing the whole audit.

v7:
  * identity for a validated session comes from the terminal row itself and
    from nowhere else: that exact row must carry a non-empty run_id and a
    strictly integer sequence (`[+-]?[0-9]+`, ASCII only). Missing, fractional,
    non-finite or otherwise unparseable values are `TERMINAL_ROW_IDENTITY_UNRESOLVED`
    with `identity_defect` = run_id_missing / sequence_missing /
    sequence_not_integer / run_id_and_sequence_missing;
  * `out["run_id"]` is the terminal row's run_id, never inherited;
  * `terminal_row_sequence` is the only sequence compared with the diagnostic
    frozen terminal; `last_seq` stays as a display-only "last parseable
    sequence anywhere in the file" and is labelled as such;
  * a sequence field that cannot be parsed as an integer is reported in
    `bad_sequences` instead of being truncated or crashing the run.

v6 (kept):
  * `corroborated` requires a `terminal_snapshot_frozen` record for the SAME
    run_id that carries a KNOWN outcome equal to the CSV outcome and an integer
    sequence no later than the last persisted CSV sequence;
  * a diagnostics entry without a frozen terminal is `unavailable` with
    `diag_terminal_absent: true`. Lifecycle bookkeeping is not corroboration;
  * a frozen terminal that lacks an outcome or a sequence, or whose sequence is
    ahead of the last persisted row, is `partial`;
  * `diag_send_state` is reported as completed / failed / unknown. An unknown
    send completion is NOT treated as a failure, and is NOT evidence either;
  * `--require-corroboration` turns `unavailable` / `partial` into a non-zero
    exit for anyone who wants a hard gate. Default stays descriptive.

Read-only. Writes nothing unless --out is passed.

Exit codes
  0  every session validated a terminal outcome (evidence may be unavailable/partial)
  1  input error
  7  one or more sessions did not validate a terminal outcome
  8  --require-corroboration and at least one validated session has evidence
     weaker than corroborated
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

SAME_INSTANT_S = 0.25

# Outcomes the Unity source can actually emit. Anything else is unknown
# semantics, not a validated terminal state.
KNOWN_OUTCOMES = {"completed", "calibration_completed", "edge_exit", "user_exit"}

VALIDATED = "TERMINAL_OUTCOME_VALIDATED"

# ASCII digits only: str.isdigit() and `\d` also accept non-ASCII decimal
# digits, and int() would then happily accept them.
_SEQ_RE = re.compile(r"[+-]?[0-9]+")


def parse_sequence(value: Any) -> Tuple[Optional[int], Optional[str]]:
    """Strict sequence parser.

    Returns (int_value, None) for a clean integer, otherwise (None, defect)
    where defect is "missing" or "not_integer". Deliberately does NOT route
    through float(): that truncates "10.7" to 10 and raises OverflowError on
    "inf". A sequence is an identity field, so a near-miss is a defect.
    """
    if value is None:
        return None, "missing"
    text = str(value).strip()
    if not text:
        return None, "missing"
    if not _SEQ_RE.fullmatch(text):
        return None, "not_integer"
    try:
        return int(text), None
    except ValueError:  # pragma: no cover - unreachable for a matching regex
        return None, "not_integer"


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
                e = index.setdefault(run_id, {"files": set(), "events": set()})
                e["files"].add(os.path.basename(path))
                ev = rec.get("lifecycle_event") or ""
                if ev:
                    e["events"].add(ev)
                if ev == "terminal_snapshot_frozen":
                    # The only record that can corroborate a terminal state.
                    e["terminal_present"] = True
                    e["terminal_seq"] = rec.get("sequence")
                    e["terminal_backend_ts"] = rec.get("backend_timestamp")
                    e["terminal_outcome"] = rec.get("session_outcome")
                elif ev == "terminal_udp_send_call_completed":
                    e["terminal_send_completed"] = True
                elif ev == "terminal_udp_send_call_failed":
                    e["terminal_send_completed"] = False
                ts = rec.get("unity_time")
                if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                    e["last_sample_ts"] = max(e.get("last_sample_ts", -1e18), ts)
    for e in index.values():
        e["files"] = sorted(e["files"])
        e["events"] = sorted(e["events"])
        e.setdefault("terminal_present", False)
    return index


def audit_session(session_dir: str, diag_index: Dict[str, Any]) -> Dict[str, Any]:
    raw = os.path.join(session_dir, "raw.csv")
    out: Dict[str, Any] = {
        "session": os.path.basename(session_dir.rstrip("/\\")),
        "raw_csv": raw,
        "unity_rows": 0, "wii_rows": 0,
        "first_unity_ts": None, "last_unity_ts": None, "last_wii_ts": None,
        "last_seq": None, "run_id": "", "run_state": "", "session_outcome": "",
        "terminal_row_run_id": "", "terminal_row_sequence": None,
        "terminal_row_sequence_defect": None, "identity_source": None,
        "run_ids": [], "terminal_evidence": "not_applicable",
        "cause": "unknown",
    }
    if not os.path.isfile(raw):
        out["verdict"] = "MISSING_CSV"
        return out

    run_ids: List[str] = []
    last_row: Optional[dict] = None
    outcome_anywhere = ""
    bad_sequences: List[dict] = []

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
                seq_value, seq_defect = parse_sequence(row.get("sequence"))
                if seq_value is not None:
                    out["last_seq"] = seq_value
                elif seq_defect == "not_integer" and len(bad_sequences) < 10:
                    bad_sequences.append({"row": out["unity_rows"],
                                          "sequence": (row.get("sequence") or "").strip()})
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
    if bad_sequences:
        out["bad_sequences"] = bad_sequences

    if out["unity_rows"] == 0 or last_row is None:
        out["verdict"] = "EMPTY"
        return out

    # ---- identity belongs to the terminal row and to no other row ----------
    terminal_run_id = (last_row.get("run_id") or "").strip()
    terminal_seq, terminal_seq_defect = parse_sequence(last_row.get("sequence"))
    out["terminal_row_run_id"] = terminal_run_id
    out["terminal_row_sequence"] = terminal_seq
    out["terminal_row_sequence_defect"] = terminal_seq_defect
    # No inheritance: an earlier row's run_id must never be used to identify
    # the terminal row.
    out["run_id"] = terminal_run_id

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
    terminal_present = False
    if diag:
        out["diag_files"] = diag.get("files", [])
        out["diag_events"] = diag.get("events", [])
        terminal_present = bool(diag.get("terminal_present"))
        out["diag_terminal_present"] = terminal_present
        out["diag_terminal_outcome"] = diag.get("terminal_outcome")
        send = diag.get("terminal_send_completed")
        out["diag_send_completed"] = send  # tri-state
        out["diag_send_state"] = ("completed" if send is True
                                  else "failed" if send is False else "unknown")
        term_seq = diag.get("terminal_seq")
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

    # v7: the terminal row must identify itself. An identity borrowed from the
    # previous row would let an unidentified last write pass as a persisted
    # same-run terminal state.
    identity_defect = None
    if not terminal_run_id and terminal_seq is None:
        identity_defect = "run_id_and_sequence_missing"
    elif not terminal_run_id:
        identity_defect = "run_id_missing"
    elif terminal_seq is None:
        identity_defect = ("sequence_missing" if terminal_seq_defect == "missing"
                           else "sequence_not_integer")
    if identity_defect:
        out["verdict"] = "TERMINAL_ROW_IDENTITY_UNRESOLVED"
        out["identity_defect"] = identity_defect
        out["identity_source"] = "terminal_row"
        out["terminal_evidence"] = "unavailable"
        out["evidence_reason"] = (
            "the terminal row carries outcome %r with run_state=ended but no usable %s; "
            "identity is never inherited from an earlier row, so no same-run persisted "
            "terminal state is established" % (
                outcome,
                "run_id and no integer sequence" if identity_defect == "run_id_and_sequence_missing"
                else "run_id" if identity_defect == "run_id_missing"
                else "integer sequence"))
        out["reason"] = "terminal row identity unresolved (%s)" % identity_defect
        return out
    out["identity_source"] = "terminal_row"

    if term_seq is not None and terminal_seq is not None:
        out["unpersisted_sequence_span"] = term_seq - terminal_seq
        out["unpersisted_span_meaning"] = (
            "terminal_snapshot sequence minus the TERMINAL ROW's own sequence; "
            "an unpersisted span, not a per-packet delivery record and not network proof"
        )

    conflicts: List[str] = []
    if diag and terminal_present:
        if out.get("diag_terminal_outcome") and outcome != out["diag_terminal_outcome"]:
            conflicts.append("outcome_mismatch: csv=%r diag=%r"
                             % (outcome, out["diag_terminal_outcome"]))
        if isinstance(term_seq, int) and term_seq < terminal_seq:
            conflicts.append("terminal_snapshot_sequence_%d_behind_persisted_%d"
                             % (term_seq, terminal_seq))
    if diag and diag.get("terminal_send_completed") is False:
        conflicts.append("diagnostic reports the terminal send call failed")
    if conflicts:
        out["verdict"] = "TERMINAL_OUTCOME_CONTRADICTED"
        out["terminal_evidence"] = "contradicted"
        out["conflicts"] = conflicts
        out["reason"] = "; ".join(conflicts)
        return out

    out["verdict"] = VALIDATED
    # Evidence strength: the CSV alone is a weaker status than a same-run frozen
    # terminal. Only the latter may be called corroborated.
    if not diag:
        out["terminal_evidence"] = "unavailable"
        out["evidence_reason"] = "no diagnostic record for this run"
    elif not terminal_present:
        out["terminal_evidence"] = "unavailable"
        out["diag_terminal_absent"] = True
        out["evidence_reason"] = ("a diagnostic entry exists but it contains no "
                                  "terminal_snapshot_frozen record for this run; "
                                  "lifecycle bookkeeping is not corroboration")
    elif not out.get("diag_terminal_outcome") or not isinstance(term_seq, int):
        out["terminal_evidence"] = "partial"
        out["evidence_reason"] = ("frozen terminal record lacks "
                                  "%s" % ("an outcome" if not out.get("diag_terminal_outcome")
                                          else "an integer sequence"))
    elif term_seq > terminal_seq:
        out["terminal_evidence"] = "partial"
        out["evidence_reason"] = ("frozen terminal sequence %d is ahead of the terminal "
                                  "row's own sequence %d; the terminal row itself was not persisted"
                                  % (term_seq, terminal_seq))
    else:
        out["terminal_evidence"] = "corroborated"
        out["evidence_reason"] = ("same run_id on the terminal row, frozen terminal outcome %r "
                                  "at sequence %s, not later than the terminal row's own sequence %d"
                                  % (outcome, term_seq, terminal_seq))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Observational session closure audit (v7).")
    ap.add_argument("--root", required=True)
    ap.add_argument("--diag-dir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--only-problems", action="store_true")
    ap.add_argument("--require-corroboration", action="store_true",
                    help="exit 8 when a validated session is only unavailable/partial")
    args = ap.parse_args()

    sessions = sorted(glob.glob(os.path.join(args.root, "session_*")))
    if not sessions:
        print("no session_* under %s" % args.root, file=sys.stderr)
        return 1

    diag_index = index_diagnostics(args.diag_dir)
    results = [audit_session(s, diag_index) for s in sessions]

    order = [VALIDATED, "TERMINAL_OUTCOME_CONTRADICTED", "TERMINAL_ROW_IDENTITY_UNRESOLVED",
             "OUTCOME_SEMANTICS_UNKNOWN", "MIXED_RUN", "OUTCOME_WITHOUT_ENDED_STATE",
             "BOTH_STREAMS_CEASE_TOGETHER", "UNITY_CEASES_BEFORE_WII",
             "WII_CEASES_BEFORE_UNITY", "INCOMPLETE_NO_OUTCOME", "EMPTY", "MISSING_CSV"]
    results.sort(key=lambda r: (order.index(r["verdict"]) if r["verdict"] in order else 99, r["session"]))

    print("=== Session closure audit (v7): %s ===" % args.root)
    print("%-34s %-31s %7s %7s %9s %9s %-13s %-10s" % ("session", "verdict", "unity", "wii",
                                                        "term_seq", "unpersist", "evidence", "send"))
    for r in results:
        if args.only_problems and r["verdict"] == VALIDATED and r["terminal_evidence"] == "corroborated":
            continue
        print("%-34s %-31s %7d %7d %9s %9s %-13s %-10s" % (
            r["session"], r["verdict"], r["unity_rows"], r["wii_rows"],
            "-" if r.get("terminal_row_sequence") is None else r["terminal_row_sequence"],
            r.get("unpersisted_sequence_span", "-"),
            r.get("terminal_evidence", "-"),
            r.get("diag_send_state", "-")))

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
            print("  unavailable = no frozen terminal record for that run; validated on the")
            print("  CSV alone, which is weaker than corroborated and must be labelled as such.")
        if ev.get("partial"):
            print("  partial = a frozen terminal record exists but does not line up with the")
            print("  persisted rows; the terminal row itself may be missing.")

    bad = [r for r in results if r["verdict"] != VALIDATED]
    if bad:
        print("\n%d session(s) did not validate a terminal outcome:" % len(bad))
        for r in bad:
            extra = ""
            if r.get("reason"):
                extra = " | %s" % r["reason"]
            elif r.get("unpersisted_sequence_span") is not None:
                extra = " | unpersisted seq span %d, send=%s" % (
                    r["unpersisted_sequence_span"], r.get("diag_send_state"))
            print("  - %s: %s%s" % (r["session"], r["verdict"], extra))
        print("  cause is unknown for all of the above; these labels describe what the")
        print("  files show, not why it happened.")

    weak = [r for r in results if r["verdict"] == VALIDATED and r["terminal_evidence"] != "corroborated"]
    if weak:
        print("\n%d validated session(s) rest on weaker than corroborated evidence:" % len(weak))
        for r in weak:
            print("  - %s: %s | %s" % (r["session"], r["terminal_evidence"], r.get("evidence_reason", "")))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"root": args.root, "diag_dir": args.diag_dir,
                       "counts": counts, "sessions": results}, fh, indent=2,
                      ensure_ascii=False, allow_nan=False)
        print("\nwritten: %s" % args.out)

    if bad:
        return 7
    if args.require_corroboration and weak:
        return 8
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
