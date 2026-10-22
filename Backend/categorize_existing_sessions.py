"""Add analysis roles to existing session metadata without changing raw data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def classify(condition: str, status: str, positive_windows: int) -> tuple[str, str, str]:
    if status == "excluded" or condition in {"tare_failed", "interrupted"}:
        return "invalid_excluded", "exclude", "Do not use for model training or feature comparison."
    if condition == "physical_off_board":
        return "physical_off_board", "normal_only", "Retain earlier valid normal windows only; do not treat as game edge-exit positives."
    if condition == "normal_control":
        return "normal_control", "control", "Use as ordinary successful-control data."
    if condition in {
        "directional_edge_exit", "direct_edge_exit", "turning_edge_exit",
        "directional_instability_then_edge_exit",
    }:
        return "directional_edge_exit", "positive", "Use as game edge-exit data; retain the recorded direction and subcondition."
    if condition in {
        "front_back_sway_then_edge_exit", "left_right_sway_then_edge_exit",
    }:
        return "sway_then_edge_exit", "positive", "Use as dynamic-sway-to-edge-exit data; keep separate from smooth directional exits."
    if condition in {
        "intense_sway", "intense_sway_with_off_board", "high_frequency_small_sway",
        "mixed_sway", "multidirectional_intense_sway",
    }:
        role = "positive" if positive_windows else "negative_dynamic"
        return "dynamic_sway", role, "Use to study dynamic sway; do not merge with directional edge-exit behavior."
    return "unclassified", "review", "Review manually before using in model development."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("telemetry_root", type=Path)
    args = parser.parse_args()
    for user_dir in args.telemetry_root.iterdir():
        if not user_dir.is_dir():
            continue
        for folder in sorted(user_dir.glob("session_*")):
            meta_path = folder / "session_metadata.json"
            quality_path = folder / "quality.json"
            if not quality_path.exists():
                continue
            metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            condition = metadata.get("condition", quality.get("condition", "unknown"))
            status = quality.get("analysis_status", metadata.get("analysis_status", "unknown"))
            positive_windows = int(quality.get("positive_windows", 0))
            group, role, use_note = classify(condition, status, positive_windows)
            additions = {
                "analysis_group": group,
                "data_role": role,
                "data_use_note": use_note,
            }
            metadata.update(additions)
            quality.update(additions)
            if meta_path.exists():
                meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
            print(f"{folder.name}: {group} / {role}")


if __name__ == "__main__":
    main()
