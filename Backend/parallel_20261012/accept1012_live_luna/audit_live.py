import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


BASE = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\1012TEST")
EDITOR_LOG = Path(r"C:\Users\QIYUXUAN\AppData\Local\Unity\Editor\Editor.log")
SESSIONS = [
    "session_20261012_101911_080981",
    "session_20261012_101940_356172",
    "session_20261012_102000_453011",
    "session_20261012_102014_820513",
]
LOG_RE = re.compile(
    r"\[ExperimentalModelWarning\]\s+state=(\S+)\s+local_monotonic_s=(\S+)"
    r"\s+run_id=(\S+)\s+prediction_sequence=(\S+)\s+reason=(\S+)\s+revoke_reason=(\S+)"
)


def present(value):
    return value is not None and value.strip() not in ("", "nan", "NaN", "None")


def values(rows, key):
    return sorted({r[key] for r in rows if present(r.get(key))})


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sequence_audit(rows):
    seqs = []
    for row in rows:
        if row.get("source") == "unity" and present(row.get("sequence")):
            try:
                seqs.append(int(row["sequence"]))
            except ValueError:
                pass
    missing = []
    duplicates = []
    reversals = []
    for i, seq in enumerate(seqs):
        if i and seq == seqs[i - 1]:
            duplicates.append({"index": i, "sequence": seq})
        if i and seq < seqs[i - 1]:
            reversals.append({"index": i, "previous": seqs[i - 1], "sequence": seq})
        if i and seq > seqs[i - 1] + 1:
            missing.append({"after": seqs[i - 1], "before": seq, "count": seq - seqs[i - 1] - 1})
    return {"count": len(seqs), "first": seqs[0] if seqs else None, "last": seqs[-1] if seqs else None,
            "missing_gaps": missing, "duplicate_adjacent": duplicates, "decreases_or_reversals": reversals}


def source_spans(rows):
    out = {}
    for source in sorted({r.get("source", "") for r in rows}):
        group = [r for r in rows if r.get("source") == source]
        field = "source_timestamp"
        times = [r.get(field, "") for r in group if present(r.get(field))]
        out[source] = {"rows": len(group), "timestamp_field": field,
                       "first_in_file": times[0] if times else None,
                       "last_in_file": times[-1] if times else None,
                       "minimum_lexical": min(times) if times else None,
                       "maximum_lexical": max(times) if times else None}
    return out


def geometry_audit(rows):
    geometry_rows = [r for r in rows if present(r.get("geometry_platform_instance_id")) or present(r.get("geometry_version_id"))]
    ownership_false = [r for r in geometry_rows if r.get("geometry_ownership_valid", "").lower() == "false"]
    query_false = [r for r in geometry_rows if r.get("geometry_query_valid", "").lower() == "false"]
    mismatches = []
    for r in geometry_rows:
        mismatches_for_row = []
        for a, b in (("geometry_platform_instance_id", "geometry_active_platform_instance_id"),
                     ("geometry_version_id", "geometry_active_version_id")):
            if present(r.get(a)) and present(r.get(b)) and r[a] != r[b]:
                mismatches_for_row.append({"fields": [a, b], "values": [r[a], r[b]]})
        if mismatches_for_row:
            mismatches.append({"source": r.get("source"), "sequence": r.get("sequence"), "mismatches": mismatches_for_row})
    return {
        "rows_with_geometry_identity": len(geometry_rows),
        "geometry_query_valid_values": dict(Counter(r.get("geometry_query_valid", "") for r in geometry_rows)),
        "geometry_ownership_valid_values": dict(Counter(r.get("geometry_ownership_valid", "") for r in geometry_rows)),
        "ownership_false_count": len(ownership_false), "query_false_count": len(query_false),
        "identity_mismatch_count": len(mismatches), "identity_mismatches": mismatches,
        "raw_identity_values": sorted({(r.get("geometry_platform_instance_id", ""), r.get("geometry_version_id", ""),
                                         r.get("geometry_active_platform_instance_id", ""), r.get("geometry_active_version_id", ""))
                                        for r in geometry_rows}),
        "raw_geometry_source_timestamp_span": {
            "first_in_file": next((r.get("geometry_source_timestamp") for r in geometry_rows if present(r.get("geometry_source_timestamp"))), None),
            "last_in_file": next((r.get("geometry_source_timestamp") for r in reversed(geometry_rows) if present(r.get("geometry_source_timestamp"))), None),
            "unique_value_count": len(values(geometry_rows, "geometry_source_timestamp")),
        },
    }


def parse_log():
    stat_before = EDITOR_LOG.stat()
    before = {"size_bytes": stat_before.st_size, "mtime_utc": datetime.fromtimestamp(stat_before.st_mtime, tz=__import__('datetime').timezone.utc).isoformat(),
              "sha256": hashlib.sha256(EDITOR_LOG.read_bytes()).hexdigest()}
    matched = []
    with EDITOR_LOG.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            if "[ExperimentalModelWarning]" not in line:
                continue
            match = LOG_RE.search(line)
            if match:
                state, mono, run_id, seq, reason, revoke_reason = match.groups()
                matched.append({"line_number": line_number, "state": state, "local_monotonic_s": mono,
                                "run_id": run_id, "prediction_sequence": seq,
                                "reason": reason, "revoke_reason": revoke_reason})
    stat_after = EDITOR_LOG.stat()
    after = {"size_bytes": stat_after.st_size, "mtime_utc": datetime.fromtimestamp(stat_after.st_mtime, tz=__import__('datetime').timezone.utc).isoformat(),
             "sha256": hashlib.sha256(EDITOR_LOG.read_bytes()).hexdigest()}
    return {"before": before, "after": after, "changed_during_read": before != after, "matched_lines": matched}


def run_audit(log_rows, run_id):
    matched = [r for r in log_rows if r["run_id"] == run_id]
    received = [r for r in matched if r["state"] == "RECEIVED"]
    received_counts = Counter(r["revoke_reason"] for r in received)
    states = Counter(r["state"] for r in matched)
    episodes = []
    active = None
    orphan_revokes = 0
    for row in matched:
        if row["state"] == "ACTIVE":
            if active is None:
                trigger = next((x for x in reversed(matched)
                                if x["state"] == "RECEIVED"
                                and x["prediction_sequence"] == row["prediction_sequence"]
                                and x["line_number"] < row["line_number"]), None)
                active = {"first_active_local_monotonic_s": row["local_monotonic_s"],
                          "first_active_prediction_sequence": row["prediction_sequence"],
                          "activation_received": ({k: trigger[k] for k in ("line_number", "local_monotonic_s", "prediction_sequence", "reason", "revoke_reason")} if trigger else None),
                          "last_active_local_monotonic_s": row["local_monotonic_s"],
                          "last_active_prediction_sequence": row["prediction_sequence"],
                          "active_line_count": 1}
            else:
                active["last_active_local_monotonic_s"] = row["local_monotonic_s"]
                active["last_active_prediction_sequence"] = row["prediction_sequence"]
                active["active_line_count"] += 1
        elif row["state"] == "REVOKED" and active is not None:
            active.update({"revoked_local_monotonic_s": row["local_monotonic_s"],
                           "revoked_prediction_sequence": row["prediction_sequence"],
                           "revoke_reason": row["revoke_reason"],
                           "same_sequence_unknown_received_preceded_revoke": any(
                               x["state"] == "RECEIVED" and x["revoke_reason"] == "UNKNOWN"
                               and x["prediction_sequence"] == row["prediction_sequence"]
                               and x["line_number"] < row["line_number"] for x in matched)}
            )
            episodes.append(active)
            active = None
        elif row["state"] == "REVOKED":
            orphan_revokes += 1
    if active is not None:
        active["revoked_local_monotonic_s"] = None
        active["revoked_prediction_sequence"] = None
        active["revoke_reason"] = None
        active["same_sequence_unknown_received_preceded_revoke"] = False
        episodes.append(active)
    return {"run_id": run_id, "matched_line_count": len(matched), "state_counts": dict(states),
            "received_revoke_reason_counts": dict(received_counts),
            "received_raw_status_counts": dict(received_counts),
            "active_episodes": episodes, "unmatched_orphan_revokes": orphan_revokes,
            "first_matched_log_line": matched[0]["line_number"] if matched else None,
            "last_matched_log_line": matched[-1]["line_number"] if matched else None}


def audit():
    log = parse_log()
    results = []
    for session_id in SESSIONS:
        path = BASE / session_id / "raw.csv"
        csv_before = path.read_bytes()
        csv_before_sha256 = hashlib.sha256(csv_before).hexdigest()
        with io.TextIOWrapper(io.BytesIO(csv_before), encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        csv_after_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        unity = [r for r in rows if r.get("source") == "unity"]
        run_ids = values(unity, "run_id")
        run_id = run_ids[0] if len(run_ids) == 1 else None
        tail = unity[-1] if unity else {}
        raw_tail = rows[-1] if rows else {}
        results.append({
            "session_id": session_id, "raw_csv": str(path), "raw_row_count": len(rows),
            "raw_csv_snapshot": {"sha256_before_read": csv_before_sha256, "sha256_after_read": csv_after_sha256,
                                 "changed_during_read": csv_before_sha256 != csv_after_sha256,
                                 "bytes_analyzed": len(csv_before)},
            "source_counts": dict(Counter(r.get("source", "") for r in rows)),
            "run_ids": run_ids, "run_id": run_id,
            "source_spans": source_spans(rows),
            "selected_difficulty_values": values(unity, "selected_difficulty"),
            "commanded_difficulty_values": values(unity, "commanded_difficulty"),
            "active_platform_difficulty_values": values(unity, "active_platform_difficulty"),
            "difficulty_values": values(unity, "difficulty"),
            "platform_difficulty_values": values(unity, "platform_difficulty"),
            "selected_session_layers_values": values(unity, "selected_session_layers"),
            "identity_values": {k: values(unity, k) for k in ("response_experiment_id", "experiment_id", "response_condition", "trial_scenario", "trial_valid", "response_trial_id", "trial_id", "response_layer_id", "layer_id")},
            "terminal_unity_row": {k: tail.get(k) for k in ("backend_timestamp", "source_timestamp", "sequence", "run_id", "run_state", "session_outcome", "session_end_backend_timestamp", "passed_count", "selected_difficulty", "active_platform_difficulty", "platform_difficulty", "difficulty", "prediction_state", "visible_warning_state", "warning_episode_id", "warning_episode_end_time", "warning_episode_end_backend_timestamp")},
            "raw_last_row": {k: raw_tail.get(k) for k in ("backend_timestamp", "source", "source_timestamp", "sequence", "run_id", "run_state", "session_outcome", "session_end_backend_timestamp", "passed_count", "fall_event", "fall_reason", "prediction_state", "visible_warning_state", "warning_episode_id", "warning_episode_end_time", "warning_episode_end_backend_timestamp")},
            "unity_sequence_audit": sequence_audit(rows),
            "geometry": geometry_audit(rows),
            "model_warning_log": run_audit(log["matched_lines"], run_id) if run_id else {"run_id": None, "matched_line_count": 0, "note": "No unique Unity run_id; not inferred."},
        })
    return {"audit_method": {"log_join": "Exact run_id from Unity Editor.log single-line [ExperimentalModelWarning] records only; stack traces excluded.",
                              "raw_status_field": "RECEIVED revoke_reason value is the raw SAFE/STRONG/UNKNOWN status.",
                              "episode_rule": "First ACTIVE opens an episode; subsequent ACTIVE updates it; first REVOKED closes it.",
                              "visual_observation": "No per-run visual observation assigned; user only saw an independent banner without run identification."},
            "editor_log_snapshot": log, "sessions": results}


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
