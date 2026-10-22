"""Train and evaluate a small, offline GRU fall-warning prototype.

The loader works on the existing per-session ``raw.csv`` telemetry files.  A
window ending at time ``t`` is positive exactly when a telemetry
``fall_event`` occurs in ``(t, t + H]`` in the same contiguous
``(run_id, platform_level)`` segment.  Rows at or after the first event in a
session are excluded, and every sequence is built from one session and one
segment only.

The default data split follows the current time-to-edge analysis: TEST9282,
TEST930, and the included-clean TEST931 sessions are the training pool, while
the complete TEST929 manifest is a held-out evaluation set.  Repeated
``--train-manifest`` and ``--heldout-manifest`` options can be used for another
split; pass ``--random-session-split`` to split the supplied training
manifests deterministically by session instead of using the default TEST929
holdout.

PyTorch is optional at import time.  When it is unavailable, the script still
loads labels and reports the current yellow rule and TTE baselines, then emits
a clear dependency message and skips only the GRU fit.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

try:  # PyTorch is optional so baseline replay remains usable on this backend.
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    TORCH_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on the host environment
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment]
    TensorDataset = None  # type: ignore[assignment]
    TORCH_IMPORT_ERROR = exc


TRUE_VALUES = {"true", "1", "yes", "y", "t", "on"}
SCRIPT_DIR = Path(__file__).resolve().parent
TELEMETRY_ROOT = SCRIPT_DIR / "telemetry_logs"

DEFAULT_TRAIN_MANIFESTS = [
    TELEMETRY_ROOT
    / "TEST9282"
    / "analysis_reduced_sensitivity_20260928_primary_review"
    / "session_manifest.csv",
    TELEMETRY_ROOT / "TEST930" / "analysis_20260929_review" / "session_manifest.csv",
    TELEMETRY_ROOT / "TEST931" / "analysis_20261001_luna" / "session_manifest.csv",
]
DEFAULT_HELDOUT_MANIFESTS = [
    TELEMETRY_ROOT / "TEST929" / "analysis_20260929_luna" / "session_manifest.csv"
]

# These fields are all available in the current Unity telemetry.  A feature is
# retained only when the training sessions contain at least one finite value;
# absent fields are then handled as NaN and imputed from training data.
FEATURE_CANDIDATES = [
    "ball_pos_x",
    "ball_pos_z",
    "ball_velocity_x",
    "ball_velocity_z",
    "ball_radial_distance",
    "ball_radial_velocity",
    "target_edge_distance",
    "target_edge_radial_velocity",
    "directional_edge_distance",
    "target_hole_distance",
    "target_hole_approach_velocity",
    "platform_tilt",
    "platform_level",
    "difficulty",
    "platform_radius",
    "ball_radius",
    "edge_warning_margin",
    "edge_warning_radius",
    "cop_x",
    "cop_z",
    "cop_velocity_x",
    "cop_velocity_z",
    "cop_speed",
]

# The candidate selected in the existing development-pool TTE analysis.
DEFAULT_TTE = {
    "horizon_s": 0.3,
    "persistence_s": 0.2,
    "min_outward_velocity": 0.05,
    "inward_cancel_window_s": 0.0,
}


def as_bool(value: Any) -> bool:
    """Parse telemetry/manifests without treating arbitrary non-empty text as true."""

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return False
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    try:
        return bool(float(text) == 1.0)
    except (TypeError, ValueError):
        return False


def bool_series(values: pd.Series, default: bool = False) -> np.ndarray:
    if values is None:
        return np.full(0, default, dtype=bool)
    result = values.map(as_bool).to_numpy(dtype=bool)
    if default:
        result = np.where(values.isna().to_numpy(), default, result)
    return result


def numeric_series(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.full(len(frame), np.nan, dtype=float)
    values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float, copy=True)
    values[~np.isfinite(values)] = np.nan
    return values


def first_numeric(frame: pd.DataFrame, names: Sequence[str]) -> np.ndarray:
    result = np.full(len(frame), np.nan, dtype=float)
    for name in names:
        candidate = numeric_series(frame, name)
        take = ~np.isfinite(result) & np.isfinite(candidate)
        result[take] = candidate[take]
    return result


def finite_or_missing_text(series: pd.Series | None, default: str = "<missing>") -> np.ndarray:
    if series is None:
        return np.full(0, default, dtype=object)
    values = series.astype("string").fillna(default).astype(str).str.strip()
    values = values.replace({"": default, "nan": default, "None": default, "<NA>": default})
    return values.to_numpy(dtype=object)


def segment_ids(frame: pd.DataFrame) -> np.ndarray:
    """Return contiguous segment IDs that never cross a run or platform level."""

    run = (
        finite_or_missing_text(frame["run_id"])
        if "run_id" in frame
        else np.full(len(frame), "<missing>", dtype=object)
    )
    level = numeric_series(frame, "platform_level")
    level_text = np.array(
        [f"{x:.12g}" if np.isfinite(x) else "<missing>" for x in level], dtype=object
    )
    keys = np.char.add(np.char.add(run.astype(str), "|level="), level_text.astype(str))
    change = np.r_[True, keys[1:] != keys[:-1]] if len(keys) else np.array([], dtype=bool)
    return np.cumsum(change, dtype=np.int64) - 1


def session_root_for_manifest(manifest_path: Path, data_root: Path | None) -> Path:
    """Find the dataset directory containing ``session_<id>/raw.csv``."""

    # Existing manifests live at telemetry_logs/<dataset>/analysis/... .
    inferred = manifest_path.parent.parent
    if data_root is None:
        return inferred
    dataset_name = inferred.name
    direct = data_root / dataset_name
    if direct.exists():
        return direct
    return data_root


def resolve_raw_path(
    manifest_path: Path, row: pd.Series, data_root: Path | None
) -> Path:
    raw_value = str(row.get("raw_csv", "")).strip()
    if raw_value and raw_value.lower() not in {"nan", "none"}:
        candidate = Path(raw_value)
        if candidate.exists():
            return candidate
    root = session_root_for_manifest(manifest_path, data_root)
    session_id = str(row.get("session_id", "")).strip()
    candidate = root / session_id / "raw.csv"
    if candidate.exists():
        return candidate
    # A --data-root may point at telemetry_logs or directly at a dataset.
    if data_root is not None:
        candidate = data_root / session_id / "raw.csv"
    return candidate


def manifest_training_mask(frame: pd.DataFrame, include_conflicted: bool) -> np.ndarray:
    """Apply the existing clean-scope conventions to training manifests."""

    if include_conflicted:
        return np.ones(len(frame), dtype=bool)
    keep = np.ones(len(frame), dtype=bool)
    if "include_clean" in frame.columns:
        keep &= frame["include_clean"].map(as_bool).to_numpy(dtype=bool)
    if "manual_csv_status" in frame.columns:
        status = frame["manual_csv_status"].astype(str).str.strip().str.lower()
        keep &= status.isin({"consistent", "nan", "none", ""}).to_numpy(dtype=bool)
    if "manual_record_conflict" in frame.columns:
        keep &= ~frame["manual_record_conflict"].map(as_bool).to_numpy(dtype=bool)
    if "csv_manual_conflict" in frame.columns:
        keep &= ~frame["csv_manual_conflict"].map(as_bool).to_numpy(dtype=bool)
    if "difficulty_mismatch" in frame.columns:
        keep &= ~frame["difficulty_mismatch"].map(as_bool).to_numpy(dtype=bool)
    return keep


def load_session(raw_path: Path, session_id: str, dataset: str) -> dict[str, Any] | None:
    """Load one Unity stream and its event/segment/baseline arrays."""

    if not raw_path.exists():
        return None
    try:
        raw = pd.read_csv(raw_path, low_memory=False)
    except Exception as exc:
        print(f"[skip] {raw_path}: {exc}", file=sys.stderr)
        return None
    if "source" in raw.columns:
        source = raw["source"].astype(str).str.strip().str.lower()
        unity = raw.loc[source.eq("unity")].copy()
        # Small synthetic fixtures sometimes omit source; all rows are then
        # interpreted as the model stream below.
        if unity.empty:
            unity = raw.copy()
    else:
        unity = raw.copy()
    if unity.empty or "backend_timestamp" not in unity.columns:
        return None
    unity["_timestamp"] = pd.to_numeric(unity["backend_timestamp"], errors="coerce")
    unity = unity.loc[np.isfinite(unity["_timestamp"].to_numpy(dtype=float))].copy()
    if unity.empty:
        return None
    sort_cols = ["_timestamp"]
    if "sequence" in unity.columns:
        sort_cols.append("sequence")
    unity = unity.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    ts = unity["_timestamp"].to_numpy(dtype=float)
    # Keep repeated timestamps in order, but all calculations below use
    # searchsorted and finite durations, so they cannot bridge a new segment.
    segments = segment_ids(unity)
    fall = (
        bool_series(unity["fall_event"])
        if "fall_event" in unity.columns
        else np.zeros(len(unity), dtype=bool)
    )
    event_indices = np.flatnonzero(fall)
    event_ts = ts[event_indices] if len(event_indices) else np.array([], dtype=float)
    first_event_ts = float(np.min(event_ts)) if len(event_ts) else math.nan
    events_by_segment: dict[int, np.ndarray] = {}
    for segment in np.unique(segments):
        values = ts[event_indices[segments[event_indices] == segment]] if len(event_indices) else np.array([], dtype=float)
        events_by_segment[int(segment)] = np.unique(values)

    feature_table = np.column_stack(
        [numeric_series(unity, name) for name in FEATURE_CANDIDATES]
    )
    # The user-visible yellow HUD is driven by prediction_state.  Keep the
    # lower-level controller transition field as a separate fallback/diagnostic
    # because it can lag by one packet during an edge crossing.
    controller_warning = (
        bool_series(unity["edge_warning_state"])
        if "edge_warning_state" in unity.columns
        else np.zeros(len(unity), dtype=bool)
    )
    if "prediction_state" in unity.columns:
        observed_warning = unity["prediction_state"].astype(str).str.strip().str.upper().eq("EDGE WARNING").to_numpy(dtype=bool)
    else:
        observed_warning = controller_warning
    edge_valid = (
        bool_series(unity["directional_edge_valid"])
        if "directional_edge_valid" in unity.columns
        else np.isfinite(first_numeric(unity, ["directional_edge_distance", "target_edge_distance"]))
    )
    distance = first_numeric(unity, ["directional_edge_distance", "target_edge_distance"])
    velocity = first_numeric(unity, ["target_edge_radial_velocity", "ball_radial_velocity"])
    radius = first_numeric(unity, ["ball_radius"])
    return {
        "session_id": session_id,
        "dataset": dataset,
        "path": str(raw_path),
        "timestamps": ts,
        "segments": segments,
        "fall": fall,
        "event_ts": event_ts,
        "first_event_ts": first_event_ts,
        "events_by_segment": events_by_segment,
        "feature_table": feature_table,
        "observed_warning": observed_warning,
        "controller_warning": controller_warning,
        "edge_valid": edge_valid,
        "distance": distance,
        "velocity": velocity,
        "radius": radius,
        "tte_prediction": np.zeros(len(unity), dtype=bool),
        "tte": np.full(len(unity), np.nan, dtype=float),
        "examples": [],
    }


def load_manifest_sessions(
    manifest_path: Path,
    data_root: Path | None,
    training: bool,
    include_conflicted: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load all sessions referenced by a manifest without editing its files."""

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")
    frame = pd.read_csv(manifest_path, low_memory=False)
    if "session_id" not in frame.columns:
        raise ValueError(f"Manifest has no session_id column: {manifest_path}")
    frame = frame.drop_duplicates("session_id", keep="first").copy()
    selected = manifest_training_mask(frame, include_conflicted) if training else np.ones(len(frame), dtype=bool)
    sessions: list[dict[str, Any]] = []
    missing: list[str] = []
    for _, row in frame.loc[selected].iterrows():
        sid = str(row.session_id).strip()
        raw_path = resolve_raw_path(manifest_path, row, data_root)
        dataset = manifest_path.parent.parent.name
        loaded = load_session(raw_path, sid, dataset)
        if loaded is None:
            missing.append(sid)
            continue
        sessions.append(loaded)
    note = {
        "manifest": str(manifest_path),
        "training_scope": bool(training),
        "manifest_rows": int(len(frame)),
        "selected_rows": int(selected.sum()),
        "sessions_loaded": int(len(sessions)),
        "missing_or_unreadable": missing,
        "filtered_rows": int((~selected).sum()),
    }
    return sessions, note


def segment_start_indices(segments: np.ndarray) -> np.ndarray:
    if len(segments) == 0:
        return np.array([], dtype=int)
    return np.r_[0, np.flatnonzero(segments[1:] != segments[:-1]) + 1]


def persistence_mask(
    ts: np.ndarray,
    velocity: np.ndarray,
    segments: np.ndarray,
    minimum_velocity: float,
    duration_s: float,
    fraction_required: float = 0.70,
) -> np.ndarray:
    result = np.zeros(len(ts), dtype=bool)
    if len(ts) < 2 or duration_s <= 0:
        return result
    outward = np.isfinite(velocity) & (velocity >= minimum_velocity)
    starts = segment_start_indices(segments)
    for i, current in enumerate(ts):
        segment_start = int(starts[np.searchsorted(starts, i, side="right") - 1])
        left = max(segment_start, int(np.searchsorted(ts, current - duration_s, side="left")))
        if i - left < 1 or current - ts[left] < duration_s * 0.75:
            continue
        result[i] = float(outward[left : i + 1].mean()) >= fraction_required
    return result


def inward_cancel_mask(
    ts: np.ndarray,
    velocity: np.ndarray,
    segments: np.ndarray,
    minimum_velocity: float,
    cancel_window_s: float,
) -> np.ndarray:
    result = np.zeros(len(ts), dtype=bool)
    if len(ts) == 0 or cancel_window_s <= 0:
        return result
    inward = np.isfinite(velocity) & (velocity <= -minimum_velocity)
    starts = segment_start_indices(segments)
    for i, current in enumerate(ts):
        segment_start = int(starts[np.searchsorted(starts, i, side="right") - 1])
        left = max(segment_start, int(np.searchsorted(ts, current - cancel_window_s, side="left")))
        result[i] = bool(np.any(inward[left : i + 1]))
    return result


def tte_rule_mask(session: dict[str, Any], params: dict[str, float]) -> np.ndarray:
    ts = session["timestamps"]
    distance = session["distance"]
    velocity = session["velocity"]
    radius = session["radius"]
    with np.errstate(divide="ignore", invalid="ignore"):
        tte = (distance - radius) / velocity
    min_velocity = float(params["min_outward_velocity"])
    persistence = persistence_mask(
        ts,
        velocity,
        session["segments"],
        min_velocity,
        float(params["persistence_s"]),
    )
    cancelled = inward_cancel_mask(
        ts,
        velocity,
        session["segments"],
        min_velocity,
        float(params["inward_cancel_window_s"]),
    )
    valid = session["edge_valid"]
    prediction = (
        valid
        & np.isfinite(distance)
        & np.isfinite(velocity)
        & np.isfinite(radius)
        & (velocity >= min_velocity)
        & persistence
        & np.isfinite(tte)
        & (tte >= 0.0)
        & (tte <= float(params["horizon_s"]))
        & ~cancelled
    )
    session["tte"] = tte
    session["tte_prediction"] = prediction
    return prediction


def interp_sequence(
    times: np.ndarray,
    values: np.ndarray,
    start: int,
    end: int,
    grid: np.ndarray,
) -> np.ndarray:
    """Resample one segment window while retaining NaN for entirely missing fields."""

    source_times = times[start : end + 1]
    result = np.full((len(grid), values.shape[1]), np.nan, dtype=np.float32)
    for column in range(values.shape[1]):
        column_values = values[start : end + 1, column]
        finite = np.isfinite(source_times) & np.isfinite(column_values)
        if not finite.any():
            continue
        x = source_times[finite]
        y = column_values[finite]
        # np.interp expects increasing x; duplicate timestamps are collapsed.
        unique_x, unique_indices = np.unique(x, return_index=True)
        y = y[unique_indices]
        if len(unique_x) == 1:
            result[:, column] = np.float32(y[0])
        else:
            result[:, column] = np.interp(grid, unique_x, y).astype(np.float32)
    return result


def build_examples(
    session: dict[str, Any],
    feature_indices: Sequence[int],
    horizon_s: float,
    window_s: float,
    stride_s: float,
    sequence_length: int,
) -> list[dict[str, Any]]:
    """Construct causal, segment-contained windows and corrected future labels."""

    ts = session["timestamps"]
    segments = session["segments"]
    feature_values = session["feature_table"][:, feature_indices]
    starts = segment_start_indices(segments)
    examples: list[dict[str, Any]] = []
    last_end_by_segment: dict[int, float] = {}
    first_event = session["first_event_ts"]
    events_by_segment = session["events_by_segment"]
    for i, current in enumerate(ts):
        if not np.isfinite(current):
            continue
        # A fall row and every post-fall row are removed from the candidate
        # pool.  This also removes later platform transitions after a fall.
        if np.isfinite(first_event) and current >= first_event:
            continue
        segment = int(segments[i])
        if segment in last_end_by_segment and current - last_end_by_segment[segment] < stride_s - 1e-9:
            continue
        segment_start = int(starts[np.searchsorted(starts, i, side="right") - 1])
        left = max(segment_start, int(np.searchsorted(ts, current - window_s, side="left")))
        if i - left < 1:
            continue
        if current - ts[left] < max(0.1, window_s * 0.75):
            continue
        grid_start = max(float(ts[left]), float(current - window_s))
        grid = np.linspace(grid_start, float(current), sequence_length, dtype=float)
        sequence = interp_sequence(ts, feature_values, left, i, grid)
        segment_events = events_by_segment.get(segment, np.array([], dtype=float))
        future = segment_events[(segment_events > current) & (segment_events <= current + horizon_s)]
        event_for_label = float(future[0]) if len(future) else math.nan
        examples.append(
            {
                "session_id": session["session_id"],
                "dataset": session["dataset"],
                "segment": segment,
                "timestamp": float(current),
                "row_index": int(i),
                "label": int(len(future) > 0),
                "event_ts": float(event_for_label) if len(future) else float(session["first_event_ts"]),
                "is_fall_session": bool(np.isfinite(session["first_event_ts"])),
                "sequence": sequence,
                "current_yellow": bool(session["observed_warning"][i]),
                "tte_prediction": bool(session["tte_prediction"][i]),
                "tte": float(session["tte"][i]) if np.isfinite(session["tte"][i]) else math.nan,
            }
        )
        last_end_by_segment[segment] = float(current)
    session["examples"] = examples
    return examples


@dataclass
class TrainOnlyScaler:
    median: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, sequences: np.ndarray) -> "TrainOnlyScaler":
        flat = np.asarray(sequences, dtype=np.float64).reshape(-1, sequences.shape[-1])
        median = np.zeros(flat.shape[1], dtype=np.float64)
        q1 = np.zeros(flat.shape[1], dtype=np.float64)
        q3 = np.zeros(flat.shape[1], dtype=np.float64)
        std = np.zeros(flat.shape[1], dtype=np.float64)
        for column in range(flat.shape[1]):
            finite = flat[:, column][np.isfinite(flat[:, column])]
            if len(finite):
                median[column] = float(np.median(finite))
                q1[column] = float(np.percentile(finite, 25))
                q3[column] = float(np.percentile(finite, 75))
                std[column] = float(np.std(finite))
        median = np.where(np.isfinite(median), median, 0.0)
        scale = q3 - q1
        scale = np.where(np.isfinite(scale) & (scale > 1e-8), scale, std)
        scale = np.where(np.isfinite(scale) & (scale > 1e-8), scale, 1.0)
        return cls(median.astype(np.float32), scale.astype(np.float32))

    def transform(self, sequences: np.ndarray) -> np.ndarray:
        values = np.asarray(sequences, dtype=np.float32).copy()
        # Broadcasting keeps each feature's train-only median independent.
        values = np.where(np.isfinite(values), values, self.median.reshape(1, 1, -1))
        values = (values - self.median.reshape(1, 1, -1)) / self.scale.reshape(1, 1, -1)
        return np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    def to_json(self) -> dict[str, list[float]]:
        return {"median": self.median.astype(float).tolist(), "scale_iqr_or_std": self.scale.astype(float).tolist()}


def flatten_examples(sessions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [example for session in sessions for example in session.get("examples", [])]


def metrics_from_predictions(
    examples: Sequence[dict[str, Any]], predictions: np.ndarray, method: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels = np.array([int(example["label"]) for example in examples], dtype=int)
    predictions = np.asarray(predictions, dtype=bool)
    if len(predictions) != len(labels):
        raise ValueError(f"{method}: prediction length {len(predictions)} != labels {len(labels)}")
    tp = int(np.sum(predictions & (labels == 1)))
    fp = int(np.sum(predictions & (labels == 0)))
    tn = int(np.sum(~predictions & (labels == 0)))
    fn = int(np.sum(~predictions & (labels == 1)))
    precision = tp / (tp + fp) if tp + fp else math.nan
    recall = tp / (tp + fn) if tp + fn else math.nan
    f1 = 2 * precision * recall / (precision + recall) if np.isfinite(precision) and np.isfinite(recall) and precision + recall else 0.0
    window_metrics = {
        "method": method,
        "n_windows": int(len(labels)),
        "positive_windows": int(labels.sum()),
        "negative_windows": int((labels == 0).sum()),
        "predicted_positive_windows": int(predictions.sum()),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": (tp + tn) / len(labels) if len(labels) else math.nan,
    }
    session_rows: list[dict[str, Any]] = []
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, example in enumerate(examples):
        grouped[str(example["session_id"])].append(index)
    for session_id, indices in grouped.items():
        indices_array = np.asarray(indices, dtype=int)
        session_labels = labels[indices_array]
        session_pred = predictions[indices_array]
        is_fall = bool(examples[indices[0]]["is_fall_session"])
        event_ts = float(examples[indices[0]]["event_ts"])
        # The corrected session target is stricter than "any alarm in a
        # session": a fall session is detected only when at least one alarm
        # lands on a positive future-horizon window.  An alarm outside that
        # horizon is retained as an off-target timing error, not silently
        # counted as a true positive.
        target_pred = session_pred & (session_labels == 1)
        off_target_pred = session_pred & (session_labels == 0)
        predicted_times = np.array(
            [float(examples[index]["timestamp"]) for index in indices if predictions[index]], dtype=float
        )
        target_times = np.array(
            [float(examples[index]["timestamp"]) for index in indices if predictions[index] and int(examples[index]["label"]) == 1], dtype=float
        )
        if len(target_times) and np.isfinite(event_ts):
            target_times.sort()
            onset_times = target_times[np.r_[True, np.diff(target_times) > 0.5]]
            first_lead = float(event_ts - onset_times[0])
            last_lead = float(event_ts - onset_times[-1])
            episodes = int(len(onset_times))
        elif len(predicted_times) and np.isfinite(event_ts):
            predicted_times.sort()
            onset_times = predicted_times[np.r_[True, np.diff(predicted_times) > 0.5]]
            first_lead = float(event_ts - onset_times[0])
            last_lead = float(event_ts - onset_times[-1])
            episodes = int(len(onset_times))
        else:
            first_lead = math.nan
            last_lead = math.nan
            episodes = int(len(predicted_times) > 0)
        session_rows.append(
            {
                "method": method,
                "session_id": session_id,
                "dataset": str(examples[indices[0]]["dataset"]),
                "is_fall_session": is_fall,
                "event_ts": event_ts,
                "n_windows": int(len(indices)),
                "positive_windows": int(session_labels.sum()),
                "predicted_positive_windows": int(session_pred.sum()),
                "detected_session": bool(target_pred.any()),
                "false_alarm_session": bool(session_pred.any() and not is_fall),
                "off_target_alarm_session": bool(off_target_pred.any()),
                "target_positive_predictions": int(target_pred.sum()),
                "off_target_predictions": int(off_target_pred.sum()),
                "warning_episode_count": episodes,
                "first_warning_lead_s": first_lead,
                "last_warning_lead_s": last_lead,
            }
        )
    session_frame = pd.DataFrame(session_rows)
    fall_rows = session_frame.loc[session_frame["is_fall_session"]]
    nonfall_rows = session_frame.loc[~session_frame["is_fall_session"]]
    detected_falls = int(fall_rows["detected_session"].sum()) if len(fall_rows) else 0
    false_alarm_sessions = int(nonfall_rows["false_alarm_session"].sum()) if len(nonfall_rows) else 0
    fall_count = int(len(fall_rows))
    nonfall_count = int(len(nonfall_rows))
    session_recall = detected_falls / fall_count if fall_count else math.nan
    session_precision = detected_falls / (detected_falls + false_alarm_sessions) if detected_falls + false_alarm_sessions else math.nan
    session_f1 = (
        2 * session_precision * session_recall / (session_precision + session_recall)
        if np.isfinite(session_precision) and np.isfinite(session_recall) and session_precision + session_recall
        else 0.0
    )
    leads_first = fall_rows["first_warning_lead_s"].dropna().to_numpy(float) if len(fall_rows) else np.array([], dtype=float)
    leads_last = fall_rows["last_warning_lead_s"].dropna().to_numpy(float) if len(fall_rows) else np.array([], dtype=float)
    session_metrics = {
        "method": method,
        "n_sessions": int(len(session_frame)),
        "fall_sessions": fall_count,
        "nonfall_sessions": nonfall_count,
        "detected_fall_sessions": detected_falls,
        "missed_fall_sessions": int(fall_count - detected_falls),
        "false_alarm_sessions": false_alarm_sessions,
        "off_target_alarm_sessions": int(session_frame["off_target_alarm_session"].sum()) if len(session_frame) else 0,
        "detected_target_sessions": detected_falls,
        "nonfall_false_alarm_rate": false_alarm_sessions / nonfall_count if nonfall_count else math.nan,
        "precision": session_precision,
        "recall": session_recall,
        "f1": session_f1,
        "accuracy": (detected_falls + nonfall_count - false_alarm_sessions) / len(session_frame)
        if len(session_frame)
        else math.nan,
        "first_warning_lead_mean_s": float(np.mean(leads_first)) if len(leads_first) else math.nan,
        "first_warning_lead_median_s": float(np.median(leads_first)) if len(leads_first) else math.nan,
        "first_warning_lead_p25_s": float(np.percentile(leads_first, 25)) if len(leads_first) else math.nan,
        "last_warning_lead_mean_s": float(np.mean(leads_last)) if len(leads_last) else math.nan,
        "last_warning_lead_median_s": float(np.median(leads_last)) if len(leads_last) else math.nan,
        "last_warning_lead_p25_s": float(np.percentile(leads_last, 25)) if len(leads_last) else math.nan,
        "warning_episode_mean_per_session": float(session_frame["warning_episode_count"].mean())
        if len(session_frame)
        else math.nan,
    }
    return {"window": window_metrics, "session": session_metrics}, session_rows


def session_split(
    sessions: list[dict[str, Any]], test_fraction: float, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministically split complete sessions, preserving both classes where possible."""

    rng = np.random.default_rng(seed)
    train: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for is_fall in (False, True):
        group = [session for session in sessions if bool(np.isfinite(session["first_event_ts"])) == is_fall]
        order = rng.permutation(len(group)) if group else np.array([], dtype=int)
        n_test = int(round(len(group) * test_fraction))
        if len(group) >= 2:
            n_test = min(max(n_test, 1), len(group) - 1)
        else:
            n_test = min(max(n_test, 0), len(group))
        test.extend(group[int(i)] for i in order[:n_test])
        train.extend(group[int(i)] for i in order[n_test:])
    rng.shuffle(train)
    rng.shuffle(test)
    return train, test


if nn is not None:

    class GRUClassifier(nn.Module):
        def __init__(self, n_features: int, hidden_size: int, layers: int, dropout: float) -> None:
            super().__init__()
            self.gru = nn.GRU(
                input_size=n_features,
                hidden_size=hidden_size,
                num_layers=layers,
                batch_first=True,
                dropout=dropout if layers > 1 else 0.0,
            )
            self.head = nn.Sequential(nn.LayerNorm(hidden_size), nn.Linear(hidden_size, 1))

        def forward(self, values: Any) -> Any:
            output, _ = self.gru(values)
            return self.head(output[:, -1, :]).squeeze(-1)


def fit_gru(
    train_examples: Sequence[dict[str, Any]],
    test_examples: Sequence[dict[str, Any]],
    scaler: TrainOnlyScaler,
    args: argparse.Namespace,
) -> tuple[np.ndarray, dict[str, Any], list[dict[str, Any]]]:
    if torch is None or nn is None or DataLoader is None or TensorDataset is None:
        message = (
            "PyTorch is not installed; GRU training was skipped. Install a CPU build "
            "from https://pytorch.org/get-started/locally/ (for example, `pip install torch`) "
            "and rerun this script."
        )
        print(message, file=sys.stderr)
        return np.full(len(test_examples), np.nan, dtype=float), {
            "status": "skipped",
            "reason": "missing_dependency",
            "message": message,
        }, []

    if not train_examples:
        return np.full(len(test_examples), np.nan, dtype=float), {
            "status": "skipped",
            "reason": "no_training_windows",
        }, []
    train_x = scaler.transform(np.stack([example["sequence"] for example in train_examples]))
    test_x = scaler.transform(np.stack([example["sequence"] for example in test_examples])) if test_examples else np.empty((0, args.sequence_length, train_x.shape[-1]), dtype=np.float32)
    train_y = np.array([int(example["label"]) for example in train_examples], dtype=np.float32)
    n_positive = int(train_y.sum())
    n_negative = int(len(train_y) - n_positive)
    if n_positive == 0 or n_negative == 0:
        message = f"GRU training skipped because training windows have one class (positive={n_positive}, negative={n_negative})."
        print(message, file=sys.stderr)
        return np.full(len(test_examples), np.nan, dtype=float), {
            "status": "skipped",
            "reason": "one_class_training_windows",
            "message": message,
        }, []

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cpu")
    if str(args.device).lower() != "cpu" and torch.cuda.is_available():
        device = torch.device(str(args.device))
    elif str(args.device).lower() != "cpu" and not torch.cuda.is_available():
        print("Requested non-CPU device is unavailable; using CPU.", file=sys.stderr)
    model = GRUClassifier(train_x.shape[-1], args.hidden_size, args.layers, args.dropout).to(device)
    x_tensor = torch.from_numpy(train_x)
    y_tensor = torch.from_numpy(train_y)
    dataset = TensorDataset(x_tensor, y_tensor)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)
    pos_weight = torch.tensor([n_negative / max(n_positive, 1)], dtype=torch.float32, device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    history: list[dict[str, Any]] = []
    model.train()
    for epoch in range(1, args.epochs + 1):
        losses: list[float] = []
        for batch_x, batch_y in loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch_x)
            loss = loss_fn(logits, batch_y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        history.append({"epoch": epoch, "train_loss": float(np.mean(losses)) if losses else math.nan})
    model.eval()
    with torch.no_grad():
        if len(test_x):
            logits = model(torch.from_numpy(test_x).to(device))
            probabilities = torch.sigmoid(logits).detach().cpu().numpy().astype(float)
        else:
            probabilities = np.empty(0, dtype=float)
    return probabilities, {
        "status": "trained",
        "device": str(device),
        "epochs": int(args.epochs),
        "batch_size": int(args.batch_size),
        "hidden_size": int(args.hidden_size),
        "layers": int(args.layers),
        "dropout": float(args.dropout),
        "learning_rate": float(args.learning_rate),
        "weight_decay": float(args.weight_decay),
        "train_windows": int(len(train_examples)),
        "train_positive_windows": n_positive,
        "train_negative_windows": n_negative,
        "pos_weight": float(n_negative / max(n_positive, 1)),
    }, history


def finite_json(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_outputs(
    out_dir: Path,
    args: argparse.Namespace,
    feature_names: list[str],
    scaler: TrainOnlyScaler | None,
    split_rows: list[dict[str, Any]],
    baseline_results: dict[str, dict[str, Any]],
    session_detail_rows: list[dict[str, Any]],
    gru_result: dict[str, Any],
    history: list[dict[str, Any]],
    notes: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(
        json.dumps(
            finite_json(
                {
                    "arguments": vars(args),
                    "feature_names": feature_names,
                    "train_only_scaler": scaler.to_json() if scaler else None,
                    "split_notes": notes,
                }
            ),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(split_rows).to_csv(out_dir / "session_split.csv", index=False, encoding="utf-8-sig")
    comparison_rows: list[dict[str, Any]] = []
    for method, result in baseline_results.items():
        row = {"method": method}
        row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
        row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
        comparison_rows.append(row)
    pd.DataFrame(comparison_rows).to_csv(out_dir / "baseline_comparison.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(session_detail_rows).to_csv(out_dir / "session_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(history).to_csv(out_dir / "training_history.csv", index=False, encoding="utf-8-sig")
    report = {
        "status": "complete",
        "task": "offline_gru_future_horizon",
        "label_definition": "positive iff a real fall_event occurs in (t, t + H] within the same session and contiguous (run_id, platform_level) segment",
        "post_fall_rows_excluded": True,
        "split_by_session": True,
        "horizon_s": float(args.horizon_seconds),
        "window_s": float(args.window_seconds),
        "stride_s": float(args.stride_seconds),
        "sequence_length": int(args.sequence_length),
        "features": feature_names,
        "gru": gru_result,
        "baselines": baseline_results,
        "notes": notes,
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(finite_json(report), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    readme = [
        "# Offline GRU prototype results",
        "",
        "Labels use a real telemetry `fall_event` strictly after the window endpoint and no more than `H` seconds later, with the event in the same session and contiguous `(run_id, platform_level)` segment. Rows at or after the first event in each session are excluded. All scaling statistics are fit on training-session windows only.",
        "",
        f"GRU status: **{gru_result.get('status', 'unknown')}**.",
        "",
        "`baseline_comparison.csv` contains window and session metrics for the current Unity yellow warning and the selected development-pool time-to-edge rule on the same held-out windows. `session_metrics.csv` contains first and last warning leads per session; `metrics.json` contains aggregate non-fall false-alarm rates and lead summaries.",
        "",
        "The generated files are replay outputs. Raw telemetry, Unity files, and existing analysis scripts are not modified.",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--train-manifest",
        "--manifest",
        dest="train_manifests",
        action="append",
        default=None,
        type=Path,
        help="Training-pool manifest; repeat for multiple datasets.",
    )
    parser.add_argument(
        "--heldout-manifest",
        "--validation-manifest",
        dest="heldout_manifests",
        action="append",
        default=None,
        type=Path,
        help="Frozen held-out manifest; repeat for multiple datasets.",
    )
    parser.add_argument(
        "--random-session-split",
        action="store_true",
        help="Ignore the default held-out manifest and split all supplied sessions by session",
    )
    parser.add_argument("--data-root", type=Path, default=None, help="telemetry_logs root or one dataset root")
    parser.add_argument("--out-dir", "--out", type=Path, default=SCRIPT_DIR / "gru_offline_results")
    parser.add_argument("--test-fraction", type=float, default=0.20, help="Session holdout fraction when no held-out manifest is given")
    parser.add_argument("--include-conflicted", action="store_true", help="Keep sessions filtered by clean manifests in the training pool")
    parser.add_argument("--horizon-seconds", "--horizon", type=float, default=2.0)
    parser.add_argument("--window-seconds", "--window", type=float, default=1.0)
    parser.add_argument("--stride-seconds", "--stride", type=float, default=0.25)
    parser.add_argument("--sequence-length", type=int, default=60)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--layers", type=int, default=1)
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--device", default="cpu", help="cpu by default; CUDA is used only when explicitly requested and available")
    parser.add_argument("--seed", type=int, default=20261001)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not 0.0 < args.test_fraction < 1.0:
        raise ValueError("--test-fraction must be in (0, 1)")
    if args.horizon_seconds <= 0 or args.window_seconds <= 0 or args.stride_seconds <= 0:
        raise ValueError("horizon/window/stride seconds must be positive")
    if args.sequence_length < 2:
        raise ValueError("--sequence-length must be at least 2")
    random.seed(args.seed)
    np.random.seed(args.seed)

    train_manifest_paths = [Path(path) for path in (args.train_manifests or DEFAULT_TRAIN_MANIFESTS)]
    heldout_manifest_paths = [Path(path) for path in (args.heldout_manifests or DEFAULT_HELDOUT_MANIFESTS)]
    train_sessions: list[dict[str, Any]] = []
    heldout_sessions: list[dict[str, Any]] = []
    manifest_notes: list[dict[str, Any]] = []
    for manifest in train_manifest_paths:
        loaded, note = load_manifest_sessions(manifest, args.data_root, True, args.include_conflicted)
        train_sessions.extend(loaded)
        manifest_notes.append(note)
    # A custom training manifest without a custom holdout naturally requests a
    # session split; the built-in TEST929 holdout is used only for the fully
    # default command (or when explicitly supplied).
    explicit_heldout = not args.random_session_split and not (
        args.train_manifests is not None and args.heldout_manifests is None
    )
    if explicit_heldout:
        for manifest in heldout_manifest_paths:
            loaded, note = load_manifest_sessions(manifest, args.data_root, False, args.include_conflicted)
            heldout_sessions.extend(loaded)
            manifest_notes.append(note)
    else:
        train_sessions, heldout_sessions = session_split(train_sessions, args.test_fraction, args.seed)
    train_ids = {session["session_id"] for session in train_sessions}
    heldout_ids = {session["session_id"] for session in heldout_sessions}
    overlap = sorted(train_ids & heldout_ids)
    if overlap:
        raise RuntimeError(f"Session leakage between train and held-out sets: {overlap[:5]}")
    if not train_sessions or not heldout_sessions:
        raise RuntimeError(f"Need both training and held-out sessions (train={len(train_sessions)}, heldout={len(heldout_sessions)})")

    feature_indices = [
        index
        for index, name in enumerate(FEATURE_CANDIDATES)
        if any(np.isfinite(session["feature_table"][:, index]).any() for session in train_sessions)
    ]
    if not feature_indices:
        raise RuntimeError("No finite numeric telemetry feature exists in the training sessions")
    feature_names = [FEATURE_CANDIDATES[index] for index in feature_indices]

    for session in train_sessions + heldout_sessions:
        tte_rule_mask(session, DEFAULT_TTE)
        build_examples(
            session,
            feature_indices,
            args.horizon_seconds,
            args.window_seconds,
            args.stride_seconds,
            args.sequence_length,
        )
    train_examples = flatten_examples(train_sessions)
    heldout_examples = flatten_examples(heldout_sessions)
    if not heldout_examples:
        raise RuntimeError("No usable held-out windows were produced; check session duration and feature data")
    scaler = TrainOnlyScaler.fit(np.stack([example["sequence"] for example in train_examples])) if train_examples else None
    gru_probabilities, gru_result, history = fit_gru(train_examples, heldout_examples, scaler, args) if scaler else (
        np.full(len(heldout_examples), np.nan, dtype=float), {"status": "skipped", "reason": "no_training_windows"}, []
    )

    baseline_results: dict[str, dict[str, Any]] = {}
    session_detail_rows: list[dict[str, Any]] = []
    for method, predictions in (
        ("current_yellow_rule", np.array([example["current_yellow"] for example in heldout_examples], dtype=bool)),
        ("time_to_edge", np.array([example["tte_prediction"] for example in heldout_examples], dtype=bool)),
    ):
        result, details = metrics_from_predictions(heldout_examples, predictions, method)
        baseline_results[method] = result
        session_detail_rows.extend(details)
    if gru_result.get("status") == "trained":
        gru_predictions = gru_probabilities >= float(args.threshold)
        result, details = metrics_from_predictions(heldout_examples, gru_predictions, "gru")
        result["probability_threshold"] = float(args.threshold)
        baseline_results["gru"] = result
        session_detail_rows.extend(details)
        for example, probability in zip(heldout_examples, gru_probabilities):
            example["gru_probability"] = float(probability)
    else:
        baseline_results["gru"] = {
            "window": {"method": "gru", "status": gru_result.get("status", "skipped")},
            "session": {"method": "gru", "status": gru_result.get("status", "skipped")},
        }

    split_rows = [
        {
            "session_id": session["session_id"],
            "dataset": session["dataset"],
            "split": "train",
            "is_fall_session": bool(np.isfinite(session["first_event_ts"])),
            "event_ts": float(session["first_event_ts"]) if np.isfinite(session["first_event_ts"]) else math.nan,
            "windows": int(len(session["examples"])),
        }
        for session in train_sessions
    ] + [
        {
            "session_id": session["session_id"],
            "dataset": session["dataset"],
            "split": "heldout",
            "is_fall_session": bool(np.isfinite(session["first_event_ts"])),
            "event_ts": float(session["first_event_ts"]) if np.isfinite(session["first_event_ts"]) else math.nan,
            "windows": int(len(session["examples"])),
        }
        for session in heldout_sessions
    ]
    notes = {
        "train_sessions": int(len(train_sessions)),
        "heldout_sessions": int(len(heldout_sessions)),
        "train_fall_sessions": int(sum(np.isfinite(s["first_event_ts"]) for s in train_sessions)),
        "heldout_fall_sessions": int(sum(np.isfinite(s["first_event_ts"]) for s in heldout_sessions)),
        "train_windows": int(len(train_examples)),
        "heldout_windows": int(len(heldout_examples)),
        "manifest_notes": manifest_notes,
        "tte_parameters": DEFAULT_TTE,
        "torch_import_error": str(TORCH_IMPORT_ERROR) if TORCH_IMPORT_ERROR else None,
    }
    write_outputs(
        args.out_dir,
        args,
        feature_names,
        scaler,
        split_rows,
        baseline_results,
        session_detail_rows,
        gru_result,
        history,
        notes,
    )
    print(json.dumps(finite_json({"out_dir": str(args.out_dir), "gru": gru_result, "baselines": baseline_results}), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
