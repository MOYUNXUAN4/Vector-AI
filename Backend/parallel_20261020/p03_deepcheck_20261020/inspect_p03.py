# -*- coding: utf-8 -*-
"""P03 15 局逐局描述性核查（只读）。

不做判定结论，只把每局的原始事实抽出来：
身份/终态、条件、源连续性、预警通道、几何、Wii、时延。
"""
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(64 * 1024 * 1024)

ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\P03")
OUT = Path(__file__).with_name("p03_session_facts.jsonl")


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def ival(v):
    s = (v or "").strip()
    if s == "":
        return None
    if s.lstrip("+-").isdigit():
        return int(s)
    return None


def one_session(d: Path):
    rows = 0
    src_count = {}
    unity_ts = []
    recv_ms = []           # backend - source (秒)
    seq_unity = []
    run_ids = set()
    last = {}
    calib = {}
    layers = {}
    difficulty = {}
    sel_diff = {}
    w_triplet = {}         # (source_type, warning_type, active) -> frames
    episodes = {}          # (type) -> set(episode_id)
    vis_states = {}
    edge_states = {}
    geo_q = {"valid": 0, "invalid": 0, "blank": 0}
    geo_o = {"valid": 0, "invalid": 0, "blank": 0}
    wii_valid = 0
    wii_total = 0
    wii_board = {}
    wii_seq_first = None
    wii_seq_last = None
    wii_seq_gaps = 0
    wii_seq_back = 0
    weights = []
    scale_first = None
    scale_tail = []
    outcomes = {}
    terminal_state = None
    first_bt = None
    last_bt = None
    dup = 0
    fall_events = 0

    with d.joinpath("raw.csv").open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for r in rd:
            rows += 1
            s = r.get("source", "")
            src_count[s] = src_count.get(s, 0) + 1
            bt = fnum(r.get("backend_timestamp"))
            if bt is not None:
                first_bt = bt if first_bt is None else min(first_bt, bt)
                last_bt = bt if last_bt is None else max(last_bt, bt)
            rid = (r.get("run_id") or "").strip()
            if rid:
                run_ids.add(rid)
            last = r
            oc = (r.get("session_outcome") or "").strip()
            if oc:
                outcomes[oc] = outcomes.get(oc, 0) + 1
            c = (r.get("calibration_mode") or "").strip()
            calib[c] = calib.get(c, 0) + 1
            lv = (r.get("selected_session_layers") or "").strip()
            layers[lv] = layers.get(lv, 0) + 1
            df = (r.get("difficulty") or "").strip()
            difficulty[df] = difficulty.get(df, 0) + 1
            sd = (r.get("selected_difficulty") or "").strip()
            sel_diff[sd] = sel_diff.get(sd, 0) + 1
            if s == "unity":
                st = fnum(r.get("source_timestamp"))
                if st is not None:
                    unity_ts.append(st)
                    if bt is not None:
                        recv_ms.append(bt - st)
                sq = ival(r.get("sequence"))
                if sq is not None:
                    seq_unity.append(sq)
            wt = (
                (r.get("warning_source") or "").strip(),
                (r.get("warning_type") or "").strip(),
                (r.get("warning_active") or "").strip(),
            )
            w_triplet[wt] = w_triplet.get(wt, 0) + 1
            if wt[2].lower() in ("true", "1"):
                ep = (r.get("warning_episode_id") or "").strip()
                key = (wt[0], wt[1])
                episodes.setdefault(key, set())
                if ep:
                    episodes[key].add(ep)
            vs = (r.get("visible_warning_state") or "").strip()
            vis_states[vs] = vis_states.get(vs, 0) + 1
            es = (r.get("edge_warning_state") or "").strip()
            edge_states[es] = edge_states.get(es, 0) + 1
            for raw_key, bucket in (("geometry_query_valid", geo_q), ("geometry_ownership_valid", geo_o)):
                v = (r.get(raw_key) or "").strip().lower()
                if v == "":
                    bucket["blank"] += 1
                elif v in ("true", "1"):
                    bucket["valid"] += 1
                else:
                    bucket["invalid"] += 1
            wv = (r.get("wii_control_valid") or "").strip().lower()
            if s != "unity" or True:
                pass
            if wv != "":
                wii_total += 1
                if wv in ("true", "1"):
                    wii_valid += 1
            wb = (r.get("wii_board_loaded") or "").strip().lower()
            if wb != "":
                wii_board[wb] = wii_board.get(wb, 0) + 1
            ws = ival(r.get("wii_control_sequence"))
            if ws is not None:
                if wii_seq_first is None:
                    wii_seq_first = ws
                if wii_seq_last is not None and ws != wii_seq_last:
                    if ws > wii_seq_last:
                        wii_seq_gaps += (ws - wii_seq_last - 1)
                    else:
                        wii_seq_back += 1
                wii_seq_last = ws
            tw = fnum(r.get("total_weight"))
            if tw is not None and tw > 0:
                weights.append(tw)
            ps = fnum(r.get("platform_scale"))
            if ps is not None:
                if scale_first is None:
                    scale_first = ps
                scale_tail.append(ps)
            if (r.get("duplicate_sample") or "").strip().lower() in ("true", "1"):
                dup += 1
            if (r.get("fall_event") or "").strip().lower() in ("true", "1"):
                fall_events += 1
            terminal_state = (r.get("run_state") or "").strip() or terminal_state

    unity_ts_sorted = sorted(unity_ts)
    gaps = [b - a for a, b in zip(unity_ts_sorted, unity_ts_sorted[1:])]
    seq_sorted = sorted(seq_unity)
    seq_missing = (seq_sorted[-1] - seq_sorted[0] + 1 - len(seq_sorted)) if seq_sorted else None
    seq_dups = len(seq_sorted) - len(set(seq_sorted))

    def pct(vals, q):
        if not vals:
            return None
        v = sorted(vals)
        i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
        return round(v[i], 3)

    return {
        "session": d.name,
        "rows": rows,
        "sources": src_count,
        "run_ids": sorted(run_ids),
        "run_id_count": len(run_ids),
        "first_backend_ts": first_bt,
        "last_backend_ts": last_bt,
        "wall_seconds": round(last_bt - first_bt, 3) if (first_bt and last_bt) else None,
        "terminal_row_run_state": terminal_state,
        "terminal_row_outcome": (last.get("session_outcome") or "").strip(),
        "outcome_counts": outcomes,
        "calibration_mode": calib,
        "selected_session_layers": layers,
        "difficulty": difficulty,
        "selected_difficulty": sel_diff,
        "unity_rows": src_count.get("unity", 0),
        "unity_seq_first": seq_sorted[0] if seq_sorted else None,
        "unity_seq_last": seq_sorted[-1] if seq_sorted else None,
        "unity_seq_missing": seq_missing,
        "unity_seq_dups": seq_dups,
        "unity_src_gap_max_ms": round(max(gaps) * 1000, 1) if gaps else None,
        "unity_src_gap_p99_ms": round(pct(gaps, 0.99) * 1000, 1) if gaps else None,
        "recv_lag_ms_p50": round(pct(recv_ms, 0.5) * 1000, 1) if recv_ms else None,
        "recv_lag_ms_p99": round(pct(recv_ms, 0.99) * 1000, 1) if recv_ms else None,
        "recv_lag_ms_max": round(max(recv_ms) * 1000, 1) if recv_ms else None,
        "warning_triplets": {"|".join(k): v for k, v in sorted(w_triplet.items()) if k[1] or k[2] in ("true", "True")},
        "active_episodes": {f"{k[0]}|{k[1]}": len(v) for k, v in sorted(episodes.items())},
        "visible_warning_states": vis_states,
        "edge_warning_states": edge_states,
        "geometry_query_valid": geo_q,
        "geometry_ownership_valid": geo_o,
        "wii_valid_ratio": round(wii_valid / wii_total, 4) if wii_total else None,
        "wii_rows_with_valid_field": wii_total,
        "wii_board_loaded": wii_board,
        "wii_seq": [wii_seq_first, wii_seq_last, wii_seq_gaps, wii_seq_back],
        "total_weight_p50": pct(weights, 0.5) if weights else None,
        "total_weight_min": round(min(weights), 2) if weights else None,
        "total_weight_max": round(max(weights), 2) if weights else None,
        "platform_scale_first": scale_first,
        "platform_scale_p50": pct(scale_tail, 0.5) if scale_tail else None,
        "platform_scale_gt2_frames": sum(1 for x in scale_tail if x > 2),
        "duplicate_sample_rows": dup,
        "fall_event_rows": fall_events,
    }


def main():
    facts = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        f = one_session(d)
        facts.append(f)
        print(
            f"{f['session']} rows={f['rows']} runs={f['run_id_count']} "
            f"state={f['terminal_row_run_state']} out={f['terminal_row_outcome']} "
            f"layers={list(f['selected_session_layers'])} diff={list(f['difficulty'])} "
            f"gap_max={f['unity_src_gap_max_ms']} wii={f['wii_valid_ratio']} "
            f"scale_first={f['platform_scale_first']}",
            flush=True,
        )
    with OUT.open("w", encoding="utf-8") as fh:
        for f in facts:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT} ({len(facts)} sessions)")


if __name__ == "__main__":
    sys.exit(main())
