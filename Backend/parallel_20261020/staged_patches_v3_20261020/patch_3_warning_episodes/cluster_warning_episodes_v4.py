#!/usr/bin/env python3
"""cluster_warning_episodes_v4.py  (supersedes cluster_warning_episodes_v3.py)

v3 defects found by inspection and by running it on P02:
  * episodes were keyed only on time gap / run_id / platform_level. `warning_source`
    and `warning_type` were ignored, so an attention-rule alarm and an edge-geometry
    alarm that touch in time collapse into one episode. It happens not to occur in
    the four P02 sessions (warning_active is a single global flag there), but the
    grouping rule is wrong and would merge the moment two channels overlap.
  * no split on source-sequence discontinuity, so a dropped block of packets inside
    a warning is treated as one continuous alarm.
  * `episode_index` was a per-file counter, so it could not identify an episode
    within a channel.

v4 keeps every v3 fix (completed sessions included, explicit CLEAR splits, short
episodes exported) and adds:
  * channel-aware episodes: an episode belongs to exactly one warning_source;
  * sequence-discontinuity split (default: > 3 missing packets);
  * per-(session, channel) episode indices;
  * the on-board `warning_episode_id` values are recorded for cross-check only.
    They are NOT used as the episode key: in session_20261020_102222 that field
    stays 0 across dozens of attention on/off transitions and is shared between
    ATTENTION and STRONG rows, so it is not a per-channel episode identity.

This remains a DESCRIPTIVE gap-cluster. It is not an alarm-burden metric and not
a substitute for the client-state acceptance log.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

WARNING_STATES = {"ATTENTION", "EDGE WARNING", "WARNING", "DANGER", "STRONG"}


@dataclass
class Episode:
    session: str
    run_id: str
    channel: str
    warning_type: str
    platform_level: str
    layer_id: str
    episode_index: int
    start_source_ts: float
    end_source_ts: float
    duration_s: float
    packet_count: int
    sequence_first: Optional[int]
    sequence_last: Optional[int]
    sequence_gaps: int
    unity_episode_ids: str
    session_outcome: str
    fall_event_ts: Optional[float]
    lead_time_to_fall_s: Optional[float]
    fall_during_episode: Optional[bool]
    seconds_episode_end_to_fall: Optional[float]
    is_short_episode: bool


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _i(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def load_unity_rows(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("source") == "unity"]


def channel_of(r: dict) -> str:
    src = (r.get("warning_source") or "").strip()
    if src:
        return src
    if _truthy(r.get("edge_warning_state")):
        return "edge_warning_state"
    state = (r.get("prediction_state") or r.get("visible_warning_state") or "").strip().upper()
    if state in WARNING_STATES:
        return "state:" + state
    return ""


def is_active(r: dict) -> bool:
    if _truthy(r.get("warning_active")) or _truthy(r.get("edge_warning_state")):
        return True
    state = (r.get("prediction_state") or "").strip().upper()
    return state in WARNING_STATES


def group_episodes(rows: List[dict], gap_tolerance_s: float = 0.5,
                   seq_tolerance: int = 3) -> List[List[dict]]:
    """Split on: inactive row (explicit CLEAR), channel change, run_id change,
    platform/layer change, source-time gap, source-sequence discontinuity."""
    episodes: List[List[dict]] = []
    cur: List[dict] = []
    meta: Dict[str, Any] = {}

    def close():
        nonlocal cur, meta
        if cur:
            episodes.append(cur)
        cur = []
        meta = {}

    for r in rows:
        if not is_active(r):
            close()
            continue

        ts = _f(r.get("source_timestamp"))
        if ts is None:
            continue
        ch = channel_of(r)
        run_id = (r.get("run_id") or "").strip()
        platform = (r.get("platform_level") or "").strip()
        layer = (r.get("layer_id") or "").strip()
        seq = _i(r.get("sequence"))

        if cur:
            split = (
                ch != meta["channel"]
                or run_id != meta["run_id"]
                or platform != meta["platform"]
                or layer != meta["layer"]
                or (ts - meta["ts"]) > gap_tolerance_s
                or (seq is not None and meta["seq"] is not None and (seq - meta["seq"]) > seq_tolerance)
            )
            if split:
                close()

        if not cur:
            meta = {"channel": ch, "run_id": run_id, "platform": platform,
                    "layer": layer, "ts": ts, "seq": seq}
        cur.append(r)
        meta["ts"] = ts
        meta["seq"] = seq

    close()
    return episodes


def episodes_for_session(path: str, gap_tolerance_s: float, min_duration_s: float) -> Tuple[List[Episode], List[Episode]]:
    rows = load_unity_rows(path)
    if not rows:
        return [], []

    session = os.path.basename(os.path.dirname(os.path.abspath(path)))
    outcome = next((r.get("session_outcome") for r in reversed(rows) if r.get("session_outcome")), "")
    fall_ts = next((_f(r.get("source_timestamp")) for r in rows if _truthy(r.get("fall_event"))), None)

    kept: List[Episode] = []
    short: List[Episode] = []
    per_channel: Dict[str, int] = {}

    for group in group_episodes(rows, gap_tolerance_s):
        t0 = _f(group[0].get("source_timestamp"))
        t1 = _f(group[-1].get("source_timestamp"))
        if t0 is None or t1 is None:
            continue
        dur = round(max(0.0, t1 - t0), 3)

        ch = channel_of(group[0])
        idx = per_channel.get(ch, 0)
        per_channel[ch] = idx + 1

        types = [(r.get("warning_type") or "").strip() for r in group]
        types = [t for t in types if t]
        dominant = max(set(types), key=types.count) if types else ch

        seqs = [_i(r.get("sequence")) for r in group]
        seqs = [s for s in seqs if s is not None]
        gaps = sum(1 for a, b in zip(seqs, seqs[1:]) if b - a > 1)

        eids = sorted({(r.get("warning_episode_id") or "").strip() for r in group} - {""})

        ep = Episode(
            session=session,
            run_id=(group[0].get("run_id") or ""),
            channel=ch,
            warning_type=dominant,
            platform_level=(group[0].get("platform_level") or ""),
            layer_id=(group[0].get("layer_id") or ""),
            episode_index=idx,
            start_source_ts=t0,
            end_source_ts=t1,
            duration_s=dur,
            packet_count=len(group),
            sequence_first=seqs[0] if seqs else None,
            sequence_last=seqs[-1] if seqs else None,
            sequence_gaps=gaps,
            unity_episode_ids="|".join(eids),
            session_outcome=outcome,
            fall_event_ts=fall_ts,
            lead_time_to_fall_s=round(fall_ts - t0, 3) if fall_ts is not None and fall_ts >= t0 else None,
            fall_during_episode=(fall_ts <= t1) if fall_ts is not None else None,
            seconds_episode_end_to_fall=(round(fall_ts - t1, 3) if fall_ts is not None and fall_ts >= t1 else None),
            is_short_episode=dur < min_duration_s,
        )
        (short if ep.is_short_episode else kept).append(ep)

    return kept, short


def main() -> int:
    ap = argparse.ArgumentParser(description="Descriptive warning gap-clusters, channel-aware (v4).")
    ap.add_argument("--csv", required=True, nargs="+")
    ap.add_argument("--out", default=None)
    ap.add_argument("--gap-tolerance", type=float, default=0.5)
    ap.add_argument("--min-duration", type=float, default=0.0)
    ap.add_argument("--seq-tolerance", type=int, default=3)
    ap.add_argument("--exclude-outcome", action="append", default=[],
                    help="explicitly drop sessions with this outcome; every drop is reported")
    args = ap.parse_args()

    paths: List[str] = []
    for p in args.csv:
        if os.path.isdir(p):
            sub = sorted(glob.glob(os.path.join(p, "session_*", "raw.csv")))
            paths.extend(sub if sub else ([os.path.join(p, "raw.csv")] if os.path.isfile(os.path.join(p, "raw.csv")) else []))
        elif os.path.isfile(p):
            paths.append(p)
    if not paths:
        print("no raw.csv found", file=sys.stderr)
        return 1

    all_kept, all_short = [], []
    excluded, empty = [], []
    outcomes: Dict[str, int] = {}

    for path in paths:
        kept, short = episodes_for_session(path, args.gap_tolerance, args.min_duration)
        outcome = (kept or short)[0].session_outcome if (kept or short) else ""
        outcomes[outcome or "(none)"] = outcomes.get(outcome or "(none)", 0) + 1
        if outcome and outcome in args.exclude_outcome:
            excluded.append((os.path.basename(os.path.dirname(path)), outcome))
            continue
        if not kept and not short:
            empty.append(os.path.basename(os.path.dirname(path)))
            continue
        all_kept.extend(kept)
        all_short.extend(short)

    total = len(all_kept) + len(all_short)
    print("=== %d session(s): %d episode(s) total (%d short) ===" % (len(paths), total, len(all_short)))
    print("outcomes: %s" % json.dumps(outcomes, sort_keys=True))
    if excluded:
        print("EXCLUDED by --exclude-outcome:")
        for s, o in excluded:
            print("  - %s (outcome=%s)" % (s, o))
    if empty:
        print("sessions with no warning rows: %s" % ", ".join(empty))

    by_channel: Dict[str, int] = {}
    for ep in all_kept + all_short:
        by_channel[ep.channel] = by_channel.get(ep.channel, 0) + 1
    print("episodes by channel: %s" % json.dumps(by_channel, sort_keys=True))

    hdr = "%-28s %-22s %3s %7s %5s %9s %5s %s"
    print("\n" + hdr % ("session", "channel", "ep", "dur_s", "pkts", "lead_s", "gaps", "outcome"))
    for ep in all_kept:
        print(hdr % (ep.session.replace("session_", ""), ep.channel[:22], ep.episode_index,
                     "%.3f" % ep.duration_s, ep.packet_count,
                     "n/a" if ep.lead_time_to_fall_s is None else "%.2f" % ep.lead_time_to_fall_s,
                     ep.sequence_gaps, ep.session_outcome or "-"))

    if all_short:
        print("\n%d episode(s) shorter than %.3fs (kept, listed below):" % (len(all_short), args.min_duration))
        for ep in all_short[:20]:
            print("   %s %s ep%d dur=%.3fs packets=%d" % (ep.session, ep.channel, ep.episode_index,
                                                           ep.duration_s, ep.packet_count))

    print("\nNOTE: descriptive gap-clusters. These are not client-state warning episodes,")
    print("      not the orange/purple acceptance log, and not an alarm-burden metric.")

    if args.out:
        rows = sorted(all_kept + all_short, key=lambda e: (e.session, e.channel, e.episode_index))
        fields = list(asdict(rows[0]).keys()) if rows else list(Episode.__dataclass_fields__)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for ep in rows:
                w.writerow(asdict(ep))
        print("\nwritten %d episode(s), including short ones: %s" % (len(rows), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
