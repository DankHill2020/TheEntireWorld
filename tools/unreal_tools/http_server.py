import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unreal
import sys
import socket
import json
import queue
import importlib
import os
import time


script_dir = os.path.dirname(__file__)
tools_dir = os.path.dirname(script_dir)
if tools_dir not in sys.path:
    sys.path.append(tools_dir)

# Shared queue between HTTP server and tick handler
request_queue = queue.Queue()
PORT = int(os.environ.get("UNREAL_HTTP_PORT", "12347"))
MAX_REQUEST_WAIT_SECONDS = float(os.environ.get("UNREAL_HTTP_MAX_WAIT_SECONDS", "120"))
_server_lock = threading.Lock()
_server_thread = None
_http_server = None


def _write_bridge_status(status):
    paths = []
    try:
        paths.append(
            os.path.join(
                unreal.Paths.project_saved_dir(),
                "AIStudioBridge",
                "startup_status.json",
            )
        )
    except Exception:
        pass
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        paths.append(
            os.path.join(
                local_appdata,
                "TA_Tech_Connector_MCPHost",
                "unreal_plugin_status.json",
            )
        )
    for path in paths:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(status, handle, indent=2)
        except Exception:
            pass


def verify_ai_studio_bridge():
    library = getattr(unreal, "AIStudioBridgeLibrary", None)
    required = [
        "inspect_anim_blueprint_graph",
        "configure_blueprint_replication",
        "bind_niagara_user_parameters_on_begin_play",
    ]
    available = bool(library)
    methods = {
        name: bool(library and hasattr(library, name))
        for name in required
    }
    status = {
        "ok": available and all(methods.values()),
        "plugin": "AIStudioBridge",
        "library_available": available,
        "required_methods": methods,
        "restart_required": not available,
        "message": (
            "AIStudioBridge is loaded and its required reflected methods are available."
            if available and all(methods.values())
            else "AIStudioBridge is missing or stale. Install/build the project plugin, then restart Unreal."
        ),
    }
    _write_bridge_status(status)
    if status["ok"]:
        unreal.log(status["message"])
    else:
        unreal.log_error(status["message"])
    return status


def _write_port_files(port):
    paths = [
        os.path.join(
            tools_dir,
            "tech_connector",
            "bridges",
            "ports",
            "unreal_http_port.txt",
        )
    ]
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        paths.append(
            os.path.join(
                local_appdata,
                "TA_Tech_Connector_MCPHost",
                "unreal_http_port.txt",
            )
        )
    for path in paths:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(str(port))
        except Exception:
            pass


def import_function(func_path):
    """
    Dynamically import a function from a module path string. used in a payload for the HTTP Handler POST
    :param func_path: Example func "unreal_tools.get_skeletons.get_all_assets_of_type"
    :return:
    """
    module_path, func_name = func_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def tick(delta_time):
    while not request_queue.empty():
        task = request_queue.get()
        if task.get("__cancelled__"):
            task["__result__"] = {"error": "Request was cancelled before Unreal execution began."}
            task["__handled__"] = True
            continue
        task["__started__"] = True
        try:
            func_path = task["function"]
            args = task.get("args", [])
            kwargs = task.get("kwargs", {})

            module_path, func_name = func_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[func_name])
            func = getattr(module, func_name)

            unreal.log(f"[Tick] Calling function: {func_path} with args={args}, kwargs={kwargs}")
            result = func(*args, **kwargs)

            # Store result to send back
            task["__result__"] = result
        except Exception as e:
            unreal.log_error(f"Function call failed: {e}")
            task["__result__"] = {"error": str(e)}
        finally:
            task["__handled__"] = True

if not getattr(unreal, "_tech_connector_http_tick_registered", False):
    unreal.register_slate_post_tick_callback(tick)
    unreal._tech_connector_http_tick_registered = True


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        unreal.log(f"HTTP: {self.address_string()} - {format % args}")

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length') or 0)
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode('utf-8'))

            if "function" not in data:
                raise ValueError("Missing 'function' in request body")

            # Build task with placeholders for result
            task = {
                "function": data["function"],
                "args": data.get("args", []),
                "kwargs": data.get("kwargs", {}),
                "__result__": None,
                "__handled__": False,
                "__started__": False,
                "__cancelled__": False,
            }

            # Queue it
            request_queue.put(task)

            # Wait for Unreal tick to process it
            deadline = time.monotonic() + MAX_REQUEST_WAIT_SECONDS
            while not task["__handled__"] and time.monotonic() < deadline:
                time.sleep(0.05)

            if not task["__handled__"]:
                if not task["__started__"]:
                    task["__cancelled__"] = True
                    status = "cancelled_before_execution"
                else:
                    status = "execution_continues_in_unreal"
                self._send_json(504, {
                    "error": f"Unreal request exceeded {MAX_REQUEST_WAIT_SECONDS:.1f} seconds.",
                    "status": status,
                })
                return

            # Send back result
            result = task["__result__"]
            self._send_json(200, result)

        except Exception as e:
            unreal.log_error(f"Error handling request: {e}")
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status_code, payload):
        """Send a JSON response without terminating the server on disconnect."""
        try:
            encoded = json.dumps(payload, indent=2, default=str).encode('utf-8')
            self.send_response(int(status_code))
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
            unreal.log_warning(f"HTTP client disconnected before response delivery: {exc}")


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def run_server():
    global _http_server
    port = PORT
    if is_port_in_use(port):
        _write_port_files(port)
        unreal.log_error(f"Port {port} already in use — HTTP server won't start.")
        return
    server_address = ('127.0.0.1', port)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(server_address, RequestHandler)
    _http_server = httpd
    httpd.daemon_threads = True
    _write_port_files(port)
    unreal.log(f"HTTP Server started on port {port}")
    try:
        httpd.serve_forever()
    except Exception as exc:
        unreal.log_error(f"Tech Connector HTTP server stopped unexpectedly: {exc}")
    finally:
        _http_server = None
        unreal._tech_connector_http_server_started = False
        try:
            httpd.server_close()
        except Exception:
            pass


def start_http_server_in_thread():
    """Start the listener unless a live server thread already owns it."""
    global _server_thread
    with _server_lock:
        if _server_thread is not None and _server_thread.is_alive() and is_port_in_use(PORT):
            unreal._tech_connector_http_server_started = True
            unreal.log(f"Tech Connector HTTP server already started on port {PORT}.")
            return False
        unreal._tech_connector_http_server_started = True
        _server_thread = threading.Thread(
            target=run_server,
            name="TechConnectorUnrealHTTP",
            daemon=True,
        )
        _server_thread.start()
        return True


def server_status():
    """Return listener and worker state for startup diagnostics."""
    listener_open = is_port_in_use(PORT)
    return {
        "ok": listener_open,
        "port": PORT,
        "thread_alive": bool(_server_thread and _server_thread.is_alive()),
        "listener_open": listener_open,
        "thread_identity_known": bool(_server_thread and _server_thread.is_alive()),
        "queued_requests": request_queue.qsize(),
    }


if __name__ == "__main__":
    verify_ai_studio_bridge()
    start_http_server_in_thread()
