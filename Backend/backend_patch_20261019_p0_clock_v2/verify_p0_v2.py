"""Verification for the v2 clock patch: 14 regression tests + one real run."""
import argparse
import csv
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE / "patched" / "tools"
TESTS = HERE / "patched" / "tests"
sys.path.insert(0, str(TOOLS))
from clock_alignment import analyze, samples_from_rows  # noqa: E402


def run_tests():
    suite = unittest.defaultTestLoader.discover(str(TESTS))
    return unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()


def audit(csv_path):
    with Path(csv_path).open(newline="", encoding="utf-8-sig", errors="replace") as stream:
        reader = csv.DictReader(stream)
        rows = []
        for row in reader:
            if (row.get("source") or "").strip().lower() != "unity":
                continue
            row["__csv_line__"] = reader.line_num
            rows.append(row)
    alignment = analyze(samples_from_rows(rows))
    print(f"run={alignment.run_id} verdict={alignment.verdict} "
          f"range={alignment.offset_range_seconds:.3f}s "
          f"drift={alignment.max_segment_drift_seconds:.3f}s "
          f"steps={len(alignment.steps)} gaps={len(alignment.gaps)}")
    return alignment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv")
    args = parser.parse_args()
    if not run_tests():
        return 1
    if args.csv:
        alignment = audit(args.csv)
        if alignment.verdict == "NO_GEOMETRY":
            print("real run has no geometry timestamps")
            return 1
    print("P0 V2 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
