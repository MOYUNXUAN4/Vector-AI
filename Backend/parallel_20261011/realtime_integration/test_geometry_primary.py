"""Primary reviewer checks independent of model fitting and live services."""
import unittest
from test_geometry_danger import bridge, packet


class PrimaryGeometryTests(unittest.TestCase):
    def test_combined_expiry_no_duplicate_renewal(self):
        b = bridge()
        p = packet(time=123.2)
        b.ingest_unity_packet(p, 10.)
        self.assertTrue(b.attach({}, 10.05)['geometry_warning']['valid'])
        b.ingest_unity_packet(p, 10.09)
        self.assertFalse(b.attach({}, 10.11)['geometry_warning']['valid'])

    def test_recoverable_state_does_not_lose_owner(self):
        b = bridge()
        b.ingest_unity_packet(packet(), 1.)
        b.ingest_unity_packet(packet(1, 1791770000.01, run_state='paused'), 1.01)
        self.assertFalse(b.attach({}, 1.01)['geometry_warning']['valid'])
        b.ingest_unity_packet(packet(2, 1791770000.02), 1.02)
        self.assertTrue(b.attach({}, 1.02)['geometry_warning']['valid'])

    def test_model_failure_cannot_be_geometry_probability(self):
        def broken(**kwargs):
            raise RuntimeError('synthetic unavailable model')
        b = bridge(runtime_factory=broken, allow_calibration_gameplay=True)
        b.ingest_unity_packet(packet(calibration_mode=True), 1.)
        result = b.attach({'difficulty': 3}, 1.)
        self.assertEqual(result['difficulty'], 3)
        self.assertFalse(result['model_warning']['probability_valid'])
        g = result['geometry_warning']
        self.assertEqual(g['state'], 'CRITICAL')
        self.assertFalse(any('probability' in key for key in g))
        self.assertEqual(g['warning_update_sequence'], result['model_warning']['warning_update_sequence'])

    def test_wrong_platform_unknown_then_fresh_platform(self):
        b = bridge()
        b.ingest_unity_packet(packet(), 1.)
        b.ingest_unity_packet(packet(1, 1791770000.01, geometry_active_platform_instance_id=-99), 1.01)
        self.assertFalse(b.attach({}, 1.01)['geometry_warning']['valid'])
        b.ingest_unity_packet(packet(2, 1791770000.02, geometry_platform_instance_id=-99,
                                     geometry_active_platform_instance_id=-99), 1.02)
        self.assertEqual(b.attach({}, 1.02)['geometry_warning']['platform_instance_id'], -99)

    def test_geometry_fault_does_not_interrupt_legacy_reply(self):
        b = bridge()
        b._geometry.warning = lambda **kwargs: (_ for _ in ()).throw(RuntimeError('synthetic'))
        result = b.attach({'difficulty': 5}, 1.)
        self.assertEqual(result['difficulty'], 5)
        self.assertNotEqual(result.get('geometry_warning', {}).get('state'), 'CRITICAL')


if __name__ == '__main__':
    unittest.main()
