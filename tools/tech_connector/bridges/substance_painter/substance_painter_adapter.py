# substance_painter_adapter.py
"""DCCAdapter implementation for Adobe Substance 3D Painter.

Wraps SubstancePainterBridge (socket) to fulfil the full DCCAdapter
contract so the planner model can use it interchangeably with any DCC.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from tech_connector.bridges.host_bridge import DCCAdapter, DCCNotAvailableError


class SubstancePainterAdapter(DCCAdapter):
    """Full DCCAdapter for Adobe Substance 3D Painter via socket bridge."""

    def __init__(self):
        self._bridge = None

    def _get_bridge(self):
        if self._bridge is None:
            from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
            self._bridge = SubstancePainterBridge()
        return self._bridge

    # ---- Identity -------------------------------------------------------

    @property
    def app_name(self) -> str:
        return "Substance Painter"

    @property
    def is_available(self) -> bool:
        bridge = self._get_bridge()
        return bridge.find_port() is not None

    # ---- Core execution -------------------------------------------------

    def execute_python(self, code: str, timeout: float = 10.0) -> Tuple[bool, str]:
        """Execute Python code in Substance Painter's embedded interpreter."""
        bridge = self._get_bridge()
        try:
            return bridge.execute(code, timeout=timeout)
        except Exception as e:
            return False, str(e)

    # ---- Scene / project state ------------------------------------------

    def list_scene(self) -> List[Dict[str, Any]]:
        """Return all texture sets in the current Substance Painter project."""
        code = """
import substance_painter.textureset as ts
import json
result = []
for texture_set in ts.all_texture_sets():
    try:
        channels = [str(c) for c in texture_set.get_stack().all_channels()]
    except Exception:
        channels = []
    result.append({"name": texture_set.name(), "channels": channels})
print(json.dumps(result))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def get_selection(self) -> List[Dict[str, Any]]:
        """Return the currently active texture set in Substance Painter."""
        code = """
import substance_painter.textureset as ts
import json
try:
    active = ts.get_active_stack()
    if active:
        name = active.material().name() if hasattr(active.material(), 'name') else str(active)
        result = [{"name": name, "type": "TextureSetStack"}]
    else:
        result = []
    print(json.dumps(result))
except Exception as e:
    print(json.dumps([]))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def query_state(self) -> Dict[str, Any]:
        """Return Substance Painter session state."""
        code = """
import substance_painter.project as project
import json
try:
    is_open = project.is_open()
    file_path = project.file_path() if is_open else None
    print(json.dumps({
        "connected": True,
        "app_name": "Substance Painter",
        "open_file": file_path,
        "project_open": is_open,
    }))
except Exception as e:
    print(json.dumps({
        "connected": True,
        "app_name": "Substance Painter",
        "open_file": None,
        "project_open": False,
        "error": str(e),
    }))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {
            "connected": False,
            "app_name": "Substance Painter",
            "open_file": None,
            "project_open": False,
        }

    # ---- Deep awareness -------------------------------------------------

    def get_texture_sets(self) -> List[Dict[str, Any]]:
        """Return all texture sets with channel info."""
        return self.list_scene()

    def get_layers(self, texture_set_name: str = "") -> List[Dict[str, Any]]:
        """Return layers for a texture set."""
        code = f"""
import substance_painter.textureset as ts
import json
try:
    sets = ts.all_texture_sets()
    target_name = {texture_set_name!r}
    if target_name:
        sets = [s for s in sets if s.name() == target_name]
    result = []
    for tex_set in sets[:1]:
        stack = tex_set.get_stack()
        layers = stack.all_layers() if hasattr(stack, 'all_layers') else []
        for layer in layers[:50]:
            result.append({{"name": str(layer.get_name()), "type": str(layer.get_type()), "texture_set": tex_set.name()}})
    print(json.dumps(result))
except Exception as e:
    print(json.dumps([]))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def get_export_settings(self) -> Dict[str, Any]:
        """Return current export settings for the project."""
        code = """
import substance_painter.export as export
import json
try:
    config = export.get_current_configuration()
    print(json.dumps({"config": str(config), "connected": True}))
except Exception as e:
    print(json.dumps({"error": str(e), "connected": True}))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {}

    def build_context_summary(self) -> str:
        """Return a concise text block for LLM context injection."""
        state = self.query_state()
        if not state.get("connected"):
            return "Substance Painter: not connected."
        texture_sets = self.get_texture_sets()
        lines = [
            "# Substance Painter Scene State",
            f"- Project: {state.get('open_file') or 'No project open'}",
            f"- Project open: {state.get('project_open', False)}",
            f"- Texture sets: {len(texture_sets)}",
        ]
        for ts in texture_sets[:10]:
            channels = ts.get("channels", [])
            channels_str = ", ".join(channels[:5]) if channels else "none"
            lines.append(f"  - {ts['name']} (channels: {channels_str})")
        return "\n".join(lines)

    # ---- Asset I/O ------------------------------------------------------

    def import_asset(self, source_path: str, destination: str = "", **options) -> Tuple[bool, str]:
        """Import a resource into Substance Painter."""
        code = f"""
import substance_painter.resource as resource
import json
try:
    url = resource.ResourceID.from_url("file:///{source_path}")
    result = resource.import_session_resource(url.url(), resource.Usage.BASE_COLOR)
    print(json.dumps({{"ok": True, "message": "Resource imported"}}))
except Exception as e:
    print(json.dumps({{"ok": False, "message": str(e)}}))
"""
        return self.execute_python(code.strip())

    def export_asset(self, asset_path: str, output_path: str, **options) -> Tuple[bool, str]:
        """Export textures from the current Substance Painter project."""
        code = f"""
import substance_painter.export as export
import json
try:
    result = export.export_project_textures({{
        "exportPath": r"{output_path}",
        "exportShaderParams": False,
    }})
    print(json.dumps({{"ok": True, "message": "Textures exported", "result": str(result)}}))
except Exception as e:
    print(json.dumps({{"ok": False, "message": str(e)}}))
"""
        ok, raw = self.execute_python(code.strip())
        try:
            data = json.loads(raw)
            return data.get("ok", ok), data.get("message", raw)
        except Exception:
            return ok, raw

    # ---- Tool invocation ------------------------------------------------

    def run_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Run a Substance Painter action or Python callable by name."""
        code = f"""
import substance_painter
import json
try:
    # Try to call as Python function/attribute
    parts = {tool_name!r}.split('.')
    obj = substance_painter
    for part in parts:
        obj = getattr(obj, part)
    if callable(obj):
        result = obj(**{kwargs!r})
    else:
        result = str(obj)
    print(json.dumps({{"success": True, "message": str(result)}}))
except Exception as e:
    print(json.dumps({{"success": False, "message": str(e)}}))
"""
        ok, raw = self.execute_python(code.strip())
        try:
            return json.loads(raw)
        except Exception:
            return {"success": ok, "message": raw, "tool": tool_name}
