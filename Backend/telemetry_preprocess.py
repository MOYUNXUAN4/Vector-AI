"""Clean and align mixed Wii/Unity telemetry logs for offline analysis.

The raw session CSV is never modified.  The command writes clean rows,
60-Hz aligned rows, sliding-window features/labels, and a JSON quality report.
Only pandas and numpy are required.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd


WII_FIELDS = ["tl", "tr", "bl", "br", "total_weight", "cop_x", "cop_z"]
UNITY_FIELDS = [
    "ball_pos_x", "ball_pos_z", "platform_level", "distance_to_hole",
    "platform_tilt", "difficulty",
]
# Optional Unity fields were added after the original pilot sessions.  Keeping
# them separate makes the preprocessing pipeline backward-compatible while
# preserving every new raw measurement for future sessions.
OPTIONAL_UNITY_FIELDS = [
    "passed_count", "run_start_backend_timestamp", "session_end_backend_timestamp",
    "commanded_difficulty", "active_platform_difficulty",
    "platform_center_x", "platform_center_z", "platform_radius", "platform_scale", "platform_difficulty",
    "platform_root_lossy_scale_x", "platform_root_lossy_scale_y", "platform_root_lossy_scale_z",
    "platform_collider_lossy_scale_x", "platform_collider_lossy_scale_y", "platform_collider_lossy_scale_z",
    "ball_velocity_x", "ball_velocity_z", "ball_position_velocity_x", "ball_position_velocity_z",
    "ball_radial_distance", "ball_radial_velocity",
    "nearest_edge_direction_x", "nearest_edge_direction_z",
    "target_edge_direction_x", "target_edge_direction_z", "target_edge_distance", "target_edge_radial_velocity",
    "directional_edge_distance", "directional_edge_point_x", "directional_edge_point_z",
    "ball_radius", "edge_warning_margin", "edge_warning_radius", "edge_warning_distance_threshold",
    "cop_velocity_x", "cop_velocity_z", "cop_speed",
    "selected_session_layers", "target_x", "target_z",
    # Response-experiment event metadata.  These fields are optional so old
    # sessions remain valid, but when present they must survive clean/aligned
    # preprocessing for response-time analysis.
    "attention_state", "trial_valid", "warning_active",
    "warning_episode_id", "warning_episode_start_time",
    "warning_episode_start_backend_timestamp", "warning_episode_end_time",
    "warning_episode_end_backend_timestamp",
    "attention_episode_id", "attention_episode_enter_time",
    "attention_episode_exit_time", "attention_episode_start_time",
    "attention_episode_end_time",
    "edge_warning_time", "edge_warning_backend_timestamp",
    "edge_contact_time", "edge_contact_backend_timestamp",
    "support_lost_time", "support_lost_backend_timestamp",
    "fall_event_time", "fall_event_backend_timestamp",
]
OPTIONAL_TEXT_FIELDS = [
    "platform_radius_source", "fall_direction", "run_id", "run_state", "session_outcome",
    "selected_difficulty", "prediction_state",
    "response_experiment_id", "response_condition", "trial_scenario",
    "response_trial_id", "response_layer_id", "warning_source", "warning_type",
    "visible_warning_state",
]
REQUIRED_BOOLEAN_FIELDS = ["duplicate_sample", "fall_event"]
BOOLEAN_FIELDS = [
    *REQUIRED_BOOLEAN_FIELDS, "directional_edge_valid", "edge_warning_state",
    "calibration_mode", "attention_state", "trial_valid", "warning_active",
]
WINDOW_SECONDS = 1.0
HORIZON_SECONDS = 2.0
STEP_SECONDS = 0.25
TARGET_HZ = 60.0


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(("true", "1", "yes"))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "session"


def load_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, na_values=["", "NaN", "nan", "None"])
    required = {"backend_timestamp", "source", "sequence", *WII_FIELDS, *UNITY_FIELDS,
                *REQUIRED_BOOLEAN_FIELDS}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    # Old pilot raw logs have no geometry/event columns.  Add them as genuine
    # missing values rather than fabricating zeros, then expose a stable
    # schema in clean.csv and aligned_60hz.csv for downstream analysis.
    for col in OPTIONAL_UNITY_FIELDS + OPTIONAL_TEXT_FIELDS + BOOLEAN_FIELDS:
        if col not in df.columns:
            df[col] = np.nan
    df["backend_timestamp"] = pd.to_numeric(df["backend_timestamp"], errors="coerce")
    df["source"] = df["source"].astype(str).str.strip().str.lower()
    text_fields = {"source", "source_timestamp", "fall_reason", *OPTIONAL_TEXT_FIELDS}
    for col in df.columns:
        if col not in text_fields and col not in BOOLEAN_FIELDS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in BOOLEAN_FIELDS:
        # Optional event-state fields remain nullable.  This distinguishes an
        # absent legacy field from an observed false state.
        if df[col].notna().any():
            df[col] = _bool_series(df[col])
    df["fall_reason"] = df["fall_reason"].astype("string")
    return df.sort_values("backend_timestamp", kind="stable").reset_index(drop=True)


def clean_rows(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = raw.copy()
    source_dt = df.groupby("source")["backend_timestamp"].diff()
    df["bad_timestamp"] = ~np.isfinite(df["backend_timestamp"]) | (source_dt.fillna(1) <= 0)
    df["time_gap"] = source_dt.gt(2.0 / TARGET_HZ).fillna(False)
    df["sequence_gap"] = df.groupby("source")["sequence"].diff().fillna(1).ne(1)
    df["valid_weight"] = df["source"].eq("wii") & df["total_weight"].ge(5.0)
    finite_wii = df[WII_FIELDS].notna().all(axis=1)
    nonnegative_wii = df[["tl", "tr", "bl", "br"]].ge(0).all(axis=1)
    df["sensor_values_valid"] = (~df["source"].eq("wii")) | (finite_wii & nonnegative_wii)
    df["valid_sensor_sample"] = (
        df["source"].ne("wii") | (df["valid_weight"] & df["sensor_values_valid"])
    ) & ~df["duplicate_sample"] & ~df["bad_timestamp"]
    df["quality_reason"] = "valid"
    df.loc[df["source"].eq("wii") & ~df["valid_weight"], "quality_reason"] = "low_weight"
    df.loc[df["source"].eq("wii") & df["valid_weight"] & ~df["sensor_values_valid"], "quality_reason"] = "invalid_sensor"
    df.loc[df["bad_timestamp"], "quality_reason"] = "bad_timestamp"
    df.loc[df["duplicate_sample"], "quality_reason"] = "duplicate_sample"
    source_gap_report = {}
    for source, group in df[df["backend_timestamp"].notna()].groupby("source"):
        source_dt = group["backend_timestamp"].diff().dropna()
        source_gap_report[str(source)] = {
            "rows": int(len(group)),
            "rate_hz": float((len(group) - 1) / (group["backend_timestamp"].iloc[-1] - group["backend_timestamp"].iloc[0])) if len(group) > 1 else 0.0,
            "gap_over_2_periods": int((source_dt > 2.0 / TARGET_HZ).sum()),
            "max_gap_seconds": float(source_dt.max()) if len(source_dt) else 0.0,
        }
    report = {
        "rows_raw": int(len(df)),
        "sources": {str(k): int(v) for k, v in df["source"].value_counts().items()},
        "valid_wii_rows": int((df["source"].eq("wii") & df["valid_sensor_sample"]).sum()),
        "invalid_wii_rows": int((df["source"].eq("wii") & ~df["valid_sensor_sample"]).sum()),
        "invalid_rows_by_reason": {str(k): int(v) for k, v in df.loc[~df["valid_sensor_sample"], "quality_reason"].value_counts().items()},
        "fall_events": int(df["fall_event"].sum()),
        "duplicate_samples": int(df["duplicate_sample"].sum()),
        "sequence_gap_rows": int(df["sequence_gap"].sum()),
        "time_gap_rows": int(df["time_gap"].sum()),
        "source_sampling": source_gap_report,
    }
    return df, report


def align_to_unity(clean: pd.DataFrame) -> pd.DataFrame:
    wii = clean[(clean.source == "wii") & clean.valid_sensor_sample].copy()
    unity = clean[(clean.source == "unity") & ~clean.bad_timestamp].copy()
    if wii.empty:
        return pd.DataFrame()
    start = float(wii.backend_timestamp.iloc[0])
    end = float(wii.backend_timestamp.iloc[-1])
    bin_seconds = 1.0 / TARGET_HZ
    grid = np.arange(start, end + bin_seconds / 2.0, bin_seconds)
    source_times = wii.backend_timestamp.to_numpy(float)
    wii60 = pd.DataFrame({"backend_timestamp": grid})
    # Linear interpolation makes both ~33 Hz and ~63 Hz recordings comparable
    # on the same real 60-Hz time grid. Never bridge a gap longer than 50 ms,
    # so off-board/invalid periods remain missing rather than being invented.
    right = np.searchsorted(source_times, grid, side="left")
    left = right - 1
    valid_pair = (left >= 0) & (right < len(source_times))
    gaps = np.full(len(grid), np.inf)
    gaps[valid_pair] = source_times[right[valid_pair]] - source_times[left[valid_pair]]
    for column in WII_FIELDS:
        values = wii[column].to_numpy(float)
        interpolated = np.interp(grid, source_times, values)
        interpolated[~valid_pair] = np.nan
        interpolated[gaps > 0.050] = np.nan
        wii60[column] = interpolated
    nearest = pd.merge_asof(
        wii60[["backend_timestamp"]],
        wii[["backend_timestamp", "sequence", "source_timestamp"]].sort_values("backend_timestamp"),
        on="backend_timestamp", direction="nearest", tolerance=0.025,
    )
    wii60["sequence"] = nearest["sequence"]
    wii60["source_timestamp"] = nearest["source_timestamp"]
    unity_cols = [
        "backend_timestamp", *UNITY_FIELDS, *OPTIONAL_UNITY_FIELDS,
        *OPTIONAL_TEXT_FIELDS, "directional_edge_valid", "edge_warning_state",
        "fall_event", "fall_reason",
    ]
    unity = unity[unity_cols].sort_values("backend_timestamp")
    aligned = pd.merge_asof(wii60, unity, on="backend_timestamp", direction="backward", tolerance=0.025,
                            suffixes=("_wii", "_unity"))
    aligned["unity_aligned"] = aligned["platform_level"].notna()
    aligned["source"] = "aligned"
    aligned["valid_sensor_sample"] = aligned[WII_FIELDS].notna().all(axis=1)
    return aligned


def make_windows(aligned: pd.DataFrame, fall_times: np.ndarray | None = None) -> pd.DataFrame:
    if aligned.empty:
        return pd.DataFrame()
    a = aligned.sort_values("backend_timestamp").reset_index(drop=True)
    t = a.backend_timestamp.to_numpy(float)
    # Use original Unity event timestamps when supplied. A fall can occur just
    # after the final valid Wii sample and therefore may not appear on a
    # backward-aligned 60-Hz row.
    if fall_times is None:
        fall_times = a.loc[a.fall_event.fillna(False), "backend_timestamp"].to_numpy(float)
    else:
        fall_times = np.asarray(fall_times, dtype=float)
    rows = []
    window_n = max(2, round(WINDOW_SECONDS * TARGET_HZ))
    step_n = max(1, round(STEP_SECONDS * TARGET_HZ))
    for end in range(window_n - 1, len(a), step_n):
        start = end - window_n + 1
        segment = a.iloc[start:end + 1]
        if (len(segment) < window_n or not segment.unity_aligned.all()
                or not segment.valid_sensor_sample.all()):
            continue
        end_t = float(t[end])
        prior_fall = fall_times[(fall_times <= end_t) & (fall_times > end_t - HORIZON_SECONDS)]
        future_fall = fall_times[(fall_times > end_t) & (fall_times <= end_t + HORIZON_SECONDS)]
        # Do not train on post-event transition windows.
        if len(prior_fall):
            continue
        x = segment[WII_FIELDS].to_numpy(float)
        cop_x = x[:, 5]
        cop_z = x[:, 6]
        dx = np.diff(cop_x)
        dz = np.diff(cop_z)
        rows.append({
            "window_end": end_t,
            "window_start": float(t[start]),
            "sample_count": int(len(segment)),
            "failure_label": int(len(future_fall) > 0),
            "cop_x_mean": float(np.mean(cop_x)),
            "cop_z_mean": float(np.mean(cop_z)),
            "cop_x_std": float(np.std(cop_x)),
            "cop_z_std": float(np.std(cop_z)),
            "cop_speed_mean": float(np.mean(np.sqrt(dx * dx + dz * dz)) * TARGET_HZ) if len(dx) else 0.0,
            "cop_speed_max": float(np.max(np.sqrt(dx * dx + dz * dz)) * TARGET_HZ) if len(dx) else 0.0,
            "weight_mean": float(segment.total_weight.mean()),
            "distance_mean": float(segment.distance_to_hole.mean()),
            "platform_level": int(segment.platform_level.iloc[-1]),
            "difficulty": int(segment.difficulty.iloc[-1]),
        })
    return pd.DataFrame(rows)


def process(path: Path, output_dir: Path) -> dict:
    raw = load_raw(path)
    clean, report = clean_rows(raw)
    aligned = align_to_unity(clean)
    fall_times = clean.loc[
        clean["source"].eq("unity") & clean["fall_event"], "backend_timestamp"
    ].dropna().to_numpy(float)
    windows = make_windows(aligned, fall_times=fall_times)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Session folders use stable, human-readable names.  For backwards
    # compatibility, a legacy flat CSV still receives stem-prefixed files.
    if path.name.lower() == "raw.csv":
        clean_name, aligned_name, windows_name, quality_name = (
            "clean.csv", "aligned_60hz.csv", "windows.csv", "quality.json"
        )
    else:
        stem = _safe_name(path.stem)
        clean_name, aligned_name, windows_name, quality_name = (
            f"{stem}.clean.csv", f"{stem}.aligned_60hz.csv",
            f"{stem}.windows.csv", f"{stem}.quality.json"
        )
    clean.to_csv(output_dir / clean_name, index=False)
    aligned.to_csv(output_dir / aligned_name, index=False)
    windows.to_csv(output_dir / windows_name, index=False)
    report.update({
        "aligned_rows": int(len(aligned)),
        "alignment_success_rate": float(aligned.unity_aligned.mean()) if len(aligned) else 0.0,
        "windows": int(len(windows)),
        "positive_windows": int(windows.failure_label.sum()) if len(windows) else 0,
        "window_seconds": WINDOW_SECONDS,
        "horizon_seconds": HORIZON_SECONDS,
        "step_seconds": STEP_SECONDS,
        "target_hz": TARGET_HZ,
    })
    (output_dir / quality_name).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="raw session CSV")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    # A session CSV already lives in telemetry_logs/<username>/.  Keep all
    # derived CSVs beside that raw file so the folder remains the single
    # source for one user's sessions.  Use --output-dir only when exporting
    # to a separate analysis location.
    output_dir = args.output_dir or args.csv.parent
    report = process(args.csv, output_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
