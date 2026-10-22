"""Locked offline comparison: two consecutive low evaluations to exit ACTIVE.

Uses the selected TEST1009 OOF probabilities and the existing evaluation metric
functions. This module never fits a model or searches a threshold grid.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEPLOYMENT = ROOT / "parallel_20261011" / "deployment_refit"
OOF = DEPLOYMENT / "output" / "oof_probabilities.csv"
MODEL = DEPLOYMENT / "output" / "artifact" / "model.txt"
PREP = (ROOT / "telemetry_logs" / "TEST1009" / "training_20261009" /
        "cop_single_factor_20261009" / "baseline_fixed" / "prepared_inputs")
THRESHOLD = 0.65
TARGET = "strong"
EXPECTED_BASELINE = {
    "conservative_recall": 0.6,
    "guaranteed_geometry_early_coverage": 0.4,
    "completed_alarm_rate": 0.55,
    "completed_observed_alarm_seconds_per_session": 0.2685500025749207,
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def known(value) -> bool:
    return value is not None and str(value).strip().lower() not in {"", "unknown", "nan", "none", "null"}


def finite(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return math.nan
    return out if math.isfinite(out) else math.nan


def evaluate_candidate(frame: pd.DataFrame, runner, *, exit_low_count: int = 2):
    """Return custom active-state output; retain the fixed entry rule and cancel semantics."""
    if exit_low_count < 1:
        raise ValueError("exit_low_count must be positive")
    out = frame.copy().reset_index(drop=True)
    n = len(out)
    # Entry/raw continuity is computed once by the unchanged production evaluator.
    # The candidate only changes how an already-active warning exits.
    entry_confirmed = runner.threshold_policy(out, TARGET, THRESHOLD)
    raw = (out["mask_strong"].fillna(False).astype(bool).to_numpy() &
           (pd.to_numeric(out["prob_strong"], errors="coerce").to_numpy(float) >= THRESHOLD) &
           (pd.to_numeric(out["clearance"], errors="coerce").to_numpy(float) > 0))
    pred = np.zeros(n, dtype=bool)
    canceled = np.zeros(n, dtype=bool)
    phase = ["inactive"] * n
    reason = ["inactive"] * n
    low_pending = np.zeros(n, dtype=bool)
    groups = out.sort_values(["session_id", "run_id", "segment_id", "timestamp"], kind="stable").groupby(
        ["session_id", "run_id", "segment_id"], sort=False
    )
    max_gap = float(runner.cmp.MAX_GAP)
    for _, group in groups:
        inds = group.index.to_list()
        active = False
        prev_time = None
        prev_platform, prev_layer, prev_version = "unknown", None, "unknown"
        low_count = 0
        for j, idx in enumerate(inds):
            row = out.loc[idx]
            now = finite(row.get("timestamp"))
            platform = runner.cmp.feature_identity(row)[0]
            layer = finite(row.get("layer"))
            version = str(row.get("geometry_version_id", "unknown"))
            clearance = finite(row.get("clearance"))
            probability = finite(row.get("prob_strong"))
            mask = bool(row.get("mask_strong", False))

            dt = now - prev_time if prev_time is not None and math.isfinite(now) and math.isfinite(prev_time) else math.nan
            gap_bad = prev_time is not None and not (0 < dt <= max_gap + 1e-9)
            identity_bad = not known(platform) or not known(version) or not math.isfinite(layer)
            context_change = (prev_time is not None and (
                (known(prev_platform) and known(platform) and platform != prev_platform)
                or layer != prev_layer or (known(prev_version) and known(version) and version != prev_version)
            ))

            # Invalid/context rows clear the state before they can count as a raw ON/OFF.
            if identity_bad:
                if active:
                    reason[idx] = "bad_identity_immediate_exit"
                else:
                    reason[idx] = "bad_identity_entry_reset"
                active, low_count = False, 0
            elif context_change:
                if active:
                    reason[idx] = "context_change_immediate_exit"
                else:
                    reason[idx] = "context_change_entry_reset"
                active, low_count = False, 0
            elif gap_bad:
                if active:
                    reason[idx] = "gap_or_non_new_evaluation_immediate_exit"
                else:
                    reason[idx] = "gap_or_non_new_evaluation_entry_reset"
                active, low_count = False, 0
            elif not math.isfinite(clearance) or clearance <= 0:
                if active:
                    reason[idx] = "nonpositive_or_invalid_clearance_immediate_exit"
                else:
                    reason[idx] = "invalid_clearance_entry_reset"
                active, low_count = False, 0
            elif not mask or not math.isfinite(probability):
                if active:
                    reason[idx] = "missing_or_invalid_score_immediate_exit"
                else:
                    reason[idx] = "missing_or_invalid_score_entry_reset"
                active, low_count = False, 0
            elif bool(row.get("joint_recovery", False)):
                if active:
                    canceled[idx] = True
                    reason[idx] = "joint_recovery_immediate_exit"
                else:
                    reason[idx] = "joint_recovery_entry_reset"
                active, low_count = False, 0
            else:
                if active:
                    if raw[idx]:
                        pred[idx] = True
                        phase[idx] = "active"
                        reason[idx] = "active_score_at_or_above_0.65_low_counter_reset"
                        low_count = 0
                    else:
                        low_count += 1
                        if low_count < exit_low_count:
                            pred[idx] = True
                            phase[idx] = "active_pending_low"
                            low_pending[idx] = True
                            reason[idx] = "first_consecutive_low_pending_exit"
                        else:
                            active = False
                            low_count = 0
                            reason[idx] = "second_consecutive_low_exit"
                else:
                    if bool(entry_confirmed[idx]):
                        active = True
                        pred[idx] = True
                        phase[idx] = "entry_confirmed_active"
                        reason[idx] = "two_consecutive_raw_on_entry_confirmed"
                        low_count = 0
                    elif raw[idx]:
                        reason[idx] = "first_raw_on_waiting_for_entry_confirmation"
                    else:
                        reason[idx] = "below_threshold_inactive"
            if pred[idx] and phase[idx] == "inactive":
                phase[idx] = "active"
            prev_time = now
            prev_platform, prev_layer, prev_version = platform, layer, version

    out["lgb_pred_strong"] = pred
    out["lgb_pred_strong_postcancel"] = pred
    out["lgb_cancel_strong"] = canceled
    out["candidate_phase"] = phase
    out["candidate_reason"] = reason
    out["candidate_pending_low"] = low_pending
    eps = runner.cmp.episodes(out, "lgb_pred_strong_postcancel", "LightGBM", TARGET, "lgb_cancel_strong")
    return out, eps


def f1(precision, recall):
    if precision is None or recall is None or precision + recall == 0:
        return None
    return float(2 * precision * recall / (precision + recall))


def synthetic_exit_checks(runner):
    """Pair the ACTIVE exit layer against the original policy on reset boundaries."""
    def trace(name, timestamps, platforms, recoveries=None, scores=None):
        n = len(timestamps)
        frame = pd.DataFrame({
            "session_id": [name] * n, "run_id": ["r"] * n, "segment_id": ["s"] * n,
            "timestamp": timestamps, "layer": [1] * n, "platform_id": platforms,
            "geometry_version_id": ["v1"] * n, "mask_strong": [True] * n,
            "prob_strong": scores or [0.9] * n, "clearance": [1.0] * n,
            "joint_recovery": recoveries or [False] * n,
        })
        baseline_raw = runner.threshold_policy(frame, TARGET, THRESHOLD)
        frame["synthetic_pred"] = baseline_raw
        baseline, _ = runner.cmp.cancel_predictions(frame, "synthetic_pred")
        candidate, _ = evaluate_candidate(frame, runner)
        same = np.array_equal(baseline, candidate.lgb_pred_strong_postcancel.to_numpy(bool))
        return {"name": name, "baseline_equals_candidate_rowwise": bool(same), "rows": n}, same

    recovery, recovery_ok = trace("synthetic_recovery", [0.0, .05, .10, .15, .20], ["p"] * 5,
                                  [False, False, True, False, False])
    context, context_ok = trace("synthetic_context", [0.0, .05, .10, .15, .20],
                                ["p1", "p1", "p2", "p2", "p2"])
    gap, gap_ok = trace("synthetic_gap", [0.0, .05, .20, .25, .30], ["p"] * 5)
    # One isolated low resets the baseline alarm, but must not become a candidate exit.
    held, held_ok = trace("synthetic_single_low", [0.0, .05, .10, .15, .20], ["p"] * 5,
                          scores=[.9, .9, .4, .9, .9])
    # Validate the specific extension: the first low stays active and the second exits immediately.
    two = pd.DataFrame({"session_id": ["synthetic_two_low"] * 5, "run_id": ["r"] * 5,
        "segment_id": ["s"] * 5, "timestamp": [0., .05, .10, .15, .20], "layer": [1] * 5,
        "platform_id": ["p"] * 5, "geometry_version_id": ["v1"] * 5, "mask_strong": [True] * 5,
        "prob_strong": [.9, .9, .4, .3, .9], "clearance": [1.] * 5, "joint_recovery": [False] * 5})
    two_rows, _ = evaluate_candidate(two, runner)
    two_low_ok = (bool(two_rows.loc[2, "lgb_pred_strong_postcancel"]) and
                  not bool(two_rows.loc[3, "lgb_pred_strong_postcancel"]) and
                  two_rows.loc[2, "candidate_reason"] == "first_consecutive_low_pending_exit" and
                  two_rows.loc[3, "candidate_reason"] == "second_consecutive_low_exit")
    checks = {"recovery_then_high_scores_rowwise_baseline_parity": recovery,
              "platform_context_first_raw_then_second_confirms_rowwise_parity": context,
              "gap_first_raw_then_second_confirms_rowwise_parity": gap,
              "two_low_exit_boundary": {"name": "synthetic_two_low_exit", "correct_first_low_hold_second_low_exit": bool(two_low_ok), "rows": 5}}
    if not (recovery_ok and context_ok and gap_ok and two_low_ok):
        raise RuntimeError(f"two-low state-machine synthetic parity failed: {checks}")
    # A one-low trace differs only by the specified pending-low display interval.
    checks["single_low_is_non_exit_and_then_rejoins_high_state"] = bool(
        held["baseline_equals_candidate_rowwise"] is False and held["rows"] == 5)
    return checks


def json_clean(value):
    if isinstance(value, dict):
        return {str(k): json_clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main():
    sys.dont_write_bytecode = True
    deployment = load_module("two_low_deployment_refit", DEPLOYMENT / "run_deployment_refit.py")
    _, runner = deployment.setup()  # setup only; never call preflight, fit, calibrate, or main
    features, joined, formal, outer_map, anchors, labels = runner.load_inputs()
    oof = pd.read_csv(OOF, low_memory=False)
    required = {"session_id", "run_id", "segment_id", "timestamp", "prob_strong", "mask_strong", "clearance", "joint_recovery", "platform_id", "geometry_version_id", "layer"}
    missing = sorted(required - set(oof.columns))
    if missing:
        raise RuntimeError(f"OOF input missing required columns: {missing}")
    if len(oof) != 6898 or oof.session_id.astype(str).nunique() != 30:
        raise RuntimeError(f"Expected locked OOF 6,898 rows / 30 sessions; got {len(oof)} / {oof.session_id.nunique()}")

    # The OOF table and original prepared labels/anchors are the only records evaluated.
    baseline_rows, baseline_eps, baseline_per, baseline_events = runner.strict_replay(oof, formal, anchors, TARGET, THRESHOLD)
    baseline_metrics = runner.candidate_metrics(baseline_per, baseline_events, TARGET)
    mismatch = {k: {"expected": v, "actual": baseline_metrics.get(k)} for k, v in EXPECTED_BASELINE.items()
                if baseline_metrics.get(k) is None or not math.isclose(float(baseline_metrics[k]), v, rel_tol=0, abs_tol=1e-12)}
    before_hashes = {"oof_probabilities.csv": sha(OOF), "model.txt": sha(MODEL)}
    for name in ("features.csv", "session_manifest.csv", "event_anchors.csv", "recovery_points.csv", "source_hashes.json", "summary.json", "risk_episode_ledger.csv"):
        before_hashes[f"prepared_inputs/{name}"] = sha(PREP / name)
    if mismatch:
        payload = {"status": "BLOCKED_BASELINE_REPLAY_MISMATCH", "baseline_replay_mismatch": mismatch,
                   "baseline_metrics": baseline_metrics, "candidate_evaluated": False,
                   "input_sha256_before": before_hashes, "method": "Candidate not run because protocol baseline exact-match gate failed."}
        (HERE / "two_low_exit_report.json").write_text(json.dumps(json_clean(payload), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        raise RuntimeError(f"baseline replay failed exact locked metrics gate: {mismatch}")

    synthetic_checks = synthetic_exit_checks(runner)
    # Required single-low parity control: with no extra held low, output must
    # match the locked immediate-OFF replay at every OOF row.
    one_low_rows, _ = evaluate_candidate(oof, runner, exit_low_count=1)
    baseline_on = baseline_rows["lgb_pred_strong_postcancel"].fillna(False).to_numpy(bool)
    one_low_on = one_low_rows["lgb_pred_strong_postcancel"].fillna(False).to_numpy(bool)
    one_low_parity_mismatch_count = int(np.count_nonzero(baseline_on != one_low_on))
    if one_low_parity_mismatch_count:
        raise RuntimeError(f"one-low parity control differs from baseline on {one_low_parity_mismatch_count} OOF rows")

    cand_rows, cand_eps = evaluate_candidate(oof, runner)
    # Enrich with existing manifest attribution and score with the exact existing strict event matcher.
    manifest = formal
    cand_eps = runner.enrich_episodes(cand_rows, cand_eps, TARGET, "lgb", manifest, THRESHOLD)
    cand_per, cand_events = runner.strict_event_matches(cand_rows, cand_eps, manifest, anchors, TARGET, "lgb")
    cand_metrics = runner.candidate_metrics(cand_per, cand_events, TARGET)

    # First and last actual pre-event warning leads are descriptive episode timing, not model score changes.
    timing = {}
    for m in manifest.to_dict("records"):
        sid = str(m["session_id"])
        evs = anchors[anchors.session_id.astype(str).eq(sid)]
        if m.get("actual_outcome") == "edge_exit":
            evs = evs[evs.is_terminal_proxy.map(runner.cmp.truth)]
            if not runner.cmp.truth(m.get("anchor_available", False)):
                evs = evs.iloc[0:0]
            if len(evs):
                evs = evs.sort_values("lower").tail(1)
        rowrec = {"baseline_first_lead_seconds": None, "baseline_last_lead_seconds": None,
                  "candidate_first_lead_seconds": None, "candidate_last_lead_seconds": None}
        for arm, rows, eps in (("baseline", baseline_rows, baseline_eps), ("candidate", cand_rows, cand_eps)):
            pre = []
            pred_col = "lgb_pred_strong_postcancel"
            for event in evs.to_dict("records"):
                lo = finite(event.get("lower"))
                if not math.isfinite(lo):
                    continue
                session_rows = rows[rows.session_id.astype(str).eq(sid)].copy()
                session_rows["_asof_platform_id"] = [runner.cmp.feature_identity(r)[0] for r in session_rows.to_dict("records")]
                session_eps = eps[eps.session_id.astype(str).eq(sid)] if len(eps) else pd.DataFrame()
                for ep in session_eps.to_dict("records"):
                    if runner.actual_on_in_event_window(session_rows, pred_col, event, ep, lo, 1.5):
                        pre.append(lo - finite(ep.get("start")))
            if pre:
                rowrec[f"{arm}_first_lead_seconds"] = float(max(pre))
                rowrec[f"{arm}_last_lead_seconds"] = float(min(pre))
        timing[sid] = rowrec

    # Paired session detail preserves original denominators and exposes every session, including zero episodes.
    session_diffs = []
    base_by = baseline_per.set_index(baseline_per.session_id.astype(str), drop=False)
    cand_by = cand_per.set_index(cand_per.session_id.astype(str), drop=False)
    start_by = oof.groupby(oof.session_id.astype(str)).timestamp.min().to_dict()
    for m in manifest.to_dict("records"):
        sid = str(m["session_id"])
        b, c = base_by.loc[sid], cand_by.loc[sid]
        b_eps = baseline_eps[baseline_eps.session_id.astype(str).eq(sid)] if len(baseline_eps) else pd.DataFrame()
        c_eps = cand_eps[cand_eps.session_id.astype(str).eq(sid)] if len(cand_eps) else pd.DataFrame()
        duration = finite(m.get("game_end_time")) - finite(start_by.get(sid))
        session_diffs.append({
            "session_id": sid, "actual_outcome": m.get("actual_outcome"), "formal_exit": bool(m.get("actual_outcome") == "edge_exit"),
            "anchor_available": bool(runner.cmp.truth(m.get("anchor_available", False))),
            "baseline": {"matched_event_count": int(b.matched_event_count), "recall": json_clean(b.recall),
                         "geometry_04": bool(b.guaranteed_coverage_ge_04), "episodes": int(b.episode_count),
                         "short_episodes_lt_0_2s": int((b_eps.duration < 0.2).sum()) if len(b_eps) else 0,
                         "warning_seconds": float(b.total_warning_seconds), "first_activation": float(b_eps.start.min()) if len(b_eps) else None},
            "candidate": {"matched_event_count": int(c.matched_event_count), "recall": json_clean(c.recall),
                          "geometry_04": bool(c.guaranteed_coverage_ge_04), "episodes": int(c.episode_count),
                          "short_episodes_lt_0_2s": int((c_eps.duration < 0.2).sum()) if len(c_eps) else 0,
                          "warning_seconds": float(c.total_warning_seconds), "first_activation": float(c_eps.start.min()) if len(c_eps) else None},
            "completed_session_duration_seconds": float(duration) if math.isfinite(duration) else None,
            "first_last_pre_event_leads": timing[sid],
            "paired_difference_candidate_minus_baseline": {
                "matched_event_count": int(c.matched_event_count) - int(b.matched_event_count),
                "episode_count": int(c.episode_count) - int(b.episode_count),
                "short_episode_count_lt_0_2s": (int((c_eps.duration < 0.2).sum()) if len(c_eps) else 0) - (int((b_eps.duration < 0.2).sum()) if len(b_eps) else 0),
                "warning_seconds": float(c.total_warning_seconds) - float(b.total_warning_seconds),
                "first_activation_time_unchanged": ((float(c_eps.start.min()) if len(c_eps) else None) == (float(b_eps.start.min()) if len(b_eps) else None)),
            },
        })

    # Count time specifically added by the single pending-low interval before the second low exits.
    pending_seconds = 0.0
    for _, group in cand_rows.sort_values(["session_id", "run_id", "segment_id", "timestamp"], kind="stable").groupby(["session_id", "run_id", "segment_id"], sort=False):
        inds = group.index.to_list()
        for j, idx in enumerate(inds[:-1]):
            if bool(cand_rows.loc[idx, "candidate_pending_low"]):
                dt = finite(cand_rows.loc[inds[j + 1], "timestamp"]) - finite(cand_rows.loc[idx, "timestamp"])
                if 0 < dt <= float(runner.cmp.MAX_GAP) + 1e-9:
                    pending_seconds += dt

    # Add standard binary-session precision/recall/F1 and descriptive aggregate episode counts.
    recall = cand_metrics["conservative_recall"]
    precision = cand_metrics["precision"]
    cand_metrics["f1"] = f1(precision, recall) if precision is not None else None
    baseline_metrics["f1"] = f1(baseline_metrics["precision"], baseline_metrics["conservative_recall"])
    exits = manifest[manifest.actual_outcome.eq("edge_exit")]
    missing_anchor = int((~exits.anchor_available.map(runner.cmp.truth)).sum())
    baseline_metrics["geometry_anchor_denominator"] = int(len(exits))
    baseline_metrics["geometry_missing_anchor_exits"] = missing_anchor
    cand_metrics["geometry_anchor_denominator"] = int(len(exits))
    cand_metrics["geometry_missing_anchor_exits"] = missing_anchor
    b_short = int((baseline_eps.duration < 0.2).sum()) if len(baseline_eps) else 0
    c_short = int((cand_eps.duration < 0.2).sum()) if len(cand_eps) else 0
    active_exit_counts = cand_rows.loc[
        cand_rows.candidate_reason.eq("second_consecutive_low_exit") | cand_rows.candidate_reason.str.endswith("immediate_exit"),
        "candidate_reason"].value_counts().to_dict()
    after_hashes = {"oof_probabilities.csv": sha(OOF), "model.txt": sha(MODEL)}
    for name in ("features.csv", "session_manifest.csv", "event_anchors.csv", "recovery_points.csv", "source_hashes.json", "summary.json", "risk_episode_ledger.csv"):
        after_hashes[f"prepared_inputs/{name}"] = sha(PREP / name)
    changed = {k: {"before": before_hashes.get(k), "after": after_hashes.get(k)} for k in before_hashes if before_hashes.get(k) != after_hashes.get(k)}
    report = {
        "status": "COMPLETED_BASELINE_MATCH_CANDIDATE_SCREENED" if not changed else "BLOCKED_INPUT_HASH_CHANGED",
        "protocol": "CANCEL_TWO_LOW_PROTOCOL.md", "candidate_count": 1, "candidate": "ACTIVE exit after two consecutive NEW valid evaluations with probability <0.65",
        "fixed_policy": {"entry_threshold": 0.65, "entry_confirmation": "original two consecutive raw ON evaluations", "forecast_horizon_seconds": 0.75,
                         "recovery": "joint physical recovery immediately exits", "invalidity_and_context": "immediate exit", "no_added_threshold_or_minimum_show_time": True},
        "baseline_replay": {"status": "EXACT_MATCH", "metrics": baseline_metrics, "expected_selected_metrics": EXPECTED_BASELINE},
        "candidate_metrics_existing_candidate_metrics_function": cand_metrics,
        "candidate_precision_recall_f1": {"precision": cand_metrics.get("precision"), "recall": recall, "f1": cand_metrics.get("f1")},
        "geometry_coverage": {"guaranteed_ge_0_4_coverage": cand_metrics["guaranteed_geometry_early_coverage"],
                              "numerator": cand_metrics["guaranteed_early_numerator"], "formal_exit_denominator": len(exits),
                              "missing_anchor_exit_count_in_denominator": missing_anchor},
        "first_last_pre_event_leads": {"by_session": timing},
        "episode_summary": {"baseline_episodes": int(len(baseline_eps)), "candidate_episodes": int(len(cand_eps)),
                            "baseline_shorter_than_0_2s": b_short, "candidate_shorter_than_0_2s": c_short},
        "completed_sessions": {"count": int((~manifest.actual_outcome.eq("edge_exit")).sum()),
                               "duration_seconds_by_session": {x["session_id"]: x["completed_session_duration_seconds"] for x in session_diffs if not x["formal_exit"]},
                               "baseline_alarm_rate": baseline_metrics["completed_alarm_rate"], "candidate_alarm_rate": cand_metrics["completed_alarm_rate"],
                               "baseline_mean_alarm_seconds": baseline_metrics["completed_observed_alarm_seconds_per_session"],
                               "candidate_mean_alarm_seconds": cand_metrics["completed_observed_alarm_seconds_per_session"]},
        "pending_low_added_active_seconds": float(pending_seconds),
        "paired_sessions": session_diffs,
        "state_transition_counts": pd.Series(cand_rows.candidate_reason).value_counts().to_dict(),
        "active_exit_reason_counts": {k: int(active_exit_counts.get(k, 0)) for k in (
            "second_consecutive_low_exit", "joint_recovery_immediate_exit", "nonpositive_or_invalid_clearance_immediate_exit",
            "missing_or_invalid_score_immediate_exit", "bad_identity_immediate_exit", "context_change_immediate_exit",
            "gap_or_non_new_evaluation_immediate_exit")},
        "recovery_cancellation_count": int(cand_rows.lgb_cancel_strong.sum()),
        "paired_session_status_differences": session_diffs,
        "synthetic_state_machine_checks": synthetic_checks,
        "one_low_exit_count_full_oof_rowwise_baseline_parity": {
            "checked_rows": int(len(oof)), "mismatch_count": one_low_parity_mismatch_count,
            "exact_rowwise_match": one_low_parity_mismatch_count == 0,
        },
        "first_activation_earlier_session_count": sum(1 for x in session_diffs if x["baseline"]["first_activation"] is not None and x["candidate"]["first_activation"] is not None and x["candidate"]["first_activation"] < x["baseline"]["first_activation"] - 1e-9),
        "interpretation": "First activation is evaluated independently of hold duration. A longer episode may affect event pairing via continuity; it is not evidence of earlier prediction. OOF scores were already used to select threshold 0.65, so this is calibration/engineering screening only, not unbiased or independent efficacy evidence and not deployment authorization.",
        "screening_rule": {"recall_and_geometry_coverage_no_lower": True, "session_f1_and_completed_alarm_rate_no_worse": True,
                           "completed_mean_burden_increase_at_most_seconds": 0.05, "short_episode_count_strictly_decreases": True,
                           "automatic_deployment": False},
        "screening_result": None,
        "input_sha256_before": before_hashes, "input_sha256_after": after_hashes, "changed_hashes": changed,
    }
    gates = [cand_metrics["conservative_recall"] >= baseline_metrics["conservative_recall"],
             cand_metrics["guaranteed_geometry_early_coverage"] >= baseline_metrics["guaranteed_geometry_early_coverage"],
             (cand_metrics.get("f1") or -1) >= (baseline_metrics.get("f1") or -1),
             cand_metrics["completed_alarm_rate"] <= baseline_metrics["completed_alarm_rate"],
             cand_metrics["completed_observed_alarm_seconds_per_session"] <= baseline_metrics["completed_observed_alarm_seconds_per_session"] + 0.05,
             c_short < b_short]
    report["screening_result"] = "PASS_FOR_FURTHER_VALIDATION_ONLY" if all(gates) and not changed else "FAIL_OR_BLOCKED"
    report["screening_gates"] = {"recall_no_lower": bool(gates[0]), "geometry_coverage_no_lower": bool(gates[1]),
                                 "session_f1_no_worse": bool(gates[2]), "completed_alarm_rate_no_worse": bool(gates[3]),
                                 "mean_burden_increase_at_most_0_05s": bool(gates[4]), "short_episode_count_strictly_decreases": bool(gates[5])}
    (HERE / "two_low_exit_report.json").write_text(json.dumps(json_clean(report), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    if report["status"] != "COMPLETED_BASELINE_MATCH_CANDIDATE_SCREENED":
        raise RuntimeError("Inputs changed during comparison; results are blocked")


if __name__ == "__main__":
    main()
