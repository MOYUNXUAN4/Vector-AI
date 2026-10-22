import csv
import json
import socket
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timesync_logger import TimeSynchronizedLogger
from udp_packet_reader import recv_json_packet


GEOMETRY_FIELDS = [
    "geometry_platform_instance_id",
    "geometry_version_id",
    "geometry_source_timestamp",
    "geometry_query_valid",
    "geometry_ownership_valid",
    "geometry_active_platform_instance_id",
    "geometry_active_version_id",
]


class TimeSyncLoggerGeometryTests(unittest.TestCase):
    def read_rows(self, logger):
        logger.close()
        with open(logger.path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            return reader.fieldnames, rows

    def test_preserves_geometry_verbatim_across_run_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = TimeSynchronizedLogger("test", temp_dir)
            payload = {
                "run_id": "run-one",
                "geometry_platform_instance_id": -17,
                "geometry_version_id": "unrecognized-version-A",
                "geometry_source_timestamp": 123.75,
                "geometry_query_valid": False,
                "geometry_ownership_valid": True,
                "geometry_active_platform_instance_id": 0,
                "geometry_active_version_id": "unrecognized-version-B",
            }
            logger.record("unity", payload, source_timestamp=123.75)
            logger.record("unity", dict(payload, run_id="run-two", geometry_query_valid=True))

            headers, rows = self.read_rows(logger)

        self.assertEqual(len(headers), len(set(headers)))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(len(row) == len(headers) for row in rows))
        self.assertEqual([row["run_id"] for row in rows], ["run-one", "run-two"])
        self.assertEqual(rows[0]["geometry_platform_instance_id"], "-17")
        self.assertEqual(rows[0]["geometry_version_id"], "unrecognized-version-A")
        self.assertEqual(rows[0]["geometry_source_timestamp"], "123.75")
        self.assertEqual(rows[0]["geometry_query_valid"], "False")
        self.assertEqual(rows[0]["geometry_ownership_valid"], "True")
        self.assertEqual(rows[0]["geometry_active_platform_instance_id"], "0")
        self.assertEqual(rows[0]["geometry_active_version_id"], "unrecognized-version-B")
        self.assertEqual(rows[1]["geometry_query_valid"], "True")

    def test_legacy_unity_wii_and_null_values_are_blank(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = TimeSynchronizedLogger("test", temp_dir)
            logger.record("unity", {"run_id": "legacy"})
            logger.record("wii", {name: "should-not-leak" for name in GEOMETRY_FIELDS})
            logger.record("unity", {name: None for name in GEOMETRY_FIELDS})
            _, rows = self.read_rows(logger)

        for row in rows:
            self.assertTrue(all(row[name] == "" for name in GEOMETRY_FIELDS))

    def test_loopback_json_to_csv_preserves_invalid_geometry_and_zero_time(self):
        payload = {
            "type": "unity_game", "run_id": "new-run", "sequence": 12,
            "timestamp": 1791398706.126,
            "geometry_platform_instance_id": 0,
            "geometry_version_id": "",
            "geometry_source_timestamp": 0.0,
            "geometry_query_valid": False,
            "geometry_ownership_valid": False,
            "geometry_active_platform_instance_id": -44,
            "geometry_active_version_id": "-44-g2",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                receiver.bind(("127.0.0.1", 0))
                receiver.settimeout(2.0)
                sender.sendto(json.dumps(payload).encode("utf-8"), receiver.getsockname())
                packet = recv_json_packet(receiver)
                self.assertIsNotNone(packet)
                logger = TimeSynchronizedLogger("test", temp_dir)
                logger.record("game", packet.payload, source_timestamp=packet.payload["timestamp"], sequence=packet.payload["sequence"])
                _, rows = self.read_rows(logger)
        self.assertEqual(rows[0]["geometry_platform_instance_id"], "0")
        self.assertEqual(rows[0]["geometry_version_id"], "")
        self.assertEqual(rows[0]["geometry_source_timestamp"], "0.0")
        self.assertEqual(rows[0]["geometry_query_valid"], "False")
        self.assertEqual(rows[0]["geometry_ownership_valid"], "False")
        self.assertEqual(rows[0]["geometry_active_platform_instance_id"], "-44")
        self.assertEqual(rows[0]["geometry_active_version_id"], "-44-g2")
        self.assertEqual(rows[0]["source_timestamp"], "1791398706.126")
        self.assertEqual(rows[0]["sequence"], "12")


if __name__ == "__main__":
    unittest.main()
