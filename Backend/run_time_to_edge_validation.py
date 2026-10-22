"""Offline time-to-edge replay for development and frozen TEST929 validation.

The script reads raw telemetry and an existing session manifest without changing
either.  It evaluates the recorded Unity warning and a causal time-to-edge
rule at the session level.  TEST929 is used only as a locked validation set;
parameter selection is performed on the development set before validation is
run.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


TRUE = {"true", "1", "yes", "y", "t"}


def bool_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(TRUE)


def numeric(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce")


def first_numeric(df: pd.DataFrame, names: list[str]) -> pd.Series:
    result = pd.Series(np.nan, index=df.index, dtype=float)
    for name in names:
        result = result.where(result.notna(), numeric(df, name))
    return result


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in TRUE


def session_short_id(session_id: str) -> str:
    parts = session_id.split("_")
    return parts[2] if len(parts) >= 3 else session_id


def episode_count(mask: np.ndarray, ts: np.ndarray, gap_s: float = 0.5) -> int:
    indices = np.flatnonzero(mask)
    if len(indices) == 0:
        return 0
    return 1 + int(np.sum(np.diff(ts[indices]) > gap_s))


def persistence_mask(
    ts: np.ndarray,
    velocity: np.ndarray,
    segment: np.ndarray,
    minimum_velocity: float,
    duration_s: float,
    fraction_required: float = 0.70,
) -> np.ndarray:
    """Require mostly outward samples over a causal duration.

    The fraction guard tolerates occasional telemetry samples and the observed
    irregular Unity sampling interval.  A window must cover at least 75% of its
    requested duration and contain at least two samples.
    """

    result = np.zeros(len(ts), dtype=bool)
    if len(ts) < 2:
        return result
    outward = np.isfinite(velocity) & (velocity >= minimum_velocity)
    segment_start = np.r_[0, np.flatnonzero(segment[1:] != segment[:-1]) + 1]
    for i, current in enumerate(ts):
        left = int(np.searchsorted(ts, current - duration_s, side="left"))
        left = max(left, int(segment_start[np.searchsorted(segment_start, i, side="right") - 1]))
        if i - left < 1:
            continue
        coverage = current - ts[left]
        if coverage < duration_s * 0.75:
            continue
        result[i] = float(outward[left : i + 1].mean()) >= fraction_required
    return result


def inward_cancel_mask(
    ts: np.ndarray,
    velocity: np.ndarray,
    segment: np.ndarray,
    minimum_velocity: float,
    cancel_window_s: float,
) -> np.ndarray:
    """True when a clear recent inward movement should cancel a warning."""

    result = np.zeros(len(ts), dtype=bool)
    if cancel_window_s <= 0 or len(ts) == 0:
        return result
    inward = np.isfinite(velocity) & (velocity <= -minimum_velocity)
    segment_start = np.r_[0, np.flatnonzero(segment[1:] != segment[:-1]) + 1]
    for i, current in enumerate(ts):
        left = int(np.searchsorted(ts, current - cancel_window_s, side="left"))
        left = max(left, int(segment_start[np.searchsorted(segment_start, i, side="right") - 1]))
        result[i] = bool(np.any(inward[left : i + 1]))
    return result


def resolve_session_path(root: Path, row: pd.Series) -> Path:
    raw_value = str(row.get("raw_csv", "")).strip()
    if raw_value and Path(raw_value).exists():
        return Path(raw_value)
    return root / str(row.session_id) / "raw.csv"


def manifest_label(row: pd.Series) -> bool:
    for field in ("failure_label", "csv_fall_event", "fall_event"):
        if field in row.index and str(row[field]).strip() not in {"", "nan", "NaN"}:
            value = row[field]
            if str(value).strip().lower() in TRUE:
                return True
            try:
                return int(float(value)) == 1
            except (TypeError, ValueError):
                continue
    return False


def manifest_difficulty(row: pd.Series) -> tuple[float, float]:
    manual = np.nan
    telemetry = np.nan
    for field in ("manual_difficulty", "difficulty_manual"):
        if field in row.index:
            try:
                manual = float(row[field])
                break
            except (TypeError, ValueError):
                pass
    for field in ("telemetry_difficulty_first", "selected_difficulty_values", "selected_difficulty_csv"):
        if field in row.index:
            try:
                telemetry = float(str(row[field]).split(";")[0])
                break
            except (TypeError, ValueError):
                pass
    return manual, telemetry


def load_session(root: Path, row: pd.Series) -> dict[str, Any] | None:
    path = resolve_session_path(root, row)
    if not path.exists():
        return None
    df = pd.read_csv(path, low_memory=False)
    source = df["source"].astype(str).str.strip().str.lower() if "source" in df else pd.Series("unity", index=df.index)
    unity = df.loc[source.eq("unity")].copy()
    if unity.empty:
        return None
    unity["_ts"] = numeric(unity, "backend_timestamp")
    unity = unity.loc[unity["_ts"].notna()].copy()
    if unity.empty:
        return None
    sort_columns = ["_ts"]
    if "sequence" in unity.columns:
        sort_columns.append("sequence")
    unity = unity.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    ts = unity["_ts"].to_numpy(float)
    fall = bool_series(unity["fall_event"]) if "fall_event" in unity else pd.Series(False, index=unity.index)
    event_values = ts[fall.to_numpy(bool)]
    event_ts = float(np.min(event_values)) if len(event_values) else math.nan
    pre = np.ones(len(unity), dtype=bool) if not np.isfinite(event_ts) else ts < event_ts
    distance = first_numeric(unity, ["directional_edge_distance", "target_edge_distance"])
    velocity = first_numeric(unity, ["target_edge_radial_velocity", "ball_radial_velocity"])
    radius = numeric(unity, "ball_radius")
    valid = bool_series(unity["directional_edge_valid"]) if "directional_edge_valid" in unity else distance.notna()
    observed = bool_series(unity["edge_warning_state"]).to_numpy(bool) if "edge_warning_state" in unity else np.zeros(len(unity), dtype=bool)
    level = numeric(unity, "platform_level").fillna(-1).to_numpy(float)
    run_id = unity["run_id"].astype(str).to_numpy() if "run_id" in unity else np.zeros(len(unity), dtype=int)
    # Do not carry persistence/correction state over to a new platform/run.
    segment = np.zeros(len(unity), dtype=int)
    if len(unity) > 1:
        segment[1:] = np.cumsum((level[1:] != level[:-1]) | (run_id[1:] != run_id[:-1]))
    manual_d, telemetry_d = manifest_difficulty(row)
    return {
        "session_id": str(row.session_id),
        "short_id": session_short_id(str(row.session_id)),
        "manual_difficulty": manual_d,
        "telemetry_difficulty": telemetry_d,
        "is_fall": manifest_label(row),
        "event_ts": event_ts,
        "ts": ts,
        "pre": pre,
        "distance": distance.to_numpy(float),
        "velocity": velocity.to_numpy(float),
        "radius": radius.to_numpy(float),
        "valid": valid.to_numpy(bool),
        "observed": observed,
        "segment": segment,
        "platform_level": level,
        "ball_x": numeric(unity, "ball_pos_x").to_numpy(float),
        "ball_z": numeric(unity, "ball_pos_z").to_numpy(float),
        "center_x": numeric(unity, "platform_center_x").to_numpy(float),
        "center_z": numeric(unity, "platform_center_z").to_numpy(float),
        "platform_radius": numeric(unity, "platform_radius").to_numpy(float),
    }


def time_to_edge_mask(
    session: dict[str, Any],
    horizon_s: float,
    persistence_s: float,
    minimum_velocity: float,
    cancel_window_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    ts = session["ts"]
    distance = session["distance"]
    velocity = session["velocity"]
    radius = session["radius"]
    valid = session["valid"]
    outward = np.isfinite(velocity) & (velocity >= minimum_velocity)
    with np.errstate(divide="ignore", invalid="ignore"):
        tte = (distance - radius) / velocity
    cache = session.setdefault("_rule_cache", {})
    persistence_key = ("persistence", float(minimum_velocity), float(persistence_s))
    cancel_key = ("cancel", float(minimum_velocity), float(cancel_window_s))
    if persistence_key not in cache:
        cache[persistence_key] = persistence_mask(ts, velocity, session["segment"], minimum_velocity, persistence_s)
    if cancel_key not in cache:
        cache[cancel_key] = inward_cancel_mask(ts, velocity, session["segment"], minimum_velocity, cancel_window_s)
    persistence = cache[persistence_key]
    cancelled = cache[cancel_key]
    prediction = valid & outward & persistence & np.isfinite(tte) & (tte >= 0.0) & (tte <= horizon_s) & ~cancelled
    return prediction, tte


def legacy_directional_mask(session: dict[str, Any]) -> np.ndarray:
    """Replay the old v2 directional-risk rule with its fixed threshold/weights.

    The old 42.1% is a different-dataset session detection result. For a fair
    same-cohort comparison, this applies its frozen 1 s features and 0.8 risk
    threshold to TEST929, using the actual logged platform radius rather than
    estimating geometry from TEST929 fall labels.
    """

    ts = session["ts"]
    x_all = session["ball_x"] - session["center_x"]
    z_all = session["ball_z"] - session["center_z"]
    radius_all = session["platform_radius"]
    segment = session["segment"]
    valid = session["valid"]
    risk = np.full(len(ts), np.nan)
    segment_start = np.r_[0, np.flatnonzero(segment[1:] != segment[:-1]) + 1]
    for i, current_ts in enumerate(ts):
        if not valid[i] or not np.isfinite(radius_all[i]) or radius_all[i] <= 0:
            continue
        left = int(np.searchsorted(ts, current_ts - 1.0, side="left"))
        left = max(left, int(segment_start[np.searchsorted(segment_start, i, side="right") - 1]))
        hts = ts[left : i + 1]
        hx = x_all[left : i + 1]
        hz = z_all[left : i + 1]
        good = np.isfinite(hts) & np.isfinite(hx) & np.isfinite(hz)
        hts, hx, hz = hts[good], hx[good], hz[good]
        if len(hts) < 8:
            continue
        dt = np.diff(hts)
        valid_dt = dt > 1e-4
        if valid_dt.sum() < 4:
            continue
        dx = np.diff(hx)[valid_dt]
        dz = np.diff(hz)[valid_dt]
        dt = dt[valid_dt]
        x0 = hx[:-1][valid_dt]
        z0 = hz[:-1][valid_dt]
        r0 = np.maximum(np.hypot(x0, z0), 1e-6)
        projected_speed = (dx / dt) * x0 / r0 + (dz / dt) * z0 / r0
        displacement = np.hypot(dx, dz)
        path_length = float(displacement.sum())
        net_x = float(hx[-1] - hx[0])
        net_z = float(hz[-1] - hz[0])
        end_radius = max(float(np.hypot(hx[-1], hz[-1])), 1e-6)
        alignment = float((net_x * hx[-1] + net_z * hz[-1]) / (end_radius * path_length)) if path_length > 1e-6 else 0.0
        r_hist = np.hypot(hx, hz)
        bin_id = np.floor((hts - hts[-1]) / 0.25).astype(int)
        unique_bins = np.unique(bin_id)
        bin_means = np.array([float(r_hist[bin_id == b].mean()) for b in unique_bins])
        radial_steps = np.diff(bin_means)
        inward_steps = radial_steps < -0.10
        max_inward_run = 0
        current_run = 0
        for is_inward in inward_steps:
            current_run = current_run + 1 if is_inward else 0
            max_inward_run = max(max_inward_run, current_run)
        recent = r_hist[hts >= hts[-1] - 1.0]
        net_change_1s = float(recent[-1] - recent[0]) if len(recent) >= 2 else float(r_hist[-1] - r_hist[0])
        outward_fraction = float(np.mean(projected_speed > 0.05))
        inward_fraction = float(np.mean(projected_speed < -0.10))
        correction = max(inward_fraction, float(np.clip(-net_change_1s / 0.50, 0.0, 1.0)), float(max_inward_run >= 2))
        radial_fraction = float(np.hypot(x_all[i], z_all[i]) / radius_all[i])
        proximity = float(np.clip((radial_fraction - 0.85) / (1.0 - 0.85), 0.0, 1.0))
        speed = float(np.clip(np.nanmedian(projected_speed) / 0.5, 0.0, 1.0))
        direction = float(np.clip(alignment, 0.0, 1.0))
        risk[i] = float(np.clip(0.35 * proximity + 0.30 * outward_fraction + 0.20 * direction + 0.15 * speed - 0.30 * correction, 0.0, 1.0))
    return np.isfinite(risk) & (risk >= 0.80)


def evaluate_rule(sessions: list[dict[str, Any]], rule_name: str, mask_fn) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fall_total = sum(int(s["is_fall"]) for s in sessions)
    nonfall_total = len(sessions) - fall_total
    detected = 0
    false_alarm = 0
    details: list[dict[str, Any]] = []
    leads: list[float] = []
    for s in sessions:
        result = mask_fn(s)
        mask = np.asarray(result[0] if isinstance(result, tuple) else result, dtype=bool) & s["pre"]
        tte = result[1] if isinstance(result, tuple) else np.full(len(mask), np.nan)
        ts = s["ts"]
        indices = np.flatnonzero(mask)
        start_mask = mask.copy()
        if len(start_mask) > 1:
            start_mask[1:] &= ~mask[:-1]
        starts = np.flatnonzero(start_mask)
        first_ts = float(ts[starts[0]]) if len(starts) else math.nan
        # Measure from the onset of the last episode, not its final frame.
        last_ts = float(ts[starts[-1]]) if len(starts) else math.nan
        event_ts = s["event_ts"]
        hit = bool(len(indices) and (not s["is_fall"] or first_ts < event_ts))
        if s["is_fall"]:
            detected += int(hit)
        else:
            false_alarm += int(hit)
        last_lead = float(event_ts - last_ts) if s["is_fall"] and hit and np.isfinite(event_ts) else math.nan
        first_lead = float(event_ts - first_ts) if s["is_fall"] and hit and np.isfinite(event_ts) else math.nan
        if np.isfinite(last_lead):
            leads.append(last_lead)
        details.append(
            {
                "rule": rule_name,
                "session_id": s["session_id"],
                "short_id": s["short_id"],
                "manual_difficulty": s["manual_difficulty"],
                "telemetry_difficulty": s["telemetry_difficulty"],
                "is_fall": s["is_fall"],
                "alarm": hit,
                "alarm_count": int(len(starts)),
                "first_alarm_timestamp": first_ts,
                "last_alarm_timestamp": last_ts,
                "fall_event_timestamp": event_ts,
                "first_lead_time_s": first_lead,
                "last_lead_time_s": last_lead,
                "min_predicted_tte_s": float(np.min(tte[mask & np.isfinite(tte)])) if np.any(mask & np.isfinite(tte)) else math.nan,
            }
        )
    recall = detected / fall_total if fall_total else math.nan
    fpr = false_alarm / nonfall_total if nonfall_total else math.nan
    precision = detected / (detected + false_alarm) if detected + false_alarm else math.nan
    f1 = 2 * precision * recall / (precision + recall) if np.isfinite(precision) and np.isfinite(recall) and precision + recall else math.nan
    metrics = {
        "rule": rule_name,
        "fall_sessions": fall_total,
        "nonfall_sessions": nonfall_total,
        "detected_fall_sessions": detected,
        "missed_fall_sessions": fall_total - detected,
        "false_alarm_sessions": false_alarm,
        "correct_nonfall_sessions": nonfall_total - false_alarm,
        "session_accuracy": (detected + nonfall_total - false_alarm) / len(sessions) if sessions else math.nan,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "session_false_alarm_rate": fpr,
        "median_last_lead_time_s": float(np.median(leads)) if leads else math.nan,
        "p25_last_lead_time_s": float(np.percentile(leads, 25)) if leads else math.nan,
        "mean_last_lead_time_s": float(np.mean(leads)) if leads else math.nan,
        "n_fall_leads": len(leads),
        "mean_alarms_per_session": float(np.mean([x["alarm_count"] for x in details])) if details else math.nan,
    }
    return metrics, details


def load_manifest(path: Path, exclude_conflicts: bool) -> tuple[pd.DataFrame, list[str]]:
    manifest = pd.read_csv(path, low_memory=False)
    conflicts: list[str] = []
    if "csv_manual_conflict" in manifest.columns:
        conflicts = manifest.loc[manifest["csv_manual_conflict"].map(as_bool), "session_id"].astype(str).tolist()
    if "manual_record_conflict" in manifest.columns:
        conflicts += manifest.loc[manifest["manual_record_conflict"].map(as_bool), "session_id"].astype(str).tolist()
    if "difficulty_mismatch" in manifest.columns:
        conflicts += manifest.loc[manifest["difficulty_mismatch"].map(as_bool), "session_id"].astype(str).tolist()
    if "manual_csv_status" in manifest.columns:
        conflicts += manifest.loc[manifest["manual_csv_status"].astype(str).str.lower().ne("consistent"), "session_id"].astype(str).tolist()
    conflicts = sorted(set(conflicts))
    if exclude_conflicts and conflicts:
        manifest = manifest.loc[~manifest.session_id.astype(str).isin(conflicts)].copy()
    return manifest, conflicts


def run_grid(sessions: list[dict[str, Any]], out: Path) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    current, current_details = evaluate_rule(sessions, "current_unity_edge_warning", lambda s: s["observed"])
    current.update({"horizon_s": np.nan, "persistence_s": np.nan, "min_outward_velocity": np.nan, "inward_cancel_window_s": np.nan, "selection_rank": 9999})
    rows.append(current)
    detail_rows.extend(current_details)
    for horizon in (0.3, 0.5, 0.7, 1.0):
        for persistence in (0.2, 0.3, 0.5):
            for minimum in (0.05, 0.10, 0.20, 0.50, 0.80, 1.00):
                for cancel_window in (0.0, 0.3, 0.5, 1.0):
                    name = f"tte_h{horizon:g}_p{persistence:g}_v{minimum:g}_cancel{cancel_window:g}"
                    metrics, details = evaluate_rule(
                        sessions,
                        name,
                        lambda s, h=horizon, p=persistence, v=minimum, c=cancel_window: time_to_edge_mask(s, h, p, v, c),
                    )
                    metrics.update(
                        {
                            "horizon_s": horizon,
                            "persistence_s": persistence,
                            "min_outward_velocity": minimum,
                            "inward_cancel_window_s": cancel_window,
                            "selection_rank": 9999,
                        }
                    )
                    rows.append(metrics)
                    detail_rows.extend(details)
    grid = pd.DataFrame(rows)
    current_fpr = float(current["session_false_alarm_rate"])
    candidates = grid[grid.rule.str.startswith("tte_")].copy()
    preferred = candidates.loc[(candidates.session_false_alarm_rate <= current_fpr + 1e-12) & (candidates.recall >= 0.5)].copy()
    if preferred.empty:
        preferred = candidates.copy()
    preferred = preferred.sort_values(
        ["f1", "recall", "precision", "median_last_lead_time_s", "session_false_alarm_rate"],
        ascending=[False, False, False, False, True],
        na_position="last",
    )
    order = {name: i for i, name in enumerate(preferred.rule.astype(str).tolist())}
    grid["selection_rank"] = grid.rule.map(order).fillna(9999).astype(int)
    recommended_name = str(preferred.iloc[0].rule)
    details = pd.DataFrame(detail_rows)
    return grid, details, recommended_name


def write_figures(grid: pd.DataFrame, details: pd.DataFrame, out: Path, title_prefix: str) -> None:
    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11, "axes.labelsize": 10})
    current = grid.loc[grid.rule.eq("current_unity_edge_warning")].iloc[0]
    recommended = grid.sort_values("selection_rank").iloc[0]
    candidates = grid.loc[grid.rule.str.startswith("tte_")].copy()
    fig, ax = plt.subplots(figsize=(7.6, 5.3), constrained_layout=True)
    scatter = ax.scatter(candidates.session_false_alarm_rate * 100, candidates.recall * 100, c=candidates.median_last_lead_time_s.fillna(0), cmap="viridis", s=28, alpha=0.78, edgecolors="white", linewidth=0.25)
    ax.scatter([current.session_false_alarm_rate * 100], [current.recall * 100], marker="*", s=180, color="#C73E36", edgecolor="black", label="Current Unity warning")
    ax.scatter([recommended.session_false_alarm_rate * 100], [recommended.recall * 100], marker="D", s=60, color="#1764A0", edgecolor="black", label="Selected time-to-edge")
    ax.set_xlabel("Non-fall session false-alarm rate (%)")
    ax.set_ylabel("Fall-session recall (%)")
    ax.set_xlim(left=-1); ax.set_ylim(-1, 105)
    ax.grid(color="#D8D8D8", linewidth=0.5); ax.spines[["top", "right"]].set_visible(False)
    cb = fig.colorbar(scatter, ax=ax, pad=0.02); cb.set_label("Median last-warning lead (s)")
    ax.legend(frameon=False, loc="lower right")
    ax.set_title(f"{title_prefix}: time-to-edge operating points", color="#23395B", fontweight="bold")
    fig.savefig(out / "figure_tradeoff.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(out / "figure_tradeoff.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    rows = [current, recommended]
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.2), constrained_layout=True)
    x = np.arange(2)
    axes[0].bar(x - 0.17, [r.recall * 100 for r in rows], 0.34, color="#2A7F9E", label="Recall")
    axes[0].bar(x + 0.17, [r.session_false_alarm_rate * 100 for r in rows], 0.34, color="#D99132", label="False alarm")
    axes[0].set_xticks(x, ["Current\nUnity", "Time-to-edge"]); axes[0].set_ylabel("Sessions (%)"); axes[0].set_ylim(0, 105)
    axes[0].set_title("Session-level performance"); axes[0].legend(frameon=False, fontsize=8); axes[0].grid(axis="y", color="#D8D8D8", linewidth=0.5)
    axes[1].bar(x - 0.2, [r.median_last_lead_time_s if np.isfinite(r.median_last_lead_time_s) else 0 for r in rows], 0.4, color="#1764A0", label="Median last lead")
    axes[1].bar(x + 0.2, [r.p25_last_lead_time_s if np.isfinite(r.p25_last_lead_time_s) else 0 for r in rows], 0.4, color="#6A3D9A", label="P25 last lead")
    axes[1].set_xticks(x, ["Current\nUnity", "Time-to-edge"]); axes[1].set_ylabel("Seconds before fall_event"); axes[1].set_title("Last warning lead time")
    axes[1].legend(frameon=False, fontsize=8); axes[1].grid(axis="y", color="#D8D8D8", linewidth=0.5)
    for axis in axes:
        axis.spines[["top", "right"]].set_visible(False); axis.set_axisbelow(True)
    fig.suptitle(f"{title_prefix}: current vs time-to-edge", color="#23395B", fontweight="bold")
    fig.savefig(out / "figure_current_vs_tte.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(out / "figure_current_vs_tte.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_readme(out: Path, dataset: str, sessions: list[dict[str, Any]], conflicts: list[str], excluded_conflicts: bool, grid: pd.DataFrame, recommended_name: str) -> None:
    current = grid.loc[grid.rule.eq("current_unity_edge_warning")].iloc[0]
    recommended = grid.loc[grid.rule.eq(recommended_name)].iloc[0]
    feasible = grid.loc[
        grid.rule.str.startswith("tte_")
        & grid.recall.ge(0.50)
        & grid.session_false_alarm_rate.le(float(current.session_false_alarm_rate) + 1e-12)
    ]
    lines = [
        f"# {dataset} offline time-to-edge replay",
        "",
        f"Sessions evaluated: {len(sessions)} ({int(sum(s['is_fall'] for s in sessions))} fall-event sessions, {int(sum(not s['is_fall'] for s in sessions))} non-fall sessions).",
        f"Manifest conflict sessions: {', '.join(conflicts) if conflicts else 'none'}. Conflict exclusion for this run: {excluded_conflicts}.",
        "",
        "TEST929 is a frozen validation set. No parameter was selected from its results. The development set is used to select the candidate, and TEST929 is evaluated only after the candidate is fixed.",
        "",
        "## Time-to-edge rule",
        "",
        "`time_to_edge = (directional_edge_distance - ball_radius) / target_edge_radial_velocity`.",
        "",
        "A prediction requires directional_edge_valid, outward velocity at or above the tested threshold, a non-negative time-to-edge within the tested horizon, and mostly outward samples during the tested persistence window. A clear inward velocity within the cancellation window suppresses the prediction. All alarms after the first Unity fall_event are excluded from pre-event scoring.",
        "",
        "## Selected candidate",
        "",
        f"`{recommended.rule}`: horizon={recommended.horizon_s:g}s, persistence={recommended.persistence_s:g}s, minimum outward velocity={recommended.min_outward_velocity:g}, inward-cancel window={recommended.inward_cancel_window_s:g}s.",
        f"Session recall={recommended.recall:.1%}, precision={recommended.precision:.1%}, F1={recommended.f1:.1%}, non-fall session false-alarm rate={recommended.session_false_alarm_rate:.1%}, median last-warning lead={recommended.median_last_lead_time_s:.3f}s.",
        "The selected cancel window is 0 seconds, so it uses no additional inward-history grace period. Inward samples do not trigger because the rule requires outward velocity. Nonzero inward-cancel windows were also tested in the development grid.",
        "",
        "Selection rule: prefer candidates with at least 50% fall-session recall and no higher session false-alarm rate than the observed Unity warning, then rank by F1. If no candidate meets both constraints, rank the full grid by F1 and flag that no candidate met the target.",
        ("At least one candidate met both development constraints." if len(feasible) else "No candidate met both development constraints; this selected row is a fallback, not a demonstrated improvement over the current warning."),
        "",
        "## Current Unity warning",
        "",
        f"Session recall={current.recall:.1%}, precision={current.precision:.1%}, F1={current.f1:.1%}, non-fall session false-alarm rate={current.session_false_alarm_rate:.1%}, median last-warning lead={current.median_last_lead_time_s:.3f}s.",
        "",
        "The reported historical '42%' is not accuracy. It is the prior directional-risk rule's session-level exit detection rate, 8/19 = 42.1%, on a different exploratory dataset and protocol. It is retained as historical context, not mixed into these validation metrics.",
        "",
        "Raw CSV files and existing cleaning outputs were not modified.",
    ]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_dataset(root: Path, manifest_path: Path, out: Path, dataset: str, exclude_conflicts: bool) -> dict[str, Any]:
    manifest, conflicts = load_manifest(manifest_path, exclude_conflicts)
    sessions = [loaded for _, row in manifest.iterrows() if (loaded := load_session(root, row)) is not None]
    if not sessions:
        raise RuntimeError(f"No usable sessions in {dataset}")
    out.mkdir(parents=True, exist_ok=True)
    grid, details, recommended_name = run_grid(sessions, out)
    grid.to_csv(out / "parameter_grid.csv", index=False, encoding="utf-8-sig")
    details.to_csv(out / "session_metrics.csv", index=False, encoding="utf-8-sig")
    grid.sort_values("selection_rank").head(20).to_csv(out / "top_rules.csv", index=False, encoding="utf-8-sig")
    current = grid.loc[grid.rule.eq("current_unity_edge_warning")].iloc[0]
    recommended = grid.loc[grid.rule.eq(recommended_name)].iloc[0]
    pd.DataFrame([current, recommended]).to_csv(out / "baseline_comparison.csv", index=False, encoding="utf-8-sig")
    (out / "recommended_rule.json").write_text(json.dumps(recommended.to_dict(), indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8")
    summary = {
        "dataset": dataset,
        "manifest": str(manifest_path),
        "sessions": len(sessions),
        "fall_sessions": int(sum(s["is_fall"] for s in sessions)),
        "nonfall_sessions": int(sum(not s["is_fall"] for s in sessions)),
        "manifest_conflict_sessions": conflicts,
        "excluded_conflicts": bool(exclude_conflicts),
        "current_rule": current.to_dict(),
        "recommended_rule": recommended.to_dict(),
        "grid_size": int(len(grid) - 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8")
    write_readme(out, dataset, sessions, conflicts, exclude_conflicts, grid, recommended_name)
    write_figures(grid, details, out, dataset)
    return summary


def run_locked_validation(
    root: Path,
    manifest_path: Path,
    out: Path,
    selected_params: dict[str, Any],
    selected_name: str,
) -> dict[str, Any]:
    """Evaluate only fixed rules on TEST929; never search its parameter grid."""

    manifest, conflicts = load_manifest(manifest_path, exclude_conflicts=False)
    sessions = [loaded for _, row in manifest.iterrows() if (loaded := load_session(root, row)) is not None]
    if not sessions:
        raise RuntimeError("No usable sessions in locked TEST929 validation")
    out.mkdir(parents=True, exist_ok=True)

    current, current_details = evaluate_rule(sessions, "current_unity_edge_warning", lambda s: s["observed"])
    old, old_details = evaluate_rule(sessions, "legacy_directional_risk_fixed_v2", legacy_directional_mask)
    tte, tte_details = evaluate_rule(
        sessions,
        "time_to_edge_selected_from_development",
        lambda s: time_to_edge_mask(
            s,
            float(selected_params["horizon_s"]),
            float(selected_params["persistence_s"]),
            float(selected_params["min_outward_velocity"]),
            float(selected_params["inward_cancel_window_s"]),
        ),
    )
    tte.update({key: selected_params[key] for key in ("horizon_s", "persistence_s", "min_outward_velocity", "inward_cancel_window_s")})
    current["parameters"] = "Unity recorded edge_warning_state"
    old["parameters"] = "fixed v2 weights; threshold 0.80; lookback 1.0 s; hold 1 sample; logged platform_radius"
    tte["parameters"] = selected_name
    comparison = pd.DataFrame([old, current, tte])
    comparison.to_csv(out / "baseline_comparison.csv", index=False, encoding="utf-8-sig")
    details = pd.DataFrame(old_details + current_details + tte_details)
    details.to_csv(out / "session_metrics.csv", index=False, encoding="utf-8-sig")

    plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 9.5, "axes.titlesize": 11, "axes.labelsize": 10})
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.2), constrained_layout=True)
    labels = ["Old directional\nv2", "Current Unity\nyellow", "Time-to-edge\nfixed from dev"]
    values = [old, current, tte]
    x = np.arange(3)
    axes[0].bar(x, [r["precision"] * 100 for r in values], color="#2A7F9E")
    axes[0].set_ylabel("Percent of sessions (%)"); axes[0].set_ylim(0, 105); axes[0].set_title("Session precision")
    axes[1].bar(x - 0.18, [r["recall"] * 100 for r in values], 0.36, color="#2A7F9E", label="Fall-session recall")
    axes[1].bar(x + 0.18, [r["session_false_alarm_rate"] * 100 for r in values], 0.36, color="#D99132", label="Non-fall session false alarm")
    axes[1].set_ylim(0, 105); axes[1].set_title("Detection vs false alarm"); axes[1].legend(frameon=False, fontsize=8)
    axes[2].bar(x - 0.18, [r["median_last_lead_time_s"] if np.isfinite(r["median_last_lead_time_s"]) else 0 for r in values], 0.36, color="#1764A0", label="Median last warning")
    axes[2].bar(x + 0.18, [r["p25_last_lead_time_s"] if np.isfinite(r["p25_last_lead_time_s"]) else 0 for r in values], 0.36, color="#6A3D9A", label="P25 last warning")
    axes[2].set_ylabel("Seconds before fall_event"); axes[2].set_title("Lead time"); axes[2].legend(frameon=False, fontsize=8)
    for axis in axes:
        axis.set_xticks(x, labels); axis.grid(axis="y", color="#D8D8D8", linewidth=0.5); axis.spines[["top", "right"]].set_visible(False); axis.set_axisbelow(True)
    fig.suptitle("Locked TEST929 comparison on the same 30 sessions", color="#23395B", fontweight="bold")
    fig.savefig(out / "figure_locked_validation.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(out / "figure_locked_validation.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    summary = {
        "dataset": "TEST929",
        "status": "frozen_validation",
        "selection_source": "TEST9282 development",
        "selected_tte_rule": selected_name,
        "sessions": len(sessions),
        "fall_sessions": int(sum(s["is_fall"] for s in sessions)),
        "nonfall_sessions": int(sum(not s["is_fall"] for s in sessions)),
        "difficulty_conflict_sessions_retained_for_global_validation": conflicts,
        "raw_files_modified": False,
        "metrics": {"legacy_directional_v2": old, "current_unity_warning": current, "time_to_edge": tte},
        "test_set_parameters_searched": False,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8")
    lines = [
        "# Frozen TEST929 comparison",
        "",
        "TEST929 was used only for fixed-rule evaluation. No parameter grid was searched on this validation set. The time-to-edge settings were selected on TEST9282 and applied unchanged. All three methods are evaluated on the same 30 sessions, with one Unity fall_event session as the positive unit.",
        "",
        f"Selected time-to-edge rule from development: `{selected_name}`.",
        "",
        "| Rule | Session precision | Session recall | Session F1 | Non-fall session false-alarm rate | Median last-warning lead | P25 last-warning lead | Session accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, metric in (("Old directional-risk v2, frozen", old), ("Current Unity yellow warning", current), ("Time-to-edge, fixed from development", tte)):
        lines.append(
            f"| {label} | {metric['precision']:.1%} | {metric['recall']:.1%} | {metric['f1']:.1%} | {metric['session_false_alarm_rate']:.1%} | {metric['median_last_lead_time_s']:.3f}s | {metric['p25_last_lead_time_s']:.3f}s | {metric['session_accuracy']:.1%} |"
        )
    lines.extend(
        [
            "",
            "The old historical 42.1% is 8/19 session-level directional-exit detection on an earlier tuned dataset, not accuracy. It is not substituted for the frozen replay result above. The old-rule replay preserves its published 0.80 risk threshold and scoring weights; it uses TEST929's logged platform radius instead of deriving geometry from TEST929 event labels.",
            "",
            "Lead time is measured from the onset of each rule's last pre-event alarm episode to the first Unity fall_event timestamp. This is a consistent lead-time definition for this table. Unity fall_event represents a platform edge-exit event, not a measured human fall. The two D1/D3 difficulty metadata conflicts remain included in the global TEST929 session count and are flagged in the source manifest.",
            "",
            "No Unity code, raw telemetry, or existing cleaning outputs were modified. The TEST929 parameter grid was not evaluated or saved.",
        ]
    )
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-root", type=Path, required=True)
    parser.add_argument("--dev-manifest", type=Path, required=True)
    parser.add_argument("--validation-root", type=Path, required=True)
    parser.add_argument("--validation-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # Tune only on TEST9282. Read TEST929 only after candidate selection, and
    # evaluate the single frozen candidate plus two fixed comparators.
    dev_summary = run_dataset(args.dev_root, args.dev_manifest, args.out / "development_TEST9282", "TEST9282_development", True)
    selected_name = str(dev_summary["recommended_rule"]["rule"])
    validation_summary = run_locked_validation(
        args.validation_root,
        args.validation_manifest,
        args.out / "validation_TEST929",
        dev_summary["recommended_rule"],
        selected_name,
    )
    final = {"development": dev_summary, "locked_validation": validation_summary}
    (args.out / "summary.json").write_text(json.dumps(final, indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8")
    (args.out / "README.md").write_text(
        "# Offline time-to-edge development and validation\n\n"
        "The TTE parameter grid and candidate selection use TEST9282 development data only. TEST929 is frozen and used only for a one-time evaluation of the fixed development candidate, the current Unity warning, and a fixed replay of the historical directional-risk rule. No TEST929 parameter grid is generated.\n\n"
        f"Selected TTE rule: `{selected_name}`. See `validation_TEST929/README.md` for same-session comparison results.\n\n"
        "Historical note: the old reported 42.1% is session-level exit detection (8/19), not accuracy.\n",
        encoding="utf-8",
    )
    print(json.dumps(final, indent=2, ensure_ascii=False, allow_nan=True, default=float))


if __name__ == "__main__":
    main()
