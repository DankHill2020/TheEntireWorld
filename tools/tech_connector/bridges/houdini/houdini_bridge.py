"""Direct Houdini socket bridge."""

import base64
import json
import os
import socket
from pathlib import Path
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo, call_python_function_via_execute
from tech_connector.models.constants import APP_DIR, APP_ROOT, TOOLS_ROOT


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
    files.append(Path(r"C:\\depot\\tools\\houdini_port.txt"))
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

    def find_port(self, host="127.0.0.1"):
        candidates = []

        for pfile in self.PORT_FILES:
            if os.path.exists(pfile):
                try:
                    with open(pfile, "r") as f:
                        candidates.append(int(f.read().strip()))
                except Exception:
                    pass

        env_port = os.environ.get("HOUDINI_COMMAND_PORT")
        if env_port:
            try:
                candidates.append(int(env_port))
            except Exception:
                pass

        candidates.append(self.DEFAULT_PORT)

        seen = set()
        for port in candidates:
            if port in seen:
                continue
            seen.add(port)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.25)
                    if s.connect_ex((host, port)) == 0:
                        return port
            except Exception:
                pass

        return None

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        port = self.find_port()
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

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, str]:
        return call_python_function_via_execute(self, function_path, args, kwargs, self.SYS_PATHS)

    def get_current_file_code(self) -> str:
        return "import hou\nprint(hou.hipFile.path())"

    def get_project_status_code(self) -> str:
        return "import hou\nprint('open' if hou.hipFile.name() != 'untitled.hip' else 'untitled')"

    def get_scene_objects_code(self) -> str:
        return "import hou\nprint([n.name() for n in hou.node('/').allSubChildren()][:500])"

    def get_selection_code(self) -> str:
        return "import hou\nprint([n.name() for n in hou.selectedNodes()])"

    def parse_input(self, text: str):
        if text.startswith("{"):
            return "function", json.loads(text)
        return "execute", None
