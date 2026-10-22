import unittest

from stream_guard import StreamGuard


def packet(seq, source=None, **changes):
    data = {"run_id": "r1", "platform_instance_id": -2,
            "geometry_version_id": "g1", "layer": 1,
            "source_timestamp": 1_700_000_000.0 + seq * 0.05 if source is None else source,
            "sequence": seq, "run_state": "running", "calibration_mode": False,
            "directional_edge_valid": True}
    data.update(changes)
    return data


class StreamGuardTests(unittest.TestCase):
    def guard(self, **kw):
        g = StreamGuard(**kw)
        g.begin_run("r1")
        return g

    def test_warmup_timebase_and_ready(self):
        g = self.guard()
        self.assertTrue(g.ingest(packet(0), 10.0))
        self.assertFalse(g.snapshot(10.0)["ready"])
        for i in range(1, 12):
            self.assertTrue(g.ingest(packet(i), 10.0 + i * 0.05))
        self.assertTrue(g.snapshot(10.55)["ready"])

    def test_stale_invalidates_history(self):
        g = self.guard()
        g.ingest(packet(0), 1.0)
        self.assertEqual(g.snapshot(1.31)["reason"], "stale_stream")
        self.assertEqual(g.snapshot(1.31)["samples"], [])
        self.assertTrue(g.ingest(packet(1), 1.32))
        self.assertEqual(len(g.snapshot(1.32)["samples"]), 1)

    def test_invalid_nan_boolean_missing(self):
        for bad, why in ((packet(0, source=float("nan")), "invalid_source_timestamp"),
                         (packet(0, sequence=True), "invalid_sequence"),
                         ({"run_id": "r1"}, "missing_fields"),
                         (packet(0, calibration_mode=1), "invalid_boolean")):
            g = self.guard()
            self.assertFalse(g.ingest(bad, 1.0))
            self.assertEqual(g.snapshot(1.0)["reason"], why)

    def test_calibration_session_gameplay_opt_in_requires_phase(self):
        cal = packet(0, calibration_mode=True)
        g = self.guard()
        self.assertFalse(g.ingest(cal, 1.0))
        g = StreamGuard(allow_calibration_session_gameplay=True)
        g.begin_run("r1")
        self.assertFalse(g.ingest(cal, 1.0))
        self.assertTrue(g.ingest(dict(cal, gameplay_phase_valid=True), 1.1))
        self.assertFalse(g.ingest(packet(2, calibration_mode=True, gameplay_phase_valid=False), 1.2))

    def test_duplicates_and_old_context_do_not_switch_run(self):
        g = self.guard()
        self.assertTrue(g.ingest(packet(2), 1.0))
        self.assertFalse(g.ingest(packet(2), 1.01))
        self.assertFalse(g.ingest(packet(3, run_id="old"), 1.02))
        self.assertFalse(g.ingest(packet(1, platform_instance_id=-3), 1.025))
        self.assertFalse(g.ingest(packet(3, run_id="old", run_state="ended"), 1.027))
        self.assertEqual(len(g.snapshot(1.02)["samples"]), 1)
        self.assertTrue(g.ingest(packet(3), 1.03))

    def test_context_gap_sequence_reset_and_bound(self):
        g = self.guard(max_samples=2)
        g.ingest(packet(0), 1.0)
        g.ingest(packet(1, geometry_version_id="g2"), 1.05)
        self.assertEqual(len(g.snapshot(1.05)["samples"]), 1)
        g.ingest(packet(3, geometry_version_id="g2"), 1.10)
        self.assertEqual(len(g.snapshot(1.10)["samples"]), 1)
        g.ingest(packet(4, geometry_version_id="g2", source_timestamp=1_700_000_000.3), 1.15)
        self.assertEqual(len(g.snapshot(1.15)["samples"]), 1)
        g.ingest(packet(5, geometry_version_id="g2", source_timestamp=1_700_000_000.35), 1.20)
        self.assertLessEqual(len(g.snapshot(1.20)["samples"]), 2)

    def test_missing_context_end_restart_and_copy(self):
        g = self.guard()
        self.assertFalse(g.ingest(packet(0, platform_instance_id=-1), 1.0))
        self.assertTrue(g.ingest(packet(0), 1.1))
        view = g.snapshot(1.1)
        view["samples"][0]["telemetry"]["extra"] = {"nested": [1]}
        g.ingest(packet(1, run_state="running", extra={"nested": [2]}), 1.12)
        view2 = g.snapshot(1.12)
        view2["samples"][1]["telemetry"]["extra"]["nested"][0] = -1
        self.assertEqual(g.snapshot(1.12)["samples"][1]["telemetry"]["extra"]["nested"], [2])
        view["samples"][0]["telemetry"]["layer"] = "tampered"
        self.assertEqual(g.snapshot(1.12)["samples"][0]["telemetry"]["layer"], 1)
        self.assertFalse(g.ingest(packet(2, run_state="ended"), 1.15))
        self.assertFalse(g.ingest(packet(2), 1.2))
        g.begin_run("r1")
        self.assertTrue(g.ingest(packet(0), 1.3))
        self.assertFalse(g.ingest(packet(1, run_id="prior"), 1.31))

    def test_status_is_strict_and_unknown(self):
        status = StreamGuard.status()
        self.assertEqual(status["state"], "UNKNOWN")
        self.assertFalse(status["probability_valid"])
        self.assertFalse(status["enabled"])
        self.assertFalse(status["model_warning"]["valid"])


if __name__ == "__main__":
    unittest.main()
