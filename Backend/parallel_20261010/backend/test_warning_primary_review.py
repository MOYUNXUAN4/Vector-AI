"""Independent integration checks; no project model/data and no network."""
import copy
import json
import unittest

import test_warning_runtime as fixture


class PrimaryReview(unittest.TestCase):
    def setUp(self):
        fixture.RuntimeTests.setUp(self)
        self.assertTrue(self.runtime.load(self.manifest, self.digest, True))
        self.assertTrue(self.runtime.enable())
        self.runtime.begin_run('r1')

    def tearDown(self):
        fixture.RuntimeTests.tearDown(self)

    def ingest(self, seq, source, receipt, **changes):
        return self.runtime.ingest(fixture.unity_packet(seq, source, **changes), receipt)

    def warm(self):
        for i in range(13):
            self.assertTrue(self.ingest(i, 1000 + i*.05, 20 + i*.05))
        self.assertEqual(self.runtime.warning(20.6)['state'], 'STRONG')

    def test_prediction_keeps_actual_input_identity_between_decisions(self):
        self.warm()
        predicted = self.runtime.warning(20.6)
        self.assertTrue(self.ingest(13, 1000.61, 20.61))
        output = self.runtime.warning(20.62)
        for key in ('prediction_sequence', 'input_sequence', 'input_source_timestamp'):
            self.assertEqual(output[key], predicted[key])
        self.assertAlmostEqual(output['feature_age_seconds'], .02)

    def test_geometry_invalid_cannot_reuse_confirmation_same_platform(self):
        self.warm()
        self.assertFalse(self.ingest(13, 1000.65, 20.65, geometry_query_valid=False))
        self.assertEqual(self.runtime.warning(20.65)['state'], 'UNKNOWN')
        for i in range(11):
            self.assertTrue(self.ingest(14+i, 1000.7+i*.05, 20.7+i*.05))
        first = self.runtime.warning(21.2)
        self.assertNotEqual(first['state'], 'STRONG')
        self.assertTrue(self.ingest(25, 1001.25, 21.25))
        self.assertEqual(self.runtime.warning(21.25)['state'], 'STRONG')

    def test_reverse_clock_read_resets_confirmation_not_a_new_evaluation(self):
        self.warm()
        before = self.runtime.warning(20.6)['prediction_sequence']
        self.assertEqual(self.runtime.warning(20.59)['state'], 'UNKNOWN')
        self.assertTrue(self.ingest(13, 1000.65, 20.65))
        output = self.runtime.warning(20.65)
        self.assertEqual(output['prediction_sequence'], before + 1)
        self.assertFalse(output['confirmed'])

    def test_attach_is_deep_copy_and_reads_do_not_advance_confirmation(self):
        for i in range(11):
            self.assertTrue(self.ingest(i, 1000+i*.05, 20+i*.05))
        original = {'type':'realtime','x':.1,'y':.2,'difficulty':4,
                    'load_cells':{'tl':3}, 'rmse':.01}
        saved = copy.deepcopy(original)
        for _ in range(8):
            attached = self.runtime.attach(original, 20.5)
            self.assertNotEqual(attached['model_warning']['state'], 'STRONG')
            json.dumps(attached, allow_nan=False)
        attached['load_cells']['tl'] = 999
        self.assertEqual(original, saved)

    def test_version_change_and_delayed_old_packet_cannot_cross_confirm(self):
        self.warm()
        self.assertTrue(self.ingest(13,1000.65,20.65,
            geometry_version_id='g2',geometry_active_version_id='g2'))
        self.assertEqual(self.runtime.warning(20.65)['state'],'UNKNOWN')
        self.assertFalse(self.ingest(4,1000.2,20.66,run_state='ended'))
        self.assertTrue(self.ingest(14,1000.7,20.7,
            geometry_version_id='g2',geometry_active_version_id='g2'))
        self.assertEqual(self.runtime.warning(20.7)['state'],'UNKNOWN')

    def test_nonpositive_clearance_invalidates_before_next_cadence(self):
        self.warm()
        self.assertTrue(self.ingest(13,1000.61,20.61,clearance=-.01))
        output = self.runtime.warning(20.61)
        self.assertEqual(output['state'],'UNKNOWN')
        self.assertFalse(output['probability_valid'])


if __name__ == '__main__':
    unittest.main()
