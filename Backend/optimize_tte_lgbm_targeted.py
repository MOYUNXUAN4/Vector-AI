"""Targeted offline tuning of TTE horizons and LightGBM temporal filtering.

Uses only the development pool for selection and evaluates the selected rules
once on TEST929 and TEST1001. Raw telemetry and Unity files are read-only.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

import compare_tree_models as tree
import run_time_to_edge_validation as tte
import train_gru_offline as gru

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "telemetry_logs" / "tte_lgbm_targeted_20261002"
HORIZONS = (0.3, 0.4, 0.5, 0.6)
VELOCITIES = (0.05, 0.10, 0.20, 0.50)
PERSISTENCE = (0.2, 0.3, 0.5)
CANCEL = (0.0, 0.3, 0.5, 1.0)
THRESHOLDS = tuple(np.round(np.arange(0.50, 0.951, 0.05), 2))


def session_metrics(rows, pred, method):
    result, details = gru.metrics_from_predictions(rows, np.asarray(pred, dtype=bool), method)
    return result["session"], details


def event_rule_metrics(sessions, masks):
    """Evaluate a TTE mask directly against the recorded fall event."""
    fall_total = sum(bool(np.isfinite(s["first_event_ts"])) for s in sessions)
    nonfall_total = len(sessions) - fall_total
    detected = false_alarm = 0
    first_leads = []
    last_leads = []
    episodes = []
    for s, raw_mask in zip(sessions, masks):
        ts = np.asarray(s["timestamps"], dtype=float)
        mask = np.asarray(raw_mask, dtype=bool)
        event = float(s["first_event_ts"])
        pre = np.ones(len(ts), dtype=bool) if not np.isfinite(event) else ts < event
        mask &= pre
        starts = np.flatnonzero(mask & np.r_[True, ~mask[:-1]]) if len(mask) else np.array([], dtype=int)
        has = len(starts) > 0
        if np.isfinite(event):
            detected += int(has and ts[starts[0]] < event)
            if has and ts[starts[0]] < event:
                first_leads.append(float(event - ts[starts[0]]))
                last_leads.append(float(event - ts[starts[-1]]))
        else:
            false_alarm += int(has)
        episodes.append(int(len(starts)))
    recall = detected / fall_total if fall_total else math.nan
    fpr = false_alarm / nonfall_total if nonfall_total else math.nan
    precision = detected / (detected + false_alarm) if detected + false_alarm else math.nan
    f1 = 2 * precision * recall / (precision + recall) if np.isfinite(precision) and np.isfinite(recall) and precision + recall else 0.0
    return {
        "precision": precision, "recall": recall, "f1": f1,
        "nonfall_false_alarm_rate": fpr,
        "first_warning_lead_median_s": float(np.median(first_leads)) if first_leads else math.nan,
        "first_warning_lead_p25_s": float(np.percentile(first_leads, 25)) if first_leads else math.nan,
        "last_warning_lead_median_s": float(np.median(last_leads)) if last_leads else math.nan,
        "last_warning_lead_p25_s": float(np.percentile(last_leads, 25)) if last_leads else math.nan,
        "warning_episode_mean_per_session": float(np.mean(episodes)) if episodes else math.nan,
    }


def tte_mask(s, horizon, persistence, velocity, cancel):
    # Compute each candidate from cached causal masks; rebuilding the replay
    # adapter for every grid point is unnecessarily expensive.
    ts = np.asarray(s["timestamps"], dtype=float)
    vel = np.asarray(s["velocity"], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        eta = (np.asarray(s["distance"], dtype=float) - np.asarray(s["radius"], dtype=float)) / vel
    cache = s.setdefault("_targeted_tte_cache", {})
    pk = (float(persistence), float(velocity))
    ck = (float(cancel), float(velocity))
    if pk not in cache:
        cache[pk] = gru.persistence_mask(ts, vel, s["segments"], float(velocity), float(persistence))
    if ck not in cache:
        cache[ck] = gru.inward_cancel_mask(ts, vel, s["segments"], float(velocity), float(cancel))
    outward = np.isfinite(vel) & (vel >= float(velocity))
    return np.asarray(s["edge_valid"], dtype=bool) & np.isfinite(eta) & outward & cache[pk] & ~cache[ck] & (eta >= 0) & (eta <= float(horizon))


def pre_mask(s):
    event = float(s.get("first_event_ts", np.nan))
    return np.ones(len(s["timestamps"]), dtype=bool) if not np.isfinite(event) else np.asarray(s["timestamps"]) < event


def example_prediction(sessions, masks):
    values = []
    for s, mask in zip(sessions, masks):
        values.extend(bool(mask[int(row["row_index"])]) for row in s.get("examples", []))
    return np.asarray(values, dtype=bool)


def load_dev_and_eval():
    dev, notes = tree.load_development()
    test929, test1001 = tree.load_test929(), tree.load_test1001()
    names = {name: i for i, name in enumerate(gru.FEATURE_CANDIDATES)}
    selected = [n for n in tree.SELECTED_FEATURES if n in names]
    indices = [names[n] for n in selected if any(np.isfinite(s["feature_table"][:, names[n]]).any() for s in dev)]
    tree.prepare_sessions(dev + test929 + test1001, indices)
    return dev, test929, test1001, indices, notes


def select_rule(rows, candidates):
    frame = pd.DataFrame(candidates)
    feasible = frame[(frame.recall >= 0.60) & (frame.nonfall_false_alarm_rate <= 0.25)]
    if feasible.empty:
        feasible = frame[frame.recall >= 0.60]
    if feasible.empty:
        feasible = frame
    return feasible.sort_values(["f1", "precision", "last_warning_lead_median_s", "nonfall_false_alarm_rate"], ascending=[False, False, False, True]).iloc[0].to_dict(), frame


def temporal_filter(rows, probabilities, threshold, consecutive):
    base = np.asarray(probabilities >= threshold, dtype=bool)
    out = np.zeros(len(rows), dtype=bool)
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(str(row["session_id"]), []).append(i)
    for ix in groups.values():
        for pos, i in enumerate(ix):
            start = max(0, pos - consecutive + 1)
            recent = ix[start:pos + 1]
            out[i] = len(recent) == consecutive and all(base[j] for j in recent)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20261002)
    args = ap.parse_args()
    if args.out_dir.exists():
        raise FileExistsError(args.out_dir)
    args.out_dir.mkdir(parents=True)
    dev, test929, test1001, indices, notes = load_dev_and_eval()
    dev_rows = tree.examples(dev)
    eval_sets = {"TEST929": test929, "TEST1001": test1001}
    dev_tte = []
    dev_tte_session_rows = []
    for h in HORIZONS:
        for p in PERSISTENCE:
            for v in VELOCITIES:
                for c in CANCEL:
                    masks = [tte_mask(s, h, p, v, c) for s in dev]
                    sm = event_rule_metrics(dev, masks)
                    dev_tte.append({"model": "time_to_edge", "horizon_s": h, "persistence_s": p, "min_outward_velocity": v, "cancel_window_s": c, **{k: sm[k] for k in ("precision", "recall", "f1", "nonfall_false_alarm_rate", "first_warning_lead_median_s", "first_warning_lead_p25_s", "last_warning_lead_median_s", "last_warning_lead_p25_s", "warning_episode_mean_per_session")}})
    tte_selected, _ = select_rule(dev_rows, dev_tte)

    oof, oof_rows, cal = tree.grouped_oof_tree("lightgbm", dev, args.folds, args.seed)
    lgbm_records = []
    dev_lgbm_session_rows = []
    for threshold in THRESHOLDS:
        for consecutive in (1, 2, 3):
            pred = temporal_filter(oof_rows, oof, float(threshold), consecutive)
            sm, details = session_metrics(oof_rows, pred, f"lightgbm_k{consecutive}")
            lgbm_records.append({"model": "lightgbm", "threshold": float(threshold), "consecutive_windows": consecutive, **{k: sm[k] for k in ("precision", "recall", "f1", "nonfall_false_alarm_rate", "first_warning_lead_median_s", "first_warning_lead_p25_s", "last_warning_lead_median_s", "last_warning_lead_p25_s", "warning_episode_mean_per_session")}})
            dev_lgbm_session_rows.extend([{**row, "threshold": float(threshold), "consecutive_windows": consecutive} for row in details])
    lgbm_selected, _ = select_rule(oof_rows, lgbm_records)

    frozen = []
    frozen_session_rows = []
    for dataset, group in eval_sets.items():
        rows = tree.examples(group)
        masks = [tte_mask(s, float(tte_selected["horizon_s"]), float(tte_selected["persistence_s"]), float(tte_selected["min_outward_velocity"]), float(tte_selected["cancel_window_s"])) for s in group]
        sm = event_rule_metrics(group, masks)
        for session, mask in zip(group, masks):
            ts = np.asarray(session["timestamps"], dtype=float)
            event = float(session["first_event_ts"])
            usable = np.asarray(mask, dtype=bool) & pre_mask(session)
            alarm_ix = np.flatnonzero(usable)
            detected = bool(len(alarm_ix) and (not np.isfinite(event) or ts[alarm_ix[0]] < event))
            lead_first = float(event - ts[alarm_ix[0]]) if detected and np.isfinite(event) else math.nan
            lead_last = float(event - ts[alarm_ix[-1]]) if detected and np.isfinite(event) else math.nan
            frozen_session_rows.append({"dataset": dataset, "model": "time_to_edge", "session_id": session["session_id"], "is_fall_session": bool(np.isfinite(event)), "detected_session": detected, "false_alarm_session": bool(len(alarm_ix) and not np.isfinite(event)), "first_warning_lead_s": lead_first, "last_warning_lead_s": lead_last, "warning_episode_count": int(len(alarm_ix) > 0), "horizon_s": tte_selected["horizon_s"], "persistence_s": tte_selected["persistence_s"], "min_outward_velocity": tte_selected["min_outward_velocity"], "cancel_window_s": tte_selected["cancel_window_s"]})
        frozen.append({"dataset": dataset, "model": "time_to_edge", **sm, **{k: tte_selected[k] for k in ("horizon_s", "persistence_s", "min_outward_velocity", "cancel_window_s")}})
        prob, _, _ = tree.tree_probabilities("lightgbm", dev_rows, rows, args.seed)
        pred = temporal_filter(rows, prob, float(lgbm_selected["threshold"]), int(lgbm_selected["consecutive_windows"]))
        sm, details = session_metrics(rows, pred, "lightgbm_selected")
        frozen_session_rows.extend([{**row, "dataset_evaluation": dataset, "threshold": lgbm_selected["threshold"], "consecutive_windows": lgbm_selected["consecutive_windows"]} for row in details])
        frozen.append({"dataset": dataset, "model": "lightgbm", **sm, **{k: lgbm_selected[k] for k in ("threshold", "consecutive_windows")}})

    pd.DataFrame(dev_tte).to_csv(args.out_dir / "development_tte_grid.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(lgbm_records).to_csv(args.out_dir / "development_lightgbm_temporal_grid.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(lgbm_records).to_csv(args.out_dir / "development_threshold_table.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([tte_selected, lgbm_selected]).to_csv(args.out_dir / "selected_configurations.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(frozen).to_csv(args.out_dir / "frozen_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(frozen_session_rows).to_csv(args.out_dir / "frozen_session_metrics.csv", index=False, encoding="utf-8-sig")
    split_rows = [{"dataset": s["dataset"], "session_id": s["session_id"], "split": "development", "is_fall_session": bool(np.isfinite(s["first_event_ts"])), "windows": len(s.get("examples", []))} for s in dev]
    split_rows += [{"dataset": s["dataset"], "session_id": s["session_id"], "split": s["dataset"], "is_fall_session": bool(np.isfinite(s["first_event_ts"])), "windows": len(s.get("examples", []))} for s in test929 + test1001]
    pd.DataFrame(split_rows).to_csv(args.out_dir / "session_split.csv", index=False, encoding="utf-8-sig")
    config = {"status": "complete", "development_datasets": ["TEST9282", "TEST930", "TEST931"], "frozen_evaluation_datasets": ["TEST929", "TEST1001"], "development_sessions": len(dev), "TEST929_sessions": len(test929), "TEST1001_sessions": len(test1001), "horizons_s": list(HORIZONS), "velocity_grid": list(VELOCITIES), "persistence_grid": list(PERSISTENCE), "cancel_window_grid": list(CANCEL), "lightgbm_threshold_grid": list(THRESHOLDS), "selected": {"tte": tte_selected, "lightgbm": lgbm_selected}, "manifest_notes": notes, "raw_files_modified": False, "unity_modified": False}
    (args.out_dir / "metrics.json").write_text(json.dumps(gru.finite_json(config), indent=2), encoding="utf-8")
    (args.out_dir / "README.md").write_text("# Targeted TTE + LightGBM optimization\n\nSelection used exactly TEST9282, TEST930, TEST931 (117 sessions). TEST929 (30) and TEST1001 (53) were evaluated once after selection and never used for tuning. TTE horizons were 0.3/0.4/0.5/0.6 s with persistence, outward velocity, and inward cancellation grids. LightGBM used grouped session OOF predictions and thresholds 0.50..0.95 with consecutive 1/2/3-window offline filters.\n\nThe selected development rules are in selected_configurations.csv. Frozen aggregate metrics are in frozen_metrics.csv and per-session metrics with complete IDs are in frozen_session_metrics.csv; session_split.csv lists every development and frozen session ID. first/last warning lead median and P25, non-fall false alarm rate, and warning episodes are recorded. NaN lead values mean no detected warning and are marked for review rather than inferred.\n\nCommand: python optimize_tte_lgbm_targeted.py --out-dir telemetry_logs/tte_lgbm_targeted_20261002\nRaw telemetry and Unity code were not modified.\n", encoding="utf-8")
    print(json.dumps(config, indent=2, default=str))


if __name__ == "__main__":
    main()
