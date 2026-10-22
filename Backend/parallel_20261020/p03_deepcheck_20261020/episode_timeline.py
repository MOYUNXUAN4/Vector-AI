# -*- coding: utf-8 -*-
"""逐 episode 时间线：每局的 ATTENTION / STRONG episode 起止（相对开局秒）与帧数。"""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(64 * 1024 * 1024)
ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\P03")
OUT = Path(__file__).with_name("p03_episode_timeline.json")


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def truthy(v):
    return (v or "").strip().lower() in ("true", "1")


def one(d):
    recs = []
    t0 = None
    fall_at = None
    edge_contact_at = None
    with d.joinpath("raw.csv").open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("source") != "unity":
                continue
            bt = fnum(r.get("backend_timestamp"))
            if bt is None:
                continue
            t0 = bt if t0 is None else min(t0, bt)
            ws = (r.get("warning_source") or "").strip()
            if truthy(r.get("warning_active")) and ws in ("unity_attention_rule", "unity_edge_geometry"):
                recs.append({
                    "bt": bt,
                    "src": ws,
                    "type": (r.get("warning_type") or "").strip(),
                    "ep": (r.get("warning_episode_id") or "").strip(),
                    "scale": fnum(r.get("platform_scale")),
                    "vis": (r.get("visible_warning_state") or "").strip(),
                    "dist": fnum(r.get("distance_to_hole")),
                })
            if fall_at is None and truthy(r.get("fall_event")):
                fall_at = bt
            if edge_contact_at is None and truthy(r.get("edge_warning_state")) is False and (r.get("visible_warning_state") or "").strip() == "EDGE_CONTACT":
                edge_contact_at = bt
    eps = {}
    for x in recs:
        k = (x["src"], x["ep"] or "(no-id)")
        e = eps.setdefault(k, {"frames": 0, "start": x["bt"], "end": x["bt"], "type": x["type"], "vis": set(), "scale_min": x["scale"], "scale_max": x["scale"]})
        e["frames"] += 1
        e["start"] = min(e["start"], x["bt"])
        e["end"] = max(e["end"], x["bt"])
        e["vis"].add(x["vis"])
        if x["scale"] is not None:
            e["scale_min"] = x["scale"] if e["scale_min"] is None else min(e["scale_min"], x["scale"])
            e["scale_max"] = x["scale"] if e["scale_max"] is None else max(e["scale_max"], x["scale"])
    out = []
    for (src, ep), e in sorted(eps.items(), key=lambda kv: kv[1]["start"]):
        out.append({
            "source": src, "episode": ep, "type": e["type"], "frames": e["frames"],
            "start_s": round(e["start"] - t0, 3), "end_s": round(e["end"] - t0, 3),
            "dur_s": round(e["end"] - e["start"], 3),
            "visible": sorted(v for v in e["vis"] if v),
            "scale_min": round(e["scale_min"], 3) if e["scale_min"] is not None else None,
            "scale_max": round(e["scale_max"], 3) if e["scale_max"] is not None else None,
        })
    return {
        "session": d.name,
        "fall_at_s": round(fall_at - t0, 3) if fall_at and t0 else None,
        "episodes": out,
    }


def main():
    allout = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        f = one(d)
        allout.append(f)
        print(f"== {f['session']} fall_at={f['fall_at_s']}")
        for e in f["episodes"]:
            print(f"   {e['source']:<22} {e['type']:<8} ep={e['episode'][:12]:<12} "
                  f"{e['start_s']:>7}s→{e['end_s']:>7}s ({e['dur_s']:>5}s) frames={e['frames']:>4} "
                  f"vis={e['visible']} scale=[{e['scale_min']},{e['scale_max']}]")
    OUT.write_text(json.dumps(allout, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
