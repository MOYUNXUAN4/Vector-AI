import unittest
from audit_seven import classify, numeric


def point(active, reason):
    return dict(active=str(active), policy_reason=reason)


class CaseClassificationTests(unittest.TestCase):
    def test_no_decisions_unknown(self):
        self.assertEqual(classify([]), 'insufficient_decisions')

    def test_score_drop(self):
        self.assertEqual(classify([point(True, 'confirmed'), point(False, 'raw_off')]), 'score_drop_after_active')

    def test_low_score_never_active(self):
        self.assertEqual(classify([point(False, 'raw_off'), point(False, 'raw_off')]), 'inactive_low_score')

    def test_late_unconfirmed_high_score(self):
        self.assertEqual(classify([point(False, 'raw_off'), point(False, 'raw_on')]), 'inactive_with_late_confirmation_pending')

    def test_pending_then_active_is_not_withdrawal(self):
        self.assertEqual(classify([point(False, 'raw_on'), point(True, 'confirmed')]), 'initial_confirmation_then_active')

    def test_joint_recovery_not_misclassified_as_score_drop(self):
        self.assertEqual(classify([point(True, 'confirmed'), point(False, 'joint_recovery')]), 'other_or_unresolved')

    def test_active_only_not_selected_pattern(self):
        self.assertEqual(classify([point(True, 'confirmed')]), 'other_or_unresolved')

    def test_nonfinite_numbers_not_zero(self):
        self.assertIsNone(numeric('nan'))
        self.assertIsNone(numeric('inf'))
        self.assertIsNone(numeric(''))
        self.assertEqual(numeric('0'), 0.)


if __name__ == '__main__':
    unittest.main()
