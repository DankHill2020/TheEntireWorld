"""Direct Substance Painter socket bridge."""

from __future__ import annotations

import base64
import json
import os
import socket
import shutil
from pathlib import Path
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo, call_python_function_via_execute
from tech_connector.bridges.session_authorization import (
    bridge_session_token,
    embedded_bridge_authorization_source,
)
from tech_connector.bridges.session_discovery import (
    candidate_session_ports,
    discover_open_ports,
    parse_session_output,
)
from tech_connector.models.constants import APP_DIR, APP_ROOT, TOOLS_ROOT


PLUGIN_FILENAME = "the_entire_world_ai_studio_bridge.py"

PLUGIN_SOURCE_CODE = embedded_bridge_authorization_source("substance_painter") + """\"\"\"Substance Painter plugin for The Entire World Tech Connector direct bridge.\"\"\"

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


HOST = "127.0.0.1"
PORT = int(os.environ.get("SUBSTANCE_PAINTER_COMMAND_PORT", "7031"))
_jobs = queue.Queue()
_server_thread = None
_server_stop = threading.Event()
_timer = None
_actions = []
_server_started = False


def _port_files():
    files = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        files.append(Path(local_app_data) / "TA_AI_Studio_MCPHost" / "substance_painter_port.txt")
    tools_root = Path(os.environ["TOOLSROOT"]).expanduser() if os.environ.get("TOOLSROOT") else Path(__file__).resolve().parents[3] if "__file__" in globals() else Path.cwd()
    if not tools_root.exists():
        tools_root = Path.cwd()
    files.append(tools_root / "substance_painter_port.txt")
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
    namespace = {"__name__": "__substance_painter_bridge__"}
    try:
        import substance_painter

        namespace["substance_painter"] = substance_painter
    except Exception:
        pass

    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            exec(code, namespace, namespace)
        output = stream.getvalue().strip()
        return {"ok": True, "result": output or "Substance Painter executed successfully."}
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
            if not _tech_connector_bridge_authorized(payload):
                response = {
                    "ok": False,
                    "error": "Tech Connector activation is required for this DCC bridge.",
                    "code": "bridge_authorization_required",
                }
                conn.sendall((json.dumps(response) + "\\n").encode("utf-8"))
                return
            code = base64.b64decode(payload["code_b64"]).decode("utf-8", errors="replace")
            done = threading.Event()
            job = [code, done]
            _jobs.put(job)

            if not done.wait(30):
                response = {"ok": False, "error": "Timed out waiting for Substance Painter main thread."}
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
            print("The Entire World AI Substance Painter bridge running on %s:%s" % (HOST, PORT))

            while not _server_stop.is_set():
                try:
                    conn, _addr = sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()
    except Exception:
        _server_started = False
        print("The Entire World AI Substance Painter bridge failed:")
        traceback.print_exc()


def _qt_modules():
    try:
        from PySide6 import QtCore, QtWidgets

        return QtCore, QtWidgets
    except Exception:
        from PySide2 import QtCore, QtWidgets

        return QtCore, QtWidgets


def start_bridge():
    global _server_thread, _timer
    if _server_thread and _server_thread.is_alive():
        print("The Entire World AI Substance Painter bridge is already running on %s:%s" % (HOST, PORT))
        return

    QtCore, _QtWidgets = _qt_modules()
    _server_stop.clear()
    _timer = QtCore.QTimer()
    _timer.timeout.connect(_process_jobs)
    _timer.start(50)

    _server_thread = threading.Thread(target=_server, daemon=True)
    _server_thread.start()


def stop_bridge():
    global _timer
    _server_stop.set()
    if _timer is not None:
        try:
            _timer.stop()
        except Exception:
            pass
        _timer = None


def _add_menu_action():
    try:
        import substance_painter.ui

        _QtCore, QtWidgets = _qt_modules()
        action = QtWidgets.QAction("Start Tech Connector Bridge", None)
        action.triggered.connect(start_bridge)
        substance_painter.ui.add_action(substance_painter.ui.ApplicationMenu.Plugins, action)
        _actions.append(action)
    except Exception:
        pass


def _remove_menu_actions():
    try:
        import substance_painter.ui

        for action in list(_actions):
            try:
                substance_painter.ui.delete_ui_element(action)
            except Exception:
                pass
        _actions.clear()
    except Exception:
        pass


def start_plugin():
    _add_menu_action()
    start_bridge()


def close_plugin():
    stop_bridge()
    _remove_menu_actions()
"""


def start_plugin_immediately():
    exec(PLUGIN_SOURCE_CODE, globals(), globals())
    if "start_plugin" in globals():
        globals()["start_plugin"]()


def documents_root(userprofile=None):
    override = os.environ.get("SUBSTANCE_PAINTER_PLUGINS_DIR")
    if override:
        return Path(override).parent
    base = Path(userprofile or os.environ.get("USERPROFILE", ""))
    if not base:
        raise RuntimeError("USERPROFILE is not set; cannot find Documents.")
    return base / "Documents"


def plugin_dir_candidates(userprofile=None):
    override = os.environ.get("SUBSTANCE_PAINTER_PLUGINS_DIR")
    if override:
        return [Path(override)]

    docs = documents_root(userprofile)
    return [
        docs / "Adobe" / "Adobe Substance 3D Painter" / "python" / "plugins",
        docs / "Allegorithmic" / "Substance Painter" / "plugins",
    ]


def default_plugin_dir(userprofile=None):
    candidates = plugin_dir_candidates(userprofile)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def plugin_needs_install(plugin_dir):
    target = Path(plugin_dir) / PLUGIN_FILENAME
    if not target.exists():
        return True
    try:
        return target.read_text(encoding="utf-8") != PLUGIN_SOURCE_CODE
    except Exception:
        return True


def install_to_plugin_dir(plugin_dir, dry_run=False):
    plugin_dir = Path(plugin_dir)
    target = plugin_dir / PLUGIN_FILENAME
    if not dry_run:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(PLUGIN_SOURCE_CODE, encoding="utf-8")
        except PermissionError:
            if not target.exists():
                raise
    return target


from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


class SubstancePainterBridge(DCCBridgeDelegateMixin):
    """Deterministic Substance Painter communication via a plugin socket server."""

    def __init__(self):
        self.init_delegate("substance_painter")

    info = HostBridgeInfo(
        id="substance_painter",
        display_name="Substance Painter",
        protocol="socket-json",
        default_port=7031,
        setup_script="bridges/substance_painter/substance_painter_bridge.py",
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

    def _candidate_ports(self) -> list[int]:
        return candidate_session_ports(
            "substance_painter",
            port_files=self.PORT_FILES,
            environment_variable="SUBSTANCE_PAINTER_COMMAND_PORT",
            default_port=self.DEFAULT_PORT,
            scan_count_variable="SUBSTANCE_PAINTER_COMMAND_PORT_SCAN_COUNT",
        )

    def find_ports(self, host="127.0.0.1") -> list[int]:
        return discover_open_ports(self._candidate_ports(), host=host)

    def find_port(self, host="127.0.0.1"):
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        port = self.find_port()
        if not port:
            return False, "No Substance Painter bridge found. Re-run setup, then restart Substance Painter."
        return self.execute_on_port(code, port=port, timeout=timeout)

    def execute_on_port(self, code: str, *, port: int, timeout: float = 10) -> tuple[bool, str]:
        try:
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = json.dumps(
                {
                    "code_b64": encoded,
                    "bridge_session": bridge_session_token("substance_painter"),
                }
            ).encode("utf-8") + b"\n"

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
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, str(result).strip() or "Substance Painter returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Substance Painter bridge found."}
        code = """
import json
import os
import substance_painter.application
import substance_painter.project
print(json.dumps({
    "pid": os.getpid(),
    "version": str(substance_painter.application.version()),
    "scene": str(substance_painter.project.file_path() or "") if substance_painter.project.is_open() else "",
    "project_open": bool(substance_painter.project.is_open()),
}))
"""
        ok, raw = self.execute_on_port(code, port=port, timeout=timeout)
        data = parse_session_output(raw)
        data.update({"ok": bool(ok), "port": port})
        if not ok:
            data.setdefault("error", str(raw))
        return data

    def sessions(self, host="127.0.0.1") -> list[dict]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, str]:
        return call_python_function_via_execute(self, function_path, args, kwargs, self.SYS_PATHS)

    def get_current_file_code(self) -> str:
        return "import substance_painter.project\nprint(substance_painter.project.file_path())"

    def get_project_status_code(self) -> str:
        return "import substance_painter.project\nprint('open' if substance_painter.project.is_open() else 'closed')"

    def get_scene_objects_code(self) -> str:
        return "import substance_painter.textureset\nprint([ts.name() for ts in substance_painter.textureset.all_texture_sets()])"

    def get_scene_snapshot_code(self, *, include_materials: bool = True, limit: int = 500, **_kwargs) -> str:
        from tech_connector.game_engine.integration.scene_snapshot_provider import substance_painter_scene_snapshot_code

        return substance_painter_scene_snapshot_code(include_materials=include_materials, limit=limit)

    def get_scene_snapshot(
        self,
        *,
        include_materials: bool = True,
        limit: int = 500,
        timeout: float = 10.0,
        port: int | None = None,
        **_kwargs,
    ) -> tuple[bool, object]:
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output

        code = self.get_scene_snapshot_code(include_materials=include_materials, limit=limit)
        if port is None:
            ok, raw = self.execute(code, timeout=timeout)
        else:
            ok, raw = self.execute_on_port(code, port=int(port), timeout=timeout)
        if not ok:
            return False, raw
        return parse_scene_snapshot_output(str(raw).splitlines()[-1], "substance_painter")

    def parse_input(self, text: str):
        if text.startswith("{"):
            return "function", json.loads(text)
        return "execute", None
