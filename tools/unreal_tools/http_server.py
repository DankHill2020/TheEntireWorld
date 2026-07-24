import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
        content_length = int(self.headers['Content-Length'])
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
                "__handled__": False
            }

            # Queue it
            request_queue.put(task)

            # Wait for Unreal tick to process it
            while not task["__handled__"]:
                time.sleep(0.05)

            # Send back result
            result = task["__result__"]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result, indent=2, default=str).encode('utf-8'))

        except Exception as e:
            unreal.log_error(f"Error handling request: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def run_server():
    port = PORT
    if is_port_in_use(port):
        _write_port_files(port)
        unreal.log_error(f"Port {port} already in use — HTTP server won't start.")
        return
    server_address = ('127.0.0.1', port)
    HTTPServer.allow_reuse_address = True
    httpd = HTTPServer(server_address, RequestHandler)
    _write_port_files(port)
    unreal.log(f"HTTP Server started on port {port}")
    httpd.serve_forever()


def start_http_server_in_thread():
    if getattr(unreal, "_tech_connector_http_server_started", False):
        unreal.log(f"Tech Connector HTTP server already started on port {PORT}.")
        return
    unreal._tech_connector_http_server_started = True
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()


if __name__ == "__main__":
    verify_ai_studio_bridge()
    start_http_server_in_thread()
