import ast
import math
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from alarm_policy import StrongAlarmPolicy, compute_recovery


def reviewed_policy_functions():
    """Load only reviewed policy helpers, avoiding unrelated optional packages."""
    path = HERE.parents[1] / "telemetry_logs" / "offline_comparison_20261008" / "comparison" / "run_comparison.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = {"finite_float", "truth", "val", "feature_identity", "apply_lgb_policy",
              "recovery_at", "cancel_predictions"}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    ns = {"np": __import__("numpy"), "pd": __import__("pandas"), "math": math,
          "MAX_GAP": .1, "POLICIES": {"strong": {"threshold": .8}}, "truth": None}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), ns)
    from types import SimpleNamespace
    return SimpleNamespace(**{name: ns[name] for name in wanted})


def reviewed_recovery_function():
    """Extract only the reviewed pure recovery function; never import prepare.py."""
    path = HERE.parents[1] / "telemetry_logs" / "TEST1009" / "training_20261009" / "prepare.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "add_recovery_flags"]
    ns = {"np": __import__("numpy"), "pd": __import__("pandas"), "MAX_GAP": .1}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), ns)
    return ns["add_recovery_flags"]


class StrongAlarmTests(unittest.TestCase):
    def setUp(self):
        self.policy = StrongAlarmPolicy(0.8)
        self.ctx = ("run-a", "platform-a", "layer-1", "v1", "segment-a")

    def step(self, p, c=1, t=0, **kwargs):
        return self.policy.step(p, c, t, self.ctx, **kwargs)

    def test_explicit_threshold_required_and_validated(self):
        for value in (None, float("nan"), -0.1, 1.1):
            with self.assertRaises((ValueError, TypeError)):
                StrongAlarmPolicy(value)

    def test_two_consecutive_threshold_boundary_points_confirm(self):
        self.assertFalse(self.step(0.8, t=1)["confirmed"])
        result = self.step(0.8, t=1.1)
        self.assertEqual((result["state"], result["raw"], result["confirmed"], result["active"]),
                         ("STRONG", True, True, True))

    def test_gap_boundary_inclusive_and_over_boundary_restarts_confirmation(self):
        self.step(.9, t=1)
        self.assertTrue(self.step(.9, t=1.1 + 5e-10)["confirmed"])
        self.policy.reset()
        self.step(.9, t=1)
        self.assertFalse(self.step(.9, t=1.100000002)["confirmed"])
        self.assertTrue(self.step(.9, t=1.2)["confirmed"])

    def test_probability_off_clears_immediately_without_hysteresis(self):
        self.step(.9, t=1); self.assertTrue(self.step(.9, t=1.05)["active"])
        result = self.step(.79, t=1.1)
        self.assertEqual((result["state"], result["active"]), ("SAFE", False))

    def test_nonpositive_clearance_is_off_and_invalid_finite_inputs_unknown(self):
        self.step(.9, t=1)
        self.assertFalse(self.step(.9, c=0, t=1.05)["raw"])
        for p, c, t in ((float("nan"), 1, 1.1), (.9, float("inf"), 1.1), (.9, 1, float("nan"))):
            result = self.policy.step(p, c, t, self.ctx)
            self.assertEqual(result["state"], "UNKNOWN")

    def test_bool_is_not_accepted_as_numeric_input_or_recovery_flag(self):
        for args in ((True, 1, 1), (.9, True, 1), (.9, 1, True)):
            result = self.policy.step(args[0], args[1], args[2], self.ctx)
            self.assertEqual(result["state"], "UNKNOWN")
        result = self.policy.step(.9, 1, 1, self.ctx, joint_recovery=1)
        self.assertEqual(result["state"], "UNKNOWN")

    def test_context_must_be_nonempty_tuple_like_not_string_or_none(self):
        for context in (None, "run-a", b"run-a", (), []):
            result = self.policy.step(.9, 1, 1, context)
            self.assertEqual(result["state"], "UNKNOWN")

    def test_context_change_resets_raw_confirmation(self):
        self.step(.9, t=1)
        changed = ("run-a", "platform-b", "layer-1", "v1", "segment-a")
        self.assertFalse(self.policy.step(.9, 1, 1.05, changed)["confirmed"])
        self.assertTrue(self.policy.step(.9, 1, 1.1, changed)["confirmed"])

    def test_duplicates_and_out_of_order_are_ignored(self):
        self.step(.9, t=1)
        duplicate = self.step(.9, t=1)
        self.assertFalse(duplicate["accepted"])
        self.assertEqual(duplicate["reason"], "duplicate_or_out_of_order")
        self.assertTrue(self.step(.9, t=1.05)["confirmed"])
        stale = self.step(.1, t=1.02)
        self.assertFalse(stale["accepted"])
        self.assertTrue(stale["active"])

    def test_recovery_cancels_active_but_raw_continuity_is_preserved(self):
        self.step(.9, t=1)
        self.assertTrue(self.step(.9, t=1.05)["active"])
        recovered = self.step(.9, t=1.1, joint_recovery=True)
        self.assertTrue(recovered["canceled"])
        self.assertFalse(recovered["active"])
        self.assertTrue(self.step(.9, t=1.15)["confirmed"])

    def test_recovery_without_active_alarm_does_not_emit_cancellation(self):
        result = self.step(.9, t=1, joint_recovery=True)
        self.assertFalse(result["canceled"])

    def test_synthetic_parity_with_reviewed_offline_policy_and_cancellation(self):
        reviewed = reviewed_policy_functions()
        import pandas as pd
        times = [0.0, .05, .1, .15, .2, .35, .4, .45]
        probs = [.9, .9, .95, .2, .9, .9, .9, .9]
        recoveries = [False, False, True, False, False, False, False, False]
        df = pd.DataFrame({"session_id": ["s"]*8, "run_id": ["r"]*8,
            "segment_id": ["g"]*8, "timestamp": times, "clearance": [1.]*8,
            "layer": [1.]*8, "platform_id": ["p"]*8, "mask_strong": [True]*8,
            "prob_strong": probs, "joint_recovery": recoveries})
        expected_df = reviewed.apply_lgb_policy(df)
        expected = expected_df["lgb_pred_strong"].tolist()
        expected_out, expected_cancel = reviewed.cancel_predictions(expected_df, "lgb_pred_strong")
        policy = StrongAlarmPolicy(.8)
        actual = [policy.step(p, 1, t, ("r", "p", 1, "v", "g"), rec)
                  for p, t, rec in zip(probs, times, recoveries)]
        self.assertEqual([x["confirmed"] for x in actual], expected)
        self.assertEqual([x["active"] for x in actual], expected_out.tolist())
        self.assertEqual([x["canceled"] for x in actual], expected_cancel.tolist())


class RecoveryTests(unittest.TestCase):
    def samples(self, velocities=None, clearances=None, times=None):
        times = times or [0, .05, .1, .15]
        velocities = velocities or [-.1]*len(times)
        clearances = clearances or [.2, .21, .23, .25][:len(times)]
        return [dict(timestamp=t, ball_radial_velocity=v, clearance=c)
                for t, v, c in zip(times, velocities, clearances)]

    def test_joint_recovery_causal_positive_clearance_and_gain(self):
        result = compute_recovery(self.samples())
        self.assertTrue(result["joint_recovery"])
        self.assertAlmostEqual(result["clearance_gain_0_1s"], .04)

    def test_cop_only_or_non_inward_motion_never_recovers(self):
        self.assertFalse(compute_recovery(self.samples(velocities=[.1]*4))["joint_recovery"])

    def test_requires_inward_duration(self):
        self.assertFalse(compute_recovery(self.samples(times=[0, .05], clearances=[.2, .3]))["joint_recovery"])

    def test_requires_gain_threshold(self):
        result = compute_recovery(self.samples(clearances=[.2, .205, .21, .215]))
        self.assertFalse(result["joint_recovery"])

    def test_requires_positive_clearance(self):
        self.assertFalse(compute_recovery(self.samples(clearances=[-.1, -.08, -.05, -.01]))["joint_recovery"])

    def test_gap_breaks_contiguous_inward_duration(self):
        samples = self.samples(times=[0, .05, .2, .25], clearances=[.2, .21, .24, .25])
        self.assertFalse(compute_recovery(samples)["joint_recovery"])

    def test_invalid_duplicate_reverse_or_large_gap_history_fails_closed(self):
        valid = self.samples()
        cases = [
            [valid[0], {**valid[1], "timestamp": float("nan")}, valid[2]],
            [valid[0], valid[0], valid[2]],
            [valid[1], valid[0], valid[2]],
            self.samples(times=[0, .05, .2, .25]),
        ]
        for history in cases:
            with self.subTest(history=history):
                result = compute_recovery(history)
                self.assertFalse(result["joint_recovery"])
                self.assertIsNone(result["clearance_gain_0_1s"])

    def test_boolean_observations_are_invalid(self):
        samples = self.samples()
        samples[1]["clearance"] = True
        self.assertFalse(compute_recovery(samples)["joint_recovery"])

    def test_older_history_preserves_duration_longer_than_point_one(self):
        samples = self.samples(times=[0, .05, .1, .15, .2], clearances=[.2, .22, .24, .26, .28])
        result = compute_recovery(samples)
        self.assertTrue(result["joint_recovery"])
        self.assertGreaterEqual(result["continuous_inward_duration"], .2)

    def test_synthetic_flags_match_reviewed_prepare_function(self):
        import pandas as pd
        samples = self.samples(times=[0, .05, .1, .15, .2],
                               clearances=[.2, .21, .23, .25, .28])
        source = pd.DataFrame({"t": [x["timestamp"] for x in samples],
            "ball_radial_velocity": [x["ball_radial_velocity"] for x in samples],
            "directional_edge_distance": [x["clearance"] + .1 for x in samples],
            "ball_radius": [.1]*len(samples)})
        rows = [dict(timestamp=x["timestamp"]) for x in samples]
        reviewed_recovery_function()(rows, source)
        for i in range(len(samples)):
            result = compute_recovery(samples[:i+1])
            self.assertEqual(result["joint_recovery"], rows[i]["joint_recovery"])
            if result["clearance_gain_0_1s"] is None:
                self.assertTrue(math.isnan(rows[i]["clearance_gain_0_1s"]))
            else:
                self.assertAlmostEqual(result["clearance_gain_0_1s"], rows[i]["clearance_gain_0_1s"])


if __name__ == "__main__":
    unittest.main()
