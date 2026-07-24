"""Common bridge contracts for host application integrations.

Two layers:
  HostBridge   – minimal legacy Protocol used by existing bridge code.
  DCCAdapter   – full ABC used by the planner model; every DCC bridge must
                 implement this so the router can swap backends transparently.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple


# ---------------------------------------------------------------------------
# Legacy thin protocol (kept for backward-compat with existing bridge code)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HostBridgeInfo:
    """Public metadata used by the UI, registry, and contributor docs."""
    id: str
    display_name: str
    protocol: str
    default_port: Optional[int] = None
    setup_script: Optional[str] = None
    supports_direct_execute: bool = False
    supports_mcp: bool = False


class HostBridge(Protocol):
    """Minimum direct bridge shape for apps that can execute local commands."""

    info: HostBridgeInfo

    def find_port(self, host: str = "127.0.0.1"):
        """Return the active localhost port, or None if the host is unavailable."""

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        """Execute app-native script code and return (success, output)."""

    def get_selection_code(self) -> str:
        """Return app-native code that prints the current selection."""

    def get_current_file_code(self) -> str:
        """Return app-native code that prints the current file, scene, or document."""

    def get_scene_objects_code(self) -> str:
        """Return app-native code that prints top-level scene/document objects."""


def call_python_function_via_execute(
    bridge: HostBridge,
    function_path: str,
    args: Optional[Sequence[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    sys_paths: Optional[Sequence[str]] = None,
) -> tuple[bool, str]:
    """Call an importable Python function through a host bridge execute method."""
    payload = {
        "function": function_path,
        "args": list(args or []),
        "kwargs": dict(kwargs or {}),
    }
    paths_repr = repr(list(sys_paths or []))
    code = f"""
import sys, importlib, traceback
for p in {paths_repr}:
    if p not in sys.path:
        sys.path.append(p)

payload = {repr(payload)}
try:
    module_path, func_name = payload["function"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    result = func(*payload.get("args", []), **payload.get("kwargs", {{}}))
    print(result)
except Exception:
    traceback.print_exc()
"""
    return bridge.execute(code)


# ---------------------------------------------------------------------------
# Full DCC Adapter ABC — all bridges must implement this
# ---------------------------------------------------------------------------

class DCCAdapter(ABC):
    """Abstract base class for DCC application adapters.

    The planner model talks exclusively to this interface.  It does not care
    whether the backend is:
      - Maya commandPort (TCP)
      - MotionBuilder Telnet
      - Unreal HTTP / Python
      - Blender sockets
      - Substance Painter REST

    Every adapter must implement all abstract methods.  Adapters may raise
    ``DCCNotAvailableError`` from any method if the host application is not
    running.
    """

    # ---- Identity -------------------------------------------------------

    @property
    @abstractmethod
    def app_name(self) -> str:
        """Human-readable DCC application name, e.g. 'Unreal', 'Maya'."""

    @property
    def is_available(self) -> bool:
        """Return True if the DCC application is currently reachable."""
        try:
            return self.query_state().get("connected", False)
        except Exception:
            return False

    # ---- Core execution -------------------------------------------------

    @abstractmethod
    def execute_python(self, code: str, timeout: float = 30.0) -> Tuple[bool, str]:
        """Execute arbitrary Python code inside the DCC application.

        Returns (success, output_or_error_string).
        """

    # ---- Scene / project state ------------------------------------------

    @abstractmethod
    def list_scene(self) -> List[Dict[str, Any]]:
        """Return a list of top-level objects in the current scene / level.

        Each dict should have at least: ``name``, ``type``, ``path``.
        """

    @abstractmethod
    def get_selection(self) -> List[Dict[str, Any]]:
        """Return currently selected objects in the DCC viewport / content browser."""

    @abstractmethod
    def query_state(self) -> Dict[str, Any]:
        """Return a dict describing the current application state.

        Minimum keys: ``connected`` (bool), ``app_name`` (str),
        ``open_file`` (str | None), ``version`` (str).
        """

    # ---- Asset I/O ------------------------------------------------------

    @abstractmethod
    def import_asset(self, source_path: str, destination: str, **options) -> Tuple[bool, str]:
        """Import an asset from *source_path* into the DCC project at *destination*.

        Returns (success, message).
        """

    @abstractmethod
    def export_asset(self, asset_path: str, output_path: str, **options) -> Tuple[bool, str]:
        """Export *asset_path* to *output_path* on disk.

        Returns (success, message).
        """

    # ---- Tool invocation ------------------------------------------------

    @abstractmethod
    def run_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Invoke a named tool or editor utility by name.

        Returns a result dict with at minimum: ``success`` (bool), ``message`` (str).
        """

    # ---- Convenience wrappers (can be overridden) -----------------------

    def get_open_file(self) -> Optional[str]:
        """Return the path of the currently open scene/project, or None."""
        return self.query_state().get("open_file")

    def execute_and_capture(self, code: str) -> str:
        """Execute Python code and return the output as a string (raises on error)."""
        ok, output = self.execute_python(code)
        if not ok:
            raise RuntimeError(f"[{self.app_name}] {output}")
        return output

    # ---- Smart operation helpers ---------------------------------------

    def build_context_summary(self) -> str:
        """Return a concise host understanding block.

        Adapters can override this for deeper, host-specific context. The base
        implementation intentionally uses only the abstract contract so every
        DCC gets a useful baseline without duplicate per-host code.
        """
        state = self.query_state()
        selection = self.get_selection()
        scene = self.list_scene()
        lines = [
            f"# {self.app_name} Context",
            f"- Connected: {state.get('connected', False)}",
            f"- Open file: {state.get('open_file') or 'None'}",
            f"- Version: {state.get('version') or 'unknown'}",
            f"- Selection count: {len(selection)}",
            f"- Scene item count: {len(scene)}",
        ]
        for item in selection[:8]:
            lines.append(f"  - Selected: {item.get('path') or item.get('name')} ({item.get('type', 'unknown')})")
        for item in scene[:8]:
            lines.append(f"  - Scene: {item.get('path') or item.get('name')} ({item.get('type', 'unknown')})")
        return "\n".join(lines)

    def build_understanding_report(self, question: str = "") -> Dict[str, Any]:
        """Return structured facts for answer/explanation requests."""
        return {
            "host": self.app_name,
            "mode": "understand",
            "question": question,
            "state": self.query_state(),
            "selection": self.get_selection(),
            "scene_sample": self.list_scene()[:100],
            "context_summary": self.build_context_summary(),
        }

    def build_prototype_plan(self, goal: str, template: str = "", context: str = "") -> Dict[str, Any]:
        """Return a default non-mutating prototype plan.

        Host-specific adapters can override or execute this through
        ``run_tool``. The base plan is deliberately honest: it says what should
        be inspected and does not claim edits happened.
        """
        return {
            "host": self.app_name,
            "mode": "prototype",
            "status": "planned",
            "goal": goal,
            "template": template or "dcc_feature",
            "context_summary": context or self.build_context_summary(),
            "operation_plan": [
                "Inspect current scene and selection.",
                "Identify existing assets/nodes/graphs that match the goal.",
                "Prefer extending existing structures over creating duplicates.",
                "Call a host-specific safe template endpoint before mutating.",
                "Validate and report skipped steps.",
            ],
            "created_or_modified_assets": [],
            "validation_report": "No mutation performed by base adapter plan.",
            "rollback_token": "",
        }

    def build_debug_report(self, goal: str = "", context: str = "") -> Dict[str, Any]:
        """Return a default non-mutating debug report."""
        return {
            "host": self.app_name,
            "mode": "debug",
            "status": "diagnosed",
            "goal": goal,
            "context_summary": context or self.build_context_summary(),
            "checks": [
                "Host reachable",
                "Open file/project recorded",
                "Selection sampled",
                "Scene item sample collected",
            ],
            "issues": [],
            "recommended_fix_order": [
                "Fix missing references or unavailable assets first.",
                "Fix invalid node/component connections.",
                "Fix graph/script/compiler errors.",
                "Re-run debug report.",
            ],
            "save": False,
        }


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class DCCNotAvailableError(RuntimeError):
    """Raised when the target DCC application is not reachable."""

    def __init__(self, app_name: str, reason: str = ""):
        msg = f"{app_name} is not available"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.app_name = app_name
