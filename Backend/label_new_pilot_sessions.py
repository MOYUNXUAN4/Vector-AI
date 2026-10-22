"""Attach human-recorded conditions to the six 2026-09-15 pilot sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


LABELS = {
    "session_20260915_134949_192149": {
        "condition": "intense_sway",
        "fall_direction": "not_recorded",
        "condition_source": "reconstructed_from_test_order_and_telemetry",
    },
    "session_20260915_135050_598824": {
        "condition": "intense_sway_with_off_board",
        "fall_direction": "not_recorded",
        "condition_source": "reconstructed_from_test_order_and_telemetry",
    },
    "session_20260915_135241_064470": {
        "condition": "directional_edge_exit",
        "fall_direction": "left",
        "condition_source": "participant_recalled_order",
    },
    "session_20260915_135411_727081": {
        "condition": "directional_edge_exit",
        "fall_direction": "right",
        "condition_source": "participant_recalled_order",
    },
    "session_20260915_135521_651603": {
        "condition": "directional_edge_exit",
        "fall_direction": "front",
        "condition_source": "participant_recalled_order",
    },
    "session_20260915_135741_871091": {
        "condition": "directional_edge_exit",
        "fall_direction": "back",
        "condition_source": "participant_recalled_order",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_dir", type=Path)
    args = parser.parse_args()
    for session_id, metadata in LABELS.items():
        folder = args.user_dir / session_id
        quality_path = folder / "quality.json"
        if not quality_path.exists():
            raise FileNotFoundError(quality_path)
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        quality.update(metadata)
        quality["event_interpretation"] = "fall_event is a Unity game-edge-exit event, not a clinical or physical fall label"
        if session_id == "session_20260915_135050_598824":
            quality["analysis_status"] = "included_normal_only"
            quality["analysis_status_reason"] = (
                "physical off-board transition occurred about 2 seconds before the Unity edge-exit; "
                "retain earlier normal windows but do not use as a standard pre-edge-exit positive example"
            )
            quality["off_board_before_game_fall"] = True
        else:
            quality["analysis_status"] = "included"
            quality["analysis_status_reason"] = "passed current pilot quality review"
            quality["off_board_before_game_fall"] = False
        quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
        (folder / "session_metadata.json").write_text(
            json.dumps({"session_id": session_id, **metadata}, indent=2), encoding="utf-8"
        )
        print(f"{session_id}: {metadata['condition']} / {metadata['fall_direction']} / {quality['analysis_status']}")


if __name__ == "__main__":
    main()
