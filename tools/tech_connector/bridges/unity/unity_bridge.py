"""Direct Unity socket bridge."""

from __future__ import annotations

import json
import socket
from typing import Any

from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.bridges.session_discovery import candidate_session_ports, discover_open_ports
from tech_connector.models.constants import APP_DIR, TOOLS_ROOT


from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


class UnityBridge(DCCBridgeDelegateMixin):
    """Deterministic Unity communication via a small in-Unity Editor socket server."""

    def __init__(self):
        self.init_delegate("unity")

    info = HostBridgeInfo(
        id="unity",
        display_name="Unity",
        protocol="socket-json",
        default_port=7041,
        setup_script="installers/Install_Unity_AI_Studio_Bridge.bat",
        supports_direct_execute=True,
        supports_mcp=False,
    )
    PORT_FILES = [
        str(APP_DIR / "unity_port.txt"),
        str(TOOLS_ROOT / "unity_port.txt"),
    ]
    DEFAULT_PORT = 7041
    MAX_PAYLOAD_BYTES = 1024 * 1024
    MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    def _candidate_ports(self) -> list[int]:
        return candidate_session_ports(
            "unity",
            port_files=self.PORT_FILES,
            environment_variable="UNITY_COMMAND_PORT",
            default_port=self.DEFAULT_PORT,
            scan_count_variable="UNITY_COMMAND_PORT_SCAN_COUNT",
        )

    def find_ports(self, host="127.0.0.1") -> list[int]:
        return discover_open_ports(self._candidate_ports(), host=host)

    def find_port(self, host="127.0.0.1"):
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        port = self.find_port()
        if not port:
            return False, "No Unity bridge found. Run Install_Unity_AI_Studio_Bridge.bat once, then restart Unity."
        return self.execute_on_port(code, port=port, timeout=timeout)

    def execute_on_port(self, code: str, *, port: int, timeout: float = 10) -> tuple[bool, str]:
        return self._send_payload({"code": code}, port=int(port), timeout=timeout)

    def execute_command(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        port: int | None = None,
        timeout: float = 120.0,
    ) -> tuple[bool, str]:
        target_port = int(port or self.find_port() or 0)
        if not target_port:
            return False, "No Unity bridge found. Install the Editor bridge in the target project."
        payload = {"command": str(command or "").strip()}
        payload.update(dict(params or {}))
        return self._send_payload(payload, port=target_port, timeout=timeout)

    @staticmethod
    def _send_payload(payload: dict[str, Any], *, port: int, timeout: float) -> tuple[bool, str]:
        try:
            encoded = json.dumps(payload).encode("utf-8") + b"\n"
            if len(encoded) > UnityBridge.MAX_PAYLOAD_BYTES:
                return False, "Unity bridge request exceeded the 1 MiB limit."

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("127.0.0.1", port))
                s.sendall(encoded)

                chunks = []
                received = 0
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    received += len(data)
                    if received > UnityBridge.MAX_RESPONSE_BYTES:
                        return False, "Unity bridge response exceeded the 8 MiB limit."
                    chunks.append(data.decode("utf-8", errors="replace"))
                    if "\n" in chunks[-1]:
                        break

            raw = "".join(chunks).strip()
            if not raw:
                return True, "Unity returned no output."

            try:
                parsed = json.loads(raw)
                result = parsed.get("result") if parsed.get("ok", True) else parsed.get("error")
                if result is None:
                    result = raw
                if isinstance(result, (dict, list)):
                    result = json.dumps(result)
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, str(result).strip() or "Unity returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Unity bridge found."}
        ok, raw = self.execute_command("session.info", port=port, timeout=timeout)
        details: dict[str, Any] = {}
        if ok:
            try:
                decoded = json.loads(raw)
                details = dict(decoded) if isinstance(decoded, dict) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                details = {"scene": str(raw or "")}
        result = {"ok": bool(ok), "port": port, **details}
        result.setdefault("scene", "")
        if not ok:
            result["error"] = str(raw)
        return result

    def sessions(self, host="127.0.0.1") -> list[dict]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def get_selection_code(self) -> str:
        return "Selection.activeGameObject != null ? Selection.activeGameObject.name : \"No Selection\""

    def get_current_file_code(self) -> str:
        return "EditorSceneManager.GetActiveScene().path"

    def get_scene_objects_code(self) -> str:
        return "string.Join(\", \", Array.ConvertAll(GameObject.FindObjectsOfType<GameObject>(), go => go.name))"

    def get_scene_snapshot_code(self, *, selected_only: bool = False, limit: int = 500, **_kwargs) -> str:
        from tech_connector.game_engine.integration.scene_snapshot_provider import unity_scene_snapshot_code

        return unity_scene_snapshot_code(selected_only=selected_only, limit=limit)

    def get_scene_snapshot(
        self,
        *,
        selected_only: bool = False,
        include_materials: bool = True,
        limit: int = 500,
        **_kwargs,
    ) -> tuple:
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output

        port = _kwargs.get("port")
        ok, raw = self.execute_command(
            "scene.snapshot",
            {
                "selected_only": bool(selected_only),
                "include_materials": bool(include_materials),
                "limit": max(1, int(limit)),
            },
            port=int(port) if port is not None else None,
        )
        if not ok:
            return False, raw
        return parse_scene_snapshot_output(raw, "unity")
