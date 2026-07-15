"""Direct Blender socket bridge."""

import base64
import json
import os
import socket
import shutil
from pathlib import Path
from bridges.host_bridge import HostBridgeInfo
from models.constants import APP_ROOT, TOOLS_ROOT


ADDON_MODULE = "the_entire_world_ai_studio_bridge"
ADDON_FILENAME = ADDON_MODULE + ".py"
STARTUP_FILENAME = "the_entire_world_ai_studio_bridge_startup.py"

ADDON_SOURCE_CODE = """\"\"\"Blender add-on for The Entire World Tech Connector direct bridge.

Install this file into Blender's user add-ons folder, then enable it or let the
repo installer create the startup hook. The bridge listens on localhost only.
\"\"\"

bl_info = {
    "name": "The Entire World Tech Connector Bridge",
    "author": "The Entire World Tech Connector",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Tech Connector",
    "description": "Local socket bridge for direct Tech Connector scene commands.",
    "category": "System",
}

import base64
import contextlib
import io
import json
import os
import queue
import socket
import threading
import traceback
from pathlib import Path

import bpy


HOST = "127.0.0.1"
PORT = int(os.environ.get("BLENDER_COMMAND_PORT", "7021"))
_BRIDGE_KEY = "the_entire_world_ai_blender_bridge_started"
_STATUS_KEY = "the_entire_world_ai_blender_bridge_status"

_jobs = queue.Queue()
_server_thread = None
_server_stop = threading.Event()
_classes_registered = False


def _write_port_files(port):
    pass


def _set_status(message):
    bpy.app.driver_namespace[_STATUS_KEY] = message
    print(message)


def _execute_code(code):
    stream = io.StringIO()
    namespace = {"__name__": "__blender_bridge__", "bpy": bpy}
    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            exec(code, namespace, namespace)
        output = stream.getvalue().strip()
        return {"ok": True, "result": output or "Blender executed successfully."}
    except Exception:
        output = stream.getvalue()
        output += traceback.format_exc()
        return {"ok": False, "error": output.strip()}


def _process_jobs():
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break

        code, done = job
        job.append(_execute_code(code))
        done.set()

    return 0.05


def _handle_client(conn):
    with conn:
        try:
            raw = b""
            while b"\\n" not in raw:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                raw += chunk

            payload = json.loads(raw.decode("utf-8", errors="replace").strip())
            code = base64.b64decode(payload["code_b64"]).decode("utf-8", errors="replace")
            done = threading.Event()
            job = [code, done]
            _jobs.put(job)

            if not done.wait(30):
                response = {"ok": False, "error": "Timed out waiting for Blender main thread."}
            else:
                response = job[-1]
        except Exception:
            response = {"ok": False, "error": traceback.format_exc()}

        conn.sendall((json.dumps(response, default=str) + "\\n").encode("utf-8"))


def _server():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((HOST, PORT))
            sock.listen(16)
            sock.settimeout(0.25)
            _write_port_files(PORT)
            _set_status("The Entire World AI Blender bridge running on %s:%s" % (HOST, PORT))

            while not _server_stop.is_set():
                try:
                    conn, _addr = sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()
    except Exception:
        bpy.app.driver_namespace[_BRIDGE_KEY] = False
        _set_status("The Entire World AI Blender bridge failed:\\n%s" % traceback.format_exc())


def start_blender_bridge():
    global _server_thread
    if bpy.app.driver_namespace.get(_BRIDGE_KEY):
        _set_status("The Entire World AI Blender bridge is already running on %s:%s" % (HOST, PORT))
        return

    _server_stop.clear()
    if not bpy.app.timers.is_registered(_process_jobs):
        bpy.app.timers.register(_process_jobs, persistent=True)

    _server_thread = threading.Thread(target=_server, daemon=True)
    _server_thread.start()
    bpy.app.driver_namespace[_BRIDGE_KEY] = True


def stop_blender_bridge():
    _server_stop.set()
    bpy.app.driver_namespace[_BRIDGE_KEY] = False
    try:
        if bpy.app.timers.is_registered(_process_jobs):
            bpy.app.timers.unregister(_process_jobs)
    except Exception:
        pass


class AI_STUDIO_OT_start_bridge(bpy.types.Operator):
    bl_idname = "ai_studio.start_bridge"
    bl_label = "Start Tech Connector Bridge"

    def execute(self, context):
        start_blender_bridge()
        self.report({"INFO"}, "Tech Connector bridge started.")
        return {"FINISHED"}


class AI_STUDIO_PT_bridge(bpy.types.Panel):
    bl_label = "Tech Connector Bridge"
    bl_idname = "AI_STUDIO_PT_bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tech Connector"

    def draw(self, context):
        layout = self.layout
        running = bool(bpy.app.driver_namespace.get(_BRIDGE_KEY))
        status = bpy.app.driver_namespace.get(_STATUS_KEY) or "Bridge not started."
        layout.label(text="Running on %s:%s" % (HOST, PORT) if running else "Not running")
        layout.label(text=status[:120])
        layout.operator(AI_STUDIO_OT_start_bridge.bl_idname, icon="PLAY")


_CLASSES = (
    AI_STUDIO_OT_start_bridge,
    AI_STUDIO_PT_bridge,
)


def register():
    global _classes_registered
    if not _classes_registered:
        for cls in _CLASSES:
            bpy.utils.register_class(cls)
        _classes_registered = True
    start_blender_bridge()


def unregister():
    global _classes_registered
    stop_blender_bridge()
    if _classes_registered:
        for cls in reversed(_CLASSES):
            bpy.utils.unregister_class(cls)
        _classes_registered = False


if __name__ == "__main__":
    register()
"""


def start_plugin_immediately():
    exec(ADDON_SOURCE_CODE, globals(), globals())
    if "register" in globals():
        globals()["register"]()


def blender_user_root(appdata=None):
    base = Path(appdata or os.environ.get("APPDATA", ""))
    if not base:
        raise RuntimeError("APPDATA is not set; cannot find Blender user scripts.")
    return base / "Blender Foundation" / "Blender"


def discover_versions(root):
    if not root.exists():
        return []
    versions = []
    for child in root.iterdir():
        if child.is_dir() and child.name[0:1].isdigit():
            versions.append(child.name)
    return sorted(versions, key=_version_key)


def _version_key(value):
    parts = []
    for part in value.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return parts


def select_versions(root, requested=None, all_versions=False):
    versions = discover_versions(root)
    if requested:
        return [requested]
    if all_versions:
        return versions
    if versions:
        return [versions[-1]]
    return []


def install_to_version(version_root, dry_run=False):
    addon_dir = version_root / "scripts" / "addons"
    startup_dir = version_root / "scripts" / "startup"
    addon_target = addon_dir / ADDON_FILENAME
    startup_target = startup_dir / STARTUP_FILENAME

    startup_code = startup_code_for(addon_dir)

    if not dry_run:
        addon_dir.mkdir(parents=True, exist_ok=True)
        startup_dir.mkdir(parents=True, exist_ok=True)
        try:
            addon_target.write_text(ADDON_SOURCE_CODE, encoding="utf-8")
        except PermissionError:
            if not addon_target.exists():
                raise
        try:
            startup_target.write_text(startup_code, encoding="utf-8")
        except PermissionError:
            if not startup_target.exists():
                raise

    return addon_target, startup_target


def startup_code_for(addon_dir):
    return f"""# Auto-generated by The Entire World Tech Connector.
import importlib
import sys

addon_dir = r"{addon_dir}"
if addon_dir not in sys.path:
    sys.path.append(addon_dir)

module = importlib.import_module("{ADDON_MODULE}")
if hasattr(module, "register"):
    module.register()
"""


def version_needs_install(version_root):
    addon_dir = version_root / "scripts" / "addons"
    addon_target = addon_dir / ADDON_FILENAME
    startup_target = version_root / "scripts" / "startup" / STARTUP_FILENAME

    if not addon_target.exists() or not startup_target.exists():
        return True

    try:
        source = ADDON_SOURCE_CODE
        installed = addon_target.read_text(encoding="utf-8")
        startup = startup_target.read_text(encoding="utf-8")
    except Exception:
        return True

    return installed != source or startup != startup_code_for(addon_dir)


class BlenderBridge:
    """Deterministic Blender communication via a small in-Blender socket server."""

    info = HostBridgeInfo(
        id="blender",
        display_name="Blender",
        protocol="socket-json",
        default_port=7021,
        setup_script="bridges/blender/blender_bridge.py",
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
            return False, "No Blender bridge found. Re-run setup, then restart Blender."

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
                result = parsed.get("result") or parsed.get("error") or raw
                return bool(parsed.get("ok", True)), str(result).strip() or "Blender returned no output."
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
        return "import bpy\nprint([obj.name for obj in bpy.context.selected_objects])"

    def get_current_file_code(self) -> str:
        return "import bpy\nprint(bpy.data.filepath)"

    def get_scene_objects_code(self) -> str:
        return "import bpy\nprint(list(bpy.data.objects.keys())[:500])"

    def parse_input(self, text: str):
        if text.startswith("{"):
            return "function", json.loads(text)
        return "execute", None
