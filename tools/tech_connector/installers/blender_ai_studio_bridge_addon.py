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
            while b"\n" not in raw:
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

        conn.sendall((json.dumps(response, default=str) + "\n").encode("utf-8"))


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
        _set_status("The Entire World AI Blender bridge failed:\n%s" % traceback.format_exc())


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
