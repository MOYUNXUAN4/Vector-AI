# -*- coding: utf-8 -*-
"""P03 适用域分段：把每局的预警 ACTIVE 帧按 platform_scale / calibration_mode 切开。

目的：区分「开局大平台前缀（5层被拒）」与「有效游戏阶段」，
避免用整局计数评价横幅是否生效。
"""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(64 * 1024 * 1024)
ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\P03")
OUT = Path(__file__).with_name("p03_phase_split.jsonl")


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def truthy(v):
    return (v or "").strip().lower() in ("true", "1")


def one(d):
    seg = {
        "prefix": {"rows": 0, "attn": 0, "strong": 0, "attn_ep": set(), "strong_ep": set(), "t0": None, "t1": None},
        "active": {"rows": 0, "attn": 0, "strong": 0, "attn_ep": set(), "strong_ep": set(), "t0": None, "t1": None},
    }
    calib_by_sec = {}
    scale_by_sec = {}
    first_bt = None
    last_bt = None
    first_outcome_bt = None
    outcome = ""
    trans_ms = None
    # 记录 scale 首次 <=2 的 backend 时间
    with d.joinpath("raw.csv").open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("source") != "unity":
                continue
            bt = fnum(r.get("backend_timestamp"))
            ps = fnum(r.get("platform_scale"))
            if bt is None or ps is None:
                continue
            first_bt = bt if first_bt is None else min(first_bt, bt)
            last_bt = bt if last_bt is None else max(last_bt, bt)
            if trans_ms is None and ps <= 2.0:
                trans_ms = bt
            key = "prefix" if ps > 2.0 else "active"
            s = seg[key]
            s["rows"] += 1
            s["t0"] = bt if s["t0"] is None else min(s["t0"], bt)
            s["t1"] = bt if s["t1"] is None else max(s["t1"], bt)
            ws = (r.get("warning_source") or "").strip()
            wa = truthy(r.get("warning_active"))
            if wa and ws == "unity_attention_rule":
                s["attn"] += 1
                ep = (r.get("warning_episode_id") or "").strip()
                if ep:
                    s["attn_ep"].add(ep)
            if wa and ws == "unity_edge_geometry":
                s["strong"] += 1
                ep = (r.get("warning_episode_id") or "").strip()
                if ep:
                    s["strong_ep"].add(ep)
            sec = int(bt - first_bt) if first_bt is not None else None
            calib_by_sec.setdefault(sec, set()).add((r.get("calibration_mode") or "").strip())
            scale_by_sec.setdefault(sec, []).append(ps)
            oc = (r.get("session_outcome") or "").strip()
            if oc:
                outcome = oc
                if first_outcome_bt is None:
                    first_outcome_bt = bt
    for k in seg:
        seg[k]["attn_ep"] = sorted(seg[k]["attn_ep"])
        seg[k]["strong_ep"] = sorted(seg[k]["strong_ep"])
        for t in ("t0", "t1"):
            if seg[k][t] is not None:
                seg[k][t] = round(seg[k][t] - first_bt, 3)
    calib_flip_sec = None
    if calib_by_sec:
        for sec in sorted(calib_by_sec):
            if "False" in calib_by_sec[sec] or "" not in calib_by_sec[sec]:
                calib_flip_sec = sec
                break
    return {
        "session": d.name,
        "outcome": outcome,
        "wall_s": round(last_bt - first_bt, 3) if first_bt and last_bt else None,
        "outcome_at_s": round(first_outcome_bt - first_bt, 3) if first_outcome_bt and first_bt else None,
        "prefix_end_s": round(trans_ms - first_bt, 3) if trans_ms and first_bt else None,
        "segments": seg,
        "calib_distinct": sorted({x for v in calib_by_sec.values() for x in v}),
        "calib_flip_s": calib_flip_sec,
    }


def main():
    out = []
    for d in sorted(ROOT.iterdir()):
        if d.is_dir():
            f = one(d)
            out.append(f)
            p, a = f["segments"]["prefix"], f["segments"]["active"]
            print(
                f"{f['session']} out={f['outcome']:<22} wall={f['wall_s']:>6}s "
                f"prefix→{f['prefix_end_s']:>6}s | pre attn={p['attn']:>4}/ep{len(p['attn_ep'])} "
                f"str={p['strong']:>4}/ep{len(p['strong_ep'])} | act attn={a['attn']:>4}/ep{len(a['attn_ep'])} "
                f"str={a['strong']:>4}/ep{len(a['strong_ep'])} | calib={f['calib_distinct']} flip={f['calib_flip_s']}",
                flush=True,
            )
    with OUT.open("w", encoding="utf-8") as fh:
        for f in out:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
