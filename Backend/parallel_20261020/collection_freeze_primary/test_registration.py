import unittest
import register_collection as registry


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.annotations = {'participant_sessions': ['p','e'], 'operator_sessions': ['o'],
            'participant_id': 'P01', 'equipment_exclusions': {'e': {}}}

    def test_unknown_is_not_participant(self):
        self.assertEqual(registry.classify('unknown', self.annotations), ('unresolved_quarantined', None))

    def test_equipment_exclusion_is_not_retained(self):
        self.assertEqual(registry.classify('e', self.annotations), ('participant_equipment_excluded', 'P01'))

    def test_operator_does_not_inherit_folder_participant(self):
        self.assertEqual(registry.classify('o', self.annotations), ('operator_technical_test', None))

    def test_participant_remains_pending_qc(self):
        self.assertEqual(registry.classify('p', self.annotations), ('participant_retained_pending_qc', 'P01'))

    def test_conflicting_purpose_is_rejected(self):
        self.annotations['operator_sessions'].append('p')
        with self.assertRaises(ValueError):
            registry.classify('p', self.annotations)


if __name__ == '__main__':
    unittest.main()
