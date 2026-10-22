#!/usr/bin/env python3
"""Extract real Unity client warning state lines from a preserved Player.log."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

RUNS = {
    "358796c34dff4bc1bd095becdcaec003": "first_run_sensitivity_unknown_non055",
    "510db1f687b34b2193ce0113d70e7262": "run_2",
    "9cde97e123d240268311b479d55a83eb": "run_3",
    "8e4f5a963d0f4ec48e382cf129ab0eb8": "run_4",
}
CHANNELS = {
    "ExperimentalModelWarning": "model",
    "ExperimentalProximityWarning": "proximity",
    "ExperimentalGeometryWarning": "geometry",
}
EVENT_RE = re.compile(r"\[(ExperimentalModelWarning|ExperimentalProximityWarning|ExperimentalGeometryWarning)\]\s+(.*)$")
FIELD_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_line(line: str, line_no: int, source_sha: str):
    match = EVENT_RE.search(line)
    if not match:
        return None
    event_name, payload = match.groups()
    fields = dict(FIELD_RE.findall(payload))
    run_id = fields.get("run_id", fields.get("run", ""))
    if run_id not in RUNS:
        return None
    if event_name == "ExperimentalGeometryWarning":
        state = fields.get("state", "").upper()
        if not state:
            state = {"active": "ACTIVE", "revoked": "REVOKED"}.get(payload.split(maxsplit=1)[0].lower(), "UNKNOWN")
    else:
        state = fields.get("state", "").upper()
    return {
        "physical_player_log_line": line_no,
        "source_sha256": source_sha,
        "event_name": event_name,
        "channel": CHANNELS[event_name],
        "run_id": run_id,
        "run_note": RUNS[run_id],
        "state": state,
        "local_monotonic_s": as_float(fields.get("local_monotonic_s")),
        "layer": fields.get("layer", ""),
        "platform": fields.get("platform", ""),
        "version": fields.get("version", ""),
        "input_sequence": fields.get("input_sequence", ""),
        "warning_update_sequence": fields.get("warning_update_sequence", ""),
        "prediction_sequence": fields.get("prediction_sequence", ""),
        "reason": fields.get("reason", ""),
        "revoke_reason": fields.get("revoke_reason", ""),
        "raw_line": line.rstrip("\r\n"),
    }


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def make_episodes(events):
    episodes = []
    geometry_open = {}
    state_open = {}
    orphan_revokes = []
    for event in events:
        channel, run = event["channel"], event["run_id"]
        if channel == "geometry":
            key = (run, event["layer"], event["platform"])
            if event["state"] == "ACTIVE":
                if key not in geometry_open:
                    geometry_open[key] = {
                        "run_id": run, "run_note": RUNS[run], "channel": channel,
                        "start_log_line": event["physical_player_log_line"],
                        "end_log_line": None, "start_local_monotonic_s": None,
                        "end_local_monotonic_s": None, "duration_s": None,
                        "logcount": 1, "revocation_reason": None, "censored": False,
                        "time_basis": "input_sequence_only_no_client_clock",
                        "layer": event["layer"], "platform": event["platform"],
                        "start_sequence": event["input_sequence"], "end_sequence": None,
                    }
                else:
                    geometry_open[key]["logcount"] += 1
                    geometry_open[key]["end_log_line"] = event["physical_player_log_line"]
                    geometry_open[key]["end_sequence"] = event["input_sequence"]
            elif event["state"] == "REVOKED":
                ep = geometry_open.pop(key, None)
                if ep is None:
                    orphan_revokes.append(event)
                else:
                    ep["end_log_line"] = event["physical_player_log_line"]
                    ep["end_sequence"] = event["input_sequence"]
                    ep["logcount"] += 1
                    ep["revocation_reason"] = event["reason"]
                    episodes.append(ep)
            continue

        key = (run, channel)
        if event["state"] == "ACTIVE":
            ep = state_open.get(key)
            if ep is None:
                state_open[key] = {
                    "run_id": run, "run_note": RUNS[run], "channel": channel,
                    "start_log_line": event["physical_player_log_line"],
                    "end_log_line": None,
                    "start_local_monotonic_s": event["local_monotonic_s"],
                    "end_local_monotonic_s": None, "duration_s": None,
                    "logcount": 1, "revocation_reason": None, "censored": False,
                    "time_basis": "client_local_monotonic_s",
                    "layer": event["layer"], "platform": event["platform"],
                    "start_sequence": event["input_sequence"] or event["prediction_sequence"],
                    "end_sequence": None,
                }
            else:
                ep["logcount"] += 1
                ep["end_log_line"] = event["physical_player_log_line"]
                if event["local_monotonic_s"] is not None:
                    ep["end_local_monotonic_s"] = event["local_monotonic_s"]
                if event["input_sequence"] or event["prediction_sequence"]:
                    ep["end_sequence"] = event["input_sequence"] or event["prediction_sequence"]
        elif event["state"] == "REVOKED":
            ep = state_open.pop(key, None)
            if ep is None:
                orphan_revokes.append(event)
            else:
                ep["end_log_line"] = event["physical_player_log_line"]
                ep["end_local_monotonic_s"] = event["local_monotonic_s"]
                if ep["start_local_monotonic_s"] is not None and event["local_monotonic_s"] is not None:
                    ep["duration_s"] = round(event["local_monotonic_s"] - ep["start_local_monotonic_s"], 6)
                ep["logcount"] += 1
                ep["revocation_reason"] = event["revoke_reason"] or event["reason"]
                ep["end_sequence"] = event["input_sequence"] or event["prediction_sequence"] or None
                episodes.append(ep)
    for ep in state_open.values():
        ep["censored"] = True
        episodes.append(ep)
    for ep in geometry_open.values():
        ep["censored"] = True
        episodes.append(ep)
    episodes.sort(key=lambda x: (x["run_id"], x["channel"], x["start_log_line"]))
    return episodes, orphan_revokes


def summarize(episodes):
    groups = defaultdict(list)
    for ep in episodes:
        groups[(ep["run_id"], ep["channel"])].append(ep)
    result = []
    for run_id in RUNS:
        for channel in ("model", "proximity", "geometry"):
            rows = groups.get((run_id, channel), [])
            measured = [e["duration_s"] for e in rows if e["duration_s"] is not None]
            result.append({
                "run_id": run_id, "run_note": RUNS[run_id], "channel": channel,
                "episode_count": len(rows),
                "accepted_duration_total_s": round(sum(measured), 6) if channel != "geometry" else None,
                "max_episode_duration_s": max(measured) if measured else None,
                "short_episode_count_lt_0_5s": sum(d < 0.5 for d in measured),
                "censored_episode_count": sum(bool(e["censored"]) for e in rows),
                "duration_episode_count": len(measured),
                "duration_note": "receive-to-clear proxy; not rendered screen exposure" if channel != "geometry" else "not measurable: geometry client lines have no local_monotonic_s",
            })
    return result


def self_test():
    def ev(ch, run, state, t=None, line=1, **extra):
        return {"channel": ch, "run_id": run, "state": state,
                "local_monotonic_s": t, "physical_player_log_line": line,
                "layer": extra.get("layer", "1"), "platform": extra.get("platform", "p"),
                "input_sequence": extra.get("input_sequence", ""),
                "prediction_sequence": extra.get("prediction_sequence", ""),
                "reason": extra.get("reason", ""), "revoke_reason": extra.get("revoke_reason", "")}
    a, b = "358796c34dff4bc1bd095becdcaec003", "510db1f687b34b2193ce0113d70e7262"
    episodes, orphan = make_episodes([
        ev("model", a, "ACTIVE", 10.0, 1), ev("model", a, "ACTIVE", 10.2, 2, prediction_sequence="12"),
        ev("model", a, "REVOKED", 10.4, 3, revoke_reason="safe"),
        ev("model", b, "ACTIVE", 1.0, 4), ev("model", b, "REVOKED", 1.3, 5),
        ev("geometry", a, "ACTIVE", None, 6, input_sequence="500"),
        ev("geometry", a, "REVOKED", None, 7, input_sequence="508", reason="clear"),
    ])
    assert not orphan and len(episodes) == 3
    model_a = next(e for e in episodes if e["run_id"] == a and e["channel"] == "model")
    geom = next(e for e in episodes if e["channel"] == "geometry")
    assert model_a["logcount"] == 3 and model_a["duration_s"] == 0.4
    assert geom["duration_s"] is None and geom["start_sequence"] == "500" and geom["end_sequence"] == "508"
    summary = summarize(episodes)
    assert all(r["accepted_duration_total_s"] is None for r in summary if r["channel"] == "geometry")
    assert all(r["episode_count"] == 0 for r in summary if r["channel"] == "geometry" and r["run_id"] != a)
    assert all(r["duration_note"] == "receive-to-clear proxy; not rendered screen exposure" for r in summary if r["channel"] in ("model", "proximity"))
    open_eps, _ = make_episodes([ev("proximity", a, "ACTIVE", 4.0, 8), ev("proximity", b, "ACTIVE", 8.0, 9)])
    assert len(open_eps) == 2 and all(e["censored"] for e in open_eps)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--player-log", type=Path, default=Path(r"C:\Users\QIYUXUAN\AppData\LocalLow\QI YUXUAN\VectorAI\Player.log"))
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("self-test passed")
        return
    args.out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = args.out_dir / "Player.log.snapshot"
    if not snapshot.exists():
        shutil.copy2(args.player_log, snapshot)
    src_sha = sha256(args.player_log)
    snap_sha = sha256(snapshot)
    if src_sha != snap_sha:
        raise SystemExit(f"source/snapshot SHA mismatch: {src_sha} != {snap_sha}")
    events = []
    with args.player_log.open("r", encoding="utf-8", errors="replace", newline="") as f:
        for line_no, line in enumerate(f, 1):
            event = parse_line(line, line_no, src_sha)
            if event:
                events.append(event)
    episodes, orphan_revokes = make_episodes(events)
    summaries = summarize(episodes)
    meta = {"source_path": str(args.player_log), "snapshot_path": str(snapshot),
            "source_sha256": src_sha, "snapshot_sha256": snap_sha,
            "physical_line_numbering": "1-based, from original Player.log snapshot",
            "clock_policy": "No conversion to Unity time or epoch; duration only within a client local_monotonic_s clock domain.",
            "runs": RUNS, "event_line_count": len(events), "episode_count": len(episodes),
            "orphan_revoke_count": len(orphan_revokes)}
    (args.out_dir / "source_manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (args.out_dir / "client_warning_events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    (args.out_dir / "client_warning_episodes.json").write_text(json.dumps(episodes, indent=2, ensure_ascii=False), encoding="utf-8")
    with (args.out_dir / "client_warning_episodes.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = list(episodes[0]) if episodes else ["run_id", "channel"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(episodes)
    with (args.out_dir / "client_warning_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader(); writer.writerows(summaries)
    (args.out_dir / "orphan_revokes.json").write_text(json.dumps(orphan_revokes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"events": len(events), "episodes": len(episodes), "orphan_revokes": len(orphan_revokes), "source_sha256": src_sha}, indent=2))


if __name__ == "__main__":
    main()
