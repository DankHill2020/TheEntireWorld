"""Direct MotionBuilder socket bridge."""

import base64
import json
import os
import socket
from pathlib import Path
from typing import Optional
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo, call_python_function_via_execute
from tech_connector.models.constants import APP_DIR, APP_ROOT, TOOLS_ROOT


# ---------------------------------------------------------------------------
# Embedded server code (executed inside MotionBuilder via Python console or
# startup script).  Provides a socket server that accepts base64-encoded
# Python, executes it on the MotionBuilder main thread, and returns JSON.
# ---------------------------------------------------------------------------

PLUGIN_FILENAME = "the_entire_world_ai_studio_mobu_bridge.py"

PLUGIN_SOURCE_CODE = '''"""The Entire World Tech Connector — MotionBuilder socket bridge."""
import base64
import contextlib
import io
import json
import os
import queue
import socket
import threading
import traceback

try:
    from pyfbsdk import FBSystem, FBPlayerControl
except Exception:
    FBSystem = None
    FBPlayerControl = None

HOST = "127.0.0.1"
PORT = int(os.environ.get("MOTIONBUILDER_COMMAND_PORT", "7011"))
_jobs = queue.Queue()
_server_thread = None
_server_stop = threading.Event()
_server_started = False


def _port_files():
    files = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        from pathlib import Path
        files.append(Path(local_app_data) / "TA_AI_Studio_MCPHost" / "motionbuilder_port.txt")
    from pathlib import Path
    tools_root = Path(os.environ["TOOLSROOT"]).expanduser() if os.environ.get("TOOLSROOT") else Path(__file__).resolve().parents[3] if "__file__" in globals() else Path.cwd()
    if not tools_root.exists():
        tools_root = Path.cwd()
    files.append(tools_root / "motionbuilder_port.txt")
    return files


def _write_port_files(port):
    for path in _port_files():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(port), encoding="utf-8")
        except Exception:
            pass


def _execute_code(code):
    stream = io.StringIO()
    namespace = {"__name__": "__motionbuilder_bridge__"}
    try:
        import pyfbsdk
        namespace["pyfbsdk"] = pyfbsdk
        namespace["FBSystem"] = pyfbsdk.FBSystem
    except Exception:
        pass

    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            exec(code, namespace, namespace)
        output = stream.getvalue().strip()
        return {"ok": True, "result": output or "MotionBuilder executed successfully."}
    except Exception:
        output = stream.getvalue()
        output += traceback.format_exc()
        return {"ok": False, "error": output.strip()}


def _process_jobs():
    while not _jobs.empty():
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        code, done = job
        job.append(_execute_code(code))
        done.set()


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
                response = {"ok": False, "error": "Timed out waiting for MotionBuilder main thread."}
            else:
                response = job[-1]
        except Exception:
            response = {"ok": False, "error": traceback.format_exc()}

        conn.sendall((json.dumps(response, default=str) + "\\n").encode("utf-8"))


def _server():
    global _server_started
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((HOST, PORT))
            sock.listen(16)
            sock.settimeout(0.25)
            _write_port_files(PORT)
            _server_started = True
            print("The Entire World AI MotionBuilder bridge running on %s:%s" % (HOST, PORT))

            while not _server_stop.is_set():
                try:
                    conn, _addr = sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()
    except Exception:
        _server_started = False
        print("The Entire World AI MotionBuilder bridge failed:")
        traceback.print_exc()


def _tick_callback():
    """Called by FBSystem timer to drain the job queue on the main thread."""
    _process_jobs()


def start_bridge():
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        print("The Entire World AI MotionBuilder bridge is already running on %s:%s" % (HOST, PORT))
        return

    _server_stop.clear()

    try:
        from pyfbsdk_additions import FBCreateUniqueTool
        # Install a UI idle callback if the FBSystem timer approach is available
        import pyfbsdk
        pyfbsdk.FBSystem().OnUIIdle.Add(_tick_callback)
    except Exception:
        pass

    _server_thread = threading.Thread(target=_server, daemon=True)
    _server_thread.start()


def stop_bridge():
    _server_stop.set()
    try:
        import pyfbsdk
        pyfbsdk.FBSystem().OnUIIdle.Remove(_tick_callback)
    except Exception:
        pass


start_bridge()
'''


def start_plugin_immediately():
    exec(PLUGIN_SOURCE_CODE, globals(), globals())
    if "start_bridge" in globals():
        globals()["start_bridge"]()


# ---------------------------------------------------------------------------
# Install helpers (startup script location)
# ---------------------------------------------------------------------------

def startup_script_candidates() -> list[Path]:
    base = Path(os.environ.get("USERPROFILE", ""))
    return [
        base / "Documents" / "MB" / "2024" / "config" / "PythonStartup",
        base / "Documents" / "MB" / "2022" / "config" / "PythonStartup",
        base / "Documents" / "MotionBuilder 2024" / "config" / "PythonStartup",
        base / "Documents" / "MotionBuilder 2022" / "config" / "PythonStartup",
        base / "Documents" / "MotionBuilder 2020" / "config" / "PythonStartup",
    ]


def default_startup_dir() -> Path:
    for path in startup_script_candidates():
        if path.exists():
            return path
    return startup_script_candidates()[0]


def plugin_needs_install(startup_dir: Path) -> bool:
    target = Path(startup_dir) / PLUGIN_FILENAME
    if not target.exists():
        return True
    try:
        return target.read_text(encoding="utf-8") != PLUGIN_SOURCE_CODE
    except Exception:
        return True


def install_to_startup_dir(startup_dir: Path, dry_run: bool = False) -> Path:
    startup_dir = Path(startup_dir)
    target = startup_dir / PLUGIN_FILENAME
    if not dry_run:
        startup_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(PLUGIN_SOURCE_CODE, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------

from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


class MotionBuilderBridge(DCCBridgeDelegateMixin):
    """MotionBuilder direct socket bridge — matches Blender/Substance pattern."""

    def __init__(self):
        self.init_delegate("motionbuilder")

    info = HostBridgeInfo(
        id="motionbuilder",
        display_name="MotionBuilder",
        protocol="socket-json",
        default_port=7011,
        setup_script="bridges/motionbuilder/motionbuilder_bridge.py",
        supports_direct_execute=True,
        supports_mcp=False,
    )
    PORT_FILES = [
        str(APP_DIR / "motionbuilder_port.txt"),
        str(TOOLS_ROOT / "motionbuilder_port.txt"),
    ]
    DEFAULT_PORT = 7011
    SYS_PATHS = [
        str(TOOLS_ROOT),
        str(APP_ROOT),
    ]

    def find_port(self, host: str = "127.0.0.1") -> Optional[int]:
        candidates = []

        for pfile in self.PORT_FILES:
            if os.path.exists(pfile):
                try:
                    with open(pfile, "r") as f:
                        candidates.append(int(f.read().strip()))
                except Exception:
                    pass

        env_port = os.environ.get("MOTIONBUILDER_COMMAND_PORT")
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
            return (
                False,
                "No MotionBuilder bridge found. Run the startup bridge setup, then restart MotionBuilder.",
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
                return True, "MotionBuilder returned no output."

            try:
                parsed = json.loads(raw)
                result = parsed.get("result") or parsed.get("error") or raw
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, str(result).strip() or "MotionBuilder returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, str]:
        return call_python_function_via_execute(self, function_path, args, kwargs, self.SYS_PATHS)

    def get_selection_code(self) -> str:
        return (
            "import pyfbsdk\n"
            "models = pyfbsdk.FBModelList()\n"
            "pyfbsdk.FBGetSelectedModels(models)\n"
            "print([m.LongName or m.Name for m in models][:200])"
        )

    def get_current_file_code(self) -> str:
        return "import pyfbsdk\nprint(pyfbsdk.FBApplication().FBXFileName)"

    def get_scene_objects_code(self) -> str:
        return (
            "import pyfbsdk\n"
            "scene = pyfbsdk.FBSystem().Scene\n"
            "print([c.Name for c in scene.Components][:200])"
        )

    def get_scene_snapshot_code(
        self,
        *,
        selected_only: bool = False,
        include_geometry: bool = False,
        limit: int = 500,
        **_kwargs,
    ) -> str:
        from tech_connector.services.dcc.scene_snapshot_provider import motionbuilder_scene_snapshot_code

        return motionbuilder_scene_snapshot_code(selected_only=selected_only, limit=limit)

    def get_scene_snapshot(
        self,
        *,
        selected_only: bool = False,
        include_geometry: bool = False,
        limit: int = 500,
        timeout: float = 10.0,
        **_kwargs,
    ) -> tuple:
        from tech_connector.services.dcc.scene_snapshot_provider import parse_scene_snapshot_output

        ok, raw = self.execute(
            self.get_scene_snapshot_code(
                selected_only=selected_only,
                include_geometry=include_geometry,
                limit=limit,
            ),
            timeout=timeout,
        )
        if not ok:
            return False, raw
        return parse_scene_snapshot_output(raw, "motionbuilder")

    def get_takes_code(self) -> str:
        return (
            "import pyfbsdk\n"
            "system = pyfbsdk.FBSystem()\n"
            "print([t.Name for t in system.Scene.Takes])"
        )

    def get_characters_code(self) -> str:
        return (
            "import pyfbsdk\n"
            "system = pyfbsdk.FBSystem()\n"
            "chars = []\n"
            "for c in system.Scene.Components:\n"
            "    if isinstance(c, pyfbsdk.FBCharacter):\n"
            "        chars.append({'name': c.Name, 'characterized': bool(c.GetCharacterize())})\n"
            "print(chars)"
        )

    def parse_input(self, text: str):
        if text.startswith("{"):
            try:
                return "function", json.loads(text)
            except Exception:
                pass
        return "execute", None

    # ------------------------------------------------------------------
    # Legacy MCP prompt helpers (kept for backwards compatibility)
    # ------------------------------------------------------------------

    def mcp_selection_prompt(self) -> str:
        return "Call motionbuilder__motionbuilder_selection and show the raw response."

    def mcp_takes_prompt(self) -> str:
        return "Call motionbuilder__motionbuilder_takes and show the raw response."

    def mcp_execute_prompt(self, code: str) -> str:
        return f"Call motionbuilder__motionbuilder_execute_python with code {code!r} and show the raw response."
