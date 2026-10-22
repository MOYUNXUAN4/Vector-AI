import copy
import json
import math
import unittest
from pathlib import Path

from bridge import (ARTIFACT_MANIFEST, PINNED_MODEL_SHA256,
                    RealtimeWarningBridge)


def packet(seq, stamp, *, run="run-A", **changes):
    result = {
        "type": "unity_game", "run_id": run, "run_state": "running",
        "timestamp": stamp, "sequence": seq, "platformLevel": 1,
        "platformTilt": .1, "calibration_mode": False,
        "selected_session_layers": 3, "platform_scale": 1.0,
        "geometry_platform_instance_id": -77,
        "geometry_active_platform_instance_id": -77,
        "geometry_version_id": "g1", "geometry_active_version_id": "g1",
        "geometry_query_valid": True, "geometry_ownership_valid": True,
        "directional_edge_valid": True, "directional_edge_distance": 2.0,
        "ball_radius": .5, "platform_radius": 6.0,
        "ball_radial_velocity": .2, "ball_velocity_x": .2,
        "ball_velocity_z": 0., "ball_pos_x": 1., "ball_pos_z": 0.,
        "platform_center_x": 0., "platform_center_z": 0., "difficulty": 1.,
        "cop_x": 0., "cop_z": 0.,
    }
    result.update(changes)
    return result


class BridgeTests(unittest.TestCase):
    def test_default_off_does_not_import_or_mutate_warning_schema(self):
        bridge = RealtimeWarningBridge()
        original = {"type": "realtime", "difficulty": 3, "rmse": 1.2}
        before = copy.deepcopy(original)
        self.assertIs(bridge.attach(original, 1.0), original)
        self.assertEqual(original, before)
        self.assertIsNone(bridge.runtime)
        bridge.start_session("run-A")
        self.assertFalse(bridge.ingest_unity_packet(packet(0, 1.0), 1.0))

    def test_loads_pinned_native_artifact_and_authorizes_only_first_run(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 10.0), 1.0))
        runtime = bridge.runtime
        warning = runtime.warning(1.0)
        self.assertEqual(warning["model_sha256"], PINNED_MODEL_SHA256)
        self.assertEqual(warning["model_id"], "test1009-strong-deployment-refit-20261011")
        self.assertFalse(bridge.ingest_unity_packet(packet(1, 10.05, run="foreign"), 1.05))
        self.assertEqual(runtime.warning(1.05)["run_id"], "run-A")
        self.assertFalse(bridge.ingest_unity_packet(
            packet(1, 10.05, run="run-A", run_state="ended"), 1.05))
        self.assertEqual(runtime.warning(1.05)["state"], "UNKNOWN")
        # Closed IDs cannot reclaim ownership, while a fresh explicit run ID can.
        bridge.start_session("run-A")
        self.assertFalse(bridge.ingest_unity_packet(packet(2, 10.1), 1.1))
        bridge.start_session("run-B")
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 20.0, run="run-B"), 2.0))

    def test_explicit_restart_ends_active_owner_without_terminal_packet(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        bridge.ingest_unity_packet(packet(0, 10.0), 1.0)
        bridge.start_session("run-A")  # same-run duplicate start is idempotent
        bridge.start_session("run-B")
        self.assertEqual(bridge.runtime.warning(1.01)["state"], "UNKNOWN")
        self.assertFalse(bridge.ingest_unity_packet(packet(1, 10.05), 1.05))
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 20.0, run="run-B"), 2.0))

    def test_malformed_owner_packet_fails_closed_and_stale_reply_is_unknown(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        bridge.ingest_unity_packet(packet(0, 10.0), 1.0)
        malformed = packet(1, 10.05)
        del malformed["geometry_version_id"]
        self.assertFalse(bridge.ingest_unity_packet(malformed, 1.05))
        outgoing = {"type": "realtime", "difficulty": 4, "x": .2}
        attached = bridge.attach(outgoing, 1.1)
        self.assertEqual(outgoing, {"type": "realtime", "difficulty": 4, "x": .2})
        self.assertEqual(attached["difficulty"], 4)
        self.assertEqual(attached["model_warning"]["state"], "UNKNOWN")
        json.dumps(attached, allow_nan=False)

    def test_model_load_failure_remains_nonfatal_unknown(self):
        bridge = RealtimeWarningBridge(enabled=True, manifest=Path("missing-manifest.json"))
        bridge.start_session("run-A")
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 1.0), 1.0))
        reply = bridge.attach({"type": "realtime", "difficulty": 2}, 1.0)
        self.assertEqual(reply["model_warning"]["state"], "UNKNOWN")
        self.assertEqual(reply["difficulty"], 2)

    def test_invalid_geometry_then_valid_same_owner_recovers_and_late_terminal_is_ignored(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 10.0), 1.0))
        self.assertFalse(bridge.ingest_unity_packet(
            packet(1, 10.05, directional_edge_valid=False), 1.05))
        self.assertEqual(bridge.runtime.warning(1.05)["state"], "UNKNOWN")
        self.assertFalse(bridge.ingest_unity_packet(
            packet(0, 10.0, run_state="ended"), 1.06))
        self.assertTrue(bridge.ingest_unity_packet(packet(2, 10.1), 1.1))
        self.assertEqual(bridge.runtime.warning(1.1)["run_id"], "run-A")

    def test_runtime_import_failure_does_not_escape_into_legacy_loop(self):
        def unavailable(**_kwargs):
            raise ImportError("simulated missing dependency")

        bridge = RealtimeWarningBridge(enabled=True, runtime_factory=unavailable)
        bridge.start_session("run-A")
        attached = bridge.attach({"type": "realtime", "difficulty": 2}, 1.0)
        self.assertEqual(attached["model_warning"]["state"], "UNKNOWN")
        self.assertEqual(attached["difficulty"], 2)

    def test_ingest_exception_clears_strong_and_preserves_legacy_reply(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 10.0), 1.0))
        runtime = bridge.runtime
        strong = runtime._base_warning("test_active_alarm")
        strong.update(state="STRONG", valid=True, probability_valid=True,
                      strong_probability=.99, raw=True, confirmed=True)
        runtime._publish(strong)

        def explode(*_args, **_kwargs):
            raise RuntimeError("simulated ingest failure")

        runtime.ingest = explode
        self.assertFalse(bridge.ingest_unity_packet(packet(1, 10.05), 1.05))
        legacy = {"type": "realtime", "difficulty": 4, "rmse": 2.3}
        attached = bridge.attach(legacy, 1.06)
        self.assertEqual(attached["difficulty"], 4)
        self.assertEqual(attached["rmse"], 2.3)
        self.assertEqual(attached["model_warning"]["state"], "UNKNOWN")

    def test_missing_start_run_id_stays_unknown_when_end_run_raises(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 10.0), 1.0))
        runtime = bridge.runtime
        strong = runtime._base_warning("test_active_alarm")
        strong.update(state="STRONG", valid=True, probability_valid=True,
                      strong_probability=.99, raw=True, confirmed=True)
        runtime._publish(strong)

        def explode():
            raise RuntimeError("simulated end_run failure")

        runtime.end_run = explode
        bridge.start_session(None)
        attached = bridge.attach({"type": "realtime", "difficulty": 3}, 1.05)
        self.assertEqual(attached["difficulty"], 3)
        self.assertEqual(attached["model_warning"]["state"], "UNKNOWN")

    def test_invalid_run_state_and_nonfinite_stamp_do_not_close_or_poison_owner(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        self.assertTrue(bridge.ingest_unity_packet(packet(0, 10.0), 1.0))
        self.assertFalse(bridge.ingest_unity_packet(
            packet(1, 10.05, run_state="not_started"), 1.05))
        self.assertEqual(bridge.runtime.warning(1.05)["state"], "UNKNOWN")
        self.assertFalse(bridge.ingest_unity_packet(packet(1, math.inf), 1.06))
        self.assertTrue(bridge.ingest_unity_packet(packet(2, 10.1), 1.1))
        self.assertEqual(bridge.runtime.warning(1.1)["run_id"], "run-A")


if __name__ == "__main__":
    unittest.main()
