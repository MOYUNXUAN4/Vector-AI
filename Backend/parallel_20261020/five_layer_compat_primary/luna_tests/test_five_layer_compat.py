"""Focused compatibility checks for explicitly selected five-layer sessions."""
import unittest

from test_runtime_adapter import FeatureRuntimePrototype, normalize_unity_packet, packet


class FiveLayerCompatibilityTests(unittest.TestCase):
    def test_selected_five_layers_one_through_five_are_valid(self):
        for layer in range(1, 6):
            with self.subTest(layer=layer):
                row, reason = normalize_unity_packet(packet(
                    layer=layer, selected_session_layers=5))
                self.assertIsNone(reason)
                self.assertTrue(row['gameplay_phase_valid'])

    def test_invalid_five_layer_totals_fail_closed(self):
        for selected in (6, 0, -1, 5.5, '5', True, float('nan')):
            with self.subTest(selected=selected):
                row, reason = normalize_unity_packet(packet(
                    selected_session_layers=selected))
                self.assertFalse(row['gameplay_phase_valid'])
                self.assertEqual(reason, 'unsupported_or_calibration_phase')

    def test_existing_supported_totals_keep_normalization(self):
        for selected in (3, 8, 10):
            for layer in (1, selected):
                with self.subTest(selected=selected, layer=layer):
                    row, reason = normalize_unity_packet(packet(
                        layer=layer, selected_session_layers=selected))
                    self.assertIsNone(reason)
                    self.assertEqual(row['layer'], layer)
                    self.assertEqual(row['selected_session_layers'], selected)
                    self.assertTrue(row['gameplay_phase_valid'])

    def test_layer_above_selected_five_is_rejected(self):
        row, reason = normalize_unity_packet(packet(
            layer=6, selected_session_layers=5))
        self.assertFalse(row['gameplay_phase_valid'])
        self.assertEqual(reason, 'unsupported_or_calibration_phase')

    def test_geometry_identity_and_nan_gates_still_reject(self):
        invalid_packets = (
            packet(layer=3, selected_session_layers=5, geometry_query_valid=False),
            packet(layer=3, selected_session_layers=5,
                   geometry_active_version_id='other'),
            packet(layer=3, selected_session_layers=5,
                   directional_edge_distance=float('nan')),
        )
        expected_reasons = (
            'invalid_geometry_query_or_ownership',
            'geometry_identity_mismatch',
            'missing_or_invalid_directional_edge_distance',
        )
        for p, expected in zip(invalid_packets, expected_reasons):
            with self.subTest(expected=expected):
                row, reason = normalize_unity_packet(p)
                self.assertFalse(row['directional_edge_valid'])
                self.assertEqual(reason, expected)

    def test_calibration_guard_remains_off_by_default(self):
        runtime = FeatureRuntimePrototype()
        runtime.begin_run('r1')
        self.assertFalse(runtime.ingest(packet(
            layer=3, selected_session_layers=5), 20.0))
        self.assertFalse(runtime.inspect(20.0)['feature_ready'])

    def test_source_gap_and_warmup_behavior_are_unchanged(self):
        runtime = FeatureRuntimePrototype(allow_calibration_session_gameplay=True)
        runtime.begin_run('r1')
        for i in range(13):
            self.assertTrue(runtime.ingest(packet(
                i + 1, 1000 + i * .05, layer=3,
                selected_session_layers=5), 20 + i * .05))
        self.assertTrue(runtime.inspect(20.6)['feature_ready'])

        # A valid post-gap packet is retained as the first sample of a fresh
        # segment, but cannot make the feature window ready on its own.
        self.assertTrue(runtime.ingest(packet(
            14, 1001.0, layer=3, selected_session_layers=5), 20.65))
        self.assertFalse(runtime.inspect(20.65)['feature_ready'])
        for i in range(1, 13):
            self.assertTrue(runtime.ingest(packet(
                14 + i, 1001.0 + i * .05, layer=3,
                selected_session_layers=5), 20.65 + i * .05))
        self.assertTrue(runtime.inspect(21.25)['feature_ready'])


if __name__ == '__main__':
    unittest.main()
