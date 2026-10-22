"""Explicit Unity-to-model adapter. No sockets, model loading or gameplay writes."""
from copy import deepcopy
import math
try:
    from .stream_guard import StreamGuard
    from .causal_features import compute_latest_features
except ImportError:
    from stream_guard import StreamGuard
    from causal_features import compute_latest_features


def _integer(value):
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalize_unity_packet(packet):
    """Map the live camelCase fields exactly as the CSV logger does.

    Timestamp is the original Unity `timestamp` in seconds, not backend receive
    time or geometry_source_timestamp (a different clock). No CSV fallbacks.
    Missing/invalid required geometry is not filled from a cache.
    """
    if not isinstance(packet, dict) or packet.get('type') != 'unity_game':
        return None, 'not_unity_game'
    row = deepcopy(packet)
    row['source_timestamp'] = packet.get('timestamp')
    row['layer'] = _integer(packet.get('platformLevel'))
    row['platform_tilt'] = packet.get('platformTilt')
    row['platform_instance_id'] = _integer(packet.get('geometry_platform_instance_id'))
    seq = _integer(packet.get('sequence'))
    row['sequence'] = seq
    # Session calibration_mode can remain true during normal supported-session
    # gameplay. Explicit evidence, not flipping that flag, identifies phase.
    scale = packet.get('platform_scale')
    selected = _integer(packet.get('selected_session_layers'))
    row['gameplay_phase_valid'] = bool(
        selected in (3, 5, 8, 10) and row['layer'] is not None
        and 1 <= row['layer'] <= selected
        and _finite(scale) and 0 < scale <= 2)
    if packet.get('geometry_query_valid') is not True or packet.get('geometry_ownership_valid') is not True:
        row['directional_edge_valid'] = False
        return row, 'invalid_geometry_query_or_ownership'
    active = _integer(packet.get('geometry_active_platform_instance_id'))
    if (active != row['platform_instance_id'] or active is None or
            packet.get('geometry_active_version_id') != packet.get('geometry_version_id')):
        row['directional_edge_valid'] = False
        return row, 'geometry_identity_mismatch'
    if not row['gameplay_phase_valid']:
        row['directional_edge_valid'] = False
        return row, 'unsupported_or_calibration_phase'
    for name in ('directional_edge_distance', 'ball_radial_velocity', 'ball_radius', 'platform_radius'):
        if not _finite(packet.get(name)):
            row['directional_edge_valid'] = False
            return row, 'missing_or_invalid_' + name
    if packet['ball_radius'] <= 0 or packet['platform_radius'] <= 0:
        row['directional_edge_valid'] = False
        return row, 'nonpositive_physical_radius'
    return row, None


class FeatureRuntimePrototype:
    """Real streaming feature assembler, deliberately without a predictor.

    Caller must explicitly begin the current run. Experimental calibration-mode
    gameplay compatibility is an opt-in; defaults cannot admit calibration.
    `enabled` stays false because no frozen predictor/state policy is installed.
    """
    def __init__(self, allow_calibration_session_gameplay=False):
        self.guard = StreamGuard(allow_calibration_session_gameplay=allow_calibration_session_gameplay)

    def begin_run(self, run_id):
        self.guard.begin_run(run_id)

    def ingest(self, packet, receive_monotonic):
        sample, reason = normalize_unity_packet(packet)
        if sample is None:
            return False
        return self.guard.ingest(sample, receive_monotonic)

    def inspect(self, now_monotonic):
        snap = self.guard.snapshot(now_monotonic)
        features = compute_latest_features([r['telemetry'] for r in snap['samples']]) if snap['ready'] else None
        ready = bool(features and features['ready'])
        reason = 'predictor_not_installed' if ready else (
            features['not_ready_reason'] if features else snap['reason'])
        latest = snap['samples'][-1]['telemetry'] if snap['samples'] else {}
        warning = {'schema_version': 1, 'experimental': True, 'enabled': False,
                   'model_id': 'unavailable', 'run_id': latest.get('run_id', ''),
                   'platform_instance_id': latest.get('platform_instance_id', 0),
                   'layer': latest.get('layer', 0), 'input_sequence': latest.get('sequence', 0),
                   'input_source_timestamp': latest.get('source_timestamp', 0.0),
                   'prediction_sequence': 0, 'state': 'UNKNOWN', 'valid': False,
                   'probability_valid': False, 'strong_probability': 0.0, 'reason': reason}
        return {'feature_ready': ready, 'features': features,
                'model_warning': warning}


def attach_warning(realtime_packet, model_warning):
    """Return an additive copy; never change existing input/difficulty fields."""
    if not isinstance(realtime_packet, dict) or realtime_packet.get('type') != 'realtime':
        raise ValueError('warning may only be attached to an existing realtime packet')
    packet = deepcopy(realtime_packet)
    packet['model_warning'] = deepcopy(model_warning)
    return packet
