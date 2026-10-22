"""Primary-review deterministic policy/failure checks using the native loader."""
import json
import ast
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'realtime_integration'))
from bridge import RealtimeWarningBridge
from test_bridge import packet


class PrimaryLiveTests(unittest.TestCase):
    def test_live_receiver_has_both_reply_hooks_and_early_ingest(self):
        source = (HERE.parent / 'UDPRecevier.py').read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == 'warning_bridge']
        names = [node.func.attr for node in calls]
        self.assertEqual(names.count('attach'), 2)
        self.assertEqual(names.count('start_session'), 1)
        self.assertEqual(names.count('ingest_unity_packet'), 1)
        ingest_line = next(node.lineno for node in calls if node.func.attr == 'ingest_unity_packet')
        reply_lines = [node.lineno for node in calls if node.func.attr == 'attach']
        self.assertLess(ingest_line, min(reply_lines))

    def ready(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session('run-A')
        # Native model has been loaded; fix score locally only to isolate policy.
        bridge.runtime._model.predict_probability = lambda features: .99
        for i in range(40):
            bridge.ingest_unity_packet(packet(i, 10+i*.02), 1+i*.02)
        self.assertEqual(bridge.attach({'type': 'realtime'}, 1.78)['model_warning']['state'], 'STRONG')
        return bridge

    def test_stale_after_real_confirmation_becomes_unknown(self):
        bridge = self.ready()
        out = bridge.attach({'type': 'realtime', 'difficulty': 3, 'x': .2}, 2.2)
        self.assertEqual(out['model_warning']['state'], 'UNKNOWN')
        self.assertFalse(out['model_warning']['valid'])
        self.assertEqual(out['difficulty'], 3)
        json.dumps(out, allow_nan=False)

    def test_foreign_and_old_terminal_preserve_current_alarm(self):
        bridge = self.ready()
        bridge.ingest_unity_packet(packet(1, 10.02, run_state='ended'), 1.79)
        bridge.ingest_unity_packet(packet(100, 12, run='old-run'), 1.79)
        self.assertEqual(bridge.attach({'type':'realtime'}, 1.79)['model_warning']['state'], 'STRONG')

    def test_infinite_timestamp_does_not_permanently_poison_ordering(self):
        bridge = self.ready()
        bridge.ingest_unity_packet(packet(40, float('inf')), 1.8)
        self.assertEqual(bridge.attach({'type':'realtime'}, 1.8)['model_warning']['state'], 'UNKNOWN')
        for i in range(41, 81):
            bridge.ingest_unity_packet(packet(i, 10+i*.02), 1+i*.02)
        self.assertEqual(bridge.attach({'type':'realtime'}, 2.6)['model_warning']['state'], 'STRONG')

    def test_transient_unknown_run_state_then_rewarm(self):
        bridge = self.ready()
        missing = packet(40, 10.8)
        del missing['run_state']
        bridge.ingest_unity_packet(missing, 1.8)
        self.assertEqual(bridge.attach({'type':'realtime'}, 1.8)['model_warning']['state'], 'UNKNOWN')
        for i in range(41, 81):
            bridge.ingest_unity_packet(packet(i, 10+i*.02), 1+i*.02)
        self.assertEqual(bridge.attach({'type':'realtime'}, 2.6)['model_warning']['state'], 'STRONG')

    def test_restart_requires_warmup_and_drops_old_alarm(self):
        bridge = self.ready()
        bridge.start_session('run-B')
        bridge.ingest_unity_packet(packet(0, 20, run='run-B'), 1.8)
        self.assertEqual(bridge.attach({'type':'realtime'}, 1.8)['model_warning']['state'], 'UNKNOWN')
        bridge.ingest_unity_packet(packet(41, 10.82), 1.82)
        self.assertEqual(bridge.runtime.warning(1.82)['run_id'], 'run-B')


if __name__ == '__main__':
    unittest.main()
