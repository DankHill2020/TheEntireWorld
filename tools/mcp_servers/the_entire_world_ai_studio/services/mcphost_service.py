"""MCPHost lifecycle and output processing."""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from bridges.blender.blender_bridge import BlenderBridge
from bridges.maya.maya_bridge import MayaBridge
from bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
from bridges.unity.unity_bridge import UnityBridge
from bridges.unreal.unreal_bridge import UnrealBridge
from models.constants import ANSI_RE, DEFAULT_MCPHOST, V2_DB
from models.project import all_roots
from services.settings_service import install_components_to_tools, save_settings
from dataclasses import dataclass

from services.ollama_service import (
    AI_MODELS,
    FALLBACK_CODE_MODEL,
    FALLBACK_GENERAL_MODEL,
    as_mcphost_model,
)
from services.model_provider_service import (
    is_provider_model,
    is_credit_or_quota_failure,
    provider_status_lines,
    resolve_model_for_policy,
)
from bridges.mcphost_bridge import TerminalBridge
if TYPE_CHECKING:
    from bridges.mcphost_bridge import TerminalBridge


class MCPHostOutputCleaner:
    """Compact MCPHost Bubble Tea/TUI output for GUI display."""

    def __init__(self):
        self._last_stream_line = ""
        self._seen_tool_results: set[str] = set()
        self._seen_compact_lines: set[str] = set()

    def reset(self):
        self._last_stream_line = ""
        self._seen_tool_results = set()
        self._seen_compact_lines = set()

    def clean(self, text: str) -> str:
        text = ANSI_RE.sub("", text).replace("\x07", "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        while "\b" in text:
            text = re.sub(r".\b", "", text)

        out = []

        for m in re.finditer(r'\\*"result\\*"\\s*:\\s*\\*"([^"]*?)\\*"', text):
            result = m.group(1)
            result = result.encode("utf-8", errors="replace").decode("unicode_escape", errors="replace")
            if result and result not in self._seen_tool_results:
                self._seen_tool_results.add(result)
                out.append("Tool Result:")
                out.append(result)

        for raw in text.splitlines():
            line = raw.strip()
            if not line or line in {"11;?", "11;? "}:
                continue

            if "┃" in line or line in {"┏", "┓", "┗", "┛"}:
                if "Loaded" in line and "tools from MCP servers" in line:
                    m = re.search(r"Loaded\s+(\d+)\s+tools", line)
                    msg = f"Loaded {m.group(1)} tools from MCP servers." if m else "Loaded tools from MCP servers."
                    if msg not in self._seen_compact_lines:
                        self._seen_compact_lines.add(msg)
                        out.append(msg)
                continue

            if line in {"Ty", "Calmay", "Calmaya__maya_se", "_maya_selection and show the raw response.", "ction and show the raw response."}:
                continue
            if line.startswith("Calmaya") or line.startswith("_maya_"):
                continue

            if "Loading Ollama model" in line:
                msg = "Loading Ollama model..."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                continue

            if "Thinking" in line and ("∙" in line or "●" in line or line.endswith("Thinking...")):
                msg = "Thinking..."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                continue

            if "Executing maya__" in line or "Executing knowledge__" in line or "Executing motionbuilder__" in line or "Executing unreal" in line.lower():
                msg = line
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                continue

            if "Model loaded successfully on GPU" in line:
                msg = "✓ Model loaded successfully on GPU."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                continue

            if "Model loaded:" in line:
                msg = line
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                continue

            if "tools from MCP servers" in line:
                msg = line
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                continue

            if "Enter your prompt" in line or "Type your message" in line or "enter submit" in line:
                msg = "MCPHost ready for input."
                if msg not in self._seen_compact_lines:
                    self._seen_compact_lines.add(msg)
                    out.append(msg)
                continue

            if "Finished without output" in line:
                continue

            if "Goodbye!" in line:
                out.append("MCPHost exited.")
                continue

            if line == self._last_stream_line:
                continue
            self._last_stream_line = line

            out.append(raw)

        return ("\n".join(out) + "\n") if out else ""


def build_health_check_message(bridge, mcphost_ready: bool) -> str:
    msg = []
    msg.append("Health Check")
    msg.append(f"Knowledge DB: {'OK' if V2_DB.exists() else 'Missing'}")
    msg.append(f"MCPHost: {'Running' if bridge.running else 'Stopped'}")
    msg.append(f"Ready marker seen: {'Yes' if mcphost_ready else 'No'}")
    msg.append("")

    maya = MayaBridge()
    port = maya.find_port()
    msg.append(f"Maya commandPort: {'OK :' + str(port) if port else 'Not found'}")
    msg.append("Maya test: use direct button 'Maya Selection' after Maya commandPort is running.")

    unreal = UnrealBridge()
    unreal_port = unreal.find_port()
    msg.append(f"Unreal HTTP bridge: {'OK :' + str(unreal_port) if unreal_port else 'Not found'}")
    msg.append("Unreal test: use direct buttons after Unreal HTTP bridge is running.")
    blender = BlenderBridge()
    blender_port = blender.find_port()
    msg.append(f"Blender socket bridge: {'OK :' + str(blender_port) if blender_port else 'Not found'}")
    msg.append("Blender test: run Install_Blender_AI_Studio_Bridge.bat once, restart Blender, then use Tools > Blender.")
    substance = SubstancePainterBridge()
    substance_port = substance.find_port()
    msg.append(f"Substance Painter socket bridge: {'OK :' + str(substance_port) if substance_port else 'Not found'}")
    msg.append("Substance Painter test: install the bridge, restart Painter, then use Tools > Substance Painter.")
    unity = UnityBridge()
    unity_port = unity.find_port()
    msg.append(f"Unity socket bridge: {'OK :' + str(unity_port) if unity_port else 'Not found'}")
    msg.append("Unity test: ensure the Unity Editor bridge plugin is running on port 7041.")
    msg.append("")
    msg.append("Model Providers")
    msg.extend(provider_status_lines())
    msg.append("MotionBuilder is optional and will stay inactive unless configured.")
    return "\n".join(msg)


def start_mcphost(
    bridge,
    settings: dict,
    model: str,
    config: str,
    use_pty: bool,
) -> tuple[bool, str, list[str]]:
    """
    Start MCPHost process.
    Returns (success, command_display, error_message).
    """
    if bridge.running:
        return False, "", "Already running"

    install_components_to_tools()

    mcphost = DEFAULT_MCPHOST
    settings["model"] = model
    settings["config"] = config
    save_settings(settings)

    if not Path(mcphost).exists():
        return False, "", f"Could not find:\n{mcphost}"
    if not Path(config).exists():
        return False, "", f"Could not find:\n{config}"

    cmd_args = [mcphost, "-m", model, "--config", config]
    if not use_pty:
        cmd_args.append("--compact")
    cmd_display = subprocess.list2cmdline(cmd_args)
    python_path_parts = [
        str(Path(__file__).resolve().parent.parent),
        str(Path(__file__).resolve().parent.parent.parent.parent),
    ]
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        python_path_parts.append(existing_pythonpath)
    env = {
        "AI_KNOWLEDGE_ROOTS": ";".join(all_roots(settings)),
        "PYTHONPATH": os.pathsep.join(python_path_parts),
    }
    bridge.start(cmd_args, env=env, use_pty=use_pty)
    return True, cmd_display, ""

ROLE_TO_MODEL = {
    "general": as_mcphost_model(AI_MODELS["general"]),
    "plan": as_mcphost_model(AI_MODELS["plan"]),
    "docs": as_mcphost_model(AI_MODELS["docs"]),
    "code": as_mcphost_model(AI_MODELS["code"]),
    "debug": as_mcphost_model(AI_MODELS["debug"]),
    "dcc": as_mcphost_model(AI_MODELS["dcc"]),
    "maya": as_mcphost_model(AI_MODELS["maya"]),
    "unreal": as_mcphost_model(AI_MODELS["unreal"]),
}

FALLBACK_ROLE_TO_MODEL = {
    "general": as_mcphost_model(FALLBACK_GENERAL_MODEL),
    "plan": as_mcphost_model(FALLBACK_GENERAL_MODEL),
    "docs": as_mcphost_model(FALLBACK_GENERAL_MODEL),
    "code": as_mcphost_model(FALLBACK_CODE_MODEL),
    "debug": as_mcphost_model(FALLBACK_CODE_MODEL),
    "dcc": as_mcphost_model(FALLBACK_CODE_MODEL),
    "maya": as_mcphost_model(FALLBACK_CODE_MODEL),
    "unreal": as_mcphost_model(FALLBACK_CODE_MODEL),
}


def as_configured_model(model: str) -> str:
    model = (model or "").strip()
    if is_provider_model(model):
        return model
    return as_mcphost_model(model)


@dataclass
class MCPHostSession:
    role: str
    model: str
    bridge: TerminalBridge
    cleaner: MCPHostOutputCleaner
    running: bool = False
    ready: bool = False


class MCPHostManager:
    def __init__(self, settings):
        self.settings = settings
        self.sessions = {}
        self.use_fallback_models = bool(settings.get("use_fallback_models", False))

    def set_use_fallback_models(self, enabled):
        self.use_fallback_models = bool(enabled)

    def get_model_for_role(self, role):
        local_models = FALLBACK_ROLE_TO_MODEL if self.use_fallback_models else ROLE_TO_MODEL
        local_model = local_models.get(role, local_models["general"])

        if f"{role}_model" in self.settings:
            return resolve_model_for_policy(as_configured_model(self.settings[f"{role}_model"]), local_model, self.settings)
        if "general_model" in self.settings and role in {"general", "plan", "docs"}:
            return resolve_model_for_policy(as_configured_model(self.settings["general_model"]), local_model, self.settings)
        if "code_model" in self.settings and role in {"code", "debug", "dcc", "maya", "unreal"}:
            return resolve_model_for_policy(as_configured_model(self.settings["code_model"]), local_model, self.settings)
        if "model" in self.settings:
            return resolve_model_for_policy(as_configured_model(self.settings["model"]), local_model, self.settings)

        return local_model

    def get_session(self, role):
        role = role or "general"

        if role in self.sessions:
            return self.sessions[role]

        session = MCPHostSession(
            role=role,
            model=self.get_model_for_role(role),
            bridge=TerminalBridge(),
            cleaner=MCPHostOutputCleaner(),
        )
        self.sessions[role] = session
        return session

    def start_session(self, role, config, use_pty=False, model_override=""):
        session = self.get_session(role)

        if session.bridge.running:
            session.running = True
            return True, f"{role} session already running.", ""

        session.model = model_override or self.get_model_for_role(role)

        ok, cmd_display, error = start_mcphost(
            bridge=session.bridge,
            settings=self.settings,
            model=session.model,
            config=config,
            use_pty=use_pty,
        )

        session.running = ok
        return ok, cmd_display, error

    def send(self, role, prompt):
        session = self.get_session(role)

        if not session.bridge.running:
            return False, f"{role} MCPHost session is not running."

        ok = session.bridge.write(prompt)

        if not ok:
            return False, f"Failed sending prompt to {role} MCPHost session."

        return True, f"Sent to {role} session."

    def mark_cloud_unavailable_if_needed(self, text):
        if is_credit_or_quota_failure(text):
            self.settings["cloud_model_unavailable"] = True
            return True
        return False

    def stop_session(self, role):
        session = self.sessions.get(role)
        if not session:
            return

        session.bridge.stop()
        session.running = False
        session.ready = False

    def stop_all(self):
        for session in self.sessions.values():
            session.bridge.stop()
            session.running = False
            session.ready = False
