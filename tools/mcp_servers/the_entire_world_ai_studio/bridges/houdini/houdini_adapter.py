# houdini_adapter.py
"""DCCAdapter implementation for SideFX Houdini.

Wraps HoudiniBridge (socket) to fulfil the full DCCAdapter contract
so the planner model can use it interchangeably with any other DCC.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from bridges.host_bridge import DCCAdapter, DCCNotAvailableError


class HoudiniAdapter(DCCAdapter):
    """Full DCCAdapter for SideFX Houdini via the socket Python bridge."""

    def __init__(self):
        self._bridge = None

    def _get_bridge(self):
        if self._bridge is None:
            from bridges.houdini.houdini_bridge import HoudiniBridge
            self._bridge = HoudiniBridge()
        return self._bridge

    # ---- Identity -------------------------------------------------------

    @property
    def app_name(self) -> str:
        return "Houdini"

    @property
    def is_available(self) -> bool:
        bridge = self._get_bridge()
        return bridge.find_port() is not None

    # ---- Core execution -------------------------------------------------

    def execute_python(self, code: str, timeout: float = 30.0) -> Tuple[bool, str]:
        """Execute Python code in Houdini's embedded interpreter."""
        bridge = self._get_bridge()
        try:
            result = bridge.execute(code, timeout=timeout)
            if isinstance(result, tuple):
                return result
            return True, str(result)
        except Exception as e:
            return False, str(e)

    # ---- Scene / project state ------------------------------------------

    def list_scene(self) -> List[Dict[str, Any]]:
        """Return top-level nodes in the Houdini scene (obj/ level)."""
        code = """
import hou, json
nodes = hou.node('/obj').children() if hou.node('/obj') else []
result = [{"name": n.name(), "type": n.type().name(), "path": n.path()} for n in nodes[:200]]
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
        """Return currently selected nodes."""
        code = """
import hou, json
sel = hou.selectedNodes()
result = [{"name": n.name(), "type": n.type().name(), "path": n.path()} for n in sel]
print(json.dumps(result))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def query_state(self) -> Dict[str, Any]:
        """Return Houdini session state."""
        code = """
import hou, json
hip = hou.hipFile
print(json.dumps({
    "connected": True,
    "app_name": "Houdini",
    "open_file": hip.path() if hip.name() != "untitled.hip" else None,
    "version": hou.applicationVersionString(),
    "fps": hou.fps(),
    "frame_start": int(hou.playbar.frameRange()[0]),
    "frame_end": int(hou.playbar.frameRange()[1]),
    "current_frame": int(hou.frame()),
    "hip_name": hip.name(),
    "has_unsaved_changes": hip.hasUnsavedChanges(),
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
            "app_name": "Houdini",
            "open_file": None,
            "version": "unknown",
        }

    # ---- Deep awareness -------------------------------------------------

    def get_geo_nodes(self) -> List[Dict[str, Any]]:
        """Return all geometry-containing (SOP) nodes."""
        code = """
import hou, json
geo_nodes = [n for n in hou.node('/obj').allSubChildren() if n.type().category().name() == 'Sop']
result = [{"name": n.name(), "path": n.path(), "type": n.type().name()} for n in geo_nodes[:100]]
print(json.dumps(result))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def get_networks(self) -> List[Dict[str, Any]]:
        """Return top-level networks (obj children) with child counts."""
        code = """
import hou, json
obj = hou.node('/obj')
if obj:
    result = [{"name": n.name(), "type": n.type().name(), "path": n.path(),
               "child_count": len(n.children())} for n in obj.children()]
else:
    result = []
print(json.dumps(result))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def build_context_summary(self) -> str:
        """Return a concise text block for LLM context injection."""
        state = self.query_state()
        if not state.get("connected"):
            return "Houdini: not connected."
        selection = self.get_selection()
        networks = self.get_networks()
        lines = [
            "# Houdini Scene State",
            f"- File: {state.get('open_file') or 'Untitled'}",
            f"- Houdini {state.get('version')} | FPS: {state.get('fps')}",
            f"- Frame range: {state.get('frame_start')} – {state.get('frame_end')} (current: {state.get('current_frame')})",
            f"- Top-level networks: {len(networks)}",
        ]
        for n in networks[:8]:
            lines.append(f"  - {n['name']} ({n['type']}) [{n.get('child_count', 0)} children]")
        lines.append(f"- Selection: {len(selection)} node(s)")
        for s in selection[:5]:
            lines.append(f"  - {s['path']} ({s['type']})")
        return "\n".join(lines)

    # ---- Asset I/O ------------------------------------------------------

    def import_asset(self, source_path: str, destination: str = "", **options) -> Tuple[bool, str]:
        """Import a file into the current Houdini scene as a File SOP or USD stage."""
        network = destination or "/obj"
        code = f"""
import hou
geo = hou.node({network!r}) or hou.node('/obj').createNode('geo', 'ai_import')
file_sop = geo.createNode('file', 'ai_import_file')
file_sop.parm('file').set(r'{source_path}')
file_sop.parm('loadtype').set(0)
print('imported')
"""
        return self.execute_python(code.strip())

    def export_asset(self, asset_path: str, output_path: str, **options) -> Tuple[bool, str]:
        """Export a Houdini geometry or scene element."""
        code = f"""
import hou
node = hou.node({asset_path!r})
if node and hasattr(node, 'geometry'):
    geo = node.geometry()
    geo.saveToFile(r'{output_path}')
    print('exported')
else:
    print('node not found or has no geometry')
"""
        return self.execute_python(code.strip())

    # ---- Tool invocation ------------------------------------------------

    def run_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Run a Houdini HDA or Python shelf tool by name."""
        code = f"""
import hou, json
try:
    # Try shelf tool
    tool = hou.shelves.tool({tool_name!r})
    if tool:
        tool.script(None, None)
        print(json.dumps({{"success": True, "message": "Tool executed", "tool": {tool_name!r}}}))
    else:
        print(json.dumps({{"success": False, "message": f"Tool not found: {tool_name}"}}))
except Exception as e:
    print(json.dumps({{"success": False, "message": str(e)}}))
"""
        ok, raw = self.execute_python(code.strip())
        try:
            return json.loads(raw)
        except Exception:
            return {"success": ok, "message": raw, "tool": tool_name}
