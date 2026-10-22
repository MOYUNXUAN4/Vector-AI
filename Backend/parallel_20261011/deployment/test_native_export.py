import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lightgbm as lgb
import numpy as np

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_export", HERE / "native_export.py")
native_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native_export)


class NativeExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, feature_module, _ = native_export._contract()
        cls.features = list(feature_module.FEATURE_NAMES)
        # Eight synthetic fixture rows; no project data or frozen test set is read.
        X = np.asarray([[float((i + 1) * (j + 1) % 7) for j in range(24)] for i in range(8)])
        y = np.asarray([0, 1, 0, 1, 0, 1, 0, 1])
        cls.booster = lgb.train({"objective": "binary", "verbosity": -1, "num_leaves": 3,
                                 "min_data_in_leaf": 1, "num_threads": 1},
                                lgb.Dataset(X, label=y, feature_name=cls.features), num_boost_round=2)
        cls.medians = {name: 0.0 for name in cls.features}
        cls.provenance = {"artifact_role": "deployment_refit",
                          "training_dataset_ids": ["TEST_FIXTURE_ONLY"],
                          "development_session_ids": ["TEST_FIXTURE_ONLY"],
                          "threshold_selection_scope": "development_grouped_oof",
                          "independent_test_used": False}

    def export(self, destination, **overrides):
        args = {"model_id": "TEST_FIXTURE_ONLY", "medians": self.medians,
                "threshold": 0.73, "provenance": self.provenance}
        args.update(overrides)
        return native_export.export_native(self.booster, destination, **args)

    def test_round_trip_hashes_schema_and_prediction(self):
        with tempfile.TemporaryDirectory() as root:
            paths = self.export(Path(root) / "artifact")
            self.assertEqual(len(paths["model_sha256"]), 64)
            self.assertEqual(len(paths["manifest_sha256"]), 64)
            manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["features"], self.features)
            self.assertEqual(manifest["threshold"], 0.73)
            loaded = native_export._contract()[0].ModelArtifact.load(
                paths["manifest"], expected_model_sha256=paths["model_sha256"], allow_experimental=True)
            sample = {name: 0.0 for name in self.features}
            sample.update(directional_edge_distance=1.0, clearance=0.5,
                          ball_radius=0.5, platform_radius=1.0, ready=True)
            self.assertTrue(0 <= loaded.predict_probability(sample) <= 1)
            evidence = json.loads(Path(paths["evidence"]).read_text(encoding="utf-8"))
            self.assertTrue(evidence["experimental_only"])
            self.assertFalse(evidence["performance_validated"])
            self.assertIn("does not prove", evidence["provenance_limitation"])

    def test_rejects_wrong_feature_order_medians_threshold_and_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            wrong = dict(self.medians)
            wrong.pop(self.features[0])
            with self.assertRaises(ValueError): self.export(base / "a", medians=wrong)
            with self.assertRaises(ValueError): self.export(base / "b", threshold=float("nan"))
            bad = dict(self.provenance, independent_test_used=True)
            with self.assertRaises(ValueError): self.export(base / "c", provenance=bad)
            reversed_booster = lgb.train({"objective": "binary", "verbosity": -1},
                lgb.Dataset(np.zeros((8, 24)), label=[0,1,0,1,0,1,0,1], feature_name=list(reversed(self.features))),
                num_boost_round=1)
            with self.assertRaises(ValueError):
                native_export.export_native(reversed_booster, base / "d", model_id="x",
                    medians=self.medians, threshold=.5, provenance=self.provenance)

    def test_destination_exists_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "already-there"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError): self.export(target)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(target.iterdir()), [marker])

    def test_rejects_declared_frozen_test_dataset_ids_case_insensitively(self):
        with tempfile.TemporaryDirectory() as root:
            for dataset_id in ("TEST929", "test1001", "Test1006"):
                bad = dict(self.provenance, training_dataset_ids=[dataset_id])
                target = Path(root) / dataset_id
                with self.subTest(dataset_id=dataset_id), self.assertRaises(ValueError):
                    self.export(target, provenance=bad)
                self.assertFalse(target.exists())

    def test_load_or_public_smoke_failure_does_not_publish_package(self):
        artifact_module = native_export._contract()[0]
        with tempfile.TemporaryDirectory() as root:
            for method, error in (("load", RuntimeError("simulated loader failure")),
                                  ("predict_probability", RuntimeError("simulated smoke failure"))):
                target = Path(root) / method
                with self.subTest(method=method), patch.object(
                        artifact_module.ModelArtifact, method, side_effect=error):
                    with self.assertRaises(RuntimeError):
                        self.export(target)
                self.assertFalse(target.exists())
                self.assertEqual(list(Path(root).glob(f".{method}.staging-*")), [])


if __name__ == "__main__":
    unittest.main()
