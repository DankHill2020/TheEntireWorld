# unreal_adapter.py
"""DCCAdapter implementation for Unreal Engine.

Wraps UnrealBridge (HTTP) and UnrealScanner to fulfil the full DCCAdapter
contract so the planner model can use it interchangeably with any other DCC.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from bridges.host_bridge import DCCAdapter, DCCNotAvailableError
from bridges.unreal.unreal_bridge import UnrealBridge
from bridges.unreal.unreal_scanner import UnrealScanner


class UnrealAdapter(DCCAdapter):
    """Full DCCAdapter for Unreal Engine via the HTTP Python bridge."""

    def __init__(self, project_root: Optional[str] = None):
        self._bridge = UnrealBridge()
        self._scanner = UnrealScanner(project_root=project_root)

    # ---- Identity -------------------------------------------------------

    @property
    def app_name(self) -> str:
        return "Unreal"

    # ---- Core execution -------------------------------------------------

    def execute_python(self, code: str, timeout: float = 30.0) -> Tuple[bool, str]:
        """Execute Python code via the canonical Unreal bridge execution path."""
        response = self._bridge.execute_python(code, timeout=timeout)
        ok = bool(response.get("ok") or response.get("success"))
        return ok, json.dumps(response, indent=2, default=str)

    # ---- Scene / project state ------------------------------------------

    def list_scene(self) -> List[Dict[str, Any]]:
        """Return top-level actors in the loaded level."""
        ok, raw = self._bridge.call(
            "[{'name': str(a.get_name()), 'type': a.get_class().get_name(), "
            "'path': str(a.get_path_name())} "
            "for a in unreal.EditorLevelLibrary.get_all_level_actors()]"
        )
        if ok:
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                pass
        return []

    def get_selection(self) -> List[Dict[str, Any]]:
        """Return selected assets from the Content Browser."""
        assets = self._scanner.get_selected_assets()
        return [{"path": a, "type": "asset"} for a in assets]

    def query_state(self) -> Dict[str, Any]:
        """Return Unreal project state."""
        port = self._bridge.find_port()
        if not port:
            return {
                "connected": False,
                "app_name": "Unreal",
                "open_file": None,
                "version": "unknown",
            }
        project = self._scanner.get_open_project()
        return {
            "connected": True,
            "app_name": "Unreal",
            "open_file": project.get("project_dir"),
            "version": "unknown",  # TODO: call unreal.SystemLibrary.get_engine_version()
            "port": port,
            "loaded_level": self._scanner.get_loaded_level(),
        }

    # ---- Asset I/O ------------------------------------------------------

    def import_asset(
        self, source_path: str, destination: str, **options
    ) -> Tuple[bool, str]:
        """Import an external file into the Unreal Content Browser."""
        task_code = (
            f"task = unreal.AssetImportTask(); "
            f"task.set_editor_property('filename', r'{source_path}'); "
            f"task.set_editor_property('destination_path', '{destination}'); "
            f"task.set_editor_property('save', True); "
            f"task.set_editor_property('automated', True); "
            f"unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task]); "
            f"'imported'"
        )
        return self._bridge.call(task_code)

    def export_asset(
        self, asset_path: str, output_path: str, **options
    ) -> Tuple[bool, str]:
        """Export a Unreal asset to disk."""
        task_code = (
            f"task = unreal.AssetExportTask(); "
            f"task.set_editor_property('object', unreal.load_asset('{asset_path}')); "
            f"task.set_editor_property('filename', r'{output_path}'); "
            f"task.set_editor_property('automated', True); "
            f"unreal.Exporter.run_asset_export_task(task); "
            f"'exported'"
        )
        return self._bridge.call(task_code)

    # ---- Tool invocation ------------------------------------------------

    def run_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Run a registered EditorUtility Blueprint or Python tool by name."""
        ok, result = self._bridge.call(
            "unreal.EditorUtilityLibrary.spawn_and_register_tab",
            args=[tool_name],
        )
        return {"success": ok, "message": str(result), "tool": tool_name}

    # ---- Unreal-specific extras ----------------------------------------

    def compile_blueprint(self, asset_path: str) -> Tuple[bool, str]:
        """Compile a Blueprint asset and return (success, log)."""
        return self._bridge.call(
            "unreal.KismetSystemLibrary.compile_blueprint",
            args=[asset_path],
        )

    def build_context_summary(self) -> str:
        """Return a concise text summary for LLM context injection."""
        return self._scanner.build_context_summary()

    def build_local_intelligence_context(self, request: str = "") -> str:
        """Return model-ready context from the reusable DCC local intelligence DB."""
        return self._scanner.build_local_intelligence_context(request)

    def refresh_project_intelligence(self) -> Dict[str, Any]:
        """Run a live scan and persist it into the local intelligence DB."""
        return self._scanner.scan_all()

    def inspect_blueprint_graph(self, asset_path: str) -> Dict[str, Any]:
        response = self._bridge.inspect_blueprint_graph(asset_path, timeout=10.0)
        data = response.get("data")
        return (
            data
            if isinstance(data, dict)
            else {"ok": False, "error": response.get("error")}
        )

    def get_context_summary(self) -> str:
        """Backward-compatible alias for older call sites."""
        return self.build_context_summary()
