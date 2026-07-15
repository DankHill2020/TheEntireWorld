from __future__ import annotations

"""Direct Maya commandPort bridge."""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import socket
from models.constants import APP_ROOT, DEFAULT_MAYA_PORT, TOOLS_ROOT


class MayaBridge:
    """Deterministic Maya communication via commandPort."""

    PORT_FILE = Path(os.environ.get("MAYA_COMMAND_PORT_FILE", r"C:\Users\Aaron\temp\maya_port.txt"))

    SYS_PATHS = [
        str(TOOLS_ROOT),
        str(APP_ROOT),
    ]

    def _candidate_ports(self) -> list[tuple[int, str]]:
        candidates: list[tuple[int, str]] = []
        env_port = os.environ.get("MAYA_COMMAND_PORT")
        if env_port:
            try:
                candidates.append((int(env_port), "env"))
            except Exception:
                pass

        try:
            port_text = self.PORT_FILE.read_text(encoding="utf-8").strip()
            if port_text:
                candidates.append((int(port_text), "file"))
        except Exception:
            pass

        try:
            scan_count = max(1, int(os.environ.get("MAYA_COMMAND_PORT_SCAN_COUNT", "10")))
        except Exception:
            scan_count = 10
        for offset in range(scan_count):
            candidates.append((DEFAULT_MAYA_PORT + offset, "scan"))
        return candidates

    def _is_port_open(self, host: str, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(float(os.environ.get("MAYA_COMMAND_PORT_CONNECT_TIMEOUT", "0.05")))
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False

    def _remove_stale_port_file(self, port: int) -> None:
        try:
            if self.PORT_FILE.read_text(encoding="utf-8").strip() == str(port):
                self.PORT_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def find_ports(self, host="127.0.0.1") -> list[int]:
        candidate_sources: dict[int, str] = {}
        stale_file_ports: list[int] = []
        seen = set()
        for port, source in self._candidate_ports():
            if port in seen:
                continue
            seen.add(port)
            candidate_sources[port] = source
        try:
            worker_count = max(1, int(os.environ.get("MAYA_COMMAND_PORT_SCAN_WORKERS", "10")))
        except Exception:
            worker_count = 10
        open_ports: set[int] = set()
        with ThreadPoolExecutor(max_workers=min(worker_count, max(1, len(candidate_sources)))) as executor:
            future_ports = {
                executor.submit(self._is_port_open, host, port): port
                for port in candidate_sources
            }
            for future in as_completed(future_ports):
                port = future_ports[future]
                if bool(future.result()):
                    open_ports.add(port)
                elif candidate_sources.get(port) == "file":
                    stale_file_ports.append(port)
        for port in stale_file_ports:
            self._remove_stale_port_file(port)
        return [port for port in candidate_sources if port in open_ports]

    def find_port(self, host="127.0.0.1"):
        stale_file_ports: list[int] = []
        seen = set()
        for port, source in self._candidate_ports():
            if port in seen:
                continue
            seen.add(port)
            if self._is_port_open(host, port):
                return port
            if source == "file":
                stale_file_ports.append(port)
        for port in stale_file_ports:
            self._remove_stale_port_file(port)
        return None

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Maya commandPort found."}
        code = """
import json
import os
import maya.cmds as cmds
print(json.dumps({
    "pid": os.getpid(),
    "version": cmds.about(version=True),
    "scene": cmds.file(q=True, sceneName=True),
    "selection": cmds.ls(selection=True) or [],
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

    def execute(self, code: str, timeout: float = 5) -> tuple[bool, str]:
        """
        Execute code against Maya's commandPort capture function.
        Returns (success, result_or_error_message).
        """
        port = self.find_port()
        if not port:
            return False, "No Maya commandPort found. Start Maya and run maya_command_port_setup.py."
        return self.execute_on_port(code, port=port, timeout=timeout)

    def execute_on_port(self, code: str, port: int, timeout: float = 5) -> tuple[bool, str]:
        try:
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = f"maya_execute_and_capture('{encoded}')\n"

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("127.0.0.1", port))
                s.sendall(payload.encode("utf-8"))

                chunks = []
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    chunk = data.decode("utf-8", errors="replace")
                    chunks.append(chunk)
                    if "\x00" in chunk:
                        break

            result = "".join(chunks).replace("\x00", "").strip()
            if not result:
                return True, None
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "ok" in parsed:
                    if not parsed.get("ok", True):
                        return False, parsed.get("error") or parsed.get("stderr") or result
                    return True, parsed.get("result")
            except Exception:
                pass
            return True, result
        except Exception as e:
            return False, str(e)

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, object]:
        args = args or []
        kwargs = kwargs or {}
        payload = {
            "function": function_path,
            "args": args,
            "kwargs": kwargs,
        }

        paths_repr = repr(self.SYS_PATHS)
        code = f"""
import sys, json, importlib, traceback, io
for p in {paths_repr}:
    if p not in sys.path:
        sys.path.append(p)

payload = {repr(payload)}
_stdout, _stderr = sys.stdout, sys.stderr
_out, _err = io.StringIO(), io.StringIO()
envelope = {{"ok": False, "result": None, "stdout": "", "stderr": "", "error": None}}
try:
    sys.stdout = _out
    sys.stderr = _err
    module_path, func_name = payload["function"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    module = importlib.reload(module)
    func = getattr(module, func_name)
    result = func(*payload.get("args", []), **payload.get("kwargs", {{}}))
    envelope.update({{"ok": True, "result": result}})
except Exception as exc:
    envelope.update({{"ok": False, "error": str(exc), "traceback": traceback.format_exc()}})
finally:
    envelope["stdout"] = _out.getvalue()
    envelope["stderr"] = _err.getvalue()
    sys.stdout = _stdout
    sys.stderr = _stderr
print(json.dumps(envelope, default=str))
"""
        return self.execute(code)

    def get_selection_code(self) -> str:
        return "import maya.cmds as cmds\nprint(cmds.ls(sl=True))"

    def get_current_file_code(self) -> str:
        return "import maya.cmds as cmds\nprint(cmds.file(q=True, sceneName=True))"

    def get_scene_objects_code(self) -> str:
        return "import maya.cmds as cmds\nprint(cmds.ls(type='transform')[:500])"

    def parse_input(self, text: str):
        """
        Parse raw Python or JSON function payload.
        Returns ('execute', None) for raw code or ('function', payload_dict).
        """
        import json

        if text.startswith("{"):
            data = json.loads(text)
            return "function", data
        return "execute", None
