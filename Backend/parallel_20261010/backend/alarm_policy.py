"""Pure streaming strong-alarm and causal recovery policy.

SAFE means the model is not alarming; it is not a claim of physical safety.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

MAX_GAP = 0.1


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _result(state, raw, confirmed, active, canceled, reason, accepted):
    return {"state": state, "raw": bool(raw), "confirmed": bool(confirmed),
            "active": bool(active), "canceled": bool(canceled),
            "reason": reason, "accepted": bool(accepted)}


class StrongAlarmPolicy:
    """Two-decision strong-warning confirmation with immediate raw OFF."""

    def __init__(self, threshold: float):
        value = _finite(threshold)
        if value is None or not 0.0 <= value <= 1.0:
            raise ValueError("threshold must be finite and within [0, 1]")
        self.threshold = value
        self.reset()

    def reset(self) -> None:
        self._context = None
        self._previous_time = None
        self._raw_previous = False
        self._active = False
        self._last_result = _result("SAFE", False, False, False, False, "reset", True)

    def step(self, probability, clearance, timestamp, context, joint_recovery=False) -> dict[str, Any]:
        p, c, t = _finite(probability), _finite(clearance), _finite(timestamp)
        if (p is None or not 0.0 <= p <= 1.0 or c is None or c <= 0 or t is None
                or not isinstance(joint_recovery, bool)):
            self.reset()
            result = _result("UNKNOWN", False, False, False, False, "invalid_input", True)
            self._last_result = result
            return result
        if context is None or isinstance(context, (str, bytes)):
            self.reset()
            result = _result("UNKNOWN", False, False, False, False, "invalid_context", True)
            self._last_result = result
            return result
        try:
            token = tuple(context)
        except (TypeError, ValueError):
            self.reset()
            result = _result("UNKNOWN", False, False, False, False, "invalid_context", True)
            self._last_result = result
            return result
        if not token:
            self.reset()
            result = _result("UNKNOWN", False, False, False, False, "invalid_context", True)
            self._last_result = result
            return result
        if self._previous_time is not None and t <= self._previous_time:
            return _result(self._last_result["state"], self._last_result["raw"],
                           self._last_result["confirmed"], self._active, False,
                           "duplicate_or_out_of_order", False)

        gap_ok = self._previous_time is None or 0.0 < t - self._previous_time <= MAX_GAP + 1e-9
        context_changed = self._context is not None and token != self._context
        if context_changed or not gap_ok:
            self._raw_previous = False
            self._active = False
        raw = p >= self.threshold and c > 0
        confirmed = bool(raw and self._raw_previous and not context_changed and gap_ok)
        self._raw_previous = raw  # Keep raw continuity even on recovery rows.
        self._previous_time = t
        self._context = token

        recovered = joint_recovery
        canceled = recovered and self._active
        if recovered:
            self._active = False
        elif confirmed:
            self._active = True
        else:
            self._active = False
        state = "STRONG" if self._active else "SAFE"
        reason = "joint_recovery" if recovered else ("confirmed" if confirmed else ("raw_on" if raw else "raw_off"))
        result = _result(state, raw, confirmed, self._active, canceled, reason, True)
        self._last_result = result
        return result


def compute_recovery(samples: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate the latest causal sample using the reviewed joint-recovery rule.

    Timestamp and clearance values are already-converted observations supplied
    by the engine. Every history row must be finite and chronological; malformed
    or discontinuous input fails closed instead of bridging across a gap.
    """
    rows = list(samples)
    clean = []
    for row in rows:
        if not isinstance(row, Mapping):
            return {"joint_recovery": False, "continuous_inward_duration": 0.0,
                    "clearance_gain_0_1s": None, "reason": "invalid_history_row"}
        t = _finite(row.get("timestamp"))
        velocity = _finite(row.get("ball_radial_velocity"))
        clearance = _finite(row.get("clearance"))
        if t is None or velocity is None or clearance is None:
            return {"joint_recovery": False, "continuous_inward_duration": 0.0,
                    "clearance_gain_0_1s": None, "reason": "invalid_history_value"}
        if clean:
            dt = t - clean[-1][0]
            if not 0 < dt <= MAX_GAP + 1e-9:
                return {"joint_recovery": False, "continuous_inward_duration": 0.0,
                        "clearance_gain_0_1s": None, "reason": "discontinuous_history"}
        clean.append((t, velocity, clearance))
    if not clean:
        return {"joint_recovery": False, "continuous_inward_duration": 0.0,
                "clearance_gain_0_1s": None, "reason": "no_finite_timestamp"}
    now, velocity, clearance = clean[-1]
    if velocity is None or clearance is None:
        return {"joint_recovery": False, "continuous_inward_duration": 0.0,
                "clearance_gain_0_1s": None, "reason": "invalid_latest_measurement"}
    start = len(clean) - 1
    while start > 0:
        prev_t, prev_v, _ = clean[start - 1]
        cur_t = clean[start][0]
        if prev_v is None or not prev_v < -0.05 or not 0 < cur_t - prev_t <= MAX_GAP:
            break
        start -= 1
    duration = max(0.0, now - clean[start][0]) if velocity < -0.05 else 0.0
    prior = [entry for entry in clean if entry[0] <= now - 0.1 + 1e-9]
    gain = None
    if prior:
        source_t, _, source_clearance = prior[-1]
        if source_clearance is not None and now - source_t >= 0.1 - 1e-8:
            gain = clearance - source_clearance
    qualified = (velocity < -0.05 and duration >= 0.1 - 1e-9 and clearance > 0 and
                 gain is not None and math.isfinite(gain) and gain >= 0.02)
    return {"joint_recovery": bool(qualified), "continuous_inward_duration": duration,
            "clearance_gain_0_1s": gain,
            "reason": "joint_recovery" if qualified else "criteria_not_met"}
