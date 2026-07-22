"""Direct Substance Painter socket bridge."""

import base64
import json
import os
import socket

from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.models.constants import APP_DIR, APP_ROOT, TOOLS_ROOT


class SubstancePainterBridge:
    """Deterministic Substance Painter communication via a plugin socket server."""

    info = HostBridgeInfo(
        id="substance_painter",
        display_name="Substance Painter",
        protocol="socket-json",
        default_port=7031,
        setup_script="installers/Install_Substance_Painter_AI_Studio_Bridge.bat",
        supports_direct_execute=True,
        supports_mcp=False,
    )
    PORT_FILES = [
        str(APP_DIR / "substance_painter_port.txt"),
        str(TOOLS_ROOT / "substance_painter_port.txt"),
    ]
    DEFAULT_PORT = 7031
    SYS_PATHS = [
        str(TOOLS_ROOT),
        str(APP_ROOT),
    ]

    def find_port(self, host="127.0.0.1"):
        candidates = []

        env_port = os.environ.get("SUBSTANCE_PAINTER_COMMAND_PORT")
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
            return (
                False,
                "No Substance Painter bridge found. Run Install_Substance_Painter_AI_Studio_Bridge.bat once, then restart Painter.",
            )

        try:
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = json.dumps({"code_b64": encoded}).encode("utf-8") + b"\n"

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
                return True, "Substance Painter returned no output."

            try:
                parsed = json.loads(raw)
                result = parsed.get("result") or parsed.get("error") or raw
                return bool(parsed.get("ok", True)), str(result).strip() or "Substance Painter returned no output."
            except Exception:
                return True, raw
        except Exception as e:
            return False, str(e)

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, str]:
        args = args or []
        kwargs = kwargs or {}
        payload = {
            "function": function_path,
            "args": args,
            "kwargs": kwargs,
        }

        paths_repr = repr(self.SYS_PATHS)
        code = f"""
import sys, importlib, traceback
for p in {paths_repr}:
    if p not in sys.path:
        sys.path.append(p)

payload = {repr(payload)}
try:
    module_path, func_name = payload["function"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    result = func(*payload.get("args", []), **payload.get("kwargs", {{}}))
    print(result)
except Exception:
    traceback.print_exc()
"""
        return self.execute(code)

    def get_selection_code(self) -> str:
        return (
            "print('Substance Painter selection is not exposed by this bridge yet. "
            "Use project or texture set presets.')"
        )

    def get_current_file_code(self) -> str:
        return """import substance_painter.project as project
print(project.file_path() if project.is_open() else 'No project open.')
"""

    def get_scene_objects_code(self) -> str:
        return """import substance_painter.textureset as textureset
print([texture_set.name() for texture_set in textureset.all_texture_sets()])
"""

    def get_project_status_code(self) -> str:
        return """import substance_painter.project as project
print({'is_open': project.is_open(), 'file_path': project.file_path() if project.is_open() else ''})
"""

    def parse_input(self, text: str):
        if text.startswith("{"):
            return "function", json.loads(text)
        return "execute", None
