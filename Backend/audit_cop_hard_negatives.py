"""Audit COP telemetry and identify hard-negative sessions offline.

No raw telemetry or manifest is modified.  The output is an audit table for
choosing the next collection/training batch: non-fall sessions that reached
the warning band, produced an outward movement, or emitted the visible yellow
warning are useful hard negatives for GRU training.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "cop_hard_negative_audit"


def finite_rate(values: np.ndarray) -> float:
    return float(np.isfinite(values).mean()) if len(values) else 0.0


def load_raw_unity(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    if "source" in raw.columns:
        source = raw["source"].astype(str).str.strip().str.lower()
        unity = raw.loc[source.eq("unity")].copy()
        if not unity.empty:
            return unity
    return raw


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifests = [
        ("TEST9282", Path(gru.DEFAULT_TRAIN_MANIFESTS[0]), True),
        ("TEST930", Path(gru.DEFAULT_TRAIN_MANIFESTS[1]), True),
        ("TEST931", Path(gru.DEFAULT_TRAIN_MANIFESTS[2]), True),
        ("TEST929", Path(gru.DEFAULT_HELDOUT_MANIFESTS[0]), False),
    ]
    rows: list[dict[str, Any]] = []
    field_counts: dict[str, dict[str, int]] = {}
    for dataset, manifest, training in manifests:
        sessions, _ = gru.load_manifest_sessions(manifest, None, training, False)
        for session in sessions:
            unity = load_raw_unity(session["path"])
            row: dict[str, Any] = {
                "dataset": dataset,
                "session_id": str(session["session_id"]),
                "is_fall_session": bool(np.isfinite(session["first_event_ts"])),
                "n_rows": int(len(unity)),
            }
            for field in ("cop_x", "cop_z", "cop_velocity_x", "cop_velocity_z", "cop_speed"):
                values = pd.to_numeric(unity[field], errors="coerce").to_numpy(dtype=float) if field in unity.columns else np.full(len(unity), np.nan)
                row[f"{field}_finite_rate"] = finite_rate(values)
                field_counts.setdefault(dataset, {}).setdefault(field, 0)
                field_counts[dataset][field] += int(np.isfinite(values).sum())

            warning = np.asarray(session["observed_warning"], dtype=bool)
            distance = np.asarray(session["distance"], dtype=float)
            velocity = np.asarray(session["velocity"], dtype=float)
            radius = np.asarray(session["radius"], dtype=float)
            # Prefer the recorded threshold; if it is missing, use the
            # controller's measured edge-warning band (2*ball_radius).
            threshold = np.full(len(distance), np.nan, dtype=float)
            if "edge_warning_distance_threshold" in unity.columns:
                threshold = pd.to_numeric(unity["edge_warning_distance_threshold"], errors="coerce").to_numpy(dtype=float)
            fallback = np.isfinite(radius) & (radius > 0)
            threshold = np.where(np.isfinite(threshold), threshold, 2.0 * radius)
            warning_band = np.isfinite(distance) & np.isfinite(threshold) & (distance <= threshold)
            outward = np.isfinite(velocity) & (velocity > 0.05)
            outward_fraction = float(outward.mean()) if len(outward) else 0.0
            row.update(
                {
                    "visible_warning_rows": int(warning.sum()),
                    "warning_band_rows": int(warning_band.sum()),
                    "outward_rows": int(outward.sum()),
                    "outward_fraction": outward_fraction,
                    "min_edge_distance": float(np.nanmin(distance)) if np.isfinite(distance).any() else np.nan,
                    "median_edge_distance": float(np.nanmedian(distance)) if np.isfinite(distance).any() else np.nan,
                    "max_outward_velocity": float(np.nanmax(velocity)) if np.isfinite(velocity).any() else np.nan,
                }
            )
            row["hard_negative_candidate"] = bool(
                not row["is_fall_session"]
                and (row["visible_warning_rows"] > 0 or row["warning_band_rows"] > 0)
            )
            row["hard_negative_reason"] = ";".join(
                reason
                for reason, condition in (
                    ("visible_warning", row["visible_warning_rows"] > 0),
                    ("warning_band", row["warning_band_rows"] > 0),
                    ("outward_motion", row["outward_fraction"] >= 0.75),
                )
                if condition and not row["is_fall_session"]
            )
            rows.append(row)

    table = pd.DataFrame(rows).sort_values(["dataset", "is_fall_session", "session_id"])
    table.to_csv(OUT / "session_cop_hard_negative_audit.csv", index=False, encoding="utf-8-sig")
    hard = table.loc[table["hard_negative_candidate"]].copy()
    hard.to_csv(OUT / "hard_negative_candidates.csv", index=False, encoding="utf-8-sig")
    availability = []
    for dataset, group in table.groupby("dataset", sort=True):
        availability.append(
            {
                "dataset": dataset,
                "sessions": int(len(group)),
                "fall_sessions": int(group["is_fall_session"].sum()),
                "nonfall_sessions": int((~group["is_fall_session"]).sum()),
                "hard_negative_sessions": int(group["hard_negative_candidate"].sum()),
                **{
                    f"{field}_sessions_with_any_finite": int((group[f"{field}_finite_rate"] > 0).sum())
                    for field in ("cop_x", "cop_z", "cop_velocity_x", "cop_velocity_z", "cop_speed")
                },
                **{
                    f"{field}_mean_finite_rate": float(group[f"{field}_finite_rate"].mean())
                    for field in ("cop_x", "cop_z", "cop_velocity_x", "cop_velocity_z", "cop_speed")
                },
            }
        )
    availability_frame = pd.DataFrame(availability)
    availability_frame.to_csv(OUT / "cop_availability_by_dataset.csv", index=False, encoding="utf-8-sig")
    summary = {
        "raw_files_modified": False,
        "manifests_modified": False,
        "datasets": availability,
        "total_sessions": int(len(table)),
        "total_hard_negative_candidates": int(len(hard)),
        "hard_negative_definition": "non-fall session with visible EDGE WARNING or at least one recorded warning-band row; outward-motion statistics are retained but not used alone because raw radial velocity is noisy",
        "cop_fields_audited": ["cop_x", "cop_z", "cop_velocity_x", "cop_velocity_z", "cop_speed"],
    }
    (OUT / "summary.json").write_text(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
