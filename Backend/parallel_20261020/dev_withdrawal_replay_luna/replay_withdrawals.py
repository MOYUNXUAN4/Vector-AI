"""Replay the fixed development TTE policy and describe alarm withdrawals."""
from __future__ import annotations
import csv, hashlib, importlib.util, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FIT = ROOT / "parallel_20261014" / "command055_fit_luna"
LABEL = ROOT / "parallel_20261014" / "risk_windows_luna" / "window_feasibility.csv"
BENCH = ROOT / "parallel_20261014" / "control055_check_primary"
REPLAY_PATH = ROOT / "parallel_20261013" / "s055_locked_replay_luna" / "replay.py"
POLICY_PATH = ROOT / "parallel_20261010" / "backend" / "alarm_policy.py"
RAW_ROOT = ROOT / "telemetry_logs" / "INPUT055_CHECK"
INPUTS = [FIT / "ordered_features.csv", FIT / "session_manifest.csv", LABEL,
          BENCH / "benchmark_proximity_tte.py", BENCH / "proximity_independent_scorer.py",
          REPLAY_PATH, POLICY_PATH, BENCH / "proximity_tte_primary.json"]
JOIN_KEYS = ["session_id", "run_id", "source_sequence", "csv_row", "segment_id"]
THRESHOLD, HORIZON, MAX_GAP = 0.5, 0.75, 0.1

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def read_csv(path):
    with path.open("r", newline="", encoding="utf-8-sig") as f: return list(csv.DictReader(f))

def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError): return None

def truth(value): return str(value).strip().lower() in {"true", "1", "yes"}

def load_replay_module():
    """Load pure functions only; never call its disk-writing run_replay()."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("fixed_tte_replay_functions", REPLAY_PATH)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {REPLAY_PATH}")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def identity(r):
    return tuple(str(r.get(k, "")) for k in JOIN_KEYS)

def movement(v, prev_v):
    if v is None: return "missing"
    if v < -0.05: return "inward"
    if v > 0 and prev_v is not None and v < prev_v: return "outward_slower_than_previous"
    if v > 0: return "outward_other"
    return "nearzero"

def decision_movement(previous, current):
    if previous is None:
        return "missing"
    dt = current["_time"] - previous["_time"]
    if previous["_context"] != current["_context"] or not (0 < dt <= MAX_GAP + 1e-9):
        return "not_comparable_across_boundary"
    return movement(number(current.get("radial_outward_velocity")),
                    number(previous.get("radial_outward_velocity")))

def domain_reason(r):
    q, v = number(r.get("q")), number(r.get("radial_outward_velocity"))
    if not truth(r.get("causal_prediction_available")): return "causal_unavailable"
    if q is None or v is None: return "source_invalid"
    if q <= 0: return "domain_q_nonpositive"
    if v <= 0: return "domain_velocity_nonpositive"
    return "domain_valid"

def prepare_rows():
    features, labels = read_csv(FIT / "ordered_features.csv"), read_csv(LABEL)
    label_index = {tuple(r[k] for k in JOIN_KEYS): r for r in labels}
    if len(label_index) != len(labels): raise ValueError("duplicate label join key")
    out, seen = [], set()
    for src in features:
        key = tuple(src[k] for k in JOIN_KEYS)
        if key in seen: raise ValueError(f"duplicate feature key {key}")
        seen.add(key)
        label = label_index.get(key)
        if label is None: raise ValueError(f"missing label for {key}")
        r = dict(src)
        for k in ("status", "label", "reason", "event_lower_time", "event_upper_time"): r[k] = label.get(k, "")
        d, radius, v = number(src.get("directional_edge_distance")), number(src.get("ball_radius")), number(src.get("radial_outward_velocity"))
        q = d - 2 * radius if d is not None and radius is not None else None
        available = truth(src.get("causal_prediction_available")) and q is not None and radius is not None and radius > 0 and v is not None and q > 0
        tte = q / v if available and v is not None and v > 0 else None
        raw_on = bool(available and v > 0 and tte <= HORIZON)
        r.update(q=q, tte=tte, probability="1" if raw_on else ("0" if available else "nan"),
                 clearance=src.get("clearance", ""), timestamp_epoch_seconds=src.get("timestamp", ""),
                 geometry_version_id=src.get("geometry_generation_id", ""), joint_recovery=src.get("joint_recovery", "False"),
                 _raw_on_fixed_tte=raw_on, _source_available=available)
        out.append(r)
    if len(seen) != len(label_index): raise ValueError(f"feature/label row mismatch {len(seen)} != {len(label_index)}")
    return out

def classify_withdrawal(prev, cur, result):
    dt = cur["_time"] - prev["_time"]
    if prev["_context"] != cur["_context"]: mechanism = "context_or_source_boundary"
    elif not (0 < dt <= MAX_GAP + 1e-9): mechanism = "gap_boundary"
    elif result.get("reason") == "joint_recovery": mechanism = "joint_recovery"
    elif result.get("reason") == "invalid_input": mechanism = domain_reason(cur)
    elif result.get("reason") == "raw_off": mechanism = "normal_raw_off"
    else: mechanism = "policy_other_inactive"
    v, pv = number(cur.get("radial_outward_velocity")), number(prev.get("radial_outward_velocity"))
    return {
        "withdrawal_mechanism": mechanism, "policy_reason": result.get("reason", ""),
        "previous_identity": "|".join(identity(prev)), "current_identity": "|".join(identity(cur)),
        "previous_time": prev["_time"], "current_time": cur["_time"], "dt_seconds": dt,
        "q": cur.get("q"), "outward_velocity": v, "tte_seconds": cur.get("tte"),
        "onset_outward_velocity": prev.get("_episode_onset_velocity", pv), "previous_outward_velocity": pv,
        "joint_recovery": truth(cur.get("joint_recovery")), "movement_class": movement(v, pv),
        "policy_canceled_by_joint_recovery": bool(result.get("canceled", False)),
        "current_status": cur.get("status", ""), "current_label": cur.get("label", ""),
        "previous_status": prev.get("status", ""), "previous_label": prev.get("label", ""),
        "previous_source_sequence": prev.get("source_sequence", ""), "current_source_sequence": cur.get("source_sequence", ""),
    }

def future_window_summary(local, index, horizon=0.4):
    """Noncausal description after an exit; never used to classify the exit."""
    current = local[index]
    target = current["_time"] + horizon
    selected = []
    last = current
    covered = False
    for row in local[index + 1:]:
        dt = row["_time"] - last["_time"]
        if row["_context"] != current["_context"] or not (0 < dt <= MAX_GAP + 1e-9):
            break
        if row["_time"] > target:
            covered = True
            break
        selected.append(row)
        last = row
        if row["_time"] >= target - 1e-9:
            covered = True
            break
    observed = min(horizon, max(0.0, last["_time"] - current["_time"]))
    if covered:
        observed = horizon
    return {
        "future_0_4s_is_noncause": True,
        "future_0_4s_complete": covered,
        "future_0_4s_observed_seconds": observed,
        "future_0_4s_any_active": any(r["_result"]["active"] for r in selected),
        "future_0_4s_any_saved_joint_recovery": any(truth(r.get("joint_recovery")) for r in selected),
        "future_0_4s_any_q_nonpositive": any(number(r.get("q")) is not None and number(r.get("q")) <= 0 for r in selected),
    }

def run():
    before = {str(p.relative_to(ROOT)): sha(p) for p in INPUTS}
    rows = prepare_rows()
    sessions = read_csv(FIT / "session_manifest.csv")
    raw_hashes = {}
    for s in sessions:
        raw = RAW_ROOT / s["session_id"] / "raw.csv"
        if not raw.is_file(): raise FileNotFoundError(f"missing manifest raw source {raw}")
        actual = sha(raw)
        expected = s["raw_sha256"].strip().lower()
        raw_hashes[str(raw.relative_to(ROOT))] = {"manifest_sha256": expected, "actual_sha256": actual, "match": expected == actual}
    if not all(x["match"] for x in raw_hashes.values()): raise ValueError("manifest raw SHA-256 mismatch")
    replay = load_replay_module()
    session_records = [{"session_id": s["session_id"], "run_id": s["run_id"],
                        "normalized_outcome": s.get("normalized_outcome", ""),
                        "actual_outcome": s.get("actual_outcome", ""), "game_end_time": s.get("game_end_time", "")} for s in sessions]
    played = replay.replay_prediction_stream(rows, THRESHOLD)
    episodes, _ = replay.build_alarm_episodes(played, session_records)
    by_sid = defaultdict(list)
    for r in played: by_sid[r["session_id"]].append(r)
    traces, withdrawals, censored = [], [], []
    status_exposure = defaultdict(lambda: {"eval_seconds": 0.0, "active_seconds": 0.0})
    for sid in sorted(by_sid):
        local = sorted(by_sid[sid], key=lambda r: (r["_time"], int(r.get("source_sequence", 0))))
        for a, b in zip(local, local[1:]):
            dt = b["_time"] - a["_time"]
            if a["_context"] != b["_context"] or not 0 < dt <= MAX_GAP + 1e-9: continue
            cat = a.get("status", "") or "missing"
            status_exposure[cat]["eval_seconds"] += dt
            if a["_result"]["active"]: status_exposure[cat]["active_seconds"] += dt
    episode_by_id = {e["episode_id"]: e for e in episodes}
    for sid in sorted(by_sid):
        local = sorted(by_sid[sid], key=lambda r: (r["_time"], int(r.get("source_sequence", 0))))
        prev = None
        for row_index, r in enumerate(local):
            result = r["_result"]
            # Attach active episode onset velocity from the reference episode rows.
            eid = r.get("episode_id", "")
            if result["active"] and eid in episode_by_id:
                onset = next((x for x in local if x.get("episode_id") == eid), r)
                r["_episode_onset_velocity"] = number(onset.get("radial_outward_velocity"))
            if (prev and prev["_result"]["active"] and not result["active"]
                    and prev["_context"] == r["_context"]
                    and 0 < r["_time"] - prev["_time"] <= MAX_GAP + 1e-9):
                w = classify_withdrawal(prev, r, result)
                ep = episode_by_id.get(prev.get("episode_id", ""), {})
                w.update(session_id=sid, episode_id=prev.get("episode_id", ""),
                         segment_id=prev.get("segment_id", ""), episode_onset_time=ep.get("onset_time", ""))
                if w["withdrawal_mechanism"] == "normal_raw_off":
                    w.update(future_window_summary(local, row_index))
                withdrawals.append(w)
            v = number(r.get("radial_outward_velocity"))
            traces.append({
                "session_id": sid, "run_id": r.get("run_id"), "source_sequence": r.get("source_sequence"),
                "csv_row": r.get("csv_row"), "segment_id": r.get("segment_id"), "timestamp": r["_time"],
                "layer": r.get("layer"), "platform_id": r.get("platform_id"), "geometry_generation_id": r.get("geometry_generation_id"),
                "status": r.get("status", ""), "label": r.get("label", ""), "q": r.get("q"),
                "outward_velocity": v, "tte": r.get("tte"), "causal_prediction_available": truth(r.get("causal_prediction_available")),
                "fixed_tte_raw_on": r.get("_raw_on_fixed_tte"), "probability": r.get("probability"),
                "confirmed": result.get("confirmed"), "active": result.get("active"), "policy_reason": result.get("reason"),
                "joint_recovery": truth(r.get("joint_recovery")),
                "policy_canceled_by_joint_recovery": bool(result.get("canceled", False)),
                "continuous_inward_duration": number(r.get("continuous_inward_duration")),
                "clearance_gain_0_1s": number(r.get("clearance_gain_0_1s")),
                "movement_class": decision_movement(prev, r),
                "previous_identity": "|".join(identity(prev)) if prev else "", "episode_id": eid,
            })
            prev = r
    for ep in episodes:
        if ep.get("duration_bound") in {"context_or_gap", "session_end_no_hold", "game_end"}:
            local = by_sid[ep["session_id"]]
            last_active = next((r for r in local if r.get("episode_id") == ep["episode_id"]
                                and format(r["_time"], ".9f") == ep["last_active_time"]), None)
            following = next((r for r in local if last_active and r["_time"] > last_active["_time"]), None)
            boundary = {
                "boundary_source_sequence": following.get("source_sequence", "") if following else "",
                "boundary_csv_row": following.get("csv_row", "") if following else "",
                "boundary_segment_id": following.get("segment_id", "") if following else "",
                "boundary_timestamp": following.get("_time", "") if following else "",
                "boundary_policy_reason": following.get("_result", {}).get("reason", "") if following else ep.get("end_reason", ""),
                "boundary_joint_recovery_flag": truth(following.get("joint_recovery")) if following else "",
                "boundary_movement_class": "not_comparable_across_boundary" if following and following.get("_context") != (last_active or {}).get("_context") else "",
            }
            censored.append({**ep, **boundary, "boundary_censor_type": ep["duration_bound"],
                             "interpretation": "active interval ends at a context, gap, session, or game boundary; no sustained hold inferred"})
    write_csv(OUT / "decision_traces.csv", traces)
    write_csv(OUT / "episode_withdrawals.csv", withdrawals)
    write_csv(OUT / "boundary_censored_episodes.csv", censored)
    ref = json.loads((BENCH / "proximity_tte_primary.json").read_text(encoding="utf-8"))
    after = {str(p.relative_to(ROOT)): sha(p) for p in INPUTS}
    raw_off = [w for w in withdrawals if w["withdrawal_mechanism"] == "normal_raw_off"]
    summary = {
        "cohort": "31-session original development INPUT055_CHECK", "n_sessions": len(sessions),
        "decision_rows": len(traces), "active_decisions": sum(bool(r["active"]) for r in traces),
        "episode_count": len(episodes), "observed_next_decision_withdrawals": len(withdrawals),
        "boundary_censored_episode_count": len(censored),
        "withdrawal_mechanisms": dict(sorted(Counter(w["withdrawal_mechanism"] for w in withdrawals).items())),
        "withdrawal_policy_reasons": dict(sorted(Counter(w["policy_reason"] for w in withdrawals).items())),
        "withdrawal_movement_classes": dict(sorted(Counter(w["movement_class"] for w in withdrawals).items())),
        "normal_raw_off_future_0_4s_descriptive_noncause": {
            "count": len(raw_off),
            "complete_horizon_count": sum(bool(w.get("future_0_4s_complete")) for w in raw_off),
            "incomplete_or_censored_count": sum(not bool(w.get("future_0_4s_complete")) for w in raw_off),
            "any_later_active_count": sum(bool(w.get("future_0_4s_any_active")) for w in raw_off),
            "any_saved_joint_recovery_flag_count": sum(bool(w.get("future_0_4s_any_saved_joint_recovery")) for w in raw_off),
            "any_q_nonpositive_count": sum(bool(w.get("future_0_4s_any_q_nonpositive")) for w in raw_off),
            "usage": "bounded future description only; excluded from withdrawal mechanism and all labels",
        },
        "saved_status_exposure_seconds": {k: v for k, v in sorted(status_exposure.items())},
        "fixed_tte": {"threshold": THRESHOLD, "horizon_seconds": HORIZON,
                      "q_definition": "directional_edge_distance - 2 * ball_radius",
                      "require_q_positive": True, "require_velocity_positive": True},
        "policy": {"confirmation_points": 2, "max_decision_gap_seconds": MAX_GAP,
                   "immediate_raw_off": True, "joint_recovery_from_saved_input": True,
                   "policy_canceled_by_joint_recovery_count": sum(bool(r["_result"]["canceled"]) for r in played)},
        "reference": {"path": str((BENCH / "proximity_tte_primary.json").relative_to(ROOT)),
                      "available": True, "saved_aggregate_only": True,
                      "event_count": ref.get("event_count"), "event_hits": ref.get("event_hits"),
                      "episodes": ref.get("episodes"), "negative_active_seconds": ref.get("negative_active_seconds"),
                      "total_active_seconds": ref.get("total_active_seconds")},
        "input_source_sha256_before": before, "input_source_sha256_after": after, "input_sources_unchanged": before == after,
        "raw_sources_sha256": raw_hashes, "all_manifest_raw_hashes_match": all(x["match"] for x in raw_hashes.values()),
        "limitations": ["Replay describes saved decisions and does not reconstruct Unity/network/display timing.",
                        "Raw CSV does not include Unity display age; no age values are fabricated.",
                        "Inward velocity is descriptive only; genuine recovery is recorded only when saved joint_recovery is true.",
                        "Saved unknown and other exposure labels remain unchanged; completion is not used to infer human recovery.",
                        "This is descriptive replay, not a model, threshold, lead, F1, or hold experiment."]
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary

if __name__ == "__main__": print(json.dumps(run(), indent=2))
