"""Regression tests for the five review findings (clock alignment v2)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from clock_alignment import (Sample, analyze, group_by_run,  # noqa: E402
                             samples_from_rows)
import clock_offset_audit as audit  # noqa: E402


def series(count=100, *, base_offset=990.0, step_at=None, step=0.0,
           gap_at=None, gap=0.0, drift_per_row=0.0, run="r1"):
    samples = []
    for index in range(count):
        unity = 10.0 + index * 0.02
        if gap_at is not None and index >= gap_at:
            unity += gap
        offset = base_offset + drift_per_row * index
        if step_at is not None and index >= step_at:
            offset += step
        samples.append(Sample(index + 2, run, unity + offset, unity))
    return samples


class FindingOneGapTests(unittest.TestCase):
    def test_gap_without_offset_step_is_not_clean(self):
        alignment = analyze(series(gap_at=50, gap=0.5))
        self.assertEqual(alignment.verdict, "GAPPED")
        self.assertEqual(len(alignment.steps), 0)
        self.assertEqual(len(alignment.gaps), 1)

    def test_inside_gap_is_ambiguous(self):
        samples = series(gap_at=50, gap=0.5)
        alignment = analyze(samples)
        inside = samples[49].unity + 0.25
        mapping = alignment.to_epoch(inside)
        self.assertTrue(mapping.ambiguous)
        self.assertIn("in_gap", mapping.reasons)


class FindingTwoDriftTests(unittest.TestCase):
    def test_slow_drift_is_not_clean(self):
        alignment = analyze(series(count=101, drift_per_row=0.001))
        self.assertAlmostEqual(alignment.offset_range_seconds, 0.1, places=6)
        self.assertEqual(alignment.verdict, "DRIFTED")
        self.assertEqual(len(alignment.steps), 0)

    def test_drifting_segment_mapping_is_ambiguous(self):
        alignment = analyze(series(count=101, drift_per_row=0.001))
        mapping = alignment.to_epoch(11.0)
        self.assertTrue(mapping.ambiguous)
        self.assertIn("drifting_segment", mapping.reasons)

    def test_small_noise_stays_clean(self):
        alignment = analyze(series(count=50, drift_per_row=0.00005))
        self.assertEqual(alignment.verdict, "CLEAN")


class FindingThreeEpochInputTests(unittest.TestCase):
    def test_epoch_input_keeps_epoch_output(self):
        alignment = analyze(series())
        event = {"event_id": "E1", "epoch_time": "1005.0"}
        mapped = audit.map_event(alignment, event)
        self.assertAlmostEqual(mapped["mapped_epoch"], 1005.0, places=6)
        self.assertAlmostEqual(mapped["mapped_unity"], 15.0, places=6)

    def test_unity_input_keeps_unity_output(self):
        alignment = analyze(series())
        event = {"event_id": "E2", "unity_time": "15.0"}
        mapped = audit.map_event(alignment, event)
        self.assertAlmostEqual(mapped["mapped_unity"], 15.0, places=6)
        self.assertAlmostEqual(mapped["mapped_epoch"], 1005.0, places=6)


class FindingFourIdentityTests(unittest.TestCase):
    def test_physical_line_and_run_are_kept(self):
        rows = [{"source_timestamp": "1000.0", "geometry_source_timestamp": "10.0",
                 "__csv_line__": 42, "run_id": "run-A"},
                {"source_timestamp": "1000.02", "geometry_source_timestamp": "10.02",
                 "__csv_line__": 43, "run_id": "run-A"}]
        samples = samples_from_rows(rows)
        self.assertEqual([s.csv_line for s in samples], [42, 43])
        self.assertEqual({s.run_id for s in samples}, {"run-A"})

    def test_mixed_runs_are_rejected(self):
        samples = series(10, run="A") + series(10, run="B")
        with self.assertRaises(ValueError):
            analyze(samples)

    def test_group_by_run_keeps_identity(self):
        groups = group_by_run(series(5, run="A") + series(7, run="B"))
        self.assertEqual(sorted(groups), ["A", "B"])
        self.assertEqual(len(groups["B"]), 7)


class FindingFiveIntervalTests(unittest.TestCase):
    def test_interval_crossing_step_is_ambiguous(self):
        samples = series(step_at=50, step=0.16)
        alignment = analyze(samples)
        result = alignment.map_interval(samples[49].unity + 0.01, samples[51].unity - 0.01)
        self.assertTrue(result.ambiguous)
        self.assertIn("interval_crosses_step", result.reasons)

    def test_interval_crossing_gap_is_ambiguous(self):
        samples = series(gap_at=50, gap=0.5)
        alignment = analyze(samples)
        result = alignment.map_interval(samples[49].unity + 0.01, samples[51].unity - 0.01)
        self.assertTrue(result.ambiguous)
        self.assertIn("interval_crosses_gap", result.reasons)

    def test_interval_inside_stable_segment_is_ok(self):
        samples = series()
        alignment = analyze(samples)
        result = alignment.map_interval(samples[10].unity, samples[20].unity)
        self.assertFalse(result.ambiguous)


class MapEventsTests(unittest.TestCase):
    def test_events_csv_has_both_clocks(self):
        alignment = analyze(series())
        event = {"event_id": "E", "unity_time": "15.0"}
        mapped = audit.map_event(alignment, event)
        self.assertIn("mapped_epoch", mapped)
        self.assertIn("mapped_unity", mapped)
        self.assertFalse(math.isnan(mapped["mapped_epoch"]))
        self.assertFalse(math.isnan(mapped["mapped_unity"]))


if __name__ == "__main__":
    unittest.main()
