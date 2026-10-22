"""Synthetic parity tests against the reviewed offline feature_rows helper."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from causal_features import FEATURE_NAMES, compute_latest_features


ROOT = Path(__file__).resolve().parents[2]
OFFLINE = ROOT / "telemetry_logs" / "Test10052" / "model_comparison_20261005" / "prepare_features.py"
SPEC = importlib.util.spec_from_file_location("reviewed_offline_features", OFFLINE)
OFFLINE_HELPER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(OFFLINE_HELPER)  # import definitions only; never invoke main()


def make_samples(kind="outward", times=None):
    times = np.asarray(times if times is not None else np.arange(17) * .05, dtype=float)
    rows = []
    for i, relative_t in enumerate(times):
        if kind == "accelerating":
            velocity = .1 + .4 * relative_t
        elif kind == "inward":
            velocity = -.2 - .1 * relative_t
        elif kind == "zero_speed":
            velocity = 0.0
        else:
            velocity = .08 + .03 * np.sin(relative_t * 4)
        angle = .2 + relative_t
        speed = 0.0 if kind == "zero_speed" else .3 + .1 * np.cos(relative_t)
        rows.append({
            "source_timestamp": 1_700_000_000.0 + relative_t,
            "directional_edge_distance": .8 - .03 * relative_t,
            "ball_radial_velocity": velocity,
            "ball_velocity_x": speed * np.cos(angle),
            "ball_velocity_z": speed * np.sin(angle),
            "ball_pos_x": .3 + .01 * relative_t, "ball_pos_z": .4,
            "platform_center_x": 0.0, "platform_center_z": 0.0,
            "ball_radius": .1, "platform_radius": 1.25,
            "platform_tilt": .02 + relative_t / 10, "difficulty": 2.0,
        })
    return rows


def compare_with_reviewed(rows):
    frame = pd.DataFrame(rows)
    frame["run_state"] = "running"
    frame["platform_level"] = 2
    frame["sequence"] = np.arange(len(frame)) + 1
    frame["_csv_row"] = np.arange(len(frame)) + 2
    session = SimpleNamespace(session_id="synthetic", run_id="run", fall_event_unix_seconds=np.nan,
                              observation_group="test")
    segment = SimpleNamespace(segment_id="synthetic:1", layer=2,
                              start_source_timestamp=float(frame.source_timestamp.iloc[0]),
                              end_source_timestamp=float(frame.source_timestamp.iloc[-1]))
    offline = OFFLINE_HELPER.feature_rows(frame, session, segment)
    if not offline:
        raise AssertionError("expected the reviewed generator to produce a decision")
    expected = offline[-1]
    # Its 50 ms scheduler can skip a nominal sample when epoch-second float
    # rounding makes the interval infinitesimally short. Compare at its actual
    # last emitted decision time, using only that causal prefix.
    prefix = [row for row in rows if row["source_timestamp"] <= expected["timestamp"]]
    online = compute_latest_features(prefix)
    if not online["ready"]:
        raise AssertionError(f"expected a ready online vector: {online}")
    np.testing.assert_allclose([online[name] for name in FEATURE_NAMES],
                               [expected[name] for name in FEATURE_NAMES],
                               rtol=0, atol=2e-10, equal_nan=True)
    return online, expected


class CausalFeatureParityTests(unittest.TestCase):
    def test_exact_24_names_and_order(self):
        self.assertEqual(len(FEATURE_NAMES), 24)
        self.assertEqual(list(compare_with_reviewed(make_samples())[0].keys())[:24], list(FEATURE_NAMES))

    def test_outward_vector(self):
        compare_with_reviewed(make_samples("outward"))

    def test_accelerating_outward(self):
        compare_with_reviewed(make_samples("accelerating"))

    def test_inward(self):
        compare_with_reviewed(make_samples("inward"))

    def test_irregular_timestamps(self):
        compare_with_reviewed(make_samples(times=[0, .047, .101, .151, .204, .256, .307,
                                                   .357, .408, .459, .509, .56, .611, .662,
                                                   .713, .764, .815]))

    def test_zero_speed_alignment_is_nan(self):
        online, _ = compare_with_reviewed(make_samples("zero_speed"))
        self.assertTrue(np.isnan(online["velocity_vector_consistency"]))
        self.assertTrue(np.isnan(online["mean_velocity_alignment_current_radial"]))

    def test_missing_optional_components_preserve_nansum_semantics(self):
        rows = make_samples()
        rows[3]["ball_velocity_x"] = np.nan
        rows[5].pop("ball_velocity_z")
        compare_with_reviewed(rows)

    def test_window_predecessor_contributes_to_acceleration_at_lo(self):
        rows = make_samples("accelerating")
        online, expected = compare_with_reviewed(rows)
        # At the lower window boundary the derivative uses the preceding sample.
        self.assertAlmostEqual(online["acceleration_mean_0_5s"], expected["acceleration_mean_0_5s"], places=10)
        self.assertTrue(np.isfinite(online["acceleration_mean_0_5s"]))

    def test_future_perturbation_does_not_change_prefix(self):
        rows = make_samples("accelerating")
        cutoff_count = 13
        before = compute_latest_features(rows[:cutoff_count])
        changed = [dict(row) for row in rows]
        for row in changed[cutoff_count:]:
            row["directional_edge_distance"] = 1000
            row["ball_radial_velocity"] = -200
            row["ball_velocity_x"] = 300
        after = compute_latest_features(changed[:cutoff_count])
        np.testing.assert_allclose([before[k] for k in FEATURE_NAMES], [after[k] for k in FEATURE_NAMES],
                                   rtol=0, atol=0, equal_nan=True)

    def test_duplicate_timestamp_not_ready(self):
        rows = make_samples()
        rows[5]["source_timestamp"] = rows[4]["source_timestamp"]
        result = compute_latest_features(rows)
        self.assertFalse(result["ready"])
        self.assertEqual(result["not_ready_reason"], "timestamps_not_strictly_increasing")

    def test_large_gap_not_ready(self):
        rows = make_samples()
        rows[7]["source_timestamp"] += .2
        for row in rows[8:]:
            row["source_timestamp"] += .2
        result = compute_latest_features(rows)
        self.assertFalse(result["ready"])
        self.assertEqual(result["not_ready_reason"], "segment_gap_exceeds_0_1s")

    def test_required_distance_missing_not_ready(self):
        rows = make_samples()
        rows[-2]["directional_edge_distance"] = np.nan
        result = compute_latest_features(rows)
        self.assertFalse(result["ready"])
        self.assertIn("required_directional_edge_distance", result["not_ready_reason"])

    def test_insufficient_history_not_ready(self):
        result = compute_latest_features(make_samples()[:8])
        self.assertFalse(result["ready"])
        self.assertEqual(result["not_ready_reason"], "insufficient_0_5s_history")


if __name__ == "__main__":
    unittest.main()
