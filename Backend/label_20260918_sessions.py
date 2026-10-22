"""Attach the participant's 2026-09-18 test notes to session metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


LABELS = {
    "session_20260918_095113_828353": ("normal_control", "none", "included", "completed normally"),
    "session_20260918_095739_812897": ("normal_control", "none", "included", "completed normally"),
    "session_20260918_095635_799810": ("tare_failed", "unknown", "excluded", "tare/leveling failed; session invalid"),
    "session_20260918_100153_732792": ("normal_control", "none", "included", "completed normally"),
    "session_20260918_100557_465677": ("normal_control", "none", "included", "completed normally"),
    "session_20260918_100845_210572": ("interrupted", "unknown", "excluded", "test was interrupted"),
    "session_20260918_101046_935089": ("normal_control", "none", "included", "completed normally"),
    "session_20260918_101342_151604": ("directional_instability_then_edge_exit", "back", "included", "backward instability at level 9; edge exit after level 10"),
    "session_20260918_101601_887973": ("directional_edge_exit", "back", "included", "backward edge exit after level 20"),
    "session_20260918_101858_518541": ("direct_edge_exit", "front", "included", "direct forward edge exit"),
    "session_20260918_102211_724346": ("turning_edge_exit", "left", "included", "left-turn edge exit at level 21"),
    "session_20260918_102430_356719": ("directional_instability_then_edge_exit", "right", "included", "rightward instability at level 9"),
    "session_20260918_102749_395333": ("front_back_sway_then_edge_exit", "front", "included", "two strong front-back sways followed by forward edge exit"),
    "session_20260918_102935_142513": ("left_right_sway_then_edge_exit", "front", "included", "two strong left-right sways followed by forward edge exit"),
    "session_20260918_103133_774821": ("multidirectional_intense_sway", "unknown", "included", "several strong multidirectional sways"),
    "session_20260918_103459_610023": ("high_frequency_small_sway", "unknown", "included", "high-frequency small-range sway"),
    "session_20260918_104437_682562": ("mixed_sway", "unknown", "included", "mixed sway pattern"),
    "session_20260918_110023_541600": ("directional_instability_then_edge_exit", "left", "included", "leftward instability"),
    "session_20260918_110317_316897": ("physical_off_board", "front_right", "included_normal_only", "lost balance and left board toward front-right"),
    "session_20260918_110951_845302": ("physical_off_board", "back", "included_normal_only", "backward instability followed by leaving the board"),
    "session_20260918_111158_874400": ("physical_off_board", "front", "included_normal_only", "forward instability followed by leaving the board"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_dir", type=Path)
    args = parser.parse_args()
    for session_id, (condition, direction, status, note) in LABELS.items():
        folder = args.user_dir / session_id
        quality_path = folder / "quality.json"
        if not quality_path.exists():
            raise FileNotFoundError(quality_path)
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        metadata = {
            "session_id": session_id,
            "condition": condition,
            "fall_direction": direction,
            "analysis_status": status,
            "participant_note": note,
            "condition_source": "participant_recorded_immediately_after_testing",
            "physical_off_board": condition == "physical_off_board",
            "event_interpretation": "fall_event is a Unity game-edge-exit event; physical_off_board is a separate sensor event",
        }
        quality.update(metadata)
        quality["analysis_status_reason"] = note
        quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
        (folder / "session_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"{session_id}: {status} / {condition} / {direction}")


if __name__ == "__main__":
    main()
