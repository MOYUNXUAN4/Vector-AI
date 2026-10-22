"""Mark sessions for downstream analysis without deleting raw data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXCLUDED = {
    "session_20260914_134356_482524": "excluded: Unity sampling dropped to about 30 Hz; alignment was 50%; no positive windows were produced for the recorded fall",
    "session_20260915_094627_896684": "excluded: alignment rate was below the 90% pilot quality threshold (89.8%)",
    "session_20260915_095045_370341": "excluded: incomplete session; no valid Wii samples and no analysis windows",
}


def mark(user_dir: Path) -> None:
    for session_dir in sorted(user_dir.glob("session_*")):
        quality = session_dir / "quality.json"
        if not quality.exists():
            continue
        data = json.loads(quality.read_text(encoding="utf-8"))
        name = session_dir.name
        if name in EXCLUDED:
            data["analysis_status"] = "excluded"
            data["analysis_status_reason"] = EXCLUDED[name]
        elif data.get("off_board_before_game_fall"):
            data["analysis_status"] = "included_normal_only"
            data["analysis_status_reason"] = (
                "physical off-board transition occurred before the Unity edge-exit; "
                "retain earlier normal windows only"
            )
        else:
            data["analysis_status"] = "included"
            data["analysis_status_reason"] = "passed current pilot quality review"
        data["window_label_definition"] = "failure_label=1 means a Unity fall_event occurs within 2 seconds after window_end; failure_label=0 means no such event"
        quality.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"{name}: {data['analysis_status']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_dir", type=Path)
    args = parser.parse_args()
    mark(args.user_dir)


if __name__ == "__main__":
    main()
