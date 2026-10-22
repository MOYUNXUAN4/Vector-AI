"""Read-only, reproducible inventory of P01 telemetry sessions (stdlib only)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = BACKEND_ROOT / "telemetry_logs" / "P01"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
REPORT_ROOT = BACKEND_ROOT / "parallel_20261019"
REPORTS = {
    "battery_dislodged": str(REPORT_ROOT / "p01_review" / "user_annotations.json"),
    "terminal_mismatch": str(REPORT_ROOT / "p01_new_gap_review" / "REPORT.md"),
    "timing_review": str(REPORT_ROOT / "p01_new_gap_review" / "result_v2.json"),
}
REPORTS = {key: path for key, path in REPORTS.items() if Path(path).is_file()}
RECOMMENDATIONS = {
    "session_20261019_105734_310716": {
        "recommendation": "user_confirmed_equipment_anomaly_review_exclusion",
        "evidence": "battery_dislodged",
        "reason": "User-confirmed battery dislodgement; retain raw evidence; exclude only this run from normal behavior/model performance evaluation pending primary decision.",
    },
    "session_20261019_151034_541581": {
        "recommendation": "terminal_evidence_mismatch_review",
        "evidence": "terminal_mismatch",
        "reason": "Report states final CSV Unity row remains running with no outcome while matching lifecycle evidence reports user_exit; do not infer/repair terminal outcome.",
    },
    "session_20261019_150806_990055": {
        "recommendation": "timing_review_flag",
        "evidence": "timing_review",
        "reason": "Report records Unity source-time continuity gaps >0.1 s; timing evidence is a technical quality flag, not participant identity or automatic exclusion.",
    },
    "session_20261019_150834_945026": {
        "recommendation": "timing_review_flag",
        "evidence": "timing_review",
        "reason": "Report records multiple Unity source-time gaps >0.4 s; timing evidence is a technical quality flag, not participant identity or automatic exclusion.",
    },
}
# Cohort assignment is supplied by the user for the historical first ten sessions;
# this is explicit provenance, not a guess from the folder name or control flags.
CONFIRMED_PARTICIPANT_SESSIONS = {
    "session_20261019_105632_058608", "session_20261019_105656_285619",
    "session_20261019_105712_007803", "session_20261019_105734_310716",
    "session_20261019_105912_781089", "session_20261019_105922_291656",
    "session_20261019_105951_117357", "session_20261019_110023_567130",
    "session_20261019_110055_533132", "session_20261019_110107_096491",
}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def number(v: Any) -> float | None:
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def value_counts(rows: list[dict[str, str]], column: str) -> dict[str, int] | None:
    if not rows or column not in rows[0]:
        return None
    return dict(sorted(Counter((r.get(column, "") or "<empty>").strip() for r in rows).items()))

def source_counts(path: Path) -> dict[str, int] | None:
    if not path.is_file():
        return None
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {}
        return dict(sorted(Counter((r.get("source", "") or "<empty>").strip() for r in reader).items()))

def inspect_session(folder: Path) -> dict[str, Any]:
    raw = folder / "raw.csv"
    entry: dict[str, Any] = {"session": folder.name, "directory": str(folder), "raw_path": str(raw),
                             "files": [], "raw_present": raw.is_file(), "raw_rows": None,
                             "cohort_evidence": "user_confirmed_participant" if folder.name in CONFIRMED_PARTICIPANT_SESSIONS else "unknown"}
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    for p in files:
        entry["files"].append({"path": str(p), "sha256_before": sha256(p), "sha256_after": None})
    if not raw.is_file():
        entry.update({"status": "missing_raw", "source_counts": None, "run_ids": [], "run_state_counts": None,
                      "session_outcome_counts": None, "sequence": None, "unity_source": None,
                      "distributions_by_source": {}, "columns_present": [], "recommendation": RECOMMENDATIONS.get(folder.name)})
        return entry
    with raw.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)
    entry["raw_rows"] = len(rows)
    entry["columns_present"] = columns
    entry["status"] = "empty_table" if not rows else "ok"
    entry["source_counts"] = dict(sorted(Counter((r.get("source", "") or "<empty>").strip() for r in rows).items())) if rows else {}
    run_ids = sorted({(r.get("run_id", "") or "").strip() for r in rows if (r.get("run_id", "") or "").strip()})
    entry["run_ids"] = run_ids
    entry["run_attribution"] = "unknown_multirun" if len(run_ids) > 1 else ("single_run" if len(run_ids) == 1 else "unknown_no_run_id")
    entry["run_state_counts"] = value_counts(rows, "run_state")
    entry["session_outcome_counts"] = value_counts(rows, "session_outcome")
    entry["terminal_row"] = {k: rows[-1].get(k) for k in ("source", "source_timestamp", "sequence", "run_id", "run_state", "session_outcome", "session_end_backend_timestamp")} if rows else None
    entry["sequence"] = {}
    by_source: dict[str, list[int]] = defaultdict(list)
    if "sequence" in columns:
        for r in rows:
            src = (r.get("source", "") or "<empty>").strip()
            seq = number(r.get("sequence"))
            if seq is not None and seq.is_integer(): by_source[src].append(int(seq))
        for src, seqs in by_source.items():
            uniq = sorted(set(seqs)); missing = []; resets = []; jumps = []
            for a, b in zip(seqs, seqs[1:]):
                if b <= a: resets.append({"previous": a, "current": b})
                elif b > a + 1: jumps.append({"previous": a, "current": b, "missing_start": a + 1, "missing_end": b - 1})
            entry["sequence"][src] = {"start": seqs[0] if seqs else None, "end": seqs[-1] if seqs else None,
                                      "unique_start": uniq[0] if uniq else None, "unique_end": uniq[-1] if uniq else None,
                                      "count": len(seqs), "unique_count": len(uniq), "missing_ranges": jumps,
                                      "reset_or_backstep_count": len(resets), "reset_or_backstep_transitions": resets}
    unity = [r for r in rows if (r.get("source", "") or "").strip().lower() == "unity"]
    entry["unity_terminal_row"] = {k: unity[-1].get(k) for k in ("source_timestamp", "sequence", "run_id", "run_state", "session_outcome", "session_end_backend_timestamp")} if unity else None
    ts = [number(r.get("source_timestamp")) for r in unity]
    valid_ts = [x for x in ts if x is not None]
    gaps = [b-a for a,b in zip(ts, ts[1:]) if a is not None and b is not None]
    positive_gaps = [g for g in gaps if g > 0]
    entry["unity_source"] = {"rows": len(unity), "timestamp_valid_rows": len(valid_ts),
        "missing_timestamp_rows": sum(x is None for x in ts),
        "adjacent_pairs_blocked_by_missing_timestamp": sum(a is None or b is None for a,b in zip(ts, ts[1:])),
        "nonpositive_adjacent_dt_count": sum(g <= 0 for g in gaps),
        "start": valid_ts[0] if valid_ts else None, "end": valid_ts[-1] if valid_ts else None,
        "duration_seconds": valid_ts[-1]-valid_ts[0] if len(valid_ts) > 1 else None,
        "gap_count_gt_0_1s": sum(g > .1 for g in positive_gaps), "gap_count_gt_0_4s": sum(g > .4 for g in positive_gaps),
        "max_gap_seconds": max(positive_gaps) if positive_gaps else None,
        "gap_values_gt_0_1s": [g for g in positive_gaps if g > .1],
        "intervals_with_missing_timestamp": "unknown" if any(x is None for x in ts) else 0}
    fields_by_source = {
        "unity": ("calibration_mode", "selected_session_layers", "selected_difficulty", "difficulty"),
        "wii": ("wii_board_loaded", "wii_center_applied", "wii_control_valid"),
    }
    source_rows = {src: [r for r in rows if (r.get("source", "") or "").strip().lower() == src]
                   for src in sorted({(r.get("source", "") or "").strip().lower() for r in rows})}
    entry["distributions_by_source"] = {
        src: {field: value_counts(src_rows, field) for field in fields_by_source.get(src, ())}
        for src, src_rows in source_rows.items()
    }
    entry["recommendation"] = RECOMMENDATIONS.get(folder.name)
    if entry["recommendation"]:
        report = REPORTS.get(entry["recommendation"]["evidence"])
        if report and Path(report).is_file():
            entry["recommendation"]["source_report"] = report
    return entry

def inventory(source: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    sessions = [inspect_session(p) for p in sorted(source.iterdir()) if p.is_dir() and p.name.startswith("session_")] if source.is_dir() else []
    # Rehash every captured source file after the full scan to prove the scan did not alter inputs.
    for item in sessions:
        for rec in item["files"]:
            p = Path(rec["path"])
            rec["sha256_after"] = sha256(p) if p.is_file() else None
            rec["unchanged"] = rec["sha256_before"] == rec["sha256_after"]
        item["source_files_unchanged"] = all(x["unchanged"] for x in item["files"])
        (output / f"{item['session']}.json").write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
        with (output / f"{item['session']}.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(("evidence_field", "value"))
            for key, value in item.items():
                if key not in {"files", "columns_present"}:
                    w.writerow((key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value))
    summary = {"scope": "Read-only P01 session inventory; no participant identity inferred from directory name or empty-input indicators.",
               "source_root": str(source), "session_count": len(sessions), "sessions": sessions,
               "report_sources": REPORTS,
               "classification_note": "Recommendations reproduce only explicitly documented evidence. They are not final inclusion decisions; no session is automatically included in training/evaluation.",
               "aggregate": {"raw_rows": sum(x.get("raw_rows") or 0 for x in sessions),
                             "missing_raw_sessions": [x["session"] for x in sessions if x["status"] == "missing_raw"],
                             "multi_run_sessions": [x["session"] for x in sessions if x.get("run_attribution") == "unknown_multirun"],
                             "source_files_unchanged": all(x["source_files_unchanged"] for x in sessions)}}
    (output / "inventory.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = ["session", "raw_present", "raw_rows", "run_attribution", "run_ids", "outcome_counts", "unity_duration_seconds", "unity_gaps_gt_0_1s", "unity_gaps_gt_0_4s", "recommendation"]
    with (output / "inventory.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for x in sessions:
            w.writerow({"session":x["session"], "raw_present":x["raw_present"], "raw_rows":x["raw_rows"],
                "run_attribution":x.get("run_attribution"), "run_ids":";".join(x.get("run_ids", [])),
                "outcome_counts":json.dumps(x.get("session_outcome_counts"), ensure_ascii=False),
                "unity_duration_seconds":(x.get("unity_source") or {}).get("duration_seconds"),
                "unity_gaps_gt_0_1s":(x.get("unity_source") or {}).get("gap_count_gt_0_1s"),
                "unity_gaps_gt_0_4s":(x.get("unity_source") or {}).get("gap_count_gt_0_4s"),
                "recommendation":(x.get("recommendation") or {}).get("recommendation", "unreviewed_evidence_only")})
    return summary

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()
    result = inventory(args.source, args.output)
    print(json.dumps(result["aggregate"] | {"session_count":result["session_count"], "output":str(args.output)}, ensure_ascii=False))

if __name__ == "__main__": main()
