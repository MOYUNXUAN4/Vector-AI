"""Strict loader and inference wrapper for approved native LightGBM artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import copy
import re
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

import numpy as np

try:  # Package import (backend.model_artifact).
    from .causal_features import FEATURE_NAMES
except ImportError:  # Stage1/script import with backend on sys.path.
    from causal_features import FEATURE_NAMES


class ArtifactError(ValueError):
    """Raised when an artifact or inference input violates the runtime contract."""


_REQUIRED = {
    "schema_version", "model_id", "target", "prediction_horizon_seconds",
    "features", "medians", "threshold", "confirmation_points",
    "decision_interval_seconds", "max_decision_gap_seconds", "recovery_policy",
    "approved_for_experimental_runtime", "model_file", "model_sha256",
}
_GEOMETRY = ("directional_edge_distance", "clearance", "radial_outward_velocity",
             "ball_radius", "platform_radius")


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ArtifactError(f"{label} must be a finite number")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class ModelArtifact:
    """Loaded, hash-pinned native LightGBM booster with explicit threshold."""

    def __init__(self, *, booster, model_id: str, threshold: float, sha256: str,
                 medians: Mapping[str, float], manifest: Mapping):
        self._booster = booster
        self._model_id = model_id
        self._threshold = threshold
        self._sha256 = sha256
        self._medians = MappingProxyType(dict(medians))
        self._manifest = _freeze(copy.deepcopy(dict(manifest)))

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def sha256(self) -> str:
        return self._sha256

    @property
    def model_sha256(self) -> str:
        return self._sha256

    @property
    def decision_interval_seconds(self) -> float:
        return self._manifest["decision_interval_seconds"]

    @property
    def max_decision_gap_seconds(self) -> float:
        return self._manifest["max_decision_gap_seconds"]

    @property
    def config(self) -> Mapping:
        """Read-only configuration metadata needed by the runtime integrator."""
        return self._manifest

    @classmethod
    def load(cls, manifest_path, *, expected_model_sha256: str,
             allow_experimental: bool = False,
             booster_factory: Callable | None = None) -> "ModelArtifact":
        path = Path(manifest_path)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"),
                                  object_pairs_hook=_unique_object,
                                  parse_constant=lambda x: (_ for _ in ()).throw(
                                      ArtifactError(f"invalid JSON number: {x}")))
        except ArtifactError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"cannot read valid UTF-8 JSON manifest: {exc}") from exc
        if not isinstance(manifest, dict) or set(manifest) != _REQUIRED:
            missing = sorted(_REQUIRED - set(manifest)) if isinstance(manifest, dict) else sorted(_REQUIRED)
            extra = sorted(set(manifest) - _REQUIRED) if isinstance(manifest, dict) else []
            raise ArtifactError(f"manifest schema keys mismatch (missing={missing}, extra={extra})")
        if manifest["schema_version"] != 1 or isinstance(manifest["schema_version"], bool):
            raise ArtifactError("schema_version must be 1")
        if not isinstance(manifest["model_id"], str) or not manifest["model_id"].strip():
            raise ArtifactError("model_id must be nonempty")
        if manifest["target"] != "strong":
            raise ArtifactError("target must be 'strong'")
        if _finite_number(manifest["prediction_horizon_seconds"], "prediction_horizon_seconds") != .75:
            raise ArtifactError("prediction_horizon_seconds must be 0.75")
        if manifest["features"] != list(FEATURE_NAMES):
            raise ArtifactError("features must exactly match FEATURE_NAMES in order")
        medians = manifest["medians"]
        if not isinstance(medians, dict) or set(medians) != set(FEATURE_NAMES):
            raise ArtifactError("medians must contain exactly all 24 feature names")
        medians = {name: _finite_number(medians[name], f"median {name}") for name in FEATURE_NAMES}
        threshold = _finite_number(manifest["threshold"], "threshold")
        if not 0 <= threshold <= 1:
            raise ArtifactError("threshold must be explicitly supplied in [0, 1]")
        for key, expected in (("confirmation_points", 2),):
            if isinstance(manifest[key], bool) or manifest[key] != expected:
                raise ArtifactError(f"{key} must be {expected}")
        for key, expected in (("decision_interval_seconds", .05), ("max_decision_gap_seconds", .1)):
            if _finite_number(manifest[key], key) != expected:
                raise ArtifactError(f"{key} must be {expected}")
        if manifest["recovery_policy"] != "joint_ball_inward_and_clearance_gain_v1":
            raise ArtifactError("unsupported recovery_policy")
        if manifest["approved_for_experimental_runtime"] is not True or allow_experimental is not True:
            raise ArtifactError("experimental runtime approval requires manifest approval and allow_experimental=True")
        if not isinstance(expected_model_sha256, str) or len(expected_model_sha256) != 64 or any(
                c not in "0123456789abcdefABCDEF" for c in expected_model_sha256):
            raise ArtifactError("expected_model_sha256 must be a trusted 64-character SHA-256 hex digest")
        declared = manifest["model_sha256"]
        if not isinstance(declared, str) or declared.lower() != expected_model_sha256.lower():
            raise ArtifactError("manifest model_sha256 does not match caller-pinned digest")
        model_file = manifest["model_file"]
        if not isinstance(model_file, str) or not model_file or Path(model_file).is_absolute():
            raise ArtifactError("model_file must be a relative filename")
        base = path.resolve().parent
        artifact_path = (base / model_file).resolve()
        try:
            artifact_path.relative_to(base)
        except ValueError as exc:
            raise ArtifactError("model_file resolves outside manifest directory") from exc
        if not artifact_path.is_file():
            raise ArtifactError("model_file does not identify a regular file")
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual.lower() != expected_model_sha256.lower():
            raise ArtifactError("model bytes do not match caller-pinned SHA-256")
        if booster_factory is None:
            try:
                import lightgbm as lgb
            except ImportError as exc:
                raise ArtifactError("LightGBM is required to load native text Booster artifacts") from exc
            booster_factory = lambda filename: lgb.Booster(model_file=str(filename))
        try:
            booster = booster_factory(str(artifact_path))
        except Exception as exc:
            raise ArtifactError(f"cannot load native LightGBM model: {exc}") from exc
        try:
            names = list(booster.feature_name())
            count = booster.num_feature()
            params = getattr(booster, "params", {}) or {}
            objective = params.get("objective")
            if not objective and hasattr(booster, "dump_model"):
                objective = booster.dump_model().get("objective")
        except Exception as exc:
            raise ArtifactError(f"cannot inspect loaded Booster compatibility: {exc}") from exc
        if names != list(FEATURE_NAMES) or count != len(FEATURE_NAMES):
            raise ArtifactError("Booster feature names/count do not match the exact 24-feature contract")
        is_binary = isinstance(objective, str) and (
            objective.lower() == "binary" or
            re.fullmatch(r"binary\s+sigmoid\s*:\s*[0-9.eE+-]+", objective, re.IGNORECASE) is not None
        )
        if not is_binary:
            raise ArtifactError("Booster objective must be binary classification")
        loaded_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if loaded_digest.lower() != expected_model_sha256.lower():
            raise ArtifactError("model bytes changed during Booster loading")
        return cls(booster=booster, model_id=manifest["model_id"], threshold=threshold,
                   sha256=loaded_digest, medians=medians, manifest=manifest)

    def predict_probability(self, features: Mapping[str, object]) -> float:
        if not isinstance(features, Mapping):
            raise ArtifactError("features must be a mapping")
        if features.get("ready") is False:
            raise ArtifactError("feature vector is not ready")
        missing = set(FEATURE_NAMES) - set(features)
        if missing:
            raise ArtifactError(f"missing required features: {sorted(missing)}")
        geometry = {key: _finite_number(features[key], key) for key in _GEOMETRY}
        if geometry["ball_radius"] <= 0 or geometry["platform_radius"] <= 0:
            raise ArtifactError("physical radii must be positive")
        if geometry["clearance"] <= 0:
            raise ArtifactError("clearance must be positive; unsafe geometry is ineligible")
        row = []
        for name in FEATURE_NAMES:
            value = features[name]
            if isinstance(value, bool):
                raise ArtifactError(f"feature {name} must not be boolean")
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ArtifactError(f"feature {name} must be numeric or NaN") from exc
            if math.isnan(number):
                number = self._medians[name]
            elif not math.isfinite(number):
                raise ArtifactError(f"feature {name} must not be infinite")
            row.append(number)
        try:
            prediction = self._booster.predict(np.asarray([row], dtype=np.float64))
        except Exception as exc:
            raise ArtifactError(f"Booster probability prediction failed: {exc}") from exc
        try:
            if len(prediction) != 1:
                raise ArtifactError("Booster returned an invalid prediction shape")
            result = float(prediction[0])
        except (TypeError, ValueError, IndexError) as exc:
            raise ArtifactError("Booster returned an invalid prediction shape") from exc
        if not math.isfinite(result) or not 0 <= result <= 1:
            raise ArtifactError("Booster prediction must be a finite probability in [0, 1]")
        return result
