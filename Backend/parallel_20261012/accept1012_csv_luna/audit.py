import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\1012TEST")
OUT = Path(__file__).with_name("summary.json")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def val(row, key):
    return (row.get(key) or "").strip()


def number(s):
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        x = float(s)
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def timestamp(s):
    x = number(s)
    if x is not None:
        return x
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return None


def unique_values(rows, key):
    return sorted({val(r, key) for r in rows if val(r, key)})


def percentile(values, p):
    if not values:
        return None
    a = sorted(values)
    pos = (len(a) - 1) * p
    lo, hi = int(pos), math.ceil(pos)
    return a[lo] + (a[hi] - a[lo]) * (pos - lo)


def analyze(path):
    before = sha(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)
    after = sha(path)
    sid = path.parent.name.removeprefix("session_")
    unity = [r for r in rows if val(r, "source").lower() == "unity"]
    wii = [r for r in rows if val(r, "source").lower() == "wii"]
    tids = [timestamp(val(r, "source_timestamp")) for r in rows]
    tids_valid = [x for x in tids if x is not None]
    intervals = [b - a for a, b in zip(tids_valid, tids_valid[1:])]
    per_source = {}
    for source, group in (("unity", unity), ("wii", wii)):
        ts = [timestamp(val(r, "source_timestamp")) for r in group]
        ts = [x for x in ts if x is not None]
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        per_source[source] = {
            "source_timestamp_first": group[0].get("source_timestamp") if group else None,
            "source_timestamp_last": group[-1].get("source_timestamp") if group else None,
            "source_timestamp_span_seconds": (max(ts) - min(ts)) if ts else None,
            "sampling_interval_seconds_p50": percentile(gaps, .50),
            "sampling_interval_seconds_p95": percentile(gaps, .95),
            "sampling_interval_seconds_max": max(gaps) if gaps else None,
        }
    run_ids = unique_values(unity, "run_id")
    seq = [number(val(r, "sequence")) for r in unity]
    seq = [int(x) for x in seq if x is not None]
    seq_gaps = [(a, b) for a, b in zip(seq, seq[1:]) if b <= a]
    time_pairs = [timestamp(val(r, "source_timestamp")) for r in unity]
    time_pairs = [x for x in time_pairs if x is not None]
    time_bad = [(a, b) for a, b in zip(time_pairs, time_pairs[1:]) if b <= a]
    end_fields = [val(r, "session_end_backend_timestamp") for r in unity]
    terminal_fields = [val(r, "run_state") for r in unity]
    outcome_fields = [val(r, "session_outcome") for r in unity]
    fall_reasons = [val(r, "fall_reason") for r in unity if val(r, "fall_reason")]
    run_state_events = []
    outcome_events = []
    prev = object()
    for i, r in enumerate(unity):
        state = val(r, "run_state")
        if state and state != prev:
            run_state_events.append({"unity_row_index": i, "run_state": state, "source_timestamp": val(r, "source_timestamp")})
        prev = state
    prev = object()
    for i, r in enumerate(unity):
        outcome = val(r, "session_outcome")
        if outcome and outcome != prev:
            outcome_events.append({"unity_row_index": i, "session_outcome": outcome, "source_timestamp": val(r, "source_timestamp")})
        prev = outcome
    # Count edge_warning_state transitions from non-active to active and active to non-active.
    edge_states = [val(r, "edge_warning_state") for r in unity]
    active_tokens = {"warning", "active", "enter", "entered", "true", "1", "on"}
    def active(s):
        return s.lower() in active_tokens or "warn" in s.lower() or "enter" in s.lower()
    enters = exits = 0
    segments = []
    in_segment = False
    start = None
    for i, state in enumerate(edge_states):
        is_active = active(state)
        was_active = active(edge_states[i - 1]) if i else False
        if is_active and not was_active:
            enters += 1
            start = i
            in_segment = True
        elif was_active and not is_active:
            exits += 1
            segments.append({"start_unity_row_index": start, "end_unity_row_index": i, "start_state": edge_states[start], "end_state": state})
            in_segment = False
        if i == len(edge_states) - 1 and in_segment:
            segments.append({"start_unity_row_index": start, "end_unity_row_index": None, "start_state": edge_states[start], "end_state": None, "open_at_end": True})
    geometry_rows = [r for r in unity if val(r, "geometry_query_valid").lower() in {"true", "1"}]
    owner_rows = [r for r in unity if val(r, "geometry_ownership_valid").lower() in {"true", "1"}]
    mismatch_rows = [r for r in unity if (val(r, "geometry_platform_instance_id") and val(r, "geometry_active_platform_instance_id") and val(r, "geometry_platform_instance_id") != val(r, "geometry_active_platform_instance_id")) or (val(r, "geometry_version_id") and val(r, "geometry_active_version_id") and val(r, "geometry_version_id") != val(r, "geometry_active_version_id"))]
    parameter_fields = ["calibration_mode", "selected_session_layers", "selected_difficulty", "actualdifficulty", "actual_difficulty", "difficulty", "platform_difficulty", "active_platform_difficulty"]
    actual_fields = [h for h in headers if h.lower() in {"actualdifficulty", "actual_difficulty"}]
    params = {k: unique_values(unity, k) for k in parameter_fields if k in headers}
    layer_fields = [h for h in headers if "layer" in h.lower()]
    layer_values = {k: unique_values(unity, k) for k in layer_fields if unique_values(unity, k)}
    model_fields = [h for h in headers if re.search(r"model_warning|update_sequence|model.*(score|prob|confidence)|(?:score|prob|confidence).*model", h, re.I)]
    attention_values = Counter(val(r, "attention_state") for r in unity if val(r, "attention_state"))
    prediction_values = Counter(val(r, "prediction_state") for r in unity if val(r, "prediction_state"))
    last = unity[-1] if unity else {}
    last_keys = ["source_timestamp", "sequence", "run_id", "run_state", "session_outcome", "session_end_backend_timestamp", "passed_count", "commanded_difficulty", "active_platform_difficulty", "difficulty", "fall_event", "fall_reason", "attention_state", "prediction_state", "warning_type", "warning_active", "visible_warning_state", "edge_warning_state", "edge_warning_time", "geometry_query_valid", "geometry_ownership_valid", "geometry_platform_instance_id", "geometry_version_id", "geometry_active_platform_instance_id", "geometry_active_version_id"]
    return {
        "sessionID": sid,
        "file": str(path),
        "sha256_before": before,
        "sha256_after": after,
        "raw_unchanged": before == after,
        "row_counts": {"all": len(rows), "unity": len(unity), "wii": len(wii), "other": len(rows) - len(unity) - len(wii)},
        "run_ids": run_ids,
        "timestamps": {"all_rows": {"first": rows[0].get("source_timestamp") if rows else None, "last": rows[-1].get("source_timestamp") if rows else None, "span_seconds_by_sorted_valid_timestamp": max(tids_valid) - min(tids_valid) if tids_valid else None, "sampling_interval_seconds_p50": percentile(intervals, .50), "sampling_interval_seconds_p95": percentile(intervals, .95), "sampling_interval_seconds_max": max(intervals) if intervals else None}, "by_source_in_file_order": per_source},
        "unity_sequence": {"first": seq[0] if seq else None, "last": seq[-1] if seq else None, "duplicate_or_nonincreasing_adjacent_count": sum(b == a for a, b in zip(seq, seq[1:])), "descending_adjacent_count": sum(b < a for a, b in zip(seq, seq[1:])), "nonincreasing_pairs_sample": seq_gaps[:20]},
        "unity_source_time": {"duplicate_or_nonincreasing_adjacent_count": sum(b == a for a, b in zip(time_pairs, time_pairs[1:])), "descending_adjacent_count": sum(b < a for a, b in zip(time_pairs, time_pairs[1:]))},
        "configuration_values": params,
        "layer_field_values": layer_values,
        "actualdifficulty_header_present": bool(actual_fields),
        "terminal_events": {"run_state_transition_events": run_state_events, "session_outcome_transition_events": outcome_events, "run_state_values": sorted(set(terminal_fields) - {""}), "session_outcome_values": sorted(set(outcome_fields) - {""}), "fall_reason_values": sorted(set(fall_reasons)), "fall_event_true_rows": sum(val(r, "fall_event").lower() in {"true", "1"} for r in unity), "session_end_backend_timestamp_nonempty_rows": sum(bool(x and x.lower() != "nan") for x in end_fields), "end_missing_status": "end timestamp absent; restart only a possibility, requires external confirmation" if not any(x and x.lower() != "nan" for x in end_fields) else "end timestamp present"},
        "edge_warning_state": {"distinct_values": sorted(set(edge_states) - {""}), "enters": enters, "exits": exits, "segments": segments, "counting_note": "Transitions inferred from edge_warning_state tokens; verify field semantics if states are not active/inactive labels."},
        "geometry": {"unity_rows": len(unity), "query_valid_rows": len(geometry_rows), "ownership_valid_rows": len(owner_rows), "identity_mismatch_rows": len(mismatch_rows), "identity_mismatch_ratio_unity": len(mismatch_rows) / len(unity) if unity else None, "identity_mismatch_ratio_of_rows_with_both_ids": sum(1 for r in unity if val(r, "geometry_platform_instance_id") and val(r, "geometry_active_platform_instance_id") and val(r, "geometry_version_id") and val(r, "geometry_active_version_id") and (val(r, "geometry_platform_instance_id") != val(r, "geometry_active_platform_instance_id") or val(r, "geometry_version_id") != val(r, "geometry_active_version_id"))) / max(1, sum(1 for r in unity if val(r, "geometry_platform_instance_id") and val(r, "geometry_active_platform_instance_id") and val(r, "geometry_version_id") and val(r, "geometry_active_version_id"))), "platform_instance_ids": unique_values(unity, "geometry_platform_instance_id"), "version_ids": unique_values(unity, "geometry_version_id"), "active_platform_instance_ids": unique_values(unity, "geometry_active_platform_instance_id"), "active_version_ids": unique_values(unity, "geometry_active_version_id")},
        "model_evidence": {"model_warning_or_update_sequence_or_model_score_headers": model_fields, "model_warning_present": any("model_warning" in x.lower() for x in headers), "update_sequence_present": any("update_sequence" in x.lower() for x in headers), "attention_state_values_are_csv_labels_only": dict(attention_values), "prediction_state_values_are_csv_labels_only": dict(prediction_values), "interpretation": "CSV fields alone do not prove ML strong prompt/alert behavior; missing model evidence columns cannot establish that the model did not alert."},
        "last_unity_row_key_fields": {k: last.get(k) for k in last_keys if k in headers},
        "headers": headers,
    }


def main():
    files = sorted(ROOT.glob("session_*/raw.csv"))
    sessions = [analyze(p) for p in files]
    report = {"source_root": str(ROOT), "sessions_found": len(files), "sessionID_policy": "Each sessionID is preserved from its own directory name; no cross-session joining or normalization.", "method": "Python standard-library csv and hashlib SHA-256 before/after; input CSVs opened read-only.", "sessions": sessions}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "sessions_found": len(sessions), "all_raw_unchanged": all(s["raw_unchanged"] for s in sessions), "counts": [{"sessionID": s["sessionID"], **s["row_counts"], "run_ids": s["run_ids"]} for s in sessions]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
