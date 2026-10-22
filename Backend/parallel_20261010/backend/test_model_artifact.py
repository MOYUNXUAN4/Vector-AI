import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

import numpy as np

try:
    from backend.causal_features import FEATURE_NAMES
    from backend.model_artifact import ArtifactError, ModelArtifact
except ImportError:
    from causal_features import FEATURE_NAMES
    from model_artifact import ArtifactError, ModelArtifact


class FakeBooster:
    def __init__(self, objective="binary", prediction=.7, names=None):
        self.params = {"objective": objective}
        self.prediction = prediction
        self.names = list(FEATURE_NAMES if names is None else names)
        self.rows = None

    def feature_name(self):
        return self.names

    def num_feature(self):
        return len(self.names)

    def predict(self, rows):
        self.rows = rows
        return [self.prediction]

    def dump_model(self):
        return {"objective": "binary sigmoid:1"}


class _ObjectiveBooster(FakeBooster):
    def __init__(self, objective):
        super().__init__(objective=None)
        self.dump_objective = objective

    def dump_model(self):
        return {"objective": self.dump_objective}


class ModelArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.model = self.root / "model.txt"
        self.model.write_bytes(b"test native artifact bytes")
        self.digest = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.manifest = {
            "schema_version": 1, "model_id": "approved-demo", "target": "strong",
            "prediction_horizon_seconds": .75, "features": list(FEATURE_NAMES),
            "medians": {name: 0.0 for name in FEATURE_NAMES}, "threshold": .83,
            "confirmation_points": 2, "decision_interval_seconds": .05,
            "max_decision_gap_seconds": .1,
            "recovery_policy": "joint_ball_inward_and_clearance_gain_v1",
            "approved_for_experimental_runtime": True, "model_file": "model.txt",
            "model_sha256": self.digest,
        }
        self.path = self.root / "manifest.json"
        self.write_manifest()
        self.booster = FakeBooster()

    def tearDown(self):
        self.tmp.cleanup()

    def write_manifest(self, raw=None):
        self.path.write_text(raw if raw is not None else json.dumps(self.manifest), encoding="utf-8")

    def load(self, *, allow=True, factory=None):
        return ModelArtifact.load(self.path, expected_model_sha256=self.digest,
                                  allow_experimental=allow,
                                  booster_factory=factory or (lambda _path: self.booster))

    def valid_features(self):
        result = {name: 1.0 for name in FEATURE_NAMES}
        result.update(ready=True, directional_edge_distance=2.0, clearance=1.0,
                      radial_outward_velocity=.1, ball_radius=.5, platform_radius=3.0)
        return result

    def test_load_and_predict_with_fixed_median_imputation(self):
        artifact = self.load()
        features = self.valid_features()
        features["inward_displacement_0_2s"] = float("nan")
        self.assertEqual(artifact.predict_probability(features), .7)
        self.assertIsInstance(self.booster.rows, np.ndarray)
        self.assertEqual(self.booster.rows.shape, (1, 24))
        self.assertEqual(self.booster.rows.dtype, np.float64)
        self.assertEqual(self.booster.rows[0][FEATURE_NAMES.index("inward_displacement_0_2s")], 0.0)
        self.assertEqual(artifact.threshold, .83)
        self.assertEqual(artifact.model_id, "approved-demo")
        self.assertEqual(artifact.sha256, self.digest)
        self.assertEqual(artifact.model_sha256, self.digest)
        self.assertEqual(artifact.decision_interval_seconds, .05)
        self.assertEqual(artifact.max_decision_gap_seconds, .1)
        self.assertIsInstance(artifact.config, MappingProxyType)
        with self.assertRaises(TypeError):
            artifact.config["threshold"] = .1

    def test_rejects_duplicate_keys_and_json_nan(self):
        self.write_manifest('{"a":1,"a":2}')
        with self.assertRaisesRegex(ArtifactError, "duplicate"):
            self.load()
        self.write_manifest('{"value":NaN}')
        with self.assertRaises(ArtifactError):
            self.load()

    def test_rejects_schema_feature_order_and_threshold(self):
        self.manifest["features"][0], self.manifest["features"][1] = self.manifest["features"][1], self.manifest["features"][0]
        self.write_manifest()
        with self.assertRaisesRegex(ArtifactError, "features"):
            self.load()
        self.manifest["features"] = list(FEATURE_NAMES)
        self.manifest["threshold"] = "auto"
        self.write_manifest()
        with self.assertRaisesRegex(ArtifactError, "threshold"):
            self.load()

    def test_rejects_path_traversal_and_symlink_escape(self):
        self.manifest["model_file"] = "../outside.txt"
        self.write_manifest()
        with self.assertRaises(ArtifactError):
            self.load()
        outside = self.root.parent / (self.root.name + "-outside.txt")
        outside.write_bytes(b"test native artifact bytes")
        link = self.root / "outside-link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            outside.unlink(missing_ok=True)
            self.skipTest("symlinks unavailable")
        self.manifest["model_file"] = link.name
        self.write_manifest()
        with self.assertRaisesRegex(ArtifactError, "outside"):
            self.load()
        outside.unlink(missing_ok=True)

    def test_rejects_untrusted_or_mismatched_hash(self):
        with self.assertRaises(ArtifactError):
            ModelArtifact.load(self.path, expected_model_sha256="", allow_experimental=True)
        with self.assertRaisesRegex(ArtifactError, "caller-pinned"):
            ModelArtifact.load(self.path, expected_model_sha256="0" * 64, allow_experimental=True)
        self.model.write_bytes(b"tampered")
        with self.assertRaisesRegex(ArtifactError, "bytes"):
            self.load()

    def test_approval_requires_both_authorities(self):
        with self.assertRaisesRegex(ArtifactError, "allow_experimental"):
            self.load(allow=False)
        self.manifest["approved_for_experimental_runtime"] = False
        self.write_manifest()
        with self.assertRaises(ArtifactError):
            self.load()

    def test_rejects_incompatible_booster(self):
        with self.assertRaisesRegex(ArtifactError, "objective"):
            self.load(factory=lambda _: FakeBooster("regression"))
        with self.assertRaisesRegex(ArtifactError, "feature"):
            self.load(factory=lambda _: FakeBooster(names=list(FEATURE_NAMES[:-1])))
        with self.assertRaisesRegex(ArtifactError, "objective"):
            self.load(factory=lambda _: _ObjectiveBooster("binary_logloss"))

    def test_rehashes_artifact_after_booster_loading(self):
        def replace_after_load(_filename):
            self.model.write_bytes(b"replaced during load")
            return self.booster
        with self.assertRaisesRegex(ArtifactError, "changed during"):
            self.load(factory=replace_after_load)

    def test_native_lightgbm_test_fixture_load_and_predict(self):
        try:
            import lightgbm as lgb
        except ImportError:
            self.skipTest("LightGBM is not installed")

        # This is deliberately synthetic test data and a disposable fixture model.
        x = np.asarray([[float(i + j) for j in range(len(FEATURE_NAMES))]
                        for i in range(8)], dtype=np.float64)
        y = np.asarray([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.int32)
        dataset = lgb.Dataset(x, label=y, feature_name=list(FEATURE_NAMES), free_raw_data=False)
        booster = lgb.train({"objective": "binary", "verbosity": -1, "num_threads": 1},
                            dataset, num_boost_round=2)
        self.model = self.root / "TEST_FIXTURE_ONLY.txt"
        booster.save_model(str(self.model))
        self.digest = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.manifest.update(model_id="TEST_FIXTURE_ONLY", model_file=self.model.name,
                             model_sha256=self.digest)
        self.write_manifest()

        artifact = ModelArtifact.load(self.path, expected_model_sha256=self.digest,
                                      allow_experimental=True)
        self.assertEqual(artifact.model_id, "TEST_FIXTURE_ONLY")
        features = self.valid_features()
        probability = artifact.predict_probability(features)
        self.assertTrue(math.isfinite(probability))
        self.assertGreaterEqual(probability, 0.0)
        self.assertLessEqual(probability, 1.0)

    def test_geometry_required_and_unsafe_or_invalid_geometry_rejected(self):
        artifact = self.load()
        features = self.valid_features()
        del features["clearance"]
        with self.assertRaisesRegex(ArtifactError, "missing"):
            artifact.predict_probability(features)
        features = self.valid_features()
        features["clearance"] = 0
        with self.assertRaisesRegex(ArtifactError, "clearance"):
            artifact.predict_probability(features)
        features = self.valid_features()
        features["ball_radius"] = 0
        with self.assertRaisesRegex(ArtifactError, "radii"):
            artifact.predict_probability(features)

    def test_rejects_nonfinite_prediction(self):
        self.booster.prediction = float("nan")
        with self.assertRaisesRegex(ArtifactError, "probability"):
            self.load().predict_probability(self.valid_features())


if __name__ == "__main__":
    unittest.main()
