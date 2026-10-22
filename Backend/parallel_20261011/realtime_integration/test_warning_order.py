import copy
import json
import unittest
from pathlib import Path

from bridge import (MAX_WARNING_UPDATE_SEQUENCE, PINNED_MODEL_SHA256,
                    RealtimeWarningBridge)
from test_bridge import packet


class WarningOrderTests(unittest.TestCase):
    def test_repeated_attach_has_strictly_increasing_sequence_and_preserves_input(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        sample = packet(0, 10.0)
        self.assertTrue(bridge.ingest_unity_packet(sample, 1.0))
        outgoing = {"type": "realtime", "difficulty": 3}
        before = copy.deepcopy(outgoing)
        first = bridge.attach(outgoing, 1.01)
        second = bridge.attach(outgoing, 1.02)
        self.assertEqual(outgoing, before)
        self.assertEqual(first["model_warning"]["warning_update_sequence"], 1)
        self.assertEqual(second["model_warning"]["warning_update_sequence"], 2)
        self.assertEqual(first["model_warning"]["model_sha256"], PINNED_MODEL_SHA256)

    def test_same_prediction_strong_then_unknown_has_newer_update_sequence(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        bridge.ingest_unity_packet(packet(0, 10.0), 1.0)
        runtime = bridge.runtime
        strong = runtime._base_warning("test_active_alarm")
        strong.update(state="STRONG", valid=True, probability_valid=True,
                      strong_probability=.99, raw=True, confirmed=True)
        runtime._publish(strong)
        strong_reply = bridge.attach({"type": "realtime"}, 1.01)["model_warning"]
        bridge._force_unknown(runtime, "test_revoke")
        unknown_reply = bridge.attach({"type": "realtime"}, 1.02)["model_warning"]
        self.assertEqual(strong_reply["prediction_sequence"], unknown_reply["prediction_sequence"])
        self.assertGreater(unknown_reply["warning_update_sequence"],
                           strong_reply["warning_update_sequence"])
        for key in ("run_id", "layer", "input_sequence", "input_source_timestamp",
                    "prediction_sequence", "feature_age_seconds"):
            self.assertEqual(unknown_reply[key], strong_reply[key])
        json.dumps(unknown_reply, allow_nan=False)

    def test_client_can_discard_late_older_reply(self):
        bridge = RealtimeWarningBridge(enabled=True)
        older = bridge.attach({"type": "realtime"}, 1.0)
        newer = bridge.attach({"type": "realtime"}, 1.1)
        client_sequence = newer["model_warning"]["warning_update_sequence"]
        self.assertLess(older["model_warning"]["warning_update_sequence"], client_sequence)
        self.assertFalse(older["model_warning"]["warning_update_sequence"] > client_sequence)

    def test_counter_does_not_reset_for_run_or_layer_change(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        bridge.ingest_unity_packet(packet(0, 10.0), 1.0)
        first = bridge.attach({"type": "realtime"}, 1.01)["model_warning"]["warning_update_sequence"]
        bridge.start_session("run-B")
        bridge.ingest_unity_packet(packet(0, 20.0, run="run-B", platformLevel=2), 2.0)
        second = bridge.attach({"type": "realtime"}, 2.01)["model_warning"]["warning_update_sequence"]
        self.assertEqual((first, second), (1, 2))
        self.assertEqual(bridge.runtime.warning(2.01)["layer"], 2)

    def test_default_off_returns_same_object_without_counter_or_warning(self):
        bridge = RealtimeWarningBridge()
        legacy = {"type": "realtime", "model_warning": {"existing": True}}
        self.assertIs(bridge.attach(legacy), legacy)
        self.assertEqual(legacy["model_warning"], {"existing": True})
        self.assertEqual(bridge._warning_update_sequence, 0)

    def test_runtime_import_failure_and_model_load_failure_are_sequenced_unknown(self):
        def unavailable(**_kwargs):
            raise ImportError("simulated")

        import_failed = RealtimeWarningBridge(enabled=True, runtime_factory=unavailable)
        import_reply = import_failed.attach({"type": "realtime"})["model_warning"]
        self.assertEqual(import_reply["warning_update_sequence"], 1)
        self.assertEqual(import_reply["state"], "UNKNOWN")
        for field in ("run_id", "layer", "input_sequence", "input_source_timestamp",
                      "prediction_sequence", "feature_age_seconds"):
            self.assertIn(field, import_reply)

        load_failed = RealtimeWarningBridge(enabled=True, manifest=Path("missing-model.json"))
        load_failed.start_session("run-load")
        reply = load_failed.attach({"type": "realtime"})["model_warning"]
        self.assertEqual(reply["warning_update_sequence"], 1)
        self.assertEqual(reply["run_id"], "run-load")
        self.assertEqual(reply["state"], "UNKNOWN")
        json.dumps(reply, allow_nan=False)

    def test_attach_exception_falls_back_with_sequence(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge.start_session("run-A")
        runtime = bridge.runtime

        def explode(*_args, **_kwargs):
            raise RuntimeError("simulated attach failure")

        runtime.attach = explode
        reply = bridge.attach({"type": "realtime"})["model_warning"]
        self.assertEqual(reply["warning_update_sequence"], 1)
        self.assertEqual(reply["state"], "UNKNOWN")
        self.assertEqual(reply["run_id"], "run-A")
        for field in ("layer", "input_sequence", "input_source_timestamp",
                      "prediction_sequence", "feature_age_seconds"):
            self.assertIn(field, reply)

    def test_forced_unknown_uses_neutral_identity_when_runtime_identity_unavailable(self):
        class RuntimeWithoutIdentity:
            def load(self, *_args, **_kwargs):
                pass

            def enable(self):
                pass

            def begin_run(self, _run_id):
                pass

            def attach(self, *_args, **_kwargs):
                raise RuntimeError("simulated attach failure")

        bridge = RealtimeWarningBridge(enabled=True,
                                       runtime_factory=lambda **_kwargs: RuntimeWithoutIdentity())
        bridge.start_session("run-A")
        # Attach exception uses a complete neutral identity because the fake
        # runtime exposes no runtime warning identity.
        warning = bridge.attach({"type": "realtime"})["model_warning"]
        self.assertEqual(warning["warning_update_sequence"], 1)
        self.assertEqual((warning["run_id"], warning["layer"], warning["input_sequence"],
                          warning["input_source_timestamp"], warning["prediction_sequence"],
                          warning["feature_age_seconds"]), ("run-A", 0, 0, 0, 0, 0.0))
        for field in ("platform_instance_id", "geometry_version_id", "raw", "confirmed",
                      "recovery_cancelled"):
            self.assertIn(field, warning)
        self.assertEqual((warning["platform_instance_id"], warning["geometry_version_id"],
                          warning["raw"], warning["confirmed"],
                          warning["recovery_cancelled"]), (0, "", False, False, False))
        self.assertFalse(warning["valid"])
        self.assertFalse(warning["probability_valid"])
        json.dumps(warning, allow_nan=False)

    def test_explicit_run_id_overrides_stale_runtime_identity(self):
        class RuntimeWithOldIdentity:
            def _base_warning(self, reason):
                return {"run_id": "old-run", "layer": 7, "input_sequence": 22,
                        "input_source_timestamp": 12.5, "prediction_sequence": 4,
                        "feature_age_seconds": 0.2, "valid": False,
                        "probability_valid": False, "reason": reason}

        bridge = RealtimeWarningBridge(enabled=True)
        warning = bridge._unknown_warning("lifecycle_failure",
                                          runtime=RuntimeWithOldIdentity(),
                                          run_id="new-run")
        self.assertEqual(warning["run_id"], "new-run")
        self.assertEqual(warning["layer"], 7)
        self.assertEqual(warning["input_sequence"], 22)

    def test_near_limit_never_wraps_or_repeats_and_omits_warning_after_exhaustion(self):
        bridge = RealtimeWarningBridge(enabled=True)
        bridge._warning_update_sequence = MAX_WARNING_UPDATE_SEQUENCE - 1
        last = bridge.attach({"type": "realtime", "model_warning": {"old": True}})
        self.assertEqual(last["model_warning"]["warning_update_sequence"],
                         MAX_WARNING_UPDATE_SEQUENCE)
        exhausted = bridge.attach({"type": "realtime", "model_warning": {"old": True}})
        self.assertNotIn("model_warning", exhausted)
        self.assertEqual(bridge._warning_update_sequence, MAX_WARNING_UPDATE_SEQUENCE)
        self.assertEqual(exhausted["type"], "realtime")


if __name__ == "__main__":
    unittest.main()
