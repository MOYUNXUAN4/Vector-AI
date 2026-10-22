#!/usr/bin/env python3
"""cluster_warning_episodes_v3.py

Collapses telemetry warning rows into discrete, traceable warning episodes.

Key improvements in v3 (resolving defects from independent review 2026-10-20):
  * Completed sessions (outcome='calibration_completed') are INCLUDED by default.
    In this project, calibration_completed is the standard outcome of a successfully
    completed 3-layer run, not a pre-game calibration-only phase.
  * Explicit CLEAR handling: an intervening row with warning_active=false splits
    episodes. Explicit clears are never bridged across.
  * Metadata boundary awareness: transitions across run_id, platform_level, or
    layer boundaries split episodes. Episodes derive their run_id from their own
    constituent rows, not from the last row of the file.
  * Completeness in export: when --out is specified, all episodes (including short
    episodes below --min-duration) are preserved in the export with an explicit
    `is_short_episode` boolean column.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class Episode:
    session: str
    run_id: str
    platform_level: str
    episode_index: int
    start_source_ts: float
    end_source_ts: float
    duration_s: float
    packet_count: int
    warning_type: str
    session_outcome: str
    fall_event_ts: Optional[float]
    lead_time_to_fall_s: Optional[float]
    fall_during_episode: Optional[bool]
    seconds_episode_end_to_fall: Optional[float]
    is_short_episode: bool = False


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def is_warning_row(r: dict) -> bool:
    return (
        _truthy(r.get("warning_active"))
        or _truthy(r.get("edge_warning_state"))
        or (str(r.get("prediction_state") or "").strip().upper() in ("WARNING", "EDGE WARNING", "DANGER"))
    )


def load_unity_rows(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("source") == "unity"]


def group_runs(rows: List[dict], gap_tolerance_s: float = 0.5) -> List[List[dict]]:
    """Groups consecutive warning rows into episodes.
    
    Splits when:
      1. A non-warning row occurs (explicit CLEAR).
      2. Gap between consecutive warning timestamps > gap_tolerance_s.
      3. run_id changes.
      4. platform_level changes.
    """
    runs: List[List[dict]] = []
    cur: List[dict] = []
    prev_ts: Optional[float] = None
    prev_run_id: Optional[str] = None
    prev_platform: Optional[str] = None

    for r in rows:
        if not is_warning_row(r):
            if cur:
                runs.append(cur)
                cur = []
                prev_ts = None
                prev_run_id = None
                prev_platform = None
            continue

        ts = _f(r.get("source_timestamp"))
        if ts is None:
            continue

        run_id = str(r.get("run_id") or "").strip()
        platform = str(r.get("platform_level") or r.get("layer") or "").strip()

        # Check split conditions
        time_split = (prev_ts is not None and (ts - prev_ts) > gap_tolerance_s)
        run_split = (prev_run_id is not None and run_id != prev_run_id)
        platform_split = (prev_platform is not None and platform != prev_platform)

        if cur and (time_split or run_split or platform_split):
            runs.append(cur)
            cur = []

        cur.append(r)
        prev_ts = ts
        prev_run_id = run_id
        prev_platform = platform

    if cur:
        runs.append(cur)

    return runs


def episodes_for_session(
    path: str,
    gap_tolerance_s: float = 0.5,
    min_duration_s: float = 0.0,
    fall_window: Optional[float] = None
) -> Tuple[List[Episode], List[Episode]]:
    rows = load_unity_rows(path)
    if not rows:
        return [], []

    session_name = os.path.basename(os.path.dirname(os.path.abspath(path)))
    global_outcome = next((r.get("session_outcome") for r in reversed(rows) if r.get("session_outcome")), "")
    fall_ts = next((_f(r.get("source_timestamp")) for r in rows if _truthy(r.get("fall_event"))), None)

    runs = group_runs(rows, gap_tolerance_s)
    kept: List[Episode] = []
    short: List[Episode] = []

    for i, run in enumerate(runs):
        t0 = _f(run[0].get("source_timestamp"))
        t1 = _f(run[-1].get("source_timestamp"))
        if t0 is None or t1 is None:
            continue

        dur = round(max(0.0, t1 - t0), 3)
        lead = round(fall_ts - t0, 3) if (fall_ts is not None and fall_ts >= t0) else None
        run_id = run[0].get("run_id") or run[-1].get("run_id") or ""
        platform = str(run[0].get("platform_level") or run[0].get("layer") or "").strip()
        warning_type = (
            run[0].get("warning_type")
            or run[0].get("warning_source")
            or run[0].get("prediction_state")
            or ""
        ).strip()

        is_short = (dur < min_duration_s)
        ep = Episode(
            session=session_name,
            run_id=run_id,
            platform_level=platform,
            episode_index=i,
            start_source_ts=t0,
            end_source_ts=t1,
            duration_s=dur,
            packet_count=len(run),
            warning_type=warning_type,
            session_outcome=global_outcome,
            fall_event_ts=fall_ts,
            lead_time_to_fall_s=lead,
            fall_during_episode=(fall_ts <= t1) if fall_ts is not None else None,
            seconds_episode_end_to_fall=(round(fall_ts - t1, 3) if fall_ts is not None and fall_ts >= t1 else None),
            is_short_episode=is_short,
        )

        if is_short:
            short.append(ep)
        else:
            kept.append(ep)

    return kept, short


def main() -> int:
    ap = argparse.ArgumentParser(description="Cluster packet-level warnings into episodes (v3).")
    ap.add_argument("--csv", required=True, nargs="+", help="raw.csv path(s) or session dir(s)")
    ap.add_argument("--out", default=None, help="write all episodes (including short) to CSV")
    ap.add_argument("--gap-tolerance", type=float, default=0.5,
                    help="seconds of silence that splits episodes (default: 0.5s)")
    ap.add_argument("--min-duration", type=float, default=0.0,
                    help="minimum duration (s) to classify as normal episode vs short episode (default: 0.0)")
    ap.add_argument("--fall-window", type=float, default=None,
                    help="optional lead-time window (s) to evaluate fall_within_window")
    ap.add_argument("--skip-outcomes", nargs="*", default=[],
                    help="optional outcomes to exclude (default: none; calibration_completed is included)")
    args = ap.parse_args()

    paths: List[str] = []
    for p in args.csv:
        if os.path.isdir(p):
            sub = sorted(glob.glob(os.path.join(p, "session_*", "raw.csv")))
            if sub:
                paths.extend(sub)
            else:
                direct = os.path.join(p, "raw.csv")
                if os.path.isfile(direct):
                    paths.append(direct)
        elif os.path.isfile(p):
            paths.append(p)

    if not paths:
        print("No raw.csv found in given paths", file=sys.stderr)
        return 1

    all_kept: List[Episode] = []
    all_short: List[Episode] = []
    skipped_sessions: List[Tuple[str, str]] = []

    for path in paths:
        kept, short = episodes_for_session(path, args.gap_tolerance, args.min_duration, args.fall_window)
        # Check if outcome should be skipped
        outcome = (kept or short)[0].session_outcome if (kept or short) else ""
        if outcome and outcome in args.skip_outcomes:
            skipped_sessions.append((path, outcome))
            continue
        all_kept.extend(kept)
        all_short.extend(short)

    total_episodes = len(all_kept) + len(all_short)
    print(f"=== {len(paths)} session(s) processed: {len(all_kept)} normal episode(s), {len(all_short)} short episode(s) ===")
    if skipped_sessions:
        print(f"Skipped {len(skipped_sessions)} session(s) matching --skip-outcomes:")
        for s_path, s_out in skipped_sessions:
            print(f"  - {os.path.basename(os.path.dirname(s_path))}: outcome={s_out}")

    header = "%-30s %3s %7s %5s %9s  %-22s %s"
    print(header % ("session", "ep", "dur_s", "pkts", "lead_s", "outcome", "fall"))
    for ep in all_kept:
        sess_disp = ep.session.replace("session_", "")
        lead_disp = "n/a" if ep.lead_time_to_fall_s is None else f"{ep.lead_time_to_fall_s:.2f}"
        fall_disp = "during" if ep.fall_during_episode else ("after" if ep.fall_during_episode is False else "none")
        print(header % (sess_disp, ep.episode_index, f"{ep.duration_s:.3f}", ep.packet_count,
                        lead_disp, ep.session_outcome or "-", fall_disp))

    if all_short:
        print(f"\n[INFO] {len(all_short)} short episode(s) with duration < {args.min_duration:.3f}s:")
        for ep in all_short[:20]:
            print(f"   {ep.session} ep{ep.episode_index} dur={ep.duration_s:.3f}s packets={ep.packet_count}")
        if len(all_short) > 20:
            print(f"   ... and {len(all_short) - 20} more")

    if args.out:
        all_to_export = all_kept + all_short
        all_to_export.sort(key=lambda e: (e.session, e.episode_index))
        fields = list(asdict(all_to_export[0]).keys()) if all_to_export else [f for f in Episode.__dataclass_fields__]
        if args.fall_window is not None:
            fields.append("fall_within_window")

        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for ep in all_to_export:
                row = asdict(ep)
                if args.fall_window is not None:
                    row["fall_within_window"] = (
                        "" if ep.lead_time_to_fall_s is None
                        else (ep.lead_time_to_fall_s <= args.fall_window)
                    )
                w.writerow(row)
        print(f"\nExported {len(all_to_export)} total episodes (including short) to: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
