"""Move legacy flat session CSVs into per-session folders.

This script is opt-in and never overwrites an existing destination.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def organize(user_dir: Path, dry_run: bool = False) -> list[tuple[Path, Path]]:
    moves = []
    for source in sorted(user_dir.glob("session_*.csv")):
        if source.name == "raw.csv" or source.name.endswith((".clean.csv", ".aligned_60hz.csv", ".windows.csv")):
            continue
        session_dir = user_dir / source.stem
        target = session_dir / "raw.csv"
        if target.exists():
            raise FileExistsError(f"Destination already exists: {target}")
        moves.append((source, target))
        if not dry_run:
            session_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
    return moves


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_dir", type=Path, help="telemetry_logs/<username>")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    moves = organize(args.user_dir, args.dry_run)
    for source, target in moves:
        print(f"{source} -> {target}")
    print(f"{'Would move' if args.dry_run else 'Moved'} {len(moves)} file(s).")


if __name__ == "__main__":
    main()
