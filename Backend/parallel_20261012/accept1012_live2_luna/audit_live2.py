import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\1012TEST")
EDITOR_LOG = Path(r"C:\Users\QIYUXUAN\AppData\Local\Unity\Editor\Editor.log")
SESSIONS = ["session_20261012_103349_663622", "session_20261012_103420_415741", "session_20261012_103433_164318"]
LOG_RE = re.compile(r"\[ExperimentalModelWarning\]\s+state=(\S+)\s+local_monotonic_s=(\S+)\s+run_id=(\S+)\s+prediction_sequence=(\S+)\s+reason=(\S+)\s+revoke_reason=(\S+)")


def present(v):
    return v is not None and str(v).strip() not in ("", "nan", "NaN", "None")


def values(rows, key):
    return sorted({r[key] for r in rows if present(r.get(key))})


def seq_audit(rows):
    seq = []
    for r in rows:
        if r.get("source") == "unity" and present(r.get("sequence")):
            try:
                seq.append(int(r["sequence"]))
            except ValueError:
                pass
    gaps, duplicates, reversals = [], [], []
    for i, n in enumerate(seq):
        if i and n == seq[i - 1]:
            duplicates.append({"index": i, "sequence": n})
        if i and n < seq[i - 1]:
            reversals.append({"index": i, "previous": seq[i - 1], "sequence": n})
        if i and n > seq[i - 1] + 1:
            gaps.append({"after": seq[i - 1], "before": n, "count": n - seq[i - 1] - 1})
    return {"count": len(seq), "first": seq[0] if seq else None, "last": seq[-1] if seq else None,
            "missing_gaps": gaps, "duplicate_adjacent": duplicates, "decreases_or_reversals": reversals}


def spans(rows):
    out = {}
    for source in sorted({r.get("source", "") for r in rows}):
        g = [r for r in rows if r.get("source") == source]
        ts = [r.get("source_timestamp", "") for r in g if present(r.get("source_timestamp"))]
        out[source] = {"rows": len(g), "timestamp_field": "source_timestamp",
                       "first_in_file": ts[0] if ts else None, "last_in_file": ts[-1] if ts else None,
                       "minimum_lexical": min(ts) if ts else None, "maximum_lexical": max(ts) if ts else None}
    return out


def geometry(rows):
    g = [r for r in rows if present(r.get("geometry_platform_instance_id")) or present(r.get("geometry_version_id"))]
    mismatches = []
    for r in g:
        diffs = []
        for a, b in (("geometry_platform_instance_id", "geometry_active_platform_instance_id"),
                     ("geometry_version_id", "geometry_active_version_id")):
            if present(r.get(a)) and present(r.get(b)) and r[a] != r[b]:
                diffs.append({"fields": [a, b], "values": [r[a], r[b]]})
        if diffs:
            mismatches.append({"source": r.get("source"), "sequence": r.get("sequence"), "mismatches": diffs})
    q = Counter(r.get("geometry_query_valid", "") for r in g)
    o = Counter(r.get("geometry_ownership_valid", "") for r in g)
    timestamps = [r.get("geometry_source_timestamp") for r in g if present(r.get("geometry_source_timestamp"))]
    return {"rows_with_geometry_identity": len(g), "geometry_query_valid_values": dict(q),
            "geometry_ownership_valid_values": dict(o), "query_false_count": q.get("False", 0),
            "ownership_false_count": o.get("False", 0), "identity_mismatch_count": len(mismatches),
            "identity_mismatches": mismatches,
            "raw_identity_values": sorted({(r.get("geometry_platform_instance_id", ""), r.get("geometry_version_id", ""),
                                              r.get("geometry_active_platform_instance_id", ""), r.get("geometry_active_version_id", "")) for r in g}),
            "raw_geometry_source_timestamp_span": {"first_in_file": timestamps[0] if timestamps else None,
                                                    "last_in_file": timestamps[-1] if timestamps else None,
                                                    "unique_value_count": len(set(timestamps))}}


def read_log():
    def snapshot():
        st = EDITOR_LOG.stat()
        return {"size_bytes": st.st_size,
                "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "sha256": hashlib.sha256(EDITOR_LOG.read_bytes()).hexdigest()}
    before = snapshot()
    records = []
    with EDITOR_LOG.open("r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            if "[ExperimentalModelWarning]" not in line:
                continue
            m = LOG_RE.search(line)
            if m:
                state, mono, run, seq, reason, revoke = m.groups()
                records.append({"line_number": line_num, "state": state, "local_monotonic_s": mono,
                                "run_id": run, "prediction_sequence": seq, "reason": reason,
                                "revoke_reason": revoke})
    after = snapshot()
    return {"before": before, "after": after, "changed_during_read": before != after}, records


def run_log(records, run_id):
    if not run_id:
        return {"run_id": None, "matched_line_count": 0, "note": "No run_id in the CSV Unity stream; log join not inferred."}
    recs = [r for r in records if r["run_id"] == run_id]
    counts = Counter(r["state"] for r in recs)
    received_counts = Counter(r["revoke_reason"] for r in recs if r["state"] == "RECEIVED")
    episodes, opened, orphan_revokes = [], None, 0
    for r in recs:
        if r["state"] == "ACTIVE":
            if opened is None:
                preceding = next((x for x in reversed(recs) if x["state"] == "RECEIVED"
                                  and x["prediction_sequence"] == r["prediction_sequence"]
                                  and x["line_number"] < r["line_number"]), None)
                opened = {"first_active_local_monotonic_s": r["local_monotonic_s"],
                          "first_active_prediction_sequence": r["prediction_sequence"],
                          "activation_received": ({k: preceding[k] for k in ("line_number", "local_monotonic_s", "prediction_sequence", "reason", "revoke_reason")} if preceding else None),
                          "last_active_local_monotonic_s": r["local_monotonic_s"],
                          "last_active_prediction_sequence": r["prediction_sequence"], "active_line_count": 1}
            else:
                opened["last_active_local_monotonic_s"] = r["local_monotonic_s"]
                opened["last_active_prediction_sequence"] = r["prediction_sequence"]
                opened["active_line_count"] += 1
        elif r["state"] == "REVOKED":
            if opened is None:
                orphan_revokes += 1
                continue
            preceding = next((x for x in reversed(recs) if x["state"] == "RECEIVED"
                              and x["line_number"] < r["line_number"]), None)
            same_unknown = any(x["state"] == "RECEIVED" and x["revoke_reason"] == "UNKNOWN"
                               and x["prediction_sequence"] == r["prediction_sequence"]
                               and x["line_number"] < r["line_number"] for x in recs)
            opened.update({"revoked_local_monotonic_s": r["local_monotonic_s"],
                           "revoked_prediction_sequence": r["prediction_sequence"],
                           "revoke_reason": r["revoke_reason"], "revoke_event_reason": r["reason"],
                           "preceding_received": ({k: preceding[k] for k in ("line_number", "local_monotonic_s", "prediction_sequence", "reason", "revoke_reason")} if preceding else None),
                           "same_sequence_unknown_received_preceded_revoke": same_unknown})
            episodes.append(opened)
            opened = None
    if opened:
        opened.update({"revoked_local_monotonic_s": None, "revoked_prediction_sequence": None,
                       "revoke_reason": None, "revoke_event_reason": None, "preceding_received": None,
                       "same_sequence_unknown_received_preceded_revoke": False})
        episodes.append(opened)
    return {"run_id": run_id, "matched_line_count": len(recs), "state_counts": dict(counts),
            "received_raw_status_counts_from_revoke_reason": dict(received_counts),
            "active_episodes": episodes, "unmatched_orphan_revokes": orphan_revokes,
            "first_matched_log_line": recs[0]["line_number"] if recs else None,
            "last_matched_log_line": recs[-1]["line_number"] if recs else None}


def audit():
    editor_snapshot, records = read_log()
    sessions = []
    for sid in SESSIONS:
        path = BASE / sid / "raw.csv"
        data_before = path.read_bytes()
        hash_before = hashlib.sha256(data_before).hexdigest()
        with io.TextIOWrapper(io.BytesIO(data_before), encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        hash_after = hashlib.sha256(path.read_bytes()).hexdigest()
        unity = [r for r in rows if r.get("source") == "unity"]
        run_ids = values(unity, "run_id")
        run_id = run_ids[0] if len(run_ids) == 1 else None
        tail = unity[-1] if unity else {}
        raw_tail = rows[-1] if rows else {}
        sessions.append({"session_id": sid, "raw_csv": str(path), "raw_csv_snapshot": {
            "sha256_before_read": hash_before, "sha256_after_read": hash_after,
            "changed_during_read": hash_before != hash_after, "bytes_analyzed": len(data_before)},
            "raw_row_count": len(rows), "source_counts": dict(Counter(r.get("source", "") for r in rows)),
            "run_ids": run_ids, "run_id": run_id, "source_spans": spans(rows),
            "selected_difficulty_values": values(unity, "selected_difficulty"),
            "commanded_difficulty_values": values(unity, "commanded_difficulty"),
            "active_platform_difficulty_values": values(unity, "active_platform_difficulty"),
            "difficulty_values": values(unity, "difficulty"), "platform_difficulty_values": values(unity, "platform_difficulty"),
            "selected_session_layers_values": values(unity, "selected_session_layers"),
            "identity_values": {k: values(unity, k) for k in ("response_experiment_id", "experiment_id", "response_condition", "trial_scenario", "trial_valid", "response_trial_id", "trial_id", "response_layer_id", "layer_id")},
            "terminal_unity_row": {k: tail.get(k) for k in ("backend_timestamp", "source_timestamp", "sequence", "run_id", "run_state", "session_outcome", "session_end_backend_timestamp", "passed_count", "prediction_state", "visible_warning_state", "warning_episode_id", "warning_episode_start_time", "warning_episode_start_backend_timestamp", "warning_episode_end_time", "warning_episode_end_backend_timestamp")},
            "raw_last_row": {k: raw_tail.get(k) for k in ("backend_timestamp", "source", "source_timestamp", "sequence", "run_id", "run_state", "session_outcome", "session_end_backend_timestamp", "passed_count", "fall_event", "fall_reason", "prediction_state", "visible_warning_state", "warning_episode_id", "warning_episode_end_time", "warning_episode_end_backend_timestamp")},
            "unity_sequence_audit": seq_audit(rows), "geometry": geometry(rows), "model_warning_log": run_log(records, run_id)})
    transitions = []
    for prev, nxt in zip(sessions, sessions[1:]):
        old = [r for r in records if r["run_id"] == prev["run_id"]]
        new = [r for r in records if r["run_id"] == nxt["run_id"]]
        if old and new:
            old_last, new_first = old[-1], new[0]
            transitions.append({"from_run_id": prev["run_id"], "from_last_record": old_last,
                                "to_run_id": nxt["run_id"], "to_first_record": new_first,
                                "local_monotonic_gap_s": round(float(new_first["local_monotonic_s"]) - float(old_last["local_monotonic_s"]), 6)})
    return {"audit_method": {"log_join": "Exact run_id match against single [ExperimentalModelWarning] lines; stack traces excluded.",
                             "episode_rule": "First ACTIVE opens; later ACTIVE updates same episode; first REVOKED closes.",
                             "preceding_received_rule": "For each REVOKED, retain the closest preceding RECEIVED line and its reason/status. No server stop inferred from missing telemetry.",
                             "status_field": "RECEIVED raw SAFE/STRONG/UNKNOWN is in revoke_reason.",
                             "visual_observation": "No per-run visual observation assigned unless the source records identify it."},
            "editor_log_snapshot": editor_snapshot, "run_transition_log_recency": transitions, "sessions": sessions}


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
