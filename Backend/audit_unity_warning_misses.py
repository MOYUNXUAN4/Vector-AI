"""Audit Unity edge-warning misses before changing the game code.

The audit is read-only.  It examines every raw session in TEST9282, TEST929,
TEST930 and TEST931 that contains a real telemetry fall_event, and separates
late/missed warnings into geometry, state, sampling and hole/transition clues.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


BASE = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs")
DATASETS = ("TEST9282", "TEST929", "TEST930", "TEST931")
OUT = BASE / "analysis_unity_warning_miss_audit_20261001"


def num(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce")


def bools(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df:
        return pd.Series(False, index=df.index)
    text = df[name].astype(str).str.strip().str.lower()
    return text.isin({"true", "1", "yes", "y", "t"})


def first_finite(a: pd.Series, b: pd.Series) -> pd.Series:
    return a.where(a.notna(), b)


def episode_onsets(mask: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """Return the timestamps at the start of each true episode."""

    mask = np.asarray(mask, dtype=bool)
    if len(mask) == 0:
        return np.asarray([], dtype=float)
    start = mask.copy()
    start[1:] &= ~mask[:-1]
    return ts[np.flatnonzero(start)]


def audit_session(dataset: str, path: Path) -> tuple[dict[str, Any] | None, pd.DataFrame | None]:
    try:
        raw = pd.read_csv(path, low_memory=False)
    except Exception:
        return None, None
    source = raw["source"].astype(str).str.strip().str.lower() if "source" in raw else pd.Series("unity", index=raw.index)
    df = raw.loc[source.eq("unity")].copy()
    if df.empty:
        return None, None
    df["_ts"] = num(df, "backend_timestamp")
    df = df.loc[df["_ts"].notna()].copy()
    sort_cols = ["_ts"] + (["sequence"] if "sequence" in df else [])
    df = df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    fall = bools(df, "fall_event").to_numpy(bool)
    if not fall.any():
        return None, None
    event_idx = int(np.flatnonzero(fall)[0])
    event_ts = float(df.loc[event_idx, "_ts"])
    pre = df["_ts"].to_numpy(float) < event_ts
    distance = first_finite(num(df, "directional_edge_distance"), num(df, "target_edge_distance")).to_numpy(float)
    threshold = num(df, "edge_warning_distance_threshold").to_numpy(float)
    radius = num(df, "ball_radius").to_numpy(float)
    threshold = np.where(np.isfinite(threshold), threshold, 2.0 * radius)
    valid = bools(df, "directional_edge_valid").to_numpy(bool)
    warning = bools(df, "edge_warning_state").to_numpy(bool)
    contact = bools(df, "edge_contact_state").to_numpy(bool)
    prediction_state = df["prediction_state"].astype(str).str.strip().str.upper().to_numpy() if "prediction_state" in df else np.full(len(df), "", dtype=object)
    hud_warning = prediction_state == "EDGE WARNING"
    geom_trigger = valid & np.isfinite(distance) & np.isfinite(threshold) & (distance <= threshold)
    no_state = geom_trigger & ~warning
    finite_pre = pre & np.isfinite(distance)
    margins = distance - threshold
    ts = df["_ts"].to_numpy(float)
    dt = np.diff(ts)
    dt = dt[np.isfinite(dt) & (dt >= 0)]
    warning_pre = pre & warning
    hud_warning_pre = pre & hud_warning
    warn_times = ts[warning_pre]
    hud_warn_times = ts[hud_warning_pre]
    first_warn = float(warn_times[0]) if len(warn_times) else math.nan
    last_warn = float(warn_times[-1]) if len(warn_times) else math.nan
    hud_onsets = episode_onsets(hud_warning_pre, ts)
    warning_onsets = episode_onsets(warning_pre, ts)
    pre_dist = distance[pre]
    pre_margin = margins[pre]
    event_dist = float(distance[event_idx]) if np.isfinite(distance[event_idx]) else math.nan
    event_threshold = float(threshold[event_idx]) if np.isfinite(threshold[event_idx]) else math.nan
    hole_state = str(df.loc[event_idx, "hole_approach_state"]) if "hole_approach_state" in df else ""
    session = {
        "dataset": dataset,
        "session_id": path.parent.name,
        "raw_csv": str(path),
        "event_timestamp": event_ts,
        "rows_unity": int(len(df)),
        "pre_rows": int(pre.sum()),
        "pre_warning_rows": int(warning_pre.sum()),
        "pre_warning_fraction": float(warning_pre.sum() / pre.sum()) if pre.sum() else math.nan,
        "pre_hud_yellow_rows": int(hud_warning_pre.sum()),
        "pre_hud_yellow_episode_count": int(len(hud_onsets)),
        "pre_geom_trigger_rows": int((geom_trigger & pre).sum()),
        "pre_geom_trigger_without_state_rows": int((no_state & pre).sum()),
        "min_pre_edge_distance": float(np.nanmin(pre_dist)) if np.isfinite(pre_dist).any() else math.nan,
        "min_pre_margin": float(np.nanmin(pre_margin)) if np.isfinite(pre_margin).any() else math.nan,
        "last_pre_edge_distance": float(distance[np.flatnonzero(pre)[-1]]) if pre.any() and np.isfinite(distance[np.flatnonzero(pre)[-1]]) else math.nan,
        "last_pre_threshold": float(threshold[np.flatnonzero(pre)[-1]]) if pre.any() and np.isfinite(threshold[np.flatnonzero(pre)[-1]]) else math.nan,
        "event_edge_distance": event_dist,
        "event_threshold": event_threshold,
        "event_warning_state": bool(warning[event_idx]),
        "event_contact_state": bool(contact[event_idx]),
        "event_directional_valid": bool(valid[event_idx]),
        "event_prediction_state": str(df.loc[event_idx, "prediction_state"]) if "prediction_state" in df else "",
        "event_hole_approach_state": hole_state,
        "first_warning_lead_s": event_ts - first_warn if np.isfinite(first_warn) else math.nan,
        "last_warning_lead_s": event_ts - last_warn if np.isfinite(last_warn) else math.nan,
        "first_hud_yellow_lead_s": event_ts - float(hud_onsets[0]) if len(hud_onsets) else math.nan,
        "last_hud_yellow_onset_lead_s": event_ts - float(hud_onsets[-1]) if len(hud_onsets) else math.nan,
        "max_dt_s": float(np.max(dt)) if len(dt) else math.nan,
        "median_dt_s": float(np.median(dt)) if len(dt) else math.nan,
        "n_invalid_geometry_pre": int((pre & ~valid).sum()),
        "n_nan_distance_pre": int((pre & ~np.isfinite(distance)).sum()),
        "flag_no_pre_warning": bool(warning_pre.sum() == 0),
        "flag_no_pre_hud_yellow": bool(hud_warning_pre.sum() == 0),
        "flag_geometry_reached_but_state_false": bool((no_state & pre).any()),
        "flag_threshold_never_reached": bool(not (geom_trigger & pre).any()),
        "flag_geometry_invalid": bool((pre & ~valid).sum() > 0 and (valid & pre).sum() == 0),
        "flag_large_sampling_gap": bool(np.isfinite(np.max(dt)) and np.max(dt) > 0.10) if len(dt) else False,
        "flag_warning_only_post_event": bool(warning_pre.sum() == 0 and warning[event_idx:].any()),
        "flag_hud_yellow_only_post_event": bool(hud_warning_pre.sum() == 0 and hud_warning[event_idx:].any()),
        "flag_hole_or_transition_at_event": hole_state.upper() in {"AT_HOLE", "APPROACHING_HOLE"},
    }
    rows = df.loc[np.arange(len(df)) >= max(0, event_idx - 12), [c for c in ["_ts", "sequence", "platform_level", "run_id", "ball_pos_x", "ball_pos_z", "ball_radial_distance", "directional_edge_distance", "target_edge_distance", "edge_warning_distance_threshold", "directional_edge_valid", "edge_warning_state", "edge_contact_state", "prediction_state", "fall_event", "target_hole_distance", "target_hole_radius", "hole_approach_state"] if c in df.columns]].copy()
    rows.insert(0, "dataset", dataset)
    rows.insert(1, "session_id", path.parent.name)
    rows["seconds_to_event"] = event_ts - rows["_ts"].astype(float)
    return session, rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    windows: list[pd.DataFrame] = []
    for dataset in DATASETS:
        root = BASE / dataset
        for path in sorted(root.glob("session_*/raw.csv")):
            summary, rows = audit_session(dataset, path)
            if summary is not None:
                summaries.append(summary)
            if rows is not None:
                windows.append(rows)
    summary_df = pd.DataFrame(summaries).sort_values(["dataset", "session_id"])
    summary_df.to_csv(OUT / "fall_warning_audit.csv", index=False, encoding="utf-8-sig")
    if windows:
        pd.concat(windows, ignore_index=True).to_csv(OUT / "last_telemetry_rows.csv", index=False, encoding="utf-8-sig")
    flag_cols = [c for c in summary_df.columns if c.startswith("flag_")]
    counts = {c: int(summary_df[c].fillna(False).astype(bool).sum()) for c in flag_cols}
    dataset_counts = summary_df.groupby("dataset").size().to_dict()
    lead_summary = {}
    for dataset, group in summary_df.groupby("dataset"):
        lead_summary[str(dataset)] = {
            "fall_sessions": int(len(group)),
            "hud_yellow_sessions": int((group["pre_hud_yellow_rows"] > 0).sum()),
            "median_last_hud_yellow_onset_lead_s": float(group["last_hud_yellow_onset_lead_s"].median()),
            "p25_last_hud_yellow_onset_lead_s": float(group["last_hud_yellow_onset_lead_s"].quantile(0.25)),
            "sessions_under_0.10_s_onset_lead": int((group["last_hud_yellow_onset_lead_s"] < 0.10).sum()),
            "sessions_under_0.20_s_onset_lead": int((group["last_hud_yellow_onset_lead_s"] < 0.20).sum()),
        }
    result = {
        "datasets": list(DATASETS),
        "fall_sessions_audited": int(len(summary_df)),
        "fall_sessions_by_dataset": {str(k): int(v) for k, v in dataset_counts.items()},
        "flag_counts": counts,
        "lead_summary_by_dataset": lead_summary,
        "raw_files_modified": False,
        "interpretation": {
            "no_pre_warning": "No edge_warning_state=true row before fall_event.",
            "geometry_reached_but_state_false": "Logged geometry says distance <= threshold while edge_warning_state is false; inspect state timing or platform reset.",
            "threshold_never_reached": "Telemetry geometry never reached the current warning threshold; likely radius/geometry mismatch or a non-edge/hole event.",
            "large_sampling_gap": "A backend timestamp gap > 0.10 s could skip a short warning episode.",
        },
    }
    (OUT / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8")
    lines = [
        "# Unity warning-miss audit",
        "",
        "This report reads raw telemetry only and does not modify Unity or CSV files.",
        "",
        f"Audited {len(summary_df)} fall-event sessions across TEST9282, TEST929, TEST930 and TEST931.",
        "",
        "A missed warning is separated into: (1) geometry never crossed the current threshold, (2) geometry crossed it but edge_warning_state stayed false, (3) all geometry invalid, (4) a large telemetry gap, and (5) hole/transition state at the terminal sample.",
        "",
        "Read fall_warning_audit.csv first, then use last_telemetry_rows.csv to inspect the final 12 samples of any flagged session.",
    ]
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=True, default=float))


if __name__ == "__main__":
    main()
