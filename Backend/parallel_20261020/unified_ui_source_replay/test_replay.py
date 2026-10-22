import unittest

import replay


class ProjectionTests(unittest.TestCase):
    def test_local_source_requires_true_and_running_for_candidate(self):
        self.assertIn("candidate", replay.local_projection(True, "running"))
        self.assertIn("no local", replay.local_projection(False, "running"))
        self.assertIn("unknown", replay.local_projection(True, ""))

    def test_missing_boolean_is_not_false(self):
        self.assertIsNone(replay.parse_bool(""))
        self.assertIsNone(replay.parse_bool(None))
        self.assertIsNone(replay.parse_bool("nan"))

    def test_explicit_boolean_parsing(self):
        self.assertIs(replay.parse_bool("True"), True)
        self.assertIs(replay.parse_bool("False"), False)

    def test_contiguous_source_segments(self):
        self.assertEqual(replay.segment_count([True, True, False, True, False, True, True]), 3)
        self.assertEqual(replay.segment_count([]), 0)

    def test_source_only_labels_never_claim_render(self):
        self.assertEqual(replay.local_projection(None, "running"), "unknown: missing local source or run context")

    def test_identity_check_catches_platform_or_version_mismatch(self):
        observed = {"platform_id": "12", "geometry_version_id": "v1", "timestamp": "1.0000001"}
        expected = {"platform": "13", "version": "v1", "source_timestamp": "1.0"}
        self.assertEqual(replay.identity_mismatches(observed, expected, (
            ("platform_id", "platform"), ("geometry_version_id", "version"),
            ("timestamp", "source_timestamp"))), ["platform_id!=platform"])

    def test_duplicate_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate sample key"):
            replay.unique_index([{"id": "x"}, {"id": "x"}], lambda row: (row["id"],), "sample")


if __name__ == "__main__":
    unittest.main()
