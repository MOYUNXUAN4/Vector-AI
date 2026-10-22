#!/usr/bin/env python3
"""Reproducible P03 post-fix client warning episode/burden analysis.

Reads only client_result.json, CONDITION_RECEIPT.json and the exact raw.csv files.
It never loads a model or changes collection/strategy state.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
REVIEW = BACKEND / "parallel_20261020" / "p03_postfix_review_primary"
CHANNELS = {
    "ExperimentalModelWarning": "orange_model",
    "ExperimentalProximityWarning": "purple_tte",
    "ExperimentalGeometryWarning": "red_geometry",
}
STATE_NAMES = {"ACTIVE", "REVOKED"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def num(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _exact_csv_lookup(csv_path: Path, run_id: str, input_sequence: str | None) -> dict[str, Any] | None:
    """Exact run_id + sequence match only; no clock or neighbor inference."""
    if not input_sequence:
        return None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("run_id") == run_id and row.get("sequence", "").strip() == str(input_sequence):
                return {
                    "run_id": run_id,
                    "input_sequence": str(input_sequence),
                    "csv_sequence": row.get("sequence"),
                    "source": row.get("source"),
                    "source_timestamp": row.get("source_timestamp"),
                    "tte_seconds": row.get("time_to_edge_seconds") or row.get("tte_seconds"),
                }
    return None


def _classify_outcome(csv_path: Path, run_id: str) -> str:
    outcomes: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("run_id") == run_id and (row.get("session_outcome") or "").strip():
                outcomes.add(row["session_outcome"].strip())
    return ";".join(sorted(outcomes)) if outcomes else "unknown"


def analyze(client: dict[str, Any], receipt: dict[str, Any], backend: Path) -> dict[str, Any]:
    expected = client.get("source_sha256_before", {})
    after = client.get("source_sha256_after", {})
    if len(client.get("sessions", [])) != 9 or len(receipt.get("session_ids", [])) != 9:
        raise ValueError("Expected exactly nine client-report sessions and receipt sessions")
    if not client.get("sources_unchanged") or expected != after:
        raise ValueError("Input report does not attest unchanged sources")
    verified: dict[str, str] = {}
    for path_text, expected_hash in expected.items():
        p = Path(path_text)
        if not p.is_file():
            # Paths in the report may have been recorded on another machine; CSV fallback resolves by exact session below.
            continue
        actual = sha256(p)
        if actual != expected_hash:
            raise ValueError(f"Source hash mismatch: {p}")
        verified[str(p)] = actual

    records_by_run: dict[str, list[dict[str, Any]]] = {}
    for rec in client.get("state_records", []):
        records_by_run.setdefault(rec["run_id"], []).append(rec)

    run_reports: list[dict[str, Any]] = []
    aggregate = {channel: {"episodes": 0, "closed_duration_s": 0.0, "closed_duration_count": 0,
                            "unknown_duration_episodes": 0, "active_records": 0, "revoked_records": 0,
                            "mismatched_transitions": 0, "negative_durations": 0}
                 for channel in CHANNELS}
    for sess in client["sessions"]:
        sid, run_id = sess["session_id"], sess["run_id"]
        csv_path = backend / "telemetry_logs" / "P03" / sid / "raw.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(csv_path)
        actual_csv_hash = sha256(csv_path)
        # Validate the corresponding receipt/report digest where available.
        report_hash = next((v for k, v in expected.items() if k.replace("\\", "/").endswith(f"/{sid}/raw.csv")), None)
        if report_hash and actual_csv_hash != report_hash:
            raise ValueError(f"CSV hash mismatch: {csv_path}")
        verified[str(csv_path)] = actual_csv_hash
        events = sorted(records_by_run.get(run_id, []), key=lambda r: int(r.get("line", 0)))
        by_channel: dict[str, list[dict[str, Any]]] = {c: [] for c in CHANNELS}
        for ev in events:
            if ev.get("channel") in by_channel:
                by_channel[ev["channel"]].append(ev)
        channels_out: dict[str, Any] = {}
        for channel, label in CHANNELS.items():
            eps: list[dict[str, Any]] = []
            opened: dict[str, Any] | None = None
            mismatches = negative = active_count = revoked_count = 0
            for ev in by_channel[channel]:
                state = str(ev.get("state", "")).upper()
                if state not in STATE_NAMES:
                    continue
                fields = ev.get("fields") or {}
                mono = num(fields.get("local_monotonic_s"))
                active_count += state == "ACTIVE"
                revoked_count += state == "REVOKED"
                if state == "ACTIVE":
                    if opened is None:
                        opened = {"onset_line": ev.get("line"), "onset_local_monotonic_s": mono,
                                  "onset_input_sequence": fields.get("input_sequence"),
                                  "onset_prediction_sequence": fields.get("prediction_sequence"),
                                  "last_prediction_sequence": fields.get("prediction_sequence"),
                                  "reason": fields.get("reason"), "revoke_reason": fields.get("revoke_reason")}
                    else:
                        # Repeated ACTIVE refreshes one episode; retain most recent model sequence only.
                        if channel == "ExperimentalModelWarning" and fields.get("prediction_sequence") is not None:
                            opened["last_prediction_sequence"] = fields.get("prediction_sequence")
                        opened["last_active_line"] = ev.get("line")
                    continue
                if opened is None:
                    mismatches += 1
                    continue
                end_input = fields.get("input_sequence")
                ended = {**opened, "closed": True, "revoke_line": ev.get("line"),
                         "revoke_local_monotonic_s": mono, "revoke_reason": fields.get("revoke_reason") or fields.get("reason") or opened.get("revoke_reason"),
                         "revoke_input_sequence": end_input}
                start_mono = opened.get("onset_local_monotonic_s")
                duration = None
                if channel == "ExperimentalGeometryWarning" or start_mono is None or mono is None:
                    ended["duration_s"] = None
                    ended["duration_status"] = "unknown_clock"
                else:
                    duration = mono - start_mono
                    if duration < 0:
                        negative += 1
                        ended["duration_s"] = None
                        ended["duration_status"] = "negative_duration"
                    else:
                        ended["duration_s"] = round(duration, 6)
                        ended["duration_status"] = "closed_local_monotonic_interval"
                if channel == "ExperimentalProximityWarning":
                    ended["onset_source_join"] = _exact_csv_lookup(csv_path, run_id, opened.get("onset_input_sequence"))
                eps.append(ended)
                opened = None
            if opened is not None:
                eps.append({**opened, "closed": False, "duration_s": None, "duration_status": "open_censored_unknown"})
            unknown_count = sum(e["duration_s"] is None for e in eps)
            closed_duration = sum(e["duration_s"] or 0 for e in eps)
            channels_out[label] = {
                "episode_count": len(eps), "active_records": int(active_count), "revoked_records": int(revoked_count),
                "closed_duration_s": round(closed_duration, 6),
                "closed_duration_episode_count": sum(e["duration_s"] is not None for e in eps),
                "unknown_duration_episode_count": unknown_count,
                "mismatched_revoke_without_active": mismatches, "negative_duration_count": negative,
                "episodes": eps,
            }
            a = aggregate[channel]
            a["episodes"] += len(eps); a["closed_duration_s"] += closed_duration
            a["closed_duration_count"] += sum(e["duration_s"] is not None for e in eps)
            a["unknown_duration_episodes"] += unknown_count; a["active_records"] += int(active_count)
            a["revoked_records"] += int(revoked_count); a["mismatched_transitions"] += mismatches
            a["negative_durations"] += negative
        outcome = _classify_outcome(csv_path, run_id)
        group = "fallout_3" if "edge_exit" in outcome.split(";") else ("completed_6" if "calibration_completed" in outcome.split(";") else "unknown")
        run_reports.append({"session_id": sid, "run_id": run_id, "outcome": outcome, "group": group,
                            "channels": channels_out})

    for a in aggregate.values():
        a["closed_duration_s"] = round(a["closed_duration_s"], 6)
    groups = {"completed_6": [], "fallout_3": [], "unknown": []}
    for run in run_reports:
        groups[run["group"]].append(run["session_id"])
    return {
        "scope": "P03 post-fix nine-run client accepted/revoked episode and local-monotonic burden analysis",
        "input_receipt": {"fix_version": receipt.get("fix_version"), "session_ids": receipt.get("session_ids")},
        "source_hash_verification": {"report_hashes_checked": len(verified), "hashes": verified,
                                     "input_client_result_hash": sha256(REVIEW / "client_result.json"),
                                     "condition_receipt_hash": sha256(REVIEW / "CONDITION_RECEIPT.json")},
        "group_counts": {k: len(v) for k, v in groups.items()}, "groups": groups,
        "aggregate_by_channel": aggregate,
        "runs": run_reports,
        "interpretation_limits": [
            "Episodes are keyed by exact run and channel; repeated ACTIVE refreshes do not create episodes.",
            "Only paired ACTIVE/REVOKED endpoints in the same client local_monotonic_s clock domain yield duration.",
            "Unclosed episodes remain censored/unknown; no duration is inferred from the next run or event.",
            "Geometry records lack local_monotonic_s, so geometry duration is unknown even when closed.",
            "TTE onset source join uses only exact run_id plus input sequence matching raw.csv sequence; no neighboring clock inference.",
            "Orange/purple burden is time under accepted client state, not pixel display duration, false-positive rate, or intervention effect.",
            "Prediction sequence is retained as a model-event identifier and is never treated as input-source time.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", type=Path, default=BACKEND)
    ap.add_argument("--out", type=Path, default=HERE / "client_burden_report.json")
    args = ap.parse_args()
    client = json.loads((args.backend / "parallel_20261020/p03_postfix_review_primary/client_result.json").read_text(encoding="utf-8"))
    receipt = json.loads((args.backend / "parallel_20261020/p03_postfix_review_primary/CONDITION_RECEIPT.json").read_text(encoding="utf-8"))
    result = analyze(client, receipt, args.backend)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
