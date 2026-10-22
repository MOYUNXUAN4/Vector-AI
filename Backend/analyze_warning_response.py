"""Derive warning-response episodes from raw telemetry.

The input is never modified.  Episodes are computed independently for the
attention and strong-warning channels, with all rows at or after a fall event
excluded from causal pre-event warnings.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "off", "nan", "none", ""}
SAFE_STATES = {"SAFE", "NORMAL", "STABLE", "OK", "NONE", "IDLE", "READY"}
STRONG_RE = re.compile(r"(?:EDGE\s*WARNING|EDGE\s*CONTACT|STRONG|CRITICAL|DANGER|RED)", re.I)
ATTENTION_RE = re.compile(r"(?:ATTENTION|YELLOW|CAUTION|ALERT)", re.I)

EPISODE_COLUMNS = [
    "dataset", "session_id", "file_session_id", "source_file", "run_id", "layer",
    "condition", "response_condition", "response_experiment_id", "trial_id", "layer_id",
    "intended_action", "manual_outcome", "episode_type",
    "warning_start", "warning_end", "warning_duration_s", "n_warning_samples",
    "warning_end_reason", "first_inward_movement_time", "first_inward_movement_velocity",
    "inward_sample_count", "reaction_time_s", "safe_return_time",
    "safe_return_confirmed_time", "recovery_time_s", "fall_event_time", "lead_time_s",
    "last_warning_lead_time_s", "minimum_directional_edge_distance",
    "minimum_warning_margin", "minimum_radial_velocity", "warning_source",
    "warning_type", "warning_active", "visible_warning_state", "warning_episode_id",
    "telemetry_warning_start", "telemetry_warning_end",
    "attention_episode_id", "attention_episode_enter_time",
    "attention_episode_exit_time", "attention_episode_start_time",
    "attention_episode_end_time", "outcome",
    "outcome_subtype", "manual_outcome_match", "post_fall_warning_rows", "missing_fields",
    "review_flags", "review_required",
]

SESSION_COLUMNS = [
    "dataset", "session_id", "file_session_id", "source_file", "condition",
    "response_condition",
    "response_experiment_id", "trial_id", "layer_ids",
    "intended_action", "manual_outcome", "n_layers", "n_segments", "n_episodes",
    "attention_episode_count", "strong_episode_count", "fall_event", "fall_event_time",
    "session_outcome", "final_run_state", "warning_any", "first_warning_time",
    "first_warning_lead_time_s", "median_reaction_time_s", "median_recovery_time_s",
    "median_lead_time_s", "n_recovered", "n_fall_after_warning", "n_no_response",
    "n_false_alarm", "n_ambiguous", "n_near_miss_recovered", "n_safe_normal",
    "review_episode_count", "review_required", "review_flags",
]

CONDITION_COLUMNS = [
    "condition", "episode_type", "sessions", "episodes", "warning_samples",
    "recovered", "fall_after_warning", "no_response", "false_alarm", "ambiguous",
    "near_miss_recovered", "safe_normal", "review_required", "median_lead_time_s",
    "median_reaction_time_s", "median_recovery_time_s",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return ""
    try:
        number = float(text)
        if math.isfinite(number) and number.is_integer() and re.fullmatch(r"[+-]?\d+(?:\.0+)?", text):
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return text


def first_value(row: Mapping[str, Any], names: Sequence[str]) -> str:
    for name in names:
        if name in row:
            text = clean_text(row[name])
            if text:
                return text
    return ""


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = clean_text(value).lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def bool_series(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    return frame[name].map(lambda value: parse_bool(value) is True).astype(bool)


def num_series(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def first_finite(*series: pd.Series) -> pd.Series:
    result = series[0].copy()
    for candidate in series[1:]:
        result = result.where(result.notna(), candidate)
    return result


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def join_flags(values: Iterable[str]) -> str:
    return ";".join(sorted({str(value) for value in values if str(value)}))


def safe_state_mask(frame: pd.DataFrame) -> tuple[pd.Series, bool]:
    if "prediction_state" not in frame:
        return pd.Series(False, index=frame.index, dtype=bool), False
    text = frame["prediction_state"].map(clean_text).str.upper()
    return text.isin(SAFE_STATES), bool(text.ne("").any())


def warning_masks(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, str, list[str]]:
    review: list[str] = []
    prediction = (
        frame["prediction_state"].map(clean_text).str.upper()
        if "prediction_state" in frame
        else pd.Series("", index=frame.index, dtype=object)
    )
    attention = bool_series(frame, "attention_state")
    if "attention_state" in frame:
        attention |= frame["attention_state"].map(clean_text).str.upper().str.contains(
            ATTENTION_RE, na=False
        )
    attention |= prediction.str.contains(ATTENTION_RE, na=False)
    warning_type = (
        frame["warning_type"].map(clean_text).str.upper()
        if "warning_type" in frame
        else pd.Series("", index=frame.index, dtype=object)
    )
    visible_state = (
        frame["visible_warning_state"].map(clean_text).str.upper()
        if "visible_warning_state" in frame
        else pd.Series("", index=frame.index, dtype=object)
    )
    warning_active = bool_series(frame, "warning_active")
    attention |= warning_active & warning_type.str.contains(
        r"(?:ATTENTION|BLUE|CAUTION)", na=False
    )
    attention |= warning_active & visible_state.str.contains(ATTENTION_RE, na=False)

    strong = bool_series(frame, "edge_warning_state")
    strong |= prediction.str.contains(STRONG_RE, na=False)
    strong |= warning_active & warning_type.str.contains(
        r"(?:STRONG|EDGE|YELLOW|RED|CRITICAL)", na=False
    )
    strong |= warning_active & visible_state.str.contains(STRONG_RE, na=False)
    source = "telemetry_state"
    distance = first_finite(
        num_series(frame, "directional_edge_distance"),
        num_series(frame, "target_edge_distance"),
    )
    threshold = num_series(frame, "edge_warning_distance_threshold")
    geometry = distance.notna() & threshold.notna() & distance.le(threshold + 1e-9)
    state_columns_present = any(
        name in frame for name in ("edge_warning_state", "prediction_state")
    )
    if not state_columns_present and geometry.any():
        strong = geometry
        source = "geometry_derived"
        review.append("geometry_derived_warning")
    elif "edge_warning_state" not in frame and not strong.any() and geometry.any():
        strong = geometry
        source = "geometry_derived"
        review.append("geometry_derived_warning")
    if "attention_state" not in frame and "prediction_state" not in frame:
        review.append("missing_attention_state")
    if (
        "edge_warning_state" not in frame
        and not prediction.str.contains(STRONG_RE, na=False).any()
        and "warning_type" not in frame
    ):
        review.append("missing_strong_warning_state")
    return attention.astype(bool), strong.astype(bool), source, review


def event_time(frame: pd.DataFrame) -> float:
    timestamps = num_series(frame, "_ts")
    candidates: list[float] = []
    if "fall_event_backend_timestamp" in frame:
        values = num_series(frame, "fall_event_backend_timestamp")
        candidates.extend(float(value) for value in values.dropna() if math.isfinite(float(value)))
    event_rows = bool_series(frame, "fall_event")
    if event_rows.any():
        values = timestamps[event_rows]
        candidates.extend(float(value) for value in values.dropna() if math.isfinite(float(value)))
    relative = num_series(frame, "fall_event_time")
    run_start = num_series(frame, "run_start_backend_timestamp")
    finite_timestamps = timestamps.dropna().to_numpy(float)
    first_timestamp = (
        float(np.min(finite_timestamps)) if len(finite_timestamps) else float("nan")
    )
    last_timestamp = (
        float(np.max(finite_timestamps)) if len(finite_timestamps) else float("nan")
    )
    for index, value in relative.items():
        if not math.isfinite(float(value)):
            continue
        value = float(value)
        if value >= 1e8:
            candidates.append(value)
        elif pd.notna(run_start.loc[index]):
            candidates.append(float(run_start.loc[index]) + value)
        elif bool(event_rows.loc[index]) and pd.notna(timestamps.loc[index]):
            candidates.append(float(timestamps.loc[index]))
        elif (
            math.isfinite(first_timestamp)
            and math.isfinite(last_timestamp)
            and first_timestamp < 1e8
            and first_timestamp - 1e-6 <= value <= last_timestamp + 1e-6
        ):
            # Small synthetic/test exports may use the same relative scale for
            # backend_timestamp and fall_event_time.
            candidates.append(value)
        elif math.isfinite(first_timestamp):
            # If only a relative event time survived the export, anchor it to
            # the first backend sample rather than silently dropping it.
            candidates.append(first_timestamp + value)
    return min(candidates) if candidates else float("nan")


def add_identity(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    result = frame.copy()
    sid_names = [name for name in ("session_id", "source_session_id") if name in result]
    if sid_names:
        result["_session_id"] = result.apply(
            lambda row: first_value(row, sid_names) or path.parent.name, axis=1
        )
    else:
        result["_session_id"] = path.parent.name
    result["_run_id"] = (
        result["run_id"].map(clean_text).replace("", "__session__")
        if "run_id" in result
        else "__session__"
    )
    if "response_layer_id" in result:
        layer = result["response_layer_id"].map(clean_text)
    elif "layer_id" in result:
        layer = result["layer_id"].map(clean_text)
    elif "platform_level" in result:
        layer = result["platform_level"].map(clean_text)
    elif "layer" in result:
        layer = result["layer"].map(clean_text)
    else:
        layer = pd.Series("", index=result.index)
    result["_layer"] = layer.replace("", "__unknown_layer__")
    return result


def manual_index(path: Path | None) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, list[dict[str, str]]]]:
    exact: dict[tuple[str, str], dict[str, str]] = {}
    by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    if path is None:
        return exact, by_session
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "session_id" not in set(reader.fieldnames or []):
            raise ValueError("manual CSV must contain a session_id column")
        for raw in reader:
            row = {key: clean_text(value) for key, value in raw.items() if key}
            sid = row.get("session_id", "")
            if not sid:
                continue
            layer = row.get("layer", "")
            exact[(sid, layer)] = row
            by_session[sid].append(row)
    return exact, by_session


def lookup_manual(
    exact: Mapping[tuple[str, str], dict[str, str]],
    by_session: Mapping[str, list[dict[str, str]]],
    session_id: str,
    layer: str,
    aliases: Iterable[str] = (),
) -> dict[str, str]:
    ids = [session_id, *[alias for alias in aliases if alias]]
    for sid in ids:
        row = exact.get((sid, layer)) or exact.get((sid, ""))
        if row:
            return row
    for sid in ids:
        for row in by_session.get(sid, []):
            if not row.get("layer") or row.get("layer") == layer:
                return row
    return {}


def inward_movement(
    frame: pd.DataFrame, start: int, end: int, minimum_speed: float
) -> tuple[float, float, int]:
    velocity = first_finite(
        num_series(frame, "target_edge_radial_velocity"),
        num_series(frame, "ball_radial_velocity"),
    ).to_numpy(float)
    timestamps = num_series(frame, "_ts").to_numpy(float)
    for index in range(start, end):
        if (
            math.isfinite(velocity[index])
            and math.isfinite(velocity[index + 1])
            and velocity[index] <= minimum_speed
            and velocity[index + 1] <= minimum_speed
            and timestamps[index + 1] >= timestamps[index]
        ):
            return float(timestamps[index]), float(velocity[index]), 2
    return float("nan"), float("nan"), 0


def safe_return(
    frame: pd.DataFrame,
    warning: np.ndarray,
    end: int,
    event: float,
    minimum_duration: float,
) -> tuple[float, float]:
    safe, has_prediction = safe_state_mask(frame)
    if not has_prediction:
        return float("nan"), float("nan")
    timestamps = num_series(frame, "_ts").to_numpy(float)
    active = np.ones(len(frame), dtype=bool)
    if math.isfinite(event):
        active &= timestamps < event
    candidates = safe.to_numpy(bool) & ~warning & active
    for index in range(end + 1, len(frame)):
        if not candidates[index] or not math.isfinite(timestamps[index]):
            continue
        cursor = index
        while cursor + 1 < len(frame) and candidates[cursor + 1]:
            cursor += 1
            if (
                not math.isfinite(timestamps[cursor])
                or timestamps[cursor] < timestamps[cursor - 1]
            ):
                break
            if timestamps[cursor] - timestamps[index] + 1e-9 >= minimum_duration:
                return float(timestamps[index]), float(timestamps[cursor])
        if timestamps[cursor] - timestamps[index] + 1e-9 >= minimum_duration:
            return float(timestamps[index]), float(timestamps[cursor])
    return float("nan"), float("nan")


def minimum(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").to_numpy(float)
    values = values[np.isfinite(values)]
    return float(np.min(values)) if len(values) else float("nan")


def first_frame_value(
    frame: pd.DataFrame, names: Sequence[str], start: int = 0, end: int | None = None
) -> str:
    stop = len(frame) if end is None else min(len(frame), end + 1)
    for name in names:
        if name not in frame:
            continue
        for value in frame[name].iloc[start:stop]:
            text = clean_text(value)
            if text:
                return text
    return ""


def segment_episodes(
    frame: pd.DataFrame,
    episode_type: str,
    mask_series: pd.Series,
    warning_source: str,
    base_review: Sequence[str],
    min_inward_speed: float,
    min_safe_duration: float,
    manual: Mapping[str, str],
    dataset: str,
    file_session_id: str,
    source_file: str,
) -> list[dict[str, Any]]:
    frame = frame.reset_index(drop=True)
    timestamps = num_series(frame, "_ts").to_numpy(float)
    event = event_time(frame)
    fall_rows = bool_series(frame, "fall_event").to_numpy(bool)
    active = np.ones(len(frame), dtype=bool)
    if math.isfinite(event):
        active &= timestamps < event
    raw_warning = mask_series.to_numpy(bool)
    warning = raw_warning & active
    post_fall_rows = int((raw_warning & ~active).sum())
    review = list(base_review)
    if not np.isfinite(timestamps).any():
        review.append("missing_backend_timestamp")
    if "prediction_state" not in frame:
        review.append("missing_prediction_state")
    if not any(name in frame for name in ("target_edge_radial_velocity", "ball_radial_velocity")):
        review.append("missing_radial_velocity")
    if fall_rows.any() and not math.isfinite(event):
        review.append("fall_event_time_ambiguous")

    rows: list[dict[str, Any]] = []
    index = 0
    while index < len(warning):
        if not warning[index]:
            index += 1
            continue
        start = index
        while index + 1 < len(warning) and warning[index + 1]:
            index += 1
        end = index
        start_time = float(timestamps[start]) if math.isfinite(timestamps[start]) else float("nan")
        end_time = float(timestamps[end]) if math.isfinite(timestamps[end]) else float("nan")
        duration = end_time - start_time if math.isfinite(start_time) and math.isfinite(end_time) else float("nan")
        inward_time, inward_velocity, inward_count = inward_movement(
            frame, start, end, min_inward_speed
        )
        safe_time, safe_confirmed = safe_return(
            frame, warning, end, event, min_safe_duration
        )
        clear = end + 1 < len(warning) and not warning[end + 1]
        end_reason = (
            "fall_event"
            if math.isfinite(event) and event <= end_time + 1e-9
            else "state_cleared"
            if clear
            else "segment_end"
        )
        fall_after = (
            math.isfinite(event)
            and math.isfinite(start_time)
            and event >= start_time
            and not (math.isfinite(safe_confirmed) and safe_confirmed < event)
        )
        has_prediction = "prediction_state" in frame
        if fall_after:
            outcome, subtype = "fall_after_warning", "fall_causal"
        elif math.isfinite(safe_time):
            if math.isfinite(inward_time):
                outcome, subtype = "recovered", "near_miss_recovered"
            else:
                outcome, subtype = "false_alarm", "safe_normal"
        elif math.isfinite(inward_time):
            outcome, subtype = "ambiguous", "inward_without_confirmed_safe_return"
        elif not has_prediction:
            outcome, subtype = "ambiguous", "missing_safe_state"
        elif end_reason == "segment_end":
            outcome, subtype = "no_response", "warning_reached_segment_end"
        else:
            outcome, subtype = "ambiguous", "warning_cleared_without_safe_state"

        edge_distance = first_finite(
            num_series(frame, "directional_edge_distance"),
            num_series(frame, "target_edge_distance"),
        )
        margin = edge_distance - num_series(frame, "edge_warning_distance_threshold")
        velocity = first_finite(
            num_series(frame, "target_edge_radial_velocity"),
            num_series(frame, "ball_radial_velocity"),
        )
        flags = list(review)
        if post_fall_rows:
            flags.append("post_fall_rows_excluded")
        if outcome == "ambiguous":
            flags.append("ambiguous_outcome")
        missing = []
        if not np.isfinite(timestamps).any():
            missing.append("backend_timestamp")
        if "prediction_state" not in frame:
            missing.append("prediction_state")
        if not any(name in frame for name in ("target_edge_radial_velocity", "ball_radial_velocity")):
            missing.append("target_edge_radial_velocity/ball_radial_velocity")
        manual_outcome = clean_text(manual.get("manual_outcome"))
        match = "" if not manual_outcome else manual_outcome.lower() == outcome.lower()
        row = {
            "dataset": dataset,
            "session_id": clean_text(frame.loc[0, "_session_id"]),
            "file_session_id": file_session_id,
            "source_file": source_file,
            "run_id": clean_text(frame.loc[0, "_run_id"]),
            "layer": clean_text(frame.loc[0, "_layer"]),
            "condition": clean_text(manual.get("condition"))
            or first_value(frame.iloc[0].to_dict(), (
                "response_condition", "condition", "selected_difficulty", "active_platform_difficulty",
                "platform_difficulty", "difficulty",
            ))
            or "unknown",
            "response_condition": first_frame_value(
                frame, ("response_condition",), start, end
            ),
            "response_experiment_id": first_frame_value(
                frame, ("response_experiment_id", "experiment_id"), start, end
            ),
            "trial_id": first_frame_value(
                frame, ("response_trial_id", "trial_id"), start, end
            ),
            "layer_id": first_frame_value(
                frame, ("response_layer_id", "layer_id"), start, end
            ) or clean_text(frame.loc[0, "_layer"]),
            "intended_action": clean_text(manual.get("intended_action")),
            "manual_outcome": manual_outcome,
            "episode_type": episode_type,
            "warning_start": finite_or_none(start_time),
            "warning_end": finite_or_none(end_time),
            "warning_duration_s": finite_or_none(duration),
            "n_warning_samples": int(end - start + 1),
            "warning_end_reason": end_reason,
            "first_inward_movement_time": finite_or_none(inward_time),
            "first_inward_movement_velocity": finite_or_none(inward_velocity),
            "inward_sample_count": inward_count,
            "reaction_time_s": finite_or_none(inward_time - start_time if math.isfinite(inward_time) and math.isfinite(start_time) else float("nan")),
            "safe_return_time": finite_or_none(safe_time),
            "safe_return_confirmed_time": finite_or_none(safe_confirmed),
            "recovery_time_s": finite_or_none(safe_time - end_time if math.isfinite(safe_time) and math.isfinite(end_time) else float("nan")),
            "fall_event_time": finite_or_none(event),
            "lead_time_s": finite_or_none(event - start_time if math.isfinite(event) and math.isfinite(start_time) and event >= start_time else float("nan")),
            "last_warning_lead_time_s": finite_or_none(event - end_time if math.isfinite(event) and math.isfinite(end_time) and event >= end_time else float("nan")),
            "minimum_directional_edge_distance": finite_or_none(minimum(edge_distance.iloc[start : end + 1])),
            "minimum_warning_margin": finite_or_none(minimum(margin.iloc[start : end + 1])),
            "minimum_radial_velocity": finite_or_none(minimum(velocity.iloc[start : end + 1])),
            "warning_source": first_frame_value(
                frame, ("warning_source",), start, end
            ) or warning_source,
            "warning_type": first_frame_value(
                frame, ("warning_type",), start, end
            ) or episode_type,
            "warning_active": first_frame_value(
                frame, ("warning_active",), start, end
            ),
            "visible_warning_state": first_frame_value(
                frame, ("visible_warning_state",), start, end
            ),
            "warning_episode_id": first_frame_value(
                frame, ("warning_episode_id", "attention_episode_id"), start, end
            ),
            "telemetry_warning_start": first_frame_value(
                frame,
                (
                    "warning_episode_start_backend_timestamp",
                    "warning_episode_start_time",
                    "attention_episode_start_time",
                ),
                start,
                end,
            ),
            "telemetry_warning_end": first_frame_value(
                frame,
                (
                    "warning_episode_end_backend_timestamp",
                    "warning_episode_end_time",
                    "attention_episode_end_time",
                ),
                start,
                end,
            ),
            "attention_episode_id": first_frame_value(
                frame, ("attention_episode_id",), start, end
            ),
            "attention_episode_enter_time": first_frame_value(
                frame, ("attention_episode_enter_time",), start, end
            ),
            "attention_episode_exit_time": first_frame_value(
                frame, ("attention_episode_exit_time",), start, end
            ),
            "attention_episode_start_time": first_frame_value(
                frame, ("attention_episode_start_time",), start, end
            ),
            "attention_episode_end_time": first_frame_value(
                frame, ("attention_episode_end_time",), start, end
            ),
            "outcome": outcome,
            "outcome_subtype": subtype,
            "manual_outcome_match": match,
            "post_fall_warning_rows": post_fall_rows,
            "missing_fields": join_flags(missing),
            "review_flags": join_flags(flags),
            "review_required": bool(flags or missing or (manual_outcome and not match)),
        }
        rows.append(row)
        index += 1
    return rows


def discover_files(input_path: Path, out_dir: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    direct = input_path / "raw.csv"
    files = [direct] if direct.is_file() else sorted(input_path.rglob("raw.csv"))
    if not files:
        files = sorted(input_path.rglob("*.csv"))
    output = out_dir.resolve()
    selected = []
    for path in files:
        try:
            if path.resolve().is_relative_to(output):
                continue
        except AttributeError:
            if str(path.resolve()).startswith(str(output)):
                continue
        selected.append(path)
    return selected


def dataset_name(path: Path) -> str:
    if path.parent.name.lower().startswith("session_") and path.parent.parent != path.parent:
        return path.parent.parent.name
    return path.parent.name or "unknown"


def select_source(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if "source" not in frame:
        return frame, "all_rows"
    source = frame["source"].map(clean_text).str.lower()
    unity = frame.loc[source.eq("unity")].copy()
    return (unity, "unity") if not unity.empty else (frame.copy(), "all_rows_no_unity")


def condition_summary(episodes: pd.DataFrame) -> pd.DataFrame:
    if episodes.empty:
        return pd.DataFrame(columns=CONDITION_COLUMNS)
    rows = []
    for (condition, episode_type), group in episodes.groupby(
        ["condition", "episode_type"], dropna=False, sort=True
    ):
        outcomes = group["outcome"].value_counts()
        subtypes = group["outcome_subtype"].value_counts()
        rows.append({
            "condition": clean_text(condition) or "unknown",
            "episode_type": clean_text(episode_type),
            "sessions": int(group["session_id"].nunique()),
            "episodes": int(len(group)),
            "warning_samples": int(pd.to_numeric(group["n_warning_samples"], errors="coerce").sum()),
            "recovered": int(outcomes.get("recovered", 0)),
            "fall_after_warning": int(outcomes.get("fall_after_warning", 0)),
            "no_response": int(outcomes.get("no_response", 0)),
            "false_alarm": int(outcomes.get("false_alarm", 0)),
            "ambiguous": int(outcomes.get("ambiguous", 0)),
            "near_miss_recovered": int(subtypes.get("near_miss_recovered", 0)),
            "safe_normal": int(subtypes.get("safe_normal", 0)),
            "review_required": int(group["review_required"].fillna(False).astype(bool).sum()),
            "median_lead_time_s": finite_or_none(pd.to_numeric(group["lead_time_s"], errors="coerce").median()),
            "median_reaction_time_s": finite_or_none(pd.to_numeric(group["reaction_time_s"], errors="coerce").median()),
            "median_recovery_time_s": finite_or_none(pd.to_numeric(group["recovery_time_s"], errors="coerce").median()),
        })
    return pd.DataFrame(rows, columns=CONDITION_COLUMNS)


def session_summary(sessions: Mapping[str, dict[str, Any]], episodes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sid, base in sessions.items():
        subset = episodes.loc[episodes["session_id"].astype(str).eq(str(sid))] if not episodes.empty else pd.DataFrame()
        outcomes = subset["outcome"].value_counts() if not subset.empty else pd.Series(dtype=int)
        subtypes = subset["outcome_subtype"].value_counts() if not subset.empty else pd.Series(dtype=int)
        lead = pd.to_numeric(subset.get("lead_time_s", pd.Series(dtype=float)), errors="coerce")
        reaction = pd.to_numeric(subset.get("reaction_time_s", pd.Series(dtype=float)), errors="coerce")
        recovery = pd.to_numeric(subset.get("recovery_time_s", pd.Series(dtype=float)), errors="coerce")
        flags = set(base.get("review_flags", set()))
        if not subset.empty:
            for text in subset["review_flags"].fillna(""):
                flags.update(part for part in str(text).split(";") if part)
        conditions = sorted({clean_text(value) for value in subset.get("condition", []) if clean_text(value)})
        response_conditions = sorted({clean_text(value) for value in subset.get("response_condition", []) if clean_text(value)})
        manuals = sorted({clean_text(value) for value in subset.get("manual_outcome", []) if clean_text(value)})
        experiment_ids = sorted({clean_text(value) for value in subset.get("response_experiment_id", []) if clean_text(value)})
        trial_ids = sorted({clean_text(value) for value in subset.get("trial_id", []) if clean_text(value)})
        layer_ids = sorted({clean_text(value) for value in subset.get("layer_id", []) if clean_text(value)})
        rows.append({
            "dataset": clean_text(base.get("dataset")) or "unknown",
            "session_id": sid,
            "file_session_id": clean_text(base.get("file_session_id")),
            "source_file": ";".join(sorted(base.get("source_files", set()))),
            "condition": ";".join(conditions) or clean_text(base.get("condition")) or "unknown",
            "response_condition": ";".join(response_conditions),
            "response_experiment_id": ";".join(experiment_ids),
            "trial_id": ";".join(trial_ids),
            "layer_ids": ";".join(layer_ids),
            "intended_action": clean_text(base.get("intended_action")),
            "manual_outcome": ";".join(manuals) or clean_text(base.get("manual_outcome")),
            "n_layers": len(base.get("layers", set())),
            "n_segments": int(base.get("segments", 0)),
            "n_episodes": int(len(subset)),
            "attention_episode_count": int((subset["episode_type"] == "attention").sum()) if not subset.empty else 0,
            "strong_episode_count": int((subset["episode_type"] == "strong").sum()) if not subset.empty else 0,
            "fall_event": bool(base.get("fall_event", False)),
            "fall_event_time": finite_or_none(base.get("fall_event_time")),
            "session_outcome": clean_text(base.get("session_outcome")),
            "final_run_state": clean_text(base.get("final_run_state")),
            "warning_any": bool(len(subset)),
            "first_warning_time": finite_or_none(pd.to_numeric(subset.get("warning_start", pd.Series(dtype=float)), errors="coerce").min() if not subset.empty else float("nan")),
            "first_warning_lead_time_s": finite_or_none(lead.min()),
            "median_reaction_time_s": finite_or_none(reaction.median()),
            "median_recovery_time_s": finite_or_none(recovery.median()),
            "median_lead_time_s": finite_or_none(lead.median()),
            "n_recovered": int(outcomes.get("recovered", 0)),
            "n_fall_after_warning": int(outcomes.get("fall_after_warning", 0)),
            "n_no_response": int(outcomes.get("no_response", 0)),
            "n_false_alarm": int(outcomes.get("false_alarm", 0)),
            "n_ambiguous": int(outcomes.get("ambiguous", 0)),
            "n_near_miss_recovered": int(subtypes.get("near_miss_recovered", 0)),
            "n_safe_normal": int(subtypes.get("safe_normal", 0)),
            "review_episode_count": int(subset["review_required"].fillna(False).astype(bool).sum()) if not subset.empty else 0,
            "review_required": bool(flags or (not subset.empty and subset["review_required"].fillna(False).astype(bool).any())),
            "review_flags": join_flags(flags),
        })
    return pd.DataFrame(rows, columns=SESSION_COLUMNS)


def safe_json(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json(item) for item in value]
    return value


def write_readme(out_dir: Path, input_path: Path, min_speed: float, safe_duration: float, counts: Mapping[str, Any]) -> None:
    text = f"""# Warning-response analysis

Input: {input_path}

Attention and strong warning channels are analyzed independently. Attention
uses attention_state or ATTENTION/yellow prediction states. Strong uses
edge_warning_state or EDGE WARNING/contact/critical prediction states. When
warning state fields are absent, a threshold crossing is reported as
geometry_derived and flagged for review.

Rows at or after the first fall event are excluded from causal warnings.
Relative fall_event_time values are anchored to run_start_backend_timestamp
when available. lead_time_s is event minus warning start. reaction_time_s is
the first two-sample radial velocity response (threshold {min_speed:g}) minus
warning start. safe_return_time is the first SAFE row after warning clear and
is confirmed after {safe_duration:g} seconds; recovery_time_s is the delay
from warning end to that first SAFE row.

Outcomes are recovered, fall_after_warning, no_response, false_alarm, and
ambiguous. outcome_subtype distinguishes near_miss_recovered from safe_normal,
so a recovered warning is not automatically a false alarm. Missing or
ambiguous values are listed in review_flags and review_required.

Outputs: warning_response_episodes.csv, warning_response_sessions.csv,
warning_response_conditions.csv, metrics.json, and this README.md.

Sessions: {counts.get("sessions", 0)}; episodes: {counts.get("episodes", 0)};
review episodes: {counts.get("review_required_episodes", 0)}.
"""
    (out_dir / "README.md").write_text(text, encoding="utf-8")


def analyze(
    input_path: Path,
    out_dir: Path,
    manual_csv: Path | None = None,
    min_inward_speed: float = -0.1,
    min_safe_duration: float = 0.3,
) -> dict[str, Any]:
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    if manual_csv is not None:
        manual_csv = Path(manual_csv)
    out_dir.mkdir(parents=True, exist_ok=True)
    exact_manual, session_manual = manual_index(manual_csv)
    files = discover_files(input_path, out_dir)
    all_episodes: list[dict[str, Any]] = []
    sessions: dict[str, dict[str, Any]] = {}
    failed: list[dict[str, str]] = []
    field_rows: Counter[str] = Counter()
    field_present: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    tracked_fields = (
        "backend_timestamp", "source", "session_id", "run_id", "platform_level",
        "fall_event", "fall_event_time", "prediction_state", "attention_state",
        "edge_warning_state", "target_edge_radial_velocity", "ball_radial_velocity",
        "directional_edge_distance", "edge_warning_distance_threshold", "run_state",
        "session_outcome", "response_experiment_id", "experiment_id",
        "response_condition", "condition", "trial_scenario", "response_trial_id",
        "trial_id", "response_layer_id", "layer_id", "warning_source",
        "warning_type", "warning_active", "visible_warning_state",
        "warning_episode_id", "warning_episode_start_time",
        "warning_episode_start_backend_timestamp", "warning_episode_end_time",
        "warning_episode_end_backend_timestamp", "attention_episode_id",
        "attention_episode_enter_time", "attention_episode_exit_time",
        "attention_episode_start_time", "attention_episode_end_time",
    )
    for path in files:
        try:
            raw = pd.read_csv(path, low_memory=False)
        except Exception as exc:
            failed.append({"path": str(path), "error": str(exc)})
            continue
        for field in tracked_fields:
            field_rows[field] += len(raw)
            if field in raw:
                field_present[field] += int(raw[field].notna().sum())
        frame, source_used = select_source(raw)
        source_counts[source_used] += 1
        frame = add_identity(frame, path)
        frame["_ts"] = num_series(frame, "backend_timestamp")
        frame = frame.sort_values("_ts", kind="mergesort", na_position="last").reset_index(drop=True)
        ids = {
            clean_text(value)
            for value in raw.get("session_id", raw.get("source_session_id", pd.Series(dtype=object)))
            if clean_text(value)
        } or {path.parent.name}
        for sid in ids:
            sessions.setdefault(sid, {
                "dataset": dataset_name(path), "file_session_id": path.parent.name,
                "source_files": set(), "layers": set(), "segments": 0,
                "fall_event": False, "fall_event_time": float("nan"), "review_flags": set(),
            })
            sessions[sid]["source_files"].add(str(path))
        for sid_value, session_frame in frame.groupby("_session_id", sort=False):
            sid = clean_text(sid_value) or path.parent.name
            base = sessions.setdefault(sid, {
                "dataset": dataset_name(path), "file_session_id": path.parent.name,
                "source_files": set(), "layers": set(), "segments": 0,
                "fall_event": False, "fall_event_time": float("nan"), "review_flags": set(),
            })
            base["source_files"].add(str(path))
            session_event = event_time(session_frame)
            if math.isfinite(session_event):
                base["fall_event"] = True
                old = base.get("fall_event_time", float("nan"))
                base["fall_event_time"] = session_event if not math.isfinite(float(old)) else min(float(old), session_event)
            outcomes = [clean_text(value) for value in session_frame.get("session_outcome", []) if clean_text(value)]
            states = [clean_text(value) for value in session_frame.get("run_state", []) if clean_text(value)]
            if outcomes:
                base["session_outcome"] = outcomes[-1]
            if states:
                base["final_run_state"] = states[-1]
            for (run_id, layer), segment in session_frame.groupby(["_run_id", "_layer"], sort=False):
                segment = segment.reset_index(drop=True)
                layer = clean_text(layer)
                base["layers"].add(layer)
                base["segments"] += 1
                attention, strong, warning_source, warning_review = warning_masks(segment)
                manual = lookup_manual(
                    exact_manual, session_manual, sid, layer, aliases=(path.parent.name,)
                )
                base.setdefault("condition", manual.get("condition", ""))
                base.setdefault("intended_action", manual.get("intended_action", ""))
                base.setdefault("manual_outcome", manual.get("manual_outcome", ""))
                for channel, mask in (("attention", attention), ("strong", strong)):
                    all_episodes.extend(segment_episodes(
                        segment, channel, mask, warning_source, warning_review,
                        min_inward_speed, min_safe_duration, manual,
                        dataset_name(path), path.parent.name, str(path),
                    ))
                if warning_review:
                    base["review_flags"].update(warning_review)
        if frame["_ts"].notna().sum() == 0:
            for sid in ids:
                sessions[sid]["review_flags"].add("missing_backend_timestamp")

    episodes = pd.DataFrame(all_episodes)
    for column in EPISODE_COLUMNS:
        if column not in episodes:
            episodes[column] = ""
    episodes = episodes.loc[:, EPISODE_COLUMNS]
    episodes.to_csv(out_dir / "warning_response_episodes.csv", index=False, encoding="utf-8-sig")
    session_table = session_summary(sessions, episodes)
    session_table.to_csv(out_dir / "warning_response_sessions.csv", index=False, encoding="utf-8-sig")
    condition_table = condition_summary(episodes)
    condition_table.to_csv(out_dir / "warning_response_conditions.csv", index=False, encoding="utf-8-sig")
    # Keep a small, explicit manual-label template beside the derived tables.
    # It is optional: telemetry remains the primary source and the template is
    # only for trial intent/outcome notes or resolving ambiguous episodes.
    pd.DataFrame(columns=[
        "session_id", "layer", "condition", "intended_action", "manual_outcome",
        "trial_valid", "operator_note",
    ]).to_csv(out_dir / "manual_response_template.csv", index=False, encoding="utf-8-sig")

    review_flags: Counter[str] = Counter()
    if not episodes.empty:
        for text in episodes["review_flags"].fillna(""):
            review_flags.update(part for part in str(text).split(";") if part)
    metrics: dict[str, Any] = {
        "protocol": {
            "min_inward_speed": min_inward_speed,
            "min_inward_samples": 2,
            "min_safe_duration_s": min_safe_duration,
            "post_fall_rows_excluded": True,
        },
        "input": str(input_path),
        "manual_csv": str(manual_csv) if manual_csv else None,
        "files_discovered": len(files), "files_read": len(files) - len(failed),
        "failed_files": failed, "sessions": len(session_table), "episodes": len(episodes),
        "episodes_by_type": episodes["episode_type"].value_counts().to_dict() if not episodes.empty else {},
        "outcomes": episodes["outcome"].value_counts().to_dict() if not episodes.empty else {},
        "outcome_subtypes": episodes["outcome_subtype"].value_counts().to_dict() if not episodes.empty else {},
        "review_required_episodes": int(episodes["review_required"].fillna(False).astype(bool).sum()) if not episodes.empty else 0,
        "review_flags": dict(review_flags), "source_selection": dict(source_counts),
        "field_availability": {
            field: {
                "rows": int(field_rows[field]), "present_rows": int(field_present[field]),
                "fraction": float(field_present[field] / field_rows[field]) if field_rows[field] else None,
            }
            for field in sorted(field_rows)
        },
    }
    metrics = safe_json(metrics)
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_readme(out_dir, input_path, min_inward_speed, min_safe_duration, metrics)
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze attention/strong warning response episodes.")
    parser.add_argument("--input", required=True, type=Path, help="raw.csv, session folder, or dataset root")
    parser.add_argument("--out-dir", type=Path, default=Path("analysis_warning_response"))
    parser.add_argument("--manual-csv", type=Path, default=None)
    parser.add_argument("--min-inward-speed", type=float, default=-0.1)
    parser.add_argument("--min-safe-duration", type=float, default=0.3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.min_safe_duration < 0:
        parser.error("--min-safe-duration must be non-negative")
    metrics = analyze(
        args.input, args.out_dir, args.manual_csv,
        args.min_inward_speed, args.min_safe_duration,
    )
    print(f"wrote {metrics['episodes']} episodes for {metrics['sessions']} sessions to {args.out_dir}")
    if metrics["failed_files"]:
        print(f"failed_files={len(metrics['failed_files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
