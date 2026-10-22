"""Extract player response episodes from response-experiment telemetry.

The script is deliberately read-only. It accepts the new Unity response
metadata when available and falls back to the existing prediction/edge-warning
fields for legacy sessions. A manual CSV can add experimental condition and
trial scenario without changing raw telemetry.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TRUE = {"true", "1", "yes", "y", "t"}
FALSE = {"false", "0", "no", "n", "f", "", "nan", "none"}


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in TRUE


def num(df: pd.DataFrame, name: str) -> np.ndarray:
    if name not in df.columns:
        return np.full(len(df), np.nan, dtype=float)
    return pd.to_numeric(df[name], errors="coerce").to_numpy(float)


def text(df: pd.DataFrame, name: str) -> np.ndarray:
    if name not in df.columns:
        return np.full(len(df), "", dtype=object)
    return df[name].fillna("").astype(str).str.strip().to_numpy(dtype=object)


def bool_array(df: pd.DataFrame, name: str) -> np.ndarray:
    return np.asarray([as_bool(v) for v in text(df, name)], dtype=bool)


def first_finite(*arrays: np.ndarray) -> np.ndarray:
    result = np.full(len(arrays[0]), np.nan, dtype=float)
    for array in arrays:
        result = np.where(np.isfinite(result), result, array)
    return result


def session_id_from_path(path: Path) -> str:
    return path.parent.name


def raw_files(root: Path) -> list[Path]:
    paths = []
    for path in root.rglob("raw.csv"):
        # Only session directories are valid telemetry roots; this avoids
        # analysis outputs that happen to contain a CSV with another name.
        if path.parent.name.startswith("session_"):
            paths.append(path)
    return sorted(paths)


def warning_arrays(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, str]:
    prediction = np.char.upper(text(df, "prediction_state").astype(str))
    warning_type = np.char.lower(text(df, "warning_type").astype(str))
    active_field = bool_array(df, "warning_active") if "warning_active" in df else np.zeros(len(df), bool)
    attention = (prediction == "ATTENTION") | np.isin(warning_type, ["attention", "early_attention", "weak"])
    strong = (prediction == "EDGE WARNING") | np.isin(warning_type, ["strong", "edge_warning", "yellow", "imminent"])
    existing = bool_array(df, "edge_warning_state")
    response_active = active_field | attention | strong
    # If the response fields are absent, retain the existing Unity warning as
    # a fallback and record that fact in the episode source column.
    used_fallback = not any(name in df.columns for name in ("warning_active", "warning_type"))
    if used_fallback:
        response_active = existing | (prediction == "EDGE WARNING")
        attention = np.zeros(len(df), bool)
        strong = response_active.copy()
    kinds = np.full(len(df), "none", dtype=object)
    kinds[strong] = "strong"
    kinds[attention & ~strong] = "attention"
    kinds[response_active & (kinds == "none")] = "warning"
    return response_active, kinds, "legacy_edge_warning_fallback" if used_fallback else "response_fields"


def episode_starts(active: np.ndarray, ts: np.ndarray, gap_s: float) -> list[tuple[int, int]]:
    indices = np.flatnonzero(active & np.isfinite(ts))
    if not len(indices):
        return []
    episodes: list[tuple[int, int]] = []
    start = previous = int(indices[0])
    for current in indices[1:]:
        current = int(current)
        if current != previous + 1 or ts[current] - ts[previous] > gap_s:
            episodes.append((start, previous))
            start = current
        previous = current
    episodes.append((start, previous))
    return episodes


def sustained_first(ts: np.ndarray, values: np.ndarray, start: int, end: int, threshold: float, run_s: float) -> int | None:
    candidate = np.isfinite(values) & (values <= threshold)
    for i in range(start, end + 1):
        if not candidate[i]:
            continue
        j = i
        while j <= end and candidate[j] and ts[j] - ts[i] < run_s:
            j += 1
        if j > i and (j > end or ts[j - 1] - ts[i] >= run_s * 0.75):
            return i
    return None


def safe_return_index(ts: np.ndarray, active: np.ndarray, edge_warning: np.ndarray, start: int, end: int, hold_s: float) -> int | None:
    safe = ~active & ~edge_warning
    for i in range(start, end + 1):
        if not safe[i]:
            continue
        j = i
        while j <= end and safe[j] and ts[j] - ts[i] < hold_s:
            j += 1
        if j > i and (j > end or ts[j - 1] - ts[i] >= hold_s * 0.75):
            return i
    return None


def load_manual(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=["session_id", "response_condition", "trial_scenario", "trial_valid"])
    frame = pd.read_csv(path, low_memory=False)
    if "session_id" not in frame.columns:
        raise ValueError("Manual response CSV must contain session_id")
    return frame


def analyze_session(path: Path, manual: pd.DataFrame, response_window_s: float, safe_hold_s: float, inward_threshold: float, inward_run_s: float, gap_s: float) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    df = pd.read_csv(path, low_memory=False)
    if "source" in df.columns:
        df = df.loc[df["source"].astype(str).str.lower().eq("unity")].copy()
    if df.empty:
        return [], {"session_id": session_id_from_path(path), "status": "no_unity_rows"}, "none"
    ts = first_finite(num(df, "backend_timestamp"), num(df, "timestamp"), num(df, "source_timestamp"))
    order = np.argsort(np.where(np.isfinite(ts), ts, np.inf), kind="stable")
    df = df.iloc[order].reset_index(drop=True)
    ts = ts[order]
    finite = np.isfinite(ts)
    if not finite.any():
        return [], {"session_id": session_id_from_path(path), "status": "no_timestamps"}, "none"
    active, kinds, source_mode = warning_arrays(df)
    edge_warning = bool_array(df, "edge_warning_state")
    prediction = np.char.upper(text(df, "prediction_state").astype(str))
    velocity = first_finite(num(df, "target_edge_radial_velocity"), num(df, "ball_radial_velocity"), num(df, "radial_velocity"))
    event_mask = bool_array(df, "fall_event")
    event_ts = float(np.min(ts[event_mask & finite])) if np.any(event_mask & finite) else math.nan
    run_id = text(df, "run_id")
    level = first_finite(num(df, "platform_level"), num(df, "passed_count"))
    segment = np.zeros(len(df), dtype=int)
    if len(df) > 1:
        segment[1:] = np.cumsum((run_id[1:] != run_id[:-1]) | (level[1:] != level[:-1]))
    manual_rows = manual.loc[manual.session_id.astype(str).eq(session_id_from_path(path))] if len(manual) else pd.DataFrame()
    manual_row = manual_rows.iloc[0].to_dict() if len(manual_rows) else {}
    condition = str(manual_row.get("response_condition", text(df, "response_condition")[0] if "response_condition" in df else "unknown"))
    scenario = str(manual_row.get("trial_scenario", text(df, "trial_scenario")[0] if "trial_scenario" in df else "unknown"))
    valid_text = manual_row.get("trial_valid", text(df, "trial_valid")[0] if "trial_valid" in df else "true")
    trial_valid = as_bool(valid_text) if str(valid_text).strip().lower() not in {"", "nan"} else True
    episodes = []
    for episode_no, (start, end) in enumerate(episode_starts(active, ts, gap_s), start=1):
        episode_time = float(ts[start])
        event_after = np.isfinite(event_ts) and event_ts >= episode_time
        search_end = int(np.searchsorted(ts, episode_time + response_window_s, side="right") - 1)
        search_end = min(len(ts) - 1, max(end, search_end))
        if event_after:
            search_end = min(search_end, int(np.searchsorted(ts, event_ts, side="left")))
        inward_idx = sustained_first(ts, velocity, start, search_end, inward_threshold, inward_run_s)
        safe_idx = safe_return_index(ts, active, edge_warning, inward_idx if inward_idx is not None else start, search_end, safe_hold_s) if inward_idx is not None else None
        fall_after = bool(event_after)
        recovered = bool(not fall_after and inward_idx is not None and safe_idx is not None)
        if fall_after:
            outcome = "fall_after_warning"
        elif recovered:
            outcome = "near_miss_recovered"
        elif inward_idx is None:
            outcome = "warning_no_response"
        else:
            outcome = "inward_without_safe_return"
        episodes.append({
            "session_id": session_id_from_path(path), "episode_id": episode_no,
            "response_condition": condition, "trial_scenario": scenario, "trial_valid": trial_valid,
            "warning_source_mode": source_mode, "warning_type": str(kinds[start]),
            "warning_start_backend_timestamp": episode_time,
            "warning_end_backend_timestamp": float(ts[end]),
            "fall_event_backend_timestamp": event_ts,
            "warning_to_inward_s": float(ts[inward_idx] - episode_time) if inward_idx is not None else math.nan,
            "warning_to_safe_s": float(ts[safe_idx] - episode_time) if safe_idx is not None else math.nan,
            "warning_lead_to_fall_s": float(event_ts - episode_time) if fall_after else math.nan,
            "fall_after_warning": fall_after, "recovery_success": recovered,
            "outcome": outcome,
        })
    pre_event = (ts < event_ts) if np.isfinite(event_ts) else np.ones(len(ts), dtype=bool)
    pre_episode = [row for row in episodes if row["warning_start_backend_timestamp"] < event_ts] if np.isfinite(event_ts) else episodes
    summary = {
        "session_id": session_id_from_path(path), "response_condition": condition,
        "trial_scenario": scenario, "trial_valid": trial_valid,
        "warning_source_mode": source_mode, "fall_event": bool(np.isfinite(event_ts)),
        "fall_event_backend_timestamp": event_ts, "warning_episode_count": len(episodes),
        "pre_event_warning_episode_count": len(pre_episode),
        "recovery_success_count": int(sum(row["recovery_success"] for row in episodes)),
        "fall_after_warning_count": int(sum(row["fall_after_warning"] for row in episodes)),
        "warning_no_response_count": int(sum(row["outcome"] == "warning_no_response" for row in episodes)),
        "missed_fall": bool(np.isfinite(event_ts) and not pre_episode),
        "first_warning_lead_s": float(event_ts - pre_episode[0]["warning_start_backend_timestamp"]) if np.isfinite(event_ts) and pre_episode else math.nan,
    }
    return episodes, summary, source_mode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--manual-csv", type=Path)
    parser.add_argument("--response-window-s", type=float, default=0.8)
    parser.add_argument("--safe-hold-s", type=float, default=0.3)
    parser.add_argument("--inward-threshold", type=float, default=-0.10)
    parser.add_argument("--inward-run-s", type=float, default=0.10)
    parser.add_argument("--episode-gap-s", type=float, default=0.5)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manual = load_manual(args.manual_csv)
    all_episodes: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    source_modes: list[str] = []
    for path in raw_files(args.dataset_root):
        episodes, summary, mode = analyze_session(path, manual, args.response_window_s, args.safe_hold_s, args.inward_threshold, args.inward_run_s, args.episode_gap_s)
        all_episodes.extend(episodes)
        summaries.append(summary)
        source_modes.append(mode)
    episodes_frame = pd.DataFrame(all_episodes)
    summary_frame = pd.DataFrame(summaries)
    episodes_frame.to_csv(args.out_dir / "response_episodes.csv", index=False, encoding="utf-8-sig")
    summary_frame.to_csv(args.out_dir / "response_session_summary.csv", index=False, encoding="utf-8-sig")
    template = pd.DataFrame(columns=["session_id", "response_condition", "trial_scenario", "trial_valid", "operator_note"])
    template.to_csv(args.out_dir / "manual_response_template.csv", index=False, encoding="utf-8-sig")
    episode_count = len(episodes_frame)
    recoveries = int(episodes_frame.get("recovery_success", pd.Series(dtype=bool)).sum()) if episode_count else 0
    response = {
        "status": "complete", "dataset_root": str(args.dataset_root),
        "session_count": int(len(summary_frame)), "episode_count": episode_count,
        "fall_sessions": int(summary_frame.get("fall_event", pd.Series(dtype=bool)).sum()) if len(summary_frame) else 0,
        "missed_fall_sessions": int(summary_frame.get("missed_fall", pd.Series(dtype=bool)).sum()) if len(summary_frame) else 0,
        "recovery_success_episodes": recoveries,
        "warning_no_response_episodes": int((episodes_frame.get("outcome", pd.Series(dtype=str)) == "warning_no_response").sum()) if episode_count else 0,
        "median_warning_to_inward_s": float(pd.to_numeric(episodes_frame.get("warning_to_inward_s", pd.Series(dtype=float)), errors="coerce").dropna().median()) if episode_count and episodes_frame["warning_to_inward_s"].notna().any() else math.nan,
        "median_warning_to_safe_s": float(pd.to_numeric(episodes_frame.get("warning_to_safe_s", pd.Series(dtype=float)), errors="coerce").dropna().median()) if episode_count and episodes_frame["warning_to_safe_s"].notna().any() else math.nan,
        "warning_source_modes": sorted(set(source_modes)),
        "manual_csv": str(args.manual_csv) if args.manual_csv else None,
        "parameters": {"response_window_s": args.response_window_s, "safe_hold_s": args.safe_hold_s, "inward_threshold": args.inward_threshold, "inward_run_s": args.inward_run_s, "episode_gap_s": args.episode_gap_s},
        "raw_files_modified": False,
    }
    (args.out_dir / "response_summary.json").write_text(json.dumps(response, indent=2, ensure_ascii=False, allow_nan=True), encoding="utf-8")
    (args.out_dir / "README.md").write_text("# Response experiment analysis\n\n`response_episodes.csv` contains one row per warning episode. `near_miss_recovered` means an inward movement began after warning and the warning returned to SAFE without a fall. `fall_after_warning` and `missed_fall` remain separate. Existing sessions without the new response fields use `edge_warning_state` as a legacy fallback and are marked in `warning_source_mode`. Raw CSV files are never modified.\n", encoding="utf-8")
    print(json.dumps(response, indent=2, ensure_ascii=False, allow_nan=True))


if __name__ == "__main__":
    main()
