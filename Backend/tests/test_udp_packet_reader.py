import json
import logging
import socket
import unittest
from unittest import mock

import udp_packet_reader as reader


class UdpPacketReaderTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        class Capture(logging.Handler):
            def emit(inner_self, record):
                self.records.append(record.getMessage())
        self.handler = Capture()
        reader._LOGGER.handlers[:] = [self.handler]

    def tearDown(self):
        reader._LOGGER.handlers.clear()

    def test_loopback_accepts_payload_larger_than_4096_with_utf8(self):
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            receiver.bind(("127.0.0.1", 0))
            payload = {"command": "telemetry", "note": "平衡" + "x" * 5000}
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            sender.sendto(raw, receiver.getsockname())
            received = reader.recv_json_packet(receiver)
            self.assertEqual(received.payload, payload)
            self.assertEqual(received.byte_count, len(raw))
            self.assertEqual(received.peer[0], "127.0.0.1")
        finally:
            receiver.close()
            sender.close()

    def test_malformed_json_then_valid_packet(self):
        receiver, sender = self._sockets()
        try:
            sender.sendto(b"{broken", receiver.getsockname())
            sender.sendto(b'{"sequence": 2}', receiver.getsockname())
            self.assertIsNone(reader.recv_json_packet(receiver))
            self.assertEqual(reader.recv_json_packet(receiver).payload["sequence"], 2)
            self.assertTrue(any("stage=json_decode" in item for item in self.records))
        finally:
            receiver.close(); sender.close()

    def test_invalid_utf8_and_non_object_are_rejected(self):
        receiver, sender = self._sockets()
        try:
            sender.sendto(b'{"v":"\xff"}', receiver.getsockname())
            sender.sendto(b"[1, 2]", receiver.getsockname())
            self.assertIsNone(reader.recv_json_packet(receiver))
            self.assertIsNone(reader.recv_json_packet(receiver))
            self.assertTrue(any("stage=utf8_decode" in item for item in self.records))
            self.assertTrue(any("stage=json_shape" in item for item in self.records))
        finally:
            receiver.close(); sender.close()

    def test_nan_compatibility(self):
        receiver, sender = self._sockets()
        try:
            sender.sendto(b'{"scale": NaN}', receiver.getsockname())
            self.assertTrue(__import__("math").isnan(reader.recv_json_packet(receiver).payload["scale"]))
        finally:
            receiver.close(); sender.close()

    def test_processing_log_includes_safe_run_id_and_sequence(self):
        reader.log_processing_error(
            {"run_id": "run-17", "sequence": 897}, 4099,
            ("127.0.0.1", 54321), RuntimeError("processing failed"),
        )
        self.assertTrue(any("runID=run-17" in item and "sequence=897" in item for item in self.records))

    def test_known_socket_error_logs_and_recovers(self):
        sock = mock.Mock()
        sock.recvfrom.side_effect = OSError(10040, "message too long")
        self.assertIsNone(reader.recv_json_packet(sock))
        self.assertTrue(any("stage=receive" in item for item in self.records))

    def test_unexpected_socket_error_logs_and_raises(self):
        sock = mock.Mock()
        sock.recvfrom.side_effect = OSError(10013, "access denied")
        with self.assertRaises(OSError):
            reader.recv_json_packet(sock)
        self.assertTrue(any("stage=receive" in item for item in self.records))

    @staticmethod
    def _sockets():
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.bind(("127.0.0.1", 0))
        return receiver, sender


if __name__ == "__main__":
    unittest.main()
