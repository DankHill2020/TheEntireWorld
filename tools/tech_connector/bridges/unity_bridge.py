"""Direct Unity socket bridge."""

import base64
import json
import os
import socket

from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.models.constants import APP_DIR, TOOLS_ROOT


class UnityBridge:
    """Deterministic Unity communication via a small in-Unity Editor socket server."""

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

    def find_port(self, host="127.0.0.1"):
        candidates = []

        env_port = os.environ.get("UNITY_COMMAND_PORT")
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
                    s.settimeout(0.25)
                    if s.connect_ex((host, port)) == 0:
                        return port
            except Exception:
                pass

        return None

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        port = self.find_port()
        if not port:
            return False, "No Unity bridge found. Run Install_Unity_AI_Studio_Bridge.bat once, then restart Unity."

        try:
            payload = json.dumps({"code": code}).encode("utf-8") + b"\n"

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("127.0.0.1", port))
                s.sendall(payload)

                chunks = []
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    chunks.append(data.decode("utf-8", errors="replace"))
                    if "\n" in chunks[-1]:
                        break

            raw = "".join(chunks).strip()
            if not raw:
                return True, "Unity returned no output."

            try:
                parsed = json.loads(raw)
                result = parsed.get("result") or parsed.get("error") or raw
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, str(result).strip() or "Unity returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def get_selection_code(self) -> str:
        return "Selection.activeGameObject != null ? Selection.activeGameObject.name : \"No Selection\""

    def get_current_file_code(self) -> str:
        return "EditorSceneManager.GetActiveScene().path"

    def get_scene_objects_code(self) -> str:
        return "string.Join(\", \", Array.ConvertAll(GameObject.FindObjectsOfType<GameObject>(), go => go.name))"
