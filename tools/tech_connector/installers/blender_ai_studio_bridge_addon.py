"""Blender add-on for The Entire World Tech Connector direct bridge.

Install this file into Blender's user add-ons folder, then enable it or let the
repo installer create the startup hook. The bridge listens on localhost only.
"""

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
import datetime
import hmac
import io
import json
import os
import queue
import socket
import threading
import time
import traceback
import sys
from pathlib import Path

import bpy


HOST = "127.0.0.1"
PORT = int(os.environ.get("BLENDER_COMMAND_PORT", "7021"))
_BRIDGE_KEY = "the_entire_world_ai_blender_bridge_started"
_STATUS_KEY = "the_entire_world_ai_blender_bridge_status"


def _bridge_session_path():
    override = os.environ.get("TECH_CONNECTOR_BRIDGE_SESSION_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        return Path(base) / "TechConnector" / "licensing" / "bridge_session.json" if base else None
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TechConnector" / "licensing" / "bridge_session.json"
    base = Path(os.environ.get("XDG_STATE_HOME", "").strip() or (Path.home() / ".local" / "state"))
    return base / "tech_connector" / "licensing" / "bridge_session.json"


def _bridge_authorized(payload):
    path = _bridge_session_path()
    supplied = str((payload or {}).get("bridge_session") or "")
    if path is None or not supplied:
        return False
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
        issued = datetime.datetime.fromisoformat(
            str(session.get("issued_at") or "").replace("Z", "+00:00")
        )
        expires = datetime.datetime.fromisoformat(
            str(session.get("expires_at") or "").replace("Z", "+00:00")
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        expected = str(session.get("session_token") or "")
        return bool(
            session.get("schema") == "tech_connector.bridge_session.v1"
            and "blender" in [str(item).casefold() for item in session.get("hosts") or []]
            and issued.tzinfo is not None
            and expires.tzinfo is not None
            and issued.astimezone(datetime.timezone.utc) < expires.astimezone(datetime.timezone.utc)
            and issued.astimezone(datetime.timezone.utc) <= now
            and now < expires.astimezone(datetime.timezone.utc)
            and len(expected) >= 32
            and hmac.compare_digest(expected, supplied)
        )
    except Exception:
        return False


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
                while b"\n" not in raw:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                    if len(raw) > _MAX_REQUEST_BYTES:
                        raise ValueError("Blender bridge request exceeded the configured size limit.")

                if b"\n" not in raw:
                    raise ValueError("Blender bridge request ended before its newline terminator.")
                payload = json.loads(raw.decode("utf-8", errors="replace").strip())
                if not _bridge_authorized(payload):
                    response = {
                        "ok": False,
                        "error": "Tech Connector activation is required for this DCC bridge.",
                        "code": "bridge_authorization_required",
                    }
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                    return
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
                conn.sendall((json.dumps(response, default=str) + "\n").encode("utf-8"))
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
                            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
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
        _set_status("The Entire World AI Blender bridge failed:\n%s" % traceback.format_exc())
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
