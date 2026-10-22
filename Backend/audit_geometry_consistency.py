"""Read-only audit of Unity geometry and edge-event telemetry.

The audit checks algebraic consistency of fields already emitted by Unity,
separates outer-edge geometry from target-hole geometry, and reports warning
misses by difficulty and fall direction.  It never edits raw CSV files or
Unity assets.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


BASE = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs")
DATASETS = ("TEST9282", "TEST929", "TEST930", "TEST931", "TEST1001")
# Keep the first pass intact and write the corrected event-attribution pass to a
# separate directory.  This makes it possible to reproduce both reports and
# avoids overwriting the earlier diagnostic output.
OUT = BASE / "analysis_geometry_consistency_20261002_corrected"
GEOMETRY_TOLERANCE = 1e-3
STATE_TOLERANCE = 1e-4


def numeric(df: pd.DataFrame, name: str) -> np.ndarray:
    if name not in df.columns:
        return np.full(len(df), np.nan, dtype=float)
    values = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float, copy=True)
    values[~np.isfinite(values)] = np.nan
    return values


def text(df: pd.DataFrame, name: str, default: str = "") -> np.ndarray:
    if name not in df.columns:
        return np.full(len(df), default, dtype=object)
    return df[name].astype("string").fillna(default).astype(str).to_numpy(dtype=object)


def booleans(df: pd.DataFrame, name: str) -> np.ndarray:
    if name not in df.columns:
        return np.zeros(len(df), dtype=bool)
    values = [str(value).strip().lower() for value in text(df, name)]
    return np.asarray([value in {"true", "1", "yes", "y", "t"} for value in values], dtype=bool)


def upper_text(values: np.ndarray) -> np.ndarray:
    return np.asarray([str(value).strip().upper() for value in values], dtype=object)


def first_finite(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    return float(finite[0]) if len(finite) else math.nan


def most_common_finite(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return math.nan
    unique, counts = np.unique(finite, return_counts=True)
    return float(unique[int(np.argmax(counts))])


def error_stats(error: np.ndarray, tolerance: float = GEOMETRY_TOLERANCE) -> dict[str, Any]:
    finite = error[np.isfinite(error)]
    if not len(finite):
        return {"n": 0, "max_abs": math.nan, "p95_abs": math.nan, "n_over_tolerance": 0}
    absolute = np.abs(finite)
    return {
        "n": int(len(finite)),
        "max_abs": float(np.max(absolute)),
        "p95_abs": float(np.percentile(absolute, 95)),
        "n_over_tolerance": int(np.sum(absolute > tolerance)),
    }


def first_event_time(df: pd.DataFrame, values: np.ndarray, event_mask: np.ndarray) -> tuple[float, int]:
    timestamps = numeric(df, "backend_timestamp")
    indices = np.flatnonzero(event_mask & np.isfinite(timestamps))
    if len(indices):
        index = int(indices[0])
        return float(timestamps[index]), index
    finite = values[np.isfinite(values)]
    return (float(finite[0]), -1) if len(finite) else (math.nan, -1)


def event_axis_direction(df: pd.DataFrame, event_index: int) -> str:
    """Return the dominant world-axis direction at the event.

    The raw axis is reported deliberately (+X/-X/+Z/-Z).  It can be mapped
    to left/right/front/back after confirming the scene's camera convention.
    """

    if event_index < 0 or event_index >= len(df):
        return "unknown"
    ball_x = numeric(df, "ball_pos_x")[event_index]
    ball_z = numeric(df, "ball_pos_z")[event_index]
    center_x = numeric(df, "platform_center_x")[event_index]
    center_z = numeric(df, "platform_center_z")[event_index]
    if not all(np.isfinite(value) for value in (ball_x, ball_z, center_x, center_z)):
        return "unknown"
    dx = float(ball_x - center_x)
    dz = float(ball_z - center_z)
    if abs(dx) < 1e-6 and abs(dz) < 1e-6:
        return "center"
    if abs(dx) >= abs(dz):
        return "+X" if dx > 0 else "-X"
    return "+Z" if dz > 0 else "-Z"


def event_order(values: dict[str, float]) -> list[dict[str, Any]]:
    order = [
        "edge_warning_time",
        "edge_contact_time",
        "support_lost_time",
        "fall_event_time",
    ]
    violations: list[dict[str, Any]] = []
    for previous, current in zip(order, order[1:]):
        left = values.get(previous, math.nan)
        right = values.get(current, math.nan)
        if np.isfinite(left) and np.isfinite(right) and left > right + STATE_TOLERANCE:
            violations.append({"earlier_field": previous, "later_field": current, "earlier": left, "later": right})
    return violations


def audit_segment(dataset: str, session_id: str, df: pd.DataFrame, segment_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ts = numeric(df, "backend_timestamp")
    sequence = numeric(df, "sequence")
    sort_order = np.lexsort((np.nan_to_num(sequence, nan=np.inf), np.nan_to_num(ts, nan=np.inf)))
    df = df.iloc[sort_order].reset_index(drop=True)
    ts = numeric(df, "backend_timestamp")

    center_x = numeric(df, "platform_center_x")
    center_z = numeric(df, "platform_center_z")
    radius = numeric(df, "platform_radius")
    ball_x = numeric(df, "ball_pos_x")
    ball_z = numeric(df, "ball_pos_z")
    ball_radius = numeric(df, "ball_radius")
    radial_offset_x = ball_x - center_x
    radial_offset_z = ball_z - center_z
    radial_distance = np.hypot(radial_offset_x, radial_offset_z)
    outward_x = np.divide(radial_offset_x, radial_distance, out=np.full(len(df), np.nan), where=radial_distance > 1e-6)
    outward_z = np.divide(radial_offset_z, radial_distance, out=np.full(len(df), np.nan), where=radial_distance > 1e-6)
    # Unity passes Vector2.right to the geometry helper when the ball is at
    # the exact platform centre, so its logged edge point is deterministic
    # (+X) even though the radial velocity is zero there.
    edge_direction_x = np.where(radial_distance > 1e-4, outward_x, 1.0)
    edge_direction_z = np.where(radial_distance > 1e-4, outward_z, 0.0)

    logged_edge = numeric(df, "directional_edge_distance")
    expected_edge = radius - radial_distance
    logged_target_edge = numeric(df, "target_edge_distance")
    expected_point_x = center_x + edge_direction_x * radius
    expected_point_z = center_z + edge_direction_z * radius
    logged_point_x = numeric(df, "directional_edge_point_x")
    logged_point_z = numeric(df, "directional_edge_point_z")

    velocity_x = numeric(df, "ball_velocity_x")
    velocity_z = numeric(df, "ball_velocity_z")
    radial_velocity_expected = np.where(
        radial_distance > 1e-4,
        velocity_x * outward_x + velocity_z * outward_z,
        0.0,
    )
    logged_radial_velocity = numeric(df, "ball_radial_velocity")
    logged_target_velocity = numeric(df, "target_edge_radial_velocity")

    hole_x = numeric(df, "target_x")
    hole_z = numeric(df, "target_z")
    hole_radius = numeric(df, "target_hole_radius")
    logged_hole_distance = numeric(df, "target_hole_distance")
    expected_hole_distance = np.hypot(ball_x - hole_x, ball_z - hole_z)
    hole_clearance = logged_hole_distance - hole_radius - ball_radius
    hole_center_offset = np.hypot(hole_x - center_x, hole_z - center_z)
    hole_outer_edge_gap = radius - hole_center_offset - hole_radius

    threshold = numeric(df, "edge_warning_distance_threshold")
    expected_threshold = ball_radius * 2.0
    warning_radius = numeric(df, "edge_warning_radius")
    expected_warning_radius = radius - ball_radius * 2.0
    directional_valid = booleans(df, "directional_edge_valid")
    warning_state = booleans(df, "edge_warning_state")
    fall_event = booleans(df, "fall_event")
    prediction_state = upper_text(text(df, "prediction_state"))
    attention_state = booleans(df, "attention_state") | (prediction_state == "ATTENTION")
    hole_approach_state = upper_text(text(df, "hole_approach_state"))
    hole_approach = np.isin(hole_approach_state, ["APPROACHING_HOLE", "AT_HOLE"])

    geometry_valid = (
        np.isfinite(center_x) & np.isfinite(center_z) & np.isfinite(radius) &
        np.isfinite(ball_x) & np.isfinite(ball_z) & np.isfinite(logged_edge)
    )
    geometry_warning = geometry_valid & np.isfinite(threshold) & (logged_edge <= threshold + STATE_TOLERANCE)
    running = np.asarray([str(value).strip().lower() != "ended" for value in text(df, "run_state")], dtype=bool)
    state_mismatch = geometry_warning & running & (warning_state != geometry_warning)
    pre_event = np.ones(len(df), dtype=bool)
    event_indices = np.flatnonzero(fall_event & np.isfinite(ts))
    event_index = int(event_indices[0]) if len(event_indices) else len(df)
    event_ts = float(ts[event_index]) if event_index < len(df) else math.nan
    if np.isfinite(event_ts):
        pre_event = ts < event_ts

    unity_event_values = {
        name: first_finite(numeric(df, name))
        for name in ("edge_warning_time", "edge_contact_time", "support_lost_time", "fall_event_time")
    }
    backend_event_values = {
        name: first_finite(numeric(df, name))
        for name in ("edge_warning_backend_timestamp", "edge_contact_backend_timestamp", "support_lost_backend_timestamp", "fall_event_backend_timestamp")
    }
    unity_violations = event_order(unity_event_values)
    backend_violations = []
    backend_order = [
        "edge_warning_backend_timestamp",
        "edge_contact_backend_timestamp",
        "support_lost_backend_timestamp",
        "fall_event_backend_timestamp",
    ]
    for previous, current in zip(backend_order, backend_order[1:]):
        left = backend_event_values.get(previous, math.nan)
        right = backend_event_values.get(current, math.nan)
        if np.isfinite(left) and np.isfinite(right) and left > right + STATE_TOLERANCE:
            backend_violations.append({"earlier_field": previous, "later_field": current, "earlier": left, "later": right})

    direction = str(text(df, "fall_direction")[event_index]) if event_index < len(df) else ""
    compass_direction = event_axis_direction(df, event_index)
    difficulty_values = numeric(df, "active_platform_difficulty")
    if not np.isfinite(difficulty_values).any():
        difficulty_values = numeric(df, "platform_difficulty")
    if not np.isfinite(difficulty_values).any():
        difficulty_values = numeric(df, "difficulty")
    difficulty = most_common_finite(difficulty_values)
    min_edge_pre = np.nanmin(logged_edge[pre_event]) if np.isfinite(logged_edge[pre_event]).any() else math.nan
    min_hole_clearance_pre = np.nanmin(hole_clearance[pre_event]) if np.isfinite(hole_clearance[pre_event]).any() else math.nan
    pre_warning = bool(np.any(warning_state & pre_event))
    pre_geom_warning = bool(np.any(geometry_warning & pre_event))
    pre_yellow = bool(np.any((prediction_state == "EDGE WARNING") & pre_event))

    summary = {
        "dataset": dataset,
        "session_id": session_id,
        "segment_id": segment_id,
        "n_unity_rows": int(len(df)),
        "difficulty": difficulty,
        "fall_event": bool(len(event_indices)),
        "fall_direction": direction,
        "event_axis_direction": compass_direction,
        "event_backend_timestamp": event_ts,
        "pre_warning_state": pre_warning,
        "pre_geometry_warning": pre_geom_warning,
        "pre_prediction_yellow": pre_yellow,
        "min_pre_directional_edge_distance": float(min_edge_pre),
        "min_pre_hole_clearance": float(min_hole_clearance_pre),
        "min_hole_outer_edge_gap": float(np.nanmin(hole_outer_edge_gap)) if np.isfinite(hole_outer_edge_gap).any() else math.nan,
        "hole_approach_rows": int(hole_approach.sum()),
        "hole_approach_prediction_yellow_rows": int(np.sum(hole_approach & (prediction_state == "EDGE WARNING"))),
        "hole_approach_prediction_yellow_fraction": float(np.mean(prediction_state[hole_approach] == "EDGE WARNING")) if hole_approach.any() else math.nan,
        "hole_approach_attention_rows": int(np.sum(hole_approach & attention_state)),
        "hole_approach_attention_fraction": float(np.mean(attention_state[hole_approach])) if hole_approach.any() else math.nan,
        "geometry_valid_fraction": float(np.mean(directional_valid)) if len(directional_valid) else math.nan,
        "geometry_warning_state_mismatch_rows": int(state_mismatch.sum()),
        "unity_event_order_violation_count": int(len(unity_violations)),
        "backend_event_order_violation_count": int(len(backend_violations)),
        "unity_event_order_violations": json.dumps(unity_violations, ensure_ascii=False),
        "backend_event_order_violations": json.dumps(backend_violations, ensure_ascii=False),
        "flag_no_pre_warning": bool(bool(fall_event.any()) and not pre_warning),
        "flag_geometry_reached_but_state_false": bool(state_mismatch[pre_event].any()),
        "flag_threshold_never_reached": bool(bool(fall_event.any()) and not pre_geom_warning),
        "flag_event_time_order_violation": bool(unity_violations or backend_violations),
    }

    geometry = {
        "dataset": dataset,
        "session_id": session_id,
        "segment_id": segment_id,
        "n_rows": len(df),
        "directional_edge_distance_error": error_stats(logged_edge - expected_edge),
        "target_edge_distance_error": error_stats(logged_target_edge - expected_edge),
        "directional_edge_point_x_error": error_stats(logged_point_x - expected_point_x),
        "directional_edge_point_z_error": error_stats(logged_point_z - expected_point_z),
        "ball_radial_velocity_error": error_stats(logged_radial_velocity - radial_velocity_expected),
        "target_edge_radial_velocity_error": error_stats(logged_target_velocity - radial_velocity_expected),
        "target_hole_distance_error": error_stats(logged_hole_distance - expected_hole_distance),
        "warning_threshold_error": error_stats(threshold - expected_threshold),
        "warning_radius_error": error_stats(warning_radius - expected_warning_radius),
        "geometry_warning_state_mismatch_rows": int(state_mismatch.sum()),
        "n_hole_geometry_rows": int(np.isfinite(expected_hole_distance).sum()),
        "min_hole_clearance": float(np.nanmin(hole_clearance)) if np.isfinite(hole_clearance).any() else math.nan,
        "max_hole_clearance": float(np.nanmax(hole_clearance)) if np.isfinite(hole_clearance).any() else math.nan,
        "min_hole_outer_edge_gap": float(np.nanmin(hole_outer_edge_gap)) if np.isfinite(hole_outer_edge_gap).any() else math.nan,
        "max_hole_outer_edge_gap": float(np.nanmax(hole_outer_edge_gap)) if np.isfinite(hole_outer_edge_gap).any() else math.nan,
    }
    return summary, geometry


def contiguous_platform_segments(unity: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """Split a run into contiguous platform blocks and attach a layer-transition
    fall row to the preceding block.

    Unity can increment ``platform_level`` in the same frame in which it emits
    the final ``fall_event``.  Grouping only by ``(run_id, platform_level)``
    therefore creates a one-row ``ended`` block with no preceding warning and
    falsely reports a miss.  The event row still carries the geometry at the
    instant of failure, so it is appended to the preceding block for event
    attribution while its pre-event samples remain in the original block.
    """
    if unity.empty:
        return []
    frame = unity.copy()
    timestamp = numeric(frame, "backend_timestamp")
    sequence = numeric(frame, "sequence")
    order = np.lexsort((np.nan_to_num(sequence, nan=np.inf), np.nan_to_num(timestamp, nan=np.inf)))
    frame = frame.iloc[order].reset_index(drop=True)
    run_values = text(frame, "run_id", "")
    levels = numeric(frame, "platform_level")
    level_key = np.asarray([
        str(int(level)) if np.isfinite(level) else "unknown" for level in levels
    ], dtype=object)
    boundaries = [0]
    for index in range(1, len(frame)):
        if run_values[index] != run_values[index - 1] or level_key[index] != level_key[index - 1]:
            boundaries.append(index)
    boundaries.append(len(frame))
    blocks: list[tuple[str, pd.DataFrame]] = []
    for block_index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        block = frame.iloc[start:end].copy()
        block_id = f"{run_values[start]}|layer_{level_key[start]}|contiguous_{block_index + 1}"
        fall_mask = booleans(block, "fall_event")
        # When the level changes on the fall frame, that frame is the terminal
        # event for the previous platform, not a new playable segment.
        if block_index > 0 and fall_mask.any():
            event_rows = block.loc[fall_mask].copy()
            previous_id, previous_block = blocks[-1]
            blocks[-1] = (previous_id, pd.concat([previous_block, event_rows], ignore_index=True))
            block = block.loc[~fall_mask].copy()
        if not block.empty:
            blocks.append((block_id, block))
    return blocks


def flatten_geometry(rows: list[dict[str, Any]]) -> pd.DataFrame:
    flattened: list[dict[str, Any]] = []
    for row in rows:
        output = {key: value for key, value in row.items() if not isinstance(value, dict)}
        for name in (
            "directional_edge_distance_error", "target_edge_distance_error",
            "directional_edge_point_x_error", "directional_edge_point_z_error",
            "ball_radial_velocity_error", "target_edge_radial_velocity_error",
            "target_hole_distance_error", "warning_threshold_error", "warning_radius_error",
        ):
            stats = row[name]
            for key, value in stats.items():
                output[f"{name}_{key}"] = value
        flattened.append(output)
    return pd.DataFrame(flattened)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    geometries: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    for dataset in DATASETS:
        root = BASE / dataset
        for path in sorted(root.glob("session_*/raw.csv")):
            try:
                raw = pd.read_csv(path, low_memory=False, na_values=["", "NaN", "nan", "None"])
            except Exception as exc:
                summaries.append({"dataset": dataset, "session_id": path.parent.name, "load_error": str(exc)})
                continue
            source = text(raw, "source").astype(str).copy()
            unity = raw.loc[np.asarray([value.strip().lower() == "unity" for value in source], dtype=bool)].copy()
            if unity.empty:
                continue
            required = [
                "platform_center_x", "platform_center_z", "platform_radius", "ball_pos_x", "ball_pos_z",
                "directional_edge_distance", "directional_edge_point_x", "directional_edge_point_z",
                "directional_edge_valid", "target_x", "target_z", "target_hole_distance", "target_hole_radius",
                "edge_warning_state", "edge_warning_time", "edge_contact_time", "support_lost_time", "fall_event_time",
            ]
            for name in required:
                values = numeric(unity, name) if name not in {"directional_edge_valid", "edge_warning_state"} else booleans(unity, name).astype(float)
                field_rows.append({
                    "dataset": dataset,
                    "session_id": path.parent.name,
                    "field": name,
                    "rows": int(len(unity)),
                    "finite_or_present_rows": int(np.isfinite(values).sum()),
                    "availability_fraction": float(np.isfinite(values).mean()) if len(values) else math.nan,
                })
            # Split by contiguous platform blocks rather than grouping all rows
            # by level.  A terminal fall row can be emitted after Unity has
            # already advanced the displayed platform level; the helper
            # attaches that row to the preceding block for correct event
            # attribution.
            for segment_id, segment in contiguous_platform_segments(unity):
                summary, geometry = audit_segment(dataset, path.parent.name, segment, str(segment_id))
                summaries.append(summary)
                geometries.append(geometry)

    summary_frame = pd.DataFrame(summaries)
    geometry_frame = flatten_geometry(geometries)
    fields_frame = pd.DataFrame(field_rows)
    summary_frame.to_csv(OUT / "segment_summary.csv", index=False, encoding="utf-8-sig")
    geometry_frame.to_csv(OUT / "geometry_reconstruction_errors.csv", index=False, encoding="utf-8-sig")
    fields_frame.to_csv(OUT / "field_availability.csv", index=False, encoding="utf-8-sig")

    fall = summary_frame.loc[summary_frame.get("fall_event", False).fillna(False).astype(bool)].copy() if not summary_frame.empty else pd.DataFrame()
    if not fall.empty:
        group = (
            fall.assign(direction=fall["event_axis_direction"].replace("", "unknown"))
            .groupby(["dataset", "difficulty", "direction"], dropna=False)
            .agg(
                fall_segments=("segment_id", "count"),
                no_pre_warning=("flag_no_pre_warning", "sum"),
                geometry_reached_but_state_false=("flag_geometry_reached_but_state_false", "sum"),
                threshold_never_reached=("flag_threshold_never_reached", "sum"),
                event_order_violations=("flag_event_time_order_violation", "sum"),
                median_min_edge_distance=("min_pre_directional_edge_distance", "median"),
            )
            .reset_index()
        )
    else:
        group = pd.DataFrame()
    group.to_csv(OUT / "fall_miss_by_difficulty_direction.csv", index=False, encoding="utf-8-sig")

    geometry_error_columns = [column for column in geometry_frame.columns if column.endswith("n_over_tolerance")]
    result = {
        "datasets": list(DATASETS),
        "segments_audited": int(len(summary_frame)),
        "fall_segments": int(len(fall)),
        "nonfall_segments": int(len(summary_frame) - len(fall)),
        "geometry_error_tolerance": GEOMETRY_TOLERANCE,
        "field_availability_file": str(OUT / "field_availability.csv"),
        "geometry_error_file": str(OUT / "geometry_reconstruction_errors.csv"),
        "fall_direction_difficulty_file": str(OUT / "fall_miss_by_difficulty_direction.csv"),
        "geometry_mismatch_counts": {
            column: int(geometry_frame[column].fillna(0).sum()) if column in geometry_frame else 0
            for column in geometry_error_columns
        },
        "event_order_violations": int(summary_frame.get("flag_event_time_order_violation", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
        "missing_pre_warning_fall_segments": int(fall.get("flag_no_pre_warning", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
        "raw_files_modified": False,
        "unity_files_modified": False,
        "interpretation": {
            "directional_edge_distance": "Unity currently logs platform_radius minus ball radial distance: outer platform-boundary clearance for the ball centre, not distance to the hole boundary.",
            "target_hole_distance": "Distance from ball centre to target hole centre. Use target_hole_distance - target_hole_radius - ball_radius for hole-opening clearance.",
            "event_times": "Unity Time.time fields are checked for ordering; backend timestamp fields are checked separately. NaN means event not observed.",
            "frozen_test": "TEST1001 is included only as a read-only geometry diagnostic; it is not used to choose model parameters.",
        },
    }
    (OUT / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8")
    (OUT / "README.md").write_text(
        "# Geometry and event consistency audit\n\n"
        "This is a read-only audit of Unity telemetry. It reconstructs the outer-edge and target-hole distances from logged positions and checks event-time ordering.\n\n"
        "`directional_edge_distance` is currently the outer platform boundary distance. `target_hole_distance` is centre-to-hole-centre distance; hole clearance is derived using the logged hole radius and ball radius.\n\n"
        "TEST1001 is included only for diagnostic inspection and is not used for model selection.\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=True, default=float))


if __name__ == "__main__":
    main()
