"""Prepare causal TEST1012 features and query-time geometry evidence; no fitting."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


BACKEND = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend")
OUTDIR = BACKEND / "parallel_20261012" / "test1012_formal_prepare"
RAW_ROOT = BACKEND / "telemetry_logs" / "TEST1012"
JSONL_ROOT = Path(r"C:\Users\QIYUXUAN\AppData\LocalLow\QI YUXUAN\VectorAI\EndlessFallingDiagnostics")
JSONL_GLOB = "samples_20261012_12*.jsonl"
BASE_PREP = BACKEND / "telemetry_logs" / "DEV_MATCHED_A" / "analysis_20261009" / "prepared" / "prepare.py"
FEATURE_HELPER = BACKEND / "telemetry_logs" / "Test10052" / "model_comparison_20261005" / "prepare_features.py"
MAX_GAP = 0.1
PLATFORM_SCALE_MAX = 2.0
GAMEPLAY_LAYERS = (1, 2, 3)
SENSITIVITY = 0.55
PRIOR_SENSITIVITY = 0.66


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def canon(x):
    v = num(x)
    return str(int(v)) if np.isfinite(v) and v.is_integer() else str(x).strip()


def load_reviewed_feature_code():
    # Load reviewed preparation code but repair its helper path to the actual code-only location.
    src = BASE_PREP.read_text(encoding="utf-8")
    old = "HELPER=BASE/'Test10052'/'model_comparison_20261005'/'prepare_features.py'"
    new = f"HELPER=Path(r'{FEATURE_HELPER}')"
    if old not in src:
        raise RuntimeError("Reviewed preparation source no longer matches the expected code-only loader")
    namespace = {"__name__": "test1012_reviewed_preparer", "__file__": str(BASE_PREP)}
    exec(compile(src.replace(old, new), str(BASE_PREP), "exec"), namespace)
    # Rebind only to this isolated preparation workspace. Never invoke the old main().
    namespace["HERE"] = OUTDIR
    namespace["COHORT"] = OUTDIR
    namespace["EXTRACTION"] = OUTDIR / "source_associations.csv"
    namespace["MAX_GAP"] = MAX_GAP
    return namespace, namespace["helper"]


def read_json_lines(blob: bytes):
    records, errors = [], []
    for ix, line in enumerate(blob.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append((ix, json.loads(line)))
        except Exception as exc:
            errors.append({"line_index": ix, "error": type(exc).__name__})
    return records, errors


def truth(value):
    return str(value).strip().lower() in ("1", "true", "yes")


def identity(row):
    return (str(row.get("run_id", "")), num(row.get("platform_level")),
            canon(row.get("ordinary_geometry_platform_instance_id", "")),
            str(row.get("ordinary_geometry_version_id", "")))


def snapshot_rows(records, run_id, offset, receipt_start_ix, receipt_send_ix, receipt_start_t, receipt_freeze_t, receipt_send_t):
    snaps, exclusions, errors = [], [], []
    for line_ix, row in records:
        if str(row.get("run_id", "")) != run_id or row.get("record_type") != "full_geometry_snapshot":
            continue
        query_u = num(row.get("diagnostic_fingerprint_query_time"))
        query_t = query_u + offset if np.isfinite(query_u) and np.isfinite(offset) else np.nan
        pid = row.get("ordinary_geometry_platform_instance_id")
        generation = str(row.get("ordinary_geometry_version_id") or "")
        fingerprint = str(row.get("diagnostic_fingerprint_version_id") or "")
        layer = num(row.get("platform_level"))
        radius = num(row.get("ball_radius"))
        distance = num(row.get("directional_edge_distance"))
        clearance = distance - radius if np.isfinite(distance) and np.isfinite(radius) else np.nan
        checks = {
            "receipt_context": bool(receipt_start_ix < line_ix < receipt_send_ix),
            "query_completed": row.get("query_completed") is True,
            "result_valid": row.get("result_valid") is True,
            "directional_edge_valid": row.get("directional_edge_valid") is True,
            "ordinary_geometry_query_valid": row.get("ordinary_geometry_query_valid") is True,
            "ordinary_geometry_ownership_valid": row.get("ordinary_geometry_ownership_valid") is True,
            "active_platform_matches": row.get("ordinary_geometry_active_platform_instance_id") == pid,
            "active_generation_matches": row.get("ordinary_geometry_active_version_id") == generation,
            "query_time_and_bridge_finite": bool(np.isfinite(query_t) and np.isfinite(offset)),
            "query_time_inside_receipt": bool(np.isfinite(query_t) and receipt_start_t <= query_t <= receipt_freeze_t),
            "identity_present": bool(pid is not None and generation),
            "gameplay_layer": bool(np.isfinite(layer) and int(layer) in GAMEPLAY_LAYERS),
            "clearance_finite_nonnegative_radius": bool(np.isfinite(clearance) and np.isfinite(radius) and radius >= 0),
        }
        valid = all(checks.values())
        snap = {
            "line_index": line_ix, "event_id": row.get("event_id"), "run_id": run_id,
            "time": query_t, "query_time_unity": query_u,
            "platform_id": canon(pid) if pid is not None else "", "layer": int(layer) if np.isfinite(layer) else None,
            "ordinary_generation_id": generation, "fingerprint_version_id": fingerprint,
            "clearance": clearance, "directional_edge_distance": distance, "ball_radius": radius,
            "valid": bool(valid), "checks": checks,
            "failed_flags": "|".join(k for k, ok in checks.items() if not ok),
        }
        snaps.append(snap)
        if not valid:
            exclusions.append({"run_id": run_id, "jsonl_line_index": line_ix, "event_id": row.get("event_id"),
                               "query_time_unity": query_u, "query_time_unix": query_t,
                               "platform_id": snap["platform_id"], "layer": snap["layer"],
                               "ordinary_generation_id": generation, "fingerprint_version_id": fingerprint,
                               "reason": snap["failed_flags"]})
    # Surface discontinuities and invalid query rows stay visible; no gap is bridged.
    for a, b in zip(snaps, snaps[1:]):
        if not (a["valid"] and b["valid"]):
            continue
        dt = b["time"] - a["time"]
        if dt <= 0 or dt > 0.15:
            errors.append({"run_id": run_id, "left_jsonl_line_index": a["line_index"],
                           "right_jsonl_line_index": b["line_index"], "gap_seconds": dt,
                           "reason": "nonpositive_query_time_step" if dt <= 0 else "broad_query_interval_over_0.15s"})
    return snaps, exclusions, errors


def receipt_for(records, run_id):
    own = [(ix, r) for ix, r in records if str(r.get("run_id", "")) == run_id]
    starts = [(ix, r) for ix, r in own if r.get("record_type") == "lifecycle" and r.get("lifecycle_event") == "new_run_created"]
    freezes = [(ix, r) for ix, r in own if r.get("record_type") == "lifecycle" and r.get("lifecycle_event") == "terminal_snapshot_frozen"]
    sends = [(ix, r) for ix, r in own if r.get("record_type") == "lifecycle" and r.get("lifecycle_event") == "terminal_udp_send_call_completed"]
    if len(starts) != 1 or len(freezes) != 1 or len(sends) != 1:
        return None, {"start_receipt_count": len(starts), "terminal_freeze_receipt_count": len(freezes),
                      "terminal_send_receipt_count": len(sends), "reason": "missing_or_nonunique_current_run_receipt"}
    start_ix, start = starts[0]
    freeze_ix, freeze = freezes[0]
    send_ix, send = sends[0]
    start_t, freeze_t, send_t = num(start.get("backend_timestamp")), num(freeze.get("backend_timestamp")), num(send.get("backend_timestamp"))
    if not (start_ix < freeze_ix < send_ix and np.isfinite(start_t) and np.isfinite(freeze_t) and np.isfinite(send_t) and start_t < freeze_t <= send_t):
        return None, {"start_receipt_count": 1, "terminal_freeze_receipt_count": 1, "terminal_send_receipt_count": 1,
                      "reason": "invalid_current_run_receipt_order_or_clock"}
    return {"start_ix": start_ix, "freeze_ix": freeze_ix, "send_ix": send_ix,
            "start_t": start_t, "freeze_t": freeze_t, "send_t": send_t,
            "run_state": str(send.get("run_state", "")), "outcome": str(send.get("session_outcome", ""))}, {
                "start_receipt_count": 1, "terminal_freeze_receipt_count": 1, "terminal_send_receipt_count": 1, "reason": ""}


def event_anchors(snaps, terminal_event, terminal_event_line, terminal_raw, actual_outcome, run_id):
    out = []
    edge_event = terminal_event or {}
    event_pid = canon(edge_event.get("event_platform_instance_id")) if edge_event else ""
    last_support = canon(edge_event.get("last_support_platform_instance_id")) if edge_event else ""
    event_diagnostic_generation = str(edge_event.get("geometry_version_id") or "")
    terminal_ordinary_generation = str(terminal_raw.get("geometry_version_id", "") or "")
    event_layer = num(edge_event.get("event_layer"))
    raw_pid = canon(terminal_raw.get("geometry_platform_instance_id", ""))
    raw_gen = str(terminal_raw.get("geometry_version_id", "") or "")
    raw_layer = num(terminal_raw.get("platform_level"))
    event_ok = bool(edge_event and edge_event.get("valid") is True and edge_event.get("event_name") == "edge_exit_predicate_commit"
                    and str(edge_event.get("event_outcome", "")) == "edge_exit")
    ownership_ok = bool(event_ok and event_pid == last_support == raw_pid and terminal_ordinary_generation == raw_gen
                        and np.isfinite(event_layer) and event_layer == raw_layer)
    metric_specs = (("directional_edge_distance_zero_crossing", "directional_edge_distance"),
                    ("surface_clearance_zero_crossing", "clearance"))
    for anchor_type, metric in metric_specs:
        candidates = []
        for a, b in zip(snaps, snaps[1:]):
            if not (a["valid"] and b["valid"]):
                continue
            if (a["platform_id"], a["layer"], a["ordinary_generation_id"]) != (b["platform_id"], b["layer"], b["ordinary_generation_id"]):
                continue
            va = a["directional_edge_distance"] if metric == "directional_edge_distance" else a["clearance"]
            vb = b["directional_edge_distance"] if metric == "directional_edge_distance" else b["clearance"]
            dt = b["time"] - a["time"]
            if not (np.isfinite(va) and np.isfinite(vb) and va > 0 >= vb and dt > 0
                    and b["time"] <= num(edge_event.get("event_backend_timestamp"))):
                continue
            candidates.append((a["time"], b["time"], a, b))
        if not candidates:
            out.append({"session_id": terminal_raw.get("_session_id"), "run_id": run_id, "anchor_type": anchor_type,
                        "timestamp": np.nan, "source": "full_geometry_snapshot_query_time", "available": False,
                        "reason": "no_adjacent_valid_positive_to_nonpositive_crossing", "terminal_event_corroborated": ownership_ok,
                        "event_platform_id": event_pid, "last_support_platform_id": last_support, "event_layer": event_layer,
                        "event_diagnostic_version_id": event_diagnostic_generation,
                        "terminal_ordinary_generation_id": terminal_ordinary_generation,
                        "terminal_raw_platform_id": raw_pid,
                        "terminal_raw_layer": raw_layer, "terminal_raw_generation_id": raw_gen})
            continue
        lower_time, upper_time, a, b = candidates[-1]
        corroborated_crossing = bool(ownership_ok and (a["platform_id"], a["layer"], a["ordinary_generation_id"]) == (event_pid, event_layer, terminal_ordinary_generation)
                                    and (b["platform_id"], b["layer"], b["ordinary_generation_id"]) == (event_pid, event_layer, terminal_ordinary_generation))
        returned, unresolved = False, False
        scan = [s for s in snaps if s["line_index"] > b["line_index"] and terminal_event_line and s["line_index"] < terminal_event_line]
        for candidate in scan:
            if not candidate["valid"]:
                unresolved = True
                break
            if (candidate["platform_id"], candidate["layer"], candidate["ordinary_generation_id"]) != (b["platform_id"], b["layer"], b["ordinary_generation_id"]):
                unresolved = True
                break
            clearance = candidate[metric] if metric == "directional_edge_distance" else candidate["clearance"]
            if clearance > 0:
                returned = True
                break
        is_terminal = bool(actual_outcome == "edge_exit" and corroborated_crossing and not returned and not unresolved)
        reason = "" if is_terminal else ("not_edge_exit_terminal" if actual_outcome != "edge_exit" else
                                          "terminal_edge_event_identity_not_corroborated" if not corroborated_crossing else
                                          "positive_return_observed" if returned else "same_identity_scan_unresolved")
        out.append({"session_id": terminal_raw.get("_session_id"), "run_id": run_id, "anchor_type": anchor_type,
                    "timestamp": np.nan, "source": "adjacent_full_geometry_snapshot_query_time_bounds",
                    "available": is_terminal, "reason": reason, "terminal_event_corroborated": corroborated_crossing,
                    "lower_jsonl_line_index": a["line_index"], "upper_jsonl_line_index": b["line_index"],
                    "lower_snapshot_event_id": a["event_id"], "upper_snapshot_event_id": b["event_id"],
                    "lower_query_time": lower_time, "upper_query_time": upper_time, "interval_width_seconds": upper_time - lower_time,
                    "narrow_anchor_le_0_15s": bool(upper_time - lower_time <= 0.15),
                    "estimated_crossing_time_descriptive_only": float(lower_time + (0 - (a["directional_edge_distance"] if metric == "directional_edge_distance" else a["clearance"]))
                                                                        * (upper_time - lower_time)
                                                                        / ((b["directional_edge_distance"] if metric == "directional_edge_distance" else b["clearance"])
                                                                           - (a["directional_edge_distance"] if metric == "directional_edge_distance" else a["clearance"]))),
                    "lower_platform_id": a["platform_id"], "upper_platform_id": b["platform_id"],
                    "layer": b["layer"], "ordinary_generation_id": b["ordinary_generation_id"],
                    "lower_fingerprint_version_id": a["fingerprint_version_id"], "upper_fingerprint_version_id": b["fingerprint_version_id"],
                    "event_platform_id": event_pid, "last_support_platform_id": last_support, "event_layer": event_layer,
                    "event_diagnostic_version_id": event_diagnostic_generation,
                    "terminal_ordinary_generation_id": terminal_ordinary_generation,
                    "event_backend_timestamp": num(edge_event.get("event_backend_timestamp")),
                    "terminal_raw_platform_id": raw_pid, "terminal_raw_layer": raw_layer, "terminal_raw_generation_id": raw_gen,
                    "positive_return_observed": returned, "return_scan_unresolved": unresolved})
    return out


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    prep, helper = load_reviewed_feature_code()
    raw_paths = sorted(RAW_ROOT.glob("session_*/raw.csv"))
    if len(raw_paths) != 15:
        raise RuntimeError(f"Expected the 15 current TEST1012 raw.csv files, found {len(raw_paths)}")
    raw_blobs, raw_hashes, raw_frames, raw_runids = {}, {}, {}, {}
    for path in raw_paths:
        blob = path.read_bytes()
        raw_blobs[path] = blob
        raw_hashes[path] = sha_bytes(blob)
        frame = pd.read_csv(io.BytesIO(blob), low_memory=False).copy()
        frame["_csv_row"] = np.arange(len(frame)) + 2
        u = frame[frame.source.astype(str).str.lower().eq("unity")].copy()
        run_ids = sorted({str(x) for x in u.run_id.dropna().unique() if str(x)})
        if len(run_ids) != 1:
            raise RuntimeError(f"Expected one explicit Unity run_id in {path.parent.name}; found {run_ids}")
        raw_frames[path] = (frame, u)
        raw_runids[path] = run_ids[0]
    wanted_runs = set(raw_runids.values())
    json_paths = sorted(JSONL_ROOT.glob(JSONL_GLOB))
    json_inventory, records_by_run, assoc_files, parse_errors_by_file = [], {}, {}, {}
    json_blobs = {}
    for path in json_paths:
        blob = path.read_bytes()
        json_blobs[path] = blob
        records, errors = read_json_lines(blob)
        runs = sorted({str(r.get("run_id")) for _, r in records if r.get("run_id") not in (None, "")})
        matched = sorted(set(runs) & wanted_runs)
        json_inventory.append({"jsonl_path": str(path), "sha256_before": sha_bytes(blob), "bytes": len(blob),
                               "record_count": len(records), "run_ids": "|".join(runs),
                               "matched_run_ids": "|".join(matched), "parse_errors": len(errors),
                               "inventory_status": "exact_run_candidate" if matched else ("empty_unassociated" if not records else "unmatched_run_id")})
        parse_errors_by_file[path] = errors
        for run in matched:
            if run in records_by_run:
                raise RuntimeError(f"Run_id appears in more than one JSONL file: {run}")
            records_by_run[run] = records
            assoc_files[run] = path
    if set(records_by_run) != wanted_runs:
        missing = sorted(wanted_runs - set(records_by_run))
        extra = sorted(set(records_by_run) - wanted_runs)
        raise RuntimeError(f"Exact-run JSONL association incomplete; missing={missing}, extra={extra}")

    feature_rows, manifests, anchors, recoveries, associations, snapshot_issues = [], [], [], [], [], []
    source_start_hashes = {**{str(p): raw_hashes[p] for p in raw_paths}, **{str(p): sha_bytes(b) for p, b in json_blobs.items()}}
    for path in raw_paths:
        sid = path.parent.name
        frame, u0 = raw_frames[path]
        run_id = raw_runids[path]
        u = u0.copy()
        u["t"] = pd.to_numeric(u.source_timestamp, errors="coerce")
        u["seq"] = pd.to_numeric(u.sequence, errors="coerce")
        u["layer_n"] = pd.to_numeric(u.platform_level, errors="coerce")
        end_rows = u[u.session_outcome.astype(str).str.strip().ne("")]
        terminal = (end_rows.sort_values("_csv_row").iloc[-1] if len(end_rows) else u.sort_values("_csv_row").iloc[-1]).to_dict()
        terminal["_session_id"] = sid
        actual = str(terminal.get("session_outcome") or "unknown")
        passed, selected = num(terminal.get("passed_count")), num(terminal.get("selected_session_layers"))
        run_ended = str(terminal.get("run_state", "")).lower() == "ended"
        normalized = "complete" if actual == "calibration_completed" and run_ended and passed == 3 and selected == 3 else actual
        event_t = num(terminal.get("fall_event_backend_timestamp"))
        if not np.isfinite(event_t):
            event_t = num(terminal.get("session_end_backend_timestamp"))
        bridge = (pd.to_numeric(u.source_timestamp, errors="coerce") - pd.to_numeric(u.geometry_source_timestamp, errors="coerce")).replace([np.inf, -np.inf], np.nan).dropna()
        offset = float(bridge.median()) if len(bridge) else np.nan
        jp = assoc_files[run_id]
        records = records_by_run[run_id]
        receipt, receipt_issue = receipt_for(records, run_id)
        if receipt is None:
            raise RuntimeError(f"Current-run receipt missing for {sid}: {receipt_issue}")
        if receipt["run_state"].lower() != "ended":
            raise RuntimeError(f"Current-run terminal receipt is not ended for {sid}: {receipt['run_state']}")
        terminal_events = [(ix, r) for ix, r in records if str(r.get("run_id")) == run_id
                           and r.get("event_name") == "edge_exit_predicate_commit" and r.get("valid") is True
                           and ix < receipt["send_ix"]]
        terminal_event = terminal_events[-1][1] if terminal_events else None
        snaps, invalids, gaps = snapshot_rows(records, run_id, offset, receipt["start_ix"], receipt["send_ix"],
                                              receipt["start_t"], receipt["freeze_t"], receipt["send_t"])
        snapshot_issues.extend(invalids)
        snapshot_issues.extend({"run_id": run_id, **g} for g in gaps)
        # Add all out-of-receipt full snapshots as excluded evidence, never as anchor inputs.
        for ix, record in records:
            if str(record.get("run_id", "")) == run_id and record.get("record_type") == "full_geometry_snapshot" and not (receipt["start_ix"] < ix < receipt["send_ix"]):
                snapshot_issues.append({"run_id": run_id, "jsonl_line_index": ix, "reason": "outside_current_run_receipt_context"})
        terminal_event_line = terminal_events[-1][0] if terminal_events else None
        geometry_anchors = event_anchors(snaps, terminal_event, terminal_event_line, terminal, actual, run_id)
        anchors.extend(geometry_anchors)
        terminal_anchor_rows = [a for a in geometry_anchors if a.get("available")]
        raw_hash = raw_hashes[path]
        json_hash = sha_bytes(json_blobs[jp])
        associations.append({"session_id": sid, "run_id": run_id, "association": "exact_unique_run_id_and_current_run_receipts",
                             "raw_path": str(path), "raw_sha256": raw_hash, "jsonl_path": str(jp), "jsonl_sha256": json_hash,
                             "jsonl_exact_run_records": sum(str(r.get("run_id", "")) == run_id for _, r in records),
                             "jsonl_full_snapshots_in_receipt": sum(r.get("record_type") == "full_geometry_snapshot" and receipt["start_ix"] < ix < receipt["send_ix"] for ix, r in records),
                             "jsonl_parse_errors": len(parse_errors_by_file[jp]), "run_start_line": receipt["start_ix"],
                             "terminal_freeze_line": receipt["freeze_ix"], "terminal_send_line": receipt["send_ix"],
                             "run_start_backend_timestamp": receipt["start_t"], "terminal_freeze_backend_timestamp": receipt["freeze_t"],
                             "terminal_send_backend_timestamp": receipt["send_t"], "median_unity_clock_bridge_seconds": offset,
                             "clock_bridge_samples": len(bridge), "edge_exit_terminal_event_count": len(terminal_events),
                             "edge_exit_terminal_event_line": terminal_events[-1][0] if terminal_events else ""})
        associations[-1]["jsonl_sourcepath_sha256"] = json_hash
        # Gameplay-compatible in calibration_mode=True includes only selected gameplay L1-L3; layer 4 is never used.
        scale = pd.to_numeric(u.platform_scale, errors="coerce")
        scope = u.layer_n.isin(GAMEPLAY_LAYERS) & scale.notna() & scale.le(PLATFORM_SCALE_MAX)
        query_ok = u.geometry_query_valid.astype(str).str.lower().isin(("true", "1"))
        owner_ok = u.geometry_ownership_valid.astype(str).str.lower().isin(("true", "1"))
        active_ok = (u.geometry_active_platform_instance_id.astype(str) == u.geometry_platform_instance_id.astype(str)) & (u.geometry_active_version_id.astype(str) == u.geometry_version_id.astype(str))
        directional_ok = u.directional_edge_valid.astype(str).str.lower().isin(("true", "1"))
        geo_ok = query_ok & owner_ok & active_ok & directional_ok
        valid = u.run_state.astype(str).str.lower().eq("running") & u.t.notna() & scope & geo_ok
        for col in ("directional_edge_distance", "ball_radial_velocity", "ball_radius", "platform_radius", "geometry_source_timestamp"):
            valid &= np.isfinite(pd.to_numeric(u[col], errors="coerce"))
        for col in ("geometry_platform_instance_id", "geometry_version_id", "geometry_active_platform_instance_id", "geometry_active_version_id"):
            valid &= u[col].notna() & u[col].astype(str).str.strip().ne("")
        raw_quality = {"session_id": sid, "run_id": run_id, "unity_rows": len(u), "gameplay_scope_rows_l1_l3": int(scope.sum()),
                       "excluded_layer4_or_unknown_scale_rows": int((~scope).sum()), "geometry_invalid_scope_rows": int((scope & ~geo_ok).sum()),
                       "query_invalid_scope_rows": int((scope & ~query_ok).sum()), "ownership_invalid_scope_rows": int((scope & ~owner_ok).sum()),
                       "active_identity_mismatch_scope_rows": int((scope & ~active_ok).sum()), "directional_invalid_scope_rows": int((scope & ~directional_ok).sum()),
                       "valid_running_geometry_rows": int(valid.sum())}
        numeric = ["geometry_platform_instance_id", "directional_edge_distance", "ball_radial_velocity", "ball_velocity_x", "ball_velocity_z",
                   "ball_pos_x", "ball_pos_z", "platform_center_x", "platform_center_z", "ball_radius", "platform_radius", "platform_tilt", "difficulty"]
        for col in numeric:
            u[col] = pd.to_numeric(u[col], errors="coerce")
        gameplay = u[valid].copy().reset_index(drop=True)
        seg_no, previous, previous_key = 0, None, None
        chunks = []
        for i, row in gameplay.iterrows():
            key = (str(row.get("run_id")), int(row.layer_n), canon(row.get("geometry_platform_instance_id", "unknown")), str(row.get("geometry_version_id", "unknown")))
            dt = row.t - previous.t if previous is not None else np.nan
            ds = row.seq - previous.seq if previous is not None else np.nan
            if previous is None or key != previous_key or not (0 < dt <= MAX_GAP) or ds != 1:
                seg_no += 1
            gameplay.loc[i, "_segment"] = seg_no
            previous, previous_key = row, key
        for segid, chunk in gameplay.groupby("_segment", sort=False):
            layer = int(chunk.layer_n.iloc[0])
            seg = SimpleNamespace(segment_id=f"{sid}:{int(segid)}", layer=layer,
                                  start_source_timestamp=float(chunk.t.iloc[0]), end_source_timestamp=float(chunk.t.iloc[-1]))
            ch = chunk.copy()
            ch["source_timestamp"] = ch.t
            ch["platform_level"] = ch.layer_n
            ch["sequence"] = ch.seq
            sess = SimpleNamespace(session_id=sid, run_id=run_id, fall_event_unix_seconds=event_t, observation_group="TEST1012")
            generated = helper.feature_rows(ch, sess, seg)
            prep["add_recovery_flags"](generated, chunk)
            for f in generated:
                src = chunk.loc[chunk._csv_row.eq(f["csv_row"])].iloc[0]
                f.update(platform_id=canon(src.geometry_platform_instance_id), geometry_version_id=str(src.geometry_version_id),
                         geometry_generation_id=str(src.geometry_version_id), identity_source="raw_csv_geometry_identity",
                         csv_row_id=int(src._csv_row), source_sequence=int(src.seq), raw_sha256=raw_hash, jsonl_sha256=json_hash,
                         calibration_mode=str(src.get("calibration_mode", "")), platform_scale=num(src.get("platform_scale")))
                feature_rows.append(f)
                if f["joint_recovery"]:
                    recoveries.append({"session_id": sid, "run_id": run_id, "source_sequence": f["source_sequence"],
                                       "csv_row_id": f["csv_row_id"], "timestamp": f["timestamp"], "layer": f["layer"],
                                       "platform_id": f["platform_id"], "geometry_generation_id": f["geometry_generation_id"],
                                       "clearance": f["clearance"], "clearance_gain_0_1s": f["clearance_gain_0_1s"],
                                       "continuous_inward_duration": f["continuous_inward_duration"], "record_type": "observed_joint_recovery_point"})
        raw_quality["feature_segment_count"] = int(gameplay._segment.nunique()) if len(gameplay) else 0
        terminal_layer = num(terminal.get("platform_level"))
        actual_failure_layer = terminal_layer if actual == "edge_exit" else np.nan
        event_corroborated = bool(terminal_event and terminal_event.get("valid") is True
                                  and canon(terminal_event.get("event_platform_instance_id")) == canon(terminal.get("geometry_platform_instance_id"))
                                  and canon(terminal_event.get("last_support_platform_instance_id")) == canon(terminal.get("geometry_platform_instance_id"))
                                  and num(terminal_event.get("event_layer")) == terminal_layer
                                  and str(terminal_event.get("geometry_version_id", "")) == str(terminal.get("geometry_version_id", "")))
        manifests.append({"session_id": sid, "run_id": run_id, "cohort": "TEST1012", "difficulty": num(terminal.get("difficulty")),
                          "actual_outcome": actual, "normalized_outcome": normalized, "passed_count": passed,
                          "selected_session_layers": selected, "run_state": str(terminal.get("run_state", "")),
                          "calibration_mode": str(terminal.get("calibration_mode", "")),
                          "calibration_mode_true_gameplay3_compatibility": str(terminal.get("calibration_mode", "")).lower() == "true",
                          "terminal_platform_level": terminal_layer, "calibration_platform_level_is_gameplay_layer": False,
                          "actual_failure_layer": actual_failure_layer, "game_end_time": event_t,
                          "terminal_event_corroborated": event_corroborated,
                          "terminal_anchor_available": bool(any(a.get("available") for a in terminal_anchor_rows)),
                          "terminal_anchor_types": "|".join(a["anchor_type"] for a in terminal_anchor_rows),
                          "terminal_platform_id": canon(terminal.get("geometry_platform_instance_id", "")),
                          "terminal_geometry_generation_id": str(terminal.get("geometry_version_id", "")),
                          "raw_sha256": raw_hash, "jsonl_sha256": json_hash,
                          "receipt_status": "valid_new_run_terminal_freeze_terminal_send"})
        manifests[-1].update(raw_quality)

    # Verify every current source remained byte-identical before materializing any derived file.
    changed = []
    for p in raw_paths:
        if sha_path(p) != raw_hashes[p]:
            changed.append(str(p))
    for p, blob in json_blobs.items():
        if sha_path(p) != sha_bytes(blob):
            changed.append(str(p))
    if changed:
        raise RuntimeError("Current TEST1012 source changed during preparation; no frozen result written: " + " | ".join(changed))

    feature_frame = pd.DataFrame(feature_rows)
    metadata_cols = helper.META + helper.BASE_FEATURES + helper.EXT_FEATURES
    identity_cols = ["platform_id", "geometry_version_id", "geometry_generation_id", "identity_source", "csv_row_id", "source_sequence",
                     "raw_sha256", "jsonl_sha256", "calibration_mode", "platform_scale"]
    feature_cols = list(dict.fromkeys(c for c in metadata_cols + ["continuous_inward_duration", "clearance_gain_0_1s", "joint_recovery"] + identity_cols if c in feature_frame.columns))
    if len(feature_cols) != len(set(feature_cols)):
        raise RuntimeError("Duplicate feature output headers")
    if not feature_frame.empty:
        feature_frame = feature_frame[feature_cols].sort_values(["session_id", "timestamp", "segment_id"]).reset_index(drop=True)
        # Every feature must map back to one exact raw CSV row and same run/platform/layer/generation.
        if feature_frame.duplicated(["session_id", "csv_row_id"]).any():
            raise RuntimeError("Feature provenance is not one-to-one with its source raw rows")
        if not feature_frame.observation_group.eq("TEST1012").all():
            raise RuntimeError("Feature cohort tag drifted from TEST1012")
    outcome_counts = {k: int(sum(m["actual_outcome"] == k for m in manifests)) for k in sorted({m["actual_outcome"] for m in manifests})}
    normalized_counts = {k: int(sum(m["normalized_outcome"] == k for m in manifests)) for k in sorted({m["normalized_outcome"] for m in manifests})}
    edge_denominator = sum(m["actual_outcome"] == "edge_exit" for m in manifests)
    anchor_available_exits = sum(m["actual_outcome"] == "edge_exit" and m["terminal_anchor_available"] for m in manifests)
    summary = {
        "dataset": "TEST1012", "sensitivity_current_user_config": SENSITIVITY, "sensitivity_prior_user_config": PRIOR_SENSITIVITY,
        "ai_and_geometry_experimental_banners": "on", "original_yellow_attention_unchanged": True,
        "sessions": len(manifests), "outcomes": outcome_counts, "normalized_outcomes": normalized_counts,
        "edge_exit_denominator_including_all_layers": edge_denominator, "edge_exits_with_formal_terminal_anchor": anchor_available_exits,
        "edge_exits_with_unknown_anchor": edge_denominator - anchor_available_exits,
        "feature_rows": len(feature_frame), "sessions_with_features": int(feature_frame.session_id.nunique()) if len(feature_frame) else 0,
        "feature_columns": len([c for c in helper.BASE_FEATURES + helper.EXT_FEATURES if c in feature_frame.columns]),
        "feature_segments": int(feature_frame.segment_id.nunique()) if len(feature_frame) else 0,
        "event_anchor_rows": len(anchors), "event_anchor_available_rows": sum(bool(a.get("available")) for a in anchors),
        "recovery_points": len(recoveries), "invalid_or_excluded_snapshot_records": sum("jsonl_line_index" in x for x in snapshot_issues),
        "snapshot_gap_records": sum("left_jsonl_line_index" in x for x in snapshot_issues),
        "exact_run_associations": sum(a["association"].startswith("exact_unique") for a in associations),
        "jsonl_inventory_files": len(json_inventory), "all_source_hashes_unchanged": True,
        "models_trained": False, "thresholds_selected": False,
        "calibration_mode_false_claimed": False, "layer4_used_as_gameplay": False,
    }
    metadata = {
        "cohort": "TEST1012", "inputs": associations, "jsonl_inventory": json_inventory,
        "raw_csv_hashes": [{"path": str(p), "sha256": raw_hashes[p]} for p in raw_paths],
        "feature_source_code": str(BASE_PREP), "feature_source_code_sha256": sha_path(BASE_PREP),
        "feature_helper_code": str(FEATURE_HELPER), "feature_helper_code_sha256": sha_path(FEATURE_HELPER),
        "feature_definition": {"columns": helper.BASE_FEATURES + helper.EXT_FEATURES, "count": 24,
                               "history_seconds": 0.5, "minimum_evaluation_interval_seconds": 0.05,
                               "max_segment_gap_seconds": MAX_GAP, "running_only": True, "strictly_pre_game_event": True,
                               "past_only": True, "geometry_validity_mask": "query_valid AND ownership_valid AND active platform/version match AND directional_edge_valid; invalid rows break segments",
                               "segment_identity": "run_id, layer, platform_instance_id, geometry_version_id, consecutive sequence, 0<dt<=0.1s"},
        "query_time_rule": "diagnostic_fingerprint_query_time + same-run median(raw source_timestamp - raw geometry_source_timestamp); unknown bridge/query time invalid, no CSV proxy fallback",
        "anchor_rule": "adjacent valid full_geometry_snapshot records, same ordinary platform/layer/generation, positive-to-nonpositive crossing, positive query-time step within current-run lifecycle receipt; terminal requires independent edge_exit_predicate_commit last-support/platform/layer/generation corroboration and no same-identity positive return",
        "fingerprint_identity_policy": "diagnostic_fingerprint_version_id retained separately from ordinary_geometry_version_id; ordinary generation defines same-geometry continuity",
        "current_run_receipt_policy": "snapshots included only after exact-run new_run_created and before exact-run terminal_snapshot_frozen; terminal_udp_send_call_completed required; later idle Wii records are not inputs",
        "outcomes": "actual calibration_completed preserved; normalized complete only when ended and passed_count=3 and selected_session_layers=3",
        "calibration_mode_note": "CSV calibration_mode=True is retained; selected gameplay layers 1-3 with platform_scale<=2 are included, layer 4 excluded. This does not claim calibration_mode=False.",
        "model_config_context": {"current_sensitivity": SENSITIVITY, "previous_sensitivity": PRIOR_SENSITIVITY,
                                 "ai_experimental_banner": True, "geometry_experimental_banner": True,
                                 "original_yellow_attention_unchanged": True},
        "models_trained": False, "thresholds_selected": False, "fit_performed": False,
        "source_stability": "all raw CSV and JSONL input hashes compared before/after parsing and before output materialization",
    }
    # Materialize only under the authorized isolated workspace.
    feature_frame.to_csv(OUTDIR / "features.csv", index=False, na_rep="")
    pd.DataFrame(manifests).to_csv(OUTDIR / "session_manifest.csv", index=False, na_rep="")
    pd.DataFrame(anchors).to_csv(OUTDIR / "event_anchors.csv", index=False, na_rep="")
    pd.DataFrame(recoveries).to_csv(OUTDIR / "recovery.csv", index=False, na_rep="")
    pd.DataFrame(associations).to_csv(OUTDIR / "source_associations.csv", index=False, na_rep="")
    pd.DataFrame(json_inventory).to_csv(OUTDIR / "jsonl_inventory.csv", index=False, na_rep="")
    pd.DataFrame(snapshot_issues).to_csv(OUTDIR / "invalid_snapshot_gaps.csv", index=False, na_rep="")
    (OUTDIR / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (OUTDIR / "metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    readme = f"""# TEST1012 formal preparation\n\nThis workspace contains a no-fit preparation of the current TEST1012 runs. It preserves actual outcomes, associates raw CSVs and diagnostic JSONL by unique run_id, and uses the current-run lifecycle receipts to bound snapshot inputs.\n\nThe reviewed 24 causal features use 0.5 seconds of past history, a 0.05-second evaluation stride, a 0.1-second maximum segment gap, and a geometry identity/validity mask. Invalid rows, layer changes, identity changes, sequence gaps, and time gaps break segments. Feature rows retain their exact CSV row and sequence.\n\nGeometry anchors use full diagnostic snapshots at query time, bridged by the same run's median Unity clock offset. Missing or invalid query times remain unknown. The independent fingerprint version and ordinary geometry generation are retained separately. A terminal anchor additionally requires an exact edge-exit event matching terminal raw platform, last-support platform, layer, and generation, with no observed same-identity positive return.\n\n`calibration_mode=True` is retained as recorded. Layers 1–3 at scale <=2 are treated as gameplay-compatible; layer 4 is excluded. This preparation does not claim calibration mode was false. Actual `calibration_completed` outcomes remain unchanged; `normalized_outcome=complete` is only assigned to ended runs with passed_count=3 and selected_session_layers=3.\n\nSensitivity context is user-provided: current 0.55, prior 0.66. Both experimental AI and geometry banners were on, and original yellow attention was unchanged. No models were trained and no thresholds were selected.\n\nRun `python prepare_formal.py` with the bundled Python runtime to reproduce. All derived files stay in this folder; source logs are read-only.\n"""
    (OUTDIR / "README.md").write_text(readme, encoding="utf-8")
    # Final stability check after outputs are materialized.
    if any(sha_path(p) != raw_hashes[p] for p in raw_paths) or any(sha_path(p) != sha_bytes(blob) for p, blob in json_blobs.items()):
        raise RuntimeError("Source hash changed during output materialization; do not treat this preparation as frozen")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
