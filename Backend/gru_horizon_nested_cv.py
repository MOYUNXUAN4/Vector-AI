"""Nested session-grouped CV for offline GRU prediction-horizon comparison.

Outer folds estimate out-of-fold performance on the development pool. Within
each outer-training partition, inner session-grouped folds produce out-of-fold
probabilities used to select that horizon's probability threshold. The outer
held-out sessions are never used for threshold selection or model scaling.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

import calibrate_gru_threshold as calibration
import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "gru_horizon_nested_cv_20261002_fixed12features"
EXPECTED_DATASETS = {"TEST9282", "TEST930", "TEST931"}
HORIZONS = (0.5, 0.75, 1.0, 1.5)
THRESHOLDS = np.round(np.arange(0.05, 0.951, 0.05), 2)
SELECTED_CONFIG = ROOT / "gru_feature_horizon_experiment" / "selected_configuration.json"


def session_key(session: dict[str, Any]) -> tuple[str, str]:
    return str(session["dataset"]), str(session["session_id"])


def is_fall(session: dict[str, Any]) -> bool:
    return bool(np.isfinite(session["first_event_ts"]))


def load_development() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sessions: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for manifest in gru.DEFAULT_TRAIN_MANIFESTS:
        loaded, note = gru.load_manifest_sessions(Path(manifest), None, True, False)
        sessions.extend(loaded)
        notes.append(note)
    datasets = {str(session["dataset"]) for session in sessions}
    if datasets != EXPECTED_DATASETS:
        raise RuntimeError(f"Expected only {sorted(EXPECTED_DATASETS)}, loaded {sorted(datasets)}")
    keys = [session_key(session) for session in sessions]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Duplicate dataset/session keys in development manifests")
    return sessions, notes


def all_horizon_examples(
    sessions: list[dict[str, Any]], args: argparse.Namespace
) -> dict[float, dict[tuple[str, str], list[dict[str, Any]]]]:
    """Build full-feature causal windows once per session and requested horizon."""

    full_feature_indices = list(range(len(gru.FEATURE_CANDIDATES)))
    examples_by_horizon: dict[float, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    for horizon in HORIZONS:
        result: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for session in sessions:
            gru.build_examples(
                session,
                full_feature_indices,
                horizon,
                args.window_seconds,
                args.stride_seconds,
                args.sequence_length,
            )
            result[session_key(session)] = list(session["examples"])
        examples_by_horizon[horizon] = result
    return examples_by_horizon


def stratified_session_folds(
    sessions: list[dict[str, Any]], n_folds: int, seed: int
) -> dict[tuple[str, str], int]:
    """Assign whole sessions to balanced folds within dataset-by-label strata."""

    if n_folds < 2 or len(sessions) < n_folds:
        raise ValueError("Need at least two folds and at least one session per fold")
    strata: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        strata[(str(session["dataset"]), is_fall(session))].append(session)
    rng = np.random.default_rng(seed)
    assignments: dict[tuple[str, str], int] = {}
    offset = 0
    for stratum in sorted(strata, key=lambda item: (item[0], item[1])):
        members = strata[stratum]
        order = rng.permutation(len(members))
        for position, index in enumerate(order):
            assignments[session_key(members[int(index)])] = (offset + position) % n_folds
        offset = (offset + len(members)) % n_folds
    if len(assignments) != len(sessions):
        raise RuntimeError("A session was omitted while assigning folds")
    return assignments


def feature_indices(train_sessions: list[dict[str, Any]]) -> list[int]:
    """Freeze input features so this experiment changes only prediction horizon."""
    selected = json.loads(SELECTED_CONFIG.read_text(encoding="utf-8"))["selected_feature_names"]
    name_to_index = {name: index for index, name in enumerate(gru.FEATURE_CANDIDATES)}
    unknown = [name for name in selected if name not in name_to_index]
    if unknown:
        raise RuntimeError(f"Selected configuration references unknown features: {unknown}")
    return [name_to_index[name] for name in selected]


def examples_for(
    sessions: list[dict[str, Any]],
    examples_by_session: dict[tuple[str, str], list[dict[str, Any]]],
    indices: list[int],
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for session in sessions:
        for example in examples_by_session[session_key(session)]:
            selected = dict(example)
            selected["sequence"] = example["sequence"][:, indices]
            examples.append(selected)
    return examples


def run_args(args: argparse.Namespace, horizon: float, seed: int) -> SimpleNamespace:
    return SimpleNamespace(
        horizon_seconds=horizon,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
        sequence_length=args.sequence_length,
        hidden_size=args.hidden_size,
        epochs=args.epochs,
        batch_size=args.batch_size,
        seed=seed,
    )


def model_probabilities(
    train_sessions: list[dict[str, Any]],
    eval_sessions: list[dict[str, Any]],
    examples_by_session: dict[tuple[str, str], list[dict[str, Any]]],
    args: argparse.Namespace,
    horizon: float,
    seed: int,
) -> tuple[list[dict[str, Any]], np.ndarray, list[int], dict[str, Any]]:
    indices = feature_indices(train_sessions)
    train_examples = examples_for(train_sessions, examples_by_session, indices)
    eval_examples = examples_for(eval_sessions, examples_by_session, indices)
    probabilities, scaler, fit_result = calibration.train_probabilities(
        train_examples, eval_examples, run_args(args, horizon, seed)
    )
    if fit_result.get("status") == "skipped":
        raise RuntimeError(f"GRU fit skipped: {fit_result}")
    fit_result["scaler"] = scaler.to_json()
    return eval_examples, probabilities, indices, fit_result


def choose_threshold(table: pd.DataFrame) -> tuple[float, str]:
    selected, rule = calibration.choose_threshold(
        table, target_far=0.25, min_recall=0.60
    )
    return selected, rule


def metric_row(
    result: dict[str, Any], horizon: float, fold: int, threshold: float
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "horizon_s": horizon,
        "outer_fold": fold,
        "threshold": threshold,
    }
    row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
    row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--outer-folds", type=int, default=3)
    parser.add_argument("--inner-folds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--window-seconds", type=float, default=1.0)
    parser.add_argument("--stride-seconds", type=float, default=0.25)
    parser.add_argument("--sequence-length", type=int, default=60)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()

    if args.out_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing output directory: {args.out_dir}")
    if args.outer_folds < 3 or args.inner_folds < 2:
        raise ValueError("Use at least 3 outer folds and 2 inner folds")
    args.out_dir.mkdir(parents=True, exist_ok=False)

    sessions, manifest_notes = load_development()
    examples_by_horizon = all_horizon_examples(sessions, args)
    eligible_keys = set.intersection(*(
        {key for key, examples in examples_by_horizon[horizon].items() if examples}
        for horizon in HORIZONS
    ))
    eligible_sessions = [session for session in sessions if session_key(session) in eligible_keys]
    excluded_sessions = [session for session in sessions if session_key(session) not in eligible_keys]
    if not eligible_sessions:
        raise RuntimeError("No sessions have windows at every requested horizon")

    outer_assignment = stratified_session_folds(
        eligible_sessions, args.outer_folds, args.seed
    )
    split_rows: list[dict[str, Any]] = []
    for session in eligible_sessions:
        key = session_key(session)
        split_rows.append({
            "dataset": key[0],
            "session_id": key[1],
            "is_fall_session": is_fall(session),
            "first_event_ts": session["first_event_ts"],
            "outer_fold": outer_assignment[key],
            "role": "outer_test_once",
            **{f"windows_h{horizon:g}s": len(examples_by_horizon[horizon][key]) for horizon in HORIZONS},
        })
    pd.DataFrame(split_rows).to_csv(args.out_dir / "eligible_sessions_and_outer_folds.csv", index=False, encoding="utf-8-sig")
    if excluded_sessions:
        pd.DataFrame([
            {
                "dataset": session["dataset"],
                "session_id": session["session_id"],
                "is_fall_session": is_fall(session),
                "windows_by_horizon": json.dumps({h: len(examples_by_horizon[h][session_key(session)]) for h in HORIZONS}),
                "reason": "no causal windows for at least one requested horizon",
            }
            for session in excluded_sessions
        ]).to_csv(args.out_dir / "excluded_sessions.csv", index=False, encoding="utf-8-sig")

    # Verify complete outer test coverage and within-fold class availability.
    for fold in range(args.outer_folds):
        held = [session for session in eligible_sessions if outer_assignment[session_key(session)] == fold]
        train = [session for session in eligible_sessions if outer_assignment[session_key(session)] != fold]
        if not held or not train:
            raise RuntimeError(f"Empty outer fold {fold}")
        if not any(is_fall(session) for session in held) or all(is_fall(session) for session in held):
            raise RuntimeError(f"Outer test fold {fold} does not contain both session labels")
        if not any(is_fall(session) for session in train) or all(is_fall(session) for session in train):
            raise RuntimeError(f"Outer training fold {fold} does not contain both session labels")

    outer_metric_rows: list[dict[str, Any]] = []
    threshold_rows: list[dict[str, Any]] = []
    threshold_grid_rows: list[dict[str, Any]] = []
    inner_split_rows: list[dict[str, Any]] = []
    outer_session_rows: list[dict[str, Any]] = []
    missed_rows: list[dict[str, Any]] = []
    fit_rows: list[dict[str, Any]] = []
    oof_examples_by_horizon: dict[float, list[dict[str, Any]]] = {h: [] for h in HORIZONS}
    oof_predictions_by_horizon: dict[float, list[bool]] = {h: [] for h in HORIZONS}

    for outer_fold in range(args.outer_folds):
        outer_train = [session for session in eligible_sessions if outer_assignment[session_key(session)] != outer_fold]
        outer_test = [session for session in eligible_sessions if outer_assignment[session_key(session)] == outer_fold]
        inner_assignment = stratified_session_folds(
            outer_train, args.inner_folds, args.seed + 1000 + outer_fold
        )
        for session in outer_train:
            inner_split_rows.append({
                "outer_fold": outer_fold,
                "dataset": session["dataset"],
                "session_id": session["session_id"],
                "is_fall_session": is_fall(session),
                "role": "inner_oof_calibration",
                "inner_fold": inner_assignment[session_key(session)],
            })
        for session in outer_test:
            inner_split_rows.append({
                "outer_fold": outer_fold,
                "dataset": session["dataset"],
                "session_id": session["session_id"],
                "is_fall_session": is_fall(session),
                "role": "outer_test_excluded_from_threshold_selection",
                "inner_fold": np.nan,
            })

        for horizon in HORIZONS:
            horizon_examples = examples_by_horizon[horizon]
            inner_oof_examples: list[dict[str, Any]] = []
            inner_oof_probabilities: list[float] = []
            inner_seen: set[tuple[str, str]] = set()
            for inner_fold in range(args.inner_folds):
                inner_train = [session for session in outer_train if inner_assignment[session_key(session)] != inner_fold]
                inner_valid = [session for session in outer_train if inner_assignment[session_key(session)] == inner_fold]
                if not inner_valid or not inner_train:
                    raise RuntimeError(f"Empty inner fold {outer_fold}/{inner_fold}")
                eval_examples, probabilities, indices, fit_result = model_probabilities(
                    inner_train,
                    inner_valid,
                    horizon_examples,
                    args,
                    horizon,
                    args.seed + outer_fold * 10000 + inner_fold,
                )
                fit_rows.append({
                    "stage": "inner_oof_threshold_fit",
                    "outer_fold": outer_fold,
                    "inner_fold": inner_fold,
                    "horizon_s": horizon,
                    "train_sessions": len(inner_train),
                    "eval_sessions": len(inner_valid),
                    "feature_names": [gru.FEATURE_CANDIDATES[i] for i in indices],
                    **fit_result,
                })
                keys_this_fold = {session_key(session) for session in inner_valid}
                if inner_seen.intersection(keys_this_fold):
                    raise RuntimeError("An inner calibration session appears in multiple inner folds")
                inner_seen.update(keys_this_fold)
                inner_oof_examples.extend(eval_examples)
                inner_oof_probabilities.extend(np.asarray(probabilities, dtype=float).tolist())
            if inner_seen != {session_key(session) for session in outer_train}:
                raise RuntimeError("Inner OOF predictions do not cover each outer-training session exactly once")

            calibration_rows: list[dict[str, Any]] = []
            inner_prob_array = np.asarray(inner_oof_probabilities, dtype=float)
            for threshold in THRESHOLDS:
                result, _ = gru.metrics_from_predictions(
                    inner_oof_examples, inner_prob_array >= threshold, "inner_oof_calibration"
                )
                row = {
                    "outer_fold": outer_fold,
                    "horizon_s": horizon,
                    "threshold": float(threshold),
                }
                row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
                calibration_rows.append(row)
                threshold_grid_rows.append(row.copy())
            threshold_table = pd.DataFrame(calibration_rows)
            selected_threshold, selection_rule = choose_threshold(threshold_table.rename(columns={
                "session_nonfall_false_alarm_rate": "session_nonfall_false_alarm_rate",
                "session_recall": "session_recall",
            }))
            chosen_row = threshold_table.loc[np.isclose(threshold_table.threshold, selected_threshold)].iloc[0]
            threshold_rows.append({
                "outer_fold": outer_fold,
                "horizon_s": horizon,
                "selected_threshold": selected_threshold,
                "selection_rule": selection_rule,
                "target_nonfall_far": 0.25,
                "minimum_recall": 0.60,
                "inner_oof_train_sessions": len(outer_train),
                "inner_oof_fall_sessions": sum(is_fall(session) for session in outer_train),
                "inner_oof_nonfall_sessions": sum(not is_fall(session) for session in outer_train),
                "inner_oof_session_precision": chosen_row["session_precision"],
                "inner_oof_session_recall": chosen_row["session_recall"],
                "inner_oof_session_f1": chosen_row["session_f1"],
                "inner_oof_session_nonfall_false_alarm_rate": chosen_row["session_nonfall_false_alarm_rate"],
            })

            outer_eval_examples, outer_probabilities, indices, fit_result = model_probabilities(
                outer_train,
                outer_test,
                horizon_examples,
                args,
                horizon,
                args.seed + outer_fold * 10000 + 9000,
            )
            fit_rows.append({
                "stage": "outer_test_fit",
                "outer_fold": outer_fold,
                "inner_fold": np.nan,
                "horizon_s": horizon,
                "train_sessions": len(outer_train),
                "eval_sessions": len(outer_test),
                "feature_names": [gru.FEATURE_CANDIDATES[i] for i in indices],
                **fit_result,
            })
            outer_predictions = np.asarray(outer_probabilities, dtype=float) >= selected_threshold
            outer_result, detail_rows = gru.metrics_from_predictions(
                outer_eval_examples, outer_predictions, f"gru_h{horizon:g}_outer_fold_{outer_fold}"
            )
            outer_metric_rows.append(metric_row(outer_result, horizon, outer_fold, selected_threshold))
            for detail in detail_rows:
                outer_session_rows.append({
                    **detail,
                    "horizon_s": horizon,
                    "outer_fold": outer_fold,
                    "threshold": selected_threshold,
                })
                if detail["is_fall_session"] and not detail["detected_session"]:
                    missed_rows.append({
                        "horizon_s": horizon,
                        "outer_fold": outer_fold,
                        "dataset": detail["dataset"],
                        "session_id": detail["session_id"],
                        "threshold": selected_threshold,
                        "off_target_alarm_session": detail["off_target_alarm_session"],
                    })
            oof_examples_by_horizon[horizon].extend(outer_eval_examples)
            oof_predictions_by_horizon[horizon].extend(outer_predictions.tolist())

    pd.DataFrame(inner_split_rows).to_csv(args.out_dir / "nested_session_splits.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(threshold_grid_rows).to_csv(args.out_dir / "inner_oof_threshold_grid.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(threshold_rows).to_csv(args.out_dir / "selected_thresholds_by_outer_fold.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(outer_metric_rows).to_csv(args.out_dir / "outer_fold_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(outer_session_rows).to_csv(args.out_dir / "outer_oof_session_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(missed_rows, columns=["horizon_s", "outer_fold", "dataset", "session_id", "threshold", "off_target_alarm_session"]).to_csv(args.out_dir / "missed_falls.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(fit_rows).to_json(args.out_dir / "fit_audit.json", orient="records", indent=2, force_ascii=False)

    pooled_rows: list[dict[str, Any]] = []
    lead_summary: dict[str, dict[str, float | int | None]] = {}
    pooled_detail_all: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        examples = oof_examples_by_horizon[horizon]
        predictions = np.asarray(oof_predictions_by_horizon[horizon], dtype=bool)
        result, detail_rows = gru.metrics_from_predictions(examples, predictions, f"gru_h{horizon:g}_nested_oof")
        pooled_rows.append(metric_row(result, horizon, -1, float("nan")))
        detected_falls = [
            row for row in detail_rows
            if row["is_fall_session"] and row["detected_session"] and np.isfinite(row["first_warning_lead_s"])
        ]
        first_leads = np.asarray([row["first_warning_lead_s"] for row in detected_falls], dtype=float)
        last_leads = np.asarray([row["last_warning_lead_s"] for row in detected_falls], dtype=float)
        lead_summary[f"{horizon:g}"] = {
            "detected_fall_sessions_with_valid_lead": int(len(first_leads)),
            "first_target_warning_lead_median_s": float(np.median(first_leads)) if len(first_leads) else None,
            "first_target_warning_lead_p25_s": float(np.percentile(first_leads, 25)) if len(first_leads) else None,
            "last_target_warning_lead_median_s": float(np.median(last_leads)) if len(last_leads) else None,
            "last_target_warning_lead_p25_s": float(np.percentile(last_leads, 25)) if len(last_leads) else None,
        }
        for row in detail_rows:
            pooled_detail_all.append({**row, "horizon_s": horizon})
    pd.DataFrame(pooled_rows).to_csv(args.out_dir / "pooled_outer_oof_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(pooled_detail_all).to_csv(args.out_dir / "pooled_outer_oof_session_metrics.csv", index=False, encoding="utf-8-sig")

    cohort_rows = []
    for dataset in sorted(EXPECTED_DATASETS):
        cohort = [session for session in eligible_sessions if session["dataset"] == dataset]
        cohort_rows.append({
            "dataset": dataset,
            "eligible_sessions": len(cohort),
            "fall_sessions": sum(is_fall(session) for session in cohort),
            "nonfall_sessions": sum(not is_fall(session) for session in cohort),
        })
    cohort_rows.append({
        "dataset": "ALL",
        "eligible_sessions": len(eligible_sessions),
        "fall_sessions": sum(is_fall(session) for session in eligible_sessions),
        "nonfall_sessions": sum(not is_fall(session) for session in eligible_sessions),
    })
    pd.DataFrame(cohort_rows).to_csv(args.out_dir / "eligible_session_counts.csv", index=False, encoding="utf-8-sig")

    summary = {
        "experiment": "nested session-grouped out-of-fold GRU horizon comparison",
        "development_datasets": sorted(EXPECTED_DATASETS),
        "test1001_used": False,
        "loaded_sessions": len(sessions),
        "eligible_sessions_all_horizons": len(eligible_sessions),
        "excluded_sessions": len(excluded_sessions),
        "eligible_fall_sessions": int(sum(is_fall(session) for session in eligible_sessions)),
        "eligible_nonfall_sessions": int(sum(not is_fall(session) for session in eligible_sessions)),
        "dataset_session_counts": cohort_rows,
        "outer_cv": {
            "folds": args.outer_folds,
            "stratification": "complete session groups, balanced within dataset x fall-label strata",
            "each_eligible_session_tested_once": True,
            "outer_seed": args.seed,
        },
        "inner_threshold_cv": {
            "folds": args.inner_folds,
            "selection_data": "out-of-fold probabilities on outer-training sessions only",
            "threshold_grid": THRESHOLDS.astype(float).tolist(),
            "selection_rule": "existing calibrate_gru_threshold.choose_threshold: maximize session F1 subject to nonfall FAR <= 0.25 and session recall >= 0.60; fallback to minimum FAR among recall-feasible thresholds, else minimum FAR",
            "outer_test_sessions_used_for_selection": False,
        },
        "horizons_s": list(HORIZONS),
        "model": {
            "feature_scope": "fixed selected feature set from gru_feature_horizon_experiment/selected_configuration.json; prediction horizon is the only changed target",
            "feature_names": json.loads(SELECTED_CONFIG.read_text(encoding="utf-8"))["selected_feature_names"],
            "window_seconds": args.window_seconds,
            "stride_seconds": args.stride_seconds,
            "sequence_length": args.sequence_length,
            "hidden_size": args.hidden_size,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "scaler_fit_scope": "each fit's training-session windows only",
        },
        "warning_lead_definition": "first/last target-positive warning episode onset per detected fall session; an onset groups positive alarms separated by at most 0.5 s, using the established metrics_from_predictions definition",
        "lead_summary_by_horizon": lead_summary,
        "pooled_outer_oof_metrics": pooled_rows,
        "manifest_notes": manifest_notes,
        "raw_telemetry_modified": False,
        "unity_files_modified": False,
        "limitations": [
            "All sessions are from the development pool; this is not a frozen independent test evaluation.",
            "Each horizon's threshold is selected using inner out-of-fold scores, while final outer-fold models are fit on more sessions; this can shift probability calibration.",
            "Session counts are modest and the 25% FAR / 60% recall operating constraints may be infeasible in some folds.",
            "The requested horizons were fixed before this run, but this pool has prior development analyses; use a separate untouched cohort for confirmatory claims.",
        ],
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (args.out_dir / "README.md").write_text(
        "# Nested session-grouped GRU horizon comparison\n\n"
        "This offline experiment uses only the clean development manifests for TEST9282, TEST930, and TEST931. "
        "It compares 0.5, 0.75, 1.0, and 1.5 second target horizons. Each eligible complete session is assigned to exactly one outer test fold, with folds balanced by dataset and fall-session label.\n\n"
        "For each outer fold and horizon, threshold selection uses only inner out-of-fold probabilities from the outer-training sessions. It searches 0.05 through 0.95 in 0.05 increments and applies the established 25% non-fall FAR / 60% recall rule. The outer fold is evaluated once after a fresh fit on the complete outer-training sessions. Every scaler is fit on the corresponding model-training windows only.\n\n"
        "`pooled_outer_oof_metrics.csv` is the primary per-horizon summary. Session-level lead summaries include detected fall sessions only and use first target-positive warning onset; the last target-positive onset summaries are also recorded in `summary.json`. `missed_falls.csv`, split assignments, threshold grids, fold metrics, and fit audit are retained for review. No TEST1001, raw telemetry edits, or Unity edits are part of this run.\n",
        encoding="utf-8",
    )
    print(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
