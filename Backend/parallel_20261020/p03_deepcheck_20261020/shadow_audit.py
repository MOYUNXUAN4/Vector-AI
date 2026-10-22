# -*- coding: utf-8 -*-
"""P03 15 局在 TTE 影子日志中的适用性：active / causal_available / reason 分布，按精确 run 过滤。"""
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(64 * 1024 * 1024)
BACKEND = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend")
SHADOW = BACKEND / "telemetry_logs/proximity_shadow.jsonl"
ROOT = BACKEND / "telemetry_logs/P03"
OUT = Path(__file__).with_name("p03_shadow_audit.json")


def run_map():
    m = {}
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        with d.joinpath("raw.csv").open("r", encoding="utf-8", newline="") as f:
            ids = {(r.get("run_id") or "").strip() for r in csv.DictReader(f) if r.get("source") == "unity"}
        ids.discard("")
        if len(ids) != 1:
            raise SystemExit(f"bad run id count in {d.name}: {ids}")
        rid = ids.pop()
        if rid in m:
            raise SystemExit(f"duplicate run id {rid}")
        m[rid] = d.name
    return m


def main():
    runs = run_map()
    per = defaultdict(lambda: {
        "records": 0, "active": 0, "causal": 0, "valid": 0,
        "states": Counter(), "reasons": Counter(), "seq_first": None, "seq_last": None,
        "active_input_seq": set(), "first_active_input_seq": None, "first_active_ist": None,
    })
    bad = 0
    with SHADOW.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            rid = r.get("run_id")
            if rid not in runs:
                continue
            p = per[runs[rid]]
            p["records"] += 1
            p["states"][r.get("state")] += 1
            p["reasons"][r.get("reason")] += 1
            if r.get("active") is True:
                p["active"] += 1
                p["active_input_seq"].add(r.get("input_sequence"))
                if p["first_active_ist"] is None:
                    p["first_active_ist"] = r.get("input_source_timestamp")
            if r.get("causal_available") is True:
                p["causal"] += 1
            if r.get("valid") is True:
                p["valid"] += 1
            sq = r.get("shadow_sequence")
            if isinstance(sq, int) and not isinstance(sq, bool):
                p["seq_first"] = sq if p["seq_first"] is None else min(p["seq_first"], sq)
                p["seq_last"] = sq if p["seq_last"] is None else max(p["seq_last"], sq)
    out = {}
    for rid, name in sorted(runs.items(), key=lambda kv: kv[1]):
        p = per.get(name)
        if not p:
            out[name] = {"records": 0, "note": "no shadow record"}
            print(f"{name}  NO SHADOW RECORD")
            continue
        out[name] = {
            "run_id": rid, "records": p["records"], "active": p["active"],
            "causal_available": p["causal"], "valid": p["valid"],
            "active_distinct_input_sequences": len(p["active_input_seq"]),
            "first_active_input_source_timestamp": p["first_active_ist"],
            "states": dict(p["states"]), "reasons": dict(p["reasons"]),
            "shadow_seq": [p["seq_first"], p["seq_last"]],
        }
        print(f"{name[-6:]} rec={p['records']:>5} active={p['active']:>4} "
              f"ep(seq)={len(p['active_input_seq']):>3} causal={p['causal']:>5} valid={p['valid']:>5} "
              f"state={dict(p['states'])} reason={dict(p['reasons'])}")
    out["_meta"] = {"bad_json_lines": bad, "shadow_file": str(SHADOW)}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nbad json lines: {bad}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
