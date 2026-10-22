"""Synthetic boundary tests; never accesses or edits original recordings."""
import unittest
from check_handoff import source_flags
from raw_crossings import qc, track


def sample(seq, t, q, **updates):
    r = dict(sequence=str(seq), source_timestamp=str(t), run_id='r', run_state='running',
             platform_level='1', geometry_platform_instance_id='-14', geometry_active_platform_instance_id='-14',
             geometry_version_id='-14-g1', geometry_active_version_id='-14-g1',
             directional_edge_valid='True', geometry_query_valid='True', geometry_ownership_valid='True',
             directional_edge_distance=str(q + 1), ball_radius='.5', _line=seq+2)
    r.update(updates)
    return r


class HandoffTests(unittest.TestCase):
    def test_q_zero_is_not_red_boundary(self):
        self.assertEqual(qc(sample(1, 1., 0.)), (0., .5))

    def test_c_zero_is_one_radius_after_q_zero(self):
        self.assertEqual(qc(sample(1, 1., -.5)), (-.5, 0.))

    def test_negative_id_accepted(self):
        self.assertTrue(source_flags(sample(1, 1., -.2)))

    def test_unknown_id_rejected(self):
        self.assertFalse(source_flags(sample(1, 1., -.2, geometry_platform_instance_id='0', geometry_active_platform_instance_id='0')))

    def test_version_mismatch_rejected(self):
        self.assertFalse(source_flags(sample(1, 1., -.2, geometry_active_version_id='-14-g2')))

    def test_nonfinite_distance_rejected(self):
        self.assertFalse(source_flags(sample(1, 1., -.2, directional_edge_distance='nan')))

    def test_backtrack_finds_first_q_nonpositive_not_decision_time(self):
        group = [sample(1, 1., .1), sample(2, 1.02, -.05), sample(3, 1.04, -.1),
                 sample(4, 1.06, -.3), sample(5, 1.08, -.6)]
        r = track(group, 2)
        self.assertEqual(r['q_high_line'], group[1]['_line'])
        self.assertEqual(r['stop_reason'], 'first_c_nonpositive')
        self.assertAlmostEqual(r['packet_bracket_span_lower_s'], .04)
        self.assertAlmostEqual(r['packet_bracket_span_upper_s'], .08)

    def test_sequence_gap_censors_not_bridge_to_red(self):
        r = track([sample(1, 1., .1), sample(2, 1.02, -.1), sample(4, 1.04, -.6)], 1)
        self.assertEqual(r['stop_reason'], 'source_discontinuity')
        self.assertNotIn('c_high_line', r)
        self.assertEqual(r['last_valid_time'], 1.02)

    def test_context_change_censors(self):
        r = track([sample(1, 1., .1), sample(2, 1.02, -.1), sample(3, 1.04, -.6, platform_level='2')], 1)
        self.assertEqual(r['stop_reason'], 'context_changed')
        self.assertNotIn('c_high_line', r)

    def test_time_gap_censors(self):
        r = track([sample(1, 1., .1), sample(2, 1.02, -.1), sample(3, 1.4, -.6)], 1)
        self.assertEqual(r['stop_reason'], 'source_discontinuity')

    def test_invalid_geometry_stops(self):
        r = track([sample(1, 1., .1), sample(2, 1.02, -.1), sample(3, 1.04, -.6, geometry_query_valid='False')], 1)
        self.assertEqual(r['stop_reason'], 'invalid_source_evidence')

    def test_no_skip_q_return_to_later_red(self):
        r = track([sample(1, 1., .1), sample(2, 1.02, -.1), sample(3, 1.04, .1), sample(4, 1.06, -.6)], 1)
        self.assertEqual(r['stop_reason'], 'q_positive_again')
        self.assertNotIn('c_high_line', r)

    def test_terminal_not_included_as_covered(self):
        r = track([sample(1, 1., .1), sample(2, 1.02, -.1), sample(3, 1.04, -.6, run_state='ended')], 1)
        self.assertEqual(r['stop_reason'], 'terminal_or_nonrunning')
        self.assertEqual(r['last_valid_time'], 1.02)


if __name__ == '__main__':
    unittest.main()
