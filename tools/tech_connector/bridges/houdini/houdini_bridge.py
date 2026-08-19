"""Direct Houdini socket bridge."""

from __future__ import annotations

import array
import base64
import json
import os
import socket
import tempfile
from pathlib import Path
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo, call_python_function_via_execute
from tech_connector.bridges.session_discovery import (
    candidate_session_ports,
    discover_open_ports,
    parse_session_output,
)
from tech_connector.models.constants import APP_DIR, APP_ROOT, TOOLS_ROOT
from tech_connector.game_engine.scene.scene_delta_contract import normalize_frame_delta


PLUGIN_FILENAME = "the_entire_world_ai_studio_houdini_bridge.py"

PLUGIN_SOURCE_CODE = """\"\"\"Houdini plugin for The Entire World Tech Connector direct bridge.\"\"\"

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

try:
    import hou
except ImportError:
    pass

HOST = "127.0.0.1"
PORT = int(os.environ.get("HOUDINI_COMMAND_PORT", "7051"))
_jobs = queue.Queue()
_server_thread = None
_server_stop = threading.Event()
_server_started = False


def _port_files():
    files = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        files.append(Path(local_app_data) / "TA_AI_Studio_MCPHost" / "houdini_port.txt")
    tools_root = Path(os.environ["TOOLSROOT"]).expanduser() if os.environ.get("TOOLSROOT") else Path(__file__).resolve().parents[3] if "__file__" in globals() else Path.cwd()
    if not tools_root.exists():
        tools_root = Path.cwd()
    files.append(Path(tools_root) / "houdini_port.txt")
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
    namespace = {"__name__": "__houdini_bridge__"}
    try:
        import hou
        namespace["hou"] = hou
    except Exception:
        pass

    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            exec(code, namespace, namespace)
        output = stream.getvalue().strip()
        return {"ok": True, "result": output or "Houdini executed successfully."}
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
                response = {"ok": False, "error": "Timed out waiting for Houdini main thread."}
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
            print("The Entire World AI Houdini bridge running on %s:%s" % (HOST, PORT))

            while not _server_stop.is_set():
                try:
                    conn, _addr = sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()
    except Exception:
        _server_started = False
        print("The Entire World AI Houdini bridge failed:")
        traceback.print_exc()


def start_bridge():
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        print("The Entire World AI Houdini bridge is already running on %s:%s" % (HOST, PORT))
        return

    _server_stop.clear()
    
    try:
        import hou
        # Evaluate jobs in the main thread using ui addEventLoopCallback
        if hou.isUIAvailable():
            hou.ui.addEventLoopCallback(_process_jobs)
    except Exception:
        pass

    _server_thread = threading.Thread(target=_server, daemon=True)
    _server_thread.start()


def stop_bridge():
    _server_stop.set()
    try:
        import hou
        if hou.isUIAvailable():
            hou.ui.removeEventLoopCallback(_process_jobs)
    except Exception:
        pass

"""


def start_plugin_immediately():
    exec(PLUGIN_SOURCE_CODE, globals(), globals())
    if "start_bridge" in globals():
        globals()["start_bridge"]()


from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


class HoudiniBridge(DCCBridgeDelegateMixin):
    def __init__(self):
        self.init_delegate("houdini")

    info = HostBridgeInfo(
        id="houdini",
        display_name="Houdini",
        protocol="socket-json",
        default_port=7051,
        setup_script="bridges/houdini/houdini_bridge.py",
        supports_direct_execute=True,
        supports_mcp=False,
    )
    PORT_FILES = [
        str(APP_DIR / "houdini_port.txt"),
        str(TOOLS_ROOT / "houdini_port.txt"),
    ]
    DEFAULT_PORT = 7051
    SYS_PATHS = [
        str(TOOLS_ROOT),
        str(APP_ROOT),
    ]

    def _candidate_ports(self) -> list[int]:
        return candidate_session_ports(
            "houdini",
            port_files=self.PORT_FILES,
            environment_variable="HOUDINI_COMMAND_PORT",
            default_port=self.DEFAULT_PORT,
            scan_count_variable="HOUDINI_COMMAND_PORT_SCAN_COUNT",
        )

    def find_ports(self, host="127.0.0.1") -> list[int]:
        return discover_open_ports(self._candidate_ports(), host=host)

    def find_port(self, host="127.0.0.1"):
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def execute_on_port(self, code: str, *, port: int, timeout: float = 10) -> tuple[bool, str]:
        port = int(port)
        if not port:
            return False, "No Houdini bridge found. Re-run setup, then restart Houdini."

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
                return True, "Houdini returned no output."

            try:
                parsed = json.loads(raw)
                result = parsed.get("result") or parsed.get("error") or raw
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, str(result).strip() or "Houdini returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        port = self.find_port()
        if not port:
            return False, "No Houdini bridge found. Re-run setup, then restart Houdini."
        return self.execute_on_port(code, port=port, timeout=timeout)

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Houdini bridge found."}
        code = """
import hou
import json
import os
print(json.dumps({
    "pid": os.getpid(),
    "version": hou.applicationVersionString(),
    "scene": hou.hipFile.path(),
    "frame": float(hou.frame()),
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
        return "import hou\nprint(hou.hipFile.path())"

    def get_project_status_code(self) -> str:
        return "import hou\nprint('open' if hou.hipFile.name() != 'untitled.hip' else 'untitled')"

    def get_scene_objects_code(self) -> str:
        return "import hou\nprint([n.name() for n in hou.node('/').allSubChildren()][:500])"

    def get_fast_timeline_sample_code(
        self,
        *,
        target_native_ids: list[str] | tuple[str, ...],
        binary_path: str,
        frame: float | None = None,
        include_cameras: bool = True,
        max_vertices_per_object: int = 1000000,
    ) -> str:
        targets_json = json.dumps([str(item) for item in target_native_ids if str(item)])
        return f"""
import array
import json
import hou

targets = json.loads({targets_json!r})
binary_path = {str(binary_path)!r}
frame = {frame!r}
include_cameras = {bool(include_cameras)!r}
max_vertices_per_object = int({int(max_vertices_per_object)!r})
if frame is not None:
    hou.setFrame(float(frame))
objects = []
frame_vertices = bytearray()

def _object_node(node):
    current = node
    while current is not None:
        try:
            if current.type().category() == hou.objNodeTypeCategory():
                return current
        except Exception:
            pass
        current = current.parent()
    return None

def _world_matrix(node):
    object_node = _object_node(node)
    matrix = object_node.worldTransform() if object_node is not None else hou.hmath.identityTransform()
    return [float(value) for value in matrix.asTuple()]

for native_id in targets:
    node = hou.node(native_id)
    if node is None:
        continue
    item = {{
        "native_id": node.path(),
        "name": node.name(),
        "type": node.type().name(),
        "visible": not node.isHidden(),
        "world_matrix": _world_matrix(node),
    }}
    try:
        geometry = node.geometry()
    except Exception:
        geometry = None
    if geometry is not None:
        point_count = len(geometry.points())
        if 0 < point_count <= max_vertices_per_object:
            try:
                packed_bytes = geometry.pointFloatAttribValuesAsString("P")
            except Exception:
                packed_values = geometry.pointFloatAttribValues("P")
                packed_bytes = array.array("f", packed_values).tobytes()
            if len(packed_bytes) >= point_count * 3 * 4:
                item["geometry"] = {{
                    "representation": "mesh",
                    "vertex_encoding": "f32-file-array",
                    "vertex_float_offset": len(frame_vertices) // 4,
                    "vertex_count": point_count,
                    "coordinate_space": "object",
                    "topology_included": False,
                    "faces": [],
                }}
                frame_vertices.extend(packed_bytes[:point_count * 3 * 4])
    objects.append(item)

cameras = []
if include_cameras:
    for node in hou.node("/obj").allSubChildren():
        try:
            if node.type().name().lower() != "cam":
                continue
            matrix = node.worldTransform()
            translation = matrix.extractTranslates()
            cameras.append({{
                "native_id": node.path(),
                "name": node.name(),
                "type": "camera",
                "translation": [float(value) for value in translation],
                "world_matrix": [float(value) for value in matrix.asTuple()],
                "focal_length_mm": float(node.parm("focal").eval()) if node.parm("focal") else 50.0,
                "near_clip": float(node.parm("near").eval()) if node.parm("near") else 0.1,
                "far_clip": float(node.parm("far").eval()) if node.parm("far") else 10000.0,
                "visible": True,
            }})
        except Exception:
            pass

with open(binary_path, "wb") as binary_file:
    binary_file.write(frame_vertices)
payload = {{
    "schema": "tech_connector.houdini.timeline_sample.v1",
    "provider_id": "houdini",
    "scene": hou.hipFile.path(),
    "unit_linear": "meters",
    "up_axis": "y",
    "current_time": float(hou.frame()),
    "frame_start": float(hou.playbar.frameRange()[0]),
    "frame_end": float(hou.playbar.frameRange()[1]),
    "fps": float(hou.fps()),
    "objects": objects,
    "cameras": cameras,
    "active_camera": "",
    "isolation": {{
        "include_geometry": True,
        "include_cameras": include_cameras,
        "include_materials": False,
        "target_native_ids": targets,
    }},
}}
print(json.dumps(payload, separators=(",", ":")))
"""

    def get_fast_timeline_sample(
        self,
        *,
        target_native_ids: list[str] | tuple[str, ...],
        frame: float | None = None,
        include_cameras: bool = True,
        max_vertices_per_object: int = 1000000,
        timeout: float = 10.0,
        port: int | None = None,
    ) -> tuple[bool, dict | str]:
        handle, binary_path = tempfile.mkstemp(prefix="tech_connector_houdini_frame_", suffix=".f32")
        os.close(handle)
        raw = ""
        try:
            code = self.get_fast_timeline_sample_code(
                target_native_ids=target_native_ids,
                binary_path=binary_path,
                frame=frame,
                include_cameras=include_cameras,
                max_vertices_per_object=max_vertices_per_object,
            )
            if port is None:
                ok, raw = self.execute(code, timeout=timeout)
            else:
                ok, raw = self.execute_on_port(code, port=int(port), timeout=timeout)
            if not ok:
                return False, raw
            snapshot = json.loads(str(raw or "{}"))
            packed = array.array("f")
            with open(binary_path, "rb") as binary_file:
                packed.fromfile(binary_file, os.path.getsize(binary_path) // packed.itemsize)
            for item in snapshot.get("objects") or []:
                geometry = item.get("geometry") if isinstance(item, dict) else None
                if isinstance(geometry, dict) and geometry.get("vertex_encoding") == "f32-file-array":
                    geometry["vertices_f32"] = packed
            return True, normalize_frame_delta(snapshot, "houdini")
        except Exception as exc:
            return False, f"Could not parse Houdini timeline sample: {exc}\n{str(raw)[:500]}"
        finally:
            try:
                os.unlink(binary_path)
            except Exception:
                pass

    def get_scene_snapshot_code(
        self,
        *,
        selected_only: bool = False,
        include_geometry: bool = True,
        include_materials: bool = True,
        limit: int = 500,
        max_vertices_per_object: int = 50000,
        max_faces_per_object: int = 50000,
    ) -> str:
        from tech_connector.game_engine.integration.scene_snapshot_provider import houdini_scene_snapshot_code

        return houdini_scene_snapshot_code(
            selected_only=selected_only,
            include_geometry=include_geometry,
            include_materials=include_materials,
            limit=limit,
            max_vertices_per_object=max_vertices_per_object,
            max_faces_per_object=max_faces_per_object,
        )

    def get_scene_snapshot(
        self,
        *,
        selected_only: bool = False,
        include_geometry: bool = True,
        include_materials: bool = True,
        limit: int = 500,
        max_vertices_per_object: int = 50000,
        max_faces_per_object: int = 50000,
        timeout: float = 10.0,
        port: int | None = None,
    ) -> tuple:
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output

        code = self.get_scene_snapshot_code(
            selected_only=selected_only,
            include_geometry=include_geometry,
            include_materials=include_materials,
            limit=limit,
            max_vertices_per_object=max_vertices_per_object,
            max_faces_per_object=max_faces_per_object,
        )
        if port is None:
            ok, raw = self.execute(code, timeout=timeout)
        else:
            ok, raw = self.execute_on_port(code, port=int(port), timeout=timeout)
        if not ok:
            return False, raw
        return parse_scene_snapshot_output(raw, "houdini")

    def get_selection_code(self) -> str:
        return "import hou\nprint([n.name() for n in hou.selectedNodes()])"

    def parse_input(self, text: str):
        if text.startswith("{"):
            return "function", json.loads(text)
        return "execute", None


