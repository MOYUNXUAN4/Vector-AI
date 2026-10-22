"""Extract real events from all 10 P01 sessions and evaluate them with the v2 clock alignment patch."""
import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE / "patched" / "tools"
sys.path.insert(0, str(TOOLS))
import clock_alignment as clock
import clock_offset_audit as audit

P01_DIR = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs\P01")

def run():
    sessions = sorted(P01_DIR.glob("session_*"))
    print(f"==========================================================================================")
    print(f" P01 Full Real-Session Alignment & Event Verification Report (10 Sessions)")
    print(f"==========================================================================================\n")
    
    total_events = 0
    total_lead_available = 0
    total_na_ambiguous = 0

    results = []

    for s in sessions:
        raw_csv = s / "raw.csv"
        if not raw_csv.exists():
            continue
        
        # 1. Read Unity rows and analyze clock alignment
        unity_rows = audit.read_unity_rows(raw_csv)
        samples = clock.samples_from_rows(unity_rows)
        if not samples:
            continue
        alignment = clock.analyze(samples)

        # 2. Extract key real events from raw CSV:
        # - Warning onset
        # - Fall event (if any)
        # - Calibration completion / Outcome
        session_events = []
        with raw_csv.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            warn_first = None
            fall_ev = None
            outcome_ev = None
            for idx, row in enumerate(reader, start=2):
                if row.get("source") != "unity":
                    continue
                ts_unity = row.get("geometry_source_timestamp")
                if not ts_unity:
                    continue
                try:
                    u_time = float(ts_unity)
                except ValueError:
                    continue

                warn = row.get("visible_warning_state") or row.get("warning_active") or row.get("attention_state")
                if warn and warn not in ("", "0", "none", "False", "UNKNOWN", "SAFE") and warn_first is None:
                    warn_first = {"event_id": f"{s.name[-6:]}_WARN_ONSET", "unity_time": str(u_time), "type": "Warning Onset", "detail": warn}

                if row.get("fall_event") in ("True", "true", "1") and fall_ev is None:
                    fall_ev = {"event_id": f"{s.name[-6:]}_FALL", "unity_time": str(u_time), "type": "Edge Fall", "detail": row.get("fall_reason", "fall")}

                if row.get("session_outcome") and outcome_ev is None:
                    outcome_ev = {"event_id": f"{s.name[-6:]}_OUTCOME", "unity_time": str(u_time), "type": "Session Outcome", "detail": row.get("session_outcome")}

        for ev in [warn_first, fall_ev, outcome_ev]:
            if ev:
                session_events.append(ev)

        # 3. Map events using v2 segment-based alignment
        mapped_session_events = []
        for ev in session_events:
            total_events += 1
            res = audit.map_event(alignment, ev, warmup_seconds=0.5)
            coverage_status = "n_a_ambiguous" if res["ambiguous"] else "lead_available"
            if coverage_status == "lead_available":
                total_lead_available += 1
            else:
                total_na_ambiguous += 1
            mapped_session_events.append({**ev, **res, "coverage_status": coverage_status})

        results.append({
            "session": s.name,
            "run_id": alignment.run_id[:8],
            "verdict": alignment.verdict,
            "offset_range": alignment.offset_range_seconds,
            "drift": alignment.max_segment_drift_seconds,
            "steps": len(alignment.steps),
            "gaps": len(alignment.gaps),
            "events": mapped_session_events
        })

    # Print summary table
    print(f"{'Session':<32} {'Verdict':<9} {'OffsetSpan':<11} {'Drift':<8} {'Steps':<6} {'Events Mapped'}")
    print("-" * 86)
    for r in results:
        print(f"{r['session']:<32} {r['verdict']:<9} {r['offset_range']:<11.3f} {r['drift']:<8.3f} {r['steps']:<6} {len(r['events'])} events")
        for ev in r["events"]:
            mapped_ep_str = "None" if math.isnan(ev['mapped_epoch']) else f"{ev['mapped_epoch']:.3f}"
            status_tag = "[OK: LEAD AVAIL]" if ev['coverage_status'] == 'lead_available' else f"[N/A: {ev['reasons'][0]}]"
            print(f"  -> {ev['event_id']:<24} {ev['type']:<16} Unity={float(ev['unity_time']):<7.2f} Epoch={mapped_ep_str:<15} {status_tag}")
        print()

    print(f"==========================================================================================")
    print(f" SUMMARY STATS:")
    print(f" Total Real Events Tested: {total_events}")
    print(f" Lead Available (Clean)   : {total_lead_available} ({total_lead_available/max(1, total_events)*100:.1f}%)")
    print(f" N/A Ambiguous (Protected): {total_na_ambiguous} ({total_na_ambiguous/max(1, total_events)*100:.1f}%)")
    print(f"==========================================================================================\n")

if __name__ == "__main__":
    run()
