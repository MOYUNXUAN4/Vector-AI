# -*- coding: utf-8 -*-
"""P03 后9局实验通道可用性：按 run 精确匹配影子日志，算每局不可用窗口累积时长与 available 覆盖率。"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(64 * 1024 * 1024)
B = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend")
SHADOW = B / "telemetry_logs/proximity_shadow.jsonl"
ROOT = B / "telemetry_logs/P03"
OUT = Path(__file__).with_name("p03_coverage.json")


def run_map():
    m, rows = {}, {}
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        with d.joinpath("raw.csv").open("r", encoding="utf-8", newline="") as f:
            rl = list(csv.DictReader(f))
        ids = {(r.get("run_id") or "").strip() for r in rl if r.get("source") == "unity"}
        ids.discard("")
        rid = ids.pop()
        m[rid] = d.name
        rows[d.name] = len([r for r in rl if r.get("source") == "unity"])
    return m, rows


def main():
    runs, unity_rows = run_map()
    per = defaultdict(list)
    with SHADOW.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = r.get("run_id")
            if rid in runs:
                per[runs[rid]].append(r)
    out = {}
    print(f"{'session':<10}{'rows':>6}{'shadow':>7}{'avail':>7}{'cover':>7}"
          f"{'unsup_s':>9}{'warm_s':>8}{'gap_s':>8}{'outdom':>7}")
    for name in sorted(runs.values()):
        recs = per.get(name, [])
        if not recs:
            continue
        recs.sort(key=lambda r: r.get("input_source_timestamp") or 0)
        t0 = recs[0].get("input_source_timestamp")
        unsup = [r for r in recs if r.get("reason") == "unsupported_or_calibration_phase"]
        warm = [r for r in recs if r.get("reason") == "insufficient_0_5s_history"]
        avail = [r for r in recs if r.get("reason") == "available"]
        outdom = [r for r in recs if r.get("reason") == "outside_proximity_domain"]

        def span(rs):
            if not rs:
                return 0.0
            return round(max(r.get("input_source_timestamp") or 0 for r in rs) -
                         min(r.get("input_source_timestamp") or 0 for r in rs), 2)

        # 不可用帧的结束时刻（相对 t0）：unsup 或 warm
        blocked = unsup + warm
        block_end = max((r.get("input_source_timestamp") or 0) for r in blocked) - t0 if blocked else 0
        cover = len(avail) / len(recs) if recs else 0
        # 首个 available 的相对时间
        first_av = min((r.get("input_source_timestamp") or 0) for r in avail) - t0 if avail else None
        out[name] = {
            "run_id": next(k for k, v in runs.items() if v == name),
            "unity_rows": unity_rows[name], "shadow_rows": len(recs),
            "available": len(avail), "available_coverage": round(cover, 3),
            "unsupported": len(unsup), "warmup": len(warm), "outside_domain": len(outdom),
            "unsupported_span_s": span(unsup), "warmup_span_s": span(warm),
            "blocked_until_s": round(block_end, 2),
            "first_available_s": round(first_av, 2) if first_av is not None else None,
            "session_span_s": round((recs[-1].get("input_source_timestamp") or 0) - t0, 2),
        }
        o = out[name]
        print(f"{name[-6:]:<10}{o['unity_rows']:>6}{o['shadow_rows']:>7}{o['available']:>7}"
              f"{o['available_coverage']:>7.2f}{o['unsupported_span_s']:>9}{o['warmup_span_s']:>8}"
              f"{o['blocked_until_s']:>8}{o['outside_domain']:>7}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
