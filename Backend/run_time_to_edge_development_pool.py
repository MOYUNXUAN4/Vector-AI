"""Tune the offline time-to-edge rule on the combined development pool.

This script intentionally reads TEST9282, TEST930, and the corrected clean
scope of TEST931 only.  It does not read TEST929 and does not modify raw CSVs
or any existing analysis outputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import run_time_to_edge_validation as tte


BASE = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\telemetry_logs")
OUT = BASE / "analysis_tte_development_20261001"


def load_development_sessions() -> tuple[list[dict], pd.DataFrame, dict[str, dict]]:
    specs = [
        (
            "TEST9282",
            BASE / "TEST9282",
            BASE / "TEST9282" / "analysis_reduced_sensitivity_20260928_primary_review" / "session_manifest.csv",
            "conflict_filtered",
        ),
        (
            "TEST930",
            BASE / "TEST930",
            BASE / "TEST930" / "analysis_20260929_review" / "session_manifest.csv",
            "conflict_filtered",
        ),
        (
            "TEST931",
            BASE / "TEST931",
            BASE / "TEST931" / "analysis_20261001_luna" / "session_manifest.csv",
            "include_clean_true",
        ),
    ]

    loaded_sessions: list[dict] = []
    pool_rows: list[dict] = []
    dataset_notes: dict[str, dict] = {}

    for dataset, root, manifest_path, mode in specs:
        if mode == "include_clean_true":
            raw_manifest = pd.read_csv(manifest_path, low_memory=False)
            include = raw_manifest["include_clean"].map(tte.as_bool)
            manifest = raw_manifest.loc[include].copy()
            excluded = raw_manifest.loc[~include, "session_id"].astype(str).tolist()
            conflicts = raw_manifest.loc[~include, "session_id"].astype(str).tolist()
        else:
            manifest, conflicts = tte.load_manifest(manifest_path, exclude_conflicts=True)
            excluded = sorted(set(conflicts))

        dataset_loaded = 0
        for _, row in manifest.iterrows():
            session = tte.load_session(root, row)
            if session is None:
                continue
            session["source_dataset"] = dataset
            loaded_sessions.append(session)
            dataset_loaded += 1
            pool_rows.append(
                {
                    "source_dataset": dataset,
                    "session_id": session["session_id"],
                    "is_fall": bool(session["is_fall"]),
                    "manual_difficulty": session["manual_difficulty"],
                    "telemetry_difficulty": session["telemetry_difficulty"],
                    "raw_csv": str(root / session["session_id"] / "raw.csv"),
                    "included_reason": "clean_scope" if mode == "include_clean_true" else "manifest_consistent",
                }
            )
        dataset_notes[dataset] = {
            "manifest": str(manifest_path),
            "manifest_rows_selected": int(len(manifest)),
            "sessions_loaded": int(dataset_loaded),
            "fall_sessions": int(sum(s["is_fall"] for s in loaded_sessions if s["source_dataset"] == dataset)),
            "nonfall_sessions": int(sum(not s["is_fall"] for s in loaded_sessions if s["source_dataset"] == dataset)),
            "excluded_session_ids": excluded,
            "raw_files_modified": False,
        }

    pool_manifest = pd.DataFrame(pool_rows).sort_values(["source_dataset", "session_id"])
    duplicate_ids = sorted(pool_manifest.loc[pool_manifest.duplicated("session_id", keep=False), "session_id"].unique())
    if duplicate_ids:
        raise RuntimeError(f"Duplicate session IDs across development datasets: {duplicate_ids}")
    return loaded_sessions, pool_manifest, dataset_notes


def write_horizon_cancel_summary(grid: pd.DataFrame, out: Path) -> None:
    candidates = grid.loc[grid.rule.astype(str).str.startswith("tte_")].copy()
    rows: list[dict] = []
    for horizon in sorted(candidates.horizon_s.dropna().unique()):
        for cancel in sorted(candidates.inward_cancel_window_s.dropna().unique()):
            subset = candidates.loc[
                np.isclose(candidates.horizon_s, horizon)
                & np.isclose(candidates.inward_cancel_window_s, cancel)
            ].copy()
            if subset.empty:
                continue
            subset = subset.sort_values(
                ["f1", "recall", "precision", "median_last_lead_time_s", "session_false_alarm_rate"],
                ascending=[False, False, False, False, True],
                na_position="last",
            )
            best = subset.iloc[0]
            rows.append(
                {
                    "horizon_s": float(horizon),
                    "inward_cancel_window_s": float(cancel),
                    "best_rule": str(best.rule),
                    "persistence_s": float(best.persistence_s),
                    "min_outward_velocity": float(best.min_outward_velocity),
                    "precision": float(best.precision),
                    "recall": float(best.recall),
                    "f1": float(best.f1),
                    "session_false_alarm_rate": float(best.session_false_alarm_rate),
                    "median_last_lead_time_s": float(best.median_last_lead_time_s),
                    "p25_last_lead_time_s": float(best.p25_last_lead_time_s),
                    "mean_alarms_per_session": float(best.mean_alarms_per_session),
                }
            )
    pd.DataFrame(rows).sort_values(["horizon_s", "inward_cancel_window_s"]).to_csv(
        out / "horizon_cancel_summary.csv", index=False, encoding="utf-8-sig"
    )


def main() -> None:
    sessions, pool_manifest, dataset_notes = load_development_sessions()
    if not sessions:
        raise RuntimeError("No usable development sessions loaded")
    OUT.mkdir(parents=True, exist_ok=True)
    pool_manifest.to_csv(OUT / "pool_manifest.csv", index=False, encoding="utf-8-sig")

    grid, details, recommended_name = tte.run_grid(sessions, OUT)
    grid.to_csv(OUT / "parameter_grid.csv", index=False, encoding="utf-8-sig")
    details.to_csv(OUT / "session_metrics.csv", index=False, encoding="utf-8-sig")
    grid.sort_values("selection_rank").head(30).to_csv(OUT / "top_rules.csv", index=False, encoding="utf-8-sig")
    write_horizon_cancel_summary(grid, OUT)

    current = grid.loc[grid.rule.eq("current_unity_edge_warning")].iloc[0]
    recommended = grid.loc[grid.rule.eq(recommended_name)].iloc[0]
    pd.DataFrame([current, recommended]).to_csv(OUT / "baseline_comparison.csv", index=False, encoding="utf-8-sig")
    (OUT / "recommended_rule.json").write_text(
        json.dumps(recommended.to_dict(), indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8"
    )
    tte.write_figures(grid, details, OUT, "TEST9282 + TEST930 + TEST931 development")

    summary = {
        "dataset": "TEST9282_TEST930_TEST931_development",
        "test_set_used": False,
        "sessions": len(sessions),
        "fall_sessions": int(sum(s["is_fall"] for s in sessions)),
        "nonfall_sessions": int(sum(not s["is_fall"] for s in sessions)),
        "grid_size": int(len(grid) - 1),
        "current_rule": current.to_dict(),
        "recommended_rule": recommended.to_dict(),
        "dataset_notes": dataset_notes,
        "raw_files_modified": False,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=True, default=float), encoding="utf-8"
    )

    feasible = grid.loc[
        grid.rule.astype(str).str.startswith("tte_")
        & grid.recall.ge(0.50)
        & grid.session_false_alarm_rate.le(float(current.session_false_alarm_rate) + 1e-12)
    ]
    readme = [
        "# Combined development-pool time-to-edge tuning",
        "",
        "Only TEST9282, TEST930, and the corrected included-clean scope of TEST931 were used. TEST929 was not read or used for parameter selection.",
        "",
        f"Sessions: {len(sessions)} ({int(sum(s['is_fall'] for s in sessions))} fall-event, {int(sum(not s['is_fall'] for s in sessions))} non-fall).",
        f"Grid: {len(grid) - 1} time-to-edge candidates (horizon, persistence, outward-velocity threshold, inward-cancel window).",
        "",
        f"Current Unity rule: precision={current.precision:.1%}, recall={current.recall:.1%}, F1={current.f1:.1%}, non-fall false-alarm rate={current.session_false_alarm_rate:.1%}, median last lead={current.median_last_lead_time_s:.3f}s.",
        f"Selected development candidate: `{recommended.rule}`; precision={recommended.precision:.1%}, recall={recommended.recall:.1%}, F1={recommended.f1:.1%}, non-fall false-alarm rate={recommended.session_false_alarm_rate:.1%}, median last lead={recommended.median_last_lead_time_s:.3f}s.",
        "",
        f"Candidates meeting recall >= 50% and no higher false-alarm rate than the current rule: {len(feasible)}.",
        "The candidate is not a final test result. It must be evaluated once, unchanged, on a frozen validation set.",
        "Raw CSV files and existing cleaning outputs were not modified.",
    ]
    (OUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=True, default=float))


if __name__ == "__main__":
    main()
