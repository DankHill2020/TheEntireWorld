from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import time
from typing import Any, Callable

from tech_connector.game_engine.runtime.tc_physics_replay_service import (
    DeterministicPhysicsRecorder, PhysicsFrame, replication_packet,
)


MAX_PACKET_BYTES = 60_000


@dataclass
class PendingPacket:
    payload: bytes
    address: tuple[str, int]
    sent_at: float
    attempts: int = 1


class PhysicsDatagramTransport:
    """Non-blocking, sequenced UDP transport suitable for rollback state and inputs."""

    def __init__(self, session_id: str, bind: tuple[str, int] = ("127.0.0.1", 0), *, retry_seconds: float = 0.08) -> None:
        if not str(session_id).strip():
            raise ValueError("Physics network session ID cannot be empty.")
        self.session_id = str(session_id)
        self.retry_seconds = max(0.01, float(retry_seconds))
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(bind)
        self.socket.setblocking(False)
        self.address = self.socket.getsockname()
        self._next_sequence = 1
        self._latest_received: dict[tuple[str, int], int] = {}
        self._pending: dict[int, PendingPacket] = {}

    def close(self) -> None:
        self.socket.close()

    def send(self, address: tuple[str, int], kind: str, payload: dict[str, Any], *, reliable: bool = True) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        envelope = {
            "schema": "tech_connector.physics_transport.v1", "session": self.session_id,
            "sequence": sequence, "ack": 0, "kind": str(kind), "reliable": bool(reliable),
            "payload": payload,
        }
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_PACKET_BYTES:
            raise ValueError("Physics replication packet exceeds the UDP payload safety limit.")
        self.socket.sendto(encoded, address)
        if reliable:
            self._pending[sequence] = PendingPacket(encoded, address, time.monotonic())
        return sequence

    def _acknowledge(self, address: tuple[str, int], sequence: int) -> None:
        encoded = json.dumps({
            "schema": "tech_connector.physics_transport.v1", "session": self.session_id,
            "sequence": 0, "ack": int(sequence), "kind": "ack", "reliable": False, "payload": {},
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.socket.sendto(encoded, address)

    def poll(self, handler: Callable[[str, dict[str, Any], tuple[str, int]], None], *, maximum_packets: int = 256) -> int:
        delivered = 0
        for _ in range(max(1, min(4096, int(maximum_packets)))):
            try:
                encoded, address = self.socket.recvfrom(MAX_PACKET_BYTES + 1)
            except BlockingIOError:
                break
            if len(encoded) > MAX_PACKET_BYTES:
                continue
            try:
                envelope = json.loads(encoded.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if envelope.get("schema") != "tech_connector.physics_transport.v1" or envelope.get("session") != self.session_id:
                continue
            acknowledgement = int(envelope.get("ack", 0) or 0)
            if acknowledgement:
                self._pending.pop(acknowledgement, None)
                continue
            sequence = int(envelope.get("sequence", 0) or 0)
            if sequence <= 0:
                continue
            if bool(envelope.get("reliable")):
                self._acknowledge(address, sequence)
            previous = self._latest_received.get(address, 0)
            if sequence <= previous:
                continue
            self._latest_received[address] = sequence
            payload = envelope.get("payload")
            if isinstance(payload, dict):
                handler(str(envelope.get("kind") or ""), payload, address)
                delivered += 1
        return delivered

    def service_retries(self, *, maximum_attempts: int = 8) -> int:
        now = time.monotonic()
        sent = 0
        for sequence, pending in list(self._pending.items()):
            if now - pending.sent_at < self.retry_seconds:
                continue
            if pending.attempts >= max(1, int(maximum_attempts)):
                del self._pending[sequence]
                continue
            self.socket.sendto(pending.payload, pending.address)
            pending.sent_at = now
            pending.attempts += 1
            sent += 1
        return sent

    @property
    def unacknowledged_count(self) -> int:
        return len(self._pending)


class PhysicsReplicationSession:
    """Connect transport delivery to deterministic frame history and rollback."""

    def __init__(self, transport: PhysicsDatagramTransport, recorder: DeterministicPhysicsRecorder | None = None) -> None:
        self.transport = transport
        self.recorder = recorder or DeterministicPhysicsRecorder()
        self.latest_authoritative_frame = -1
        self.rollback_requests: list[int] = []

    def send_frame(self, address: tuple[str, int], frame: PhysicsFrame, baseline: PhysicsFrame | None = None) -> int:
        return self.transport.send(address, "state", replication_packet(frame, baseline), reliable=True)

    def request_rollback(self, address: tuple[str, int], frame: int) -> int:
        return self.transport.send(address, "rollback", {"frame": int(frame)}, reliable=True)

    def poll(self) -> int:
        return self.transport.poll(self._receive)

    def _receive(self, kind: str, payload: dict[str, Any], _address: tuple[str, int]) -> None:
        if kind == "rollback":
            self.rollback_requests.append(int(payload.get("frame", -1)))
            return
        if kind != "state" or payload.get("schema") != "tech_connector.physics_replication.v1":
            return
        frame = int(payload.get("frame", -1))
        state = payload.get("state")
        inputs = payload.get("inputs") or ()
        if frame <= self.latest_authoritative_frame or not isinstance(state, dict) or not isinstance(inputs, list):
            return
        recorded = self.recorder.record(frame, state, inputs)
        if recorded.state_hash != str(payload.get("state_hash") or ""):
            self.recorder.frames.pop()
            raise ValueError(f"Authoritative physics frame {frame} failed its state hash.")
        self.latest_authoritative_frame = frame


__all__ = ["MAX_PACKET_BYTES", "PhysicsDatagramTransport", "PhysicsReplicationSession"]
