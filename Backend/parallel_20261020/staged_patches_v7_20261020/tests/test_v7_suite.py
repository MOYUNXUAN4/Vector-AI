#!/usr/bin/env python3
"""test_v7_suite.py — adversarial regression suite for the v7 offline tools.

Three groups of fixtures:

  * the v4 counterexamples that v5 fixed (kept so a v5 fix cannot silently
    regress). The board fixtures now carry a real Wii source clock
    (`wii_control_timestamp`) and `wii_control_sequence`, because v6 refuses to
    establish source continuity from receive time.
  * the three v5 boundaries named in the 2026-10-20 review of v5:
      A. source-clock continuity (1020 ms source gap with 1 ms receive spacing;
         non-finite timestamps; sequence skips/reversals; receive-only file)
      B. closure corroboration (a diagnostics entry without a frozen terminal)
      C. receipt commit / recovery (exercised in test_ps_lifecycle.ps1)
  * the two v6 boundaries named in the 2026-10-20 review of v6:
      D. terminal-row identity is never inherited from an earlier row; missing,
         fractional and non-finite sequences are identity defects, not values
      E. pending recovery must verify the rollback record and the backup bytes
         before committing (exercised in test_ps_lifecycle.ps1, T15/T16)

Run:  python tests/test_v7_suite.py
Exit: 0 all passed, 1 failures
"""

from __future__ import annotations

import csv
import datetime
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.dirname(os.path.dirname(ROOT))  # .../fyp_Backend


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


w6 = load("v7_wii", "patch_5_wii_preflight/wii_cop_preflight_v6.py")
c7 = load("v7_closure", "tools/session_closure_audit_v7.py")
p5 = load("v7_profile", "patch_4_clock_profile/receive_latency_profile_v5.py")
e5 = load("v7_episodes", "patch_3_warning_episodes/cluster_warning_episodes_v5.py")

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print("[%s] %-62s %s" % ("PASS" if ok else "FAIL", name, detail))


def write_csv(path: str, rows):
    fields = sorted(set().union(*(r.keys() for r in rows)))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()


BASE = 1_700_000_000.0


# ---------------------------------------------------------------------------
# patch 5: board evidence on a declared source clock
# ---------------------------------------------------------------------------
def wii_row(i, step=0.05, **kw):
    """One wii row with a real board clock, a record clock and a sequence."""
    base = {
        "source": "wii",
        "wii_control_timestamp": iso(BASE + i * step),
        "source_timestamp": iso(BASE + i * step),
        "backend_timestamp": "%.4f" % (100.0 + i * step),
        "wii_control_sequence": str(1000 + i),
        "total_weight": "80.0",
        "cop_x": "0.0",
        "cop_z": "0.0",
        "wii_control_valid": "true",
        "wii_board_loaded": "true",
        "wii_center_applied": "true",
        "wii_control_age_seconds": "0.01",
        "wii_center_generation": "1",
        "wii_controller_instance_id": "board-a",
    }
    base.update(kw)
    return base


def test_wii(tmp: str) -> None:
    path = os.path.join(tmp, "wii.csv")

    # --- v5 regressions ----------------------------------------------------
    rows = [dict(source="wii", wii_control_timestamp=iso(BASE + i * 0.05),
                 wii_control_sequence=str(i), backend_timestamp=str(100 + i * 0.05),
                 total_weight="80", cop_x="0", cop_z="0") for i in range(60)]
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: missing board flags are not OK", r["verdict"] == "UNKNOWN_EVIDENCE", r["verdict"])
    check("wii: missing flag columns reported",
          not r["evidence"]["complete"] and "wii_board_loaded" in r["evidence"]["missing_columns"])

    rows = [wii_row(i) for i in range(60)]
    for i, row in enumerate(rows):
        row["wii_control_timestamp"] = iso(BASE - i * 0.05)
        row["source_timestamp"] = iso(BASE - i * 0.05)
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: reversed source clock is not OK", r["verdict"] != "OK", r["verdict"])
    dur = r.get("window_duration_s")
    check("wii: no negative window duration", dur is None or dur > 0, str(dur))

    rows = [wii_row(i) for i in range(60)]
    for row in rows:
        row.pop("wii_control_age_seconds")
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: missing age column is UNKNOWN", r["verdict"] == "UNKNOWN_EVIDENCE", r["verdict"])

    rows = [wii_row(i, wii_center_generation="", wii_controller_instance_id="") for i in range(60)]
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: empty identity is not OK", r["verdict"] != "OK", r["verdict"])

    rows = [wii_row(i) for i in range(120)]
    rows[40]["total_weight"] = ""
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: invalid row is a barrier, not bridged",
          r["verdict"] == "OK" and r.get("window_start_index", 0) > 40,
          "%s at %s" % (r["verdict"], r.get("window_start_index")))

    rows = [wii_row(i, wii_board_loaded="false", wii_center_applied="false") for i in range(80)]
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: explicit false flags are not OK", r["verdict"] != "OK", r["verdict"])

    # --- boundary A: source clock is the evidence --------------------------
    # 1020 ms hole in the board's own clock while backend receive spacing stays
    # at 1 ms. v5 scored this OK; v6 must reject it.
    rows = []
    for i in range(50):
        t = BASE + i * 0.02 + (1.020 if i >= 25 else 0.0)
        rows.append(wii_row(i, wii_control_timestamp=iso(t), source_timestamp=iso(t),
                            backend_timestamp="%.4f" % (1_700_000_002.0 + i * 0.001)))
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: 1020 ms SOURCE gap with 1 ms receive spacing is not OK",
          r["verdict"] != "OK", "%s %s" % (r["verdict"], r.get("reason")))
    check("wii: the source gap is named as the blocker",
          "gap" in (r.get("reason") or ""), r.get("reason"))
    check("wii: receive timing is reported separately, not as the evidence",
          r.get("time_domain") == "board_control" and r["source_continuity_verified"] is False,
          "%s/%s" % (r.get("time_domain"), r.get("source_continuity_verified")))

    # non-finite timestamps must never serialise as accepted evidence
    rows = [wii_row(i) for i in range(50)]
    for row in rows:
        row["backend_timestamp"] = "inf"
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: infinite timestamps are UNKNOWN_EVIDENCE, not OK",
          r["verdict"] == "UNKNOWN_EVIDENCE", r["verdict"])
    check("wii: the non-finite value is recorded",
          r["evidence"]["nonfinite_count"] > 0 and r["source_continuity_verified"] is False,
          str(r["evidence"]["nonfinite_count"]))
    try:
        json.dumps(r, allow_nan=False)
        serialisable = True
    except ValueError:
        serialisable = False
    check("wii: result serialises without a NaN/Infinity literal", serialisable)

    # receive-only file: continuity of the board cannot be established at all
    rows = [dict(source="wii", backend_timestamp="%.4f" % (100 + i * 0.02),
                 total_weight="80", cop_x="0", cop_z="0",
                 wii_control_valid="true", wii_board_loaded="true",
                 wii_center_applied="true", wii_control_age_seconds="0.01",
                 wii_center_generation="1", wii_controller_instance_id="board-a",
                 wii_control_sequence=str(1000 + i)) for i in range(60)]
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: receive-only file is SOURCE_CLOCK_UNAVAILABLE, never OK",
          r["verdict"] == "SOURCE_CLOCK_UNAVAILABLE", r["verdict"])
    check("wii: receive-only file refuses to claim source continuity",
          r["source_continuity_verified"] is False and r["clock_is_source"] is False)

    # a skipped control sequence with a perfectly flat clock
    rows = [wii_row(i) for i in range(60)]
    rows[30]["wii_control_sequence"] = str(1000 + 30 + 5)
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: sequence skip with a flat clock is not OK", r["verdict"] != "OK", r["verdict"])
    check("wii: the sequence gap is named as the blocker",
          "sequence" in (r.get("reason") or ""), r.get("reason"))

    rows = [wii_row(i) for i in range(60)]
    rows[30]["wii_control_sequence"] = str(1000 + 30 - 10)
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: sequence reversal is not OK", r["verdict"] != "OK", r["verdict"])

    # the logger writes the same control sample onto several rows; that is not
    # a gap, and it must not be counted as source progress either
    rows = [wii_row(i // 2) for i in range(60)]
    write_csv(path, rows)
    r = w6.audit(path)
    check("wii: duplicated control samples still pass", r["verdict"] == "OK", r["verdict"])
    check("wii: duplicated samples are collapsed in the duration",
          r.get("window_unique_samples", 99) < 50, str(r.get("window_unique_samples")))
    check("wii: source clock reported in the window output",
          r.get("time_domain") == "board_control" and r.get("window_sequence_last") is not None,
          "%s seq=%s" % (r.get("time_domain"), r.get("window_sequence_last")))

    # CLI settings are validated, and cannot smuggle a non-finite threshold
    try:
        w6._finite_arg("--max-gap", float("inf"), 1e-9, 3600.0)
        guarded = False
    except ValueError:
        guarded = True
    check("wii: non-finite CLI setting is rejected", guarded)

    # --- real sessions ------------------------------------------------------
    real = os.path.join(BACKEND, "telemetry_logs/P01/session_20261019_105632_058608/raw.csv")
    if os.path.isfile(real):
        r = w6.audit(real)
        check("wii: real loaded session still OK", r["verdict"] == "OK", r["verdict"])
        check("wii: real session uses the board clock",
              r.get("time_domain") == "board_control", str(r.get("time_domain")))
        check("wii: real session evidence complete", r["evidence"]["complete"] is True)
    real = os.path.join(BACKEND, "telemetry_logs/P01/session_20261019_161529_760840/raw.csv")
    if os.path.isfile(real):
        r = w6.audit(real)
        check("wii: empty-board session is INSUFFICIENT_LOAD", r["verdict"] == "INSUFFICIENT_LOAD",
              r["verdict"])


# ---------------------------------------------------------------------------
# patch 4: global-offset sufficiency (unchanged tool, kept as a guard)
# ---------------------------------------------------------------------------
def test_profile(tmp: str) -> None:
    base = 1_700_000_000.0
    src = [base + i * 0.02 for i in range(240)]
    geom_drift = [i * 0.02 - i * 0.001 for i in range(240)]
    r = p5.analyse_arrays(src, [t + 0.005 for t in src], geom_drift)
    d = r["unity_dual_clock_stats"]
    check("p4: 239 ms gradual drift is insufficient",
          d["global_offset_verdict"] == "insufficient", d["global_offset_verdict"])
    check("p4: gradual drift is measured, not just jumps",
          abs(d["detrended_spread_ms"] - 239.0) < 5 and d["discrete_jump_count"] == 0,
          "spread %.1f jumps %d" % (d["detrended_spread_ms"], d["discrete_jump_count"]))
    check("p4: sufficient flag is False, not True",
          d["single_global_offset_sufficient"] is False, str(d["single_global_offset_sufficient"]))

    src_s = src[:60]
    r = p5.analyse_arrays(src_s, [t + 0.005 for t in src_s], [i * 0.02 for i in range(60)])
    d = r["unity_dual_clock_stats"]
    check("p4: too few paired samples is unknown, not sufficient",
          d["global_offset_verdict"] == "unknown" and d["single_global_offset_sufficient"] is None,
          d["global_offset_verdict"])

    r = p5.analyse_arrays(src, [t + 0.005 for t in src], [i * 0.02 for i in range(240)])
    d = r["unity_dual_clock_stats"]
    check("p4: constant offset alone is sufficient",
          d["global_offset_verdict"] == "sufficient", d["global_offset_verdict"])

    geom_jump = [i * 0.02 for i in range(240)]
    for i in range(150, 240):
        geom_jump[i] -= 0.150
    r = p5.analyse_arrays(src, [t + 0.005 for t in src], geom_jump)
    d = r["unity_dual_clock_stats"]
    check("p4: single jump is insufficient", d["global_offset_verdict"] == "insufficient",
          d["global_offset_verdict"])

    path = os.path.join(tmp, "jump.csv")
    rows = [dict(source="unity",
                 source_timestamp="%.4f" % (src[i]),
                 backend_timestamp="%.4f" % (src[i] + 0.005),
                 geometry_source_timestamp="%.4f" % geom_jump[i]) for i in range(240)]
    write_csv(path, rows)
    r = p5.analyse(path)
    d = r["unity_dual_clock_stats"]
    check("p4: jumps carry a physical csv_line",
          bool(d["discrete_jumps"]) and d["discrete_jumps"][0]["csv_line"] > 1,
          str(d["discrete_jumps"][0]["csv_line"] if d["discrete_jumps"] else None))

    check("p4: self-test exits 0", p5.self_test() == 0)

    real = os.path.join(BACKEND, "telemetry_logs/P01/session_20261019_161529_760840/raw.csv")
    if os.path.isfile(real):
        r = p5.analyse(real)
        d = r["unity_dual_clock_stats"]
        check("p4: real 16:15 session reports 6 staircase jumps",
              d["discrete_jump_count"] == 6 and abs(d["cumulative_jump_ms"] - 948.8) < 1.0,
              "jumps=%d sum=%.1f" % (d["discrete_jump_count"], d["cumulative_jump_ms"]))
        check("p4: real 16:15 session offset claim is insufficient",
              d["global_offset_verdict"] == "insufficient", d["global_offset_verdict"])


# ---------------------------------------------------------------------------
# closure audit: corroboration needs a frozen terminal record
# ---------------------------------------------------------------------------
def test_closure(tmp: str) -> None:
    diag_dir = os.path.join(tmp, "diag")
    os.makedirs(diag_dir, exist_ok=True)
    csv_rows = [dict(source="unity", backend_timestamp="100", sequence="10",
                     run_id="r1", run_state="ended", session_outcome="edge_exit")]

    def audit(rows, records):
        """Write real diagnostic JSONL records, then run the real indexer."""
        for old in os.listdir(diag_dir):
            os.remove(os.path.join(diag_dir, old))
        with open(os.path.join(diag_dir, "samples_fixture.jsonl"), "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(dict(schema_version="endless_falling_geometry_diag_v1",
                                         record_type="lifecycle", **rec)) + "\n")
        d = os.path.join(tmp, "session_fixture")
        os.makedirs(d, exist_ok=True)
        write_csv(os.path.join(d, "raw.csv"), rows)
        return c7.audit_session(d, c7.index_diagnostics(diag_dir))

    def frozen(seq, outcome, run_id="r1", **kw):
        rec = dict(lifecycle_event="terminal_snapshot_frozen", run_id=run_id,
                   unity_time=65.0, backend_timestamp=100.0, sequence=seq,
                   session_outcome=outcome)
        rec.update(kw)
        return rec

    def sent(run_id="r1", ok=True):
        return dict(lifecycle_event=("terminal_udp_send_call_completed" if ok
                                     else "terminal_udp_send_call_failed"),
                    run_id=run_id, unity_time=66.0)

    r = audit(csv_rows, [frozen(20, "user_exit"), sent()])
    check("closure: contradiction is not VALIDATED",
          r["verdict"] == "TERMINAL_OUTCOME_CONTRADICTED", r["verdict"])
    check("closure: contradiction names the conflict",
          bool(r.get("conflicts")) and r["outcome_match"] is False, str(r.get("conflicts")))

    r = audit(csv_rows, [frozen(10, "edge_exit"), sent()])
    check("closure: frozen terminal corroborates",
          r["verdict"] == c7.VALIDATED and r["terminal_evidence"] == "corroborated",
          "%s/%s" % (r["verdict"], r["terminal_evidence"]))
    check("closure: send state is reported as completed", r["diag_send_state"] == "completed",
          r.get("diag_send_state"))

    r = audit(csv_rows, [])
    check("closure: no diagnostics is unavailable, not corroborated",
          r["verdict"] == c7.VALIDATED and r["terminal_evidence"] == "unavailable",
          "%s/%s" % (r["verdict"], r["terminal_evidence"]))

    # --- boundary B --------------------------------------------------------
    r = audit(csv_rows, [dict(lifecycle_event="new_run_created", run_id="r1",
                              unity_time=1.0, sequence=1)])
    check("closure: lifecycle-only diag entry is unavailable, not corroborated",
          r["terminal_evidence"] == "unavailable", r["terminal_evidence"])
    check("closure: missing frozen terminal is named",
          r.get("diag_terminal_absent") is True and bool(r.get("evidence_reason")),
          str(r.get("evidence_reason")))

    r = audit(csv_rows, [dict(lifecycle_event="new_run_created", run_id="r1", unity_time=1.0),
                         dict(lifecycle_event="restart_requested", run_id="r1", unity_time=2.0)])
    check("closure: bookkeeping records never corroborate",
          r["terminal_evidence"] != "corroborated", r["terminal_evidence"])

    # a frozen terminal belonging to another run must not leak into this one
    r = audit(csv_rows, [frozen(10, "edge_exit", run_id="other-run"), sent("other-run")])
    check("closure: another run's frozen terminal does not corroborate",
          r["terminal_evidence"] == "unavailable", r["terminal_evidence"])

    r = audit(csv_rows, [frozen(12, "edge_exit"), sent()])
    check("closure: terminal row not persisted is partial",
          r["terminal_evidence"] == "partial", r["terminal_evidence"])
    check("closure: partial evidence is explained",
          "ahead of the terminal row" in (r.get("evidence_reason") or ""), r.get("evidence_reason"))

    r = audit(csv_rows, [dict(lifecycle_event="terminal_snapshot_frozen", run_id="r1",
                              unity_time=65.0, session_outcome="edge_exit")])
    check("closure: frozen terminal without a sequence is partial",
          r["terminal_evidence"] == "partial", r["terminal_evidence"])

    r = audit(csv_rows, [dict(lifecycle_event="terminal_snapshot_frozen", run_id="r1",
                              unity_time=65.0, sequence=10)])
    check("closure: frozen terminal without an outcome is partial",
          r["terminal_evidence"] == "partial", r["terminal_evidence"])

    r = audit(csv_rows, [frozen(10, "edge_exit")])
    check("closure: unknown send state is reported, not treated as failed",
          r["verdict"] == c7.VALIDATED and r["diag_send_state"] == "unknown",
          "%s/%s" % (r["verdict"], r.get("diag_send_state")))
    check("closure: unknown send state still corroborates",
          r["terminal_evidence"] == "corroborated", r["terminal_evidence"])

    r = audit(csv_rows, [frozen(10, "edge_exit"), sent(ok=False)])
    check("closure: failed send is a contradiction",
          r["verdict"] == "TERMINAL_OUTCOME_CONTRADICTED", r["verdict"])

    base = dict(csv_rows[0])
    r = audit([dict(base, session_outcome="aborted")], [])
    check("closure: unknown outcome semantics rejected",
          r["verdict"] == "OUTCOME_SEMANTICS_UNKNOWN", r["verdict"])

    r = audit([base, dict(base, run_id="r2", sequence="11")], [])
    check("closure: mixed run is not validated", r["verdict"] == "MIXED_RUN", r["verdict"])

    r = audit([base, dict(source="unity", backend_timestamp="100.02", sequence="11",
                          run_id="r1", run_state="running", session_outcome="")], [])
    check("closure: outcome must be on the terminal row",
          r["verdict"] == "INCOMPLETE_NO_OUTCOME", r["verdict"])

    # --- boundary D: the terminal row must identify itself ------------------
    # The 2026-10-20 review of v6 fixture: a running row with identity, then a
    # final row with outcome + ended but blank run_id AND blank sequence.
    running = dict(source="unity", backend_timestamp="100", sequence="10",
                   run_id="r1", run_state="running", session_outcome="")
    final_blank = dict(source="unity", backend_timestamp="100.02", sequence="",
                       run_id="", run_state="ended", session_outcome="edge_exit")

    r = audit([running, final_blank], [frozen(10, "edge_exit"), sent()])
    check("closure D: review fixture no longer validates",
          r["verdict"] != c7.VALIDATED, r["verdict"])
    check("closure D: review fixture no longer corroborates",
          r["verdict"] == "TERMINAL_ROW_IDENTITY_UNRESOLVED"
          and r["terminal_evidence"] != "corroborated",
          "%s/%s" % (r["verdict"], r.get("terminal_evidence")))
    check("closure D: run_id is not taken from the running row", r["run_id"] == "",
          repr(r["run_id"]))
    check("closure D: combined defect is named",
          r.get("identity_defect") == "run_id_and_sequence_missing", str(r.get("identity_defect")))
    check("closure D: no unpersisted span is computed from an inherited sequence",
          r.get("unpersisted_sequence_span") is None, str(r.get("unpersisted_sequence_span")))

    r = audit([running, dict(final_blank, sequence="11")], [frozen(10, "edge_exit"), sent()])
    check("closure D: blank run_id alone is unresolved",
          r["verdict"] == "TERMINAL_ROW_IDENTITY_UNRESOLVED"
          and r.get("identity_defect") == "run_id_missing",
          "%s/%s" % (r["verdict"], r.get("identity_defect")))
    check("closure D: blank run_id still reports the row's own sequence",
          r.get("terminal_row_sequence") == 11, str(r.get("terminal_row_sequence")))

    r = audit([running, dict(final_blank, run_id="r1")], [frozen(10, "edge_exit"), sent()])
    check("closure D: blank sequence alone is unresolved",
          r["verdict"] == "TERMINAL_ROW_IDENTITY_UNRESOLVED"
          and r.get("identity_defect") == "sequence_missing",
          "%s/%s" % (r["verdict"], r.get("identity_defect")))
    check("closure D: blank sequence is reported as absent, not inherited",
          r.get("terminal_row_sequence") is None and r.get("last_seq") == 10,
          "terminal=%s last=%s" % (r.get("terminal_row_sequence"), r.get("last_seq")))

    r = audit([running, dict(final_blank, run_id="r1", sequence="10.7")],
              [frozen(10, "edge_exit"), sent()])
    check("closure D: fractional sequence is not truncated to an integer",
          r.get("identity_defect") == "sequence_not_integer", str(r.get("identity_defect")))

    for bad in ("inf", "-inf", "nan", "1e3", "0x10", "  ", "10."):
        r = audit([running, dict(final_blank, run_id="r1", sequence=bad)],
                  [frozen(10, "edge_exit"), sent()])
        check("closure D: sequence %r is an identity defect, not a value" % bad,
              r["verdict"] == "TERMINAL_ROW_IDENTITY_UNRESOLVED",
              "%s/%s" % (r["verdict"], r.get("identity_defect")))

    r = audit([running, dict(final_blank, run_id="r1", sequence="10")],
              [frozen(10, "edge_exit"), sent()])
    check("closure D: an identified terminal row still corroborates",
          r["verdict"] == c7.VALIDATED and r["terminal_evidence"] == "corroborated",
          "%s/%s" % (r["verdict"], r["terminal_evidence"]))
    check("closure D: identity source is the terminal row",
          r.get("identity_source") == "terminal_row", str(r.get("identity_source")))

    # --- real batches -------------------------------------------------------
    p01 = os.path.join(BACKEND, "telemetry_logs/P01")
    diag = os.path.abspath(os.path.join(os.environ.get("LOCALAPPDATA", ""), "..", "LocalLow",
                                        "QI YUXUAN", "VectorAI", "EndlessFallingDiagnostics"))
    if os.path.isdir(p01) and os.path.isdir(diag):
        idx = c7.index_diagnostics(diag)
        res = [c7.audit_session(os.path.join(p01, n), idx)
               for n in sorted(os.listdir(p01)) if n.startswith("session_")]
        check("closure: P01 still has 22 validated sessions",
              sum(1 for r in res if r["verdict"] == c7.VALIDATED) == 22,
              str(sum(1 for r in res if r["verdict"] == c7.VALIDATED)))
        check("closure: P01 validated sessions are all corroborated",
              all(r["terminal_evidence"] == "corroborated"
                  for r in res if r["verdict"] == c7.VALIDATED),
              str(sorted({r["terminal_evidence"] for r in res if r["verdict"] == c7.VALIDATED})))
        p02 = os.path.join(BACKEND, "telemetry_logs/P02")
        if os.path.isdir(p02):
            r2 = [c7.audit_session(os.path.join(p02, n), idx)
                  for n in sorted(os.listdir(p02)) if n.startswith("session_")]
            check("closure: P02 all four sessions validated",
                  sum(1 for r in r2 if r["verdict"] == c7.VALIDATED) == 4,
                  str([r["verdict"] for r in r2]))
            check("closure: P02 all four are corroborated",
                  all(r["terminal_evidence"] == "corroborated" for r in r2),
                  str([r["terminal_evidence"] for r in r2]))


# ---------------------------------------------------------------------------
# warning episodes (unchanged tool, kept as a guard)
# ---------------------------------------------------------------------------
def test_episodes(tmp: str) -> None:
    base = dict(source_timestamp="10", sequence="10", warning_active="true",
                warning_source="attention", run_id="a", platform_level="1", layer_id="1",
                geometry_platform_instance_id="-1", geometry_version_id="-1-g1")

    other = dict(base, source_timestamp="10.02", sequence="11",
                 geometry_platform_instance_id="-2", geometry_version_id="-2-g2")
    check("episodes: same-layer platform swap splits",
          len(e5.group_episodes([base, other])) == 2,
          str(len(e5.group_episodes([base, other]))))

    version = dict(base, source_timestamp="10.02", sequence="11", geometry_version_id="-1-g9")
    check("episodes: version change splits",
          len(e5.group_episodes([base, version])) == 2,
          str(len(e5.group_episodes([base, version]))))

    back = dict(base, source_timestamp="9.98", sequence="9")
    check("episodes: time/sequence reversal splits",
          len(e5.group_episodes([base, back])) == 2,
          str(len(e5.group_episodes([base, back]))))

    rows = [dict(base, source_timestamp="10", sequence="10")]
    for k in range(1, 7):
        rows.append(dict(base, source_timestamp="%.3f" % (10 + k * 0.02), sequence=str(10 + k * 4)))
    tight = len(e5.group_episodes(rows, seq_tolerance=3))
    loose = len(e5.group_episodes(rows, seq_tolerance=5))
    check("episodes: --seq-tolerance actually changes grouping", tight != loose,
          "tol3=%d tol5=%d" % (tight, loose))

    path = os.path.join(tmp, "ep.csv")
    write_csv(path, [dict(base, source="unity"),
                     dict(base, source="unity", source_timestamp="10.02", sequence="11")])
    kept, short = e5.episodes_for_session(path, 0.5, 0.0, seq_tolerance=3)
    check("episodes: from a file, tolerance is threaded through",
          len(kept) + len(short) == 1, str(len(kept) + len(short)))

    p02 = os.path.join(BACKEND, "telemetry_logs/P02")
    if os.path.isdir(p02):
        total = 0
        for name in sorted(os.listdir(p02)):
            raw = os.path.join(p02, name, "raw.csv")
            if os.path.isfile(raw):
                k, s = e5.episodes_for_session(raw, 0.5, 0.0, 3)
                total += len(k) + len(s)
        check("episodes: P02 still yields 90 descriptive groups (not model alarms)",
              total == 90, str(total))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="v7_tools_") as tmp:
        test_wii(tmp)
        test_profile(tmp)
        test_closure(tmp)
        test_episodes(tmp)

    failed = [r for r in results if not r[1]]
    print("\n=== %d checks, %d passed, %d failed ===" % (len(results), len(results) - len(failed), len(failed)))
    for name, _, detail in failed:
        print("  FAILED: %s %s" % (name, detail))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
