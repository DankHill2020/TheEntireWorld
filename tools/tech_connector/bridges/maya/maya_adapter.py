# maya_adapter.py
"""DCCAdapter implementation for Autodesk Maya.

Deep context awareness:
- Scene hierarchy (DAG nodes, transforms, shapes)
- Current selection with full attribute state
- Rigging: joints, skin clusters, constraints, HIK
- Animation: keyframes, curves, take list, playback range
- File & workspace state
- Plugin list
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from tech_connector.bridges.host_bridge import DCCAdapter, DCCNotAvailableError


class MayaAdapter(DCCAdapter):
    """Full DCCAdapter for Autodesk Maya via the authenticated JSON bridge."""

    DEFAULT_PORT = 8192

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self._host = host
        self._port = port
        # Import existing bridge lazily so we don't crash if Maya isn't up
        self._bridge = None

    def _get_bridge(self):
        if self._bridge is None:
            from tech_connector.bridges.maya.maya_bridge import MayaBridge
            self._bridge = MayaBridge()
        return self._bridge

    # ---- Identity -------------------------------------------------------

    @property
    def app_name(self) -> str:
        return "Maya"

    @property
    def is_available(self) -> bool:
        bridge = self._get_bridge()
        return bridge.find_port() is not None

    # ---- Core execution -------------------------------------------------

    def execute_python(self, code: str, timeout: float = 30.0) -> Tuple[bool, str]:
        """Execute Python code in Maya's embedded interpreter."""
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
        """Return all DAG nodes in the scene with type and path."""
        code = """
import maya.cmds as cmds, json
nodes = cmds.ls(dagObjects=True, long=True) or []
result = []
for n in nodes[:200]:  # cap for performance
    try:
        ntype = cmds.nodeType(n)
        parent = cmds.listRelatives(n, parent=True, fullPath=True) or []
        result.append({"path": n, "type": ntype, "name": n.split("|")[-1],
                       "parent": parent[0] if parent else ""})
    except Exception:
        pass
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
        """Return currently selected nodes with full attribute context."""
        code = """
import maya.cmds as cmds, json
sel = cmds.ls(selection=True, long=True) or []
result = []
for n in sel:
    try:
        ntype = cmds.nodeType(n)
        attrs = {}
        for a in (cmds.listAttr(n, keyable=True) or [])[:20]:
            try:
                attrs[a] = cmds.getAttr(f"{n}.{a}")
            except Exception:
                pass
        result.append({"path": n, "name": n.split("|")[-1], "type": ntype, "attrs": attrs})
    except Exception:
        pass
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
        """Return Maya workspace and scene state."""
        code = """
import maya.cmds as cmds, json
print(json.dumps({
    "connected":    True,
    "app_name":     "Maya",
    "open_file":    cmds.file(query=True, sceneName=True) or None,
    "version":      cmds.about(version=True),
    "fps":          cmds.currentUnit(query=True, time=True),
    "frame_start":  cmds.playbackOptions(query=True, minTime=True),
    "frame_end":    cmds.playbackOptions(query=True, maxTime=True),
    "current_frame":cmds.currentTime(query=True),
    "renderer":     cmds.getAttr("defaultRenderGlobals.currentRenderer"),
    "up_axis":      cmds.upAxis(query=True, axis=True),
}))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {"connected": False, "app_name": "Maya", "open_file": None, "version": "unknown"}

    # ---- Deep awareness -------------------------------------------------

    def get_rigs(self) -> List[Dict[str, Any]]:
        """Return all joint hierarchies (rigs) in the scene."""
        code = """
import maya.cmds as cmds, json
roots = [j for j in (cmds.ls(type="joint", long=True) or [])
         if not cmds.listRelatives(j, parent=True, type="joint")]
result = []
for r in roots:
    children = cmds.listRelatives(r, allDescendents=True, type="joint") or []
    result.append({"root": r, "joint_count": len(children)+1, "name": r.split("|")[-1]})
print(json.dumps(result))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def get_skin_clusters(self) -> List[Dict[str, Any]]:
        """Return all skin cluster nodes with their influences."""
        code = """
import maya.cmds as cmds, json
clusters = cmds.ls(type="skinCluster") or []
result = []
for sc in clusters:
    geo = cmds.skinCluster(sc, query=True, geometry=True) or []
    infl = cmds.skinCluster(sc, query=True, influence=True) or []
    result.append({"name": sc, "geometry": geo, "influences": infl, "influence_count": len(infl)})
print(json.dumps(result))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def get_animation_curves(self) -> Dict[str, Any]:
        """Return summary of animation curves and keyframe ranges."""
        code = """
import maya.cmds as cmds, json
curves = cmds.ls(type="animCurve") or []
start = cmds.playbackOptions(q=True, animationStartTime=True)
end   = cmds.playbackOptions(q=True, animationEndTime=True)
print(json.dumps({"curve_count": len(curves), "anim_start": start, "anim_end": end,
                  "sample_curves": curves[:10]}))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {}

    def get_loaded_plugins(self) -> List[str]:
        """Return list of currently loaded Maya plugins."""
        code = """
import maya.cmds as cmds, json
print(json.dumps(cmds.pluginInfo(query=True, listPlugins=True) or []))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def get_namespaces(self) -> List[str]:
        """Return all non-default namespaces (useful for referencing)."""
        code = """
import maya.cmds as cmds, json
ns = cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or []
print(json.dumps([n for n in ns if n not in ("UI", "shared")]))
"""
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return []

    def get_references(self) -> List[Dict[str, Any]]:
        """Return all file references in the scene."""
        code = """
import maya.cmds as cmds, json
refs = cmds.ls(references=True) or []
result = []
for r in refs:
    try:
        path = cmds.referenceQuery(r, filename=True)
        ns   = cmds.referenceQuery(r, namespace=True)
        loaded = cmds.referenceQuery(r, isLoaded=True)
        result.append({"node": r, "path": path, "namespace": ns, "loaded": loaded})
    except Exception:
        pass
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
            return "Maya: not connected."
        rigs     = self.get_rigs()
        clusters = self.get_skin_clusters()
        anim     = self.get_animation_curves()
        refs     = self.get_references()
        plugins  = self.get_loaded_plugins()
        lines = [
            f"# Maya Scene State",
            f"- File: {state.get('open_file') or 'Untitled'}",
            f"- Maya {state.get('version')} | FPS: {state.get('fps')} | Up: {state.get('up_axis')}",
            f"- Frame range: {state.get('frame_start')} – {state.get('frame_end')} (current: {state.get('current_frame')})",
            f"- Renderer: {state.get('renderer')}",
            f"- Rigs: {len(rigs)} root joint(s)",
        ]
        for r in rigs[:5]:
            lines.append(f"  - {r['name']} ({r['joint_count']} joints)")
        lines += [
            f"- Skin clusters: {len(clusters)}",
            f"- Anim curves: {anim.get('curve_count', 0)} | range: {anim.get('anim_start')} – {anim.get('anim_end')}",
            f"- File references: {len(refs)}",
            f"- Loaded plugins: {len(plugins)}",
        ]
        if plugins:
            lines.append(f"  ({', '.join(plugins[:8])}{'...' if len(plugins)>8 else ''})")
        return "\n".join(lines)

    # ---- Asset I/O ------------------------------------------------------

    def import_asset(self, source_path: str, destination: str = "", **options) -> Tuple[bool, str]:
        """Import a file into the current Maya scene."""
        ns = options.get("namespace", "imported")
        code = f"""
import maya.cmds as cmds
cmds.file(r"{source_path}", i=True, namespace="{ns}",
          ignoreVersion=True, mergeNamespacesOnClash=False)
print("imported")
"""
        return self.execute_python(code.strip())

    def export_asset(self, asset_path: str, output_path: str, **options) -> Tuple[bool, str]:
        """Export selected objects or the whole scene."""
        export_all = options.get("export_all", False)
        file_type  = options.get("file_type", "FBX export")
        sel_flag   = "all=True" if export_all else "preserveReferences=True"
        code = f"""
import maya.cmds as cmds
cmds.file(r"{output_path}", force=True, type="{file_type}", {sel_flag},
          exportSelected={not export_all})
print("exported")
"""
        return self.execute_python(code.strip())

    # ---- Tool invocation ------------------------------------------------

    def run_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Run a Maya MEL procedure or Python callable by name."""
        code = f"""
import maya.cmds as cmds, json
try:
    result = eval("{tool_name}")
    print(json.dumps({{"success": True, "message": str(result)}}))
except Exception as e:
    print(json.dumps({{"success": False, "message": str(e)}}))
"""
        ok, raw = self.execute_python(code.strip())
        try:
            return json.loads(raw)
        except Exception:
            return {"success": ok, "message": raw}


if __name__ == "__main__":
    adapter = MayaAdapter()
    print(adapter.build_context_summary())
