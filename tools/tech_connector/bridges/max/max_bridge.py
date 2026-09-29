from __future__ import annotations

"""Direct, main-thread-safe 3ds Max pymxs socket bridge."""

import base64
import json
import os
import socket
from pathlib import Path
from typing import Optional

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
from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


PLUGIN_FILENAME = "tech_connector_3dsmax_bridge.py"
PLUGIN_SOURCE_CODE = embedded_bridge_authorization_source("3dsmax") + '''"""Tech Connector 3ds Max startup bridge."""
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
PORT = int(os.environ.get("MAX_COMMAND_PORT", "7091"))
_jobs = queue.Queue()
_stop = threading.Event()
_server_thread = None
_timer = None


def _port_files():
    rows = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        rows.append(Path(local) / "TA_AI_Studio_MCPHost" / "3dsmax_port.txt")
    root = Path(os.environ.get("TOOLSROOT") or Path.cwd())
    rows.append(root / "3dsmax_port.txt")
    return rows


def _write_port_files():
    for path in _port_files():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(PORT), encoding="utf-8")
        except Exception:
            pass


def _execute(code):
    stream = io.StringIO()
    namespace = {"__name__": "__tech_connector_3dsmax__"}
    try:
        import pymxs
        namespace.update({"pymxs": pymxs, "rt": pymxs.runtime})
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            exec(code, namespace, namespace)
        return {"ok": True, "result": stream.getvalue().strip() or "3ds Max executed successfully."}
    except Exception:
        return {"ok": False, "error": (stream.getvalue() + traceback.format_exc()).strip()}


def _drain_jobs():
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            return
        job.append(_execute(job[0]))
        job[1].set()


def _handle(conn):
    with conn:
        try:
            raw = b""
            while b"\\n" not in raw:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                raw += chunk
            request = json.loads(raw.decode("utf-8", errors="replace").strip())
            if not _tech_connector_bridge_authorized(request):
                response = {
                    "ok": False,
                    "error": "Tech Connector activation is required for this DCC bridge.",
                    "code": "bridge_authorization_required",
                }
                conn.sendall((json.dumps(response) + "\\n").encode("utf-8"))
                return
            code = base64.b64decode(request["code_b64"]).decode("utf-8", errors="replace")
            done = threading.Event()
            job = [code, done]
            _jobs.put(job)
            response = job[-1] if done.wait(float(request.get("timeout_seconds", 30.0))) else {"ok": False, "error": "Timed out waiting for the 3ds Max main thread."}
        except Exception:
            response = {"ok": False, "error": traceback.format_exc()}
        conn.sendall((json.dumps(response, default=str) + "\\n").encode("utf-8"))


def _serve():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(16)
        sock.settimeout(0.25)
        _write_port_files()
        while not _stop.is_set():
            try:
                conn, _address = sock.accept()
            except socket.timeout:
                continue
            threading.Thread(target=_handle, args=(conn,), daemon=True).start()


def start_bridge():
    global _server_thread, _timer
    if _server_thread and _server_thread.is_alive():
        return
    try:
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PySide2.QtCore import QTimer
        _timer = QTimer()
        _timer.timeout.connect(_drain_jobs)
        _timer.start(10)
    except Exception:
        traceback.print_exc()
        return
    _stop.clear()
    _server_thread = threading.Thread(target=_serve, daemon=True)
    _server_thread.start()


def stop_bridge():
    _stop.set()
    if _timer is not None:
        _timer.stop()


start_bridge()
'''


def startup_script_candidates() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Autodesk" / "3dsMax"
    rows = sorted(local.glob("*\\ENU\\scripts\\startup"), reverse=True) if local.exists() else []
    rows.extend([
        Path(os.environ.get("USERPROFILE", "")) / "Documents" / "3ds Max 2026" / "scripts" / "Startup",
        Path(os.environ.get("USERPROFILE", "")) / "Documents" / "3ds Max 2025" / "scripts" / "Startup",
    ])
    return rows


def default_startup_dir() -> Path:
    rows = startup_script_candidates()
    return next((path for path in rows if path.exists()), rows[0])


def install_to_startup_dir(startup_dir: Path, dry_run: bool = False) -> Path:
    target = Path(startup_dir) / PLUGIN_FILENAME
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(PLUGIN_SOURCE_CODE, encoding="utf-8")
    return target


class MaxBridge(DCCBridgeDelegateMixin):
    info = HostBridgeInfo(
        id="3dsmax",
        display_name="3ds Max",
        protocol="socket-json",
        default_port=7091,
        setup_script="bridges/max/max_bridge.py",
        supports_direct_execute=True,
        supports_mcp=False,
    )
    DEFAULT_PORT = 7091
    PORT_FILES = [str(APP_DIR / "3dsmax_port.txt"), str(TOOLS_ROOT / "3dsmax_port.txt")]
    SYS_PATHS = [str(TOOLS_ROOT), str(APP_ROOT)]

    def __init__(self):
        self.init_delegate("3dsmax")

    def find_port(self, host: str = "127.0.0.1") -> Optional[int]:
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def find_ports(self, host: str = "127.0.0.1") -> list[int]:
        candidates = candidate_session_ports(
            "3dsmax",
            port_files=self.PORT_FILES,
            environment_variable="MAX_COMMAND_PORT",
            default_port=self.DEFAULT_PORT,
            scan_count_variable="MAX_COMMAND_PORT_SCAN_COUNT",
        )
        return discover_open_ports(candidates, host=host)

    def execute_on_port(self, code: str, *, port: int, timeout: float = 10.0) -> tuple[bool, str]:
        try:
            request = {
                "code_b64": base64.b64encode(str(code).encode("utf-8")).decode("ascii"),
                "timeout_seconds": max(0.1, float(timeout) * 0.95),
                "bridge_session": bridge_session_token("3dsmax"),
            }
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                connection.settimeout(max(0.1, float(timeout)))
                connection.connect(("127.0.0.1", int(port)))
                connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
                raw = b""
                while b"\n" not in raw:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
            response = json.loads(raw.decode("utf-8", errors="replace").strip())
            result = str(response.get("result") or response.get("error") or "")
            ok = bool(response.get("ok")) and not bridge_output_has_error(result)
            return ok, result or "3ds Max returned no output."
        except Exception as exc:
            return False, str(exc)

    def execute(self, code: str, timeout: float = 10.0) -> tuple[bool, str]:
        port = self.find_port()
        if not port:
            return False, "No 3ds Max bridge found. Install the startup bridge and restart 3ds Max."
        return self.execute_on_port(code, port=port, timeout=timeout)

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No 3ds Max bridge found."}
        code = """
import json
import os
import pymxs
rt = pymxs.runtime
print(json.dumps({
    "pid": os.getpid(),
    "version": str(rt.maxVersion()),
    "scene": str(rt.maxFilePath) + str(rt.maxFileName),
    "selection": [str(node.name) for node in list(rt.selection)],
    "frame": float(rt.currentTime),
}))
"""
        ok, raw = self.execute_on_port(code, port=port, timeout=timeout)
        data = parse_session_output(raw)
        data.update({"ok": bool(ok), "port": port})
        if not ok:
            data.setdefault("error", str(raw))
        return data

    def sessions(self, host: str = "127.0.0.1") -> list[dict]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, str]:
        return call_python_function_via_execute(self, function_path, args, kwargs, self.SYS_PATHS)

    def get_selection_code(self) -> str:
        return "import pymxs\nprint([str(node.name) for node in pymxs.runtime.selection])"

    def get_current_file_code(self) -> str:
        return "import pymxs\nrt=pymxs.runtime\nprint(str(rt.maxFilePath) + str(rt.maxFileName))"

    def get_scene_objects_code(self) -> str:
        return "import pymxs\nprint([str(node.name) for node in list(pymxs.runtime.objects)[:500]])"

    def get_scene_snapshot_code(
        self,
        *,
        selected_only: bool = False,
        include_materials: bool = True,
        limit: int = 500,
        **_kwargs,
    ) -> str:
        from tech_connector.game_engine.integration.scene_snapshot_provider import max_scene_snapshot_code

        return max_scene_snapshot_code(
            selected_only=selected_only,
            include_materials=include_materials,
            limit=limit,
        )

    def get_scene_snapshot(
        self,
        *,
        selected_only: bool = False,
        include_materials: bool = True,
        limit: int = 500,
        timeout: float = 30.0,
        **_kwargs,
    ) -> tuple[bool, object]:
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output

        code = self.get_scene_snapshot_code(
            selected_only=selected_only,
            include_materials=include_materials,
            limit=limit,
        )
        port = _kwargs.get("port")
        if port is None:
            ok, output = self.execute(code, timeout=timeout)
        else:
            ok, output = self.execute_on_port(code, port=int(port), timeout=timeout)
        if not ok:
            return False, output
        return parse_scene_snapshot_output(str(output).splitlines()[-1], "3dsmax")


__all__ = [
    "MaxBridge", "PLUGIN_FILENAME", "PLUGIN_SOURCE_CODE", "default_startup_dir",
    "install_to_startup_dir", "startup_script_candidates",
]
