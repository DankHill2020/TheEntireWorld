# motionbuilder_adapter.py
"""DCCAdapter implementation for Autodesk MotionBuilder.

Deep context awareness:
- Scene components/models
- Selection
- Takes and time range
- Characters, control rigs, constraints, devices
- File state and FBX import/export handoff
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from bridges.host_bridge import DCCAdapter


class MotionBuilderAdapter(DCCAdapter):
    """Full DCCAdapter for MotionBuilder via the socket bridge."""

    def __init__(self):
        from bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge

        self._bridge = MotionBuilderBridge()

    @property
    def app_name(self) -> str:
        return "MotionBuilder"

    @property
    def is_available(self) -> bool:
        return self._bridge.find_port() is not None

    def execute_python(self, code: str, timeout: float = 30.0) -> Tuple[bool, str]:
        return self._bridge.execute(code, timeout=timeout)

    def _json_query(self, code: str, fallback):
        ok, raw = self.execute_python(code.strip())
        if ok:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return fallback

    def query_state(self) -> Dict[str, Any]:
        port = self._bridge.find_port()
        if not port:
            return {
                "connected": False,
                "app_name": "MotionBuilder",
                "open_file": None,
                "version": "unknown",
            }
        code = """
import json
from pyfbsdk import FBApplication, FBSystem, FBPlayerControl
app = FBApplication()
system = FBSystem()
player = FBPlayerControl()
scene = system.Scene
current_take = system.CurrentTake.Name if system.CurrentTake else ""
print(json.dumps({
    "connected": True,
    "app_name": "MotionBuilder",
    "open_file": app.FBXFileName or None,
    "version": getattr(system, "Version", "unknown"),
    "port": __import__("os").environ.get("MOTIONBUILDER_COMMAND_PORT", "7011"),
    "current_take": current_take,
    "take_count": len(scene.Takes),
    "component_count": len(scene.Components),
    "current_time": str(player.GetEditCurrentTime()),
    "transport_fps": str(player.GetTransportFps()),
}, default=str))
"""
        state = self._json_query(code, {})
        if isinstance(state, dict):
            state["port"] = port
            return state
        return {"connected": True, "app_name": "MotionBuilder", "open_file": None, "version": "unknown", "port": port}

    def list_scene(self) -> List[Dict[str, Any]]:
        code = """
import json
from pyfbsdk import FBSystem, FBModel
items = []
for comp in FBSystem().Scene.Components:
    try:
        is_model = isinstance(comp, FBModel)
        parent = ""
        if is_model and comp.Parent:
            parent = comp.Parent.LongName or comp.Parent.Name
        items.append({
            "name": comp.Name,
            "long_name": getattr(comp, "LongName", comp.Name),
            "type": comp.ClassName(),
            "path": getattr(comp, "LongName", comp.Name),
            "selected": bool(getattr(comp, "Selected", False)),
            "parent": parent,
        })
    except Exception:
        pass
print(json.dumps(items[:1000], default=str))
"""
        return self._json_query(code, [])

    def get_selection(self) -> List[Dict[str, Any]]:
        code = """
import json
from pyfbsdk import FBModelList, FBGetSelectedModels
models = FBModelList()
FBGetSelectedModels(models)
items = []
for model in models:
    try:
        items.append({
            "name": model.Name,
            "long_name": model.LongName,
            "type": model.ClassName(),
            "path": model.LongName,
            "translation": list(model.Translation.Data),
            "rotation": list(model.Rotation.Data),
            "scaling": list(model.Scaling.Data),
        })
    except Exception:
        pass
print(json.dumps(items, default=str))
"""
        return self._json_query(code, [])

    def get_takes(self) -> List[Dict[str, Any]]:
        code = """
import json
from pyfbsdk import FBSystem
system = FBSystem()
items = []
for take in system.Scene.Takes:
    try:
        items.append({
            "name": take.Name,
            "selected": bool(system.CurrentTake and take.Name == system.CurrentTake.Name),
            "local_start": str(take.LocalTimeSpan.GetStart()),
            "local_stop": str(take.LocalTimeSpan.GetStop()),
            "reference_start": str(take.ReferenceTimeSpan.GetStart()),
            "reference_stop": str(take.ReferenceTimeSpan.GetStop()),
        })
    except Exception:
        pass
print(json.dumps(items, default=str))
"""
        return self._json_query(code, [])

    def get_characters(self) -> List[Dict[str, Any]]:
        code = """
import json
from pyfbsdk import FBSystem, FBCharacter
chars = []
for comp in FBSystem().Scene.Components:
    if isinstance(comp, FBCharacter):
        try:
            chars.append({
                "name": comp.Name,
                "active": bool(comp.ActiveInput),
                "input_type": str(comp.InputType),
                "characterized": bool(comp.GetCharacterize()),
            })
        except Exception:
            chars.append({"name": comp.Name})
print(json.dumps(chars, default=str))
"""
        return self._json_query(code, [])

    def get_constraints(self) -> List[Dict[str, Any]]:
        code = """
import json
from pyfbsdk import FBSystem, FBConstraint
items = []
for comp in FBSystem().Scene.Components:
    if isinstance(comp, FBConstraint):
        try:
            items.append({
                "name": comp.Name,
                "type": comp.ClassName(),
                "active": bool(comp.Active),
                "weight": float(comp.Weight),
            })
        except Exception:
            items.append({"name": comp.Name, "type": comp.ClassName()})
print(json.dumps(items, default=str))
"""
        return self._json_query(code, [])

    def get_devices(self) -> List[Dict[str, Any]]:
        code = """
import json
from pyfbsdk import FBSystem, FBDevice
items = []
for comp in FBSystem().Scene.Components:
    if isinstance(comp, FBDevice):
        items.append({
            "name": comp.Name,
            "type": comp.ClassName(),
            "online": bool(getattr(comp, "Online", False)),
            "recording": bool(getattr(comp, "Recording", False)),
        })
print(json.dumps(items, default=str))
"""
        return self._json_query(code, [])

    def import_asset(self, source_path: str, destination: str = "", **options) -> Tuple[bool, str]:
        merge = bool(options.get("merge", True))
        code = f"""
from pyfbsdk import FBApplication
app = FBApplication()
ok = app.FileMerge(r"{source_path}") if {merge!r} else app.FileOpen(r"{source_path}")
print("imported" if ok else "import failed")
"""
        return self.execute_python(code.strip(), timeout=60.0)

    def export_asset(self, asset_path: str, output_path: str, **options) -> Tuple[bool, str]:
        selected = bool(options.get("selected", False))
        code = f"""
from pyfbsdk import FBApplication
app = FBApplication()
ok = app.FileSave(r"{output_path}")
print("exported" if ok else "export failed")
"""
        if selected:
            code = f"""
from pyfbsdk import FBApplication
app = FBApplication()
ok = app.FileExport(r"{output_path}")
print("exported selection" if ok else "export failed")
"""
        return self.execute_python(code.strip(), timeout=60.0)

    def run_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        ok, result = self._bridge.call_function(tool_name, args=kwargs.pop("args", []), kwargs=kwargs)
        return {"success": ok, "message": result, "tool": tool_name}

    def build_context_summary(self) -> str:
        state = self.query_state()
        if not state.get("connected"):
            return "MotionBuilder: not connected."
        selection = self.get_selection()
        takes = self.get_takes()
        chars = self.get_characters()
        constraints = self.get_constraints()
        devices = self.get_devices()
        scene = self.list_scene()
        lines = [
            "# MotionBuilder Scene State",
            f"- File: {state.get('open_file') or 'Untitled'}",
            f"- Version: {state.get('version')} | Current take: {state.get('current_take') or 'None'}",
            f"- Components: {state.get('component_count', len(scene))} | Selection: {len(selection)}",
            f"- Takes: {len(takes)} | Characters: {len(chars)} | Constraints: {len(constraints)} | Devices: {len(devices)}",
        ]
        for take in takes[:6]:
            marker = " *current*" if take.get("selected") else ""
            lines.append(f"  - Take: {take.get('name')} {take.get('local_start')} -> {take.get('local_stop')}{marker}")
        for char in chars[:6]:
            lines.append(f"  - Character: {char.get('name')} characterized={char.get('characterized')}")
        for item in selection[:6]:
            lines.append(f"  - Selected: {item.get('long_name') or item.get('name')} ({item.get('type')})")
        return "\n".join(lines)


if __name__ == "__main__":
    print(MotionBuilderAdapter().build_context_summary())
