import base64
import logging
import os
from pathlib import Path
import socket
import sys

logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

from fastmcp import FastMCP

mcp = FastMCP("MotionBuilderMCP")


def _detect_tools_root() -> Path:
    configured = os.environ.get("AI_STUDIO_TOOLS_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    source = Path(__file__).resolve()
    for candidate in source.parents:
        if candidate.name.lower() == "tools":
            return candidate
    raise RuntimeError(f"Could not locate the tools root from {source}")


TOOLS_ROOT = _detect_tools_root()
LOCAL_APP_DATA = Path(
    os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
)


def _candidate_ports():
    ports = []

    env_port = os.environ.get("MOBU_COMMAND_PORT") or os.environ.get("MOTIONBUILDER_COMMAND_PORT")
    if env_port:
        try:
            ports.append(int(env_port))
        except Exception:
            pass

    for path in [
        TOOLS_ROOT / "motionbuilder_port.txt",
        LOCAL_APP_DATA / "TA_AI_Studio_MCPHost" / "motionbuilder_port.txt",
    ]:
        try:
            with path.open("r", encoding="utf-8") as f:
                ports.append(int(f.read().strip()))
        except Exception:
            pass

    ports.append(7011)

    seen = set()
    out = []
    for p in ports:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def find_motionbuilder_port(host="127.0.0.1") -> int:
    for port in _candidate_ports():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.25)
                if s.connect_ex((host, port)) == 0:
                    return port
        except Exception:
            pass
    return _candidate_ports()[-1]


def send_to_motionbuilder(code: str, host="127.0.0.1", timeout=10) -> str:
    port = find_motionbuilder_port(host)

    encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
    payload = f"mobu_execute_and_capture('{encoded}')\n"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(payload.encode("utf-8"))

        chunks = []
        try:
            while True:
                data = s.recv(4096)
                if not data:
                    break
                chunk = data.decode("utf-8", errors="replace")
                chunks.append(chunk)
                if "\x00" in chunk:
                    break
        except socket.timeout:
            pass

    return "".join(chunks).replace("\x00", "").strip() or "MotionBuilder returned no output."


@mcp.tool()
def motionbuilder_execute_python(code: str) -> str:
    """Execute Python inside the active MotionBuilder session. Always print results."""
    return send_to_motionbuilder(code)


@mcp.tool()
def motionbuilder_current_file() -> str:
    """Return the current MotionBuilder scene file."""
    code = """
from pyfbsdk import FBApplication
app = FBApplication()
print(app.FBXFileName)
"""
    return send_to_motionbuilder(code)


@mcp.tool()
def motionbuilder_selection() -> str:
    """Return selected MotionBuilder models/components."""
    code = """
from pyfbsdk import FBModelList, FBGetSelectedModels
models = FBModelList()
FBGetSelectedModels(models)
print([m.LongName for m in models])
"""
    return send_to_motionbuilder(code)


@mcp.tool()
def motionbuilder_scene_objects() -> str:
    """Return scene component/model names from MotionBuilder."""
    code = """
from pyfbsdk import FBSystem
scene = FBSystem().Scene
items = []
for comp in scene.Components:
    try:
        items.append(comp.LongName)
    except Exception:
        try:
            items.append(comp.Name)
        except Exception:
            pass
print(items[:500])
"""
    return send_to_motionbuilder(code)


@mcp.tool()
def motionbuilder_takes() -> str:
    """Return all takes in the MotionBuilder scene."""
    code = """
from pyfbsdk import FBSystem
scene = FBSystem().Scene
print([take.Name for take in scene.Takes])
"""
    return send_to_motionbuilder(code)


@mcp.tool()
def motionbuilder_characters() -> str:
    """Return characters in the MotionBuilder scene."""
    code = """
from pyfbsdk import FBSystem, FBCharacter
scene = FBSystem().Scene
chars = []
for comp in scene.Components:
    if isinstance(comp, FBCharacter):
        chars.append(comp.Name)
print(chars)
"""
    return send_to_motionbuilder(code)


if __name__ == "__main__":
    mcp.run()