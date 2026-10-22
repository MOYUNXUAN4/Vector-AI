#!/usr/bin/env python3
"""Regression suite for the v4 offline tools.

Each test corresponds to a defect that was demonstrated on real data or with a
synthetic fixture. Run with any Python 3.9+ interpreter (no numpy needed):

    python tests/test_v4_suite.py
"""

from __future__ import annotations

import csv
import importlib.util
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILED = []


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def check(label, cond, detail=""):
    if cond:
        print("[PASS] %s" % label)
    else:
        print("[FAIL] %s %s" % (label, detail))
        FAILED.append(label)


# ---------------------------------------------------------------- patch 3
ep3 = load("ep3", "patch_3_warning_episodes/cluster_warning_episodes_v4.py")


def row(ts, run="a", platform="1", layer="1", src="attention", active=True,
        wtype="ATTENTION", seq=None, state="ATTENTION"):
    r = {
        "source_timestamp": str(ts),
        "run_id": run,
        "platform_level": platform,
        "layer_id": layer,
        "warning_source": src if active else "",
        "warning_type": wtype if active else "",
        "warning_active": "True" if active else "False",
        "prediction_state": state if active else "SAFE",
        "sequence": "" if seq is None else str(seq),
        "warning_episode_id": "0",
    }
    return r


def test_patch3():
    # 1. different run ids never merge
    g = ep3.group_episodes([row(10.0, run="a"), row(10.1, run="b")])
    check("p3 cross-run split", len(g) == 2, "got %d" % len(g))

    # 2. an explicit CLEAR row splits (v2 previously bridged it)
    g = ep3.group_episodes([row(10.0), row(10.1, active=False), row(10.2)])
    check("p3 explicit CLEAR split", len(g) == 2, "got %d" % len(g))

    # 3. channel change splits (v3 merged these)
    g = ep3.group_episodes([row(10.0), row(10.1, src="edge", wtype="STRONG", state="EDGE WARNING")])
    check("p3 channel change split", len(g) == 2, "got %d" % len(g))

    # 4. sequence discontinuity splits
    g = ep3.group_episodes([row(10.0, seq=100), row(10.02, seq=150)])
    check("p3 sequence-gap split", len(g) == 2, "got %d" % len(g))

    # 5. platform/layer change splits
    g = ep3.group_episodes([row(10.0, platform="1"), row(10.02, platform="2")])
    check("p3 platform split", len(g) == 2, "got %d" % len(g))

    # 6. contiguous same-channel rows stay together
    g = ep3.group_episodes([row(10.0, seq=1), row(10.02, seq=2), row(10.04, seq=3)])
    check("p3 contiguous kept", len(g) == 1, "got %d" % len(g))

    # 7. completed sessions are not dropped by default
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "raw.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted(row(0).keys()) + ["source", "session_outcome", "fall_event", "run_state"])
        w.writeheader()
        for r in [row(10.0, seq=1), row(10.02, seq=2)]:
            r.update({"source": "unity", "session_outcome": "calibration_completed",
                      "fall_event": "False", "run_state": "ended"})
            w.writerow(r)
    kept, short = ep3.episodes_for_session(p, 0.5, 0.0)
    check("p3 completed session retained", len(kept) + len(short) == 1,
          "got %d kept / %d short" % (len(kept), len(short)))


# ---------------------------------------------------------------- patch 4
rl4 = load("rl4", "patch_4_clock_profile/receive_latency_profile_v4.py")


def test_patch4():
    base = 1_700_000_000.0
    src = [base + i * 0.02 for i in range(240)]

    def run(lat, label_at=None):
        bck = [s + l for s, l in zip(src, lat)]
        return rl4.analyse_arrays(src, bck, [float("nan")] * len(src), name="fixture")

    lat = [0.005] * 120 + [0.105] * 120
    r = run(lat)
    check("p4 100 ms persistent step detected", r["step_detected"] and r["max_adjacent_step_ms"] > 90,
          "%.1f ms" % r["max_adjacent_step_ms"])

    lat = [0.005] * 240
    for i in range(100, 130):
        lat[i] = 0.155
    r = run(lat)
    check("p4 600 ms burst not a step", not r["step_detected"],
          "%.1f ms, spike %.1f" % (r["max_adjacent_step_ms"], r["max_within_segment_spike_ms"]))

    lat = [0.005 + 0.001 * ((i % 7) - 3) for i in range(240)]
    r = run(lat)
    check("p4 flat series no step", not r["step_detected"], "%.1f ms" % r["max_adjacent_step_ms"])

    # dual clock staircase: every 60 rows the geometry clock loses 150 ms
    geom = [s for s in src]
    for k in range(1, 4):
        for i in range(k * 60, len(geom)):
            geom[i] -= 0.150
    r = rl4.analyse_arrays(src, [s + 0.005 for s in src], geom, name="staircase")
    dual = r["unity_dual_clock_stats"]
    check("p4 dual-clock staircase counted", len(dual.get("discrete_jumps", [])) == 3,
          "jumps=%d" % len(dual.get("discrete_jumps", [])))
    check("p4 dual-clock drift magnitude", abs(dual.get("cumulative_drift_ms", 0) - 450.0) < 5,
          "%.1f ms" % dual.get("cumulative_drift_ms", 0))
    check("p4 global offset declared insufficient",
          dual.get("single_global_offset_sufficient") is False)

    # a truly stable pair must not be reported as a staircase
    r = rl4.analyse_arrays(src, [s + 0.005 for s in src], [s - 0.003 for s in src], name="flatpair")
    check("p4 flat dual clock has no jumps",
          len(r["unity_dual_clock_stats"].get("discrete_jumps", [])) == 0)


# ---------------------------------------------------------------- patch 5
wp5 = load("wp5", "patch_5_wii_preflight/wii_cop_preflight_v4.py")

COLS = ["source", "backend_timestamp", "total_weight", "cop_x", "cop_z",
        "wii_control_valid", "wii_board_loaded", "wii_center_applied",
        "wii_control_age_seconds", "wii_center_generation", "wii_controller_instance_id"]


def write_wii(rows):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "raw.csv")
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            base = {c: "" for c in COLS}
            base.update(r)
            base["source"] = "wii"
            w.writerow(base)
    return p


def wii_rows(n=200, weight=80.0, loaded=True, valid=True, centered=True, age=0.01,
             gen="3", inst="dev-a", jitter=0.0, gap_at=None, ineligible_before=0):
    out = []
    t = 1792419217.0
    for i in range(n):
        if gap_at is not None and i == gap_at:
            t += 2.0
        out.append({
            "backend_timestamp": "%.4f" % (t + i * 0.02),
            "total_weight": "%.2f" % (weight + (0.4 if (jitter and i % 2) else 0.0)),
            "cop_x": "%.4f" % (jitter * (1 if i % 2 else -1)),
            "cop_z": "0.0",
            "wii_control_valid": str(valid),
            "wii_board_loaded": str(loaded if i >= ineligible_before else False),
            "wii_center_applied": str(centered),
            "wii_control_age_seconds": "%.3f" % age,
            "wii_center_generation": gen if isinstance(gen, str) else gen.get(i, "3"),
            "wii_controller_instance_id": inst,
        })
    return out


def test_patch5():
    r = wp5.audit(write_wii(wii_rows()))
    check("p5 valid loaded still board -> OK", r["verdict"] == "OK", r["verdict"])

    r = wp5.audit(write_wii(wii_rows(weight=0.2, loaded=False)))
    check("p5 empty board -> INSUFFICIENT_LOAD", r["verdict"] == "INSUFFICIENT_LOAD", r["verdict"])

    # the v3 bug: board_loaded=False while weight is high must NOT pass
    r = wp5.audit(write_wii(wii_rows(weight=80.0, loaded=False)))
    check("p5 board_loaded=False is honoured", r["verdict"] != "OK", r["verdict"])

    r = wp5.audit(write_wii(wii_rows(weight=80.0, valid=False)))
    check("p5 control_valid=False is honoured", r["verdict"] != "OK", r["verdict"])

    r = wp5.audit(write_wii(wii_rows(weight=80.0, age=0.9)))
    check("p5 stale control age is honoured", r["verdict"] != "OK", r["verdict"])

    r = wp5.audit(write_wii(wii_rows(jitter=3.0)))
    check("p5 swaying participant -> LOADED_NOT_STATIONARY",
          r["verdict"] == "LOADED_NOT_STATIONARY", r["verdict"])

    # A window that spans a 2 s hole must be rejected. Force the first eligible
    # region to start at 95 so the only nearby windows all reach across the gap.
    r = wp5.audit(write_wii(wii_rows(gap_at=100, ineligible_before=95)))
    check("p5 internal time gap is not bridged",
          r["verdict"] == "OK" and r.get("window_start_index", 0) >= 100,
          "%s at %s" % (r["verdict"], r.get("window_start_index")))

    gens = {i: ("5" if 100 <= i < 120 else "4") for i in range(200)}
    r = wp5.audit(write_wii(wii_rows(gen=gens, ineligible_before=95)))
    check("p5 generation change disqualifies window",
          r["verdict"] != "OK" or r.get("window_start_index", 0) >= 120,
          "%s at %s" % (r["verdict"], r.get("window_start_index")))

    r = wp5.audit(write_wii(wii_rows()))
    check("p5 flags reported as present", all(r["flag_columns_present"].values()),
          str(r["flag_columns_present"]))


# ---------------------------------------------------------------- closure
cl4 = load("cl4", "tools/session_closure_audit_v4.py")


def write_session(outcome, state, n_unity=50, n_wii=50):
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "session_x")
    os.makedirs(p)
    cols = ["source", "backend_timestamp", "sequence", "run_id", "run_state", "session_outcome"]
    with open(os.path.join(p, "raw.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i in range(n_unity):
            w.writerow({"source": "unity", "backend_timestamp": "%.2f" % (i * 0.02),
                        "sequence": str(i), "run_id": "r1", "run_state": state,
                        "session_outcome": outcome if i == n_unity - 1 else ""})
        for i in range(n_wii):
            w.writerow({"source": "wii", "backend_timestamp": "%.2f" % (i * 0.02),
                        "sequence": "", "run_id": "r1", "run_state": state, "session_outcome": ""})
    return p


def test_closure():
    r = cl4.audit_session(write_session("edge_exit", "ended"), {})
    check("closure outcome+ended -> validated", r["verdict"] == "TERMINAL_OUTCOME_VALIDATED", r["verdict"])

    r = cl4.audit_session(write_session("edge_exit", "running"), {})
    check("closure outcome without ended state flagged",
          r["verdict"] == "OUTCOME_WITHOUT_ENDED_STATE", r["verdict"])

    r = cl4.audit_session(write_session("", "running"), {})
    check("closure no outcome -> observational label",
          r["verdict"] == "BOTH_STREAMS_CEASE_TOGETHER", r["verdict"])
    check("closure never asserts a cause", r["cause"] == "unknown", r.get("cause"))

    r = cl4.audit_session(write_session("edge_exit", "ended"),
                          {"r1": {"files": ["x"], "terminal_send_completed": True}})
    check("closure send_completed tri-state true", r.get("diag_send_completed") is True)

    r = cl4.audit_session(write_session("edge_exit", "ended"), {"r1": {"files": ["x"]}})
    check("closure send_completed unknown stays null", r.get("diag_send_completed") is None)


def main():
    for fn in (test_patch3, test_patch4, test_patch5, test_closure):
        try:
            fn()
        except Exception:
            print("[FAIL] %s raised" % fn.__name__)
            traceback.print_exc()
            FAILED.append(fn.__name__)
    print()
    if FAILED:
        print("FAILED: %d check(s)" % len(FAILED))
        for f in FAILED:
            print("  - %s" % f)
        return 1
    print("ALL V4 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
