"""Repeated session-level development CV for GRU feature stability.

This is a robustness check, not a final test: only TEST9282, TEST930 and
TEST931 are used.  TEST929 remains completely untouched.  The two candidate
feature sets use the previously calibrated development thresholds (all-current
0.75 and edge-kinematic 0.95) so the comparison does not tune a threshold on
each fold.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

import calibrate_gru_threshold as calibration
import run_gru_feature_horizon_experiment as feature_exp
import train_gru_offline as gru


ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "gru_repeated_dev_cv"


def load_development() -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for manifest in gru.DEFAULT_TRAIN_MANIFESTS:
        loaded, _ = gru.load_manifest_sessions(Path(manifest), None, True, False)
        sessions.extend(loaded)
    return sessions


def metric(result: dict[str, Any], group: str, seed: int, train_n: int, eval_n: int, threshold: float) -> dict[str, Any]:
    row = {
        "feature_group": group,
        "seed": seed,
        "train_sessions": train_n,
        "eval_sessions": eval_n,
        "threshold_fixed": threshold,
    }
    row.update({f"window_{key}": value for key, value in result["window"].items() if key != "method"})
    row.update({f"session_{key}": value for key, value in result["session"].items() if key != "method"})
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seeds", type=int, nargs="+", default=[20261001, 20261002, 20261003, 20261004, 20261005])
    parser.add_argument("--horizon-seconds", type=float, default=0.5)
    parser.add_argument("--window-seconds", type=float, default=1.0)
    parser.add_argument("--stride-seconds", type=float, default=0.25)
    parser.add_argument("--sequence-length", type=int, default=60)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    development = load_development()
    results: list[dict[str, Any]] = []
    feature_groups = {
        "all_current": (feature_exp.FEATURE_GROUPS["all_current"], 0.75),
        "edge_kinematic": (feature_exp.FEATURE_GROUPS["edge_kinematic"], 0.95),
    }
    name_to_index = {name: index for index, name in enumerate(gru.FEATURE_CANDIDATES)}

    for seed in args.seeds:
        random.seed(seed)
        np.random.seed(seed)
        train_sessions, eval_sessions = gru.session_split(development, 0.20, seed)
        for group, (names, threshold) in feature_groups.items():
            indices = [
                name_to_index[name]
                for name in names
                if name in name_to_index
                and any(np.isfinite(session["feature_table"][:, name_to_index[name]]).any() for session in train_sessions)
            ]
            run_args = SimpleNamespace(
                horizon_seconds=args.horizon_seconds,
                window_seconds=args.window_seconds,
                stride_seconds=args.stride_seconds,
                sequence_length=args.sequence_length,
                hidden_size=args.hidden_size,
                epochs=args.epochs,
                batch_size=args.batch_size,
                seed=seed,
            )
            train_examples = calibration.prepare_examples(train_sessions, indices, run_args)
            eval_examples = calibration.prepare_examples(eval_sessions, indices, run_args)
            probabilities, _, _ = calibration.train_probabilities(train_examples, eval_examples, run_args)
            result, _ = gru.metrics_from_predictions(eval_examples, probabilities >= threshold, f"gru_{group}")
            results.append(metric(result, group, seed, len(train_sessions), len(eval_sessions), threshold))

    frame = pd.DataFrame(results)
    frame.to_csv(args.out_dir / "repeated_dev_cv.csv", index=False, encoding="utf-8-sig")
    summary_rows: list[dict[str, Any]] = []
    for group, group_frame in frame.groupby("feature_group", sort=True):
        summary_rows.append(
            {
                "feature_group": group,
                "folds": int(len(group_frame)),
                "session_f1_mean": float(group_frame.session_f1.mean()),
                "session_f1_std": float(group_frame.session_f1.std(ddof=1)),
                "session_recall_mean": float(group_frame.session_recall.mean()),
                "session_precision_mean": float(group_frame.session_precision.mean()),
                "session_nonfall_false_alarm_rate_mean": float(group_frame.session_nonfall_false_alarm_rate.mean()),
                "session_nonfall_false_alarm_rate_std": float(group_frame.session_nonfall_false_alarm_rate.std(ddof=1)),
                "session_last_warning_lead_median_mean_s": float(group_frame.session_last_warning_lead_median_s.mean()),
            }
        )
    summary = {
        "development_datasets": ["TEST9282", "TEST930", "TEST931"],
        "development_sessions": len(development),
        "seeds": list(args.seeds),
        "split_fraction": 0.20,
        "test_set_used": False,
        "raw_files_modified": False,
        "summary": summary_rows,
    }
    pd.DataFrame(summary_rows).to_csv(args.out_dir / "repeated_dev_cv_summary.csv", index=False, encoding="utf-8-sig")
    (args.out_dir / "summary.json").write_text(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(gru.finite_json(summary), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
