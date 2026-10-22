"""Independent TEST1012 causal-feature and terminal-anchor audit.

Reads the current cohort raw CSVs, diagnostic JSONL, and prepared tables. It
does not fit models, alter source files, or read any earlier/frozen cohort.
"""
from __future__ import annotations

from collections import Counter, deque
from pathlib import Path
import hashlib
import json
import math
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PREP = ROOT / "test1012_formal_prepare"
FEATURES = PREP / "features.csv"
ASSOCIATIONS = PREP / "source_associations.csv"
MANIFEST = PREP / "session_manifest.csv"
PREP_ANCHORS = PREP / "event_anchors.csv"
BACKEND = ROOT.parent
sys.path.insert(0, str(BACKEND / "parallel_20261010" / "backend"))
from causal_features import compute_latest_features, FEATURE_NAMES  # noqa: E402

HISTORY_SECONDS = 0.5
DECISION_STRIDE_SECONDS = 0.05
MAX_SOURCE_GAP_SECONDS = 0.1
GAMEPLAY_LAYERS = (1, 2, 3)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def num(value) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def truth(value) -> bool:
    return str(value).strip().lower() in {"true", "1"}


def canon(value) -> str:
    n = num(value)
    return str(int(n)) if math.isfinite(n) and n.is_integer() else str(value).strip()


def finite_equal(a, b) -> bool:
    if pd.isna(a) or pd.isna(b):
        return pd.isna(a) and pd.isna(b)
    return str(a) == str(b)


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def replay_features(expected: pd.DataFrame, associations: pd.DataFrame) -> dict:
    maximum = {name: 0.0 for name in FEATURE_NAMES}
    mismatch_count = 0
    mismatch_examples = []
    missing, unexpected, context_mismatches = [], [], []
    matched_rows = 0
    raw_hashes_before, jsonl_hashes_before = {}, {}
    session_details = []
    calibration_modes = Counter()

    required = set(FEATURE_NAMES) | {
        "session_id", "run_id", "timestamp", "source_sequence", "csv_row_id",
        "segment_id", "layer", "history_start_timestamp", "history_span_seconds",
    }
    absent = sorted(required - set(expected.columns))
    if absent:
        raise RuntimeError(f"Prepared features are missing required columns: {absent}")

    for assoc in associations.to_dict("records"):
        sid = str(assoc["session_id"])
        run_id = str(assoc["run_id"])
        raw_path = Path(assoc["raw_path"])
        jsonl_path = Path(assoc["jsonl_path"])
        raw_hash = sha(raw_path)
        json_hash = sha(jsonl_path)
        raw_hashes_before[str(raw_path)] = raw_hash
        jsonl_hashes_before[str(jsonl_path)] = json_hash

        raw = pd.read_csv(raw_path, low_memory=False).copy()
        raw["_csv_row_id"] = np.arange(len(raw)) + 2
        unity = raw[raw["source"].astype(str).str.lower().eq("unity")].copy()
        if set(unity["run_id"].dropna().astype(str)) != {run_id}:
            raise RuntimeError(f"Raw source run_id mismatch for {sid}")
        unity["t"] = pd.to_numeric(unity["source_timestamp"], errors="coerce")
        unity["seq"] = pd.to_numeric(unity["sequence"], errors="coerce")
        unity["layer_n"] = pd.to_numeric(unity["platform_level"], errors="coerce")
        unity["row_id"] = unity["_csv_row_id"]
        scale = pd.to_numeric(unity["platform_scale"], errors="coerce")
        scope = unity["layer_n"].isin(GAMEPLAY_LAYERS) & scale.notna() & scale.le(2.0)
        query_ok = unity["geometry_query_valid"].map(truth)
        owner_ok = unity["geometry_ownership_valid"].map(truth)
        active_match = (
            unity["geometry_active_platform_instance_id"].astype(str)
            .eq(unity["geometry_platform_instance_id"].astype(str))
            & unity["geometry_active_version_id"].astype(str)
            .eq(unity["geometry_version_id"].astype(str))
        )
        directional_ok = unity["directional_edge_valid"].map(truth)
        valid = (
            unity["run_state"].astype(str).str.lower().eq("running")
            & unity["t"].notna() & scope & query_ok & owner_ok & active_match
            & directional_ok
        )
        for col in ("directional_edge_distance", "ball_radial_velocity", "ball_radius", "platform_radius"):
            values = pd.to_numeric(unity[col], errors="coerce")
            valid &= np.isfinite(values)
        eligible = unity[valid].copy().reset_index(drop=True)
        for col in ("directional_edge_distance", "ball_radial_velocity", "ball_velocity_x", "ball_velocity_z",
                    "ball_radius", "platform_radius", "platform_tilt", "difficulty"):
            eligible[col] = pd.to_numeric(eligible[col], errors="coerce")
        eligible["platform_id"] = eligible["geometry_platform_instance_id"].map(canon)
        eligible["generation"] = eligible["geometry_version_id"].astype(str)
        calibration_modes.update(eligible["calibration_mode"].astype(str).str.lower())

        baseline = expected[expected["session_id"].astype(str).eq(sid)].copy()
        by_row = {int(num(r["csv_row_id"])): r for r in baseline.to_dict("records")}
        generated_rows = {}
        previous = None
        context = None
        samples = deque()
        last_eval = -math.inf
        segment_number = 0
        reset_counts = Counter()
        expected_run_rows = unity[unity.run_state.astype(str).str.lower().eq("ended")]
        terminal_candidates = expected_run_rows[expected_run_rows.session_outcome.astype(str).str.strip().ne("")]
        terminal_row = (terminal_candidates.sort_values("_csv_row_id").iloc[-1] if len(terminal_candidates)
                        else unity.sort_values("_csv_row_id").iloc[-1])
        cutoff = num(terminal_row.get("fall_event_backend_timestamp"))
        if not math.isfinite(cutoff):
            cutoff = num(terminal_row.get("session_end_backend_timestamp"))

        for row in eligible.to_dict("records"):
            key = (run_id, int(row["layer_n"]), row["platform_id"], row["generation"])
            t = float(row["t"])
            seq = int(row["seq"])
            identity_reset = previous is not None and key != context
            time_gap_reset = previous is not None and not 0 < t - previous["t"] <= MAX_SOURCE_GAP_SECONDS
            sequence_reset = previous is not None and seq - previous["seq"] != 1
            reset = previous is None or identity_reset or time_gap_reset or sequence_reset
            if reset:
                segment_number += 1
                reset_counts["segment_start"] += 1
                reset_counts["identity_change"] += int(identity_reset)
                reset_counts["time_or_timestamp_gap"] += int(time_gap_reset)
                reset_counts["sequence_gap"] += int(sequence_reset)
                samples.clear()
                first_eval = t + HISTORY_SECONDS
                last_eval = -math.inf
            # The terminal/event timestamp is a strict cutoff for input rows.
            # The row at/after the event cannot be an input or a prediction.
            if math.isfinite(cutoff) and t >= cutoff:
                continue
            sample = dict(row, source_timestamp=t)
            samples.append(sample)
            previous, context = row, key
            while samples and t - float(samples[0]["source_timestamp"]) > HISTORY_SECONDS + MAX_SOURCE_GAP_SECONDS:
                samples.popleft()
            if t < first_eval or t - last_eval < DECISION_STRIDE_SECONDS - 1e-9:
                continue
            last_eval = t
            vector = compute_latest_features(list(samples))
            if not vector.get("ready"):
                continue
            row_id = int(row["row_id"])
            seq = int(row["seq"])
            generated_rows[row_id] = (seq, float(t), int(row["layer_n"]), key, vector, segment_number)

        expected_rows = set(by_row)
        actual_rows = set(generated_rows)
        for row_id in sorted(expected_rows - actual_rows):
            r = by_row[row_id]
            missing.append({"session_id": sid, "source_sequence": int(num(r["source_sequence"])),
                            "csv_row_id": row_id})
        for row_id in sorted(actual_rows - expected_rows):
            seq, t, layer, _, _, _ = generated_rows[row_id]
            unexpected.append({"session_id": sid, "source_sequence": seq, "csv_row_id": row_id,
                               "timestamp": t, "layer": layer})
        session_match = 0
        actual_to_expected_groups = {}
        expected_to_actual_groups = {}
        for row_id in sorted(actual_rows & expected_rows):
            seq, t, layer, _, vector, replay_segment = generated_rows[row_id]
            target = by_row[row_id]
            expected_segment = str(target["segment_id"])
            actual_to_expected_groups.setdefault(replay_segment, set()).add(expected_segment)
            expected_to_actual_groups.setdefault(expected_segment, set()).add(replay_segment)
            target_seq = int(num(target["source_sequence"]))
            if seq != target_seq:
                context_mismatches.append({"session_id": sid, "csv_row_id": row_id,
                                           "actual_sequence": seq, "expected_sequence": target_seq,
                                           "field": "source_sequence"})
            for field, actual_value in (("timestamp", t), ("layer", layer)):
                expected_value = num(target[field])
                if not (math.isfinite(expected_value) and math.isclose(actual_value, expected_value, rel_tol=0, abs_tol=1e-9)):
                    context_mismatches.append({"session_id": sid, "csv_row_id": row_id,
                                               "source_sequence": seq, "field": field,
                                               "actual": actual_value, "expected": expected_value})
            for name in FEATURE_NAMES:
                actual_value = num(vector[name])
                expected_value = num(target[name])
                if math.isnan(actual_value) and math.isnan(expected_value):
                    continue
                if math.isfinite(actual_value) and math.isfinite(expected_value):
                    maximum[name] = max(maximum[name], abs(actual_value - expected_value))
                if not np.isclose(actual_value, expected_value, rtol=1e-10, atol=1e-10, equal_nan=True):
                    mismatch_count += 1
                    if len(mismatch_examples) < 40:
                        mismatch_examples.append({"session_id": sid, "source_sequence": seq,
                                                  "csv_row_id": row_id, "feature": name,
                                                  "actual": actual_value if math.isfinite(actual_value) else None,
                                                  "expected": expected_value if math.isfinite(expected_value) else None})
            for field in ("history_start_timestamp", "history_span_seconds"):
                actual_value = vector.get(field)
                expected_value = num(target[field])
                actual_num = num(actual_value)
                if not np.isclose(actual_num, expected_value, rtol=0, atol=1e-8, equal_nan=True):
                    context_mismatches.append({"session_id": sid, "csv_row_id": row_id,
                                               "source_sequence": seq, "field": field,
                                               "actual": actual_num if math.isfinite(actual_num) else None,
                                               "expected": expected_value if math.isfinite(expected_value) else None})
            session_match += 1
        segment_partition_mismatch = any(len(v) != 1 for v in actual_to_expected_groups.values()) or any(
            len(v) != 1 for v in expected_to_actual_groups.values())
        if segment_partition_mismatch:
            context_mismatches.append({"session_id": sid, "field": "segment_partition",
                                       "replayed_segment_count": len(actual_to_expected_groups),
                                       "prepared_segment_count": len(expected_to_actual_groups)})
        matched_rows += session_match
        session_details.append({"session_id": sid, "run_id": run_id,
                                "expected_decisions": len(expected_rows), "replayed_decisions": len(actual_rows),
                                "matched_decisions": session_match, "eligible_source_rows": len(eligible),
                                "replayed_segment_count": len(actual_to_expected_groups),
                                "prepared_segment_count": len(expected_to_actual_groups),
                                "reset_counts": dict(reset_counts),
                                "strict_terminal_cutoff": cutoff,
                                "eligible_layer_counts": {str(k): int(v) for k, v in eligible.layer_n.value_counts().sort_index().items()},
                                "raw_sha256_before": raw_hash, "jsonl_sha256_before": json_hash})

    hashes_unchanged = all(sha(Path(p)) == v for p, v in raw_hashes_before.items())
    hashes_unchanged &= all(sha(Path(p)) == v for p, v in jsonl_hashes_before.items())
    return {"expected_decision_rows": len(expected), "replayed_decision_rows": matched_rows,
            "feature_columns": len(FEATURE_NAMES), "feature_cells_compared": matched_rows * len(FEATURE_NAMES),
            "feature_cell_mismatches": mismatch_count, "feature_mismatch_examples": mismatch_examples,
            "missing_decisions": missing, "unexpected_decisions": unexpected,
            "decision_context_mismatches": context_mismatches,
            "max_absolute_error_by_feature": maximum,
            "comparison_tolerance": {"rtol": 1e-10, "atol": 1e-10},
            "eligible_calibration_mode_counts": dict(calibration_modes),
            "raw_and_jsonl_hashes_unchanged": hashes_unchanged,
            "session_details": session_details}


def load_jsonl(path: Path):
    records = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            record["_line"] = line_number
            records.append(record)
    return records


def terminal_audit(associations: pd.DataFrame, manifest: pd.DataFrame) -> dict:
    """Independently bracket geometry events and corroborate raw terminal IDs."""
    out = []
    for assoc in associations.to_dict("records"):
        sid, run_id = str(assoc["session_id"]), str(assoc["run_id"])
        if sid not in set(manifest.session_id.astype(str)):
            raise RuntimeError(f"No manifest row for {sid}")
        m = manifest[manifest.session_id.astype(str).eq(sid)].iloc[0].to_dict()
        raw_path, json_path = Path(assoc["raw_path"]), Path(assoc["jsonl_path"])
        raw = pd.read_csv(raw_path, low_memory=False)
        unity = raw[raw.source.astype(str).str.lower().eq("unity")].copy()
        unity["_row"] = np.arange(len(unity)) + 2
        ended = unity[unity.session_outcome.astype(str).str.strip().ne("")]
        terminal = (ended.sort_values("_row").iloc[-1] if len(ended)
                    else unity.sort_values("_row").iloc[-1]).to_dict()
        records = load_jsonl(json_path)
        own = [(i, r) for i, r in enumerate(records, 1) if str(r.get("run_id", "")) == run_id]
        starts = [(i, r) for i, r in own if r.get("record_type") == "lifecycle" and r.get("lifecycle_event") == "new_run_created"]
        freezes = [(i, r) for i, r in own if r.get("record_type") == "lifecycle" and r.get("lifecycle_event") == "terminal_snapshot_frozen"]
        sends = [(i, r) for i, r in own if r.get("record_type") == "lifecycle" and r.get("lifecycle_event") == "terminal_udp_send_call_completed"]
        lifecycle_ok = len(starts) == len(freezes) == len(sends) == 1 and starts[0][0] < freezes[0][0] < sends[0][0]
        receipt_start = num(starts[0][1].get("backend_timestamp")) if lifecycle_ok else math.nan
        receipt_freeze = num(freezes[0][1].get("backend_timestamp")) if lifecycle_ok else math.nan
        receipt_send = num(sends[0][1].get("backend_timestamp")) if lifecycle_ok else math.nan
        raw_t = num(terminal.get("source_timestamp"))
        raw_terminal_seq = num(terminal.get("sequence"))
        raw_pid = canon(terminal.get("geometry_platform_instance_id"))
        raw_layer = num(terminal.get("platform_level"))
        raw_generation = str(terminal.get("geometry_version_id") or "")
        event_rows = [(i, r) for i, r in own if r.get("event_name") == "edge_exit_predicate_commit"
                      and r.get("valid") is True and str(r.get("event_outcome", "")) == "edge_exit"]
        event = event_rows[-1][1] if event_rows else {}
        event_line = event_rows[-1][0] if event_rows else None
        event_t = num(event.get("event_backend_timestamp"))
        event_seq = num(event.get("event_sequence"))
        event_pid = canon(event.get("event_platform_instance_id")) if event else ""
        last_support = canon(event.get("last_support_platform_instance_id")) if event else ""
        event_layer = num(event.get("event_layer"))
        # Event diagnostic generation/fingerprint is recorded independently of
        # the ordinary generation carried by the CSV and full query snapshots.
        event_diag_generation = str(event.get("geometry_version_id") or "")
        event_identity = bool(event and event_pid == last_support == raw_pid
                              and math.isfinite(event_layer) and math.isfinite(raw_layer)
                              and event_layer == raw_layer
                              and math.isfinite(event_seq) and math.isfinite(raw_terminal_seq)
                              and event_seq == raw_terminal_seq)

        bridge = (pd.to_numeric(unity.source_timestamp, errors="coerce")
                  - pd.to_numeric(unity.geometry_source_timestamp, errors="coerce"))
        bridge = bridge.replace([np.inf, -np.inf], np.nan).dropna()
        bridge_s = float(bridge.median()) if len(bridge) else math.nan
        snapshots = []
        for line, r in own:
            if r.get("record_type") != "full_geometry_snapshot":
                continue
            q_u = num(r.get("diagnostic_fingerprint_query_time"))
            q_unix = q_u + bridge_s if math.isfinite(q_u) and math.isfinite(bridge_s) else math.nan
            ordinary_pid = canon(r.get("ordinary_geometry_platform_instance_id"))
            ordinary_gen = str(r.get("ordinary_geometry_version_id") or "")
            layer = num(r.get("platform_level"))
            distance, radius = num(r.get("directional_edge_distance")), num(r.get("ball_radius"))
            clearance = distance - radius if math.isfinite(distance) and math.isfinite(radius) else math.nan
            valid = bool(
                lifecycle_ok and starts[0][0] < line < sends[0][0]
                and r.get("query_completed") is True and r.get("result_valid") is True
                and r.get("directional_edge_valid") is True
                and r.get("ordinary_geometry_query_valid") is True
                and r.get("ordinary_geometry_ownership_valid") is True
                and str(r.get("ordinary_geometry_active_platform_instance_id")) == str(r.get("ordinary_geometry_platform_instance_id"))
                and str(r.get("ordinary_geometry_active_version_id")) == str(r.get("ordinary_geometry_version_id"))
                and math.isfinite(q_unix) and receipt_start <= q_unix <= receipt_send
                and ordinary_pid not in {"", "None"} and ordinary_gen
                and math.isfinite(layer) and int(layer) in GAMEPLAY_LAYERS
                and math.isfinite(clearance) and math.isfinite(radius) and radius >= 0
            )
            snapshots.append({"line": line, "event_id": r.get("event_id"), "time": q_unix,
                              "query_time_unity": q_u, "platform_id": ordinary_pid,
                              "layer": int(layer) if math.isfinite(layer) else None,
                              "ordinary_generation": ordinary_gen,
                              "fingerprint_generation": str(r.get("diagnostic_fingerprint_version_id") or ""),
                              "distance": distance, "radius": radius, "clearance": clearance,
                              "valid": valid})
        # Do not substitute the sampling trigger timestamp for query time, do
        # not skip invalid intervening snapshots, and do not compare fingerprint
        # versions to ordinary generation IDs.
        brackets = []
        for a, b in zip(snapshots, snapshots[1:]):
            if not (a["valid"] and b["valid"]):
                continue
            identity_a = (a["platform_id"], a["layer"], a["ordinary_generation"])
            identity_b = (b["platform_id"], b["layer"], b["ordinary_generation"])
            if identity_a != identity_b:
                continue
            dt = b["time"] - a["time"]
            if not (math.isfinite(event_t) and 0 < dt and b["time"] <= event_t):
                continue
            if a["clearance"] > 0 >= b["clearance"]:
                brackets.append((a, b, dt, "surface_clearance_zero_crossing"))
            if a["distance"] > 0 >= b["distance"]:
                brackets.append((a, b, dt, "directional_edge_distance_zero_crossing"))
        # Select the latest pre-event crossing for each metric, retaining both
        # raw bounds instead of collapsing to an interpolated event time.
        latest = {}
        for item in brackets:
            metric = item[3]
            if metric not in latest or item[1]["time"] > latest[metric][1]["time"]:
                latest[metric] = item
        anchors = {}
        metric_names = ("surface_clearance_zero_crossing", "directional_edge_distance_zero_crossing")
        metric_column = {"surface_clearance_zero_crossing": "clearance",
                         "directional_edge_distance_zero_crossing": "distance"}
        for metric in metric_names:
            item = latest.get(metric)
            if not item:
                anchors[metric] = {"status": "unknown_no_adjacent_valid_bracket"}
                continue
            a, b, width, _ = item
            value_col = metric_column[metric]
            returned, unresolved = False, False
            for later in (s for s in snapshots if b["line"] < s["line"] < (event_line or 0)):
                if not later["valid"]:
                    unresolved = True
                    break
                if (later["platform_id"], later["layer"], later["ordinary_generation"]) != (
                        b["platform_id"], b["layer"], b["ordinary_generation"]):
                    unresolved = True
                    break
                if later[value_col] > 0:
                    returned = True
                    break
            terminal_proven = bool(event_identity and not returned and not unresolved)
            anchors[metric] = {"status": "bracket_found_not_collapsed", "lower_time": a["time"],
                               "upper_time": b["time"], "width_seconds": width,
                               "lower_value": a[value_col], "upper_value": b[value_col],
                               "positive_return_observed": returned,
                               "return_scan_unresolved": unresolved,
                               "terminal_event_identity_corroborated": event_identity,
                               "terminal_anchor_status": "confirmed" if terminal_proven else "unknown_or_not_terminal",
                               "lower_query_line": a["line"], "upper_query_line": b["line"],
                               "lower_event_id": a["event_id"], "upper_event_id": b["event_id"],
                               "platform_id": a["platform_id"], "layer": a["layer"],
                               "ordinary_generation": a["ordinary_generation"],
                               "lower_fingerprint_generation": a["fingerprint_generation"],
                               "upper_fingerprint_generation": b["fingerprint_generation"],
                               "event_platform_id": event_pid, "event_last_support_platform_id": last_support,
                               "event_layer": event_layer, "event_diagnostic_generation": event_diag_generation,
                               "raw_terminal_platform_id": raw_pid, "raw_terminal_layer": raw_layer,
                               "raw_terminal_generation": raw_generation,
                               "event_identity_matches_raw_terminal": event_identity}
        # Independently retain the raw Unity transition context: last row with
        # positive directional margin before each geometry crossing is a proxy,
        # not a replacement for the full-query bracket.
        running = unity[unity.run_state.astype(str).str.lower().eq("running")].copy()
        running["t"] = pd.to_numeric(running.source_timestamp, errors="coerce")
        running["seq"] = pd.to_numeric(running.sequence, errors="coerce")
        running["clearance"] = (pd.to_numeric(running.directional_edge_distance, errors="coerce")
                                 - pd.to_numeric(running.ball_radius, errors="coerce"))
        raw_proxy = {}
        for metric, col in (("surface_clearance_zero_crossing", "clearance"),
                            ("directional_edge_distance_zero_crossing", "directional_edge_distance")):
            vals = pd.to_numeric(running[col], errors="coerce")
            idx = np.flatnonzero((vals.shift(1) > 0) & (vals <= 0))
            idx = [i for i in idx if math.isfinite(event_t) and num(running.iloc[i].t) <= event_t]
            raw_proxy[metric] = ({"status": "raw_csv_proxy_bracket", "lower_time": num(running.iloc[idx[-1]-1].t),
                                 "upper_time": num(running.iloc[idx[-1]].t),
                                 "lower_sequence": num(running.iloc[idx[-1]-1].seq),
                                 "upper_sequence": num(running.iloc[idx[-1]].seq)} if idx and idx[-1] > 0
                                else {"status": "unknown_no_adjacent_raw_proxy"})

        # Inspect recovery metadata fields instead of dropping joint-recovery
        # observations from the prepared table; future labels are not inputs.
        label_columns = {"joint_recovery", "clearance_gain_0_1s", "continuous_inward_duration"}
        feature_columns = set(pd.read_csv(FEATURES, nrows=0).columns)
        future_label = {"prepared_future_label_columns_present": label_columns.issubset(feature_columns),
                        "future_label_columns_in_24_feature_inputs": sorted(label_columns & set(FEATURE_NAMES)),
                        "feature_row_after_terminal": False}
        expected_feature_rows = pd.read_csv(FEATURES, usecols=lambda c: c in {"session_id", "timestamp"}, low_memory=False)
        if len(expected_feature_rows):
            rows = expected_feature_rows[expected_feature_rows.session_id.astype(str).eq(sid)]
            future_label["feature_row_after_terminal"] = bool(
                math.isfinite(raw_t) and (pd.to_numeric(rows.timestamp, errors="coerce") >= raw_t).any())
        out.append({"session_id": sid, "run_id": run_id, "actual_outcome": str(m.get("actual_outcome", "")),
                    "terminal_receipt_order_valid": lifecycle_ok,
                    "terminal_receipt_timestamps": {"start": receipt_start, "freeze": receipt_freeze, "send": receipt_send},
                    "raw_terminal": {"row_id": int(terminal["_row"]), "sequence": raw_terminal_seq,
                                     "timestamp": raw_t, "platform_id": raw_pid, "layer": raw_layer,
                                     "ordinary_generation": raw_generation,
                                     "run_state": terminal.get("run_state"), "outcome": terminal.get("session_outcome")},
                    "edge_exit_event": {"found": bool(event), "line": event_line,
                                        "timestamp": event_t, "sequence": event_seq,
                                        "platform_id": event_pid, "last_support_platform_id": last_support,
                                        "layer": event_layer,
                                        "diagnostic_generation_separate_from_ordinary": event_diag_generation,
                                        "identity_matches_raw_terminal": event_identity},
                    "median_same_run_clock_bridge_seconds": bridge_s,
                    "valid_full_snapshot_count": sum(s["valid"] for s in snapshots),
                    "invalid_full_snapshot_count": sum(not s["valid"] for s in snapshots),
                    "geometry_bounds": anchors, "raw_csv_crossing_proxy": raw_proxy,
                    "future_label_provenance": future_label})
    return {"sessions": len(out), "edge_exit_sessions": sum(r["actual_outcome"] == "edge_exit" for r in out),
            "edge_exit_event_corroborated_sessions": sum(r["edge_exit_event"]["identity_matches_raw_terminal"] for r in out if r["actual_outcome"] == "edge_exit"),
            "details": out}


def compare_prepared_anchors(terminals: dict) -> dict:
    # Epoch timestamps are ~1.79e9; pandas' default fast parser can round a
    # decimal CSV field by one ULP. Preserve the written decimal value when
    # comparing independent query bounds.
    prepared = pd.read_csv(PREP_ANCHORS, low_memory=False, float_precision="round_trip")
    field_map = {
        "surface_clearance_zero_crossing": "surface_clearance_zero_crossing",
        "directional_edge_distance_zero_crossing": "directional_edge_distance_zero_crossing",
    }
    comparisons, mismatches = [], []
    for detail in terminals["details"]:
        if detail["actual_outcome"] != "edge_exit":
            continue
        sid = detail["session_id"]
        for metric, anchor_type in field_map.items():
            independent = detail["geometry_bounds"][metric]
            rows = prepared[prepared.session_id.astype(str).eq(sid)
                            & prepared.anchor_type.astype(str).eq(anchor_type)]
            row = rows.iloc[0].to_dict() if len(rows) == 1 else {}
            checks = {"unique_prepared_row": len(rows) == 1,
                      "prepared_available": str(row.get("available", "")).lower() == "true",
                      "lower_bound_matches": False, "upper_bound_matches": False,
                      "width_matches": False,
                      "narrow_flag_matches_width": False}
            for name, source in (("lower_bound_matches", "lower_query_time"),
                                 ("upper_bound_matches", "upper_query_time"),
                                 ("width_matches", "interval_width_seconds")):
                prepared_value = num(row.get(source))
                independent_value = num(independent.get({"lower_bound_matches": "lower_time",
                                                         "upper_bound_matches": "upper_time",
                                                         "width_matches": "width_seconds"}[name]))
                checks[name] = bool(math.isfinite(prepared_value) and math.isfinite(independent_value)
                                    and math.isclose(prepared_value, independent_value, rel_tol=0, abs_tol=1e-8))
            narrow = str(row.get("narrow_anchor_le_0_15s", "")).lower() == "true"
            checks["narrow_flag_matches_width"] = bool(
                narrow == (math.isfinite(num(independent.get("width_seconds")))
                           and num(independent.get("width_seconds")) <= 0.15)
            )
            item = {"session_id": sid, "run_id": detail["run_id"], "anchor_type": anchor_type,
                    "independent_anchor_status": independent.get("terminal_anchor_status"),
                    "independent_width_seconds": independent.get("width_seconds"),
                    "prepared_narrow_le_0_15": narrow, "checks": checks,
                    "pass": all(checks.values()) and independent.get("terminal_anchor_status") == "confirmed"}
            comparisons.append(item)
            if not item["pass"]:
                mismatches.append(item)
    return {"anchor_rows_compared": len(comparisons),
            "all_bounds_and_narrow_flags_match": not mismatches,
            "mismatch_count": len(mismatches), "comparisons": comparisons,
            "mismatches": mismatches}


def main():
    expected = pd.read_csv(FEATURES, low_memory=False)
    associations = pd.read_csv(ASSOCIATIONS, low_memory=False)
    manifest = pd.read_csv(MANIFEST, low_memory=False)
    if len(associations) != 15 or associations.run_id.astype(str).nunique() != 15:
        raise RuntimeError("Expected exactly 15 unique run associations")
    if len(expected) != 3849 or expected.session_id.astype(str).nunique() != 15:
        raise RuntimeError("Prepared feature row/session count changed from the current TEST1012 preparation")
    if not set(expected.observation_group.astype(str)) <= {"TEST1012"}:
        raise RuntimeError("Prepared features contain a non-TEST1012 cohort tag")
    if pd.to_numeric(expected.layer, errors="coerce").max() > 3:
        raise RuntimeError("Prepared feature table includes a layer above 3")

    replay = replay_features(expected, associations)
    terminals = terminal_audit(associations, manifest)
    anchor_table_comparison = compare_prepared_anchors(terminals)
    source_hashes_final = {
        str(Path(p)): sha(Path(p))
        for a in associations.to_dict("records") for p in (a["raw_path"], a["jsonl_path"])
    }
    replay_hashes = {s["raw_sha256_before"] for s in replay["session_details"]} | {s["jsonl_sha256_before"] for s in replay["session_details"]}
    source_hashes_final_match = all(value in replay_hashes for value in source_hashes_final.values())
    replay["raw_and_jsonl_hashes_unchanged"] = replay["raw_and_jsonl_hashes_unchanged"] and source_hashes_final_match
    anchor_summary = {
        metric: {
            "edge_exits_with_bounds": sum(d["geometry_bounds"][metric]["status"] == "bracket_found_not_collapsed"
                                           for d in terminals["details"] if d["actual_outcome"] == "edge_exit"),
            "terminal_anchor_confirmed": sum(d["geometry_bounds"][metric]["terminal_anchor_status"] == "confirmed"
                                              for d in terminals["details"] if d["actual_outcome"] == "edge_exit"),
            "narrow_le_0_15_seconds": sum(
                d["geometry_bounds"][metric].get("width_seconds", math.inf) <= 0.15
                for d in terminals["details"] if d["actual_outcome"] == "edge_exit"),
            "minimum_width_seconds": min((d["geometry_bounds"][metric].get("width_seconds", math.inf)
                                           for d in terminals["details"] if d["actual_outcome"] == "edge_exit"), default=math.nan),
            "maximum_width_seconds": max((d["geometry_bounds"][metric].get("width_seconds", -math.inf)
                                           for d in terminals["details"] if d["actual_outcome"] == "edge_exit"), default=math.nan),
        }
        for metric in ("surface_clearance_zero_crossing", "directional_edge_distance_zero_crossing")
    }
    result = {"scope": "TEST1012 current 15-run cohort; independent causal kernel replay and terminal evidence audit",
              "source_features_path": str(FEATURES), "source_associations_path": str(ASSOCIATIONS),
              "source_manifest_path": str(MANIFEST), "feature_replay": replay,
              "terminal_evidence": terminals,
              "prepared_anchor_table_comparison": anchor_table_comparison,
              "edge_exit_geometry_summary_by_metric": anchor_summary,
              "limits": ["No fitting, probability, threshold, warning-policy, live-service or Unity-display evaluation.",
                         "Geometry results preserve observed lower/upper query bounds; any interpolated estimate is omitted.",
                         "Raw CSV crossing intervals are retained as proxies, separate from diagnostic query anchors.",
                         "Sensitivity 0.55/prior 0.66 and both banner states ON are user-provided context, not historical telemetry proof."]}
    result = json_safe(result)
    (HERE / "formal_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": replay["session_details"] and len(replay["session_details"]),
                      "expected_decisions": replay["expected_decision_rows"],
                      "replayed_decisions": replay["replayed_decision_rows"],
                      "feature_cell_mismatches": replay["feature_cell_mismatches"],
                      "missing_decisions": len(replay["missing_decisions"]),
                      "unexpected_decisions": len(replay["unexpected_decisions"]),
                      "context_mismatches": len(replay["decision_context_mismatches"]),
                      "raw_and_jsonl_hashes_unchanged": replay["raw_and_jsonl_hashes_unchanged"],
                      "edge_exit_anchor_summary": anchor_summary,
                      "prepared_anchor_rows_match": anchor_table_comparison["all_bounds_and_narrow_flags_match"]}, ensure_ascii=False))
    if (replay["feature_cell_mismatches"] or replay["missing_decisions"] or replay["unexpected_decisions"]
            or replay["decision_context_mismatches"] or not replay["raw_and_jsonl_hashes_unchanged"]
            or not anchor_table_comparison["all_bounds_and_narrow_flags_match"]
            or any(v["terminal_anchor_confirmed"] != 7 for v in anchor_summary.values())):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
