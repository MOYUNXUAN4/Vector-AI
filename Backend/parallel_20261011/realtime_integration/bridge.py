"""Default-off adapter between the live Falling UDP receiver and warning runtime."""
from __future__ import annotations

import os
import math
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "parallel_20261010" / "backend"
ARTIFACT_MANIFEST = PROJECT_ROOT / "parallel_20261011" / "deployment_refit" / "output" / "artifact" / "manifest.json"
PINNED_MODEL_SHA256 = "01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068"
MAX_WARNING_UPDATE_SEQUENCE = (1 << 63) - 1


def env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


class RealtimeWarningBridge:
    """Owns exactly one run authorized by a start_session message.

    The live start_session command carries Unity's run_id. Ownership binds to
    that exact ID; gameplay packets can never claim or switch ownership.
    """

    def __init__(self, *, enabled=False, allow_calibration_gameplay=False,
                 runtime_factory=None, manifest=ARTIFACT_MANIFEST,
                 pinned_hash=PINNED_MODEL_SHA256):
        self.enabled = bool(enabled)
        self.allow_calibration_gameplay = bool(allow_calibration_gameplay)
        self._runtime_factory = runtime_factory
        self._manifest = manifest
        self._pinned_hash = pinned_hash
        self._runtime = None
        self._authorized = False
        self._owner_run_id = None
        self._closed_run_ids = set()
        self._load_attempted = False
        self._last_sequence = None
        self._last_source_timestamp = None
        self._last_load_error = ""
        self._forced_unknown = None
        self._warning_update_sequence = 0
        self._geometry = None
        if self.enabled:
            try:
                try:
                    from .geometry_danger import GeometryDanger
                except ImportError:
                    from geometry_danger import GeometryDanger
                self._geometry = GeometryDanger(
                    allow_calibration_gameplay=self.allow_calibration_gameplay)
            except Exception:
                self._geometry = None

    def _next_warning_update_sequence(self):
        if self._warning_update_sequence >= MAX_WARNING_UPDATE_SEQUENCE:
            # Fail closed without disrupting the legacy reply path. Missing
            # model_warning is the protocol's explicit clear/revocation signal.
            return None
        self._warning_update_sequence += 1
        return self._warning_update_sequence

    def _unknown_warning(self, reason, *, runtime=None, run_id=None):
        warning = None
        if runtime is not None:
            try:
                warning = dict(runtime._base_warning(reason))
            except Exception:
                try:
                    warning = dict(runtime._identity)
                    warning.update({"schema_version": 1, "experimental": True,
                                    "enabled": False, "model_id": "unavailable",
                                    "model_sha256": ""})
                except Exception:
                    warning = None
        if warning is None:
            warning = {"schema_version": 1, "experimental": True,
                       "enabled": False, "model_id": "unavailable",
                       "model_sha256": ""}
        # Fallback warnings preserve runtime identity when available. Otherwise
        # use explicit neutral identity values rather than guessing a layer.
        if run_id is not None:
            warning["run_id"] = run_id
        else:
            warning.setdefault("run_id", self._owner_run_id or "")
        warning.setdefault("platform_instance_id", 0)
        warning.setdefault("geometry_version_id", "")
        warning.setdefault("layer", 0)
        warning.setdefault("input_sequence", 0)
        warning.setdefault("input_source_timestamp", 0)
        warning.setdefault("prediction_sequence", 0)
        warning.setdefault("feature_age_seconds", 0.0)
        warning.setdefault("raw", False)
        warning.setdefault("confirmed", False)
        warning.setdefault("recovery_cancelled", False)
        warning.update({"state": "UNKNOWN", "valid": False,
                        "probability_valid": False, "strong_probability": 0.0,
                        "reason": reason})
        return warning

    @property
    def runtime(self):
        return self._runtime

    def _ensure_runtime(self):
        if not self.enabled:
            return None
        if self._runtime is None:
            try:
                if self._runtime_factory is None:
                    if str(BACKEND_DIR) not in sys.path:
                        sys.path.insert(0, str(BACKEND_DIR))
                    from warning_runtime import ModelWarningRuntime
                    self._runtime_factory = ModelWarningRuntime
                self._runtime = self._runtime_factory(
                    allow_calibration_session_gameplay=self.allow_calibration_gameplay)
            except Exception as exc:
                self._last_load_error = f"runtime_unavailable:{type(exc).__name__}"
                return None
        if not self._load_attempted:
            self._load_attempted = True
            # Runtime load failure is intentionally non-fatal; its outward
            # warning remains UNKNOWN and gameplay continues normally.
            try:
                self._runtime.load(self._manifest, self._pinned_hash,
                                   allow_experimental=True)
                self._runtime.enable()
            except Exception as exc:
                self._last_load_error = f"model_load_failed:{type(exc).__name__}"
        return self._runtime

    def preload(self):
        """Load and enable the configured model before gameplay starts.

        This is deliberately safe for the legacy service: failures are reported
        as data and never raised to the caller. The runtime's load guard ensures
        later session starts reuse this same native model instance.
        """
        result = {"enabled": self.enabled, "loaded": False, "model_id": None,
                  "reason": "disabled" if not self.enabled else "unavailable"}
        if not self.enabled:
            return result
        runtime = self._ensure_runtime()
        if runtime is None:
            result["reason"] = self._last_load_error or "runtime_unavailable"
            return result
        model = getattr(runtime, "_model", None)
        if model is not None:
            result.update(loaded=True, model_id=getattr(model, "model_id", None), reason="loaded")
        else:
            result["reason"] = self._last_load_error or getattr(runtime, "last_load_error", "") or "model_unavailable"
        return result

    def start_session(self, run_id=None):
        if not self.enabled:
            return
        runtime = self._ensure_runtime()
        if not isinstance(run_id, str) or not run_id.strip():
            if self._owner_run_id is not None:
                self._closed_run_ids.add(self._owner_run_id)
                if runtime is not None:
                    try:
                        runtime.end_run()
                    except Exception:
                        self._set_fallback_unknown("lifecycle_failure")
            self._owner_run_id = None
            self._last_sequence = None
            self._last_source_timestamp = None
            self._authorized = False
            self._set_fallback_unknown("missing_start_run_id")
            self._geometry_clear("missing_start_run_id")
            return
        run_id = run_id.strip()
        if run_id in self._closed_run_ids and run_id != self._owner_run_id:
            return
        if run_id == self._owner_run_id:
            return  # duplicate start command is idempotent
        if self._owner_run_id is not None:
            self._closed_run_ids.add(self._owner_run_id)
            if runtime is not None:
                try:
                    runtime.end_run()
                except Exception:
                    self._set_fallback_unknown("lifecycle_failure")
        self._owner_run_id = None
        self._last_sequence = None
        self._last_source_timestamp = None
        self._owner_run_id = run_id
        self._forced_unknown = None
        if self._geometry is not None:
            try:
                self._geometry.start(run_id)
            except Exception:
                self._geometry_clear("lifecycle_failure")
        if runtime is not None:
            try:
                runtime.begin_run(run_id)
            except Exception:
                self._set_fallback_unknown("lifecycle_failure", run_id=run_id)

    def ingest_unity_packet(self, packet, receive_monotonic=None):
        if not self.enabled or not isinstance(packet, dict) or packet.get("type") != "unity_game":
            return False
        runtime = self._ensure_runtime()
        now = time.monotonic() if receive_monotonic is None else receive_monotonic
        run_id = packet.get("run_id")
        state = packet.get("run_state")
        sequence, stamp = packet.get("sequence"), packet.get("timestamp")

        # Reject delayed terminal and malformed packets before validation so
        # they cannot revoke a newer same-run stream.
        older = ((type(sequence) is int and self._last_sequence is not None and
                  sequence <= self._last_sequence) or
                 (type(stamp) in (int, float) and self._last_source_timestamp is not None and
                  math.isfinite(stamp) and stamp <= self._last_source_timestamp))
        if (run_id == self._owner_run_id or not isinstance(run_id, str)) and older:
            return False

        if self._owner_run_id is None:
            return False
        if not isinstance(run_id, str) or not run_id.strip():
            if runtime is not None:
                self._force_unknown(runtime, "invalid_owner_packet")
            self._geometry_invalidate("invalid_owner_packet")
            return False
        # Foreign delayed/future packets never mutate current runtime state.
        if run_id != self._owner_run_id:
            return False
        if state == "ended":
            self._close_owner(runtime)
            return False
        if state != "running":
            if runtime is not None:
                self._force_unknown(runtime, "invalid_run_state")
            self._geometry_invalidate("invalid_run_state")
            return False

        # Preserve ordering fences even for invalid geometry/context packets;
        # delayed terminal packets after such a gap must still be ignored.
        if type(sequence) is int and sequence >= 0:
            self._last_sequence = sequence
        if type(stamp) in (int, float) and math.isfinite(stamp):
            self._last_source_timestamp = stamp

        required = ("timestamp", "sequence", "platformLevel", "platformTilt",
                    "geometry_platform_instance_id", "geometry_version_id",
                    "geometry_active_platform_instance_id", "geometry_active_version_id",
                    "geometry_query_valid", "geometry_ownership_valid",
                    "directional_edge_valid", "directional_edge_distance",
                    "ball_radius", "platform_radius", "ball_radial_velocity",
                    "calibration_mode", "selected_session_layers", "platform_scale")
        required_missing = any(key not in packet for key in required)
        geometry_required_missing = (required_missing or "time" not in packet or
                                     "geometry_source_timestamp" not in packet)
        if required_missing:
            if runtime is not None:
                self._force_unknown(runtime, "invalid_owner_packet")
        if self._geometry is not None:
            try:
                if geometry_required_missing:
                    self._geometry.invalidate("invalid_owner_packet")
                else:
                    self._geometry.ingest(packet, now)
            except Exception:
                self._geometry_invalidate("geometry_failure")
        if runtime is None:
            return False
        try:
            accepted = runtime.ingest(packet, now)
        except Exception:
            self._force_unknown(runtime, "ingest_failed")
            return False
        if not accepted:
            # Context/geometry resets and malformed samples require fresh
            # warmup, but are not lifecycle events; retain the owner.
            self._force_unknown(runtime, "invalid_owner_packet")
        else:
            self._forced_unknown = None
        return accepted

    def _close_owner(self, runtime):
        if self._owner_run_id is not None:
            self._closed_run_ids.add(self._owner_run_id)
        self._owner_run_id = None
        self._last_sequence = None
        self._last_source_timestamp = None
        self._authorized = False
        self._forced_unknown = None
        self._geometry_clear("ended")
        if runtime is not None:
            try:
                runtime.end_run()
            except Exception:
                self._set_fallback_unknown("lifecycle_failure")

    def _set_fallback_unknown(self, reason, *, run_id=None, runtime=None):
        self._forced_unknown = self._unknown_warning(reason, runtime=runtime,
                                                     run_id=run_id)

    def _geometry_invalidate(self, reason):
        if self._geometry is not None:
            try:
                self._geometry.invalidate(reason)
            except Exception:
                self._geometry = None

    def _geometry_clear(self, reason):
        if self._geometry is not None:
            try:
                self._geometry.clear(reason)
            except Exception:
                self._geometry = None

    def _geometry_unknown_warning(self, reason):
        return {"schema_version": 1, "experimental": True,
                "enabled": bool(self.enabled), "source": "geometry_rule",
                "policy_id": "outer_clearance_nonpositive_v1",
                "run_id": self._owner_run_id or "", "layer": 0,
                "platform_instance_id": 0, "geometry_version_id": "",
                "input_sequence": 0, "input_source_timestamp": 0.0,
                "sample_age_seconds": 0.0, "query_age_seconds": 0.0,
                "geometry_age_seconds": 0.0, "clearance": 0.0,
                "clearance_valid": False, "state": "UNKNOWN", "valid": False,
                "reason": reason}

    def _force_unknown(self, runtime, reason):
        try:
            runtime.guard._clear_stream(reason)
            runtime._unknown(reason, reset_policy=True)
        except Exception:
            self._set_fallback_unknown(reason, runtime=runtime)
        else:
            self._forced_unknown = self._unknown_warning(reason, runtime=runtime)

    def attach(self, realtime_packet, receive_monotonic=None):
        if not self.enabled:
            return realtime_packet
        warning_update_sequence = self._next_warning_update_sequence()
        if warning_update_sequence is None:
            packet = dict(realtime_packet)
            packet.pop("model_warning", None)
            packet.pop("geometry_warning", None)
            return packet
        runtime = self._ensure_runtime()
        now = time.monotonic() if receive_monotonic is None else receive_monotonic
        geometry_warning = None
        if self._geometry is not None:
            try:
                geometry_warning = self._geometry.warning(
                    enabled=self.enabled, run_id=self._owner_run_id or "", now=now)
            except Exception:
                self._geometry_invalidate("geometry_failure")
                geometry_warning = self._geometry_unknown_warning("geometry_failure")
        if geometry_warning is not None:
            geometry_warning["warning_update_sequence"] = warning_update_sequence
        if runtime is None:
            packet = dict(realtime_packet)
            packet["model_warning"] = self._unknown_warning(
                self._last_load_error or "runtime_unavailable")
            packet["model_warning"]["warning_update_sequence"] = warning_update_sequence
            if geometry_warning is not None:
                packet["geometry_warning"] = geometry_warning
            return packet
        try:
            attached = runtime.attach(realtime_packet, now)
            if self._forced_unknown is not None:
                attached["model_warning"] = dict(self._forced_unknown)
            attached["model_warning"]["warning_update_sequence"] = warning_update_sequence
            if geometry_warning is not None:
                attached["geometry_warning"] = geometry_warning
            return attached
        except Exception:
            # Never let experimental telemetry interrupt the legacy reply.
            packet = dict(realtime_packet)
            packet["model_warning"] = (
                dict(self._forced_unknown) if self._forced_unknown is not None else
                self._unknown_warning("bridge_failure", runtime=runtime))
            packet["model_warning"]["warning_update_sequence"] = warning_update_sequence
            if geometry_warning is not None:
                packet["geometry_warning"] = geometry_warning
            return packet


def bridge_from_environment():
    """Construct cheap default-off bridge; model code loads only by opt-in."""
    return RealtimeWarningBridge(
        enabled=env_enabled("FALLING_WARNING_MODEL_ENABLED"),
        allow_calibration_gameplay=env_enabled("FALLING_WARNING_ALLOW_CALIBRATION_GAMEPLAY"))
