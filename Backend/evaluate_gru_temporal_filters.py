"""Offline temporal post-processing experiments for the calibrated GRU.

This module deliberately keeps the existing GRU implementation as the single
source of truth for loading telemetry, making examples, fitting the scaler and
training the model.  It only consumes the resulting examples/probabilities and
does not write to Unity files, manifests or raw telemetry.  The default run
trains on the complete development pool (TEST9282, TEST930 and TEST931), then
evaluates the frozen TEST929 sessions once at the already calibrated threshold
of 0.75.

The temporal filters operate in example time order, within one session and one
contiguous segment.  ``k`` consecutive means k adjacent model windows whose
timestamps are no more than 1.5 strides apart and whose probabilities exceed
the fixed threshold.  An inward cancellation requires a continuous run of
finite negative radial velocity for at least the requested duration.  Missing
radial velocity never gets guessed: cancellation is skipped for that session
and the output marks ``review_required``.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import calibrate_gru_threshold as calibration
import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "gru_temporal_filter_results"
DEFAULT_CANCEL_DURATIONS = (0.2, 0.25, 0.3, 0.5, 0.75)


def _clean_float(value: Any) -> float | None:
    """Return a JSON-friendly finite float, or None for unavailable values."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _method_name(k: int = 1, cancel_s: float | None = None) -> str:
    if cancel_s is None and k == 1:
        return "raw_gru"
    base = f"consecutive_k{k}" if k > 1 else "raw_gru"
    if cancel_s is None:
        return base
    text = f"{cancel_s:.2f}".replace(".", "p")
    return f"{base}_cancel_{text}s"


def _session_groups(examples: Sequence[dict[str, Any]]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, example in enumerate(examples):
        groups[str(example["session_id"])].append(index)
    for indices in groups.values():
        indices.sort(key=lambda index: (float(examples[index]["timestamp"]), index))
    return groups


def _velocity_inventory(sessions: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Describe the preferred inward velocity field for every session.

    ``load_session`` already combines target-edge radial velocity first and
    ball radial velocity second in ``session["velocity"]``.  We retain the
    counts here so an absent field is visible in every report rather than being
    silently treated as zero.
    """

    candidate_indices = {
        name: index for index, name in enumerate(gru.FEATURE_CANDIDATES)
    }
    target_index = candidate_indices.get("target_edge_radial_velocity")
    ball_index = candidate_indices.get("ball_radial_velocity")
    inventory: dict[str, dict[str, Any]] = {}
    for session in sessions:
        table = np.asarray(session["feature_table"], dtype=float)
        target = table[:, target_index] if target_index is not None else np.full(len(table), np.nan)
        ball = table[:, ball_index] if ball_index is not None else np.full(len(table), np.nan)
        target_count = int(np.isfinite(target).sum())
        ball_count = int(np.isfinite(ball).sum())
        preferred_count = int(np.isfinite(np.asarray(session["velocity"], dtype=float)).sum())
        if preferred_count:
            if target_count:
                source = "target_edge_radial_velocity_preferred_with_ball_fallback"
            else:
                source = "ball_radial_velocity_fallback"
            available = True
            review = False
        else:
            source = "unavailable_review_required"
            available = False
            review = True
        inventory[str(session["session_id"])] = {
            "dataset": str(session.get("dataset", "")),
            "target_edge_radial_velocity_finite_rows": target_count,
            "ball_radial_velocity_finite_rows": ball_count,
            "preferred_velocity_finite_rows": preferred_count,
            "source": source,
            "available": available,
            "review_required": review,
        }
    return inventory


def _continuous_inward_duration(session: dict[str, Any]) -> np.ndarray:
    """Compute the elapsed duration of the current negative-velocity run.

    Duration is measured between telemetry timestamps and resets at a segment
    boundary, a missing velocity, a non-negative value, or a non-positive time
    gap.  The first negative row starts at 0 s; a duration threshold is reached
    only after subsequent negative samples span that amount of time.
    """

    timestamps = np.asarray(session["timestamps"], dtype=float)
    segments = np.asarray(session["segments"])
    velocity = np.asarray(session["velocity"], dtype=float)
    duration = np.zeros(len(timestamps), dtype=float)
    for index in range(len(timestamps)):
        if (
            index == 0
            or not np.isfinite(timestamps[index])
            or not np.isfinite(velocity[index])
            or velocity[index] >= 0.0
            or segments[index] != segments[index - 1]
            or not np.isfinite(timestamps[index - 1])
            or timestamps[index] <= timestamps[index - 1]
        ):
            duration[index] = 0.0
            continue
        if np.isfinite(velocity[index - 1]) and velocity[index - 1] < 0.0:
            duration[index] = duration[index - 1] + (timestamps[index] - timestamps[index - 1])
        else:
            duration[index] = 0.0
    return duration


def _inward_flags(
    examples: Sequence[dict[str, Any]],
    sessions_by_id: dict[str, dict[str, Any]],
    duration_s: float,
) -> tuple[np.ndarray, dict[str, str]]:
    """Map continuous inward-duration flags onto model examples."""

    flags = np.zeros(len(examples), dtype=bool)
    status: dict[str, str] = {}
    duration_by_session: dict[str, np.ndarray] = {}
    for session_id, session in sessions_by_id.items():
        velocity = np.asarray(session["velocity"], dtype=float)
        if not np.isfinite(velocity).any():
            status[session_id] = "review_required_velocity_unavailable"
            continue
        duration_by_session[session_id] = _continuous_inward_duration(session)
        status[session_id] = "applied"
    for index, example in enumerate(examples):
        session_id = str(example["session_id"])
        duration = duration_by_session.get(session_id)
        row_index = int(example["row_index"])
        if duration is not None and 0 <= row_index < len(duration):
            flags[index] = bool(duration[row_index] + 1e-12 >= duration_s)
    return flags, status


def _temporal_predictions(
    examples: Sequence[dict[str, Any]],
    raw_positive: np.ndarray,
    stride_s: float,
    k: int = 1,
    cancel_flags: np.ndarray | None = None,
) -> np.ndarray:
    """Apply consecutive-window and optional cancellation rules.

    The run counter resets on a non-positive window, a segment transition, a
    time gap larger than 1.5 strides, or an inward cancellation.  Therefore a
    warning cancelled by inward movement must satisfy k new positive windows
    before it can reappear.
    """

    values = np.asarray(raw_positive, dtype=bool)
    if len(values) != len(examples):
        raise ValueError("raw prediction length does not match examples")
    if cancel_flags is not None and len(cancel_flags) != len(values):
        raise ValueError("cancel flag length does not match examples")
    output = np.zeros(len(values), dtype=bool)
    groups = _session_groups(examples)
    tolerance = max(float(stride_s) * 1.5 + 1e-9, float(stride_s) + 1e-9)
    for indices in groups.values():
        run = 0
        previous_timestamp: float | None = None
        previous_segment: Any = None
        for index in indices:
            timestamp = float(examples[index]["timestamp"])
            segment = examples[index].get("segment")
            adjacent = (
                previous_timestamp is not None
                and np.isfinite(timestamp)
                and np.isfinite(previous_timestamp)
                and timestamp - previous_timestamp <= tolerance
                and timestamp > previous_timestamp
                and segment == previous_segment
            )
            if not adjacent:
                run = 0
            inward_cancel = bool(cancel_flags[index]) if cancel_flags is not None else False
            if inward_cancel:
                # Cancellation consumes this example and forces re-satisfaction
                # of the consecutive condition on later windows.
                run = 0
                output[index] = False
            elif values[index]:
                run += 1
                output[index] = run >= max(int(k), 1)
            else:
                run = 0
                output[index] = False
            previous_timestamp = timestamp
            previous_segment = segment
    return output


def _flatten_metric(result: dict[str, Any], method: str, *, k: int, cancel_s: float | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "method": method,
        "consecutive_k": int(k),
        "cancel_duration_s": cancel_s,
    }
    row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
    row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
    return row


def _detail_rows(
    rows: Iterable[dict[str, Any]],
    method: str,
    k: int,
    cancel_s: float | None,
    velocity_inventory: dict[str, dict[str, Any]],
    cancellation_status: dict[str, str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        session_id = str(row.get("session_id", ""))
        inventory = velocity_inventory.get(session_id, {})
        enriched.update(
            {
                "method": method,
                "consecutive_k": int(k),
                "cancel_duration_s": cancel_s,
                "cancel_status": (
                    cancellation_status.get(session_id, "review_required_velocity_unavailable")
                    if cancel_s is not None
                    else "not_applicable"
                ),
                "velocity_source": inventory.get("source", "review_required_velocity_unavailable"),
                "velocity_review_required": bool(inventory.get("review_required", True)) if cancel_s is not None else False,
            }
        )
        output.append(enriched)
    return output


def _warning_experience(
    examples: Sequence[dict[str, Any]],
    raw_positive: np.ndarray,
    stride_s: float,
    k: int,
    cancel_flags: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Measure warning exposure and cancellation per session.

    For ordinary methods, duration is the union of emitted positive model
    windows.  For cancellation methods, a warning becomes active after k
    consecutive positive windows and ends when the emitted signal becomes
    negative or an inward-cancel flag is observed.  This measures visible
    warning exposure rather than silently counting every probability spike.
    """

    raw_positive = np.asarray(raw_positive, dtype=bool)
    if len(raw_positive) != len(examples):
        raise ValueError("raw prediction length does not match examples")
    if cancel_flags is not None and len(cancel_flags) != len(raw_positive):
        raise ValueError("cancel flag length does not match examples")
    cancellation_mode = cancel_flags is not None
    output: list[dict[str, Any]] = []
    for key, indices in _session_groups(examples).items():
        run = 0
        active = False
        active_start = math.nan
        previous_timestamp: float | None = None
        previous_segment: Any = None
        episodes: list[dict[str, Any]] = []
        cancelled_count = 0

        def close_episode(end_time: float) -> None:
            nonlocal active, active_start
            if active and np.isfinite(active_start) and np.isfinite(end_time):
                episodes.append(
                    {
                        "start": float(active_start),
                        "end": float(max(end_time, active_start)),
                        "duration_s": float(max(end_time - active_start, 0.0)),
                    }
                )
            active = False
            active_start = math.nan

        for index in indices:
            timestamp = float(examples[index]["timestamp"])
            segment = examples[index].get("segment")
            adjacent = (
                previous_timestamp is not None
                and np.isfinite(timestamp)
                and np.isfinite(previous_timestamp)
                and timestamp > previous_timestamp
                and timestamp - previous_timestamp <= float(stride_s) * 1.5 + 1e-9
                and segment == previous_segment
            )
            if not adjacent:
                if active and previous_timestamp is not None:
                    close_episode(previous_timestamp + float(stride_s))
                run = 0

            cancel = bool(cancel_flags[index]) if cancel_flags is not None else False
            if cancellation_mode and cancel:
                if active:
                    close_episode(timestamp)
                    cancelled_count += 1
                run = 0
                previous_timestamp = timestamp
                previous_segment = segment
                continue

            if cancellation_mode:
                if raw_positive[index]:
                    if active:
                        # Keep the current warning episode alive while the
                        # model continues to emit a positive window.
                        pass
                    else:
                        run += 1
                        if run >= max(int(k), 1):
                            active = True
                            active_start = timestamp
                            run = 0
                else:
                    if active:
                        close_episode(timestamp)
                    active = False
                    run = 0
            elif raw_positive[index]:
                # For non-cancellation methods, each positive model window is
                # an emitted warning interval rather than a latched state.
                if not episodes or not adjacent or episodes[-1]["end"] < timestamp:
                    episodes.append({"start": timestamp, "end": timestamp + float(stride_s), "duration_s": float(stride_s)})
                else:
                    episodes[-1]["end"] = float(timestamp + float(stride_s))
                    episodes[-1]["duration_s"] = float(max(episodes[-1]["end"] - episodes[-1]["start"], 0.0))

            previous_timestamp = timestamp
            previous_segment = segment

        if active and previous_timestamp is not None:
            close_episode(previous_timestamp + float(stride_s))
        duration = float(sum(float(episode["duration_s"]) for episode in episodes))
        output.append(
            {
                "dataset": key[0],
                "session_id": key[1],
                "warning_duration_s": duration,
                "warning_episode_count": int(len(episodes)),
                "cancelled_warning_count": int(cancelled_count),
                "warning_cancelled": bool(cancelled_count),
                "final_warning_active": bool(active),
            }
        )
    return output


def _experience_summary(rows: list[dict[str, Any]], examples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate warning-duration and cancellation metrics, with non-falls explicit."""

    fall_by_id = {
        (str(example["dataset"]), str(example["session_id"])): bool(example["is_fall_session"])
        for example in examples
    }
    nonfall = [row for row in rows if not fall_by_id.get((str(row["dataset"]), str(row["session_id"])), False)]
    durations = np.asarray([float(row["warning_duration_s"]) for row in nonfall], dtype=float) if nonfall else np.empty(0)
    warned = durations[durations > 0] if len(durations) else np.empty(0)
    return {
        "nonfall_warning_duration_total_s": float(durations.sum()) if len(durations) else 0.0,
        "nonfall_warning_duration_mean_all_s": float(durations.mean()) if len(durations) else math.nan,
        "nonfall_warning_duration_median_all_s": float(np.median(durations)) if len(durations) else math.nan,
        "nonfall_warning_duration_mean_warned_s": float(warned.mean()) if len(warned) else 0.0,
        "nonfall_warning_duration_median_warned_s": float(np.median(warned)) if len(warned) else 0.0,
        "nonfall_warning_sessions_with_duration": int(np.sum(durations > 0)) if len(durations) else 0,
        "nonfall_sessions": int(len(nonfall)),
        "cancelled_warning_count_all_sessions": int(sum(int(row["cancelled_warning_count"]) for row in rows)),
        "cancelled_warning_session_count": int(sum(bool(row["warning_cancelled"]) for row in rows)),
    }


def _write_plot(comparison: pd.DataFrame, out_dir: Path) -> None:
    """Write a compact, publication-style summary in both raster and vector form."""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Serif",
            "font.size": 9.5,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "figure.dpi": 160,
        }
    )
    labels = comparison["method"].astype(str).tolist()
    x = np.arange(len(labels), dtype=float)
    fig, axes = plt.subplots(2, 1, figsize=(max(10.5, 0.34 * len(labels)), 7.4), sharex=True, constrained_layout=True)
    colors = {"precision": "#2A7F9E", "recall": "#6A3D9A", "f1": "#C73E36"}
    for metric, color in colors.items():
        axes[0].plot(x, comparison[f"session_{metric}"].to_numpy(float), marker="o", linewidth=1.7, markersize=3.8, label=metric.upper(), color=color)
    axes[0].set_ylim(0, 1.05)
    axes[0].set_ylabel("Session metric")
    axes[0].set_title("Frozen TEST929 GRU temporal filtering", color="#23395B", fontweight="bold")
    axes[0].legend(frameon=False, ncol=3, loc="upper right")
    axes[1].plot(x, comparison["session_nonfall_false_alarm_rate"].to_numpy(float), marker="s", linewidth=1.7, markersize=3.5, color="#C73E36", label="Non-fall FAR")
    axes[1].plot(x, comparison["session_last_warning_lead_median_s"].to_numpy(float), marker="D", linewidth=1.7, markersize=3.5, color="#1764A0", label="Last valid lead (s)")
    axes[1].set_ylabel("Rate / seconds")
    axes[1].set_ylim(bottom=0)
    axes[1].legend(frameon=False, ncol=2, loc="upper right")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=65, ha="right", fontsize=7.5)
    for axis in axes:
        axis.grid(color="#D8D8D8", linewidth=0.5)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_axisbelow(True)
    fig.savefig(out_dir / "figure_temporal_filter_comparison.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(out_dir / "figure_temporal_filter_comparison.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _write_experience_plot(comparison: pd.DataFrame, out_dir: Path) -> None:
    """Plot user-visible non-fall warning exposure and cancellations."""

    preferred = [
        "raw_gru",
        "consecutive_k2",
        "raw_gru_cancel_0p20s",
        "consecutive_k2_cancel_0p20s",
    ]
    frame = comparison.loc[comparison["method"].isin(preferred)].copy()
    if frame.empty:
        return
    frame["method"] = pd.Categorical(frame["method"], categories=preferred, ordered=True)
    frame = frame.sort_values("method")
    labels = [str(value).replace("raw_gru_cancel_0p20s", "raw + cancel 0.20s").replace("consecutive_k2_cancel_0p20s", "k=2 + cancel 0.20s").replace("consecutive_k2", "k=2") for value in frame["method"].astype(str)]
    x = np.arange(len(frame), dtype=float)
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 3.8), constrained_layout=True)
    axes[0].bar(x, frame["nonfall_warning_duration_mean_all_s"].to_numpy(float), color="#2A7F9E", width=0.65)
    axes[0].set_ylabel("Seconds per non-fall session")
    axes[0].set_title("Non-fall warning duration")
    axes[1].bar(x, frame["cancelled_warning_count_all_sessions"].to_numpy(float), color="#C73E36", width=0.65)
    axes[1].set_ylabel("Cancelled warning episodes")
    axes[1].set_title("Cancelled warnings")
    for axis in axes:
        axis.set_xticks(x, labels, rotation=25, ha="right")
        axis.grid(axis="y", color="#D8D8D8", linewidth=0.5)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_axisbelow(True)
    fig.suptitle("User-visible GRU warning experience on frozen TEST929", color="#23395B", fontweight="bold")
    fig.savefig(out_dir / "figure_warning_experience.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(out_dir / "figure_warning_experience.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--horizon-seconds", type=float, default=0.5)
    parser.add_argument("--window-seconds", type=float, default=1.0)
    parser.add_argument("--stride-seconds", type=float, default=0.25)
    parser.add_argument("--sequence-length", type=int, default=60)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument(
        "--cancel-durations",
        type=float,
        nargs="+",
        default=list(DEFAULT_CANCEL_DURATIONS),
        help="Inward cancellation durations in seconds; fixed defaults include the requested 0.2, 0.3 and 0.5 s.",
    )
    parser.add_argument("--seed", type=int, default=20261001)
    return parser.parse_args(argv)


def _load_pool() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    development: list[dict[str, Any]] = []
    manifest_notes: list[dict[str, Any]] = []
    for manifest_value in gru.DEFAULT_TRAIN_MANIFESTS:
        manifest = Path(manifest_value)
        loaded, note = gru.load_manifest_sessions(manifest, None, True, False)
        development.extend(loaded)
        manifest_notes.append(note)
    frozen: list[dict[str, Any]] = []
    frozen_notes: list[dict[str, Any]] = []
    for manifest_value in gru.DEFAULT_HELDOUT_MANIFESTS:
        manifest = Path(manifest_value)
        loaded, note = gru.load_manifest_sessions(manifest, None, False, False)
        frozen.extend(loaded)
        frozen_notes.append(note)
    if not development:
        raise RuntimeError("No usable development sessions were loaded")
    if not frozen:
        raise RuntimeError("No usable frozen TEST929 sessions were loaded")
    return development, frozen, manifest_notes + frozen_notes


def run(args: argparse.Namespace) -> dict[str, Any]:
    if abs(float(args.threshold) - 0.75) > 1e-12:
        raise ValueError("The calibrated threshold is fixed at 0.75 for this experiment")
    if args.horizon_seconds <= 0 or args.window_seconds <= 0 or args.stride_seconds <= 0:
        raise ValueError("horizon, window and stride must be positive")
    if args.sequence_length < 2:
        raise ValueError("sequence length must be at least 2")
    durations = sorted({round(float(value), 6) for value in args.cancel_durations if float(value) > 0})
    if not durations:
        raise ValueError("at least one positive cancellation duration is required")
    args.cancel_durations = durations
    random.seed(args.seed)
    np.random.seed(args.seed)

    development, frozen, manifest_notes = _load_pool()
    # Feature indices and all model training examples are derived from the
    # development pool only.  TEST929 is untouched until the final prediction.
    indices = calibration.feature_indices(development)
    if not indices:
        raise RuntimeError("No finite development telemetry features")
    train_examples = calibration.prepare_examples(development, indices, args)
    test_examples = calibration.prepare_examples(frozen, indices, args)
    if not train_examples or not test_examples:
        raise RuntimeError("Development or TEST929 produced no usable model windows")
    model_args = calibration.model_args(args)
    scaler = gru.TrainOnlyScaler.fit(np.stack([example["sequence"] for example in train_examples]))
    probabilities, train_result, history = gru.fit_gru(train_examples, test_examples, scaler, model_args)
    probabilities = np.asarray(probabilities, dtype=float)
    if len(probabilities) != len(test_examples):
        raise RuntimeError("GRU output length does not match TEST929 examples")
    if not np.isfinite(probabilities).any():
        raise RuntimeError(f"GRU did not return finite probabilities: {train_result}")
    raw_positive = probabilities >= float(args.threshold)

    all_sessions = list(development) + list(frozen)
    velocity_inventory = _velocity_inventory(all_sessions)
    frozen_by_id = {str(session["session_id"]): session for session in frozen}
    comparison_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    experience_rows: list[dict[str, Any]] = []
    method_specs: list[tuple[str, int, float | None]] = [("raw_gru", 1, None)]
    method_specs.extend((_method_name(k=k), k, None) for k in (2, 3, 4))
    method_specs.extend((_method_name(k=1, cancel_s=duration), 1, duration) for duration in durations)
    method_specs.extend(
        (_method_name(k=k, cancel_s=duration), k, duration)
        for k in (2, 3, 4)
        for duration in durations
    )

    for method, k, cancel_s in method_specs:
        cancel_flags: np.ndarray | None = None
        cancellation_status: dict[str, str] = {}
        if cancel_s is not None:
            cancel_flags, cancellation_status = _inward_flags(test_examples, frozen_by_id, float(cancel_s))
        predictions = _temporal_predictions(
            test_examples,
            raw_positive,
            float(args.stride_seconds),
            k=k,
            cancel_flags=cancel_flags,
        )
        result, details = gru.metrics_from_predictions(test_examples, predictions, method)
        metric = _flatten_metric(result, method, k=k, cancel_s=cancel_s)
        experience = _warning_experience(
            test_examples,
            raw_positive if cancel_flags is not None else predictions,
            float(args.stride_seconds),
            k=k,
            cancel_flags=cancel_flags,
        )
        metric.update(_experience_summary(experience, test_examples))
        comparison_rows.append(metric)
        experience_rows.extend(
            {
                **row,
                "method": method,
                "consecutive_k": int(k),
                "cancel_duration_s": cancel_s,
                "cancel_status": cancellation_status.get(str(row["session_id"]), "not_applicable")
                if cancel_s is not None
                else "not_applicable",
            }
            for row in experience
        )
        detail_rows.extend(_detail_rows(details, method, k, cancel_s, velocity_inventory, cancellation_status))

    comparison = pd.DataFrame(comparison_rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(args.out_dir / "comparison.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(detail_rows).to_csv(args.out_dir / "session_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(experience_rows).to_csv(args.out_dir / "warning_experience.csv", index=False, encoding="utf-8-sig")
    _write_plot(comparison, args.out_dir)
    _write_experience_plot(comparison, args.out_dir)

    velocity_summary = {
        "sessions_total": int(len(all_sessions)),
        "sessions_with_preferred_velocity": int(sum(bool(item["available"]) for item in velocity_inventory.values())),
        "sessions_missing_preferred_velocity": int(sum(not bool(item["available"]) for item in velocity_inventory.values())),
        "source_counts": dict(pd.Series([item["source"] for item in velocity_inventory.values()]).value_counts()),
    }
    config = {
        "task": "offline_gru_temporal_filters",
        "threshold_fixed": float(args.threshold),
        "horizon_seconds": float(args.horizon_seconds),
        "window_seconds": float(args.window_seconds),
        "stride_seconds": float(args.stride_seconds),
        "sequence_length": int(args.sequence_length),
        "hidden_size": int(args.hidden_size),
        "epochs": int(args.epochs),
        "batch_size": int(args.batch_size),
        "seed": int(args.seed),
        "development_datasets": ["TEST9282", "TEST930", "TEST931"],
        "frozen_dataset": "TEST929",
        "development_sessions": int(len(development)),
        "frozen_TEST929_sessions": int(len(frozen)),
        "development_windows": int(len(train_examples)),
        "frozen_TEST929_windows": int(len(test_examples)),
        "features": [gru.FEATURE_CANDIDATES[index] for index in indices],
        "feature_indices": [int(index) for index in indices],
        "consecutive_k_values": [2, 3, 4],
        "cancellation_durations_seconds": durations,
        "cancellation_velocity_rule": "continuous finite preferred velocity < 0; target_edge_radial_velocity preferred with ball_radial_velocity row-level fallback",
        "cancellation_missing_field_policy": "review_required; leave predictions unchanged for that session",
        "velocity_inventory_summary": velocity_summary,
        "velocity_inventory": velocity_inventory,
        "experience_metrics": {
            "warning_duration_definition": "union of emitted positive model windows; cancellation methods remain active until inward cancellation or segment/gap boundary",
            "cancellation_definition": "active warning ended by continuous inward radial velocity flag",
        },
        "train_only_scaler": scaler.to_json(),
        "training": {"result": train_result, "history": history},
        "manifest_notes": manifest_notes,
        "raw_files_modified": False,
        "test_set_used_for_training_or_selection": False,
    }
    (args.out_dir / "config.json").write_text(json.dumps(gru.finite_json(config), indent=2, ensure_ascii=False), encoding="utf-8")
    readme = (
        "# Offline GRU temporal-filter experiment\n\n"
        "The GRU was trained once on complete development sessions from TEST9282, TEST930 and TEST931. "
        "The calibrated probability threshold was fixed at 0.75; TEST929 was held out until the final frozen evaluation and was not used for training or rule selection.\n\n"
        f"Windows use horizon={args.horizon_seconds:g}s, window={args.window_seconds:g}s, stride={args.stride_seconds:g}s and sequence_length={args.sequence_length}. "
        "`raw_gru` is the thresholded probability stream. `consecutive_kN` emits only after N adjacent positive windows (within one segment). "
        "Cancellation methods reset the consecutive counter after a continuous inward radial velocity run (`< 0`) reaches the configured duration, so a new warning must satisfy the consecutive condition again.\n\n"
        "Velocity comes from `target_edge_radial_velocity` when finite, with a row-level fallback to `ball_radial_velocity`. "
        "Sessions with neither field are explicitly marked `review_required_velocity_unavailable` in `config.json` and `session_metrics.csv`; no substitute field is guessed.\n\n"
        "`comparison.csv` contains aggregate window and session metrics, including session precision/recall/F1, non-fall false-alarm rate, median last valid warning lead, non-fall warning duration and cancellation counts. "
        "`session_metrics.csv` retains each `session_id` and per-method detection/lead details; `warning_experience.csv` retains warning duration and cancellation counts per session. Figures are provided as PNG and PDF. "
        "No Unity, manifest or raw telemetry file was modified.\n"
    )
    (args.out_dir / "README.md").write_text(readme, encoding="utf-8")
    return {
        "out_dir": str(args.out_dir),
        "comparison": comparison_rows,
        "velocity_summary": velocity_summary,
        "train_result": train_result,
        "raw_files_modified": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run(args)
    summary = {
        "out_dir": result["out_dir"],
        "raw_files_modified": result["raw_files_modified"],
        "methods": [
            {
                "method": row["method"],
                "session_precision": _clean_float(row.get("session_precision")),
                "session_recall": _clean_float(row.get("session_recall")),
                "session_f1": _clean_float(row.get("session_f1")),
                "session_nonfall_false_alarm_rate": _clean_float(row.get("session_nonfall_false_alarm_rate")),
                "session_last_warning_lead_median_s": _clean_float(row.get("session_last_warning_lead_median_s")),
            }
            for row in result["comparison"]
        ],
        "velocity_summary": result["velocity_summary"],
    }
    print(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
