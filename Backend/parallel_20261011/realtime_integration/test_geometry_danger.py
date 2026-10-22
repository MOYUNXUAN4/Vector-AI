import copy
import json
import math
import unittest

from bridge import MAX_WARNING_UPDATE_SEQUENCE, RealtimeWarningBridge


def packet(seq=0, stamp=1791770000.0, **changes):
    p = {"type": "unity_game", "run_id": "run-A", "run_state": "running",
         "timestamp": stamp, "time": 123.0, "geometry_source_timestamp": 123.0,
         "sequence": seq, "platformLevel": 2, "platformTilt": .1,
         "calibration_mode": False, "selected_session_layers": 3,
         "platform_scale": 1.0, "geometry_platform_instance_id": -77,
         "geometry_active_platform_instance_id": -77,
         "geometry_version_id": "v1", "geometry_active_version_id": "v1",
         "geometry_query_valid": True, "geometry_ownership_valid": True,
         "directional_edge_valid": True, "directional_edge_distance": .4,
         "ball_radius": .5, "platform_radius": 5.0,
         "ball_radial_velocity": 0.0}
    p.update(changes)
    if "run" in p:
        p["run_id"] = p.pop("run")
    return p


def bridge(**kwargs):
    b = RealtimeWarningBridge(enabled=True, manifest="missing-manifest", **kwargs)
    b.start_session("run-A")
    return b


class GeometryWarningTests(unittest.TestCase):
    def get_warning(self, b, now=1.0):
        return b.attach({"type": "realtime", "difficulty": 4}, now)["geometry_warning"]

    def test_critical_coexists_with_model_unknown_and_positive_is_clear(self):
        b = bridge()
        b.ingest_unity_packet(packet(), 1.0)
        attached = b.attach({"type": "realtime"}, 1.0)
        g, m = attached["geometry_warning"], attached["model_warning"]
        self.assertEqual(g["state"], "CRITICAL")
        self.assertTrue(g["valid"])
        self.assertEqual(g["source"], "geometry_rule")
        self.assertNotIn("probability", g)
        self.assertEqual(m["state"], "UNKNOWN")
        self.assertEqual(g["warning_update_sequence"], m["warning_update_sequence"])
        b.ingest_unity_packet(packet(1, 1791770000.05, directional_edge_distance=1.0), 1.05)
        self.assertEqual(self.get_warning(b, 1.05)["state"], "CLEAR")

    def test_invalid_query_metadata_and_physics_revoke_geometry(self):
        invalid = [
            {"directional_edge_distance": math.nan}, {"ball_radius": True},
            {"ball_radius": -1.0}, {"platform_radius": math.inf},
            {"geometry_source_timestamp": math.nan},
            {"geometry_source_timestamp": 123.31},
            {"geometry_source_timestamp": 122.69},
            {"geometry_active_version_id": "v2"},
            {"geometry_query_valid": False},
        ]
        for change in invalid:
            with self.subTest(change=change):
                b = bridge()
                b.ingest_unity_packet(packet(**change), 1.0)
                w = self.get_warning(b)
                self.assertEqual(w["state"], "UNKNOWN")
                self.assertFalse(w["clearance_valid"])

    def test_freshness_query_cache_and_clock_reversal(self):
        b = bridge()
        b.ingest_unity_packet(packet(0, geometry_source_timestamp=122.69), 1.0)
        self.assertFalse(self.get_warning(b)["valid"])
        b.ingest_unity_packet(packet(1, 1791770000.05, geometry_source_timestamp=123.0), 1.1)
        self.assertFalse(self.get_warning(b, .99)["valid"])
        b.ingest_unity_packet(packet(2, 1791770000.1, time=123.29), 1.2)
        self.assertFalse(self.get_warning(b, 1.22)["valid"])

    def test_foreign_and_delayed_terminal_do_not_revoke_or_refresh(self):
        b = bridge()
        b.ingest_unity_packet(packet(4, 10.4), 1.0)
        original = self.get_warning(b, 1.1)
        b.ingest_unity_packet(packet(5, 10.5, run_id="foreign"), 1.2)
        b.ingest_unity_packet(packet(3, 10.3, run_state="ended"), 1.3)
        after = self.get_warning(b, 1.2)
        self.assertEqual(after["state"], "CRITICAL")
        self.assertEqual(after["input_sequence"], original["input_sequence"])
        self.assertEqual(self.get_warning(b, 1.31)["state"], "UNKNOWN")

    def test_context_change_is_immediate_and_needs_no_model_warmup(self):
        b = bridge()
        b.ingest_unity_packet(packet(0), 1.0)
        self.assertTrue(self.get_warning(b)["valid"])
        b.ingest_unity_packet(packet(1, 1791770000.05, platformLevel=3,
                                     geometry_version_id="v2",
                                     geometry_active_version_id="v2"), 1.05)
        w = self.get_warning(b, 1.05)
        self.assertEqual(w["layer"], 3)
        self.assertEqual(w["geometry_version_id"], "v2")
        self.assertTrue(w["valid"])

    def test_unity_clocks_calibration_phase_and_combined_freshness(self):
        b = bridge(allow_calibration_gameplay=True)
        sample = packet(calibration_mode=True)
        b.ingest_unity_packet(sample, 1.0)
        # Unity timestamp is epoch based; geometry query time uses `time`.
        w = self.get_warning(b, 1.0)
        self.assertTrue(w["valid"])
        self.assertEqual(w["query_age_seconds"], 0.0)
        self.assertEqual(w["geometry_age_seconds"], 0.0)
        b.ingest_unity_packet(packet(1, 1791770000.05, time=123.29), 1.2)
        w = self.get_warning(b, 1.22)
        self.assertFalse(w["valid"])

    def test_missing_query_clock_and_nonfinite_attach_time_are_finite_unknown(self):
        b = bridge()
        invalid = packet()
        del invalid["time"]
        b.ingest_unity_packet(invalid, 1.0)
        self.assertFalse(self.get_warning(b)["valid"])
        result = b.attach({"type": "realtime"}, math.nan)
        json.dumps(result, allow_nan=False)

    def test_invalid_sample_keeps_ordering_fence_after_cache_clear(self):
        b = bridge()
        b.ingest_unity_packet(packet(10, geometry_source_timestamp=122.0), 1.0)
        self.assertFalse(self.get_warning(b)["valid"])
        b.ingest_unity_packet(packet(9, 1791770000.09), 1.01)
        self.assertFalse(self.get_warning(b, 1.01)["valid"])
        b.ingest_unity_packet(packet(11, 1791770000.11), 1.02)
        self.assertTrue(self.get_warning(b, 1.02)["valid"])

    def test_missing_model_required_field_revokes_cached_geometry(self):
        b = bridge()
        b.ingest_unity_packet(packet(), 1.0)
        self.assertTrue(self.get_warning(b)["valid"])
        incomplete = packet(1, 1791770000.01)
        del incomplete["platformTilt"]
        b.ingest_unity_packet(incomplete, 1.01)
        self.assertFalse(self.get_warning(b, 1.01)["valid"])
        b.ingest_unity_packet(packet(2, 1791770000.02), 1.02)
        self.assertTrue(self.get_warning(b, 1.02)["valid"])

    def test_invalid_run_state_and_missing_run_id_preserve_explicit_owner(self):
        for invalid_changes in ({"run_state": "paused"}, {"missing_run_id": True}):
            with self.subTest(invalid_changes=invalid_changes):
                b = bridge()
                b.ingest_unity_packet(packet(), 1.0)
                invalid = packet(1, 1791770000.01)
                if invalid_changes.get("missing_run_id"):
                    del invalid["run_id"]
                else:
                    invalid.update(invalid_changes)
                b.ingest_unity_packet(invalid, 1.01)
                self.assertFalse(self.get_warning(b, 1.01)["valid"])
                b.ingest_unity_packet(packet(2, 1791770000.02), 1.02)
                self.assertTrue(self.get_warning(b, 1.02)["valid"])

    def test_geometry_helper_exceptions_fail_closed_without_breaking_reply(self):
        b = bridge()
        b.ingest_unity_packet(packet(), 1.0)
        b._geometry.warning = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError())
        result = b.attach({"type": "realtime", "difficulty": 4}, 1.01)
        self.assertEqual(result["difficulty"], 4)
        self.assertEqual(result["geometry_warning"]["state"], "UNKNOWN")
        self.assertFalse(result["geometry_warning"]["valid"])

        b2 = bridge()
        b2._geometry.ingest = lambda *_args: (_ for _ in ()).throw(RuntimeError())
        b2.ingest_unity_packet(packet(), 1.0)
        result = b2.attach({"type": "realtime", "difficulty": 5}, 1.01)
        self.assertEqual(result["difficulty"], 5)
        self.assertEqual(result["geometry_warning"]["state"], "UNKNOWN")

    def test_runtime_unavailable_and_attach_fault_do_not_hide_geometry(self):
        def no_runtime(**_kwargs):
            raise ImportError()
        b = bridge(runtime_factory=no_runtime)
        b.ingest_unity_packet(packet(), 1.0)
        self.assertTrue(self.get_warning(b)["valid"])
        b2 = bridge()
        b2.ingest_unity_packet(packet(), 1.0)
        b2.runtime.attach = lambda *_args: (_ for _ in ()).throw(RuntimeError())
        result = b2.attach({"type": "realtime"}, 1.0)
        self.assertTrue(result["geometry_warning"]["valid"])

    def test_restart_end_invalid_state_and_default_off(self):
        b = bridge()
        b.ingest_unity_packet(packet(), 1.0)
        b.start_session("run-B")
        self.assertEqual(b.attach({"type": "realtime"}, 1.01)["geometry_warning"]["state"], "UNKNOWN")
        b.ingest_unity_packet(packet(0, 20, run="run-B"), 2.0)
        b.ingest_unity_packet(packet(1, 20.05, run="run-B", run_state="ended"), 2.05)
        self.assertIsNone(b._geometry._latest)
        off = RealtimeWarningBridge()
        original = {"type": "realtime"}
        self.assertIs(off.attach(original, 1), original)
        self.assertNotIn("geometry_warning", original)

    def test_counter_exhaustion_revokes_both_and_input_is_copied(self):
        b = bridge()
        source = packet()
        b.ingest_unity_packet(source, 1.0)
        source["directional_edge_distance"] = -100
        b._warning_update_sequence = MAX_WARNING_UPDATE_SEQUENCE
        result = b.attach({"type": "realtime", "model_warning": {}, "geometry_warning": {}}, 1.0)
        self.assertNotIn("model_warning", result)
        self.assertNotIn("geometry_warning", result)
        self.assertAlmostEqual(b._geometry._latest["sample"]["clearance"], -.1)
        self.assertEqual(copy.deepcopy(result), result)


if __name__ == "__main__":
    unittest.main()
