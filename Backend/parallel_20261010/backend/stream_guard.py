"""Import-safe streaming validity guard for Unity telemetry.

This module only validates and buffers samples. It does not construct features,
run a predictor, or make a safety decision.
"""
from collections import deque
import math
import copy


class StreamGuard:
    REQUIRED = ("run_id", "platform_instance_id", "geometry_version_id", "layer",
                "source_timestamp", "sequence", "run_state", "calibration_mode",
                "directional_edge_valid")

    def __init__(self, max_samples=128, warmup_seconds=0.5, stale_timeout=0.3,
                 max_source_gap=0.1, allow_calibration_session_gameplay=False):
        if type(max_samples) is not int or max_samples < 1:
            raise ValueError("max_samples must be a positive integer")
        for name, value in (("warmup_seconds", warmup_seconds),
                            ("stale_timeout", stale_timeout),
                            ("max_source_gap", max_source_gap)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(name + " must be finite and non-negative")
        self.max_samples = max_samples
        self.warmup_seconds = float(warmup_seconds)
        self.stale_timeout = float(stale_timeout)
        self.max_source_gap = float(max_source_gap)
        if type(allow_calibration_session_gameplay) is not bool:
            raise ValueError("allow_calibration_session_gameplay must be bool")
        self.allow_calibration_session_gameplay = allow_calibration_session_gameplay
        self._samples = deque(maxlen=max_samples)
        self._owner_run_id = None
        self._context = None
        self._last_source = None
        self._last_sequence = None
        self._last_receive = None
        self._high_source = None
        self._high_sequence = None
        self._high_receive = None
        self._first_source = None
        self._segment_generation = 0
        self._reason = "no_run"

    def _clear_stream(self, reason):
        self._segment_generation += 1
        self._samples.clear()
        self._context = None
        self._last_source = None
        self._last_sequence = None
        self._last_receive = None
        self._first_source = None
        self._reason = reason

    def begin_run(self, run_id):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        self._owner_run_id = run_id
        self._clear_stream("warming_up")
        self._high_source = None
        self._high_sequence = None
        self._high_receive = None

    def reset(self):
        self._owner_run_id = None
        self._clear_stream("no_run")
        self._high_source = None
        self._high_sequence = None
        self._high_receive = None

    def end_run(self):
        self._owner_run_id = None
        self._clear_stream("ended")
        self._high_source = None
        self._high_sequence = None
        self._high_receive = None

    def _valid(self, sample, receive_time):
        if not isinstance(sample, dict) or any(k not in sample for k in StreamGuard.REQUIRED):
            return False, "missing_fields"
        for key in ("run_id", "geometry_version_id", "run_state"):
            if not isinstance(sample[key], str) or not sample[key].strip():
                return False, "invalid_identity"
        if sample["geometry_version_id"].strip().lower() in ("unknown", "nan", "none"):
            return False, "invalid_identity"
        platform = sample["platform_instance_id"]
        if type(platform) is not int or platform in (-1, 0, -2147483648):
            return False, "invalid_identity"
        if type(sample["layer"]) is not int or sample["layer"] <= 0:
            return False, "invalid_identity"
        if isinstance(sample["source_timestamp"], bool) or not isinstance(sample["source_timestamp"], (int, float)) or not math.isfinite(sample["source_timestamp"]):
            return False, "invalid_source_timestamp"
        if type(sample["sequence"]) is not int or sample["sequence"] < 0:
            return False, "invalid_sequence"
        if type(sample["calibration_mode"]) is not bool or type(sample["directional_edge_valid"]) is not bool:
            return False, "invalid_boolean"
        if isinstance(receive_time, bool) or not isinstance(receive_time, (int, float)) or not math.isfinite(receive_time):
            return False, "invalid_receive_time"
        if sample["run_state"] != "running":
            return False, "terminal_state"
        if sample["calibration_mode"]:
            if not self.allow_calibration_session_gameplay or type(sample.get("gameplay_phase_valid")) is not bool or not sample["gameplay_phase_valid"]:
                return False, "calibration"
        if not sample["directional_edge_valid"]:
            return False, "invalid_directional_edge"
        return True, None

    def ingest(self, sample, receive_time):
        """Accept one normalized sample; receive_time is caller-supplied monotonic time."""
        # Ownership is checked before any invalid or terminal packet can mutate state.
        if not isinstance(sample, dict) or self._owner_run_id is None or sample.get("run_id") != self._owner_run_id:
            self._reason = "run_not_owned"
            return False
        # Ignore delayed same-run packets before an old terminal/invalid flag
        # can clear the current stream. Preserve ordering fences through gaps.
        stamp, seq = sample.get("source_timestamp"), sample.get("sequence")
        if (type(stamp) in (int, float) and math.isfinite(stamp) and
                self._high_source is not None and stamp <= self._high_source):
            self._reason = "duplicate_or_out_of_order"
            return False
        if type(seq) is int and self._high_sequence is not None and seq <= self._high_sequence:
            self._reason = "duplicate_or_out_of_order"
            return False
        if (type(receive_time) in (int, float) and math.isfinite(receive_time) and
                self._high_receive is not None and receive_time < self._high_receive):
            self._clear_stream("receive_time_reversed")
            return False
        ok, reason = self._valid(sample, receive_time)
        if not ok:
            self._clear_stream(reason)
            if reason == "terminal_state":
                self._owner_run_id = None
                self._high_source = None
                self._high_sequence = None
            return False
        if self._owner_run_id is None or sample["run_id"] != self._owner_run_id:
            self._reason = "run_not_owned"
            return False
        if self._last_receive is not None and receive_time < self._last_receive:
            self._clear_stream("receive_time_reversed")
            return False
        if self._last_receive is not None and receive_time - self._last_receive > self.stale_timeout:
            self._clear_stream("stale_stream")
            # The newly received valid packet starts a new warmup window.
            # Do not discard it: offline segmentation also keeps this first
            # post-gap point, which is needed for the next acceleration.
        if ((self._high_source is not None and sample["source_timestamp"] <= self._high_source) or
                (self._high_sequence is not None and sample["sequence"] <= self._high_sequence)):
            self._reason = "duplicate_or_out_of_order"
            return False
        context = tuple(sample[k] for k in ("run_id", "platform_instance_id", "layer", "geometry_version_id"))
        if self._context is not None and context == self._context:
            if sample["source_timestamp"] <= self._last_source or sample["sequence"] <= self._last_sequence:
                self._reason = "duplicate_or_out_of_order"
                return False
            if sample["source_timestamp"] - self._last_source > self.max_source_gap:
                self._clear_stream("source_gap")
            elif sample["sequence"] != self._last_sequence + 1:
                self._clear_stream("sequence_discontinuity")
        elif self._context is not None:
            self._clear_stream("context_changed")
        self._context = context
        self._last_source = float(sample["source_timestamp"])
        self._last_sequence = sample["sequence"]
        self._high_source = self._last_source
        self._high_sequence = self._last_sequence
        if self._first_source is None:
            self._first_source = self._last_source
        self._last_receive = float(receive_time)
        self._high_receive = self._last_receive
        self._samples.append({"telemetry": copy.deepcopy(sample), "receive_time": float(receive_time)})
        self._reason = "warming_up"
        return True

    def snapshot(self, now_monotonic):
        metadata = self.metadata_snapshot(now_monotonic)
        if metadata["reason"] == "receive_time_reversed":
            return {**metadata, "samples": []}
        samples = [{"telemetry": copy.deepcopy(x["telemetry"]), "receive_time": x["receive_time"]} for x in self._samples]
        return {**metadata, "samples": samples}

    def metadata_snapshot(self, now_monotonic):
        """Return snapshot validity metadata without copying retained telemetry.

        This intentionally mirrors snapshot()'s time validation, stale-stream
        transition, and retained-capacity warmup calculation. Call snapshot()
        only when the caller actually needs the sample history.
        """
        if isinstance(now_monotonic, bool) or not isinstance(now_monotonic, (int, float)) or not math.isfinite(now_monotonic):
            raise ValueError("now_monotonic must be finite")
        if self._last_receive is not None and now_monotonic < self._last_receive:
            return {"valid": False, "ready": False, "reason": "receive_time_reversed",
                    "segment_generation": self._segment_generation}
        if self._last_receive is not None and now_monotonic - self._last_receive > self.stale_timeout:
            self._clear_stream("stale_stream")
        count = len(self._samples)
        elapsed = (self._last_source - self._samples[0]["telemetry"]["source_timestamp"]) if count else 0.0
        ready = bool(count) and elapsed >= self.warmup_seconds
        reason = "ready" if ready else self._reason
        return {"valid": ready, "ready": ready, "reason": reason,
                "segment_generation": self._segment_generation}

    # Keep the initial candidate spelling available for isolated callers.
    snapshot_metadata = metadata_snapshot

    @staticmethod
    def status():
        return {"state": "UNKNOWN", "valid": False, "probability_valid": False,
                "strong_probability": 0.0, "experimental": True, "enabled": False,
                "model_id": "mock-unavailable",
                "model_warning": {"valid": False, "message": "Predictor unavailable; no inference performed."}}
