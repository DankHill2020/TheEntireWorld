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
sys.path.append(tools_dir)

# Shared queue between HTTP server and tick handler
request_queue = queue.Queue()


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

unreal.register_slate_post_tick_callback(tick)


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
    port = 12347
    if is_port_in_use(port):
        unreal.log_error(f"Port {port} already in use — HTTP server won't start.")
        return
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, RequestHandler)
    unreal.log(f"HTTP Server started on port {port}")
    httpd.serve_forever()


def start_http_server_in_thread():
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()


if __name__ == "__main__":
    start_http_server_in_thread()
