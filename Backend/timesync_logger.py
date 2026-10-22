import csv
import os
import re
import threading
import time
from datetime import datetime, timezone


# Sender-side action requests, not Unity-applied input or physical sensor time.
# Appended only to new logs; old raw files and model feature schemas are intact.
WII_CONTROL_FIELDS = (
    "wii_control_schema", "wii_controller_instance_id", "wii_control_sequence",
    "wii_control_timestamp", "wii_control_valid", "wii_control_age_seconds",
    "wii_control_raw_cop_not_one_to_one", "wii_actions_enabled", "wii_joystick_enabled",
    "wii_requested_left", "wii_requested_right", "wii_requested_forward", "wii_requested_backward",
    "wii_issued_left", "wii_issued_right", "wii_issued_forward", "wii_issued_backward",
    "wii_key_left", "wii_key_right", "wii_key_forward", "wii_key_backward",
    "wii_control_balance_x", "wii_control_balance_y", "wii_trigger_lr", "wii_trigger_fb",
    "wii_center_generation", "wii_center_applied", "wii_board_loaded",
    "wii_center_offset_tl", "wii_center_offset_tr", "wii_center_offset_bl", "wii_center_offset_br",
    "wii_corner_floor", "wii_control_event",
)


class TimeSynchronizedLogger:
    """Single-process logger for Wii and game telemetry streams."""

    def __init__(self, username=None, output_dir=None):
        """Create one CSV session log inside the current user's folder.

        The output directory is resolved beside this backend file so logs do
        not depend on the shell's current working directory.  A sanitized
        username is used as a folder name because usernames may contain
        characters that Windows does not allow in paths.
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = output_dir or os.path.join(base_dir, "telemetry_logs")
        user_folder = self._safe_username(username or "unassigned")
        user_dir = os.path.join(output_dir, user_folder)
        os.makedirs(user_dir, exist_ok=True)
        # Keep one raw file and all derived outputs together per session.
        session_id = datetime.now().strftime("session_%Y%m%d_%H%M%S_%f")
        session_dir = os.path.join(user_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)
        self.path = os.path.join(session_dir, "raw.csv")
        self._lock = threading.Lock()
        self._last_seq = {}
        self._received = {}
        self._missing = {}
        self._duplicates = {}
        self._last_sample_signature = {}
        self._first_time = {}
        self._last_time = {}
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=[
            "backend_timestamp", "source", "source_timestamp", "sequence",
            "passed_count",
            "run_id", "run_start_backend_timestamp", "run_state", "session_outcome",
            "session_end_backend_timestamp", "commanded_difficulty", "active_platform_difficulty",
            "tl", "tr", "bl", "br", "offset_tl", "offset_tr", "offset_bl", "offset_br",
            "ratio_tl", "ratio_tr", "ratio_bl", "ratio_br", "total_weight", "cop_x", "cop_z",
            "ball_pos_x", "ball_pos_z", "duplicate_sample",
            "platform_level", "distance_to_hole", "platform_tilt",
            "difficulty", "fall_event", "fall_reason",
            # Calibration and prediction state.  Keep these as independent
            # telemetry fields so future analysis can distinguish a UI
            # attention prediction from an actual geometric edge warning.
            "calibration_mode", "selected_session_layers", "selected_difficulty",
            "attention_state", "prediction_state",
            # Response-experiment metadata and warning episode transitions.
            # These are logged verbatim when present and remain blank for
            # legacy sessions, so old telemetry stays backwards-compatible.
            "response_experiment_id", "experiment_id", "response_condition", "trial_scenario",
            "trial_valid", "response_trial_id", "trial_id", "response_layer_id", "layer_id",
            "warning_source", "warning_type", "warning_active",
            "visible_warning_state",
            "warning_episode_id", "warning_episode_start_time",
            "warning_episode_start_backend_timestamp", "warning_episode_end_time",
            "warning_episode_end_backend_timestamp",
            "attention_episode_id", "attention_episode_enter_time",
            "attention_episode_exit_time", "attention_episode_start_time",
            "attention_episode_end_time",
            # The target/hole position is needed to distinguish an outward
            # path to a legitimate hole from an outward edge-exit trajectory.
            "target_x", "target_z",
            "target_hole_distance", "target_hole_radius", "target_hole_approach_velocity",
            "moving_toward_target_hole", "hole_approach_state",
            # Unity geometry and motion.  These are intentionally recorded
            # verbatim from UDP so offline analysis uses the same geometry as
            # the game's edge-exit check rather than estimating it later.
            "platform_center_x", "platform_center_z", "platform_radius",
            "platform_scale", "platform_difficulty", "platform_radius_source",
            "platform_root_lossy_scale_x", "platform_root_lossy_scale_y", "platform_root_lossy_scale_z",
            "platform_collider_lossy_scale_x", "platform_collider_lossy_scale_y", "platform_collider_lossy_scale_z",
            "ball_velocity_x", "ball_velocity_z", "ball_position_velocity_x", "ball_position_velocity_z",
            "ball_radial_distance", "ball_radial_velocity",
            "nearest_edge_direction_x", "nearest_edge_direction_z",
            "target_edge_direction_x", "target_edge_direction_z",
            "target_edge_distance", "target_edge_radial_velocity",
            "directional_edge_distance", "directional_edge_point_x", "directional_edge_point_z", "directional_edge_valid",
            "ball_radius", "edge_warning_margin", "edge_warning_radius", "edge_warning_distance_threshold",
            "cop_velocity_x", "cop_velocity_z", "cop_speed",
            "fall_direction", "edge_warning_state",
            "edge_warning_time", "edge_warning_backend_timestamp",
            "edge_contact_time", "edge_contact_backend_timestamp",
            "support_lost_time", "support_lost_backend_timestamp",
            "fall_event_time", "fall_event_backend_timestamp",
            # Query ownership is distinct from the active platform; keep source
            # values and missing identity explicit, including Unity-time units.
            "geometry_platform_instance_id", "geometry_version_id",
            "geometry_source_timestamp", "geometry_query_valid",
            "geometry_ownership_valid", "geometry_active_platform_instance_id",
            "geometry_active_version_id",
        ] + list(WII_CONTROL_FIELDS))
        self._writer.writeheader()
        self._file.flush()

    @staticmethod
    def _safe_username(username):
        """Return a filesystem-safe, readable username folder name."""
        value = str(username).strip()
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
        value = value.rstrip(" .") or "unassigned"
        # Avoid Windows device names such as CON, NUL, COM1, and LPT1.
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])", value):
            value = f"_{value}"
        return value[:120]

    def record(self, source, payload, source_timestamp=None, sequence=None):
        now = time.time()
        with self._lock:
            self._received[source] = self._received.get(source, 0) + 1
            if source in self._last_seq and sequence is not None:
                gap = int(sequence) - int(self._last_seq[source]) - 1
                if gap > 0:
                    self._missing[source] = self._missing.get(source, 0) + gap
            if sequence is not None:
                self._last_seq[source] = int(sequence)
            is_unity = source in ("unity", "game")
            duplicate_sample = False
            if is_unity:
                signature = (
                    source_timestamp,
                    payload.get("copX", ""),
                    payload.get("copZ", ""),
                    payload.get("platformLevel", payload.get("passedCount", "")),
                    payload.get("distanceToHole", ""),
                    payload.get("platformTilt", ""),
                )
                duplicate_sample = signature == self._last_sample_signature.get(source)
                self._last_sample_signature[source] = signature
                if duplicate_sample:
                    self._duplicates[source] = self._duplicates.get(source, 0) + 1
            self._first_time.setdefault(source, now)
            self._last_time[source] = now
            self._writer.writerow({
                "backend_timestamp": f"{now:.6f}",
                "source": source,
                "source_timestamp": source_timestamp or "",
                "sequence": "" if sequence is None else sequence,
                "passed_count": payload.get("passedCount", ""),
                "run_id": payload.get("run_id", ""),
                "run_start_backend_timestamp": payload.get("run_start_backend_timestamp", ""),
                "run_state": payload.get("run_state", ""),
                "session_outcome": payload.get("session_outcome", ""),
                "session_end_backend_timestamp": payload.get("session_end_backend_timestamp", ""),
                "commanded_difficulty": payload.get("commanded_difficulty", ""),
                "active_platform_difficulty": payload.get("active_platform_difficulty", ""),
                "tl": payload.get("tl", ""), "tr": payload.get("tr", ""),
                "bl": payload.get("bl", ""), "br": payload.get("br", ""),
                "offset_tl": payload.get("offset_tl", ""),
                "offset_tr": payload.get("offset_tr", ""),
                "offset_bl": payload.get("offset_bl", ""),
                "offset_br": payload.get("offset_br", ""),
                "ratio_tl": payload.get("ratio_tl", ""),
                "ratio_tr": payload.get("ratio_tr", ""),
                "ratio_bl": payload.get("ratio_bl", ""),
                "ratio_br": payload.get("ratio_br", ""),
                "total_weight": payload.get("weight", payload.get("total_weight", "")),
                "cop_x": payload.get("copX", payload.get("cop_x", "")),
                "cop_z": payload.get("copZ", payload.get("cop_z", "")),
                # These are game-ball world coordinates.  Do not substitute
                # Wii COP values: they are distinct signals.
                "ball_pos_x": payload.get("ball_pos_x", "") if is_unity else "",
                "ball_pos_z": payload.get("ball_pos_z", "") if is_unity else "",
                "duplicate_sample": duplicate_sample,
                "platform_level": payload.get("platformLevel", payload.get("passedCount", "")),
                "distance_to_hole": payload.get("distanceToHole", ""),
                "platform_tilt": payload.get("platformTilt", ""),
                "difficulty": payload.get("difficulty", ""),
                "fall_event": payload.get("fallEvent", False),
                "fall_reason": payload.get("fallReason", ""),
                "calibration_mode": payload.get("calibration_mode", payload.get("calibrationMode", "")),
                "selected_session_layers": payload.get("selected_session_layers", payload.get("selectedSessionLayers", "")),
                "selected_difficulty": payload.get("selected_difficulty", payload.get("selectedDifficulty", "")),
                "attention_state": payload.get("attention_state", payload.get("attentionState", "")),
                "prediction_state": payload.get("prediction_state", payload.get("predictionState", "")),
                "response_experiment_id": payload.get("response_experiment_id", payload.get("responseExperimentId", payload.get("experiment_id", payload.get("experimentId", "")))),
                "experiment_id": payload.get("experiment_id", payload.get("experimentId", payload.get("response_experiment_id", payload.get("responseExperimentId", "")))),
                "response_condition": payload.get("response_condition", payload.get("responseCondition", "")),
                "trial_scenario": payload.get("trial_scenario", payload.get("trialScenario", "")),
                "trial_valid": payload.get("trial_valid", payload.get("trialValid", "")),
                "response_trial_id": payload.get("response_trial_id", payload.get("responseTrialId", payload.get("trial_id", payload.get("trialId", "")))),
                "trial_id": payload.get("trial_id", payload.get("trialId", payload.get("response_trial_id", payload.get("responseTrialId", "")))),
                "response_layer_id": payload.get("response_layer_id", payload.get("responseLayerId", payload.get("layer_id", payload.get("layerId", "")))),
                "layer_id": payload.get("layer_id", payload.get("layerId", payload.get("response_layer_id", payload.get("responseLayerId", "")))),
                "warning_source": payload.get("warning_source", payload.get("warningSource", "")),
                "warning_type": payload.get("warning_type", payload.get("warningType", "")),
                "warning_active": payload.get("warning_active", payload.get("warningActive", "")),
                "visible_warning_state": payload.get("visible_warning_state", payload.get("visibleWarningState", "")),
                "warning_episode_id": payload.get("warning_episode_id", payload.get("warningEpisodeId", "")),
                "warning_episode_start_time": payload.get("warning_episode_start_time", payload.get("warningEpisodeStartTime", "")),
                "warning_episode_start_backend_timestamp": payload.get("warning_episode_start_backend_timestamp", payload.get("warningEpisodeStartBackendTimestamp", "")),
                "warning_episode_end_time": payload.get("warning_episode_end_time", payload.get("warningEpisodeEndTime", "")),
                "warning_episode_end_backend_timestamp": payload.get("warning_episode_end_backend_timestamp", payload.get("warningEpisodeEndBackendTimestamp", "")),
                "attention_episode_id": payload.get("attention_episode_id", payload.get("attentionEpisodeId", "")),
                "attention_episode_enter_time": payload.get("attention_episode_enter_time", payload.get("attentionEpisodeEnterTime", "")),
                "attention_episode_exit_time": payload.get("attention_episode_exit_time", payload.get("attentionEpisodeExitTime", "")),
                "attention_episode_start_time": payload.get("attention_episode_start_time", payload.get("attentionEpisodeStartTime", "")),
                "attention_episode_end_time": payload.get("attention_episode_end_time", payload.get("attentionEpisodeEndTime", "")),
                "target_x": payload.get("target_x", payload.get("targetX", "")),
                "target_z": payload.get("target_z", payload.get("targetZ", "")),
                "target_hole_distance": payload.get("target_hole_distance", ""),
                "target_hole_radius": payload.get("target_hole_radius", ""),
                "target_hole_approach_velocity": payload.get("target_hole_approach_velocity", ""),
                "moving_toward_target_hole": payload.get("moving_toward_target_hole", ""),
                "hole_approach_state": payload.get("hole_approach_state", ""),
                "platform_center_x": payload.get("platform_center_x", ""),
                "platform_center_z": payload.get("platform_center_z", ""),
                "platform_radius": payload.get("platform_radius", ""),
                "platform_scale": payload.get("platform_scale", ""),
                "platform_difficulty": payload.get("platform_difficulty", ""),
                "platform_radius_source": payload.get("platform_radius_source", ""),
                "platform_root_lossy_scale_x": payload.get("platform_root_lossy_scale_x", ""),
                "platform_root_lossy_scale_y": payload.get("platform_root_lossy_scale_y", ""),
                "platform_root_lossy_scale_z": payload.get("platform_root_lossy_scale_z", ""),
                "platform_collider_lossy_scale_x": payload.get("platform_collider_lossy_scale_x", ""),
                "platform_collider_lossy_scale_y": payload.get("platform_collider_lossy_scale_y", ""),
                "platform_collider_lossy_scale_z": payload.get("platform_collider_lossy_scale_z", ""),
                "ball_velocity_x": payload.get("ball_velocity_x", ""),
                "ball_velocity_z": payload.get("ball_velocity_z", ""),
                "ball_position_velocity_x": payload.get("ball_position_velocity_x", ""),
                "ball_position_velocity_z": payload.get("ball_position_velocity_z", ""),
                "ball_radial_distance": payload.get("ball_radial_distance", ""),
                "ball_radial_velocity": payload.get("ball_radial_velocity", ""),
                "nearest_edge_direction_x": payload.get("nearest_edge_direction_x", ""),
                "nearest_edge_direction_z": payload.get("nearest_edge_direction_z", ""),
                "target_edge_direction_x": payload.get("target_edge_direction_x", ""),
                "target_edge_direction_z": payload.get("target_edge_direction_z", ""),
                "target_edge_distance": payload.get("target_edge_distance", ""),
                "target_edge_radial_velocity": payload.get("target_edge_radial_velocity", ""),
                "directional_edge_distance": payload.get("directional_edge_distance", ""),
                "directional_edge_point_x": payload.get("directional_edge_point_x", ""),
                "directional_edge_point_z": payload.get("directional_edge_point_z", ""),
                "directional_edge_valid": payload.get("directional_edge_valid", ""),
                "ball_radius": payload.get("ball_radius", ""),
                "edge_warning_margin": payload.get("edge_warning_margin", ""),
                "edge_warning_radius": payload.get("edge_warning_radius", ""),
                "edge_warning_distance_threshold": payload.get("edge_warning_distance_threshold", ""),
                "cop_velocity_x": payload.get("cop_velocity_x", ""),
                "cop_velocity_z": payload.get("cop_velocity_z", ""),
                "cop_speed": payload.get("cop_speed", ""),
                "fall_direction": payload.get("fall_direction", ""),
                "edge_warning_state": payload.get("edge_warning_state", ""),
                "edge_warning_time": payload.get("edge_warning_time", ""),
                "edge_warning_backend_timestamp": payload.get("edge_warning_backend_timestamp", ""),
                "edge_contact_time": payload.get("edge_contact_time", ""),
                "edge_contact_backend_timestamp": payload.get("edge_contact_backend_timestamp", ""),
                "support_lost_time": payload.get("support_lost_time", ""),
                "support_lost_backend_timestamp": payload.get("support_lost_backend_timestamp", ""),
                "fall_event_time": payload.get("fall_event_time", ""),
                "fall_event_backend_timestamp": payload.get("fall_event_backend_timestamp", ""),
                "geometry_platform_instance_id": payload.get("geometry_platform_instance_id", "") if is_unity else "",
                "geometry_version_id": payload.get("geometry_version_id", "") if is_unity else "",
                "geometry_source_timestamp": payload.get("geometry_source_timestamp", "") if is_unity else "",
                "geometry_query_valid": payload.get("geometry_query_valid", "") if is_unity else "",
                "geometry_ownership_valid": payload.get("geometry_ownership_valid", "") if is_unity else "",
                "geometry_active_platform_instance_id": payload.get("geometry_active_platform_instance_id", "") if is_unity else "",
                "geometry_active_version_id": payload.get("geometry_active_version_id", "") if is_unity else "",
                # Never invent neutral controls for old senders, and never
                # attribute a Unity/game packet to a Wii control snapshot.
                **{name: payload.get(name, "") if source == "wii" else ""
                   for name in WII_CONTROL_FIELDS},
            })
            self._file.flush()

    def summary(self):
        with self._lock:
            result = {}
            for source, count in self._received.items():
                duration = max(0.001, self._last_time[source] - self._first_time[source])
                result[source] = {
                    "received": count,
                    "missing": self._missing.get(source, 0),
                    "duplicate_samples": self._duplicates.get(source, 0),
                    "unique_samples": max(0, count - self._duplicates.get(source, 0)),
                    "loss_percent": 100.0 * self._missing.get(source, 0) / max(1, count + self._missing.get(source, 0)),
                    "rate_hz": (count - 1) / duration if count > 1 else 0.0,
                }
            return result

    def close(self):
        with self._lock:
            if not self._file.closed:
                self._file.close()
