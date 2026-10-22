"""Offline, source-only replay for seven handoff cases.

No client lease, rendering, TTE state, or geometry receiver state is reconstructed.
Run from any directory: python replay.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


HERE = Path(__file__).resolve().parent
PARALLEL = HERE.parent
CASES_DIR = PARALLEL / "seven_handoff_cases_primary"
TELEMETRY = PARALLEL.parent / "telemetry_logs" / "INPUT055_CHECK"
TTE_TRACE = PARALLEL / "dev_withdrawal_primary" / "tte_trace.csv"
INPUT_NAMES = ("raw_timelines.csv", "orange_decision_timelines.csv", "seven_cases.csv", "summary.json", "REPORT.md")
UNKNOWN = "unknown"


def read_csv(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None or value.strip() == "":
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def physical_line_rows(path: Path, wanted_lines: Iterable[int]) -> Dict[int, dict]:
    """Return CSV records keyed by physical one-based file line (header is line 1)."""
    wanted = set(wanted_lines)
    found: Dict[int, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            line = reader.line_num
            if line in wanted:
                found[line] = row
            if len(found) == len(wanted):
                break
    return found


def unique_index(rows: Iterable[dict], key_fn, label: str) -> Dict[tuple, dict]:
    index = {}
    for row in rows:
        key = key_fn(row)
        if key in index:
            raise ValueError(f"duplicate {label} key: {key}")
        index[key] = row
    return index


def identity_mismatches(observed: dict, expected: dict, pairs: Iterable[Tuple[str, str]]) -> List[str]:
    mismatches = []
    for left, right in pairs:
        actual, wanted = observed.get(left, "") or "", expected.get(right, "") or ""
        if left == "timestamp":
            try:
                matches = math.isfinite(float(actual)) and math.isfinite(float(wanted)) and abs(float(actual) - float(wanted)) <= 1e-5
            except (TypeError, ValueError):
                matches = False
        else:
            matches = str(actual) == str(wanted)
        if not matches:
            mismatches.append(f"{left}!={right}")
    return mismatches


def local_projection(raw_local: Optional[bool], run_state: Optional[str]) -> str:
    """A conditional source projection; player binding/enabled state remains unknown."""
    running = run_state.strip().lower() == "running" if run_state and run_state.strip() else None
    if raw_local is True and running is True:
        return "EDGE WARNING candidate: local source field true; client/player binding unknown"
    if raw_local is False or running is False:
        return "no local source projection supported by observed fields"
    return "unknown: missing local source or run context"


def build(output_dir: Path = HERE) -> dict:
    before: Dict[str, str] = {}
    input_paths = {name: CASES_DIR / name for name in INPUT_NAMES}
    cases = read_csv(input_paths["seven_cases.csv"])
    raw_rows = read_csv(input_paths["raw_timelines.csv"])
    decisions = read_csv(input_paths["orange_decision_timelines.csv"])
    tte_rows = read_csv(TTE_TRACE)
    prior_summary = json.loads(input_paths["summary.json"].read_text(encoding="utf-8"))

    raw_paths = {case["case_id"]: TELEMETRY / case["session_id"] / "raw.csv" for case in cases}
    all_paths = dict(input_paths)
    all_paths.update({f"telemetry_{case_id}": path for case_id, path in raw_paths.items()})
    all_paths["tte_trace"] = TTE_TRACE
    before = {name: sha256(path) for name, path in all_paths.items()}
    declared_raw_hashes = prior_summary.get("source_sha_before", {})
    for case_id, path in raw_paths.items():
        declared = next((value for name, value in declared_raw_hashes.items()
                        if Path(name).resolve() == path.resolve()), None)
        if declared is None:
            raise ValueError(f"prior summary has no source_sha_before entry for {path}")
        if declared != before[f"telemetry_{case_id}"]:
            raise ValueError(f"raw input SHA does not match prior summary for case {case_id}")

    lines_by_case: Dict[str, List[int]] = {}
    for row in raw_rows:
        lines_by_case.setdefault(row["case_id"], []).append(int(row["physical_csv_line"]))
    original_by_case: Dict[str, Dict[int, dict]] = {
        case_id: physical_line_rows(raw_paths[case_id], lines)
        for case_id, lines in lines_by_case.items()
    }

    decisions_by_key = unique_index(decisions, lambda row: (row["case_id"], row["source_sequence"]), "orange case+sequence")
    tte_by_run_sequence: Dict[Tuple[str, str], List[dict]] = {}
    for row in tte_rows:
        tte_by_run_sequence.setdefault((row.get("run_id", ""), row.get("source_sequence", "")), []).append(row)
    evidence: List[dict] = []
    case_stats: Dict[str, dict] = {}
    for case in cases:
        cid = case["case_id"]
        local_values: List[Optional[bool]] = []
        aggregate_mismatches = []
        decision_exact_count = 0
        decision_true_local_count = 0
        orange_confirmed_obs = 0
        orange_active_obs = 0
        exact_tte_matches = 0
        tte_available_false = 0
        tte_active_false = 0
        tte_identity_mismatches = 0
        tte_decision_matches = 0
        tte_decision_available_false = 0
        tte_decision_active_false = 0
        for timeline in (r for r in raw_rows if r["case_id"] == cid):
            line = int(timeline["physical_csv_line"])
            original = original_by_case[cid].get(line)
            if original is None:
                raise ValueError(f"physical line {line} not found in original raw for {cid}")
            mismatches = identity_mismatches(original, timeline, (
                ("sequence", "sequence"), ("run_id", "run_id"),
                ("layer_id", "layer"), ("geometry_active_platform_instance_id", "platform"),
                ("geometry_active_version_id", "version")))
            if original.get("source") != "unity" or mismatches:
                raise ValueError(f"original raw identity mismatch at {cid} line {line}: {mismatches}; source={original.get('source')}")
            local = parse_bool(original.get("edge_warning_state")) if original else None
            run_state = original.get("run_state", "") if original else ""
            aggregate = parse_bool(timeline.get("native_warning_active"))
            if local is not None:
                local_values.append(local)
            if local != aggregate:
                aggregate_mismatches.append({"physical_csv_line": line, "sequence": timeline["sequence"],
                                             "edge_warning_state": local, "native_warning_active": aggregate})
            dec = decisions_by_key.get((cid, timeline["sequence"]))
            if dec:
                dec_mismatches = identity_mismatches(dec, timeline, (
                    ("session_id", "session_id"), ("run_id", "run_id"),
                    ("source_sequence", "sequence"), ("layer", "layer"),
                    ("platform_id", "platform"), ("geometry_version_id", "version"),
                    ("timestamp", "source_timestamp")))
                if int(dec.get("csv_row", "-1")) != line:
                    dec_mismatches.append("csv_row!=physical_csv_line")
                if dec_mismatches:
                    raise ValueError(f"orange decision identity mismatch at {cid} line {line}: {dec_mismatches}")
            tte_candidates = tte_by_run_sequence.get((timeline.get("run_id", ""), timeline["sequence"]), [])
            tte = tte_candidates[0] if len(tte_candidates) == 1 else None
            if tte:
                exact_tte_matches += 1
                tte_available_false += parse_bool(tte.get("available")) is False
                tte_active_false += parse_bool(tte.get("active")) is False
                tte_identity_mismatches += bool(identity_mismatches(tte, timeline, (
                    ("session_id", "session_id"), ("run_id", "run_id"), ("source_sequence", "sequence"),
                    ("layer", "layer"), ("platform_id", "platform"), ("geometry_version_id", "version"),
                    ("timestamp", "source_timestamp"))))
            if dec:
                decision_exact_count += 1
                if tte:
                    tte_decision_matches += 1
                    tte_decision_available_false += parse_bool(tte.get("available")) is False
                    tte_decision_active_false += parse_bool(tte.get("active")) is False
                if local is True:
                    decision_true_local_count += 1
                if dec.get("policy_reason") == "confirmed":
                    orange_confirmed_obs += 1
                if parse_bool(dec.get("active")) is True:
                    orange_active_obs += 1
            running = run_state.strip().lower() == "running" if run_state and run_state.strip() else None
            yellow_possible = local is True and running is True
            projection = local_projection(local, run_state)
            if dec:
                projection += "; exact orange decision observation=" + dec.get("policy_reason", UNKNOWN)
                projection += " (decision snapshot only; no carry-forward)"
            evidence.append({
                "case_id": cid, "session_id": timeline["session_id"], "physical_csv_line": line,
                "sequence": timeline["sequence"], "source_timestamp": timeline["source_timestamp"],
                "raw_edge_warning_state": "" if local is None else str(local).lower(),
                "raw_run_state": run_state,
                "aggregate_native_warning_active": "" if aggregate is None else str(aggregate).lower(),
                "aggregate_visible_warning_state": timeline.get("native_visible_warning_state", ""),
                "aggregate_vs_local_field_match": "" if local is None or aggregate is None else str(local == aggregate).lower(),
                "orange_exact_decision_observation": dec.get("policy_reason", "") if dec else "",
                "orange_decision_active_snapshot": (dec.get("active", "") if dec else ""),
                "orange_decision_confirmed_snapshot": (str(dec.get("policy_reason") == "confirmed").lower() if dec else ""),
                "tte_exact_run_sequence_match_count": len(tte_candidates),
                "tte_timestamp": tte.get("timestamp", "") if tte else "",
                "tte_available_source_snapshot": tte.get("available", "") if tte else "",
                "tte_active_source_snapshot": tte.get("active", "") if tte else "",
                "tte_policy_reason_source_snapshot": tte.get("policy_reason", "") if tte else "",
                "tte_platform_id": tte.get("platform_id", "") if tte else "",
                "tte_geometry_version_id": tte.get("geometry_version_id", "") if tte else "",
                "tte_clearance_source_value": tte.get("clearance", "") if tte else "",
                "yellow_source_projection_candidate": str(yellow_possible).lower() if local is not None and running is not None else UNKNOWN,
                "geometry_red_receiver_active": UNKNOWN,
                "tte_receiver_active": UNKNOWN,
                "client_local_active_and_rendered": UNKNOWN,
                "source_supported_projection": projection,
                "client_timing_lease_rendering": UNKNOWN,
            })

        counts = Counter(v for v in local_values if v is not None)
        case_decisions = [d for d in decisions if d["case_id"] == cid]
        decision_confirmed = sum(d.get("policy_reason") == "confirmed" for d in case_decisions)
        case_stats[cid] = {
            "session_id": case["session_id"], "run_id": case["run_id"],
            "timeline_source_packets": sum(r["case_id"] == cid for r in raw_rows),
            "exact_original_raw_rows_found": sum(line in original_by_case[cid] for line in lines_by_case[cid]),
            "raw_edge_warning_state_true": counts[True], "raw_edge_warning_state_false": counts[False],
            "raw_edge_warning_state_missing_or_unparseable": len(lines_by_case[cid]) - sum(counts.values()),
            "aggregate_warning_active_vs_exact_local_mismatches": aggregate_mismatches,
            "local_true_run_contiguous_segments": segment_count([
                parse_bool(original_by_case[cid].get(int(r["physical_csv_line"]), {}).get("edge_warning_state")) is True
                for r in raw_rows if r["case_id"] == cid
            ]),
            "orange_decisions": len(case_decisions), "orange_confirmed_decisions": decision_confirmed,
            "orange_active_decisions": sum(parse_bool(d.get("active")) is True for d in case_decisions),
            "exact_sequence_overlaps_with_source_packets": decision_exact_count,
            "overlap_decisions_with_local_edge_warning_state_true": decision_true_local_count,
            "tte_exact_run_sequence_matches": exact_tte_matches,
            "tte_source_available_false_count": tte_available_false,
            "tte_source_active_false_count": tte_active_false,
            "tte_identity_mismatches_vs_packet": tte_identity_mismatches,
            "tte_exact_orange_decision_matches": tte_decision_matches,
            "tte_orange_decision_available_false_count": tte_decision_available_false,
            "tte_orange_decision_active_false_count": tte_decision_active_false,
            "orange_carry_forward_used": False,
            "red_geometry_receiver_state": UNKNOWN, "tte_receiver_state": UNKNOWN,
            "client_actual_ui_and_rendering": UNKNOWN,
            "source_only_projection_summary": "For each packet with raw edge_warning_state=true and run_state=running, local CURRENT EDGE STATE may be a candidate if the current player is the bound/enabled player; actual client state/rendering is unverified. Orange is reported only at exact saved decision observations. No red/TTE/client lease inferred.",
        }

    after = {name: sha256(path) for name, path in all_paths.items()}
    hashes = {"inputs_before_sha256": before, "inputs_after_sha256": after,
              "all_inputs_unchanged": before == after}
    summary = {
        "classification": "offline source-only replay; not real UI/client integration",
        "cases": case_stats, "case_count": len(case_stats), "raw_source_packet_count": len(evidence),
        "orange_decision_count": len(decisions),
        "exact_local_true_packets": sum(parse_bool(e["raw_edge_warning_state"]) is True for e in evidence),
        "exact_local_false_packets": sum(parse_bool(e["raw_edge_warning_state"]) is False for e in evidence),
        "aggregate_warning_active_local_field_mismatches": sum(len(s["aggregate_warning_active_vs_exact_local_mismatches"]) for s in case_stats.values()),
        "orange_decision_count_with_local_true": sum(s["overlap_decisions_with_local_edge_warning_state_true"] for s in case_stats.values()),
        "tte_exact_run_sequence_match_count": sum(s["tte_exact_run_sequence_matches"] for s in case_stats.values()),
        "tte_source_available_false_count": sum(s["tte_source_available_false_count"] for s in case_stats.values()),
        "tte_source_active_false_count": sum(s["tte_source_active_false_count"] for s in case_stats.values()),
        "tte_identity_mismatch_count": sum(s["tte_identity_mismatches_vs_packet"] for s in case_stats.values()),
        "tte_exact_orange_decision_match_count": sum(s["tte_exact_orange_decision_matches"] for s in case_stats.values()),
        "tte_orange_decision_available_false_count": sum(s["tte_orange_decision_available_false_count"] for s in case_stats.values()),
        "tte_orange_decision_active_false_count": sum(s["tte_orange_decision_active_false_count"] for s in case_stats.values()),
        "orange_decision_confirmation_count": sum(s["orange_confirmed_decisions"] for s in case_stats.values()),
        "forbidden_inferences": ["orange decision carry-forward as lease", "red active from c<=0", "TTE active from numeric q/c", "rendered client UI", "missing values to false/zero"],
        "hashes": hashes,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "source_packet_evidence.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(evidence[0].keys()))
        writer.writeheader(); writer.writerows(evidence)
    (output_dir / "case_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "input_hashes.json").write_text(json.dumps(hashes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "REPLAY_REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def segment_count(values: List[bool]) -> int:
    return sum(value and (index == 0 or not values[index - 1]) for index, value in enumerate(values))


def render_report(summary: dict) -> str:
    lines = ["# Unified UI source-only replay", "", "This is offline source evidence only; it is not real UI/client integration or a render validation.",
             "The UIManager reads the current run's bound, enabled player's `EdgeWarningState` for local yellow, gates all sources by running presentation context, and uses receiver getters for orange/model, TTE/proximity, and red/geometry.",
             "The historical raw CSV `edge_warning_state` is the closest direct local field in scope; it does not prove current player binding, enabled state, receiver state, draw invocation, or pixels on screen.", "",
             f"Packets: {summary['raw_source_packet_count']}; exact local true: {summary['exact_local_true_packets']}; false: {summary['exact_local_false_packets']}; aggregate/local mismatches: {summary['aggregate_warning_active_local_field_mismatches']}.",
             f"Orange decisions: {summary['orange_decision_count']}; confirmed: {summary['orange_decision_confirmation_count']}; decision rows whose exact source packet has local true: {summary['orange_decision_count_with_local_true']}.", "",
             f"TTE exact run+sequence packet matches: {summary['tte_exact_run_sequence_match_count']}; orange-decision matches: {summary['tte_exact_orange_decision_match_count']}; at those decision rows available=false: {summary['tte_orange_decision_available_false_count']}, active=false: {summary['tte_orange_decision_active_false_count']}; packet identity mismatches: {summary['tte_identity_mismatch_count']}. These are historical source rows, not proof of the Unity receiver getter state.", "",
             "| Case | Packets | Exact local true/false | Aggregate/local mismatches | Orange decisions (confirmed) | Local true contiguous segments |", "|---|---:|---:|---:|---:|---:|"]
    for cid, case in summary["cases"].items():
        lines.append(f"| {cid} | {case['timeline_source_packets']} | {case['raw_edge_warning_state_true']}/{case['raw_edge_warning_state_false']} | {len(case['aggregate_warning_active_vs_exact_local_mismatches'])} | {case['orange_decisions']} ({case['orange_confirmed_decisions']}) | {case['local_true_run_contiguous_segments']} |")
    lines += ["", "Every orange result is a decision-time snapshot; no state is carried between rows and no client warning lease is inferred. `c<=0` does not activate the red source. Geometry receiver active, TTE receiver active, and actual client render are unknown for all historical packets. Missing source fields remain blank/unknown.",
              "", f"Input hashes unchanged before/after replay: {summary['hashes']['all_inputs_unchanged']}.", ""]
    for cid, case in summary["cases"].items():
        if case["aggregate_warning_active_vs_exact_local_mismatches"]:
            rows = ", ".join(f"line {m['physical_csv_line']} seq {m['sequence']} (exact edge_warning_state={m['edge_warning_state']}, aggregate warning_active={m['native_warning_active']})" for m in case["aggregate_warning_active_vs_exact_local_mismatches"])
            lines.append(f"{cid} field discrepancies: {rows}.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    result = build()
    print(json.dumps({"cases": result["case_count"], "packets": result["raw_source_packet_count"],
                      "orange_decisions": result["orange_decision_count"],
                      "input_hashes_unchanged": result["hashes"]["all_inputs_unchanged"]}, ensure_ascii=False))
