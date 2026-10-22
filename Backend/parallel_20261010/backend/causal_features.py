"""Causal online implementation of the reviewed 24 telemetry features.

The input is an already isolated, chronological continuity segment. This module
does not segment streams, classify risk, fit models, or serialize NaN values.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

HISTORY_SECONDS = 0.5
RECENT_SECONDS = 0.2
MAX_GAP_SECONDS = 0.1

FEATURE_NAMES = (
    "directional_edge_distance", "normalized_edge_distance", "clearance",
    "radial_outward_velocity", "ball_xz_speed", "platform_tilt", "difficulty",
    "ball_radius", "platform_radius", "distance_mean_0_5s", "distance_max_0_5s",
    "distance_min_0_5s", "velocity_mean_0_5s", "velocity_max_0_5s",
    "velocity_min_0_5s", "outward_acceleration", "acceleration_mean_0_5s",
    "acceleration_std_0_5s", "acceleration_max_0_5s", "velocity_vector_consistency",
    "mean_velocity_alignment_current_radial", "outward_fraction_0_5s",
    "inward_fraction_0_5s", "inward_displacement_0_2s",
)


def _number(sample: Mapping[str, object], key: str) -> float:
    try:
        value = float(sample.get(key, np.nan))
    except (TypeError, ValueError, OverflowError):
        return float("nan")
    return value if math.isfinite(value) else float("nan")


def _not_ready(reason: str, span: float = float("nan"), start: float = float("nan")) -> dict:
    result = {name: float("nan") for name in FEATURE_NAMES}
    result.update(ready=False, not_ready_reason=reason,
                  history_start_timestamp=start, history_span_seconds=span)
    return result


def compute_latest_features(samples: Sequence[Mapping[str, object]]) -> dict:
    """Compute the latest reviewed feature vector from one causal segment.

    ``samples`` must contain mappings in chronological order, including seconds
    timestamps. The selected history starts at the newest available sample at
    or before latest_time - 0.5 s. Invalid input/window returns NaN features and
    a diagnostic reason; it never substitutes a safe physical value.
    """
    if not samples:
        return _not_ready("empty_segment")
    times = np.asarray([_number(row, "source_timestamp") for row in samples], dtype=float)
    if not np.isfinite(times).all():
        return _not_ready("nonfinite_timestamp")
    dts = np.diff(times)
    if len(times) > 1 and not np.all(dts > 0):
        return _not_ready("timestamps_not_strictly_increasing")
    if len(times) > 1 and not np.all(dts <= MAX_GAP_SECONDS):
        return _not_ready("segment_gap_exceeds_0_1s")

    latest_t = float(times[-1])
    target_t = latest_t - HISTORY_SECONDS
    lo = int(np.searchsorted(times, target_t, side="right") - 1)
    if lo < 0:
        span = latest_t - float(times[0])
        return _not_ready("insufficient_0_5s_history", span, float(times[0]))
    span = latest_t - float(times[lo])
    if span < HISTORY_SECONDS - 1e-8:
        return _not_ready("insufficient_0_5s_history", span, float(times[lo]))

    def column(key: str) -> np.ndarray:
        return np.asarray([_number(row, key) for row in samples], dtype=float)

    dist = column("directional_edge_distance")
    radial_vel = column("ball_radial_velocity")
    ball_radius = column("ball_radius")
    platform_radius = column("platform_radius")
    current = len(samples) - 1
    # Distance and radial velocity are required throughout the history window.
    for key, values in (("directional_edge_distance", dist),
                        ("ball_radial_velocity", radial_vel)):
        if not np.isfinite(values[lo:]).all():
            return _not_ready("nonfinite_required_" + key, span, float(times[lo]))
    if not (np.isfinite(ball_radius[current]) and np.isfinite(platform_radius[current])):
        return _not_ready("nonfinite_current_physical_radius", span, float(times[lo]))
    if ball_radius[current] <= 0 or platform_radius[current] <= 0:
        return _not_ready("nonpositive_current_physical_radius", span, float(times[lo]))

    vx, vz = column("ball_velocity_x"), column("ball_velocity_z")
    px, pz = column("ball_pos_x"), column("ball_pos_z")
    cx, cz = column("platform_center_x"), column("platform_center_z")
    tilt, difficulty = column("platform_tilt"), column("difficulty")
    speed = np.hypot(vx, vz)
    radial_x, radial_z = px - cx, pz - cz
    radial_norm = np.hypot(radial_x, radial_z)
    radial_x = np.divide(radial_x, radial_norm, out=np.full_like(radial_x, np.nan), where=radial_norm > 0)
    radial_z = np.divide(radial_z, radial_norm, out=np.full_like(radial_z, np.nan), where=radial_norm > 0)

    # Acceleration is differentiated over the full supplied segment before
    # slicing, so the lower-window sample retains its historical predecessor.
    accel = np.full(len(samples), np.nan)
    if len(samples) > 1:
        accel[1:] = np.divide(np.diff(radial_vel), dts,
                              out=np.full(len(samples) - 1, np.nan), where=dts > 0)

    hist = slice(lo, current + 1)
    hdist, hvel, hacc = dist[hist], radial_vel[hist], accel[hist]
    hav = np.isfinite(hacc)
    vec_sum = np.hypot(np.nansum(vx[hist]), np.nansum(vz[hist]))
    vec_denom = np.nansum(speed[hist])
    consistency = vec_sum / vec_denom if vec_denom > 0 else np.nan
    align = np.divide(vx[hist] * radial_x[current] + vz[hist] * radial_z[current],
                      speed[hist], out=np.full(len(hvel), np.nan), where=speed[hist] > 0)
    current_distance = dist[current]
    recent_target = latest_t - RECENT_SECONDS
    recent_lo = int(np.searchsorted(times, recent_target, side="right") - 1)
    inward_displacement = np.nan
    if recent_lo >= 0 and latest_t - float(times[recent_lo]) >= RECENT_SECONDS - 1e-8:
        inward_displacement = float(radial_norm[recent_lo] - radial_norm[current])

    result = dict(
        directional_edge_distance=float(current_distance),
        normalized_edge_distance=float(current_distance / platform_radius[current]),
        clearance=float(current_distance - ball_radius[current]),
        radial_outward_velocity=float(radial_vel[current]),
        ball_xz_speed=float(speed[current]),
        platform_tilt=float(tilt[current]), difficulty=float(difficulty[current]),
        ball_radius=float(ball_radius[current]), platform_radius=float(platform_radius[current]),
        distance_mean_0_5s=float(np.mean(hdist)), distance_max_0_5s=float(np.max(hdist)),
        distance_min_0_5s=float(np.min(hdist)), velocity_mean_0_5s=float(np.mean(hvel)),
        velocity_max_0_5s=float(np.max(hvel)), velocity_min_0_5s=float(np.min(hvel)),
        outward_acceleration=float(accel[current]),
        acceleration_mean_0_5s=float(np.mean(hacc[hav])) if hav.any() else np.nan,
        acceleration_std_0_5s=float(np.std(hacc[hav], ddof=0)) if hav.any() else np.nan,
        acceleration_max_0_5s=float(np.max(hacc[hav])) if hav.any() else np.nan,
        velocity_vector_consistency=float(consistency),
        mean_velocity_alignment_current_radial=float(np.nanmean(align)) if np.isfinite(align).any() else np.nan,
        outward_fraction_0_5s=float(np.mean(hvel > .05)),
        inward_fraction_0_5s=float(np.mean(hvel < -.05)),
        inward_displacement_0_2s=float(inward_displacement),
        ready=True, not_ready_reason="", history_start_timestamp=float(times[lo]),
        history_span_seconds=float(span),
    )
    return result
