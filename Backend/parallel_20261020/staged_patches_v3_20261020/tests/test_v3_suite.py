#!/usr/bin/env python3
"""test_v3_suite.py

Comprehensive regression test suite for v3 offline tools and patch integrity.
Verifies all findings raised in independent review (2026-10-20).
"""

import os
import sys
from pathlib import Path
import numpy as np

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "patch_3_warning_episodes"))
sys.path.insert(0, str(BASE_DIR / "patch_4_clock_profile"))
sys.path.insert(0, str(BASE_DIR / "patch_5_wii_preflight"))
sys.path.insert(0, str(BASE_DIR / "tools"))

import cluster_warning_episodes_v3 as ep
import receive_latency_profile_v3 as prof
import wii_cop_preflight_v3 as wii
import session_closure_audit_v3 as closure


def test_episodes_cross_run_split():
    rows = [
        {"source_timestamp": "10.0", "warning_active": "true", "run_id": "run-a", "platform_level": "1"},
        {"source_timestamp": "10.1", "warning_active": "true", "run_id": "run-b", "platform_level": "2"}
    ]
    groups = ep.group_runs(rows, 0.5)
    assert len(groups) == 2, f"Expected 2 groups across run boundary, got {len(groups)}"
    assert groups[0][0]["run_id"] == "run-a"
    assert groups[1][0]["run_id"] == "run-b"
    print("[PASS] test_episodes_cross_run_split passed")


def test_episodes_explicit_clear_split():
    rows = [
        {"source_timestamp": "10.0", "warning_active": "true"},
        {"source_timestamp": "10.1", "warning_active": "false"},
        {"source_timestamp": "10.2", "warning_active": "true"}
    ]
    groups = ep.group_runs(rows, 0.5)
    assert len(groups) == 2, f"Expected 2 groups separated by explicit clear, got {len(groups)}"
    print("[PASS] test_episodes_explicit_clear_split passed")


def test_receive_latency_in_stream_step():
    src = 1_700_000_000 + np.arange(100) * 0.02
    latency = np.r_[np.full(50, 0.005), np.full(50, 0.105)]
    prof.load = lambda _: (src, src + latency, np.arange(100) * 0.02, list(range(100)))

    res = prof.analyse("in_mem_100ms_step", 0.4, 5.0)
    assert res["step_detected"] is True, "In-stream 100ms latency step was not detected!"
    assert abs(res["max_adjacent_step_ms"] - 100.0) < 1.0, f"Expected ~100ms step, got {res['max_adjacent_step_ms']}"
    print("[PASS] test_receive_latency_in_stream_step passed")


def test_wii_preflight_verdicts():
    t = np.arange(100) * 0.02

    # 1. Empty board
    w_empty = np.full(100, 0.10)
    wii.load_wii = lambda _: (w_empty, np.zeros(100), np.zeros(100), np.zeros(100), t, np.ones(100, bool), np.ones(100, bool), np.ones(100, bool))
    r_empty = wii.audit("in_mem", 50, 20.0, 1.0, 1.5)
    assert r_empty["verdict"] == "INSUFFICIENT_LOAD", f"Expected INSUFFICIENT_LOAD, got {r_empty['verdict']}"

    # 2. Moving / swaying participant
    w_move = np.full(100, 80.0)
    x_move = 5.0 * np.sin(t * 10)  # std > 1.0 cm
    wii.load_wii = lambda _: (w_move, x_move, np.zeros(100), np.zeros(100), t, np.ones(100, bool), np.ones(100, bool), np.ones(100, bool))
    r_move = wii.audit("in_mem", 50, 20.0, 1.0, 1.5)
    assert r_move["verdict"] == "LOADED_NOT_STATIONARY", f"Expected LOADED_NOT_STATIONARY, got {r_move['verdict']}"

    # 3. Skewed stationary baseline
    x_skew = np.full(100, 3.0)  # offset 3.0 cm > 1.5 cm tol
    wii.load_wii = lambda _: (w_move, x_skew, np.zeros(100), np.zeros(100), t, np.ones(100, bool), np.ones(100, bool), np.ones(100, bool))
    r_skew = wii.audit("in_mem", 50, 20.0, 1.0, 1.5)
    assert r_skew["verdict"] == "SKEWED", f"Expected SKEWED, got {r_skew['verdict']}"

    # 4. Valid centered baseline
    wii.load_wii = lambda _: (w_move, np.zeros(100), np.zeros(100), np.zeros(100), t, np.ones(100, bool), np.ones(100, bool), np.ones(100, bool))
    r_ok = wii.audit("in_mem", 50, 20.0, 1.0, 1.5)
    assert r_ok["verdict"] == "OK", f"Expected OK, got {r_ok['verdict']}"

    print("[PASS] test_wii_preflight_verdicts passed (all 4 states)")


def test_closure_audit_neutral_labels():
    # Verify taxonomy labels are descriptive
    assert "TERMINAL_OUTCOME_RECORDED" in closure.audit_session.__code__.co_consts
    print("[PASS] test_closure_audit_neutral_labels passed")


if __name__ == "__main__":
    test_episodes_cross_run_split()
    test_episodes_explicit_clear_split()
    test_receive_latency_in_stream_step()
    test_wii_preflight_verdicts()
    test_closure_audit_neutral_labels()
    print("\nALL V3 REGRESSION TESTS PASSED CLEANLY!")
