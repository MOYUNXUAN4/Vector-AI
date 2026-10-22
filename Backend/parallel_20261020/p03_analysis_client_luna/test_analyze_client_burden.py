import json
import unittest

from analyze_client_burden import BACKEND, REVIEW, analyze


class P03ClientBurdenIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = json.loads((REVIEW / "client_result.json").read_text(encoding="utf-8"))
        cls.receipt = json.loads((REVIEW / "CONDITION_RECEIPT.json").read_text(encoding="utf-8"))
        cls.report = analyze(cls.client, cls.receipt, BACKEND)

    def test_exactly_six_completed_and_three_fallouts(self):
        self.assertEqual(self.report["group_counts"], {"completed_6": 6, "fallout_3": 3, "unknown": 0})

    def test_refreshes_are_not_counted_as_extra_episodes(self):
        orange = self.report["aggregate_by_channel"]["ExperimentalModelWarning"]
        # 34 ACTIVE refresh records collapse to five ACTIVE-to-REVOKED episodes.
        self.assertEqual(orange["active_records"], 34)
        self.assertEqual(orange["episodes"], 5)
        self.assertEqual(orange["mismatched_transitions"], 0)

    def test_geometry_durations_remain_unknown_without_local_clock(self):
        geometry = self.report["aggregate_by_channel"]["ExperimentalGeometryWarning"]
        self.assertEqual(geometry["episodes"], 5)
        self.assertEqual(geometry["closed_duration_count"], 0)
        self.assertEqual(geometry["unknown_duration_episodes"], 5)

    def test_tte_onset_joins_only_exact_run_and_sequence(self):
        n = 0
        for run in self.report["runs"]:
            for event in run["channels"]["purple_tte"]["episodes"]:
                join = event.get("onset_source_join")
                self.assertIsNotNone(join)
                self.assertEqual(join["run_id"], run["run_id"])
                self.assertEqual(join["input_sequence"], event["onset_input_sequence"])
                self.assertEqual(join["input_sequence"], join["csv_sequence"])
                self.assertEqual(join["source"], "unity")
                n += 1
        self.assertEqual(n, 20)


if __name__ == "__main__":
    unittest.main()
