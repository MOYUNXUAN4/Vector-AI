"""Self-tests for the descriptive TTE withdrawal replay."""
import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "replay_withdrawals.py"
spec = importlib.util.spec_from_file_location("withdrawal_replay_tested", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ReplayWithdrawalTests(unittest.TestCase):
    def future_row(self, t, ctx, *, active=False, recovery=False, q=1.0):
        return {"_time": t, "_context": ctx, "_result": {"active": active},
                "joint_recovery": recovery, "q": q}

    def test_fixed_direction_classes(self):
        self.assertEqual(module.movement(-0.051, 0.2), "inward")
        self.assertEqual(module.movement(0.1, 0.2), "outward_slower_than_previous")
        self.assertEqual(module.movement(0.2, 0.1), "outward_other")
        self.assertEqual(module.movement(0.0, 0.1), "nearzero")
        self.assertEqual(module.movement(None, 0.1), "missing")

    def test_domain_reasons_are_separate(self):
        base = {"causal_prediction_available": "True", "q": 0.1, "radial_outward_velocity": 0.1}
        self.assertEqual(module.domain_reason({**base, "q": 0}), "domain_q_nonpositive")
        self.assertEqual(module.domain_reason({**base, "radial_outward_velocity": 0}), "domain_velocity_nonpositive")
        self.assertEqual(module.domain_reason({**base, "causal_prediction_available": "False"}), "causal_unavailable")
        self.assertEqual(module.domain_reason(base), "domain_valid")

    def test_future_trace_is_bounded_and_noncausal(self):
        ctx = ("run", "segment", "1", "platform", "generation")
        rows = [
            {"_time": 1.0, "_context": ctx, "_result": {"active": False}, "joint_recovery": False, "q": 1.0},
            {"_time": 1.1, "_context": ctx, "_result": {"active": True}, "joint_recovery": True, "q": 0.0},
            {"_time": 1.2, "_context": ctx, "_result": {"active": False}, "joint_recovery": False, "q": 1.0},
            {"_time": 1.3, "_context": ctx, "_result": {"active": False}, "joint_recovery": False, "q": 1.0},
            {"_time": 1.4, "_context": ctx, "_result": {"active": False}, "joint_recovery": False, "q": 1.0},
        ]
        result = module.future_window_summary(rows, 0)
        self.assertTrue(result["future_0_4s_is_noncause"])
        self.assertTrue(result["future_0_4s_complete"])
        self.assertTrue(result["future_0_4s_any_active"])
        self.assertTrue(result["future_0_4s_any_saved_joint_recovery"])
        self.assertTrue(result["future_0_4s_any_q_nonpositive"])

    def test_future_trace_stops_at_context_change(self):
        ctx, other = ("r", "s1"), ("r", "s2")
        rows = [self.future_row(1.0, ctx),
                self.future_row(1.1, ctx),
                self.future_row(1.2, other, active=True, recovery=True, q=0)]
        result = module.future_window_summary(rows, 0)
        self.assertFalse(result["future_0_4s_complete"])
        self.assertFalse(result["future_0_4s_any_active"])
        self.assertFalse(result["future_0_4s_any_saved_joint_recovery"])
        self.assertFalse(result["future_0_4s_any_q_nonpositive"])

    def test_future_trace_stops_at_source_gap(self):
        ctx = ("r", "s")
        rows = [self.future_row(1.0, ctx),
                self.future_row(1.1, ctx),
                self.future_row(1.25, ctx, active=True, recovery=True, q=0)]
        result = module.future_window_summary(rows, 0)
        self.assertFalse(result["future_0_4s_complete"])
        self.assertFalse(result["future_0_4s_any_active"])
        self.assertFalse(result["future_0_4s_any_saved_joint_recovery"])
        self.assertFalse(result["future_0_4s_any_q_nonpositive"])

    def test_future_trace_marks_session_end_incomplete(self):
        ctx = ("r", "s")
        rows = [self.future_row(1.0, ctx),
                self.future_row(1.1, ctx, active=True, recovery=True, q=0),
                self.future_row(1.2, ctx)]
        result = module.future_window_summary(rows, 0)
        self.assertFalse(result["future_0_4s_complete"])
        self.assertTrue(result["future_0_4s_any_active"])
        self.assertTrue(result["future_0_4s_any_saved_joint_recovery"])
        self.assertTrue(result["future_0_4s_any_q_nonpositive"])

    def test_first_sample_after_horizon_does_not_contribute_flags(self):
        ctx = ("r", "s")
        rows = [self.future_row(1.0, ctx),
                self.future_row(1.1, ctx),
                self.future_row(1.2, ctx),
                self.future_row(1.3, ctx),
                self.future_row(1.36, ctx),
                self.future_row(1.41, ctx, active=True, recovery=True, q=0)]
        result = module.future_window_summary(rows, 0)
        self.assertTrue(result["future_0_4s_complete"])
        self.assertEqual(result["future_0_4s_observed_seconds"], 0.4)
        self.assertFalse(result["future_0_4s_any_active"])
        self.assertFalse(result["future_0_4s_any_saved_joint_recovery"])
        self.assertFalse(result["future_0_4s_any_q_nonpositive"])

    def test_decision_movement_does_not_compare_across_context_or_gap(self):
        base = {"_context": ("r", "s1"), "_time": 1.0, "radial_outward_velocity": 0.2}
        context_change = {"_context": ("r", "s2"), "_time": 1.05, "radial_outward_velocity": -0.2}
        gap = {"_context": ("r", "s1"), "_time": 1.2, "radial_outward_velocity": -0.2}
        self.assertEqual(module.decision_movement(base, context_change), "not_comparable_across_boundary")
        self.assertEqual(module.decision_movement(base, gap), "not_comparable_across_boundary")

    def test_reference_policy_confirmation_raw_off_recovery(self):
        policy_path = module.POLICY_PATH
        policy_spec = importlib.util.spec_from_file_location("withdrawal_policy_tested", policy_path)
        policy = importlib.util.module_from_spec(policy_spec)
        sys.modules[policy_spec.name] = policy
        policy_spec.loader.exec_module(policy)
        p = policy.StrongAlarmPolicy(0.5)
        ctx = ("run", "segment", "1", "platform", "generation")
        self.assertEqual(p.step(1, 1, 1.00, ctx)["reason"], "raw_on")
        on = p.step(1, 1, 1.05, ctx)
        self.assertTrue(on["active"])
        self.assertEqual(on["reason"], "confirmed")
        off = p.step(0, 1, 1.10, ctx)
        self.assertFalse(off["active"])
        self.assertEqual(off["reason"], "raw_off")
        p.step(1, 1, 1.15, ctx)
        self.assertTrue(p.step(1, 1, 1.20, ctx)["active"])
        recovered = p.step(1, 1, 1.25, ctx, True)
        self.assertFalse(recovered["active"])
        self.assertTrue(recovered["canceled"])
        self.assertEqual(recovered["reason"], "joint_recovery")


if __name__ == "__main__":
    unittest.main()
