"""
Run this inside Blender to enable The Entire World Tech Connector direct bridge.

In Blender:
1. Open the Scripting workspace.
2. Paste or open this file in the Text Editor.
3. Press Run Script.

The bridge listens on localhost only and executes Python sent by the Studio.
"""

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
_jobs = queue.Queue()
_server_started = False
_BRIDGE_KEY = "the_entire_world_ai_blender_bridge_started"


def _write_port_files(port):
    pass


def _execute_code(code):
    stream = io.StringIO()
    namespace = {
        "__name__": "__blender_bridge__",
        "bpy": bpy,
    }
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(16)
        _write_port_files(PORT)
        print("The Entire World AI Blender bridge running on %s:%s" % (HOST, PORT))

        while True:
            conn, _addr = sock.accept()
            threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()


def start_blender_bridge():
    global _server_started
    if _server_started or bpy.app.driver_namespace.get(_BRIDGE_KEY):
        print("The Entire World AI Blender bridge is already running on %s:%s" % (HOST, PORT))
        return

    if not bpy.app.timers.is_registered(_process_jobs):
        bpy.app.timers.register(_process_jobs, persistent=True)

    threading.Thread(target=_server, daemon=True).start()
    _server_started = True
    bpy.app.driver_namespace[_BRIDGE_KEY] = True


start_blender_bridge()
