"""Attach participant-recorded conditions to the 2026-09-18 918test sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


LABELS = {
    "session_20260918_134858_656691": ("accidental_edge_exit", "directional_edge_exit", "right", "positive", "normal play; unintentionally exited from the right edge"),
    "session_20260918_135114_950747": ("normal_control", "normal_control", "none", "control", "normal play and successful completion"),
    "session_20260918_135352_308873": ("normal_control", "normal_control", "none", "control", "normal play and successful completion"),
    "session_20260918_135628_154337": ("sway_no_exit", "dynamic_sway", "unknown", "negative_dynamic", "successful completion with repeated sway near one of the final two levels"),
    "session_20260918_135951_036780": ("recoverable_directional_shift", "recoverable_directional_shift", "front", "hard_negative", "repeatedly approached the front edge and completed successfully"),
    "session_20260918_140356_112281": ("recoverable_directional_shift", "recoverable_directional_shift", "front", "hard_negative", "repeatedly approached the front edge and completed successfully"),
    "session_20260918_140711_901851": ("recoverable_directional_shift", "recoverable_directional_shift", "right", "hard_negative", "repeatedly approached the right edge and completed successfully"),
    "session_20260918_141040_477432": ("recoverable_directional_shift", "recoverable_directional_shift", "left", "hard_negative", "repeatedly approached the left edge and completed successfully"),
    "session_20260918_141335_853578": ("recoverable_directional_shift", "recoverable_directional_shift", "right", "hard_negative", "repeatedly approached the right edge and completed successfully"),
    "session_20260918_141629_337259": ("recoverable_directional_shift", "recoverable_directional_shift", "left", "hard_negative", "repeatedly approached the left edge and completed successfully"),
    "session_20260918_142201_071338": ("recoverable_directional_shift", "recoverable_directional_shift", "back", "hard_negative", "repeatedly leaned toward the back edge and completed successfully"),
    "session_20260918_142722_869388": ("recoverable_directional_shift", "recoverable_directional_shift", "back", "hard_negative", "repeatedly leaned toward the back edge and completed successfully"),
    "session_20260918_142021_053952": ("direct_edge_exit", "directional_edge_exit", "back", "normal_only", "direct back edge exit; no valid positive window because sensor samples were invalid immediately before the event"),
    "session_20260918_142533_495493": ("repeated_approach_then_edge_exit", "directional_edge_exit", "back", "positive", "approached the back edge several times and then exited backward"),
    "session_20260918_143230_207094": ("direct_edge_exit", "directional_edge_exit", "front", "positive", "direct front edge exit"),
    "session_20260918_143359_529760": ("normal_play_then_edge_exit", "directional_edge_exit", "front", "positive", "normal play followed by a direct front edge exit"),
    "session_20260918_143549_176682": ("normal_play_then_edge_exit", "directional_edge_exit", "right", "positive", "normal play followed by a direct right edge exit"),
    "session_20260918_143736_236721": ("normal_play_then_edge_exit", "directional_edge_exit", "right", "positive", "normal play followed by a direct right edge exit"),
    "session_20260918_143918_673323": ("normal_play_then_edge_exit", "directional_edge_exit", "left", "positive", "normal play followed by a direct left edge exit"),
    "session_20260918_144134_389931": ("normal_play_then_edge_exit", "directional_edge_exit", "left", "positive", "normal play followed by a direct left edge exit"),
    "session_20260918_144349_142400": ("sway_then_edge_exit", "sway_then_edge_exit", "unknown", "positive", "strong sway followed by a game edge exit; sway amplitude/frequency subtype not recorded"),
    "session_20260918_144754_446543": ("sway_no_exit", "dynamic_sway", "unknown", "negative_dynamic", "strong sway followed by successful completion; sway amplitude/frequency subtype not recorded"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_dir", type=Path)
    args = parser.parse_args()
    for sid, (condition, group, direction, role, note) in LABELS.items():
        folder = args.user_dir / sid
        qpath = folder / "quality.json"
        if not qpath.exists():
            raise FileNotFoundError(qpath)
        quality = json.loads(qpath.read_text(encoding="utf-8"))
        status = "included_normal_only" if role == "normal_only" else "included"
        metadata = {
            "session_id": sid,
            "participant_id": "QIYUXUAN",
            "source_username": "918test",
            "condition": condition,
            "analysis_group": group,
            "fall_direction": direction,
            "data_role": role,
            "analysis_status": status,
            "participant_note": note,
            "condition_source": "participant_recorded_immediately_after_testing",
            "sway_subtype": "amplitude_and_frequency_unknown" if "sway" in condition else "not_applicable",
            "physical_off_board": False,
            "event_interpretation": "fall_event is a Unity game-edge-exit event, not a clinical or physical fall label",
        }
        quality.update(metadata)
        quality["analysis_status_reason"] = note
        quality["data_use_note"] = (
            "Retain label-0 windows only; do not use this session as a pre-edge-exit positive example."
            if role == "normal_only" else
            "Use in the recorded experimental group; preserve condition and direction during analysis."
        )
        qpath.write_text(json.dumps(quality, indent=2), encoding="utf-8")
        (folder / "session_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"{sid}: {group} / {direction} / {role} / events={quality.get('fall_events')} / positives={quality.get('positive_windows')}")


if __name__ == "__main__":
    main()
