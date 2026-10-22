"""Read-only TEST1012 pilot screen; emits JSON to stdout and writes no data."""
import csv
import json
import math
from pathlib import Path

ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\TEST1012")
OFFSETS = (0.8, 0.6, 0.4)


def num(row, key):
    try:
        x = float(row.get(key, ""))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def yes(row, key):
    return str(row.get(key, "")).strip().lower() in ("1", "true", "yes")


def context_ok(r):
    return (r.get("run_state") == "running" and r.get("platform_level") == "1"
            and r.get("source") == "unity"
            and yes(r, "geometry_query_valid") and yes(r, "geometry_ownership_valid")
            and yes(r, "directional_edge_valid")
            and num(r, "geometry_platform_instance_id") is not None
            and bool(r.get("geometry_version_id"))
            and r.get("geometry_active_platform_instance_id") == r.get("geometry_platform_instance_id")
            and r.get("geometry_active_version_id") == r.get("geometry_version_id")
            and num(r, "source_timestamp") is not None
            and num(r, "geometry_source_timestamp") is not None)


def load_session(path):
    with (path / "raw.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_seq"] = int(r["sequence"])
        r["_t"] = num(r, "source_timestamp")
        r["_clear"] = (num(r, "directional_edge_distance") - num(r, "ball_radius")
                       if num(r, "directional_edge_distance") is not None and num(r, "ball_radius") is not None else None)
        r["_v"] = num(r, "ball_radial_velocity")
        r["_ctx"] = context_ok(r)
    return rows


def same_context(a, b):
    return all(a.get(k) == b.get(k) for k in ("run_id", "platform_level", "geometry_platform_instance_id", "geometry_version_id"))


def continuous(rows):
    for a, b in zip(rows, rows[1:]):
        if b["_t"] - a["_t"] <= 0 or b["_t"] - a["_t"] > .1000001 or b["_seq"] != a["_seq"] + 1:
            return False
    return True


def valid_segments(rows):
    valid = [r for r in rows if r["_ctx"] and r["_clear"] is not None and r["_v"] is not None]
    segments, segment = [], []
    for r in valid:
        if segment:
            p = segment[-1]
            dt = r["_t"] - p["_t"]
            if not same_context(p, r) or r["_seq"] != p["_seq"] + 1 or not (0 < dt <= .1000001):
                segments.append(segment)
                segment = []
        segment.append(r)
    if segment:
        segments.append(segment)
    return segments


def angle_deg(r):
    bx, bz = num(r, "ball_pos_x"), num(r, "ball_pos_z")
    px, pz = num(r, "platform_center_x"), num(r, "platform_center_z")
    dx, dz = (bx - px, bz - pz) if bx is not None and bz is not None and px is not None and pz is not None else (None, None)
    return math.degrees(math.atan2(dz, dx)) % 360 if dx is not None and (dx or dz) else None


def angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def terminal_anchor(rows):
    # Last positive -> nonpositive consecutive crossing in same valid running context.
    valid = [r for r in rows if r["_ctx"] and r["_clear"] is not None]
    crossings = []
    for a, b in zip(valid, valid[1:]):
        if b["_seq"] == a["_seq"] + 1 and same_context(a, b) and b["_t"] - a["_t"] <= .1 and a["_clear"] > 0 >= b["_clear"]:
            crossings.append((a, b))
    return crossings[-1] if crossings else None


def recovery_labels(rows):
    labels = []
    # Each labeled row is first confirmation time of a continuous >=.1s inward-v, positive-clearance recovery,
    # with >=.02m clearance gain from a same-context sample at least .1s earlier.
    for segment in valid_segments(rows):
        i = 0
        while i < len(segment):
            if segment[i]["_v"] >= -.05:
                i += 1
                continue
            start = i
            j = i
            while j < len(segment) and segment[j]["_v"] < -.05:
                end = segment[j]
                if end["_clear"] > 0 and end["_t"] - segment[start]["_t"] >= .1:
                    baseline = [r for r in segment[:j] if r["_t"] <= end["_t"] - .1]
                    if baseline and end["_clear"] - baseline[-1]["_clear"] >= .02:
                        labels.append(end)
                        break
                j += 1
            i = max(j + 1, start + 1)
    return labels


def asof(rows, anchor, offset):
    target = anchor["_t"] - offset
    candidates = [r for r in rows if r["_ctx"] and r["_clear"] is not None and r["_v"] is not None
                  and same_context(r, anchor) and r["_t"] <= target]
    if not candidates:
        return None
    r = max(candidates, key=lambda x: x["_t"])
    age = target - r["_t"]
    return r if 0 <= age <= .0600001 else None


def fall_events(rows):
    anchor = terminal_anchor(rows)
    if not anchor:
        return None
    lower, upper = anchor
    out = {"anchor_lower_seq": lower["_seq"], "anchor_upper_seq": upper["_seq"],
           "anchor_lower_time": lower["_t"], "anchor_lower_clearance": lower["_clear"]}
    out["samples"] = {}
    out["sample_rejections"] = {}
    for off in OFFSETS:
        r = asof(rows, lower, off)
        if r and (r["_clear"] <= 0 or r["_v"] <= .05):
            out["sample_rejections"][str(off)] = "not positive-clearance/outward radial velocity"
            r = None
        elif r is None:
            out["sample_rejections"][str(off)] = "no valid same-context sample within 0.06s as-of window"
        out["samples"][str(off)] = None if r is None else {
            "sequence": r["_seq"], "age_seconds": lower["_t"] - off - r["_t"],
            "clearance": r["_clear"], "radial_velocity": r["_v"], "angle_deg": angle_deg(r),
            "platform_id": r["geometry_platform_instance_id"], "version_id": r["geometry_version_id"]}
    return out


def completion_events(rows):
    labels = recovery_labels(rows)
    candidates = []
    # Match the current outward sample; a future recovery only establishes cohort eligibility.
    label_ids = {r["_seq"] for r in labels}
    for segment in valid_segments(rows):
        for i, r in enumerate(segment):
            if r["_clear"] <= 0 or r["_v"] <= .05:
                continue
            for label in segment[i + 1:]:
                if label["_t"] - r["_t"] > 1.5:
                    break
                if label["_seq"] in label_ids:
                    delay = label["_t"] - r["_t"]
                    if delay <= 0:
                        continue
                    # Every row between the candidate and recovery label is present in this segment.
                    candidates.append({"label_seq": label["_seq"], "sample_seq": r["_seq"],
                                   "future_label_delay_seconds": delay,
                                   "clearance": r["_clear"], "radial_velocity": r["_v"], "angle_deg": angle_deg(r),
                                   "platform_id": r["geometry_platform_instance_id"], "version_id": r["geometry_version_id"]})
                    break
    # Deduplicate candidate rows (first subsequent qualifying recovery is retained).
    return sorted({c["sample_seq"]: c for c in candidates}.values(), key=lambda x: x["sample_seq"])


def best_pairs(falls, completes, off):
    fs = [(sid, ev) for sid, ev in falls.items() if ev["samples"][str(off)] is not None]
    complete_ids = sorted(completes)
    edges = {}
    for i, (fsid, fev) in enumerate(fs):
        f = fev["samples"][str(off)]
        for j, csid in enumerate(complete_ids):
            for c in completes[csid]:
                da = angle_diff(f["angle_deg"], c["angle_deg"])
                dc = abs(f["clearance"] - c["clearance"])
                dv = abs(f["radial_velocity"] - c["radial_velocity"])
                if da <= 30 and dc <= .5 and dv <= .75:
                    # Compress every control state to the minimum-cost state per session pair.
                    cost = da / 30 + dc / .5 + dv / .75
                    edge = (cost, da, dc, dv, c)
                    if (i, j) not in edges or (cost, c["sample_seq"]) < (edges[(i, j)][0], edges[(i, j)][4]["sample_seq"]):
                        edges[(i, j)] = edge
    # Exhaustive one-to-one assignment: maximize pair count, then minimize total normalized cost.
    best = None
    def walk(i, used, picked, cost):
        nonlocal best
        if i == len(fs):
            key = (-len(picked), cost, tuple(picked))
            if best is None or key < best[0]:
                best = (key, list(picked))
            return
        walk(i + 1, used, picked, cost)
        for j in range(len(complete_ids)):
            if j not in used and (i, j) in edges:
                walk(i + 1, used | {j}, picked + [(i, j)], cost + edges[(i, j)][0])
    walk(0, set(), [], 0.0)
    selected = best[1] if best else []
    pairs = []
    usedf, usedc = set(), set()
    for i, j in selected:
        usedf.add(i); usedc.add(j)
        fsid, fev = fs[i]; csid = complete_ids[j]
        f = fev["samples"][str(off)]
        cost, da, dc, dv, c = edges[(i, j)]
        pairs.append({"fall_session": fsid, "complete_session": csid,
                      "fall_anchor_lower_seq": fev["anchor_lower_seq"], "fall_anchor_upper_seq": fev["anchor_upper_seq"],
                      "fall_asof_seq": f["sequence"], "complete_recovery_label_seq": c["label_seq"],
                      "complete_current_seq": c["sample_seq"], "fall_age_seconds": f["age_seconds"],
                      "future_recovery_delay_seconds": c["future_label_delay_seconds"], "angle_delta_deg": da,
                      "clearance_delta": dc, "radial_velocity_delta": dv, "normalized_additive_cost": cost})
    unmatched_f = [{"session": fs[i][0], "reason": fs[i][1]["sample_rejections"].get(str(off), "no compatible one-to-one edge")} for i in range(len(fs)) if i not in usedf]
    all_f = set(falls) - {sid for sid, _ in fs}
    unmatched_f += [{"session": sid, "reason": falls[sid]["sample_rejections"].get(str(off), "no valid eligible sample")} for sid in sorted(all_f)]
    used_complete_sessions = {complete_ids[j] for j in usedc}
    unmatched_c = [{"session": sid, "reason": "not selected by max-cardinality/min-cost assignment"} for sid in completes if sid not in used_complete_sessions and completes[sid]]
    all_c = {sid for sid in completes if not completes[sid]}
    unmatched_c += [{"session": sid, "reason": "no eligible outward sample following observed recovery label"} for sid in sorted(all_c)]
    return {"offset_seconds": off, "pair_count": len(pairs), "fall_coverage": f"{len(usedf)}/{len(falls)}",
            "completion_coverage": f"{len(usedc)}/{len(completes)}", "pairs": pairs,
            "unmatched_falls": unmatched_f, "unmatched_completions": unmatched_c}


def main():
    sessions = {}
    for p in sorted(ROOT.glob("session_*")):
        if not p.is_dir():
            continue
        rows = load_session(p)
        sessions[p.name] = rows
    falls, completes, excluded = {}, {}, []
    for sid, rows in sessions.items():
        outcomes = {r.get("session_outcome") for r in rows if r.get("session_outcome")}
        terminal_layers = {r.get("platform_level") for r in rows if r.get("source") == "unity" and r.get("session_outcome")}
        outcome = next(iter(outcomes), "")
        if outcome == "edge_exit" and terminal_layers == {"1"}:
            ev = fall_events(rows)
            if ev:
                falls[sid] = ev
        elif outcome == "calibration_completed":
            completes[sid] = completion_events(rows)
        else:
            excluded.append({"session": sid, "outcome": outcome, "terminal_layers": sorted(terminal_layers), "reason": "outside first-layer fall/completion cohorts"})
    result = {"method": {"screen": "raw CSV proxy only; no live display inference", "anchor": "last positive clearance row before consecutive valid running L1 crossing", "clearance": "directional_edge_distance - ball_radius", "angle": "ball center minus platform center", "fall_sampling": "latest same-context outward sample at or before lower anchor minus offset; age <=0.06s", "completion_sampling": "current outward row; future recovery within 1.5s only for cohort eligibility", "recovery": "future inward radial velocity <-0.05m/s continuously >=0.1s, c gain >=0.02m over latest same-context baseline at/before end-0.1s, c>0, all rows consecutive and gaps <=0.1s", "matching_cost": "angle_delta/30 + clearance_delta/0.5 + radial_velocity_delta/0.75; max pair count then minimum sum", "no_model_state_or_sensitivity_recorded": True},
              "fall_sessions": {sid: {"anchor_lower_seq": ev["anchor_lower_seq"], "anchor_upper_seq": ev["anchor_upper_seq"],
                                      "samples": ev["samples"], "sample_rejections": ev["sample_rejections"]} for sid, ev in falls.items()},
              "completion_control_counts": {sid: len(ev) for sid, ev in completes.items()},
              "excluded_sessions": excluded, "offset_results": [best_pairs(falls, completes, o) for o in OFFSETS]}
    print(json.dumps(result, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
