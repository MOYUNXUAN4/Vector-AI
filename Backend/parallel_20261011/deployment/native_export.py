"""Export an already-refit LightGBM Booster into the reviewed native format.

This utility validates declarations and artifact compatibility. It cannot prove
how a Booster was trained or whether the supplied provenance is truthful.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import shutil
import tempfile
import types
from pathlib import Path
from typing import Mapping

BACKEND_COPY = Path(r"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\parallel_20261010\backend")


def _contract():
    if not BACKEND_COPY.is_dir():
        raise RuntimeError(f"required backend copy is missing: {BACKEND_COPY}")
    package_name = "_native_export_contract_20261010"
    if package_name not in __import__("sys").modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(BACKEND_COPY)]
        __import__("sys").modules[package_name] = package
    artifact = importlib.import_module(f"{package_name}.model_artifact")
    features = importlib.import_module(f"{package_name}.causal_features")
    policy = importlib.import_module(f"{package_name}.alarm_policy")
    return artifact, features, policy


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _provenance_copy(provenance: Mapping) -> dict:
    if not isinstance(provenance, Mapping):
        raise ValueError("provenance must be a mapping of declarations")
    required = {"artifact_role", "training_dataset_ids", "development_session_ids",
                "threshold_selection_scope", "independent_test_used"}
    if set(provenance) != required:
        raise ValueError(f"provenance keys must exactly match {sorted(required)}")
    if provenance["artifact_role"] != "deployment_refit":
        raise ValueError("artifact_role must be deployment_refit")
    if provenance["threshold_selection_scope"] != "development_grouped_oof":
        raise ValueError("threshold_selection_scope must be development_grouped_oof")
    if provenance["independent_test_used"] is not False:
        raise ValueError("independent_test_used must be false")
    copied = dict(provenance)
    for key in ("training_dataset_ids", "development_session_ids"):
        values = copied[key]
        if not isinstance(values, (list, tuple)) or not values or any(
                not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError(f"{key} must be a nonempty list of nonempty IDs")
        if len(set(values)) != len(values):
            raise ValueError(f"{key} must not contain duplicates")
        copied[key] = list(values)
    frozen_test_ids = {"test929", "test1001", "test1006"}
    if any(value.casefold() in frozen_test_ids for value in copied["training_dataset_ids"]):
        raise ValueError("training_dataset_ids must not declare a known frozen independent test dataset")
    return copied


def export_native(booster, destination, *, model_id, medians, threshold, provenance):
    """Atomically export a pre-fit Booster; never fits, calibrates, or serializes Python objects."""
    artifact_module, feature_module, policy_module = _contract()
    names = list(feature_module.FEATURE_NAMES)
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("model_id must be nonempty")
    if not isinstance(medians, Mapping) or set(medians) != set(names):
        raise ValueError("medians must contain exactly the 24 reviewed feature names")
    fixed_medians = {name: _finite(medians[name], f"median {name}") for name in names}
    threshold = _finite(threshold, "threshold")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be explicitly supplied in [0, 1]")
    declared_provenance = _provenance_copy(provenance)
    if not isinstance(booster, __import__("lightgbm").Booster):
        raise TypeError("booster must be an already-refit native lightgbm.Booster")
    if list(booster.feature_name()) != names or booster.num_feature() != len(names):
        raise ValueError("Booster features must exactly match the reviewed 24 names and order")
    objective = (getattr(booster, "params", {}) or {}).get("objective")
    if not objective:
        objective = booster.dump_model().get("objective")
    valid_objective = isinstance(objective, str) and (
        objective.lower() == "binary" or
        re.fullmatch(r"binary\s+sigmoid\s*:\s*[0-9.eE+-]+", objective, re.I) is not None)
    if not valid_objective:
        raise ValueError("Booster objective must be binary (including native binary sigmoid:1)")

    dest = Path(destination).resolve()
    if dest.exists():
        raise FileExistsError(f"destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging_prefix = f".{dest.name}.staging-"
    temp = Path(tempfile.mkdtemp(prefix=staging_prefix, dir=dest.parent))
    validated_parent = dest.parent.resolve()
    try:
        model_path = temp / "model.txt"
        booster.save_model(str(model_path))
        model_hash = _sha256(model_path)
        manifest = {
            "schema_version": 1, "model_id": model_id, "target": "strong",
            "prediction_horizon_seconds": 0.75, "features": names,
            "medians": fixed_medians, "threshold": threshold,
            "confirmation_points": 2, "decision_interval_seconds": 0.05,
            "max_decision_gap_seconds": 0.1,
            "recovery_policy": "joint_ball_inward_and_clearance_gain_v1",
            "approved_for_experimental_runtime": True,
            "model_file": "model.txt", "model_sha256": model_hash,
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                 encoding="utf-8")
        # Round-trip through the actual strict loader, pinned by the just-computed digest.
        loaded = artifact_module.ModelArtifact.load(
            manifest_path, expected_model_sha256=model_hash, allow_experimental=True)
        if loaded.model_id != model_id or loaded.threshold != threshold:
            raise ValueError("strict loader round-trip returned mismatched metadata")
        # Exercise the same public inference contract used by runtime consumers.
        sample = {name: 0.0 for name in names}
        sample.update(directional_edge_distance=1.0, clearance=0.5,
                      ball_radius=0.5, platform_radius=1.0, ready=True)
        loaded.predict_probability(sample)

        dependencies = {}
        for filename in ("model_artifact.py", "causal_features.py", "alarm_policy.py"):
            source = BACKEND_COPY / filename
            dependencies[filename] = {"path": str(source), "sha256": _sha256(source)}
        manifest_hash = _sha256(manifest_path)
        evidence = {
            "experimental_only": True,
            "performance_validated": False,
            "approval_scope": "experimental runtime only; final runtime remains default-off",
            "provenance_declarations": declared_provenance,
            "provenance_limitation": "These fields are caller declarations. This exporter validates completeness and required values only; it does not prove training history, dataset identity, threshold selection, or test-set isolation.",
            "dependency_provenance": {"backend_copy": str(BACKEND_COPY), "files": dependencies},
            "model_sha256": model_hash,
            "manifest_sha256": manifest_hash,
        }
        evidence_path = temp / "build_evidence.json"
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                 encoding="utf-8")
        # Ensure serialization remains the strict schema understood by the loader.
        artifact_module.ModelArtifact.load(manifest_path, expected_model_sha256=model_hash,
                                           allow_experimental=True)
        temp.rename(dest)
    except Exception:
        resolved_temp = temp.resolve()
        if resolved_temp.parent == validated_parent and resolved_temp.name.startswith(staging_prefix):
            shutil.rmtree(resolved_temp, ignore_errors=True)
        raise
    return {
        "directory": str(dest),
        "model": str(dest / "model.txt"),
        "manifest": str(dest / "manifest.json"),
        "evidence": str(dest / "build_evidence.json"),
        "model_sha256": model_hash,
        "manifest_sha256": manifest_hash,
    }
