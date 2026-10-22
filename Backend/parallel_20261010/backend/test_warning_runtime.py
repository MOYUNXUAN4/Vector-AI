import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

try:
    from backend.causal_features import FEATURE_NAMES
    from backend.warning_runtime import ModelWarningRuntime
except ImportError:
    from causal_features import FEATURE_NAMES
    from warning_runtime import ModelWarningRuntime


class MockBooster:
    def __init__(self):
        self.params = {"objective": "binary"}
        self.prediction = .9

    def feature_name(self):
        return list(FEATURE_NAMES)

    def num_feature(self):
        return len(FEATURE_NAMES)

    def predict(self, rows):
        return [self.prediction]


def unity_packet(seq, source, *, run="r1", pid=-77, layer=1, clearance=.2,
                 velocity=.2, calibration=True, **changes):
    packet = {
        "type": "unity_game", "run_id": run, "run_state": "running",
        "timestamp": source, "sequence": seq, "platformLevel": layer,
        "platformTilt": .2, "calibration_mode": calibration,
        "selected_session_layers": 3, "platform_scale": 1.2,
        "geometry_platform_instance_id": pid,
        "geometry_active_platform_instance_id": pid,
        "geometry_version_id": "g1", "geometry_active_version_id": "g1",
        "geometry_query_valid": True, "geometry_ownership_valid": True,
        "directional_edge_valid": True,
        "directional_edge_distance": clearance + .1, "ball_radius": .1,
        "platform_radius": 8., "ball_radial_velocity": velocity,
        "ball_velocity_x": velocity, "ball_velocity_z": 0.,
        "ball_pos_x": 1., "ball_pos_z": 0., "platform_center_x": 0.,
        "platform_center_z": 0., "difficulty": 1.,
        "cop_x": 0., "cop_z": 0.,
    }
    packet.update(changes)
    return packet


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        model_file = self.root / "mock.txt"
        model_file.write_bytes(b"mock native booster bytes")
        self.digest = hashlib.sha256(model_file.read_bytes()).hexdigest()
        self.manifest = self.root / "manifest.json"
        manifest = {
            "schema_version": 1, "model_id": "mock-approved", "target": "strong",
            "prediction_horizon_seconds": .75, "features": list(FEATURE_NAMES),
            "medians": {name: 0.0 for name in FEATURE_NAMES}, "threshold": .75,
            "confirmation_points": 2, "decision_interval_seconds": .05,
            "max_decision_gap_seconds": .1,
            "recovery_policy": "joint_ball_inward_and_clearance_gain_v1",
            "approved_for_experimental_runtime": True, "model_file": "mock.txt",
            "model_sha256": self.digest,
        }
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        self.booster = MockBooster()
        self.runtime = ModelWarningRuntime(allow_calibration_session_gameplay=True,
                                           booster_factory=lambda _: self.booster)

    def tearDown(self):
        self.temp.cleanup()

    def load_enabled(self):
        self.assertTrue(self.runtime.load(self.manifest, self.digest, True))
        self.assertFalse(self.runtime.enable() is False)
        self.runtime.begin_run("r1")

    def send(self, seq, source, receipt, **kwargs):
        return self.runtime.ingest(unity_packet(seq, source, **kwargs), receipt)

    def warm(self, count=13, **kwargs):
        for i in range(count):
            self.assertTrue(self.send(i, 1000 + i * .05, 20 + i * .05, **kwargs))

    def test_real_loader_mock_booster_prediction_and_repeat_reads_do_not_confirm(self):
        self.load_enabled()
        self.warm(count=11)
        warning = self.runtime.warning(20.5)
        self.assertTrue(warning["probability_valid"])
        self.assertEqual(warning["state"], "SAFE")
        prediction_sequence = warning["prediction_sequence"]
        for _ in range(4):
            self.assertEqual(self.runtime.warning(20.5)["prediction_sequence"], prediction_sequence)
        self.assertEqual(self.runtime.warning(20.5)["state"], "SAFE")
        self.assertTrue(self.send(11, 1000.55, 20.55))
        self.assertEqual(self.runtime.warning(20.55)["state"], "STRONG")

    def test_prediction_identity_and_age_stay_on_evaluated_packet(self):
        self.load_enabled()
        self.warm(count=11)
        first = self.runtime.warning(20.5)
        self.assertEqual(first["input_sequence"], 10)
        self.assertTrue(self.send(11, 1000.51, 20.51))
        later = self.runtime.warning(20.61)
        self.assertEqual(later["input_sequence"], 10)
        self.assertEqual(later["input_source_timestamp"], 1000.5)
        self.assertAlmostEqual(later["feature_age_seconds"], .11)

    def test_reverse_time_read_resets_confirmation_policy(self):
        self.load_enabled()
        self.warm()
        self.send(13, 1000.65, 20.65)
        self.assertEqual(self.runtime.warning(20.65)["state"], "STRONG")
        self.assertEqual(self.runtime.warning(20.64)["state"], "UNKNOWN")
        self.assertTrue(self.send(14, 1000.70, 20.70))
        warning = self.runtime.warning(20.70)
        self.assertEqual(warning["state"], "SAFE")
        self.assertFalse(warning["confirmed"])

    def test_005_cadence_and_probability_off(self):
        self.load_enabled()
        self.warm()
        before = self.runtime.warning(20.6)["prediction_sequence"]
        self.assertTrue(self.send(13, 1000.65, 20.65))
        self.assertEqual(self.runtime.warning(20.65)["prediction_sequence"], before + 1)
        self.booster.prediction = .2
        self.assertTrue(self.send(14, 1000.70, 20.70))
        warning = self.runtime.warning(20.70)
        self.assertEqual(warning["state"], "SAFE")
        self.assertFalse(warning["raw"])

    def test_joint_recovery_cancels_but_cop_or_clearance_gain_alone_does_not(self):
        self.load_enabled()
        # Model is strong, but outward/no inward radial movement must not recover.
        for i in range(14):
            self.send(i, 1000 + i*.05, 20 + i*.05, velocity=.1,
                      clearance=.2 + max(0, i-9)*.01, cop_x=1000.)
        self.assertEqual(self.runtime.warning(20.65)["state"], "STRONG")
        for i in range(14, 19):
            self.send(i, 1000 + i*.05, 20 + i*.05, velocity=.1,
                      clearance=.25 + (i-14)*.02, cop_x=1000.)
        self.assertEqual(self.runtime.warning(20.9)["state"], "STRONG")
        for i in range(19, 22):
            self.send(i, 1000 + i*.05, 20 + i*.05, velocity=-.2,
                      clearance=.35 + (i-19)*.02, cop_x=1000.)
        warning = self.runtime.warning(21.05)
        self.assertEqual(warning["state"], "SAFE")
        self.assertTrue(warning["recovery_cancelled"])

    def test_disabled_load_failure_and_predict_failure_unknown(self):
        self.runtime.begin_run("r1")
        self.warm()
        self.assertEqual(self.runtime.warning(20.6)["state"], "UNKNOWN")
        self.assertTrue(self.runtime.load(self.manifest, self.digest, True))
        self.runtime.enable()
        self.runtime.begin_run("r1")
        self.warm()
        self.assertFalse(self.runtime.load(self.manifest, "0"*64, True))
        self.assertEqual(self.runtime.warning(20.6)["state"], "UNKNOWN")
        self.assertFalse(self.runtime.enable())
        self.load_enabled()
        self.booster.predict = lambda rows: (_ for _ in ()).throw(RuntimeError("mock failure"))
        self.warm()
        self.assertEqual(self.runtime.warning(20.6)["state"], "UNKNOWN")
        self.assertEqual(self.runtime.warning(20.6)["reason"], "prediction_failed")

    def test_stale_context_gap_and_restart_unknown_reset(self):
        self.load_enabled()
        self.warm()
        self.send(13, 1000.65, 20.65)
        self.assertEqual(self.runtime.warning(20.65)["state"], "STRONG")
        self.assertEqual(self.runtime.warning(21.0)["state"], "UNKNOWN")
        self.send(14, 1000.70, 21.01)
        self.assertEqual(self.runtime.warning(21.01)["state"], "UNKNOWN")
        self.send(15, 1000.75, 21.06, pid=-90, layer=2)
        self.assertEqual(self.runtime.warning(21.06)["state"], "UNKNOWN")
        # Build a new segment, then force a source discontinuity.
        for i in range(16, 29):
            self.send(i, 1000.8 + (i-16)*.05, 21.11 + (i-16)*.05, pid=-90, layer=2)
        self.assertTrue(self.runtime.warning(21.72)["valid"])
        self.send(29, 1001.7, 21.76, pid=-90, layer=2)
        self.assertEqual(self.runtime.warning(21.76)["state"], "UNKNOWN")
        self.runtime.begin_run("new")
        self.assertFalse(self.send(100, 9000., 22., run="r1"))
        self.assertEqual(self.runtime.warning(22.)["state"], "UNKNOWN")

    def test_old_run_duplicate_and_attach_are_non_mutating(self):
        self.load_enabled()
        self.warm()
        self.send(13, 1000.65, 20.65)
        self.assertEqual(self.runtime.warning(20.65)["state"], "STRONG")
        seq = self.runtime.warning(20.65)["prediction_sequence"]
        self.assertFalse(self.send(13, 1000.65, 20.66))
        self.assertFalse(self.send(100, 9000., 20.67, run="old", run_state="ended"))
        original = {"type": "realtime", "difficulty": 4, "x": 1.}
        attached = self.runtime.attach(original, 20.67)
        self.assertEqual(original, {"type": "realtime", "difficulty": 4, "x": 1.})
        self.assertEqual(attached["difficulty"], 4)
        self.assertEqual(attached["model_warning"]["prediction_sequence"], seq)
        json.dumps(attached, allow_nan=False)

    def test_nonpositive_clearance_no_inference_and_event_ledger(self):
        self.load_enabled()
        self.warm(clearance=-.01)
        warning = self.runtime.warning(20.6)
        self.assertEqual(warning["state"], "UNKNOWN")
        self.assertFalse(warning["probability_valid"])
        self.assertEqual(warning["strong_probability"], 0.0)
        events = self.runtime.drain_events()
        self.assertLessEqual(len(events), 128)
        self.assertEqual(self.runtime.drain_events(), [])


if __name__ == "__main__":
    unittest.main()
