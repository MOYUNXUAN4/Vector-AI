"""Read-only offline-counterfactual replay of the 1012TEST Unity CSV logs.

This intentionally uses the frozen warning bridge and native model. It does
not train, tune, run a service, or write to any source CSV.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path


BACKEND_ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend")
INPUT_ROOT = BACKEND_ROOT / "telemetry_logs" / "1012TEST"
BRIDGE_DIR = BACKEND_ROOT / "parallel_20261011" / "realtime_integration"
MANIFEST = BACKEND_ROOT / "parallel_20261011" / "deployment_refit" / "output" / "artifact" / "manifest.json"
OUTPUT_DIR = BACKEND_ROOT / "parallel_20261012" / "accept1012_replay_luna"
OUTPUT_JSON = OUTPUT_DIR / "summary.json"
PINNED_MODEL_SHA256 = "01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068"


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
    if result is None or not result.is_integer():
        return None
    return int(result)


def boolean(value):
    if value is True or value == "True" or value == "true" or value == "1":
        return True
    if value is False or value == "False" or value == "false" or value == "0":
        return False
    return None


def put(packet, name, value, converter=None):
    if value is None or str(value).strip() == "":
        return
    packet[name] = converter(value) if converter else value


def inverse_logger_mapping(row):
    """Map logger columns to bridge packet keys without altering source values."""
    packet = {"type": "unity_game"}
    put(packet, "timestamp", row.get("source_timestamp"), number)
    put(packet, "sequence", row.get("sequence"), integer)
    put(packet, "run_id", row.get("run_id"))
    put(packet, "run_state", row.get("run_state"))
    put(packet, "platformLevel", row.get("platform_level"), number)
    put(packet, "platformTilt", row.get("platform_tilt"), number)
    put(packet, "calibration_mode", row.get("calibration_mode"), boolean)
    put(packet, "selected_session_layers", row.get("selected_session_layers"), integer)
    put(packet, "platform_scale", row.get("platform_scale"), number)

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
        put(packet, dest, row.get(source), conv)
    for key in ("geometry_query_valid", "geometry_ownership_valid", "directional_edge_valid"):
        put(packet, key, row.get(key), boolean)
    return packet


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files():
    files = sorted(INPUT_ROOT.glob("session_*/raw.csv"))
    if len(files) != 8:
        raise RuntimeError(f"Expected exactly 8 session raw.csv files, found {len(files)}")
    return files


def load_bridge():
    sys.path.insert(0, str(BRIDGE_DIR))
    from bridge import RealtimeWarningBridge

    bridge = RealtimeWarningBridge(
        enabled=True,
        allow_calibration_gameplay=True,
        manifest=MANIFEST,
        pinned_hash=PINNED_MODEL_SHA256,
    )
    loaded = bridge.preload()
    if not loaded.get("loaded"):
        raise RuntimeError(f"Frozen model did not load through bridge: {loaded}")
    model = bridge.runtime._model
    if getattr(model, "model_sha256", None) != PINNED_MODEL_SHA256:
        actual = getattr(model, "model_sha256", None)
        raise RuntimeError(f"Bridge model hash mismatch: {actual}")
    locked_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return bridge, loaded, model, locked_manifest


def add_episode(episodes, current, end_source_time, end_reason):
    if current is None:
        return
    current["last_strong_source_time"] = current.get("last_strong_source_time")
    current["end_source_time"] = end_source_time
    current["end_reason"] = end_reason
    episodes.append(current)


def add_source_event_diagnostics(session, path, max_gap_seconds):
    """Add source-only event/gap context; never interpolate missing telemetry."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    unity_rows = [row for row in rows if row.get("source") == "unity"]

    fall_events = []
    for row in rows:
        backend_time = number(row.get("fall_event_backend_timestamp"))
        source_time = number(row.get("fall_event_time"))
        if backend_time is not None or source_time is not None:
            fall_events.append({
                "fall_event_backend_timestamp": backend_time,
                "fall_event_time": source_time,
                "row_source_timestamp": number(row.get("source_timestamp")),
                "row_backend_timestamp": number(row.get("backend_timestamp")),
                "row_sequence": integer(row.get("sequence")),
                "session_outcome": row.get("session_outcome") or None,
            })
    session["source_fall_events"] = fall_events
    fall_backend = fall_events[-1]["fall_event_backend_timestamp"] if fall_events else None
    first_strong = session.get("first_strong_source_time")
    session["first_strong_source_time_minus_fall_event_backend_seconds"] = (
        first_strong - fall_backend
        if first_strong is not None and fall_backend is not None else None
    )

    gaps = []
    previous = None
    for row in unity_rows:
        stamp = number(row.get("source_timestamp"))
        sequence = integer(row.get("sequence"))
        if stamp is None or sequence is None:
            previous = None
            continue
        if previous is not None:
            prior_stamp, prior_sequence = previous
            delta = stamp - prior_stamp
            if delta > max_gap_seconds:
                gaps.append({
                    "sequence_before": prior_sequence,
                    "sequence_after": sequence,
                    "source_timestamp_before": prior_stamp,
                    "source_timestamp_after": stamp,
                    "source_gap_seconds": delta,
                    "exceeds_max_decision_gap": True,
                    "source_values_interpolated": False,
                })
        previous = (stamp, sequence)
    session["source_time_gaps_over_max_decision_gap"] = gaps
    session["source_gap_count_over_max_decision_gap"] = len(gaps)


def replay_session(path, bridge, sequence_state):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        all_rows = list(csv.DictReader(stream))
    unity_rows = [row for row in all_rows if row.get("source") == "unity"]
    run_ids = {row.get("run_id", "").strip() for row in unity_rows if row.get("run_id", "").strip()}
    if len(run_ids) != 1:
        raise RuntimeError(f"{path.parent.name}: expected one source run_id, found {sorted(run_ids)}")
    run_id = next(iter(run_ids))
    bridge.start_session(run_id)

    result = {
        "session_id": path.parent.name,
        "run_id": run_id,
        "rows": len(unity_rows),
        "accepted": 0,
        "valid": 0,
        "strong_seen": 0,
        "actual_mask_reasons": {},
        "strong_episodes": [],
        "first_strong_source_time": None,
        "last_strong_source_time": None,
        "source_terminal_outcome": None,
        "source_terminal_run_state": None,
        "missing_backend_timestamp_rows": 0,
        "missing_source_timestamp_rows": 0,
        "missing_or_invalid_sequence_rows": 0,
        "run_id_mismatch_rows": 0,
        "warning_update_sequence_monotonic": True,
    }
    reasons = Counter()
    first_backend = None
    prior_backend = None
    prior_warning_sequence = sequence_state[0]
    open_episode = None
    prev_state = None

    for raw in unity_rows:
        if raw.get("run_id") != run_id:
            result["run_id_mismatch_rows"] += 1
        backend_timestamp = number(raw.get("backend_timestamp"))
        if backend_timestamp is None:
            result["missing_backend_timestamp_rows"] += 1
            continue
        if first_backend is None:
            first_backend = backend_timestamp
        if prior_backend is not None and backend_timestamp < prior_backend:
            raise RuntimeError(f"{path.parent.name}: backend timestamps reverse; refusing to synthesize receipt time")
        prior_backend = backend_timestamp
        receipt = backend_timestamp - first_backend

        packet = inverse_logger_mapping(raw)
        if packet.get("timestamp") is None:
            result["missing_source_timestamp_rows"] += 1
        if packet.get("sequence") is None:
            result["missing_or_invalid_sequence_rows"] += 1

        accepted = bridge.ingest_unity_packet(packet, receipt)
        attached = bridge.attach({"type": "realtime"}, receipt)
        warning = attached.get("model_warning", {})
        result["accepted"] += int(bool(accepted))
        result["valid"] += int(bool(warning.get("valid")))
        reason = str(warning.get("reason", ""))
        reasons[reason] += 1

        warning_sequence = warning.get("warning_update_sequence")
        if type(warning_sequence) is not int or warning_sequence <= prior_warning_sequence:
            result["warning_update_sequence_monotonic"] = False
        if type(warning_sequence) is int:
            prior_warning_sequence = warning_sequence
            sequence_state[0] = warning_sequence

        state = warning.get("state")
        warning_source_time = number(warning.get("input_source_timestamp"))
        if state == "STRONG":
            result["strong_seen"] += 1
            if result["first_strong_source_time"] is None:
                result["first_strong_source_time"] = warning_source_time
            result["last_strong_source_time"] = warning_source_time
            if open_episode is None:
                open_episode = {
                    "trigger_source_time": warning_source_time,
                    "first_strong_source_time": warning_source_time,
                    "last_strong_source_time": warning_source_time,
                    "trigger_sequence": warning.get("input_sequence"),
                    "trigger_reason": reason,
                }
            else:
                open_episode["last_strong_source_time"] = warning_source_time
        elif open_episode is not None:
            add_episode(result["strong_episodes"], open_episode, warning_source_time, reason)
            open_episode = None
        prev_state = state

        # Retain the terminal state actually present in the source record.
        if raw.get("session_outcome", "").strip():
            result["source_terminal_outcome"] = raw["session_outcome"].strip()
        if raw.get("run_state", "").strip():
            result["source_terminal_run_state"] = raw["run_state"].strip()

    if open_episode is not None:
        add_episode(result["strong_episodes"], open_episode, None, "session_end_without_non_strong_observation")
    result["actual_mask_reasons"] = dict(sorted(reasons.items()))
    result["strong_episode_count"] = len(result["strong_episodes"])
    result["warning_update_sequence_last"] = prior_warning_sequence
    result["warning_update_sequence_first"] = (
        result["warning_update_sequence_last"] - (result["rows"] - result["missing_backend_timestamp_rows"]) + 1
        if result["rows"] > result["missing_backend_timestamp_rows"] else None
    )
    return result


def main():
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = source_files()
    locked_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    max_gap_seconds = number(locked_manifest.get("max_decision_gap_seconds"))
    if max_gap_seconds is None:
        raise RuntimeError("Locked manifest has no finite max_decision_gap_seconds")
    if len(sys.argv) > 1 and sys.argv[1] == "--enrich-existing-summary":
        summary = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        by_id = {path.parent.name: path for path in files}
        for session in summary["sessions"]:
            add_source_event_diagnostics(session, by_id[session["session_id"]], max_gap_seconds)
        summary["source_diagnostics"] = {
            "replay_order": "Offline counterfactual replay after CSV capture; source Unity row order is preserved.",
            "max_decision_gap_seconds_from_locked_manifest": max_gap_seconds,
            "gap_rule": "Only adjacent source Unity timestamps with present timestamps and sequences are compared. Missing values are not filled.",
            "long_gap_handling": "For source gaps over 0.1 seconds, the bridge stream guard clears prior feature history and resumes in warming_up until fresh history is ready. The listed mask reasons are the warnings returned during this replay.",
            "first_strong_fall_difference": "Arithmetic is shown in seconds using each source field as recorded. This is not measured UDP, display lead, or field performance.",
        }
        OUTPUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"summary": str(OUTPUT_JSON), "source_event_diagnostics_added": len(summary["sessions"])}, indent=2))
        return
    before = {str(path): sha256(path) for path in files}
    bridge, load_info, model, locked_manifest = load_bridge()
    warning_update_sequence = [0]

    sessions = []
    for path in files:
        session = replay_session(path, bridge, warning_update_sequence)
        add_source_event_diagnostics(session, path, max_gap_seconds)
        sessions.append(session)
    if bridge.runtime is not None and bridge.runtime._owner_run_id is not None:
        bridge.runtime.end_run()

    after = {str(path): sha256(path) for path in files}
    integrity = {
        path: {"before": before[path], "after": after[path], "unchanged": before[path] == after[path]}
        for path in before
    }
    summary = {
        "purpose": "offline-counterfactual replay of 1012TEST source Unity rows through the frozen warning bridge",
        "execution_order": "offline replay after source CSV capture",
        "scope": {
            "sessions": len(sessions),
            "source": str(INPUT_ROOT),
            "bridge_enabled": True,
            "allow_calibration_gameplay": True,
            "model_manifest": str(MANIFEST),
            "model_sha256": PINNED_MODEL_SHA256,
            "model_loaded_via_bridge": bool(load_info.get("loaded")),
            "model_id": load_info.get("model_id"),
            "threshold": getattr(model, "threshold", None),
            "confirmation_points": locked_manifest.get("confirmation_points"),
            "decision_interval_seconds": locked_manifest.get("decision_interval_seconds"),
            "max_decision_gap_seconds": locked_manifest.get("max_decision_gap_seconds"),
            "recovery_policy": locked_manifest.get("recovery_policy"),
            "replay_receipt": "backend_timestamp - first Unity row backend_timestamp per CSV; missing values are not synthesized",
            "mapping": "logger column mapping only; source values are not adjusted",
            "not_claimed": ["live UDP operation", "HUD display", "field model performance", "deployment outcome"],
        },
        "totals": {
            "rows": sum(s["rows"] for s in sessions),
            "accepted": sum(s["accepted"] for s in sessions),
            "valid": sum(s["valid"] for s in sessions),
            "strong_seen": sum(s["strong_seen"] for s in sessions),
            "strong_episodes": sum(s["strong_episode_count"] for s in sessions),
        },
        "warning_update_sequence": {
            "monotonic_across_all_sessions": all(s["warning_update_sequence_monotonic"] for s in sessions),
            "final_value": warning_update_sequence[0],
        },
        "input_integrity": integrity,
        "all_input_csv_unchanged": all(v["unchanged"] for v in integrity.values()),
        "sessions": sessions,
    }
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "summary": str(OUTPUT_JSON),
        "sessions": len(sessions),
        "totals": summary["totals"],
        "warning_update_sequence_monotonic": summary["warning_update_sequence"]["monotonic_across_all_sessions"],
        "all_input_csv_unchanged": summary["all_input_csv_unchanged"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
