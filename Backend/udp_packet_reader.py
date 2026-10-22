"""Safe, diagnosable JSON packet reads for the UDP backend."""
from __future__ import annotations

import errno
import json
import logging
import logging.handlers
import socket
from dataclasses import dataclass
from pathlib import Path


MAX_IPV4_UDP_PAYLOAD = 65507
RECEIVE_BUFFER_SIZE = 65535
_LOGGER = logging.getLogger("udp_packet_reader")


@dataclass(frozen=True)
class ReceivedPacket:
    payload: dict
    byte_count: int
    peer: tuple


def _configure_logger() -> logging.Logger:
    if not _LOGGER.handlers:
        _LOGGER.setLevel(logging.WARNING)
        _LOGGER.propagate = False
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        _LOGGER.addHandler(console)
        try:
            log_dir = Path(__file__).resolve().parent / "runtime_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            disk = logging.handlers.RotatingFileHandler(
                log_dir / "udp_packet_errors.log", maxBytes=1_000_000,
                backupCount=3, encoding="utf-8", delay=True,
            )
            disk.setFormatter(formatter)
            _LOGGER.addHandler(disk)
        except OSError as exc:
            _LOGGER.warning("stage=logging bytes=0 peer=unknown file_logging_unavailable=%s", exc)
    return _LOGGER


def _log(stage: str, byte_count: int, peer: object, exc: BaseException,
         packet: dict | None = None) -> None:
    # Only identifiers useful for correlating a packet are retained.
    identifiers = ""
    if packet:
        run_id = packet.get("run_id", packet.get("runID", packet.get("runId")))
        sequence = packet.get("sequence")
        if isinstance(run_id, (str, int)) and len(str(run_id)) <= 80:
            safe_run_id = "".join(c for c in str(run_id) if c.isalnum() or c in "_.:-")
            identifiers += f" runID={safe_run_id}"
        if isinstance(sequence, (str, int, float)):
            safe_sequence = "".join(c for c in str(sequence) if c.isalnum() or c in "_.:-")[:80]
            identifiers += f" sequence={safe_sequence}"
    _configure_logger().error(
        "stage=%s bytes=%d peer=%s%s error=%s: %s",
        stage, byte_count, peer, identifiers, type(exc).__name__, exc,
    )


def log_processing_error(packet: dict, byte_count: int, peer: object,
                         exc: BaseException) -> None:
    _log("processing", byte_count, peer, exc, packet)


def _recoverable_socket_error(exc: OSError) -> bool:
    # Windows reports a datagram larger than the receive buffer as WSAEMSGSIZE,
    # and occasionally reports a reset from a prior UDP peer as WSAECONNRESET.
    return getattr(exc, "winerror", None) in (10040, 10054) or exc.errno in (
        errno.EMSGSIZE, errno.ECONNRESET,
    )


def recv_json_packet(sock: socket.socket) -> ReceivedPacket | None:
    """Read one JSON object; return None for a logged, recoverable bad packet."""
    try:
        data, peer = sock.recvfrom(RECEIVE_BUFFER_SIZE)
    except OSError as exc:
        _log("receive", 0, "unknown", exc)
        if _recoverable_socket_error(exc):
            return None
        raise
    try:
        message = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        _log("utf8_decode", len(data), peer, exc)
        return None
    try:
        payload = json.loads(message)  # Preserve Python's existing NaN behavior.
    except (json.JSONDecodeError, ValueError) as exc:
        _log("json_decode", len(data), peer, exc)
        return None
    if not isinstance(payload, dict):
        _log("json_shape", len(data), peer, TypeError("top-level JSON value must be an object"))
        return None
    return ReceivedPacket(payload, len(data), peer)
