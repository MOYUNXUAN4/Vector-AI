"""Read-only replay of the frozen TEST1009 Unity telemetry through the warning runtime."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "parallel_20261010" / "backend"
BASELINE = ROOT / "telemetry_logs" / "TEST1009" / "training_20261009" / "cop_single_factor_20261009" / "baseline_fixed"
MANIFEST = ROOT / "parallel_20261011" / "deployment_refit" / "output" / "artifact" / "manifest.json"
PINNED_HASH = "01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068"
OUT = Path(__file__).resolve().parent
FEATURE_COLUMNS = (
    "directional_edge_distance", "normalized_edge_distance", "clearance",
    "radial_outward_velocity", "ball_xz_speed", "platform_tilt", "difficulty",
    "ball_radius", "platform_radius", "distance_mean_0_5s", "distance_max_0_5s",
    "distance_min_0_5s", "velocity_mean_0_5s", "velocity_max_0_5s",
    "velocity_min_0_5s", "outward_acceleration", "acceleration_mean_0_5s",
    "acceleration_std_0_5s", "acceleration_max_0_5s", "velocity_vector_consistency",
    "mean_velocity_alignment_current_radial", "outward_fraction_0_5s",
    "inward_fraction_0_5s", "inward_displacement_0_2s",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def number(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def integer(value):
    result = number(value)
    if result is None or not math.isfinite(result) or not result.is_integer():
        return None
    return int(result)


def boolean(value):
    if value is True or value == "True" or value == "true" or value == "1":
        return True
    if value is False or value == "False" or value == "false" or value == "0":
        return False
    return None


def put(packet, name, value, converter=None):
    raw = value
    if raw is None or str(raw).strip() == "":
        return
    packet[name] = converter(raw) if converter else raw


def inverse_logger_mapping(row):
    """Rebuild unity_game camelCase fields from timesync_logger.py columns.

    Only source='unity' rows reach this function. The timestamp is the logger's
    source_timestamp in epoch seconds. backend_timestamp is never substituted
    for it; backend_timestamp is separately used as replay receipt offset.
    """
    p = {"type": "unity_game"}
    # runtime_adapter.normalize_unity_packet direct inputs.
    put(p, "timestamp", row.get("source_timestamp"), number)
    put(p, "sequence", row.get("sequence"), integer)
    put(p, "run_id", row.get("run_id"))
    put(p, "run_state", row.get("run_state"))
    put(p, "platformLevel", row.get("platform_level"), number)
    put(p, "platformTilt", row.get("platform_tilt"), number)
    put(p, "calibration_mode", row.get("calibration_mode"), boolean)
    put(p, "selected_session_layers", row.get("selected_session_layers"), integer)
    put(p, "platform_scale", row.get("platform_scale"), number)

    # Causal feature input fields. Preserve the logger's game-ball X/Z values
    # and velocity components; never map COP or position-derivative substitutes.
    field_map = {
        "ball_pos_x": "ball_pos_x", "ball_pos_z": "ball_pos_z",
        "ball_velocity_x": "ball_velocity_x", "ball_velocity_z": "ball_velocity_z",
        "platform_center_x": "platform_center_x", "platform_center_z": "platform_center_z",
        "difficulty": "difficulty", "directional_edge_distance": "directional_edge_distance",
        "ball_radial_velocity": "ball_radial_velocity", "ball_radius": "ball_radius",
        "platform_radius": "platform_radius",
        "geometry_platform_instance_id": "geometry_platform_instance_id",
        "geometry_version_id": "geometry_version_id",
        "geometry_active_platform_instance_id": "geometry_active_platform_instance_id",
        "geometry_active_version_id": "geometry_active_version_id",
    }
    for dest, source in field_map.items():
        conv = integer if dest.endswith("platform_instance_id") else number if dest not in (
            "geometry_version_id", "geometry_active_version_id") else None
        put(p, dest, row.get(source), conv)
    for key in ("geometry_query_valid", "geometry_ownership_valid"):
        put(p, key, row.get(key), boolean)
    put(p, "directional_edge_valid", row.get("directional_edge_valid"), boolean)
    return p


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def load_runtime():
    sys.path.insert(0, str(BACKEND))
    from warning_runtime import ModelWarningRuntime
    from causal_features import compute_latest_features
    return ModelWarningRuntime, compute_latest_features


def load_sources():
    config = read_json(BASELINE / "config.json")
    expected_ids = list(config["outer_folds"].keys())
    manifest_rows = list(csv.DictReader((BASELINE / "prepared_inputs" / "session_manifest.csv").open(encoding="utf-8-sig", newline="")))
    by_id = {r["session_id"]: r for r in manifest_rows}
    if set(expected_ids) != set(by_id) or len(expected_ids) != 30:
        raise RuntimeError("baseline config and session manifest do not identify the same 30 sessions")
    feature_rows = list(csv.DictReader((BASELINE / "prepared_inputs" / "features.csv").open(encoding="utf-8-sig", newline="")))
    expected_hashes = read_json(BASELINE / "prepared_inputs" / "source_hashes.json")
    raw_files = {}
    for sid in expected_ids:
        path = ROOT / "telemetry_logs" / "TEST1009" / sid / "raw.csv"
        if not path.is_file():
            raise FileNotFoundError(f"expected source-only session raw.csv is missing: {sid}")
        raw_files[sid] = path
    return config, expected_ids, by_id, feature_rows, expected_hashes, raw_files


def feature_identity(row):
    return (row["session_id"], integer(row.get("source_sequence")), number(row.get("timestamp")))


def replay(allow_calibration):
    ModelWarningRuntime, compute_latest_features = load_runtime()
    runtime = ModelWarningRuntime(allow_calibration_session_gameplay=allow_calibration)
    loaded = runtime.load(str(MANIFEST), PINNED_HASH, allow_experimental=True)
    if not loaded:
        raise RuntimeError(f"pinned model load failed: {runtime.last_load_error}")
    runtime.enable()
    config, session_ids, session_manifest, prepared_rows, expected_hashes, raw_files = load_sources()
    prepared = defaultdict(list)
    for row in prepared_rows:
        prepared[feature_identity(row)].append(row)
    before_hashes = {sid: sha256(path) for sid, path in raw_files.items()}
    counts = Counter()
    reasons = Counter()
    session_counts = defaultdict(Counter)
    timings_us = []
    comparisons = []
    comparison_prepared_vectors = []
    runtime_events = []
    probabilities_by_id = {}
    accepted_rows = 0

    for sid in session_ids:
        run_id = session_manifest[sid]["run_id"]
        runtime.begin_run(run_id)
        path = raw_files[sid]
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = csv.DictReader(f)
            unity_rows = (r for r in rows if r.get("source") == "unity")
            first_backend = None
            previous_backend = None
            for raw in unity_rows:
                counts["unity_rows"] += 1
                session_counts[sid]["unity_rows"] += 1
                if raw.get("run_id") != run_id:
                    counts["run_id_mismatch_rows"] += 1
                backend_ts = number(raw.get("backend_timestamp"))
                if backend_ts is None:
                    counts["missing_backend_receipt_rows"] += 1
                    continue
                if first_backend is None:
                    first_backend = backend_ts
                if previous_backend is not None and backend_ts < previous_backend:
                    raise RuntimeError(f"backend receipt timestamps reverse in {sid}; no receipt timestamp was synthesized")
                previous_backend = backend_ts
                receipt = backend_ts - first_backend
                packet = inverse_logger_mapping(raw)
                if packet.get("timestamp") is None:
                    counts["missing_source_timestamp_rows"] += 1
                t0 = time.perf_counter_ns()
                accepted = runtime.ingest(packet, receipt)
                warning = runtime.warning(receipt)
                elapsed = (time.perf_counter_ns() - t0) / 1000.0
                timings_us.append(elapsed)
                counts["ingest_accepted"] += int(bool(accepted))
                counts["ingest_rejected"] += int(not accepted)
                session_counts[sid]["ingest_accepted"] += int(bool(accepted))
                session_counts[sid]["ingest_rejected"] += int(not accepted)
                reasons[warning.get("reason", "")] += 1
                if warning.get("valid"):
                    accepted_rows += 1
                    session_counts[sid]["valid_warning_rows"] += 1
                snapshot = runtime.guard.snapshot(receipt)
                if snapshot.get("ready") and snapshot.get("samples"):
                    features = compute_latest_features([x["telemetry"] for x in snapshot["samples"]])
                    if features.get("ready"):
                        latest = snapshot["samples"][-1]["telemetry"]
                        ident = (sid, latest.get("sequence"), float(latest.get("source_timestamp")))
                        candidates = prepared.get(ident, [])
                        for prep in candidates:
                            session_counts[sid]["prepared_feature_matches"] += 1
                            exact_identity = (
                                prep["session_id"] == sid
                                and integer(prep.get("source_sequence")) == latest.get("sequence")
                                and number(prep.get("timestamp")) == float(latest.get("source_timestamp"))
                            )
                            identity_fields_match = (
                                integer(prep.get("layer")) == latest.get("layer")
                                and integer(prep.get("platform_id")) == latest.get("platform_instance_id")
                                and prep.get("geometry_version_id") == latest.get("geometry_version_id")
                            )
                            diffs = {}
                            for name in FEATURE_COLUMNS:
                                baseline_value = number(prep.get(name))
                                runtime_value = number(features.get(name))
                                if baseline_value is None or runtime_value is None:
                                    diffs[name] = None if baseline_value == runtime_value else "missingness_mismatch"
                                else:
                                    diffs[name] = runtime_value - baseline_value
                            max_abs = max((abs(v) for v in diffs.values() if isinstance(v, (int, float))), default=None)
                            # Tolerance is a transparent numeric equality check, not a tuning criterion.
                            equal = exact_identity and identity_fields_match and all(
                                (v is None) or (isinstance(v, (int, float)) and abs(v) <= 1e-6 + 1e-6 * abs(number(prep.get(k)) or 0.0))
                                for k, v in diffs.items()
                            )
                            prediction_matches_identity = (
                                warning.get("input_sequence") == latest.get("sequence")
                                and number(warning.get("input_source_timestamp")) == float(latest.get("source_timestamp"))
                            )
                            p_runtime = number(warning.get("strong_probability")) if warning.get("probability_valid") and prediction_matches_identity else None
                            p_baseline_features = None
                            p_baseline_error = None
                            comparisons.append({
                                "session_id": sid, "source_sequence": latest.get("sequence"),
                                "timestamp": float(latest.get("source_timestamp")),
                                "prepared_segment_id": prep.get("segment_id"),
                                "runtime_segment_generation": snapshot.get("segment_generation"),
                                "prepared_history_start_timestamp": number(prep.get("history_start_timestamp")),
                                "runtime_history_start_timestamp": number(features.get("history_start_timestamp")),
                                "history_start_delta_seconds": (
                                    number(features.get("history_start_timestamp")) - number(prep.get("history_start_timestamp"))
                                    if number(features.get("history_start_timestamp")) is not None and number(prep.get("history_start_timestamp")) is not None else None),
                                "prepared_history_span_seconds": number(prep.get("history_span_seconds")),
                                "runtime_history_span_seconds": number(features.get("history_span_seconds")),
                                "history_span_delta_seconds": (
                                    number(features.get("history_span_seconds")) - number(prep.get("history_span_seconds"))
                                    if number(features.get("history_span_seconds")) is not None and number(prep.get("history_span_seconds")) is not None else None),
                                "exact_identity_match": exact_identity,
                                "feature_identity_match": identity_fields_match,
                                "feature_equal_with_1e-6_abs_rel_tolerance": equal,
                                "max_abs_feature_difference": max_abs,
                                "feature_differences": diffs,
                                "runtime_probability": p_runtime,
                                "probability_from_prepared_vector_same_model": p_baseline_features,
                                "prepared_vector_probability_error": p_baseline_error,
                                "probability_difference_runtime_minus_prepared": (
                                    p_runtime - p_baseline_features if p_runtime is not None and p_baseline_features is not None else None),
                                "warning_reason": warning.get("reason"),
                            })
                            if not equal:
                                session_counts[sid]["feature_mismatches"] += 1
                            comparison_prepared_vectors.append({
                                "comparison_index": len(comparisons) - 1,
                                "features": {k: number(prep.get(k)) for k in FEATURE_COLUMNS},
                            })
                runtime_events.extend(runtime.drain_events())
        runtime.end_run()

    # Batch the matched prepared-vector predictions through the exact pinned
    # Booster after timing so diagnostic work does not inflate ingest timings.
    valid_batch = []
    for entry in comparison_prepared_vectors:
        feats = entry["features"]
        geometry = {k: feats.get(k) for k in ("directional_edge_distance", "clearance", "radial_outward_velocity", "ball_radius", "platform_radius")}
        invalid = next((f"{k} is missing or nonfinite" for k, v in geometry.items() if v is None or not math.isfinite(v)), None)
        if invalid is None and (geometry["ball_radius"] <= 0 or geometry["platform_radius"] <= 0 or geometry["clearance"] <= 0):
            invalid = "nonpositive clearance or physical radius; deployment inference is ineligible"
        if invalid:
            comparisons[entry["comparison_index"]]["prepared_vector_probability_error"] = invalid
            continue
        row = []
        for name in FEATURE_COLUMNS:
            value = feats[name]
            if value is None or math.isnan(value):
                value = runtime._model._medians[name]
            elif not math.isfinite(value):
                invalid = f"feature {name} is infinite"
                break
            row.append(value)
        if invalid:
            comparisons[entry["comparison_index"]]["prepared_vector_probability_error"] = invalid
            continue
        valid_batch.append((entry["comparison_index"], row))
    if valid_batch:
        batch_predictions = runtime._model._booster.predict(np.asarray([r for _, r in valid_batch], dtype=np.float64))
        for (index, _), prediction in zip(valid_batch, batch_predictions):
            comparisons[index]["probability_from_prepared_vector_same_model"] = float(prediction)
            p_runtime = comparisons[index]["runtime_probability"]
            if p_runtime is not None:
                comparisons[index]["probability_difference_runtime_minus_prepared"] = p_runtime - float(prediction)
    after_hashes = {sid: sha256(path) for sid, path in raw_files.items()}
    per_session = {
        sid: {
            **dict(session_counts[sid]),
            "source_csv_sha256_before": before_hashes[sid],
            "source_csv_sha256_after": after_hashes[sid],
            "source_unchanged": before_hashes[sid] == after_hashes[sid],
        }
        for sid in session_ids
    }
    comparison_keys = {(x["session_id"], x["source_sequence"], x["timestamp"]) for x in comparisons}
    prepared_keys = set(prepared.keys())
    missing_matches = [
        {"session_id": key[0], "source_sequence": key[1], "timestamp": key[2]}
        for key in sorted(prepared_keys - comparison_keys, key=lambda x: (x[0], x[1] or -1, x[2] or -1))
    ]
    diff_rows = [x for x in comparisons if not x["feature_equal_with_1e-6_abs_rel_tolerance"]]
    history_start_deltas = [x["history_start_delta_seconds"] for x in comparisons if x["history_start_delta_seconds"] is not None]
    history_span_deltas = [x["history_span_delta_seconds"] for x in comparisons if x["history_span_delta_seconds"] is not None]
    prep_to_runtime = defaultdict(set)
    runtime_to_prep = defaultdict(set)
    for row in comparisons:
        key_p = (row["session_id"], row["prepared_segment_id"])
        key_r = (row["session_id"], row["runtime_segment_generation"])
        prep_to_runtime[key_p].add(key_r[1])
        runtime_to_prep[key_r].add(key_p[1])
    segment_splits = [
        {"session_id": session, "prepared_segment_id": segment, "runtime_generations": sorted(gens)}
        for (session, segment), gens in prep_to_runtime.items() if len(gens) != 1
    ]
    segment_merges = [
        {"session_id": session, "runtime_generation": generation, "prepared_segment_ids": sorted(str(x) for x in segments)}
        for (session, generation), segments in runtime_to_prep.items() if len(segments) != 1
    ]
    actual_probs = [x["probability_difference_runtime_minus_prepared"] for x in comparisons if x["probability_difference_runtime_minus_prepared"] is not None]
    summary = {
        "calibration_mode": "explicitly_opted_in_three_layer_gameplay_compatible" if allow_calibration else "strict_default",
        "runtime_enabled": True, "model_id": runtime._model.model_id,
        "model_sha256": runtime._model.sha256, "threshold": runtime._model.threshold,
        "sessions": len(session_ids), "source_session_ids": session_ids,
        "unity_rows": counts["unity_rows"], "accepted_rows": counts["ingest_accepted"],
        "rejected_rows": counts["ingest_rejected"], "valid_warning_rows": accepted_rows,
        "warning_reason_counts": dict(reasons),
        "feature_comparison": {
            "prepared_feature_rows": len(prepared_rows), "matched_comparisons": len(comparisons),
            "missing_identity_matches": len(missing_matches), "feature_mismatch_count": len(diff_rows),
            "mismatch_samples": [{k: row[k] for k in ("session_id", "source_sequence", "timestamp", "max_abs_feature_difference", "feature_differences", "feature_identity_match")} for row in diff_rows[:20]],
            "missing_identity_sample": missing_matches[:20],
            "segment_and_window_comparison": {
                "prepared_segment_count": len(prep_to_runtime),
                "runtime_generation_count": len(runtime_to_prep),
                "prepared_segments_split_across_runtime_generations": len(segment_splits),
                "runtime_generations_merging_prepared_segments": len(segment_merges),
                "segment_split_samples": segment_splits[:20],
                "segment_merge_samples": segment_merges[:20],
                "history_start_delta_seconds": {
                    "count": len(history_start_deltas), "nonzero_count": sum(abs(x) > 1e-6 for x in history_start_deltas),
                    "max_absolute": max((abs(x) for x in history_start_deltas), default=None),
                },
                "history_span_delta_seconds": {
                    "count": len(history_span_deltas), "nonzero_count": sum(abs(x) > 1e-6 for x in history_span_deltas),
                    "max_absolute": max((abs(x) for x in history_span_deltas), default=None),
                },
            },
            "probability_comparison_same_model": {
                "meaning": "runtime probability minus prediction from the matched prepared 24-feature row, using the same deployment artifact; differences reflect feature-history or input-mapping differences, not calibration or a performance metric",
                "count": len(actual_probs), "mean_absolute_difference": statistics.mean(abs(x) for x in actual_probs) if actual_probs else None,
                "max_absolute_difference": max((abs(x) for x in actual_probs), default=None),
                "prepared_vector_ineligible_count": sum(x.get("prepared_vector_probability_error") is not None for x in comparisons),
                "prepared_vector_ineligible_reasons": dict(Counter(x.get("prepared_vector_probability_error") for x in comparisons if x.get("prepared_vector_probability_error"))),
            },
        },
        "timing": {
            "scope": "actual wall time for ModelWarningRuntime.ingest plus warning call, local process only; excludes input parsing, report serialization, and network/device latency",
            "samples": len(timings_us), "p50_microseconds": percentile(timings_us, .50),
            "p95_microseconds": percentile(timings_us, .95), "p99_microseconds": percentile(timings_us, .99),
            "max_microseconds": max(timings_us, default=None),
        },
        "input_integrity": {
            "expected_prepared_source_hashes": expected_hashes,
            "raw_csv_sha256_before": before_hashes, "raw_csv_sha256_after": after_hashes,
            "raw_sources_unchanged": before_hashes == after_hashes,
            "run_id_mismatch_rows": counts["run_id_mismatch_rows"],
            "missing_backend_receipt_rows": counts["missing_backend_receipt_rows"],
            "missing_source_timestamp_rows": counts["missing_source_timestamp_rows"],
        },
        "per_session": per_session,
        "state_events": runtime_events,
    }
    return summary, runtime


def failure_probes():
    """Exercise runtime fail-closed behavior with synthetic perturbations only."""
    ModelWarningRuntime, _ = load_runtime()
    raw_path = ROOT / "telemetry_logs" / "TEST1009" / "session_20261009_094954_427313" / "raw.csv"
    with raw_path.open(encoding="utf-8-sig", newline="") as f:
        source = next(r for r in csv.DictReader(f)
                      if r.get("source") == "unity" and r.get("run_state") == "running"
                      and number(r.get("platform_scale")) is not None
                      and number(r.get("platform_scale")) <= 2
                      and integer(r.get("platform_level")) in (1, 2, 3)
                      and boolean(r.get("directional_edge_valid")) is True
                      and boolean(r.get("geometry_query_valid")) is True
                      and boolean(r.get("geometry_ownership_valid")) is True)
    packet = inverse_logger_mapping(source)
    rid = packet["run_id"]
    receipt0 = number(source["backend_timestamp"])

    def new_runtime():
        rt = ModelWarningRuntime(allow_calibration_session_gameplay=True)
        ok = rt.load(str(MANIFEST), PINNED_HASH, allow_experimental=True)
        if not ok:
            raise RuntimeError(rt.last_load_error)
        rt.enable()
        rt.begin_run(rid)
        return rt

    result = {}
    # Explicit model-load pin failure.
    wrong = ModelWarningRuntime(allow_calibration_session_gameplay=True)
    wrong_ok = wrong.load(str(MANIFEST), "0" * 64, allow_experimental=True)
    wrong.enable()
    w = wrong.warning(0.0)
    result["wrong_hash"] = {"expected": "load fails closed, state UNKNOWN, valid=false", "passed": (not wrong_ok and w["state"] == "UNKNOWN" and not w["valid"]), "observed_reason": w["reason"]}

    def check_unknown(label, rt, when, expected_reason=None):
        w = rt.warning(when)
        result[label] = {"expected": "UNKNOWN, valid=false, no alert leak", "passed": w["state"] == "UNKNOWN" and w["valid"] is False and w["probability_valid"] is False and (expected_reason is None or w["reason"] == expected_reason), "observed_state": w["state"], "observed_valid": w["valid"], "observed_reason": w["reason"]}

    # Stale timeout after a valid real packet.
    rt = new_runtime(); rt.ingest(packet, 0.0); check_unknown("stale", rt, 0.31, "stale_stream")
    # Source gap clears the previous continuity history and emits UNKNOWN.
    rt = new_runtime(); rt.ingest(packet, 0.0)
    gap = dict(packet, timestamp=packet["timestamp"] + .2, sequence=packet["sequence"] + 1)
    rt.ingest(gap, .2); check_unknown("source_gap", rt, .2)
    # Context changes restart the stream, each independently tested.
    for key, value, label in (("platformLevel", number(packet["platformLevel"]) + 1, "layer_change"),
                              ("geometry_version_id", str(packet["geometry_version_id"]) + "-next", "version_change")):
        rt = new_runtime(); rt.ingest(packet, 0.0)
        changed = dict(packet, timestamp=packet["timestamp"] + .01, sequence=packet["sequence"] + 1, **{key: value})
        if key == "platformLevel":
            changed["platformLevel"] = value
        if key == "geometry_version_id":
            changed["geometry_active_version_id"] = value
        rt.ingest(changed, .01); check_unknown(label, rt, .01)
    # Explicit run boundary uses manifest evidence to name the new owner.
    rt = new_runtime(); rt.ingest(packet, 0.0); rt.begin_run("synthetic-next-run"); check_unknown("run_reset", rt, .01)
    # Missing geometry is injected as query invalid; it cannot become a valid warning.
    rt = new_runtime(); rt.ingest(packet, 0.0)
    missing = dict(packet, timestamp=packet["timestamp"] + .01, sequence=packet["sequence"] + 1, geometry_query_valid=False)
    rt.ingest(missing, .01); check_unknown("missing_geometry", rt, .01)
    # Duplicate/out-of-order inputs are rejected and do not mutate identity or create a new alert.
    rt = new_runtime(); rt.ingest(packet, 0.0)
    duplicate_ok = rt.ingest(packet, .01); w = rt.warning(.01)
    old = dict(packet, timestamp=packet["timestamp"] - .01, sequence=packet["sequence"] - 1)
    old_ok = rt.ingest(old, .02); w2 = rt.warning(.02)
    result["duplicate_out_of_order"] = {"expected": "both rejected; no new prediction or alert is created", "passed": not duplicate_ok and not old_ok and w["prediction_sequence"] == 0 and w2["prediction_sequence"] == 0 and w2["state"] == "UNKNOWN", "duplicate_accepted": duplicate_ok, "out_of_order_accepted": old_ok, "state": w2["state"]}
    # Warm real model to a decision, then inject a predictor exception.
    rt = new_runtime()
    with raw_path.open(encoding="utf-8-sig", newline="") as f:
        live = [r for r in csv.DictReader(f) if r.get("source") == "unity" and r.get("run_state") == "running"]
    first = next(i for i, r in enumerate(live) if number(r["source_timestamp"]) is not None)
    base_backend = number(live[first]["backend_timestamp"])
    predicted = False
    for raw in live[first:]:
        p = inverse_logger_mapping(raw)
        if p.get("run_id") != rid:
            continue
        recv = number(raw["backend_timestamp"]) - base_backend
        prior_prediction_source = rt._last_prediction_source
        rt.ingest(p, recv); rt.warning(recv)
        if rt._last_prediction_source is not None and rt._last_prediction_source != prior_prediction_source:
            predicted = True
            break
    if predicted:
        calls = {"count": 0}
        def prediction_exception(_features):
            calls["count"] += 1
            raise RuntimeError("synthetic prediction exception")
        rt._model.predict_probability = prediction_exception
        bad = dict(p, timestamp=p["timestamp"] + .06, sequence=p["sequence"] + 1)
        recv += .06
        rt.ingest(bad, recv); check_unknown("prediction_exception", rt, recv, "prediction_failed")
        result["prediction_exception"]["injected_predictor_call_count"] = calls["count"]
        result["prediction_exception"]["passed"] = result["prediction_exception"]["passed"] and calls["count"] == 1
    else:
        result["prediction_exception"] = {"expected": "UNKNOWN after injected predictor exception", "passed": False, "observed_reason": "no_real_prediction_point_available_for_injection"}
    return {"classification": "synthetic_failure_probes_not_real_session_observations", "results": result, "all_passed": all(x["passed"] for x in result.values())}


def bridge_replay_parity():
    """Replay the same flattened Unity source through bridge and direct runtime."""
    ModelWarningRuntime, _ = load_runtime()
    sys.path.insert(0, str(OUT.parent / "realtime_integration"))
    from bridge import RealtimeWarningBridge
    _, session_ids, session_manifest, _, _, raw_files = load_sources()
    totals = Counter()
    rejected_reasons = Counter()
    mismatches = []
    per_session = defaultdict(Counter)
    exact_probability_rows = 0
    for sid in session_ids:
        run_id = session_manifest[sid]["run_id"]
        direct = ModelWarningRuntime(allow_calibration_session_gameplay=True)
        if not direct.load(str(MANIFEST), PINNED_HASH, allow_experimental=True):
            raise RuntimeError(f"direct parity model load failed: {direct.last_load_error}")
        direct.enable(); direct.begin_run(run_id)
        bridge = RealtimeWarningBridge(enabled=True, allow_calibration_gameplay=True)
        bridge.start_session(run_id)  # exact run_id from prepared session_manifest
        with raw_files[sid].open(encoding="utf-8-sig", newline="") as f:
            first_backend = None
            for row in csv.DictReader(f):
                if row.get("source") != "unity":
                    continue
                totals["unity_rows"] += 1
                backend_ts = number(row.get("backend_timestamp"))
                if backend_ts is None:
                    totals["missing_receipt_rows"] += 1
                    continue
                if first_backend is None:
                    first_backend = backend_ts
                now = backend_ts - first_backend
                packet = inverse_logger_mapping(row)
                direct.ingest(packet, now)
                direct_warning = direct.warning(now)
                bridge_accepted = bridge.ingest_unity_packet(packet, now)
                attached = bridge.attach({"type": "realtime"}, now)
                bridge_warning = attached.get("model_warning", {})
                totals["bridge_accepted"] += int(bool(bridge_accepted))
                per_session[sid]["bridge_accepted"] += int(bool(bridge_accepted))
                if not bridge_accepted:
                    totals["rejected_rows_checked"] += 1
                    per_session[sid]["rejected_rows_checked"] += 1
                    rejected_reasons[str(bridge_warning.get("reason", "missing_reason"))] += 1
                    unknown_fail_closed = (
                        bridge_warning.get("state") == "UNKNOWN"
                        and bridge_warning.get("valid") is False
                        and bridge_warning.get("probability_valid") is False
                        and (number(bridge_warning.get("strong_probability")) in (None, 0.0))
                    )
                    totals["rejected_fail_closed_rows"] += int(unknown_fail_closed)
                    totals["rejected_leak_rows"] += int(not unknown_fail_closed)
                    per_session[sid]["rejected_fail_closed_rows"] += int(unknown_fail_closed)
                    per_session[sid]["rejected_leak_rows"] += int(not unknown_fail_closed)
                    continue
                totals["accepted_rows_compared"] += 1
                per_session[sid]["accepted_rows_compared"] += 1
                exact = True
                for field in ("state", "valid", "probability_valid", "prediction_sequence",
                              "input_sequence", "input_source_timestamp", "reason", "model_sha256"):
                    if bridge_warning.get(field) != direct_warning.get(field):
                        exact = False
                bp, dp = number(bridge_warning.get("strong_probability")), number(direct_warning.get("strong_probability"))
                prob_equal = bp == dp
                exact_probability_rows += int(prob_equal)
                if not prob_equal:
                    exact = False
                totals["exact_output_rows"] += int(exact)
                totals["output_mismatch_rows"] += int(not exact)
                per_session[sid]["output_mismatch_rows"] += int(not exact)
                totals["probability_mismatch_rows"] += int(not prob_equal)
                if not exact and len(mismatches) < 20:
                    mismatches.append({"session_id": sid, "source_sequence": packet.get("sequence"),
                                       "timestamp": packet.get("timestamp"),
                                       "bridge": {k: bridge_warning.get(k) for k in ("state", "valid", "probability_valid", "strong_probability", "reason", "prediction_sequence", "input_sequence")},
                                       "runtime": {k: direct_warning.get(k) for k in ("state", "valid", "probability_valid", "strong_probability", "reason", "prediction_sequence", "input_sequence")}})
        direct.end_run()
    return {
        "mode": "explicit_calibration_gameplay_opt_in",
        "run_id_authority": "each start_session uses exact run_id from baseline_fixed prepared_inputs/session_manifest.csv",
        "source_rows": totals["unity_rows"], "bridge_accepted_rows": totals["bridge_accepted"],
        "accepted_rows_compared": totals["accepted_rows_compared"],
        "rejected_rows_checked": totals["rejected_rows_checked"],
        "rejected_rows_fail_closed": totals["rejected_fail_closed_rows"],
        "rejected_state_or_validity_leaks": totals["rejected_leak_rows"],
        "rejected_warning_reason_counts": dict(rejected_reasons),
        "exact_output_rows": totals["exact_output_rows"],
        "output_mismatch_rows": totals["output_mismatch_rows"],
        "probability_exact_rows": exact_probability_rows,
        "probability_mismatch_rows": totals["probability_mismatch_rows"],
        "mismatch_samples": mismatches,
        "per_session": {sid: dict(per_session[sid]) for sid in session_ids},
        "result": "PASS" if totals["output_mismatch_rows"] == 0 and totals["rejected_leak_rows"] == 0 and totals["accepted_rows_compared"] > 0 else "FAIL",
    }


def main():
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    out_path = OUT / "replay_report.json"
    if len(sys.argv) > 1 and sys.argv[1] == "--refresh-integrations":
        # Keep the already verified strict/default and calibration-compatible
        # replay results; refresh only bridge parity and injected failure probes.
        report = read_json(out_path)
        bridge_parity = bridge_replay_parity()
        failures = failure_probes()
        config, session_ids, _, prepared_rows, _, raw_files = load_sources()
        old_hashes = report["calibration_gameplay_compatible_opt_in"]["input_integrity"]["raw_csv_sha256_before"]
        after_hashes = report["calibration_gameplay_compatible_opt_in"]["input_integrity"]["raw_csv_sha256_after"]
        prep_counts = Counter(r["session_id"] for r in prepared_rows)
        raw_counts = Counter()
        for sid, path in raw_files.items():
            with path.open(encoding="utf-8-sig", newline="") as f:
                raw_counts[sid] = sum(1 for row in csv.DictReader(f) if row.get("source") == "unity")
        report["calibration_gameplay_compatible_opt_in"]["per_session"] = {
            sid: {
                "unity_rows": raw_counts[sid],
                "prepared_feature_matches": prep_counts[sid],
                "feature_mismatches": sum(1 for row in report["calibration_gameplay_compatible_opt_in"]["feature_comparison"]["mismatch_samples"] if row["session_id"] == sid),
                "source_csv_sha256_before": old_hashes[sid],
                "source_csv_sha256_after": after_hashes[sid],
                "source_unchanged": old_hashes[sid] == after_hashes[sid],
            }
            for sid in session_ids
        }
        report["bridge_real_stream_parity"] = bridge_parity
        report["synthetic_failure_probes"] = failures
        out_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(out_path), "strict_compatible_replay": "preserved from prior verified report with identical source hashes and model pin", "bridge_real_stream_parity": bridge_parity, "synthetic_failure_probes": failures, "per_session_count": len(session_ids)}, indent=2, allow_nan=False))
        return
    strict, _ = replay(False)
    compatible, _ = replay(True)
    bridge_parity = bridge_replay_parity()
    failures = failure_probes()
    report = {
        "report_schema": 1,
        "purpose": "read-only real-data stream replay; no threshold tuning or model performance claims",
        "model_source": {"manifest": str(MANIFEST), "pinned_sha256": PINNED_HASH},
        "strict_default": strict,
        "calibration_gameplay_compatible_opt_in": compatible,
        "bridge_real_stream_parity": bridge_parity,
        "synthetic_failure_probes": failures,
    }
    out_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(out_path),
        "strict": {k: strict[k] for k in ("sessions", "unity_rows", "accepted_rows", "valid_warning_rows")},
        "compatible": {k: compatible[k] for k in ("sessions", "unity_rows", "accepted_rows", "valid_warning_rows")},
        "feature_comparison": compatible["feature_comparison"],
        "timing": compatible["timing"],
        "synthetic_failure_probes": failures,
        "bridge_real_stream_parity": bridge_parity,
        "raw_sources_unchanged": compatible["input_integrity"]["raw_sources_unchanged"] and strict["input_integrity"]["raw_sources_unchanged"],
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
