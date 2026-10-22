"""Audit Unity-vs-wall-clock alignment per run (v2).

Reports every offset step, data gap and drifting segment, keeps the physical
CSV line and run id, and re-times events without changing clocks.

Usage:
    python tools/clock_offset_audit.py session/raw.csv
    python tools/clock_offset_audit.py raw.csv --json report.json --md report.md
    python tools/clock_offset_audit.py raw.csv --events events.csv --events-out fixed.csv

Read-only: never modifies the input CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clock_alignment import (analyze, group_by_run,  # noqa: E402
                             samples_from_rows)


def read_unity_rows(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig", errors="replace") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            if (row.get("source") or "").strip().lower() != "unity":
                continue
            row["__csv_line__"] = reader.line_num
            rows.append(row)
    return rows


def summarize(path, alignment):
    return {
        "run_id": alignment.run_id,
        "verdict": alignment.verdict,
        "offset_range_seconds": round(alignment.offset_range_seconds, 6),
        "max_segment_drift_seconds": round(alignment.max_segment_drift_seconds, 6),
        "rows_with_geometry": len(alignment.samples),
        "components": alignment.components,
        "first_csv_line": alignment.samples[0].csv_line if alignment.samples else None,
        "last_csv_line": alignment.samples[-1].csv_line if alignment.samples else None,
        "segments": [
            {
                "index": segment.index,
                "first_csv_line": segment.first_csv_line,
                "last_csv_line": segment.last_csv_line,
                "rows": segment.rows,
                "offset_median": round(segment.offset_median, 6),
                "offset_min": round(segment.offset_min, 6),
                "offset_max": round(segment.offset_max, 6),
                "drift_seconds": round(segment.drift_seconds, 6),
                "start_unity": round(segment.start_unity, 6),
                "end_unity": round(segment.end_unity, 6),
                "transient": segment.transient,
                "drifting": segment.drifting,
            }
            for segment in alignment.segments
        ],
        "steps": [
            {
                "after_csv_line": step.after_csv_line,
                "epoch": round(step.epoch, 6),
                "unity": round(step.unity, 6),
                "delta_seconds": round(step.delta_seconds, 6),
            }
            for step in alignment.steps
        ],
        "gaps": [
            {
                "after_csv_line": gap.after_csv_line,
                "start_unity": round(gap.start_unity, 6),
                "end_unity": round(gap.end_unity, 6),
                "start_epoch": round(gap.start_epoch, 6),
                "end_epoch": round(gap.end_epoch, 6),
                "seconds": round(gap.seconds, 6),
            }
            for gap in alignment.gaps
        ],
    }


def render_markdown(reports):
    lines = ["# Unity / wall-clock alignment audit", "",
             "Per run. `offset range` is max-min over all samples; `drift` is "
             "the largest within-segment max-min. A gap is unsupported time "
             "even when the offset is stable.", "",
             "| File | Run | Verdict | Offset range (s) | Drift (s) | Steps | Gaps | Lines |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for report in reports:
        for run in report["runs"]:
            lines.append("| {name} | {run} | {verdict} | {span:.3f} | {drift:.3f} | {steps} | {gaps} | {a}-{b} |".format(
                name=Path(report["path"]).parent.name, run=run["run_id"] or "unknown",
                verdict=run["verdict"], span=run["offset_range_seconds"],
                drift=run["max_segment_drift_seconds"], steps=len(run["steps"]),
                gaps=len(run["gaps"]), a=run["first_csv_line"], b=run["last_csv_line"]))
    for report in reports:
        for run in report["runs"]:
            lines += ["", f"## {Path(report['path']).parent.name} / {run['run_id']}", ""]
            if run["steps"]:
                lines += ["| After CSV line | Unity time (s) | Step (s) |", "| ---: | ---: | ---: |"]
                for step in run["steps"]:
                    lines.append(f"| {step['after_csv_line']} | {step['unity']:.3f} | {step['delta_seconds']:+.3f} |")
            else:
                lines.append("No offset step detected.")
            if run["gaps"]:
                lines += ["", "| Gap after CSV line | Unity range | Seconds |",
                          "| ---: | --- | ---: |"]
                for gap in run["gaps"]:
                    lines.append(f"| {gap['after_csv_line']} | {gap['start_unity']:.3f}..{gap['end_unity']:.3f} | {gap['seconds']:.3f} |")
    return "\n".join(lines) + "\n"


def _uncertain_interval(alignment, unity_time, warmup_seconds):
    """Gap (plus optional warmup) or transient segment covering the moment."""
    for gap in alignment.gaps:
        if gap.start_unity - 1e-9 <= unity_time <= gap.end_unity + warmup_seconds + 1e-9:
            return True
    for segment in alignment.segments:
        if segment.transient and segment.start_unity - 1e-9 <= unity_time <= segment.end_unity + 1e-9:
            return True
    return False


def map_event(alignment, row, warmup_seconds=0.0):
    """Map one event row; returns output fields.

    Epoch inputs keep their epoch value and gain a Unity value; Unity inputs
    keep their Unity value and gain an epoch value.  An optional
    ``unity_end`` switches to interval checking.  ``warmup_seconds`` extends
    each data gap by the backend warmup so events that cannot have a valid
    lead are marked N/A while remaining in the coverage table.
    """
    has_unity = row.get("unity_time") not in (None, "")
    has_epoch = row.get("epoch_time") not in (None, "")
    if has_unity:
        unity = float(row["unity_time"])
        if row.get("unity_end") not in (None, ""):
            interval = alignment.map_interval(unity, float(row["unity_end"]))
            reasons = list(interval.reasons)
            if _uncertain_interval(alignment, unity, warmup_seconds) or _uncertain_interval(
                    alignment, float(row["unity_end"]), warmup_seconds):
                reasons.append("uncertain_interval")
            return {"mapped_epoch": interval.start, "mapped_unity": unity,
                    "segment_index": interval.segment_index,
                    "ambiguous": bool(reasons), "reasons": tuple(dict.fromkeys(reasons))}
        mapping = alignment.to_epoch(unity)
        reasons = list(mapping.reasons)
        if _uncertain_interval(alignment, unity, warmup_seconds):
            reasons.append("uncertain_interval")
        return {"mapped_epoch": mapping.value, "mapped_unity": unity,
                "segment_index": mapping.segment_index,
                "ambiguous": bool(reasons), "reasons": tuple(dict.fromkeys(reasons))}
    if has_epoch:
        epoch = float(row["epoch_time"])
        mapping = alignment.to_unity(epoch)
        return {"mapped_epoch": epoch, "mapped_unity": mapping.value,
                "segment_index": mapping.segment_index,
                "ambiguous": mapping.ambiguous, "reasons": mapping.reasons}
    raise ValueError("event requires unity_time or epoch_time")


def map_events(alignments, events_path, output_path, warmup_seconds=0.0):
    with Path(events_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if "event_id" not in fields:
        raise ValueError("events CSV requires an event_id column")
    by_run = {alignment.run_id: alignment for alignment in alignments}
    default = alignments[0] if len(alignments) == 1 else None
    out_fields = fields + ["mapped_epoch", "mapped_unity", "segment_index",
                           "ambiguous", "reasons", "coverage_status"]
    unavailable = 0
    with Path(output_path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=out_fields)
        writer.writeheader()
        for row in rows:
            # A hand-written row with a trailing comma yields an extra value
            # stored under the None key; ignore that empty overflow only.
            row = {key: value for key, value in row.items() if key is not None}
            run_id = row.get("run_id")
            alignment = by_run.get(run_id) if run_id else default
            if alignment is None:
                raise ValueError("event without run_id and the file has multiple runs: "
                                 + str(row.get("event_id")))
            mapped = map_event(alignment, row, warmup_seconds)
            status = "n_a_ambiguous" if mapped["ambiguous"] else "lead_available"
            if mapped["ambiguous"]:
                unavailable += 1
            writer.writerow({**row,
                             "mapped_epoch": "" if math.isnan(mapped["mapped_epoch"]) else f"{mapped['mapped_epoch']:.6f}",
                             "mapped_unity": "" if math.isnan(mapped["mapped_unity"]) else f"{mapped['mapped_unity']:.6f}",
                             "segment_index": mapped["segment_index"],
                             "ambiguous": str(mapped["ambiguous"]).lower(),
                             "reasons": ",".join(mapped["reasons"]) if mapped["reasons"] else "ok",
                             "coverage_status": status})
    return len(rows), unavailable


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="raw.csv files")
    parser.add_argument("--json")
    parser.add_argument("--md")
    parser.add_argument("--events")
    parser.add_argument("--events-out")
    parser.add_argument("--run-id")
    parser.add_argument("--max-gap", type=float, default=0.1)
    parser.add_argument("--jump", type=float, default=0.05)
    parser.add_argument("--drift", type=float, default=0.02)
    parser.add_argument("--min-rows", type=int, default=5)
    parser.add_argument("--warmup-seconds", type=float, default=0.0,
                        help="extend each data gap by the backend warmup when "
                             "marking events N/A (e.g. 0.5)")
    args = parser.parse_args(argv)
    if bool(args.events) != bool(args.events_out):
        parser.error("--events and --events-out must be used together")

    reports, alignments = [], []
    for path in args.csv:
        groups = group_by_run(samples_from_rows(read_unity_rows(path)))
        if args.run_id:
            groups = {key: value for key, value in groups.items() if key == args.run_id}
            if not groups:
                parser.error("requested run id not found in " + path)
        runs = []
        for run_id, samples in groups.items():
            alignment = analyze(samples, run_id=run_id, max_gap=args.max_gap,
                                jump=args.jump, drift=args.drift,
                                min_rows=args.min_rows)
            alignments.append(alignment)
            runs.append(summarize(path, alignment))
        reports.append({"path": str(Path(path).resolve()), "runs": runs})

    if args.events:
        if len(alignments) != 1:
            parser.error("--events requires exactly one run; use --run-id")
        count, unavailable = map_events(alignments, args.events, args.events_out,
                                        warmup_seconds=args.warmup_seconds)
        print(f"mapped {count} events -> {args.events_out} "
              f"({unavailable} N/A, retained in coverage)")

    payload = {"generated_at_epoch": round(time.time(), 3), "files": reports}
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(render_markdown(reports), encoding="utf-8")

    for report in reports:
        for run in report["runs"]:
            print("{name} [{run}]: {verdict}  range={span:.3f}s drift={drift:.3f}s "
                  "rows={rows} steps={steps} gaps={gaps}".format(
                      name=Path(report["path"]).parent.name, run=run["run_id"],
                      verdict=run["verdict"], span=run["offset_range_seconds"],
                      drift=run["max_segment_drift_seconds"], rows=run["rows_with_geometry"],
                      steps=len(run["steps"]), gaps=len(run["gaps"])))
            for step in run["steps"]:
                print(f"  step after CSV line {step['after_csv_line']}: "
                      f"{step['delta_seconds']:+.3f}s at unity {step['unity']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
