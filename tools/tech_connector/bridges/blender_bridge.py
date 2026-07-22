"""Direct Blender socket bridge."""

import base64
import json
import os
import socket

from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.models.constants import APP_ROOT, TOOLS_ROOT


class BlenderBridge:
    """Deterministic Blender communication via a small in-Blender socket server."""

    info = HostBridgeInfo(
        id="blender",
        display_name="Blender",
        protocol="socket-json",
        default_port=7021,
        setup_script="installers/Install_Blender_AI_Studio_Bridge.bat",
        supports_direct_execute=True,
        supports_mcp=False,
    )
    DEFAULT_PORT = 7021
    SYS_PATHS = [
        str(TOOLS_ROOT),
        str(APP_ROOT),
    ]

    def find_port(self, host="127.0.0.1"):
        candidates = []

        env_port = os.environ.get("BLENDER_COMMAND_PORT")
        if env_port:
            try:
                candidates.append(int(env_port))
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
            return False, "No Blender bridge found. Run Install_Blender_AI_Studio_Bridge.bat once, then restart Blender."

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
                return True, "Blender returned no output."

            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "ok" in parsed:
                    if not parsed.get("ok", True):
                        return False, parsed.get("error") or parsed.get("stderr") or raw
                    result = parsed.get("result")
                    return ((False, result) if bridge_output_has_error(result) else (True, result))
                result = parsed.get("result") or parsed.get("error") or raw
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, result
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, object]:
        args = args or []
        kwargs = kwargs or {}
        payload = {
            "function": function_path,
            "args": args,
            "kwargs": kwargs,
        }

        paths_repr = repr(self.SYS_PATHS)
        code = f"""
import sys, json, importlib, traceback, io
for p in {paths_repr}:
    if p not in sys.path:
        sys.path.append(p)

payload = {repr(payload)}
_stdout, _stderr = sys.stdout, sys.stderr
_out, _err = io.StringIO(), io.StringIO()
envelope = {{"ok": False, "result": None, "stdout": "", "stderr": "", "error": None}}
try:
    sys.stdout = _out
    sys.stderr = _err
    module_path, func_name = payload["function"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    module = importlib.reload(module)
    func = getattr(module, func_name)
    result = func(*payload.get("args", []), **payload.get("kwargs", {{}}))
    envelope.update({{"ok": True, "result": result}})
except Exception as exc:
    envelope.update({{"ok": False, "error": str(exc), "traceback": traceback.format_exc()}})
finally:
    envelope["stdout"] = _out.getvalue()
    envelope["stderr"] = _err.getvalue()
    sys.stdout = _stdout
    sys.stderr = _stderr
print(json.dumps(envelope, default=str))
"""
        return self.execute(code)

    def get_selection_code(self) -> str:
        return "import bpy\nprint([obj.name for obj in bpy.context.selected_objects])"

    def get_current_file_code(self) -> str:
        return "import bpy\nprint(bpy.data.filepath)"

    def get_scene_objects_code(self) -> str:
        return "import bpy\nprint(list(bpy.data.objects.keys())[:500])"

    def parse_input(self, text: str):
        if text.startswith("{"):
            return "function", json.loads(text)
        return "execute", None
