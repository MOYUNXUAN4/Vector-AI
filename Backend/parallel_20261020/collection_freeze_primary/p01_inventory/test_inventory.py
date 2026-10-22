import csv
import json
import tempfile
import unittest
from pathlib import Path

import inventory


class InventoryTests(unittest.TestCase):
    def make_source(self, root, name, text=None):
        folder = root / name
        folder.mkdir(parents=True)
        if text is not None:
            (folder / "raw.csv").write_text(text, encoding="utf-8")
        return folder

    def test_missing_raw_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            folder = self.make_source(Path(td), "session_missing")
            result = inventory.inspect_session(folder)
            self.assertEqual(result["status"], "missing_raw")
            self.assertIsNone(result["raw_rows"])

    def test_missing_columns_are_unknown_not_filled(self):
        with tempfile.TemporaryDirectory() as td:
            folder = self.make_source(Path(td), "session_sparse", "source,run_id\nunity,r1\n")
            result = inventory.inspect_session(folder)
            self.assertEqual(result["raw_rows"], 1)
            self.assertNotIn("wii_control_valid", result["distributions_by_source"]["unity"])
            self.assertIsNone(result["unity_source"]["duration_seconds"])
            self.assertIsNone(result["session_outcome_counts"])

    def test_empty_table_is_preserved_as_empty(self):
        with tempfile.TemporaryDirectory() as td:
            folder = self.make_source(Path(td), "session_empty", "source,run_id,sequence\n")
            result = inventory.inspect_session(folder)
            self.assertEqual(result["status"], "empty_table")
            self.assertEqual(result["raw_rows"], 0)
            self.assertEqual(result["run_ids"], [])

    def test_multirun_does_not_assign_terminal_to_one_run(self):
        raw = "source,source_timestamp,sequence,run_id,run_state,session_outcome\n"
        raw += "unity,1,1,a,running,\nunity,2,1,b,completed,three_layers_completed\n"
        with tempfile.TemporaryDirectory() as td:
            folder = self.make_source(Path(td), "session_multi", raw)
            result = inventory.inspect_session(folder)
            self.assertEqual(result["run_attribution"], "unknown_multirun")
            self.assertEqual(result["run_ids"], ["a", "b"])
            self.assertEqual(result["terminal_row"]["run_id"], "b")
            self.assertEqual(result["unity_source"]["duration_seconds"], 1.0)

    def test_sequence_reports_jumps_and_resets_in_source_order(self):
        raw = "source,sequence,run_id\nunity,10,r\nunity,12,r\nunity,1,r\n"
        with tempfile.TemporaryDirectory() as td:
            folder = self.make_source(Path(td), "session_sequence", raw)
            result = inventory.inspect_session(folder)
            seq = result["sequence"]["unity"]
            self.assertEqual(seq["missing_ranges"][0]["missing_start"], 11)
            self.assertEqual(seq["reset_or_backstep_count"], 1)

    def test_missing_unity_timestamp_breaks_gap_adjacency(self):
        raw = "source,source_timestamp,run_id,wii_control_valid,calibration_mode\n"
        raw += "unity,1.0,r,,true\nunity,,r,,true\nunity,2.0,r,,true\n"
        raw += "wii,1.1,r,true,\nwii,1.2,r,false,\n"
        with tempfile.TemporaryDirectory() as td:
            folder = self.make_source(Path(td), "session_missing_ts", raw)
            result = inventory.inspect_session(folder)
            u = result["unity_source"]
            self.assertEqual(u["missing_timestamp_rows"], 1)
            self.assertEqual(u["adjacent_pairs_blocked_by_missing_timestamp"], 2)
            self.assertEqual(u["gap_count_gt_0_1s"], 0)
            self.assertEqual(u["intervals_with_missing_timestamp"], "unknown")
            self.assertEqual(result["distributions_by_source"]["wii"]["wii_control_valid"], {"false": 1, "true": 1})
            self.assertNotIn("wii_control_valid", result["distributions_by_source"]["unity"])

    def test_inventory_writes_hashes_and_per_session_csv_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "source"; out = Path(td) / "out"; root.mkdir()
            self.make_source(root, "session_one", "source,run_id\nunity,r\n")
            summary = inventory.inventory(root, out)
            self.assertEqual(summary["session_count"], 1)
            rec = json.loads((out / "session_one.json").read_text(encoding="utf-8"))
            self.assertTrue(rec["source_files_unchanged"])
            self.assertTrue((out / "session_one.csv").is_file())
            with (out / "session_one.csv").open(encoding="utf-8-sig", newline="") as f:
                self.assertIn("evidence_field", next(csv.reader(f)))


if __name__ == "__main__":
    unittest.main()
