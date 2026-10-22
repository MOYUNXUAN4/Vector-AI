"""Prospective synthetic five-layer checks, never a replay of historical exposure."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for directory in ('parallel_20261010/backend', 'parallel_20261011/realtime_integration',
                  'parallel_20261015/proximity_reply_luna'):
    sys.path.insert(0, str(ROOT / directory))

import test_warning_runtime as model_fixture
from bridge import RealtimeWarningBridge
from test_geometry_danger import packet as geometry_packet
from proximity_reply import ReplyProximityShadow
from test_proximity_reply import packet as tte_packet


class FiveLayerChainTests(unittest.TestCase):
    def test_mock_model_becomes_valid_and_confirmed_on_five_layer_session(self):
        fixture = model_fixture.RuntimeTests()
        fixture.setUp()
        try:
            fixture.load_enabled()
            fixture.warm(count=12, selected_session_layers=5, layer=5, calibration=True)
            warning = fixture.runtime.warning(20.55)
            self.assertTrue(warning['probability_valid'])
            self.assertEqual(warning['state'], 'STRONG')
        finally:
            fixture.tearDown()

    def test_geometry_works_without_model_and_rejects_invalid_query(self):
        def broken_model(**kwargs):
            raise RuntimeError('synthetic model unavailable')
        bridge = RealtimeWarningBridge(enabled=True, runtime_factory=broken_model,
                                       allow_calibration_gameplay=True)
        bridge.start_session('run-A')
        bridge.ingest_unity_packet(geometry_packet(selected_session_layers=5,
            platformLevel=5, calibration_mode=True), 1.0)
        result = bridge.attach({'type': 'realtime', 'difficulty': 3}, 1.0)
        self.assertEqual(result['geometry_warning']['state'], 'CRITICAL')
        self.assertFalse(result['model_warning']['probability_valid'])
        self.assertEqual(result['difficulty'], 3)
        bridge.ingest_unity_packet(geometry_packet(1, 1791770000.05,
            selected_session_layers=5, platformLevel=5, calibration_mode=True,
            geometry_query_valid=False), 1.05)
        self.assertFalse(bridge.attach({'type': 'realtime'}, 1.05)['geometry_warning']['valid'])

    def test_five_layer_tte_approach_then_stale_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [0.0]
            shadow = ReplyProximityShadow(Path(directory) / 'synthetic.jsonl', clock=lambda: now[0])
            shadow.start_session('r1')
            for i in range(1, 9):
                now[0] = i * .09
                packet = tte_packet(i, layer=5)
                packet.update(selected_session_layers=5, calibration_mode=True)
                shadow.ingest(packet, now[0])
            warning = shadow.attach_realtime({'type': 'realtime'}, now[0])['proximity_warning']
            self.assertTrue(warning['valid'])
            self.assertTrue(warning['active'])
            self.assertEqual(warning['state'], 'APPROACH')
            self.assertNotIn('strong_probability', warning)
            now[0] += .31
            stale = shadow.attach_realtime({'type': 'realtime'}, now[0])['proximity_warning']
            self.assertFalse(stale['valid'])
            self.assertFalse(stale['active'])


if __name__ == '__main__':
    unittest.main()
