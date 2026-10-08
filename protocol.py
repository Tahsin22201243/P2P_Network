"""
protocol.py
Application protocol for the decentralized P2P communication/file-sharing system.

Wire format:
    [4-byte unsigned big-endian payload length][UTF-8 JSON payload]

For files:
    1. A framed JSON file_meta message is sent.
    2. Exactly file_size raw bytes immediately follow that JSON frame.
    3. The receiver reads exactly file_size bytes directly from the same TCP stream.

All JSON messages are UTF-8 encoded.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any, Dict, Optional

HEADER_SIZE = 4
MAX_JSON_PAYLOAD = 16 * 1024 * 1024  # 16 MiB safety limit
FILE_CHUNK_SIZE = 64 * 1024


class ProtocolError(Exception):
    """Raised when a peer violates the application protocol."""


class PeerDisconnected(ConnectionError):
    """Raised when the remote peer closes the TCP stream."""


def serialize_payload(payload: Dict[str, Any]) -> bytes:
    """Serialize a JSON-compatible dictionary to compact UTF-8 bytes."""
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary")

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"JSON serialization failed: {exc}") from exc


def deserialize_payload(data: bytes) -> Dict[str, Any]:
    """Deserialize UTF-8 JSON bytes into a dictionary."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Invalid JSON payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("JSON payload must be an object")

    return payload


def send_framed_message(sock: socket.socket, payload_dict: Dict[str, Any]) -> None:
    """Send one length-prefixed JSON message."""
    payload = serialize_payload(payload_dict)

    if len(payload) > 0xFFFFFFFF:
        raise ProtocolError("Payload is too large for 4-byte framing")

    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def recv_exact(sock: socket.socket, size: int) -> bytes:
    """Receive exactly `size` bytes."""
    if size < 0:
        raise ValueError("size cannot be negative")

    chunks = []
    remaining = size

    while remaining:
        try:
            chunk = sock.recv(remaining)
        except socket.timeout:
            continue
        except OSError as exc:
            raise PeerDisconnected(str(exc)) from exc

        if not chunk:
            raise PeerDisconnected("Peer closed the connection")

        chunks.append(chunk)
        remaining -= len(chunk)

    return b"".join(chunks)


def recv_framed_message(sock: socket.socket) -> Dict[str, Any]:
    """Receive one complete length-prefixed JSON message."""
    header = recv_exact(sock, HEADER_SIZE)
    payload_length = struct.unpack("!I", header)[0]

    if payload_length > MAX_JSON_PAYLOAD:
        raise ProtocolError(f"JSON payload exceeds limit: {payload_length} bytes")

    payload = recv_exact(sock, payload_length)
    return deserialize_payload(payload)


def build_hello(peer_id: str, peer_name: str, port: int) -> Dict[str, Any]:
    return {
        "type": "hello",
        "peer_id": peer_id,
        "peer_name": peer_name,
        "port": port,
    }


def build_hello_ack(peer_id: str, peer_name: str, port: int) -> Dict[str, Any]:
    return {
        "type": "hello_ack",
        "peer_id": peer_id,
        "peer_name": peer_name,
        "port": port,
    }


def build_text(
    sender_id: str,
    sender_name: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "type": "text",
        "sender_id": sender_id,
        "sender_name": sender_name,
        "message": message,
    }


def build_file_meta(
    sender_id: str,
    sender_name: str,
    filename: str,
    file_size: int,
    transfer_id: str,
    sha256: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        "type": "file_meta",
        "sender_id": sender_id,
        "sender_name": sender_name,
        "filename": filename,
        "file_size": file_size,
        "transfer_id": transfer_id,
    }
    if sha256:
        payload["sha256"] = sha256
    return payload