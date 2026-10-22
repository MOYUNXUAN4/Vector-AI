"""Synthetic mechanism tests; no real-data relabelling or training."""
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('primary_review_replay', HERE / 'review_replay.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
pspec = importlib.util.spec_from_file_location('review_policy', review.POLICY)
policy = importlib.util.module_from_spec(pspec)
pspec.loader.exec_module(policy)


def row(t, seq, v=1., q=.5, segment='s', recovery=False):
    return dict(session_id='session', run_id='r', segment_id=segment, layer='1',
                platform_id='-1', geometry_version_id='-1-g1', source_sequence=str(seq),
                timestamp=str(t), clearance=str(q + .5), directional_edge_distance=str(q + 1),
                ball_radius='.5', radial_outward_velocity=str(v),
                causal_prediction_available='True', joint_recovery=str(recovery))


class ReplayTests(unittest.TestCase):
    def play(self, frame, probabilities, tte=True):
        return review.replay(frame, probabilities, .5, policy.StrongAlarmPolicy, tte=tte)

    def test_two_points_required(self):
        trace, _ = self.play([row(0, 1), row(.06, 2)], [1., 1.])
        self.assertEqual([r['active'] for r in trace], [False, True])

    def test_domain_exit_not_recovery(self):
        _, ends = self.play([row(0, 1), row(.06, 2), row(.12, 3, q=-.01)], [1., 1., 0.])
        self.assertEqual(ends[0]['mechanism'], 'q_nonpositive_domain_exit')
        self.assertEqual(ends[0]['movement'], 'outward_not_slower_than_previous')
        self.assertFalse(ends[0]['recovery_cancelled'])

    def test_outward_slowdown_is_not_inward(self):
        _, ends = self.play([row(0, 1), row(.06, 2), row(.12, 3, v=.5)], [1., 1., 0.])
        self.assertEqual(ends[0]['mechanism'], 'raw_off')
        self.assertEqual(ends[0]['movement'], 'outward_slower_than_previous')
        self.assertGreater(ends[0]['tte_seconds'], .75)

    def test_instantaneous_inward_not_sustained(self):
        _, ends = self.play([row(0, 1), row(.06, 2), row(.12, 3, v=-.1)], [1., 1., 0.])
        self.assertEqual(ends[0]['movement'], 'inward_instantaneous')
        self.assertEqual(ends[0]['joint_recovery'], 'False')

    def test_joint_recovery_is_separate_mechanism(self):
        _, ends = self.play([row(0, 1), row(.06, 2), row(.12, 3, recovery=True)], [1., 1., 1.])
        self.assertEqual(ends[0]['mechanism'], 'joint_recovery')
        self.assertTrue(ends[0]['recovery_cancelled'])

    def test_context_change_is_censored(self):
        _, ends = self.play([row(0, 1), row(.06, 2), row(.12, 3, segment='new')], [1., 1., 0.])
        self.assertEqual(ends[0]['withdrawal_kind'], 'boundary_censored')
        self.assertEqual(ends[0]['mechanism'], 'context_changed')

    def test_gap_not_normal_withdrawal(self):
        _, ends = self.play([row(0, 1), row(.06, 2), row(.3, 3)], [1., 1., 0.])
        self.assertEqual(ends[0]['mechanism'], 'decision_gap')
        self.assertEqual(ends[0]['movement'], 'not_comparable')

    def test_nonpositive_clearance_is_invalid(self):
        _, ends = self.play([row(0, 1), row(.06, 2), row(.12, 3, q=-.51)], [1., 1., 1.], tte=False)
        self.assertEqual(ends[0]['mechanism'], 'invalid_or_nonpositive_clearance')
        self.assertFalse(ends[0]['active'])


if __name__ == '__main__':
    unittest.main()
