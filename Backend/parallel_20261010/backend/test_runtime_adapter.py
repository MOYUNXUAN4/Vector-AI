"""Primary-agent integration/safety checks independent of helper parity tests."""
from copy import deepcopy
import json
import unittest
from runtime_adapter import FeatureRuntimePrototype, normalize_unity_packet, attach_warning


def packet(seq=1, t=1000.0, run='r1', pid=-77, layer=1, **changes):
    p = {'type': 'unity_game', 'run_id': run, 'run_state': 'running',
         'timestamp': t, 'sequence': seq, 'platformLevel': layer, 'platformTilt': .2,
         'calibration_mode': True, 'selected_session_layers': 3, 'platform_scale': 1.2,
         'geometry_platform_instance_id': pid, 'geometry_active_platform_instance_id': pid,
         'geometry_version_id': 'g1', 'geometry_active_version_id': 'g1',
         'geometry_query_valid': True, 'geometry_ownership_valid': True, 'directional_edge_valid': True,
         'directional_edge_distance': 1.0, 'ball_radius': .1, 'platform_radius': 8.,
         'ball_radial_velocity': .2, 'ball_velocity_x': .2, 'ball_velocity_z': 0.,
         'ball_pos_x': 1., 'ball_pos_z': 0., 'platform_center_x': 0., 'platform_center_z': 0.,
         'difficulty': 1}
    p.update(changes)
    return p


class RuntimeTests(unittest.TestCase):
    def runtime(self, ready=True):
        r = FeatureRuntimePrototype(allow_calibration_session_gameplay=True)
        r.begin_run('r1')
        if ready:
            for i in range(13):
                self.assertTrue(r.ingest(packet(i+1, 1000+i*.05), 20+i*.05))
        return r

    def test_live_mapping_matches_csv_logger(self):
        p = packet()
        row, reason = normalize_unity_packet(p)
        self.assertIsNone(reason)
        self.assertEqual(row['source_timestamp'], p['timestamp'])
        self.assertEqual(row['platform_tilt'], p['platformTilt'])
        self.assertEqual(row['layer'], p['platformLevel'])
        self.assertTrue(row['calibration_mode'])
        self.assertTrue(row['gameplay_phase_valid'])

    def test_explicit_calibration_compatibility_default_off(self):
        r = FeatureRuntimePrototype()
        r.begin_run('r1')
        self.assertFalse(r.ingest(packet(), 20))
        self.assertFalse(r.inspect(20)['feature_ready'])

    def test_supported_session_layers_include_every_layer(self):
        for selected in (3, 8, 10):
            for layer in range(1, selected + 1):
                with self.subTest(selected=selected, layer=layer):
                    row, reason = normalize_unity_packet(packet(
                        layer=layer, selected_session_layers=selected))
                    self.assertIsNone(reason)
                    self.assertTrue(row['gameplay_phase_valid'])
                    runtime = FeatureRuntimePrototype(
                        allow_calibration_session_gameplay=True)
                    runtime.begin_run('r1')
                    for i in range(13):
                        self.assertTrue(runtime.ingest(packet(
                            i + 1, 1000 + i * .05, layer=layer,
                            selected_session_layers=selected), 20 + i * .05))
                    self.assertTrue(runtime.inspect(20.6)['feature_ready'])

    def test_invalid_session_totals_fail_closed(self):
        for selected in (None, True, False, 0, -3, 1, 2, 4, 7, 9, 11,
                         8.5, '8', float('nan'), float('inf')):
            with self.subTest(selected=selected):
                row, reason = normalize_unity_packet(packet(
                    selected_session_layers=selected))
                self.assertFalse(row['gameplay_phase_valid'])
                self.assertEqual(reason, 'unsupported_or_calibration_phase')
        p = packet()
        del p['selected_session_layers']
        row, reason = normalize_unity_packet(p)
        self.assertFalse(row['gameplay_phase_valid'])
        self.assertEqual(reason, 'unsupported_or_calibration_phase')

    def test_invalid_session_layers_fail_closed(self):
        for selected in (3, 8, 10):
            for layer in (None, True, False, 0, -1, selected + 1,
                          1.5, '1', float('nan'), float('inf')):
                with self.subTest(selected=selected, layer=layer):
                    row, reason = normalize_unity_packet(packet(
                        layer=layer, selected_session_layers=selected))
                    self.assertFalse(row['gameplay_phase_valid'])
                    self.assertEqual(reason, 'unsupported_or_calibration_phase')
            p = packet(selected_session_layers=selected)
            del p['platformLevel']
            row, reason = normalize_unity_packet(p)
            self.assertFalse(row['gameplay_phase_valid'])
            self.assertEqual(reason, 'unsupported_or_calibration_phase')

    def test_integral_float_layer_fields_preserve_numeric_mapping(self):
        for selected in (3., 8., 10.):
            row, reason = normalize_unity_packet(packet(
                layer=selected, selected_session_layers=selected))
            self.assertIsNone(reason)
            self.assertEqual(type(row['layer']), int)
            self.assertTrue(row['gameplay_phase_valid'])

    def test_multilayer_scale_and_calibration_gates_unchanged(self):
        for selected in (3, 8, 10):
            for scale in (None, True, False, 0, -.1, 2.01,
                          float('nan'), float('inf')):
                with self.subTest(selected=selected, scale=scale):
                    row, reason = normalize_unity_packet(packet(
                        layer=selected, selected_session_layers=selected,
                        platform_scale=scale))
                    self.assertFalse(row['gameplay_phase_valid'])
                    self.assertEqual(reason, 'unsupported_or_calibration_phase')
            for scale in (.01, 2.):
                row, reason = normalize_unity_packet(packet(
                    layer=selected, selected_session_layers=selected,
                    platform_scale=scale))
                self.assertIsNone(reason)
                self.assertTrue(row['gameplay_phase_valid'])
            runtime = FeatureRuntimePrototype()
            runtime.begin_run('r1')
            self.assertFalse(runtime.ingest(packet(
                layer=selected, selected_session_layers=selected), 20))
            self.assertFalse(runtime.inspect(20)['feature_ready'])

    def test_calibration_large_platform_never_ready(self):
        r = self.runtime(False)
        self.assertFalse(r.ingest(packet(platform_scale=15.), 20))
        self.assertFalse(r.inspect(20)['feature_ready'])

    def test_normal_session_and_no_prediction(self):
        r = self.runtime()
        out = r.inspect(20.6)
        self.assertTrue(out['feature_ready'])
        self.assertEqual(out['model_warning']['state'], 'UNKNOWN')
        self.assertFalse(out['model_warning']['probability_valid'])
        json.dumps(out['model_warning'], allow_nan=False)

    def test_geometry_identity_mismatch(self):
        r = self.runtime()
        self.assertFalse(r.ingest(packet(14,1000.65, geometry_active_version_id='other'),20.65))
        self.assertFalse(r.inspect(20.65)['feature_ready'])

    def test_geometry_query_invalid(self):
        r = self.runtime()
        self.assertFalse(r.ingest(packet(14,1000.65, geometry_query_valid=False),20.65))
        self.assertFalse(r.inspect(20.65)['feature_ready'])

    def test_missing_timestamp_not_receive_fallback(self):
        r = self.runtime()
        p = packet(14,1000.65)
        del p['timestamp']
        self.assertFalse(r.ingest(p,20.65))
        self.assertFalse(r.inspect(20.65)['feature_ready'])

    def test_nonfinite_required_features(self):
        for key in ('ball_radius','platform_radius','ball_radial_velocity','directional_edge_distance'):
            r = self.runtime()
            self.assertFalse(r.ingest(packet(14,1000.65, **{key:float('nan')}),20.65))
            self.assertFalse(r.inspect(20.65)['feature_ready'])

    def test_source_and_receive_clock_separation(self):
        r = self.runtime()
        self.assertTrue(r.inspect(20.6)['feature_ready'])
        self.assertFalse(r.inspect(21)['feature_ready'])

    def test_stale_invalidates_without_resurrection(self):
        r = self.runtime()
        self.assertTrue(r.ingest(packet(14,1000.65),21))
        self.assertFalse(r.inspect(21)['feature_ready'])
        self.assertTrue(r.ingest(packet(15,1000.7),21.05))
        self.assertFalse(r.inspect(21.05)['feature_ready'])

    def test_restart_old_run_cannot_mutate_new(self):
        r = self.runtime()
        r.begin_run('new')
        r.ingest(packet(1,2000,run='new'),21)
        self.assertFalse(r.ingest(packet(100,3000,run='r1',run_state='ended'),21.01))
        self.assertTrue(r.ingest(packet(2,2000.05,run='new'),21.05))

    def test_delayed_same_run_terminal_ignored(self):
        r = self.runtime()
        self.assertFalse(r.ingest(packet(2,1000.05,run_state='ended'),20.65))
        self.assertTrue(r.inspect(20.65)['feature_ready'])

    def test_delayed_other_platform_ignored(self):
        r = self.runtime()
        self.assertFalse(r.ingest(packet(2,1000.05,pid=-99),20.65))
        self.assertTrue(r.inspect(20.65)['feature_ready'])

    def test_platform_transition_resets_window(self):
        r = self.runtime()
        self.assertTrue(r.ingest(packet(14,1000.65,pid=-99,layer=2),20.65))
        self.assertFalse(r.inspect(20.65)['feature_ready'])

    def test_terminal_calibration_completion_closes_run(self):
        r = self.runtime()
        self.assertFalse(r.ingest(packet(14,1000.65,run_state='ended',layer=4),20.65))
        self.assertFalse(r.ingest(packet(15,1000.7),20.7))

    def test_receive_order_fence_survives_reset(self):
        r = self.runtime()
        r.ingest(packet(14,1000.65,geometry_query_valid=False),20.65)
        self.assertFalse(r.ingest(packet(15,1000.7),20.5))

    def test_warning_is_additive_not_input_authority(self):
        original = {'type':'realtime','x':.3,'y':.4,'difficulty':2,'rmse':0.,'tl':2.5}
        old = deepcopy(original)
        warning = self.runtime().inspect(20.6)['model_warning']
        new = attach_warning(original, warning)
        self.assertEqual(original, old)
        self.assertEqual({k:new[k] for k in old}, old)
        self.assertEqual(new['model_warning']['state'], 'UNKNOWN')
        json.dumps(new, allow_nan=False)

    def test_buffer_too_small_is_not_ready(self):
        from stream_guard import StreamGuard
        r = self.runtime(False)
        r.guard = StreamGuard(max_samples=2, allow_calibration_session_gameplay=True)
        r.begin_run('r1')
        for i in range(13):
            r.ingest(packet(i+1,1000+i*.05),20+i*.05)
        self.assertFalse(r.inspect(20.6)['feature_ready'])


if __name__ == '__main__':
    unittest.main()
