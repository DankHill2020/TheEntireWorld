"""Direct Blender socket bridge."""

from __future__ import annotations

import array
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import socket
import shutil
import tempfile
import time
from pathlib import Path
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo, call_python_function_via_execute
from tech_connector.bridges.session_preferences import preferred_session_port
from tech_connector.models.constants import APP_ROOT, TOOLS_ROOT
from tech_connector.game_engine.scene.scene_delta_contract import normalize_frame_delta


def _sidecar_array(typecode: str, data: bytes, byte_offset: int, count: int) -> array.array:
    values = array.array(typecode)
    byte_offset = int(byte_offset)
    count = int(count)
    if byte_offset < 0 or count < 0:
        raise ValueError("Blender geometry sidecar contains a negative offset or count.")
    byte_count = values.itemsize * count
    end = byte_offset + byte_count
    if end > len(data):
        raise ValueError(
            f"Blender geometry sidecar range {byte_offset}:{end} exceeds {len(data)} bytes."
        )
    values.frombytes(data[byte_offset:end])
    return values


def decode_blender_snapshot_geometry(snapshot: dict, data: bytes) -> dict:
    """Hydrate typed Blender geometry outside the DCC main thread."""
    for item in snapshot.get("objects") or []:
        geometry = item.get("geometry") if isinstance(item, dict) else None
        if not isinstance(geometry, dict) or geometry.get("vertex_encoding") != "f32-file-array":
            continue
        vertices = _sidecar_array(
            "f",
            data,
            geometry.get("vertex_byte_offset", 0),
            geometry.get("vertex_float_count", 0),
        )
        if len(vertices) % 3:
            raise ValueError("Blender geometry vertex payload is not divisible into XYZ triples.")
        geometry["vertices"] = [
            [float(vertices[index]), float(vertices[index + 1]), float(vertices[index + 2])]
            for index in range(0, len(vertices), 3)
        ]

        face_counts = _sidecar_array(
            "I",
            data,
            geometry.get("face_count_byte_offset", 0),
            geometry.get("face_count_count", 0),
        )
        face_indices = _sidecar_array(
            "I",
            data,
            geometry.get("face_index_byte_offset", 0),
            geometry.get("face_index_count", 0),
        )
        cursor = 0
        faces = []
        for raw_count in face_counts:
            face_size = int(raw_count)
            end = cursor + face_size
            if face_size < 3 or end > len(face_indices):
                raise ValueError("Blender geometry face payload is malformed.")
            faces.append([int(value) for value in face_indices[cursor:end]])
            cursor = end
        if cursor != len(face_indices):
            raise ValueError("Blender geometry face payload contains trailing indices.")
        geometry["faces"] = faces

        if geometry.get("uv_encoding") == "f32-file-array":
            uvs = _sidecar_array(
                "f",
                data,
                geometry.get("uv_byte_offset", 0),
                geometry.get("uv_float_count", 0),
            )
            if len(uvs) % 2:
                raise ValueError("Blender geometry UV payload is not divisible into UV pairs.")
            geometry["uvs"] = [
                [float(uvs[index]), float(uvs[index + 1])]
                for index in range(0, len(uvs), 2)
            ]
            face_uv_indices = _sidecar_array(
                "I",
                data,
                geometry.get("face_uv_byte_offset", 0),
                geometry.get("face_uv_index_count", 0),
            )
            cursor = 0
            uv_faces = []
            for raw_count in face_counts:
                end = cursor + int(raw_count)
                if end > len(face_uv_indices):
                    raise ValueError("Blender geometry face-UV payload is malformed.")
                uv_faces.append([int(value) for value in face_uv_indices[cursor:end]])
                cursor = end
            if cursor != len(face_uv_indices):
                raise ValueError("Blender geometry face-UV payload contains trailing indices.")
            geometry["face_uv_indices"] = uv_faces
    snapshot["binary_geometry_bytes"] = len(data)
    return snapshot


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
import time
import traceback
from pathlib import Path

import bpy


HOST = "127.0.0.1"
PORT = int(os.environ.get("BLENDER_COMMAND_PORT", "7021"))
_BRIDGE_KEY = "the_entire_world_ai_blender_bridge_started"
_STATUS_KEY = "the_entire_world_ai_blender_bridge_status"


def _bounded_env_int(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


_MAX_REQUEST_BYTES = _bounded_env_int("TECH_CONNECTOR_BLENDER_MAX_REQUEST_BYTES", 16 * 1024 * 1024, 4096, 256 * 1024 * 1024)
_MAX_PENDING_JOBS = _bounded_env_int("TECH_CONNECTOR_BLENDER_MAX_PENDING_JOBS", 32, 1, 512)
_MAX_JOBS_PER_TICK = _bounded_env_int("TECH_CONNECTOR_BLENDER_MAX_JOBS_PER_TICK", 4, 1, 64)
_MAX_CLIENT_THREADS = _bounded_env_int("TECH_CONNECTOR_BLENDER_MAX_CLIENT_THREADS", 32, 1, 256)
_MAX_REQUEST_SECONDS = _bounded_env_int("TECH_CONNECTOR_BLENDER_MAX_REQUEST_SECONDS", 600, 1, 3600)

_jobs = queue.Queue(maxsize=_MAX_PENDING_JOBS)
_client_slots = threading.BoundedSemaphore(_MAX_CLIENT_THREADS)
_server_thread = None
_server_stop = threading.Event()
_classes_registered = False
_bound_port = None


def _bridge_poll_seconds():
    try:
        value = float(os.environ.get("TECH_CONNECTOR_BLENDER_BRIDGE_POLL_SECONDS", "0.005"))
    except (TypeError, ValueError):
        value = 0.005
    return max(0.001, min(0.05, value))


_BRIDGE_POLL_SECONDS = _bridge_poll_seconds()


def _bridge_port_scan_count():
    try:
        value = int(os.environ.get("BLENDER_COMMAND_PORT_SCAN_COUNT", "10"))
    except (TypeError, ValueError):
        value = 10
    return max(1, min(100, value))


def _write_port_files(port):
    paths = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        paths.append(Path(local_app_data) / "TA_AI_Studio_MCPHost" / "blender_port.txt")
    app_root = os.environ.get("TECH_CONNECTOR_APP_ROOT", "").strip()
    if app_root:
        paths.append(Path(app_root) / "bridges" / "ports" / "blender_port.txt")
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(int(port)), encoding="utf-8")
        except Exception:
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
    processed = 0
    while processed < _MAX_JOBS_PER_TICK:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        processed += 1
        try:
            if job.get("canceled") or time.monotonic() >= float(job["deadline"]):
                job["response"] = {"ok": False, "error": "Blender request expired before execution."}
            else:
                job["started"] = True
                job["response"] = _execute_code(job["code"])
        finally:
            job["done"].set()

    return _BRIDGE_POLL_SECONDS


def _cancel_pending_jobs(message):
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        job["canceled"] = True
        job["response"] = {"ok": False, "error": str(message)}
        job["done"].set()


def _handle_client(conn):
    try:
        with conn:
            try:
                conn.settimeout(2.0)
                raw = b""
                while b"\\n" not in raw:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                    if len(raw) > _MAX_REQUEST_BYTES:
                        raise ValueError("Blender bridge request exceeded the configured size limit.")

                if b"\\n" not in raw:
                    raise ValueError("Blender bridge request ended before its newline terminator.")
                payload = json.loads(raw.decode("utf-8", errors="replace").strip())
                encoded = str(payload["code_b64"])
                if len(encoded) > _MAX_REQUEST_BYTES:
                    raise ValueError("Encoded Blender command exceeded the configured size limit.")
                code_bytes = base64.b64decode(encoded, validate=True)
                if len(code_bytes) > _MAX_REQUEST_BYTES:
                    raise ValueError("Decoded Blender command exceeded the configured size limit.")
                code = code_bytes.decode("utf-8", errors="replace")
                try:
                    timeout_seconds = float(payload.get("timeout_seconds", 30.0))
                except (TypeError, ValueError):
                    timeout_seconds = 30.0
                timeout_seconds = max(0.1, min(float(_MAX_REQUEST_SECONDS), timeout_seconds))
                done = threading.Event()
                job = {
                    "code": code,
                    "done": done,
                    "deadline": time.monotonic() + timeout_seconds,
                    "started": False,
                    "canceled": False,
                    "response": None,
                }
                try:
                    _jobs.put_nowait(job)
                except queue.Full:
                    response = {"ok": False, "error": "Blender bridge is busy; its bounded request queue is full."}
                else:
                    if not done.wait(timeout_seconds):
                        job["canceled"] = True
                        suffix = " An already-running operation may still finish." if job.get("started") else " The queued operation was canceled."
                        response = {"ok": False, "error": "Timed out waiting for Blender main thread." + suffix}
                    else:
                        response = job.get("response") or {"ok": False, "error": "Blender request completed without a response."}
            except Exception:
                response = {"ok": False, "error": traceback.format_exc()}

            try:
                conn.sendall((json.dumps(response, default=str) + "\\n").encode("utf-8"))
            except OSError:
                pass
    finally:
        _client_slots.release()


def _server():
    global _bound_port
    try:
        sock = None
        last_error = None
        for candidate in range(PORT, PORT + _bridge_port_scan_count()):
            candidate_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    candidate_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    candidate_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                candidate_socket.bind((HOST, candidate))
                sock = candidate_socket
                _bound_port = candidate
                break
            except OSError as exc:
                last_error = exc
                candidate_socket.close()
        if sock is None:
            raise OSError("No free Blender bridge port was found") from last_error
        with sock:
            sock.listen(16)
            sock.settimeout(0.25)
            _write_port_files(_bound_port)
            _set_status("The Entire World AI Blender bridge running on %s:%s" % (HOST, _bound_port))

            while not _server_stop.is_set():
                try:
                    conn, _addr = sock.accept()
                except socket.timeout:
                    continue
                if not _client_slots.acquire(blocking=False):
                    with conn:
                        try:
                            response = {"ok": False, "error": "Blender bridge is busy; too many live clients."}
                            conn.sendall((json.dumps(response) + "\\n").encode("utf-8"))
                        except OSError:
                            pass
                    continue
                try:
                    threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()
                except Exception:
                    _client_slots.release()
                    conn.close()
                    raise
    except Exception:
        bpy.app.driver_namespace[_BRIDGE_KEY] = False
        _set_status("The Entire World AI Blender bridge failed:\\n%s" % traceback.format_exc())
    finally:
        _bound_port = None


def start_blender_bridge():
    global _server_thread
    if bpy.app.driver_namespace.get(_BRIDGE_KEY):
        _set_status("The Entire World AI Blender bridge is already running on %s:%s" % (HOST, _bound_port or PORT))
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
    _cancel_pending_jobs("Blender bridge stopped before request execution.")
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
        layout.label(text="Running on %s:%s" % (HOST, _bound_port or PORT) if running else "Not running")
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
            if (
                not addon_target.exists()
                or addon_target.read_text(encoding="utf-8") != ADDON_SOURCE_CODE
            ):
                raise
        try:
            startup_target.write_text(startup_code, encoding="utf-8")
        except PermissionError:
            if (
                not startup_target.exists()
                or startup_target.read_text(encoding="utf-8") != startup_code
            ):
                raise

    return addon_target, startup_target


def startup_code_for(addon_dir):
    return f"""# Auto-generated by The Entire World Tech Connector.
import importlib
import os
import sys

addon_dir = r"{addon_dir}"
os.environ.setdefault("TECH_CONNECTOR_APP_ROOT", r"{APP_ROOT}")
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


from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


class BlenderBridge(DCCBridgeDelegateMixin):
    """Deterministic Blender communication via a small in-Blender socket server."""

    def __init__(self):
        self.init_delegate("blender")

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

    def _candidate_ports(self) -> list[int]:
        candidates = []
        preferred_port = preferred_session_port("blender")
        if preferred_port:
            candidates.append(preferred_port)

        env_port = os.environ.get("BLENDER_COMMAND_PORT")
        if env_port:
            try:
                candidates.append(int(env_port))
            except Exception:
                pass

        try:
            scan_count = int(os.environ.get("BLENDER_COMMAND_PORT_SCAN_COUNT", "10"))
        except (TypeError, ValueError):
            scan_count = 10
        candidates.extend(range(self.DEFAULT_PORT, self.DEFAULT_PORT + max(1, min(100, scan_count))))
        return list(dict.fromkeys(int(port) for port in candidates if int(port) > 0))

    @staticmethod
    def _is_port_open(host: str, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(float(os.environ.get("BLENDER_COMMAND_PORT_CONNECT_TIMEOUT", "0.025")))
                return sock.connect_ex((host, int(port))) == 0
        except Exception:
            return False

    def find_ports(self, host="127.0.0.1") -> list[int]:
        candidates = self._candidate_ports()
        if not candidates:
            return []
        open_ports: set[int] = set()
        max_workers = min(len(candidates), 16)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._is_port_open, host, port): port
                for port in candidates
            }
            for future in as_completed(futures):
                port = futures[future]
                try:
                    if future.result():
                        open_ports.add(port)
                except Exception:
                    pass
        return [port for port in candidates if port in open_ports]

    def find_port(self, host="127.0.0.1"):
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Blender bridge found."}
        code = """
import bpy
import json
import os
print(json.dumps({
    "pid": os.getpid(),
    "version": bpy.app.version_string,
    "scene": bpy.data.filepath or "",
    "selection": [obj.name for obj in bpy.context.selected_objects],
    "frame": float(bpy.context.scene.frame_current_final),
}))
"""
        ok, raw = self.execute_on_port(code, port=port, timeout=timeout)
        if not ok:
            return {"ok": False, "port": port, "error": raw}
        try:
            data = json.loads(str(raw or "{}"))
        except Exception:
            data = {"raw": raw}
        data.update({"ok": True, "port": port})
        return data

    def sessions(self, host="127.0.0.1") -> list[dict]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def execute_on_port(
        self,
        code: str,
        *,
        port: int,
        timeout: float = 10,
        cancel_event=None,
    ) -> tuple[bool, str]:
        port = int(port)
        if not port:
            return False, "No Blender bridge found. Re-run setup, then restart Blender."
        if cancel_event is not None and cancel_event.is_set():
            return False, "Blender command canceled."

        try:
            timeout = max(0.1, float(timeout))
            deadline = time.monotonic() + timeout
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = json.dumps(
                {
                    "code_b64": encoded,
                    "timeout_seconds": max(0.1, timeout * 0.95),
                }
            ).encode("utf-8") + b"\n"
            max_response_bytes = max(
                1024,
                int(os.environ.get("TECH_CONNECTOR_BLENDER_MAX_RESPONSE_BYTES", str(512 * 1024 * 1024))),
            )

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(min(1.0, timeout))
                s.connect(("127.0.0.1", port))
                s.sendall(payload)

                chunks: list[bytes] = []
                received_bytes = 0
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        return False, "Blender command canceled."
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        return False, f"Blender command timed out after {timeout:g} seconds."
                    s.settimeout(min(0.25, remaining))
                    try:
                        data = s.recv(262144)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    chunks.append(data)
                    received_bytes += len(data)
                    if received_bytes > max_response_bytes:
                        return False, "Blender response exceeded the configured size limit."
                    if b"\n" in data:
                        break

            raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
            if not raw:
                return True, "Blender returned no output."

            try:
                parsed = json.loads(raw)
                result = parsed.get("result") or parsed.get("error") or raw
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, str(result).strip() or "Blender returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def execute(self, code: str, timeout: float = 10, cancel_event=None) -> tuple[bool, str]:
        port = self.find_port()
        if not port:
            return False, "No Blender bridge found. Re-run setup, then restart Blender."
        return self.execute_on_port(code, port=port, timeout=timeout, cancel_event=cancel_event)

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, str]:
        return call_python_function_via_execute(self, function_path, args, kwargs, self.SYS_PATHS)

    def get_selection_code(self) -> str:
        return "import bpy\nprint([obj.name for obj in bpy.context.selected_objects])"

    def get_current_file_code(self) -> str:
        return "import bpy\nprint(bpy.data.filepath)"

    def get_scene_objects_code(self) -> str:
        return "import bpy\nprint(list(bpy.data.objects.keys())[:500])"

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
import mathutils
import os
import bpy

targets = json.loads({targets_json!r})
binary_path = {str(binary_path)!r}
frame = {frame!r}
include_cameras = {bool(include_cameras)!r}
max_vertices_per_object = int({int(max_vertices_per_object)!r})
scene = bpy.context.scene
if frame is not None:
    scene.frame_set(int(frame), subframe=float(frame) - int(frame))
depsgraph = bpy.context.evaluated_depsgraph_get()
objects = []
frame_vertices = bytearray()

def _matrix_row_vector_values(matrix):
    return [float(matrix[row][column]) for column in range(4) for row in range(4)]

def _world_bbox(obj):
    corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    xs = [float(point.x) for point in corners]
    ys = [float(point.y) for point in corners]
    zs = [float(point.z) for point in corners]
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]

for native_id in targets:
    source_obj = bpy.data.objects.get(native_id)
    if source_obj is None:
        continue
    eval_obj = source_obj.evaluated_get(depsgraph)
    item = {{
        "native_id": source_obj.name_full,
        "name": source_obj.name,
        "type": str(source_obj.type).lower(),
        "visible": not source_obj.hide_get() and not source_obj.hide_viewport,
        "translation": [float(value) for value in eval_obj.matrix_world.translation],
        "world_matrix": _matrix_row_vector_values(eval_obj.matrix_world),
    }}
    try:
        item["bbox"] = _world_bbox(eval_obj)
    except Exception:
        pass
    mesh = None
    try:
        if source_obj.type == "MESH":
            mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
            vertex_count = len(mesh.vertices)
            if 0 < vertex_count <= max_vertices_per_object:
                packed = array.array("f", [0.0]) * (vertex_count * 3)
                mesh.vertices.foreach_get("co", packed)
                geometry = {{
                    "representation": "mesh",
                    "vertex_encoding": "f32-file-array",
                    "vertex_float_offset": len(frame_vertices) // 4,
                    "vertex_count": vertex_count,
                    "coordinate_space": "object",
                    "topology_included": False,
                    "faces": [],
                }}
                frame_vertices.extend(packed.tobytes())
                item["geometry"] = geometry
    finally:
        if mesh is not None:
            eval_obj.to_mesh_clear()
    objects.append(item)

cameras = []
if include_cameras:
    for source_obj in scene.objects:
        if source_obj.type != "CAMERA":
            continue
        eval_obj = source_obj.evaluated_get(depsgraph)
        camera = source_obj.data
        cameras.append({{
            "native_id": source_obj.name_full,
            "name": source_obj.name,
            "type": "camera",
            "translation": [float(value) for value in eval_obj.matrix_world.translation],
            "world_matrix": _matrix_row_vector_values(eval_obj.matrix_world),
            "focal_length_mm": float(camera.lens),
            "near_clip": float(camera.clip_start),
            "far_clip": float(camera.clip_end),
            "visible": not source_obj.hide_get(),
        }})

with open(binary_path, "wb") as binary_file:
    binary_file.write(frame_vertices)
fps = float(scene.render.fps) / max(1.0e-8, float(scene.render.fps_base))
payload = {{
    "schema": "tech_connector.blender.timeline_sample.v1",
    "provider_id": "blender",
    "process_id": int(os.getpid()),
    "scene": bpy.data.filepath or "",
    "unit_linear": str(scene.unit_settings.system),
    "up_axis": "z",
    "current_time": float(scene.frame_current_final),
    "frame_start": float(scene.frame_start),
    "frame_end": float(scene.frame_end),
    "fps": fps,
    "objects": objects,
    "cameras": cameras,
    "active_camera": scene.camera.name_full if scene.camera else "",
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
        cancel_event=None,
    ) -> tuple[bool, dict | str]:
        if cancel_event is not None and cancel_event.is_set():
            return False, "Blender timeline sample canceled."
        handle, binary_path = tempfile.mkstemp(prefix="tech_connector_blender_frame_", suffix=".f32")
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
                ok, raw = self.execute(code, timeout=timeout, cancel_event=cancel_event)
            else:
                ok, raw = self.execute_on_port(
                    code,
                    port=int(port),
                    timeout=timeout,
                    cancel_event=cancel_event,
                )
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
            return True, normalize_frame_delta(snapshot, "blender")
        except Exception as exc:
            return False, f"Could not parse Blender timeline sample: {exc}\n{str(raw)[:500]}"
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
        binary_path: str = "",
    ) -> str:
        from tech_connector.game_engine.integration.scene_snapshot_provider import blender_scene_snapshot_code

        return blender_scene_snapshot_code(
            selected_only=selected_only,
            include_geometry=include_geometry,
            include_materials=include_materials,
            limit=limit,
            max_vertices_per_object=max_vertices_per_object,
            max_faces_per_object=max_faces_per_object,
            binary_path=binary_path,
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
        cancel_event=None,
    ) -> tuple:
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output

        binary_path = ""
        if include_geometry:
            handle, binary_path = tempfile.mkstemp(
                prefix="tech_connector_blender_scene_",
                suffix=".bin",
            )
            os.close(handle)
        try:
            code = self.get_scene_snapshot_code(
                selected_only=selected_only,
                include_geometry=include_geometry,
                include_materials=include_materials,
                limit=limit,
                max_vertices_per_object=max_vertices_per_object,
                max_faces_per_object=max_faces_per_object,
                binary_path=binary_path,
            )
            if port is None:
                ok, raw = self.execute(code, timeout=timeout, cancel_event=cancel_event)
            else:
                ok, raw = self.execute_on_port(
                    code,
                    port=int(port),
                    timeout=timeout,
                    cancel_event=cancel_event,
                )
            if not ok:
                return False, raw
            parsed_ok, snapshot = parse_scene_snapshot_output(raw, "blender")
            if not parsed_ok or not isinstance(snapshot, dict):
                return parsed_ok, snapshot
            if binary_path:
                with open(binary_path, "rb") as binary_file:
                    binary_data = binary_file.read()
                snapshot = decode_blender_snapshot_geometry(snapshot, binary_data)
            return True, snapshot
        except Exception as exc:
            return False, f"Could not decode Blender scene snapshot: {exc}"
        finally:
            if binary_path:
                try:
                    os.unlink(binary_path)
                except Exception:
                    pass

    def parse_input(self, text: str):
        if text.startswith("{"):
            return "function", json.loads(text)
        return "execute", None
