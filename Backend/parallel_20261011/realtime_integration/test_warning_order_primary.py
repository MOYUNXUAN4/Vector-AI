"""Primary review of transport ordering, separate from inference confirmation."""
import json
import unittest
from bridge import RealtimeWarningBridge
from test_bridge import packet


class OrderPrimaryTests(unittest.TestCase):
    def test_confirmed_alarm_then_same_prediction_unknown_is_orderable(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session('run-A')
        bridge.runtime._model.predict_probability = lambda features: .99
        for i in range(38):
            bridge.ingest_unity_packet(packet(i, 10+i*.02), 1+i*.02)
        strong = bridge.attach({'type': 'realtime', 'rmse': 2.1}, 1.74)
        self.assertEqual(strong['model_warning']['state'], 'STRONG')
        # A stale read generates UNKNOWN without any additional model fit/inference.
        unknown = bridge.attach({'type': 'realtime', 'rmse': 2.1}, 2.2)
        a, b = strong['model_warning'], unknown['model_warning']
        self.assertEqual(b['state'], 'UNKNOWN')
        self.assertEqual(a['prediction_sequence'], b['prediction_sequence'])
        self.assertEqual(a['input_sequence'], b['input_sequence'])
        self.assertEqual(a['input_source_timestamp'], b['input_source_timestamp'])
        self.assertEqual(a['run_id'], b['run_id'])
        self.assertEqual(a['layer'], b['layer'])
        self.assertGreater(b['warning_update_sequence'], a['warning_update_sequence'])
        # Minimal sorting reference: old STRONG cannot replace the newer UNKNOWN.
        latest = max((unknown, strong), key=lambda p: p['model_warning']['warning_update_sequence'])
        self.assertEqual(latest['model_warning']['state'], 'UNKNOWN')
        self.assertEqual(unknown['rmse'], 2.1)
        json.dumps(unknown, allow_nan=False)

    def test_invalid_geometry_unknown_retains_current_run_and_known_identity(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session('run-A')
        bridge.ingest_unity_packet(packet(0, 10), 1)
        before = bridge.attach({'type': 'realtime'}, 1)['model_warning']
        bridge.ingest_unity_packet(packet(1, 10.02, geometry_query_valid=False), 1.02)
        after = bridge.attach({'type': 'realtime'}, 1.02)['model_warning']
        self.assertEqual(after['state'], 'UNKNOWN')
        self.assertEqual(after['run_id'], 'run-A')
        self.assertEqual(after['layer'], before['layer'])
        self.assertEqual(after['prediction_sequence'], before['prediction_sequence'])
        self.assertGreater(after['warning_update_sequence'], before['warning_update_sequence'])
        for key in ('input_sequence', 'input_source_timestamp', 'feature_age_seconds'):
            self.assertIn(key, after)
        json.dumps(after, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
