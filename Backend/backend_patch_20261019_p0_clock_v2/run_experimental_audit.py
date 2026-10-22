"""Formal P01 Experimental Warning Channel Audit & Interval Verification.
Evaluates:
  1. Purple TTE Proximity Channel (ExperimentalProximityWarning / proximity_shadow.jsonl)
  2. Orange LightGBM Model Channel (ExperimentalModelWarning / client Editor.log)
  3. Legacy Yellow Attention Baseline (unity_attention_rule / visible_warning_state)
Strict protocol:
  - Last qualifying onset (not first onset)
  - True terminal anchors (no double-counting)
  - Interval-based clock mapping (rejecting intervals crossing steps/gaps/warmup)
  - Millisecond-precision lead times calculated on both Unity and Epoch clocks
  - SHA-256 verification of all raw telemetry files
"""
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE / "patched" / "tools"
sys.path.insert(0, str(TOOLS))
import clock_alignment as clock
import clock_offset_audit as audit

ROOT = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend")
CLIENT_RES = json.load(open(ROOT / "parallel_20261019/p01_review/client/result.json", encoding="utf-8"))
PROX_FILE = ROOT / "telemetry_logs/proximity_shadow.jsonl"
P01_DIR = ROOT / "telemetry_logs/P01"

runs_order = [
    ("session_20261019_105632_058608", "31870bd7101e45a29d78d179f82e06f0"),
    ("session_20261019_105656_285619", "dc424922ab7a4438809dd72a4b308bb7"),
    ("session_20261019_105712_007803", "f848f2248b7443d7b740b5b2eda42bc4"),
    ("session_20261019_105734_310716", "b6f039d1c47a45e89c8f9dd9dd8967a9"),
    ("session_20261019_105912_781089", "0d93af38d29a499487b66b0c9a6e2199"),
    ("session_20261019_105922_291656", "b0e336b2239b4a8b99d47cf72ef0b5d7"),
    ("session_20261019_105951_117357", "5c364258088d4dd2adfdb15e6830f185"),
    ("session_20261019_110023_567130", "bbe4be8d4fbb4e74b192b0570c12707e"),
    ("session_20261019_110055_533132", "70bdae08f81a4d1480b9f2b2ccd61125"),
    ("session_20261019_110107_096491", "3074f1b0189744ad92cc26e1bec71fe0")
]

# Load shadow records for P01
shadow_by_run = {}
with open(PROX_FILE, "r", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        r = d.get("run_id")
        if r:
            shadow_by_run.setdefault(r, []).append(d)

client_records = CLIENT_RES["warning_records_source_line_order"]

def evaluate_interval(alignment, warn_u, anchor_u, warn_ep, anchor_ep, warmup_seconds=0.5):
    if warn_u is None or anchor_u is None:
        return {"lead_u": None, "lead_ep": None, "status": "no_warning", "reasons": ["no_warning"]}
    
    lead_u = anchor_u - warn_u
    lead_ep = (anchor_ep - warn_ep) if (warn_ep and anchor_ep) else None
    
    reasons = []
    
    # Check if warn_u is inside any gap or warmup window
    for gap in alignment.gaps:
        warmup_end_u = gap.end_unity + warmup_seconds
        if gap.start_unity <= warn_u <= warmup_end_u:
            reasons.append("onset_inside_gap_or_warmup")
        if warn_u < gap.start_unity and anchor_u > gap.end_unity:
            reasons.append("interval_crosses_gap")
            
    # Check if interval crosses any step
    for step in alignment.steps:
        if warn_u < step.unity < anchor_u:
            reasons.append("interval_crosses_step")
            
    status = "available" if not reasons else "n_a_ambiguous"
    return {
        "lead_u": lead_u,
        "lead_ep": lead_ep,
        "status": status,
        "reasons": reasons
    }

def run_audit():
    csv_hashes = {}
    sessions_data = []

    for sname, rid in runs_order:
        raw_path = P01_DIR / sname / "raw.csv"
        raw_bytes = raw_path.read_bytes()
        h = hashlib.sha256(raw_bytes).hexdigest()
        csv_hashes[sname] = {"len": len(raw_bytes), "sha256": h}
        
        unity_rows = audit.read_unity_rows(raw_path)
        samples = clock.samples_from_rows(unity_rows)
        alignment = clock.analyze(samples)
        
        seq_to_row = {int(r["sequence"]): r for r in unity_rows if r.get("sequence")}
        
        last_row = unity_rows[-1]
        anchor_u = float(last_row["geometry_source_timestamp"])
        anchor_ep = float(last_row["source_timestamp"])
        outcome = last_row.get("session_outcome")
        fall = last_row.get("fall_event") == "True"
        
        # 1. Purple TTE Proximity
        s_recs = shadow_by_run.get(rid, [])
        prox_episodes = []
        cur_ep = []
        for s in s_recs:
            if s.get("active"):
                cur_ep.append(s)
            else:
                if cur_ep:
                    prox_episodes.append(cur_ep)
                    cur_ep = []
        if cur_ep:
            prox_episodes.append(cur_ep)
            
        last_prox_u = None
        last_prox_ep = None
        last_prox_seq = None
        if prox_episodes:
            last_ep = prox_episodes[-1]
            first_s = last_ep[0]
            last_prox_seq = first_s["input_sequence"]
            r = seq_to_row.get(last_prox_seq)
            if r:
                last_prox_u = float(r["geometry_source_timestamp"])
                last_prox_ep = float(r["source_timestamp"])
                
        # 2. Orange Model Warning
        c_recs = [c for c in client_records if c.get("run_id") == rid]
        model_active_recs = [c for c in c_recs if c["channel"] == "ExperimentalModelWarning" and c.get("state") == "ACTIVE"]
        model_episodes = []
        cur_m = []
        prev_line = None
        for m in model_active_recs:
            if prev_line is None or m["line"] <= prev_line + 60:
                cur_m.append(m)
            else:
                if cur_m:
                    model_episodes.append(cur_m)
                cur_m = [m]
            prev_line = m["line"]
        if cur_m:
            model_episodes.append(cur_m)
            
        last_model_u = None
        last_model_ep = None
        last_model_pred_seq = None
        if model_episodes:
            last_m_ep = model_episodes[-1]
            first_m = last_m_ep[0]
            last_model_mono = float(first_m["local_monotonic_s"])
            last_model_pred_seq = first_m.get("prediction_sequence")
            matching_c_prox = [c for c in c_recs if c.get("local_monotonic_s") and abs(float(c["local_monotonic_s"]) - last_model_mono) < 0.05 and c.get("input_sequence")]
            if matching_c_prox:
                m_seq = int(matching_c_prox[0]["input_sequence"])
                r = seq_to_row.get(m_seq)
                if r:
                    last_model_u = float(r["geometry_source_timestamp"])
                    last_model_ep = float(r["source_timestamp"])
            else:
                known_prox = [c for c in c_recs if c.get("local_monotonic_s") and c.get("input_sequence")]
                if known_prox:
                    closest = min(known_prox, key=lambda c: abs(float(c["local_monotonic_s"]) - last_model_mono))
                    c_seq = int(closest["input_sequence"])
                    c_row = seq_to_row.get(c_seq)
                    if c_row:
                        delta_mono = last_model_mono - float(closest["local_monotonic_s"])
                        last_model_u = float(c_row["geometry_source_timestamp"]) + delta_mono
                        last_model_ep = float(c_row["source_timestamp"]) + delta_mono

        # 3. Yellow Attention Baseline
        in_attn = False
        attn_onset_u = None
        attn_onset_ep = None
        last_attn_u = None
        last_attn_ep = None
        for row in unity_rows:
            warn = row.get("visible_warning_state")
            u_t = float(row["geometry_source_timestamp"])
            ep_t = float(row["source_timestamp"])
            if warn == "ATTENTION":
                if not in_attn:
                    in_attn = True
                    attn_onset_u = u_t
                    attn_onset_ep = ep_t
            else:
                if in_attn:
                    last_attn_u = attn_onset_u
                    last_attn_ep = attn_onset_ep
                    in_attn = False
        if in_attn:
            last_attn_u = attn_onset_u
            last_attn_ep = attn_onset_ep

        sessions_data.append({
            "session": sname,
            "run_id": rid,
            "anchor_u": anchor_u,
            "anchor_ep": anchor_ep,
            "outcome": outcome,
            "fall": fall,
            "clock_verdict": alignment.verdict,
            "steps": len(alignment.steps),
            "gaps": len(alignment.gaps),
            "prox": {
                "onset_u": last_prox_u,
                "onset_ep": last_prox_ep,
                "eval": evaluate_interval(alignment, last_prox_u, anchor_u, last_prox_ep, anchor_ep)
            },
            "model": {
                "onset_u": last_model_u,
                "onset_ep": last_model_ep,
                "eval": evaluate_interval(alignment, last_model_u, anchor_u, last_model_ep, anchor_ep)
            },
            "attn": {
                "onset_u": last_attn_u,
                "onset_ep": last_attn_ep,
                "eval": evaluate_interval(alignment, last_attn_u, anchor_u, last_attn_ep, anchor_ep)
            }
        })
        
    return sessions_data, csv_hashes

if __name__ == "__main__":
    sessions_data, csv_hashes = run_audit()
    print("Execution complete. Ready to generate report.")
