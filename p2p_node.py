"""
p2p_node.py
Threaded, fully decentralized P2P node.

Each node:
- owns a TCP listening socket;
- accepts incoming peers;
- can initiate outgoing TCP connections;
- maintains active peer connections;
- sends/receives framed JSON messages;
- transfers files as framed metadata followed by raw bytes;
- sends text/files directly to selected connected peers.

No central server exists.
"""

from __future__ import annotations

import hashlib
import os
import socket
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from protocol import (
    FILE_CHUNK_SIZE,
    PeerDisconnected,
    ProtocolError,
    build_file_meta,
    build_hello,
    build_hello_ack,
    build_text,
    recv_framed_message,
    recv_exact,
    send_framed_message,
)

DEFAULT_DOWNLOAD_DIR = Path(__file__).resolve().parent / "downloads"
SOCKET_TIMEOUT = 1.0
CONNECT_TIMEOUT = 5.0


class PeerConnection:
    """State associated with one live TCP connection."""

    def __init__(
        self,
        sock: socket.socket,
        peer_id: str,
        name: str,
        ip: str,
        port: int,
    ) -> None:
        self.socket = sock
        self.peer_id = peer_id
        self.name = name
        self.ip = ip
        self.port = port
        self.send_lock = threading.Lock()
        self.closed = threading.Event()

    def send_json(self, payload: Dict[str, Any]) -> None:
        with self.send_lock:
            if self.closed.is_set():
                raise ConnectionError("Peer connection is closed")
            send_framed_message(self.socket, payload)

    def send_file(
        self,
        metadata: Dict[str, Any],
        file_path: Path,
    ) -> None:
        with self.send_lock:
            if self.closed.is_set():
                raise ConnectionError("Peer connection is closed")

            send_framed_message(self.socket, metadata)

            with file_path.open("rb") as source:
                while True:
                    chunk = source.read(FILE_CHUNK_SIZE)
                    if not chunk:
                        break
                    self.socket.sendall(chunk)

    def close(self) -> None:
        if self.closed.is_set():
            return

        self.closed.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.socket.close()
        except OSError:
            pass


class P2PNode:
    """Fully decentralized P2P node."""

    def __init__(
        self,
        name: str,
        port: int,
        event_callback: Optional[Callable[[str], None]] = None,
        peers_callback: Optional[Callable[[list[dict[str, Any]]], None]] = None,
    ) -> None:
        self.name = name.strip() or "Peer"
        self.port = port
        self.peer_id = str(uuid.uuid4())

        self.download_dir = DEFAULT_DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.event_callback = event_callback
        self.peers_callback = peers_callback

        self.server_socket: Optional[socket.socket] = None
        self.running = threading.Event()
        self.server_thread: Optional[threading.Thread] = None

        self.peers: Dict[str, PeerConnection] = {}
        self.peers_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self.running.is_set():
            raise RuntimeError("Node is already running")

        self._validate_port(self.port)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(SOCKET_TIMEOUT)

        try:
            server.bind(("0.0.0.0", self.port))
            server.listen(64)
        except OSError:
            server.close()
            raise

        self.server_socket = server
        self.running.set()

        self.server_thread = threading.Thread(
            target=self._accept_loop,
            name=f"accept-{self.port}",
            daemon=True,
        )
        self.server_thread.start()

        self._log(
            f"Server started: {self.name} [{self.peer_id[:8]}] "
            f"listening on 0.0.0.0:{self.port}"
        )

    def stop(self) -> None:
        if not self.running.is_set():
            return

        self.running.clear()

        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except OSError:
                pass
            self.server_socket = None

        with self.peers_lock:
            connections = list(self.peers.values())
            self.peers.clear()

        for peer in connections:
            peer.close()

        self._publish_peers()
        self._log("Node stopped.")

    # ------------------------------------------------------------------
    # Server / connection handling
    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        while self.running.is_set():
            server = self.server_socket
            if server is None:
                break

            try:
                client_sock, address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.running.is_set():
                    self._log("Listener socket closed unexpectedly.")
                break

            client_sock.settimeout(SOCKET_TIMEOUT)

            threading.Thread(
                target=self._handle_socket,
                args=(client_sock, address, False),
                name=f"incoming-{address[0]}:{address[1]}",
                daemon=True,
            ).start()

    def connect(self, ip: str, port: int) -> None:
        if not self.running.is_set():
            raise RuntimeError("Start your server before connecting.")

        ip = ip.strip()
        self._validate_port(port)

        if not ip:
            raise ValueError("IP address cannot be empty.")

        threading.Thread(
            target=self._connect_worker,
            args=(ip, port),
            name=f"connect-{ip}:{port}",
            daemon=True,
        ).start()

    def _connect_worker(self, ip: str, port: int) -> None:
        sock: Optional[socket.socket] = None

        try:
            self._log(f"Connecting to {ip}:{port} ...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((ip, port))
            sock.settimeout(SOCKET_TIMEOUT)

            self._handle_socket(sock, (ip, port), True)
        except (OSError, ValueError) as exc:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            self._log(f"Connection to {ip}:{port} failed: {exc}")

    def _handle_socket(
        self,
        sock: socket.socket,
        address: tuple[str, int],
        outgoing: bool,
    ) -> None:
        peer: Optional[PeerConnection] = None

        try:
            local_hello = build_hello(
                self.peer_id,
                self.name,
                self.port,
            )
            send_framed_message(sock, local_hello)

            first = recv_framed_message(sock)
            first_type = first.get("type")

            if first_type not in {"hello", "hello_ack"}:
                raise ProtocolError(
                    f"Expected hello/hello_ack, received {first_type!r}"
                )

            peer = self._peer_from_handshake(sock, address, first)
            if peer is None:
                return

            send_framed_message(
                sock,
                build_hello_ack(
                    self.peer_id,
                    self.name,
                    self.port,
                ),
            )

            self._register_peer(peer)
            self._log(
                f"Connected: {peer.name} ({peer.peer_id[:8]}) "
                f"at {peer.ip}:{peer.port}"
            )

            self._receive_loop(peer)

        except (
            PeerDisconnected,
            ProtocolError,
            OSError,
            ValueError,
            ConnectionError,
        ) as exc:
            if peer is not None:
                self._remove_peer(
                    peer.peer_id,
                    f"{peer.name} disconnected: {exc}",
                )
            else:
                try:
                    sock.close()
                except OSError:
                    pass

    def _peer_from_handshake(
        self,
        sock: socket.socket,
        address: tuple[str, int],
        message: Dict[str, Any],
    ) -> Optional[PeerConnection]:
        peer_id = message.get("peer_id")
        name = message.get("peer_name")
        port = message.get("port")

        if not isinstance(peer_id, str) or not peer_id:
            raise ProtocolError("Handshake missing peer_id")

        if peer_id == self.peer_id:
            self._log("Ignored self-connection.")
            try:
                sock.close()
            except OSError:
                pass
            return None

        if not isinstance(name, str) or not name:
            raise ProtocolError("Handshake missing peer_name")

        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
        ):
            raise ProtocolError("Handshake contains invalid peer port")

        return PeerConnection(
            sock=sock,
            peer_id=peer_id,
            name=name,
            ip=address[0],
            port=port,
        )

    def _register_peer(self, peer: PeerConnection) -> None:
        old_peer: Optional[PeerConnection] = None

        with self.peers_lock:
            old_peer = self.peers.get(peer.peer_id)
            self.peers[peer.peer_id] = peer

        if old_peer is not None and old_peer is not peer:
            old_peer.close()
            self._log(
                f"Replaced an older connection to {peer.name} ({peer.peer_id[:8]})."
            )

        self._publish_peers()

    # ------------------------------------------------------------------
    # Receive / protocol dispatch
    # ------------------------------------------------------------------

    def _receive_loop(self, peer: PeerConnection) -> None:
        while self.running.is_set() and not peer.closed.is_set():
            message = recv_framed_message(peer.socket)
            self._dispatch_message(peer, message)

    def _dispatch_message(
        self,
        peer: PeerConnection,
        message: Dict[str, Any],
    ) -> None:
        message_type = message.get("type")

        if message_type == "hello":
            self._log(f"Received hello from {message.get('peer_name', peer.name)}.")
            return

        if message_type == "hello_ack":
            self._log(
                f"Handshake acknowledged by {message.get('peer_name', peer.name)}."
            )
            return

        if message_type == "text":
            sender_name = str(message.get("sender_name", peer.name))
            text = message.get("message")

            if not isinstance(text, str):
                raise ProtocolError("Text message field is invalid")

            self._log(f"Direct from {sender_name}: {text}")
            return

        if message_type == "file_meta":
            self._receive_file(peer, message)
            return

        raise ProtocolError(f"Unknown or unsupported message type: {message_type!r}")

    def _receive_file(
        self,
        peer: PeerConnection,
        metadata: Dict[str, Any],
    ) -> None:
        filename = metadata.get("filename")
        file_size = metadata.get("file_size")
        transfer_id = metadata.get("transfer_id")
        expected_sha256 = metadata.get("sha256")

        if (
            not isinstance(filename, str)
            or not filename
            or not isinstance(file_size, int)
            or isinstance(file_size, bool)
            or file_size < 0
            or not isinstance(transfer_id, str)
        ):
            raise ProtocolError("Invalid file metadata")

        safe_name = Path(filename).name
        if safe_name in {"", ".", ".."}:
            raise ProtocolError("Invalid file name")

        destination = self._unique_download_path(safe_name)
        temporary = destination.with_name(f".{destination.name}.{transfer_id}.part")

        received = 0
        digest = hashlib.sha256()

        self._log(
            f"Receiving file '{safe_name}' ({file_size:,} bytes) from {peer.name}..."
        )

        try:
            with temporary.open("wb") as output:
                remaining = file_size

                while remaining:
                    chunk_size = min(FILE_CHUNK_SIZE, remaining)
                    chunk = recv_exact(peer.socket, chunk_size)
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    remaining -= len(chunk)

            actual_sha256 = digest.hexdigest()

            if expected_sha256 and actual_sha256 != expected_sha256:
                try:
                    temporary.unlink()
                except OSError:
                    pass
                raise ProtocolError(f"SHA-256 mismatch for '{safe_name}'")

            temporary.replace(destination)

        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        self._log(
            f"File received from {peer.name}: "
            f"{destination.name} ({received:,} bytes) -> {destination.parent}"
        )

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_text(self, peer_id: str, message: str) -> None:
        message = message.strip()
        if not message:
            raise ValueError("Message cannot be empty.")

        peer = self._get_peer(peer_id)
        payload = build_text(
            self.peer_id,
            self.name,
            message,
        )
        peer.send_json(payload)
        self._log(f"Direct to {peer.name}: {message}")

    def send_file(self, peer_id: str, file_path: str | os.PathLike[str]) -> None:
        path = self._validate_file_path(file_path)
        peer = self._get_peer(peer_id)

        metadata = self._make_file_metadata(path)

        threading.Thread(
            target=self._send_file_worker,
            args=(peer, path, metadata, "Direct"),
            name=f"file-{peer.peer_id[:8]}",
            daemon=True,
        ).start()

    def _send_file_worker(
        self,
        peer: PeerConnection,
        path: Path,
        metadata: Dict[str, Any],
        label: str,
    ) -> None:
        try:
            peer.send_file(metadata, path)
            self._log(f"{label} file sent to {peer.name}: {path.name}")
        except (OSError, ConnectionError, ProtocolError) as exc:
            self._remove_peer(
                peer.peer_id,
                f"File send failed for {peer.name}: {exc}",
            )

    # ------------------------------------------------------------------
    # Peer bookkeeping
    # ------------------------------------------------------------------

    def _get_peer(self, peer_id: str) -> PeerConnection:
        with self.peers_lock:
            peer = self.peers.get(peer_id)

        if peer is None or peer.closed.is_set():
            raise ValueError("Selected peer is no longer connected.")

        return peer

    def _remove_peer(self, peer_id: str, reason: str) -> None:
        with self.peers_lock:
            peer = self.peers.pop(peer_id, None)

        if peer is not None:
            peer.close()
            self._publish_peers()
            self._log(reason)

    def get_peers(self) -> list[dict[str, Any]]:
        with self.peers_lock:
            return [
                {
                    "peer_id": peer.peer_id,
                    "name": peer.name,
                    "ip": peer.ip,
                    "port": peer.port,
                }
                for peer in self.peers.values()
                if not peer.closed.is_set()
            ]

    def _publish_peers(self) -> None:
        if self.peers_callback is not None:
            try:
                self.peers_callback(self.get_peers())
            except Exception:
                pass

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    def _make_file_metadata(self, path: Path) -> Dict[str, Any]:
        digest = hashlib.sha256()

        with path.open("rb") as source:
            while True:
                chunk = source.read(FILE_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)

        transfer_id = str(uuid.uuid4())

        return build_file_meta(
            self.peer_id,
            self.name,
            path.name,
            path.stat().st_size,
            transfer_id,
            digest.hexdigest(),
        )

    @staticmethod
    def _validate_file_path(file_path: str | os.PathLike[str]) -> Path:
        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Not a regular file: {path}")

        return path

    def _unique_download_path(self, filename: str) -> Path:
        candidate = self.download_dir / filename

        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        counter = 1

        while True:
            candidate = self.download_dir / (f"{stem} ({counter}){suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_port(port: int) -> None:
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
        ):
            raise ValueError("Port must be an integer from 1 to 65535.")

    def _log(self, message: str) -> None:
        if self.event_callback is not None:
            try:
                self.event_callback(message)
            except Exception:
                pass