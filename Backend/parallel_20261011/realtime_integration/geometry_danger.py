"""Independent, experimental geometric clearance warning.

This rule consumes only a fresh, validated Unity geometry sample. It has no
model probabilities or prediction state and is intentionally not a predictor.
"""
from __future__ import annotations

import math
import sys
import time
from copy import deepcopy
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "parallel_20261010" / "backend"


class GeometryDanger:
    def __init__(self, *, allow_calibration_gameplay=False):
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))
        try:
            from runtime_adapter import normalize_unity_packet
            from stream_guard import StreamGuard
        except ImportError:
            from parallel_20261010.backend.runtime_adapter import normalize_unity_packet
            from parallel_20261010.backend.stream_guard import StreamGuard
        self._normalize = normalize_unity_packet
        self._guard = StreamGuard(warmup_seconds=0, max_source_gap=.1,
                                  stale_timeout=.3,
                                  allow_calibration_session_gameplay=allow_calibration_gameplay)
        self._owner = None
        self._latest = None
        self._reason = "no_run"

    def start(self, run_id):
        self.clear("new_run")
        self._owner = run_id
        if isinstance(run_id, str) and run_id.strip():
            self._guard.begin_run(run_id)
        else:
            self._guard.reset()

    def clear(self, reason="cleared"):
        self._latest = None
        self._reason = reason
        try:
            self._guard.end_run()
        except Exception:
            pass
        self._owner = None

    @staticmethod
    def _finite(value):
        if type(value) not in (int, float):
            return False
        try:
            return math.isfinite(value)
        except (OverflowError, TypeError, ValueError):
            return False

    def ingest(self, packet, receive_time):
        """Update from an owned, running packet; rejected ordering is inert."""
        if not isinstance(packet, dict) or packet.get("run_id") != self._owner or self._owner is None:
            return False
        try:
            normalized, reason = self._normalize(packet)
        except Exception:
            self._invalidate("invalid_geometry")
            return False
        seq, stamp = packet.get("sequence"), packet.get("timestamp")
        # Guard high-water marks survive invalidation, so a late sample cannot
        # revive an older dangerous clearance after the displayed cache clears.
        high_seq, high_source = self._guard._high_sequence, self._guard._high_source
        if ((type(seq) is int and high_seq is not None and seq <= high_seq) or
                (self._finite(stamp) and high_source is not None and stamp <= high_source)):
            return False
        if (not self._finite(receive_time) or not self._finite(packet.get("time")) or
                not self._finite(packet.get("timestamp")) or
                not self._finite(packet.get("geometry_source_timestamp"))):
            self._invalidate("invalid_or_missing_query_time")
            return False
        query_age = packet["time"] - packet["geometry_source_timestamp"]
        if not self._finite(query_age):
            self._invalidate("invalid_query_age")
            return False
        if query_age < 0:
            self._invalidate("query_time_future")
            return False
        if query_age > .3:
            self._invalidate("stale_geometry_query")
            return False
        if normalized is None or reason is not None:
            self._invalidate(reason or "invalid_geometry")
            return False
        clearance = packet["directional_edge_distance"] - packet["ball_radius"]
        if not self._finite(clearance):
            self._invalidate("invalid_clearance")
            return False
        normalized = deepcopy(normalized)
        normalized.update({"run_state": packet.get("run_state"),
                           "calibration_mode": packet.get("calibration_mode"),
                           "directional_edge_valid": True,
                           "geometry_source_timestamp": packet["geometry_source_timestamp"],
                           "query_age_seconds": float(query_age),
                           "clearance": float(clearance)})
        if not self._guard.ingest(normalized, receive_time):
            # Guard ordering rejects are inert; validation failures revoke data.
            snapshot = self._guard.snapshot(receive_time)
            if snapshot.get("reason") not in ("duplicate_or_out_of_order", "run_not_owned"):
                self._invalidate(snapshot.get("reason", "invalid_geometry"))
            return False
        self._latest = {"sample": deepcopy(normalized), "receive_time": float(receive_time)}
        self._reason = "clearance_nonpositive" if normalized["clearance"] <= 0 else "clearance_positive"
        return True

    def _invalidate(self, reason):
        self._latest = None
        self._reason = reason
        try:
            self._guard._clear_stream(reason)
        except Exception:
            pass

    def invalidate(self, reason="invalid_geometry"):
        """Revoke the cached geometry while preserving explicit run ownership."""
        self._invalidate(reason)

    def warning(self, *, enabled, run_id, now):
        sample = self._latest["sample"] if self._latest else {}
        age = None
        reason = self._reason
        valid = False
        state = "UNKNOWN"
        clearance = 0.0
        query_age = 0.0
        if self._latest is not None:
            age = now - self._latest["receive_time"] if self._finite(now) else math.inf
            query_age = sample["query_age_seconds"]
            if age < 0:
                self._invalidate("receive_time_reversed")
                sample, reason, age, query_age = {}, self._reason, None, 0.0
            elif sample["query_age_seconds"] + age > .3:
                self._invalidate("stale_geometry_sample")
                sample, reason, age, query_age = {}, self._reason, None, 0.0
            else:
                clearance = sample["clearance"]
                valid = True
                state = "CRITICAL" if clearance <= 0 else "CLEAR"
                reason = "clearance_nonpositive" if clearance <= 0 else "clearance_positive"
        return {
            "schema_version": 1, "experimental": True, "enabled": bool(enabled),
            "source": "geometry_rule", "policy_id": "outer_clearance_nonpositive_v1",
            "run_id": run_id if isinstance(run_id, str) else "",
            "layer": sample.get("layer", 0),
            "platform_instance_id": sample.get("platform_instance_id", 0),
            "geometry_version_id": sample.get("geometry_version_id", ""),
            "input_sequence": sample.get("sequence", 0),
            "input_source_timestamp": sample.get("source_timestamp", 0.0),
            "sample_age_seconds": float(age) if age is not None else 0.0,
            "query_age_seconds": float(query_age),
            "geometry_age_seconds": float(query_age + age) if age is not None else 0.0,
            "clearance": float(clearance), "clearance_valid": bool(valid),
            "state": state, "valid": bool(valid), "reason": reason,
        }
