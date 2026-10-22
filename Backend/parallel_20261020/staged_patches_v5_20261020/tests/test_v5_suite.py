#!/usr/bin/env python3
"""test_v5_suite.py — adversarial regression suite for the v5 offline tools.

Every fixture in this file corresponds to a counterexample from the 2026-10-20
review of v4, i.e. a case that v4 got wrong. If a fix is reverted, the matching
check fails.

Run:  python tests/test_v5_suite.py
Exit: 0 all passed, 1 failures
"""

from __future__ import annotations

import csv
import importlib.util
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


w5 = load("v5_wii", "patch_5_wii_preflight/wii_cop_preflight_v5.py")
c5 = load("v5_closure", "tools/session_closure_audit_v5.py")
p5 = load("v5_profile", "patch_4_clock_profile/receive_latency_profile_v5.py")
e5 = load("v5_episodes", "patch_3_warning_episodes/cluster_warning_episodes_v5.py")

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print("[%s] %-56s %s" % ("PASS" if ok else "FAIL", name, detail))


def write_csv(path: str, rows):
    fields = sorted(set().union(*(r.keys() for r in rows)))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# patch 5: board evidence
# ---------------------------------------------------------------------------
def wii_row(i, **kw):
    base = {
        "source": "wii",
        "backend_timestamp": "%.4f" % (100.0 + i * 0.02),
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

    rows = [dict(source="wii", backend_timestamp=str(100 + i * 0.02),
                 total_weight="80", cop_x="0", cop_z="0") for i in range(60)]
    write_csv(path, rows)
    r = w5.audit(path)
    check("wii: missing board flags are not OK", r["verdict"] == "UNKNOWN_EVIDENCE", r["verdict"])
    check("wii: missing flag columns reported",
          not r["evidence"]["complete"] and "wii_board_loaded" in r["evidence"]["missing_columns"])

    rows = [wii_row(i) for i in range(60)]
    for i, row in enumerate(rows):
        row["backend_timestamp"] = "%.4f" % (100.0 - i * 0.02)
    write_csv(path, rows)
    r = w5.audit(path)
    check("wii: reversed clock is not OK", r["verdict"] != "OK", r["verdict"])
    dur = r.get("window_duration_s")
    check("wii: no negative window duration", dur is None or dur > 0, str(dur))

    rows = [wii_row(i) for i in range(60)]
    for row in rows:
        row.pop("wii_control_age_seconds")
    write_csv(path, rows)
    r = w5.audit(path)
    check("wii: missing age column is UNKNOWN", r["verdict"] == "UNKNOWN_EVIDENCE", r["verdict"])

    rows = [wii_row(i, wii_center_generation="", wii_controller_instance_id="") for i in range(60)]
    write_csv(path, rows)
    r = w5.audit(path)
    check("wii: empty identity is not OK", r["verdict"] != "OK", r["verdict"])

    rows = [wii_row(i) for i in range(120)]
    rows[40]["total_weight"] = ""
    write_csv(path, rows)
    r = w5.audit(path)
    check("wii: invalid row is a barrier, not bridged",
          r["verdict"] == "OK" and r.get("window_start_index", 0) > 40,
          "%s at %s" % (r["verdict"], r.get("window_start_index")))

    rows = [wii_row(i, wii_board_loaded="false", wii_center_applied="false") for i in range(80)]
    write_csv(path, rows)
    r = w5.audit(path)
    check("wii: explicit false flags are not OK", r["verdict"] != "OK", r["verdict"])

    real = os.path.join(BACKEND, "telemetry_logs/P01/session_20261019_105632_058608/raw.csv")
    if os.path.isfile(real):
        r = w5.audit(real)
        check("wii: real loaded session still OK", r["verdict"] == "OK", r["verdict"])
        check("wii: real session evidence complete", r["evidence"]["complete"] is True)
    real = os.path.join(BACKEND, "telemetry_logs/P01/session_20261019_161529_760840/raw.csv")
    if os.path.isfile(real):
        r = w5.audit(real)
        check("wii: empty-board session is INSUFFICIENT_LOAD", r["verdict"] == "INSUFFICIENT_LOAD",
              r["verdict"])


# ---------------------------------------------------------------------------
# patch 4: global-offset sufficiency
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

    # csv_line provenance only exists when the file is read (not in-memory)
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
# closure audit
# ---------------------------------------------------------------------------
def test_closure(tmp: str) -> None:
    def audit(rows, diag):
        d = os.path.join(tmp, "session_fixture")
        os.makedirs(d, exist_ok=True)
        write_csv(os.path.join(d, "raw.csv"), rows)
        return c5.audit_session(d, {"r1": diag} if diag is not None else {})

    base = dict(source="unity", backend_timestamp="100", sequence="10",
                run_id="r1", run_state="ended", session_outcome="edge_exit")

    r = audit([base], dict(terminal_seq=20, terminal_outcome="user_exit",
                           terminal_send_completed=True))
    check("closure: contradiction is not VALIDATED",
          r["verdict"] == "TERMINAL_OUTCOME_CONTRADICTED", r["verdict"])
    check("closure: contradiction names the conflict",
          bool(r.get("conflicts")) and r["outcome_match"] is False, str(r.get("conflicts")))

    r = audit([base], dict(terminal_seq=10, terminal_outcome="edge_exit",
                           terminal_send_completed=True))
    check("closure: corroborated session validated",
          r["verdict"] == c5.VALIDATED and r["terminal_evidence"] == "corroborated",
          "%s/%s" % (r["verdict"], r["terminal_evidence"]))

    r = audit([base], {})
    check("closure: no diagnostics is unavailable, not contradicted",
          r["verdict"] == c5.VALIDATED and r["terminal_evidence"] == "unavailable",
          "%s/%s" % (r["verdict"], r["terminal_evidence"]))

    r = audit([base], dict(terminal_seq=12, terminal_outcome="edge_exit",
                           terminal_send_completed=True))
    check("closure: terminal row not persisted is partial",
          r["terminal_evidence"] == "partial", r["terminal_evidence"])

    r = audit([base], dict(terminal_seq=10, terminal_outcome="edge_exit",
                           terminal_send_completed=False))
    check("closure: failed send is a contradiction",
          r["verdict"] == "TERMINAL_OUTCOME_CONTRADICTED", r["verdict"])

    r = audit([dict(base, session_outcome="aborted")], {})
    check("closure: unknown outcome semantics rejected",
          r["verdict"] == "OUTCOME_SEMANTICS_UNKNOWN", r["verdict"])

    r = audit([base, dict(base, run_id="r2", sequence="11")], {})
    check("closure: mixed run is not validated", r["verdict"] == "MIXED_RUN", r["verdict"])

    r = audit([base, dict(source="unity", backend_timestamp="100.02", sequence="11",
                          run_id="r1", run_state="running", session_outcome="")], {})
    check("closure: outcome must be on the terminal row",
          r["verdict"] == "INCOMPLETE_NO_OUTCOME", r["verdict"])

    p01 = os.path.join(BACKEND, "telemetry_logs/P01")
    diag = os.path.join(os.environ.get("LOCALAPPDATA", ""), "..", "LocalLow",
                        "QI YUXUAN", "VectorAI", "EndlessFallingDiagnostics")
    diag = os.path.abspath(diag)
    if os.path.isdir(p01) and os.path.isdir(diag):
        idx = c5.index_diagnostics(diag)
        verdicts = []
        for name in sorted(os.listdir(p01)):
            if name.startswith("session_"):
                verdicts.append(c5.audit_session(os.path.join(p01, name), idx)["verdict"])
        check("closure: P01 still has 22 validated sessions",
              verdicts.count(c5.VALIDATED) == 22, str(verdicts.count(c5.VALIDATED)))
        p02 = os.path.join(BACKEND, "telemetry_logs/P02")
        if os.path.isdir(p02):
            v2 = [c5.audit_session(os.path.join(p02, n), idx)["verdict"]
                  for n in sorted(os.listdir(p02)) if n.startswith("session_")]
            check("closure: P02 all four sessions validated",
                  v2.count(c5.VALIDATED) == 4, str(v2))


# ---------------------------------------------------------------------------
# warning episodes
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
        check("episodes: P02 still yields 90 descriptive groups", total == 90, str(total))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="v5_tools_") as tmp:
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
