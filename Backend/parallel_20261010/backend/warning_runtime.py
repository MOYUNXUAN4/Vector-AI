"""Opt-in, isolated strong-warning runtime engine.

No sockets, service lifecycle, gameplay writes, or implicit model activation.
"""
from collections import deque
import copy
import math

try:  # Package imports.
    from .runtime_adapter import normalize_unity_packet, attach_warning
    from .stream_guard import StreamGuard
    from .causal_features import compute_latest_features
    from .model_artifact import ModelArtifact
    from .alarm_policy import StrongAlarmPolicy, compute_recovery
except ImportError:  # Script imports with this directory on sys.path.
    from runtime_adapter import normalize_unity_packet, attach_warning
    from stream_guard import StreamGuard
    from causal_features import compute_latest_features
    from model_artifact import ModelArtifact
    from alarm_policy import StrongAlarmPolicy, compute_recovery


class ModelWarningRuntime:
    def __init__(self, *, allow_calibration_session_gameplay=False,
                 max_samples=128, event_capacity=128, booster_factory=None):
        self.guard = StreamGuard(max_samples=max_samples,
            allow_calibration_session_gameplay=allow_calibration_session_gameplay)
        if type(event_capacity) is not int or event_capacity < 1:
            raise ValueError("event_capacity must be a positive integer")
        self._events = deque(maxlen=event_capacity)
        self._booster_factory = booster_factory
        self._model = None
        self._enabled = False
        self._policy = None
        self._owner_run_id = None
        self._segment_generation = None
        self._last_prediction_source = None
        self._last_prediction_receive = None
        self._prediction_sequence = 0
        self._last_warning = None
        self._last_load_error = "model_not_loaded"
        self._identity = {"run_id": "", "platform_instance_id": 0,
                          "layer": 0, "geometry_version_id": "",
                          "input_sequence": 0, "input_source_timestamp": 0.0}
        self._last_state = "UNKNOWN"

    def load(self, manifest, pinnedhash, allow_experimental=False):
        """Load a hash-pinned artifact; any failure removes a previously loaded model."""
        self._model = None
        self._policy = None
        self._enabled = False
        self._last_prediction_source = None
        self._last_prediction_receive = None
        self._prediction_sequence = 0
        try:
            kwargs = {"expected_model_sha256": pinnedhash,
                      "allow_experimental": allow_experimental}
            if self._booster_factory is not None:
                kwargs["booster_factory"] = self._booster_factory
            self._model = ModelArtifact.load(manifest, **kwargs)
            self._policy = StrongAlarmPolicy(self._model.threshold)
            self._last_load_error = ""
            self._publish(self._base_warning("loaded_disabled"))
            return True
        except Exception as exc:
            self._model = None
            self._policy = None
            self._enabled = False
            self._last_warning = None
            self._last_load_error = f"{type(exc).__name__}: {exc}"
            self._publish(self._base_warning("model_load_failed"))
            return False

    @property
    def last_load_error(self):
        return self._last_load_error

    def enable(self):
        self._enabled = self._model is not None
        if self._policy is not None:
            self._policy.reset()
        self._last_warning = None
        self._last_prediction_source = None
        self._last_prediction_receive = None
        self._publish(self._base_warning("enabled" if self._enabled else "model_unavailable"))
        return self._enabled

    def disable(self):
        self._enabled = False
        if self._policy is not None:
            self._policy.reset()
        self._last_warning = None
        self._last_prediction_source = None
        self._last_prediction_receive = None
        self._publish(self._base_warning("disabled"))

    def reset(self):
        self.guard.reset()
        self._owner_run_id = None
        self._segment_generation = None
        self._last_prediction_source = None
        self._last_prediction_receive = None
        if self._policy is not None:
            self._policy.reset()
        self._last_warning = None
        self._identity = {"run_id": "", "platform_instance_id": 0,
                          "layer": 0, "geometry_version_id": "",
                          "input_sequence": 0, "input_source_timestamp": 0.0}
        self._publish(self._base_warning("reset"))

    def end_run(self):
        self.guard.end_run()
        self._owner_run_id = None
        self._segment_generation = None
        self._last_prediction_source = None
        self._last_prediction_receive = None
        if self._policy is not None:
            self._policy.reset()
        self._publish(self._base_warning("ended"))

    def begin_run(self, run_id):
        self.guard.begin_run(run_id)
        self._owner_run_id = run_id
        self._segment_generation = None
        self._last_prediction_source = None
        self._last_prediction_receive = None
        self._prediction_sequence = 0
        self._last_warning = None
        self._identity = {"run_id": run_id, "platform_instance_id": 0,
                          "layer": 0, "geometry_version_id": "",
                          "input_sequence": 0, "input_source_timestamp": 0.0}
        if self._policy is not None:
            self._policy.reset()
        self._publish(self._base_warning("run_started"))

    def _sync_segment(self, snapshot):
        generation = snapshot.get("segment_generation")
        if generation != self._segment_generation:
            self._segment_generation = generation
            self._last_prediction_source = None
            self._last_prediction_receive = None
            if self._policy is not None:
                self._policy.reset()

    def _base_warning(self, reason):
        model = self._model
        return {
            "schema_version": 1,
            "experimental": True,
            "enabled": bool(self._enabled and model is not None),
            "model_id": model.model_id if model is not None else "mock-unavailable",
            "model_sha256": model.sha256 if model is not None else "",
            **copy.deepcopy(self._identity),
            "prediction_sequence": self._prediction_sequence,
            "state": "UNKNOWN",
            "valid": False,
            "probability_valid": False,
            "strong_probability": 0.0,
            "feature_age_seconds": 0.0,
            "reason": str(reason),
            "raw": False,
            "confirmed": False,
            "recovery_cancelled": False,
        }

    def _publish(self, warning):
        old = self._last_state
        new = warning["state"]
        if old != new:
            self._events.append({"run_id": warning["run_id"],
                                 "platform_instance_id": warning["platform_instance_id"],
                                 "layer": warning["layer"],
                                 "geometry_version_id": warning["geometry_version_id"],
                                 "input_sequence": warning["input_sequence"],
                                 "input_source_timestamp": warning["input_source_timestamp"],
                                 "prediction_sequence": warning["prediction_sequence"],
                                 "state": new, "previous_state": old,
                                 "reason": warning["reason"]})
        self._last_state = new
        self._last_warning = copy.deepcopy(warning)
        return copy.deepcopy(warning)

    def _unknown(self, reason, *, reset_policy=False):
        if reset_policy and self._policy is not None:
            self._policy.reset()
        return self._publish(self._base_warning(reason))

    def ingest(self, packet, receiptmonotonic):
        if self._owner_run_id is None:
            return False
        sample, _ = normalize_unity_packet(packet)
        if sample is None or sample.get("run_id") != self._owner_run_id:
            return False
        if (isinstance(receiptmonotonic, bool) or
                not isinstance(receiptmonotonic, (int, float)) or
                not math.isfinite(receiptmonotonic)):
            self.guard.ingest(sample, receiptmonotonic)
            self._unknown("invalid_receive_time", reset_policy=True)
            return False
        accepted = self.guard.ingest(sample, receiptmonotonic)
        snapshot = self.guard.metadata_snapshot(receiptmonotonic)
        prior_generation = self._segment_generation
        self._sync_segment(snapshot)
        if not accepted:
            # A real segment reset clears policy; duplicates and foreign packets
            # leave the generation unchanged and cannot alter active warning.
            if (snapshot.get("segment_generation") != prior_generation and
                    snapshot.get("reason") not in ("duplicate_or_out_of_order", "run_not_owned")):
                self._unknown(snapshot.get("reason", "invalid_stream"), reset_policy=True)
            return False

        self._identity = {"run_id": sample["run_id"],
                          "platform_instance_id": sample["platform_instance_id"],
                          "layer": sample["layer"],
                          "geometry_version_id": sample["geometry_version_id"],
                          "input_sequence": sample["sequence"],
                          "input_source_timestamp": float(sample["source_timestamp"])}
        if not self._enabled or self._model is None:
            return True
        if not snapshot.get("ready"):
            self._unknown(snapshot.get("reason", "warming_up"), reset_policy=True)
            return True
        try:
            raw_clearance = float(sample["directional_edge_distance"]) - float(sample["ball_radius"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raw_clearance = float("nan")
        if not math.isfinite(raw_clearance) or raw_clearance <= 0:
            self._unknown("nonpositive_clearance", reset_policy=True)
            return True
        if self._last_prediction_source is not None and (
                sample["source_timestamp"] - self._last_prediction_source <
                self._model.decision_interval_seconds - 1e-9):
            return True

        snapshot = self.guard.snapshot(receiptmonotonic)
        rows = [row["telemetry"] for row in snapshot["samples"]]
        features = compute_latest_features(rows)
        if not features.get("ready"):
            self._unknown(features.get("not_ready_reason", "features_not_ready"), reset_policy=True)
            return True
        clearance = float(features["clearance"])
        if not math.isfinite(clearance) or clearance <= 0:
            self._last_prediction_source = float(sample["source_timestamp"])
            self._last_prediction_receive = float(receiptmonotonic)
            self._unknown("nonpositive_clearance", reset_policy=True)
            return True

        recovery_rows = []
        for row in rows:
            distance = row.get("directional_edge_distance")
            radius = row.get("ball_radius")
            stamp = row.get("source_timestamp")
            try:
                converted_clearance = float(distance) - float(radius)
            except (TypeError, ValueError, OverflowError):
                converted_clearance = None
            recovery_rows.append({"timestamp": stamp,
                                  "clearance": converted_clearance,
                                  "ball_radial_velocity": row.get("ball_radial_velocity")})
        recovery = compute_recovery(recovery_rows)
        try:
            probability = self._model.predict_probability(features)
            result = self._policy.step(probability, clearance,
                sample["source_timestamp"],
                (sample["run_id"], sample["platform_instance_id"], sample["layer"],
                 sample["geometry_version_id"], self._segment_generation),
                joint_recovery=recovery["joint_recovery"])
        except Exception:
            self._last_prediction_source = float(sample["source_timestamp"])
            self._last_prediction_receive = float(receiptmonotonic)
            self._unknown("prediction_failed", reset_policy=True)
            return True
        self._last_prediction_source = float(sample["source_timestamp"])
        self._last_prediction_receive = float(receiptmonotonic)
        self._prediction_sequence += 1
        if not result.get("accepted"):
            self._unknown(result.get("reason", "policy_rejected"))
            return True
        warning = self._base_warning(result["reason"])
        warning.update(state=result["state"], valid=True, probability_valid=True,
                       strong_probability=float(probability), raw=bool(result["raw"]),
                       confirmed=bool(result["confirmed"]),
                       recovery_cancelled=bool(result["canceled"]),
                       feature_age_seconds=0.0,
                       prediction_sequence=self._prediction_sequence)
        self._publish(warning)
        return True

    def warning(self, now):
        snapshot = self.guard.metadata_snapshot(now)
        self._sync_segment(snapshot)
        if not self._enabled or self._model is None:
            reason = "disabled" if self._model is not None else (self._last_load_error or "model_unavailable")
            return self._base_warning(reason)
        if not snapshot.get("ready"):
            return self._unknown(snapshot.get("reason", "warming_up"), reset_policy=True)
        if self._last_warning is None:
            return self._base_warning("awaiting_prediction")
        result = copy.deepcopy(self._last_warning)
        if self._last_prediction_receive is not None:
            result["feature_age_seconds"] = max(0.0, float(now) - self._last_prediction_receive)
        return result

    def attach(self, realtime, now):
        return attach_warning(realtime, self.warning(now))

    def drain_events(self):
        result = copy.deepcopy(list(self._events))
        self._events.clear()
        return result
