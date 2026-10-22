"""Read-only audit of Unity warning visibility and matching telemetry sessions."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend")
LOG = Path(r"C:\Users\QIYUXUAN\AppData\Local\Unity\Editor\Editor.log")
OUT = ROOT / "parallel_20261012" / "disappear_audit_luna" / "summary.json"
SESSIONS = {
    "latest_104434": ROOT / "telemetry_logs" / "1012TEST" / "session_20261012_104434_821214" / "raw.csv",
    "prior_103349": ROOT / "telemetry_logs" / "1012TEST" / "session_20261012_103349_663622" / "raw.csv",
}
RUN_IDS = {
    "latest_104434": "567a765f63824eaa88db0381beebb44f",
    "prior_103349": "e798e445cd4648bb883eff384d21788d",
}
LOG_RE = re.compile(
    r"\[ExperimentalModelWarning\]\s+state=(\S+)\s+local_monotonic_s=(\S+)"
    r"\s+run_id=(\S+)\s+prediction_sequence=(\S+)\s+reason=(\S+)\s+revoke_reason=(\S+)"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_snapshot(path: Path) -> dict:
    stat = path.stat()
    return {"bytes": stat.st_size, "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), "sha256": sha256(path)}


def fnum(value):
    try:
        if value is None or value == "":
            return None
        x = float(value)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def parse_log():
    snap0 = file_snapshot(LOG)
    records = []
    with LOG.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            match = LOG_RE.search(line)
            if not match:
                continue
            state, mono, run_id, pseq, reason, revoke = match.groups()
            records.append({"line_number": line_no, "state": state, "local_monotonic_s": mono,
                            "run_id": run_id, "prediction_sequence": pseq,
                            "reason": reason, "revoke_reason": revoke})
    snap1 = file_snapshot(LOG)
    results = {}
    for label, run_id in RUN_IDS.items():
        rs = [r for r in records if r["run_id"] == run_id]
        state_counts = Counter(r["state"] for r in rs)
        received_reasons = Counter(f"{r['reason']}|{r['revoke_reason']}" for r in rs if r["state"] == "RECEIVED")
        episodes, active = [], None
        for r in rs:
            if r["state"] == "ACTIVE":
                if active is None:
                    prior_received = next((x for x in reversed(rs[:rs.index(r)]) if x["state"] == "RECEIVED"), None)
                    active = {"first_active": r, "last_active": r, "active_line_count": 0,
                              "activation_received": prior_received}
                active["last_active"] = r
                active["active_line_count"] += 1
            elif r["state"] == "REVOKED" and active is not None:
                prior_received = next((x for x in reversed(rs[:rs.index(r)]) if x["state"] == "RECEIVED"), None)
                item = {"first_active": active["first_active"], "last_active": active["last_active"],
                        "active_line_count": active["active_line_count"], "revoked": r,
                        "preceding_received": prior_received}
                t = fnum(active["last_active"]["local_monotonic_s"])
                first_t = fnum(active["first_active"]["local_monotonic_s"])
                rev_t = fnum(r["local_monotonic_s"])
                if t is not None and rev_t is not None:
                    item["last_active_to_revoke_s"] = round(rev_t - t, 6)
                if first_t is not None and rev_t is not None:
                    item["first_active_to_revoke_elapsed_s"] = round(rev_t - first_t, 6)
                if r["revoke_reason"] == "prediction_age_exceeded_0_3s" and t is not None and rev_t is not None:
                    item["last_active_receipt_plus_0_3_to_revoke_s"] = round(rev_t - (t + 0.3), 6)
                    item["timeout_interpretation"] = "frontend age expiry observed; not evidence of backend stop time"
                episodes.append(item)
                active = None
        results[label] = {"run_id": run_id, "matched_line_count": len(rs),
                          "state_counts": dict(state_counts),
                          "received_reason_and_raw_status_counts": dict(received_reasons),
                          "active_episodes": episodes,
                          "open_active_at_log_end": active,
                          "first_log_line": rs[0]["line_number"] if rs else None,
                          "last_log_line": rs[-1]["line_number"] if rs else None}
    return {"snapshot_before": snap0, "snapshot_after": snap1,
            "changed_during_read": snap0 != snap1, "runs": results}


def session_summary(path: Path, expected_run: str):
    before = file_snapshot(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    after = file_snapshot(path)
    sources = Counter(r.get("source", "") for r in rows)
    unity = [r for r in rows if r.get("source") == "unity"]
    wii = [r for r in rows if r.get("source") == "wii"]
    terminal = [r for r in unity if r.get("run_state") and r["run_state"] != "running"]
    unity_sequences = [fnum(r.get("sequence")) for r in unity]
    seq_gaps = []
    for a, b in zip(unity_sequences, unity_sequences[1:]):
        if a is not None and b is not None and b != a + 1:
            seq_gaps.append({"previous": a, "next": b})

    geometry = []
    clearance_rows = []
    for i, r in enumerate(unity, 1):
        d, radius = fnum(r.get("directional_edge_distance")), fnum(r.get("ball_radius"))
        clearance = d - radius if d is not None and radius is not None else None
        geometry.append((r, clearance))
        if clearance is not None and clearance <= 0:
            clearance_rows.append({"unity_observation_ordinal": i,
                                   "backend_timestamp_epoch_s": r.get("backend_timestamp"),
                                   "source_timestamp": r.get("source_timestamp"),
                                   "unity_sequence": r.get("sequence"),
                                   "run_state": r.get("run_state"),
                                   "session_outcome": r.get("session_outcome"),
                                   "directional_edge_distance": r.get("directional_edge_distance"),
                                   "ball_radius": r.get("ball_radius"),
                                   "net_clearance_distance_minus_radius": round(clearance, 9),
                                   "ball_radial_velocity_outward_positive_convention": r.get("ball_radial_velocity"),
                                   "target_edge_radial_velocity": r.get("target_edge_radial_velocity"),
                                   "geometry_version_id": r.get("geometry_version_id"),
                                   "geometry_source_timestamp": r.get("geometry_source_timestamp")})
    geom_ts_gaps, geom_version_changes = [], []
    for (a, _), (b, _) in zip(geometry, geometry[1:]):
        ta, tb = fnum(a.get("geometry_source_timestamp")), fnum(b.get("geometry_source_timestamp"))
        if ta is not None and tb is not None and tb - ta > 0.100:
            geom_ts_gaps.append({"from": a.get("geometry_source_timestamp"), "to": b.get("geometry_source_timestamp"),
                                 "gap_s": round(tb - ta, 6), "unity_sequences": [a.get("sequence"), b.get("sequence")]})
        if a.get("geometry_version_id") and b.get("geometry_version_id") and a.get("geometry_version_id") != b.get("geometry_version_id"):
            geom_version_changes.append({"from": a.get("geometry_version_id"), "to": b.get("geometry_version_id"),
                                         "unity_sequences": [a.get("sequence"), b.get("sequence")],
                                         "geometry_source_timestamps": [a.get("geometry_source_timestamp"), b.get("geometry_source_timestamp")]})

    def source_span(rs):
        return {"rows": len(rs), "first_source_timestamp": rs[0].get("source_timestamp") if rs else None,
                "last_source_timestamp": rs[-1].get("source_timestamp") if rs else None,
                "first_backend_timestamp_epoch_s": rs[0].get("backend_timestamp") if rs else None,
                "last_backend_timestamp_epoch_s": rs[-1].get("backend_timestamp") if rs else None}

    terminal_row = terminal[-1] if terminal else None
    return {
        "path": str(path), "run_id_expected": expected_run,
        "run_ids_in_unity": sorted({r.get("run_id", "") for r in unity if r.get("run_id")}),
        "source_counts": dict(sources), "row_count": len(rows),
        "source_cutoffs": {"unity": source_span(unity), "wii": source_span(wii)},
        "unity_last_record": unity[-1] if unity else None,
        "terminal_unity_record": terminal_row,
        "run_ended_confirmed": bool(terminal_row),
        "terminal_interpretation": "terminal state recorded" if terminal_row else "no terminal Unity row in captured CSV; runtime completion is unknown",
        "unity_state_counts": dict(Counter(r.get("run_state", "") or "(blank)" for r in unity)),
        "unity_outcome_counts": dict(Counter(r.get("session_outcome", "") or "(blank)" for r in unity)),
        "unity_visible_warning_state_counts": dict(Counter(r.get("visible_warning_state", "") or "(blank)" for r in unity)),
        "unity_sequence_gap_count": len(seq_gaps), "unity_sequence_gaps": seq_gaps[:30],
        "geometry_net_clearance_nonpositive_count": len(clearance_rows),
        "geometry_net_clearance_nonpositive_rows": clearance_rows,
        "geometry_source_timestamp_gap_over_0_100s_count": len(geom_ts_gaps),
        "geometry_source_timestamp_gaps_over_0_100s": geom_ts_gaps,
        "geometry_version_change_count": len(geom_version_changes),
        "geometry_version_changes": geom_version_changes,
        "hash_before_read": before, "hash_after_read": after,
        "changed_during_read": before != after,
    }


def main():
    log = parse_log()
    sessions = {label: session_summary(path, RUN_IDS[label]) for label, path in SESSIONS.items()}
    result = {
        "audit_scope": "read-only telemetry and Unity Editor.log review; no model replay, training, or service startup",
        "method": {
            "log_join": "Exact run_id match on one [ExperimentalModelWarning] record per line.",
            "active_segment_rule": "First ACTIVE opens a contiguous logged active segment; following ACTIVE rows extend it; first REVOKED closes it.",
            "preceding_received_rule": "For each ACTIVE/REVOKED segment retain nearest earlier RECEIVED log row, including reason and revoke_reason raw status.",
            "time_domains": "Editor local_monotonic_s is only compared with itself. CSV backend/source timestamps are epoch/UTC telemetry clocks and are not subtracted from monotonic log times.",
            "csv_motion_join": "The logged prediction sequence is not mapped to a CSV movement instant; these logs do not expose a reliable input sequence join.",
            "geometry_rule": "Unity telemetry directional_edge_distance minus ball_radius; rows are ordered by file position within Unity source.",
            "timestamp_gap_rule": "Flag adjacent Unity geometry_source_timestamp jumps > 0.100 s; geometry version changes are reported separately.",
        },
        "editor_log": log,
        "sessions": sessions,
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
