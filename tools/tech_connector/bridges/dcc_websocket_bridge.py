"""Lightweight WebSocket client implementation for DCC integrations using raw sockets.

Guarantees 100% compatibility with standard HTTP and falls back automatically if WebSocket mode
is disabled or if the DCC tool is only running the HTTP REST server.
"""

import base64
import hashlib
import json
import os
import socket
import struct
from typing import Any, Dict, Optional


class DccWebSocketClient:
    """Raw RFC-6455 WebSocket client to execute commands inside DCCs with streaming feedback."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None

    def connect(self, path: str = "/ws", timeout: float = 3.0) -> bool:
        """Connect to WebSocket endpoint and perform handshake."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect((self.host, self.port))

            # Send Handshake
            key = base64.b64encode(os.urandom(16)).decode("utf-8")
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            self.sock.sendall(handshake.encode("utf-8"))

            # Read Handshake Response
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                resp += chunk

            if b"101 Switching Protocols" in resp:
                return True
        except Exception:
            pass

        self.close()
        return False

    def send_text(self, text: str):
        """Send a masked WebSocket text frame."""
        if not self.sock:
            return

        payload = text.encode("utf-8")
        payload_len = len(payload)

        # Build header
        header = bytearray([0x81])  # FIN=1, Opcode=1 (Text)
        
        # Mask bit is 1 (always for client to server frames)
        if payload_len <= 125:
            header.append(0x80 | payload_len)
        elif payload_len <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", payload_len))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", payload_len))

        # Generate a random 4-byte mask key
        mask_key = os.urandom(4)
        header.extend(mask_key)

        # Mask the payload
        masked_payload = bytearray(
            payload[i] ^ mask_key[i % 4] for i in range(payload_len)
        )

        self.sock.sendall(header + masked_payload)

    def receive_frame(self) -> Optional[str]:
        """Read and parse next WebSocket text frame."""
        if not self.sock:
            return None

        try:
            # Read first 2 bytes
            head = self.sock.recv(2)
            if len(head) < 2:
                return None

            byte1, byte2 = head[0], head[1]
            opcode = byte1 & 0x0F
            is_masked = bool(byte2 & 0x80)
            length = byte2 & 0x7F

            if opcode == 0x08:  # Connection Close
                return None

            if length == 126:
                length_bytes = self.sock.recv(2)
                length = struct.unpack("!H", length_bytes)[0]
            elif length == 127:
                length_bytes = self.sock.recv(8)
                length = struct.unpack("!Q", length_bytes)[0]

            if is_masked:
                mask_key = self.sock.recv(4)

            # Read payload
            payload = b""
            while len(payload) < length:
                chunk = self.sock.recv(length - len(payload))
                if not chunk:
                    break
                payload += chunk

            if is_masked:
                payload = bytearray(
                    payload[i] ^ mask_key[i % 4] for i in range(length)
                )

            return payload.decode("utf-8", errors="replace")
        except Exception:
            return None

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


def execute_via_websocket_if_enabled(
    host: str,
    port: int,
    action_dict: dict[str, Any],
    fallback_fn: Any
) -> dict[str, Any]:
    """Execute command over WebSockets if the server is available, else fallback to standard HTTP."""
    from tech_connector.services.settings_service import load_settings
    settings = load_settings()

    # WebSockets can be enabled/disabled via settings checkbox
    use_websocket = settings.get("use_websocket_bridge", False)
    if not use_websocket:
        return fallback_fn()

    client = DccWebSocketClient(host, port)
    if client.connect(timeout=2.0):
        try:
            # Send execution payload
            client.send_text(json.dumps(action_dict))
            
            # Wait for execution feedback
            resp = client.receive_frame()
            if resp:
                data = json.loads(resp)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        finally:
            client.close()

    # Automatic fallback to standard HTTP execution in case of WebSocket failures
    return fallback_fn()
