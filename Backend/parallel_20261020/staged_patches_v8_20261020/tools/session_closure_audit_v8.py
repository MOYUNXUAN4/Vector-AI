#!/usr/bin/env python3
"""session_closure_audit_v8.py  (supersedes session_closure_audit_v7.py)

v8 defect found by the 2026-10-20 review of v7:
  * the DIAGNOSTIC sequence was used as if it were an integer without ever
    being checked. `index_diagnostics` copied `sequence` out of the JSONL
    verbatim, and `audit_session` subtracted it from the CSV terminal sequence
    before any type test. A JSON string ("10", "bad") raised an uncaught
    TypeError and killed the whole multi-session run; `10.5` and `None` were
    silently tolerated. Only the CSV-side sequence had been hardened in v7.
  * one raising session aborted the run, so a bulk audit could not report the
    malformed session and still describe the others.

v8:
  * `parse_diag_sequence` is type-strict and runs at INDEX time, before any
    comparison. Only a JSON integer is an identity. bool (a subclass of int in
    Python), strings, fractional floats, integral floats, NaN/Infinity, lists
    and dicts are defects: boolean / string / fractional / float_typed /
    non_finite / not_integer. Nothing is coerced, so "10" never becomes 10.
  * `diag_terminal_sequence_defect` and `diag_terminal_sequence_json_type` are
    reported per session. A frozen terminal with a malformed sequence is
    `partial`, never `corroborated`.
  * the frozen terminal's outcome must be a JSON string before it is compared
    with the CSV outcome; a non-string outcome is `partial`, not a contradiction.
  * `terminal_backend_ts` must be a finite number (bool excluded) before the
    tail-silence subtraction.
  * `main` audits each session inside its own try/except: a session the auditor
    cannot parse becomes `AUDIT_ERROR` with the exception type and message, and
    the remaining sessions are still audited. Exit 7 either way.
  * `AUDIT_ERROR` is a problem verdict, not a silent skip.

v7 (kept):
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
  7  one or more sessions did not validate a terminal outcome, or the auditor
     raised on a session (AUDIT_ERROR)
  8  --require-corroboration and at least one validated session has evidence
     weaker than corroborated
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
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
    """Strict CSV sequence parser.

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


def json_type_name(value: Any) -> str:
    """JSON-ish type label, for reports only. bool is named before int."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def parse_diag_sequence(value: Any) -> Tuple[Optional[int], Optional[str]]:
    """Type-strict diagnostic sequence parser.

    A JSON integer is the only accepted identity. Everything else is a defect
    and is NEVER coerced:

      missing      null / absent
      boolean      true / false  (bool is an int subclass in Python)
      string       "10", "bad"   (a quoted number is not a number)
      fractional   10.5
      float_typed  10.0          (integral, still not an integer)
      non_finite   NaN / Infinity
      not_integer  array / object / anything else
    """
    if value is None:
        return None, "missing"
    if isinstance(value, bool):
        return None, "boolean"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None, "non_finite"
        if not value.is_integer():
            return None, "fractional"
        return None, "float_typed"
    if isinstance(value, str):
        return None, "string"
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
                    e["terminal_records"] = e.get("terminal_records", 0) + 1
                    e["terminal_seq_raw"] = rec.get("sequence")
                    seq, defect = parse_diag_sequence(rec.get("sequence"))
                    e["terminal_seq"] = seq
                    e["terminal_seq_defect"] = defect
                    e["terminal_seq_type"] = json_type_name(rec.get("sequence"))
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
        e.setdefault("terminal_seq", None)
        e.setdefault("terminal_seq_defect", "missing")
        e.setdefault("terminal_seq_type", "null")
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
        # v8: the diagnostic sequence was validated at INDEX time. It is an int
        # or it is None with a named defect; it is never subtracted otherwise.
        term_seq = diag.get("terminal_seq")
        seq_defect = diag.get("terminal_seq_defect")
        out["diag_terminal_sequence"] = term_seq
        out["diag_terminal_sequence_defect"] = seq_defect
        out["diag_terminal_sequence_json_type"] = diag.get("terminal_seq_type")
        out["diag_terminal_records"] = diag.get("terminal_records", 0)
        if terminal_present and seq_defect:
            out["diag_terminal_sequence_malformed"] = True
        term_ts = diag.get("terminal_backend_ts")
        if (isinstance(term_ts, (int, float)) and not isinstance(term_ts, bool)
                and math.isfinite(term_ts) and out["last_unity_ts"] is not None):
            out["tail_silence_s"] = round(term_ts - out["last_unity_ts"], 3)
        if outcome and isinstance(out.get("diag_terminal_outcome"), str):
            out["outcome_match"] = (outcome == out["diag_terminal_outcome"])
        elif outcome:
            out["outcome_match"] = None

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
        diag_outcome = out.get("diag_terminal_outcome")
        if isinstance(diag_outcome, str) and diag_outcome and outcome != diag_outcome:
            conflicts.append("outcome_mismatch: csv=%r diag=%r" % (outcome, diag_outcome))
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
    diag_outcome = out.get("diag_terminal_outcome")
    seq_type = out.get("diag_terminal_sequence_json_type")
    seq_defect = out.get("diag_terminal_sequence_defect")
    if not diag:
        out["terminal_evidence"] = "unavailable"
        out["evidence_reason"] = "no diagnostic record for this run"
    elif not terminal_present:
        out["terminal_evidence"] = "unavailable"
        out["diag_terminal_absent"] = True
        out["evidence_reason"] = ("a diagnostic entry exists but it contains no "
                                  "terminal_snapshot_frozen record for this run; "
                                  "lifecycle bookkeeping is not corroboration")
    elif not isinstance(diag_outcome, str) or not diag_outcome:
        out["terminal_evidence"] = "partial"
        out["evidence_reason"] = ("frozen terminal record has no usable outcome "
                                  "(JSON type %s); a malformed identity is not coerced"
                                  % json_type_name(diag_outcome))
    elif term_seq is None:
        out["terminal_evidence"] = "partial"
        out["evidence_reason"] = ("frozen terminal record's sequence is not a JSON integer "
                                  "(%s, JSON type %s); a malformed identity is not coerced, "
                                  "so it cannot corroborate the persisted terminal row"
                                  % (seq_defect, seq_type))
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
    ap = argparse.ArgumentParser(description="Observational session closure audit (v8).")
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

    # v8: one unreadable session must not abort the run. The exception is
    # reported against that session and the rest are still audited.
    results: List[Dict[str, Any]] = []
    for session in sessions:
        try:
            results.append(audit_session(session, diag_index))
        except Exception as exc:  # noqa: BLE001 - deliberate per-session isolation
            results.append({
                "session": os.path.basename(session.rstrip("/\\")),
                "raw_csv": os.path.join(session, "raw.csv"),
                "unity_rows": 0, "wii_rows": 0,
                "verdict": "AUDIT_ERROR",
                "terminal_evidence": "invalid",
                "audit_error": "%s: %s" % (type(exc).__name__, exc),
                "reason": ("the auditor raised on this session (%s); the remaining sessions "
                           "were still audited" % type(exc).__name__),
            })

    order = [VALIDATED, "TERMINAL_OUTCOME_CONTRADICTED", "TERMINAL_ROW_IDENTITY_UNRESOLVED",
             "OUTCOME_SEMANTICS_UNKNOWN", "MIXED_RUN", "OUTCOME_WITHOUT_ENDED_STATE",
             "AUDIT_ERROR", "BOTH_STREAMS_CEASE_TOGETHER", "UNITY_CEASES_BEFORE_WII",
             "WII_CEASES_BEFORE_UNITY", "INCOMPLETE_NO_OUTCOME", "EMPTY", "MISSING_CSV"]
    results.sort(key=lambda r: (order.index(r["verdict"]) if r["verdict"] in order else 99, r["session"]))

    print("=== Session closure audit (v8): %s ===" % args.root)
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
            print("  persisted rows, or the record is malformed; it cannot corroborate.")

    malformed = [r for r in results if r.get("diag_terminal_sequence_malformed")]
    if malformed:
        print("\n%d session(s) have a malformed diagnostic terminal sequence:" % len(malformed))
        for r in malformed:
            print("  - %s: %s (%s)" % (r["session"], r.get("diag_terminal_sequence_defect"),
                                       r.get("diag_terminal_sequence_json_type")))

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
