#!/usr/bin/env python3
"""cluster_warning_episodes_v5.py  (supersedes cluster_warning_episodes_v4.py)

v4 defect found by an independent adversarial review (2026-10-20):
  * episode identity used `platform_level` only. A change of
    `geometry_platform_instance_id` or `geometry_version_id` within the same
    level and layer therefore merged two different platforms into one episode.
  * a decreasing timestamp or a decreasing sequence number did NOT split; the
    row was simply appended, so out-of-order evidence merged.
  * `--seq-tolerance` was parsed and then never passed to
    episodes_for_session()/group_episodes(), so changing it had no effect.

v5:
  * identity key = run_id + channel + platform_level + layer_id +
    geometry_platform_instance_id + geometry_version_id;
  * a non-increasing source timestamp, or a decreasing sequence number, is an
    order discontinuity and splits (out-of-order rows are barriers, not joins);
  * --seq-tolerance is threaded through every layer and is the single
    definition of "sequence discontinuity" (default 3 = up to 3 missing
    packets stay inside one episode);
  * a session that contains more than one run_id is marked `mixed_run_ids` and
    its outcome/fall fields are NOT attributed (they would be ambiguous).

This remains a DESCRIPTIVE gap-cluster. The group count is NOT a model alarm
count, NOT the orange/purple accepted-client log, and NOT an alarm-burden
metric. `edge_warning_state` is a serialised representation that may belong to
the same rule as another channel; a channel name is not proof of an
independent warning system.
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

IDENTITY_FIELDS = (
    "platform_level",
    "layer_id",
    "geometry_platform_instance_id",
    "geometry_version_id",
)


@dataclass
class Episode:
    session: str
    run_id: str
    channel: str
    channel_is_fallback: bool
    warning_type: str
    platform_level: str
    layer_id: str
    geometry_platform_instance_id: str
    geometry_version_id: str
    episode_index: int
    start_source_ts: float
    end_source_ts: float
    duration_s: float
    packet_count: int
    sequence_first: Optional[int]
    sequence_last: Optional[int]
    sequence_discontinuities: int
    unity_episode_ids: str
    session_outcome: str
    outcome_attributed: bool
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


def _s(r: dict, key: str) -> str:
    return (r.get(key) or "").strip()


def load_unity_rows(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("source") == "unity"]


def channel_of(r: dict) -> str:
    src = _s(r, "warning_source")
    if src:
        return src
    if _truthy(r.get("edge_warning_state")):
        return "edge_warning_state"
    state = (_s(r, "prediction_state") or _s(r, "visible_warning_state")).upper()
    if state in WARNING_STATES:
        return "state:" + state
    return ""


def channel_is_fallback(r: dict) -> bool:
    """True when the channel name was reconstructed from a state field.

    A reconstructed name is a label of convenience, not evidence that this is a
    separate warning rule from whichever rule already fired.
    """
    return not _s(r, "warning_source")


def is_active(r: dict) -> bool:
    if _truthy(r.get("warning_active")) or _truthy(r.get("edge_warning_state")):
        return True
    state = _s(r, "prediction_state").upper()
    return state in WARNING_STATES


def _identity(r: dict) -> Tuple[str, ...]:
    return tuple(_s(r, f) for f in IDENTITY_FIELDS)


def group_episodes(rows: List[dict], gap_tolerance_s: float = 0.5,
                   seq_tolerance: int = 3) -> List[List[dict]]:
    """Split on inactivity, channel, run, platform identity, identity metadata,
    source-time gap, sequence discontinuity, and any order reversal.

    `seq_tolerance` is the number of missing packets still treated as one
    episode: a jump of more than `seq_tolerance` splits. A decreasing sequence
    number always splits, because it is not a gap but an ordering violation.
    """
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
            close()
            continue

        ch = channel_of(r)
        run_id = _s(r, "run_id")
        ident = _identity(r)
        seq = _i(r.get("sequence"))

        if cur:
            dt = ts - meta["ts"]
            order_break = dt < 0
            gap_break = dt > gap_tolerance_s
            seq_reversal = (seq is not None and meta["seq"] is not None and seq < meta["seq"])
            seq_jump = (seq is not None and meta["seq"] is not None
                        and (seq - meta["seq"]) > seq_tolerance)
            split = (
                ch != meta["channel"]
                or run_id != meta["run_id"]
                or ident != meta["identity"]
                or order_break
                or gap_break
                or seq_reversal
                or seq_jump
            )
            if split:
                close()

        if not cur:
            meta = {"channel": ch, "run_id": run_id, "identity": ident,
                    "ts": ts, "seq": seq}
        cur.append(r)
        meta["ts"] = ts
        meta["seq"] = seq

    close()
    return episodes


def session_run_ids(rows: List[dict]) -> List[str]:
    return sorted({_s(r, "run_id") for r in rows if _s(r, "run_id")})


def episodes_for_session(path: str, gap_tolerance_s: float, min_duration_s: float,
                         seq_tolerance: int = 3) -> Tuple[List[Episode], List[Episode]]:
    rows = load_unity_rows(path)
    if not rows:
        return [], []

    session = os.path.basename(os.path.dirname(os.path.abspath(path)))
    run_ids = session_run_ids(rows)
    single_run = len(run_ids) == 1

    # Outcome/fall are file-wide facts. They are only attributed when the file
    # contains exactly one run; otherwise they cannot be tied to an episode.
    outcome = ""
    fall_ts: Optional[float] = None
    if single_run:
        outcome = next((_s(r, "session_outcome") for r in reversed(rows) if _s(r, "session_outcome")), "")
        fall_ts = next((_f(r.get("source_timestamp")) for r in rows if _truthy(r.get("fall_event"))), None)

    kept: List[Episode] = []
    short: List[Episode] = []
    per_channel: Dict[str, int] = {}

    for group in group_episodes(rows, gap_tolerance_s, seq_tolerance):
        t0 = _f(group[0].get("source_timestamp"))
        t1 = _f(group[-1].get("source_timestamp"))
        if t0 is None or t1 is None:
            continue
        dur = round(max(0.0, t1 - t0), 3)

        ch = channel_of(group[0])
        idx = per_channel.get(ch, 0)
        per_channel[ch] = idx + 1

        types = [_s(r, "warning_type") for r in group]
        types = [t for t in types if t]
        dominant = max(set(types), key=types.count) if types else ch

        seqs = [_i(r.get("sequence")) for r in group]
        seqs = [s for s in seqs if s is not None]
        disc = sum(1 for a, b in zip(seqs, seqs[1:]) if (b - a) > seq_tolerance or b < a)

        eids = sorted({_s(r, "warning_episode_id") for r in group} - {""})

        ep = Episode(
            session=session,
            run_id=_s(group[0], "run_id"),
            channel=ch,
            channel_is_fallback=channel_is_fallback(group[0]),
            warning_type=dominant,
            platform_level=_s(group[0], "platform_level"),
            layer_id=_s(group[0], "layer_id"),
            geometry_platform_instance_id=_s(group[0], "geometry_platform_instance_id"),
            geometry_version_id=_s(group[0], "geometry_version_id"),
            episode_index=idx,
            start_source_ts=t0,
            end_source_ts=t1,
            duration_s=dur,
            packet_count=len(group),
            sequence_first=seqs[0] if seqs else None,
            sequence_last=seqs[-1] if seqs else None,
            sequence_discontinuities=disc,
            unity_episode_ids="|".join(eids),
            session_outcome=outcome,
            outcome_attributed=single_run,
            fall_event_ts=fall_ts,
            lead_time_to_fall_s=(round(fall_ts - t0, 3) if fall_ts is not None and fall_ts >= t0 else None),
            fall_during_episode=((fall_ts <= t1) if fall_ts is not None else None),
            seconds_episode_end_to_fall=(round(fall_ts - t1, 3) if fall_ts is not None and fall_ts >= t1 else None),
            is_short_episode=dur < min_duration_s,
        )
        (short if ep.is_short_episode else kept).append(ep)

    return kept, short


def session_summary(path: str) -> Dict[str, Any]:
    rows = load_unity_rows(path)
    rids = session_run_ids(rows)
    return {
        "session": os.path.basename(os.path.dirname(os.path.abspath(path))),
        "unity_rows": len(rows),
        "run_ids": rids,
        "mixed_run_ids": len(rids) > 1,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Descriptive warning gap-clusters, identity-aware (v5).")
    ap.add_argument("--csv", required=True, nargs="+")
    ap.add_argument("--out", default=None)
    ap.add_argument("--gap-tolerance", type=float, default=0.5)
    ap.add_argument("--min-duration", type=float, default=0.0)
    ap.add_argument("--seq-tolerance", type=int, default=3,
                    help="missing packets still treated as one episode; a larger jump or a "
                         "decreasing sequence always splits")
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
    excluded, empty, mixed = [], [], []
    outcomes: Dict[str, int] = {}
    fallback_channels = set()

    for path in paths:
        info = session_summary(path)
        if info["mixed_run_ids"]:
            mixed.append(info)
        kept, short = episodes_for_session(path, args.gap_tolerance, args.min_duration,
                                          args.seq_tolerance)
        outcome = (kept or short)[0].session_outcome if (kept or short) else ""
        outcomes[outcome or "(unknown)"] = outcomes.get(outcome or "(unknown)", 0) + 1
        if outcome and outcome in args.exclude_outcome:
            excluded.append((os.path.basename(os.path.dirname(path)), outcome))
            continue
        if not kept and not short:
            empty.append(os.path.basename(os.path.dirname(path)))
            continue
        all_kept.extend(kept)
        all_short.extend(short)
        for ep in kept + short:
            if ep.channel_is_fallback:
                fallback_channels.add(ep.channel)

    total = len(all_kept) + len(all_short)
    print("=== %d session(s): %d descriptive group(s) (%d short) ===" % (len(paths), total, len(all_short)))
    print("outcomes: %s" % json.dumps(outcomes, sort_keys=True))
    print("identity key: run_id + channel + platform_level + layer_id + "
          "geometry_platform_instance_id + geometry_version_id")
    print("seq tolerance: %d missing packet(s); decreasing sequence always splits" % args.seq_tolerance)
    if mixed:
        print("MIXED RUNS (outcome/fall NOT attributed):")
        for m in mixed:
            print("  - %s run_ids=%s" % (m["session"], m["run_ids"]))
    if fallback_channels:
        print("channels reconstructed from state fields (not proof of a separate rule): %s"
              % ", ".join(sorted(fallback_channels)))
    if excluded:
        print("EXCLUDED by --exclude-outcome:")
        for s, o in excluded:
            print("  - %s (outcome=%s)" % (s, o))
    if empty:
        print("sessions with no warning rows: %s" % ", ".join(empty))

    by_channel: Dict[str, int] = {}
    for ep in all_kept + all_short:
        by_channel[ep.channel] = by_channel.get(ep.channel, 0) + 1
    print("groups by channel: %s" % json.dumps(by_channel, sort_keys=True))

    hdr = "%-26s %-20s %-7s %3s %7s %5s %9s %5s %s"
    print("\n" + hdr % ("session", "channel", "plat", "ep", "dur_s", "pkts", "lead_s", "disc", "outcome"))
    for ep in all_kept:
        print(hdr % (ep.session.replace("session_", ""), ep.channel[:20],
                     (ep.geometry_platform_instance_id or "-")[:7], ep.episode_index,
                     "%.3f" % ep.duration_s, ep.packet_count,
                     "n/a" if ep.lead_time_to_fall_s is None else "%.2f" % ep.lead_time_to_fall_s,
                     ep.sequence_discontinuities, ep.session_outcome or "-"))

    if all_short:
        print("\n%d group(s) shorter than %.3fs (kept, listed below):" % (len(all_short), args.min_duration))
        for ep in all_short[:20]:
            print("   %s %s ep%d dur=%.3fs packets=%d" % (ep.session, ep.channel, ep.episode_index,
                                                           ep.duration_s, ep.packet_count))

    print("\nNOTE: descriptive gap-clusters. The count is not a model alarm count, not the")
    print("      orange/purple accepted-client log, and not an alarm-burden metric.")

    if args.out:
        rows = sorted(all_kept + all_short, key=lambda e: (e.session, e.channel, e.episode_index))
        fields = list(asdict(rows[0]).keys()) if rows else list(Episode.__dataclass_fields__)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for ep in rows:
                w.writerow(asdict(ep))
        print("\nwritten %d group(s), including short ones: %s" % (len(rows), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
