"""Direct Unreal HTTP bridge."""

import json
import os
import socket
import urllib.request

from tech_connector.models.constants import APP_DIR, TOOLS_ROOT


class UnrealBridge:
    """Deterministic Unreal communication via HTTP bridge."""

    PORT_FILES = [
        str(APP_DIR / "unreal_http_port.txt"),
        str(TOOLS_ROOT / "unreal_http_port.txt"),
    ]
    DEFAULT_PORT = 12347

    def find_port(self, host="127.0.0.1"):
        candidates = []

        env_port = os.environ.get("UNREAL_HTTP_PORT")
        if env_port:
            try:
                candidates.append(int(env_port))
            except Exception:
                pass

        for path in self.PORT_FILES:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    candidates.append(int(f.read().strip()))
            except Exception:
                pass

        candidates.append(self.DEFAULT_PORT)

        seen = set()
        for port in candidates:
            if port in seen:
                continue
            seen.add(port)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    if s.connect_ex((host, port)) == 0:
                        return port
            except Exception:
                pass

        return None

    def call(self, function_path: str, args=None, kwargs=None, timeout: float = 30) -> tuple[bool, str]:
        args = args or []
        kwargs = kwargs or {}

        port = self.find_port()
        if not port:
            return False, "Unreal HTTP bridge not found on port 12347. Start your Unreal HTTP server first."

        try:
            payload = json.dumps({
                "function": function_path,
                "args": args,
                "kwargs": kwargs,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")

            try:
                parsed = json.loads(raw)
                result = json.dumps(parsed, indent=2, default=str)
            except Exception:
                result = raw

            return True, result
        except Exception as e:
            return False, str(e)

    def parse_input(self, text: str) -> tuple[str, str, list, dict]:
        """
        Parse function path or JSON payload.
        Returns (function_path, args, kwargs).
        """
        if text.startswith("{"):
            data = json.loads(text)
            return (
                data["function"],
                data.get("args", []),
                data.get("kwargs", {}),
            )
        return text, [], {}
