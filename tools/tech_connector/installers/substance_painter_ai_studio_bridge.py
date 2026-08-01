"""Substance Painter plugin for The Entire World Tech Connector direct bridge."""

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

from tech_connector.models.constants import TOOLS_ROOT


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
    files.append(TOOLS_ROOT / "substance_painter_port.txt")
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
                response = {"ok": False, "error": "Timed out waiting for Substance Painter main thread."}
            else:
                response = job[-1]
        except Exception:
            response = {"ok": False, "error": traceback.format_exc()}

        conn.sendall((json.dumps(response, default=str) + "\n").encode("utf-8"))


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
