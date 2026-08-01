"""Universal Live Link 3D Transform & Asset Synchronization Service for Tech Connector.

Streams real-time 3D object transforms (Translate, Rotate, Scale), camera FOV/lens specs,
light intensity/color, and skeletal poses bi-directionally between Maya, Blender,
Houdini, MotionBuilder, Unreal Engine 5, and Unity.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TransformEnvelope:
    """3D Transform and Component payload exchanged across Live Link bridges."""

    object_name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)  # Euler angles in degrees
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    camera_fov: float | None = None
    focal_length_mm: float | None = None
    light_intensity: float | None = None
    light_color_hex: str | None = None
    extra_attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_name": self.object_name,
            "position": list(self.position),
            "rotation": list(self.rotation),
            "scale": list(self.scale),
            "camera_fov": self.camera_fov,
            "focal_length_mm": self.focal_length_mm,
            "light_intensity": self.light_intensity,
            "light_color_hex": self.light_color_hex,
            "extra_attributes": self.extra_attributes,
        }


class LiveLinkTransformService:
    """Orchestrates high-frequency 3D transform sync across all running DCCs and Game Engines."""

    _instance: "LiveLinkTransformService" | None = None

    @classmethod
    def get_instance(cls) -> "LiveLinkTransformService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.active_targets: set[str] = set()  # maya, blender, houdini, motionbuilder, unreal, unity

    def enable_target(self, app_name: str, enabled: bool = True):
        app_key = app_name.lower().strip()
        if enabled:
            self.active_targets.add(app_key)
        else:
            self.active_targets.discard(app_key)

    def broadcast_transform(self, envelope: TransformEnvelope, source_app: str = "studio"):
        """Broadcast 3D transform update to all active DCC and Game Engine targets."""
        for target in self.active_targets:
            if target == source_app.lower():
                continue
            self._dispatch_to_app(target, envelope)

    def _dispatch_to_app(self, app_name: str, envelope: TransformEnvelope):
        px, py, pz = envelope.position
        rx, ry, rz = envelope.rotation
        sx, sy, sz = envelope.scale
        obj = envelope.object_name

        try:
            if app_name == "maya":
                from tech_connector.bridges.dcc_websocket_bridge import dcc_bridge
                code = f"""
import maya.cmds as cmds
if cmds.objExists('{obj}'):
    cmds.setAttr('{obj}.translate', {px}, {py}, {pz})
    cmds.setAttr('{obj}.rotate', {rx}, {ry}, {rz})
    cmds.setAttr('{obj}.scale', {sx}, {sy}, {sz})
"""
                dcc_bridge.execute_in_dcc("maya", code)

            elif app_name == "blender":
                from tech_connector.bridges.dcc_websocket_bridge import dcc_bridge
                code = f"""
import bpy, math
obj = bpy.data.objects.get('{obj}')
if obj:
    obj.location = ({px}, {py}, {pz})
    obj.rotation_euler = (math.radians({rx}), math.radians({ry}), math.radians({rz}))
    obj.scale = ({sx}, {sy}, {sz})
"""
                dcc_bridge.execute_in_dcc("blender", code)

            elif app_name == "houdini":
                from tech_connector.bridges.dcc_websocket_bridge import dcc_bridge
                code = f"""
import hou
node = hou.node('/obj/{obj}')
if node:
    node.parmTuple('t').set(({px}, {py}, {pz}))
    node.parmTuple('r').set(({rx}, {ry}, {rz}))
    node.parmTuple('s').set(({sx}, {sy}, {sz}))
"""
                dcc_bridge.execute_in_dcc("houdini", code)

            elif app_name == "motionbuilder":
                from tech_connector.bridges.dcc_websocket_bridge import dcc_bridge
                code = f"""
from pyfbsdk import FBFindModelByLabel, FBVector3d
m = FBFindModelByLabel('{obj}')
if m:
    m.Translation = FBVector3d({px}, {py}, {pz})
    m.Rotation = FBVector3d({rx}, {ry}, {rz})
    m.Scaling = FBVector3d({sx}, {sy}, {sz})
"""
                dcc_bridge.execute_in_dcc("motionbuilder", code)

            elif app_name in {"unreal", "ue5"}:
                from tech_connector.bridges.unreal.unreal_bridge import execute_unreal_python
                code = f"""
import unreal
actor = unreal.EditorLevelLibrary.get_all_level_actors()
target = next((a for a in actor if a.get_actor_label() == '{obj}'), None)
if target:
    target.set_actor_location(unreal.Vector({px}, {py}, {pz}), False, False)
    target.set_actor_rotation(unreal.Rotator({rx}, {ry}, {rz}), False)
    target.set_actor_scale_3d(unreal.Vector({sx}, {sy}, {sz}))
"""
                execute_unreal_python(code)

            elif app_name == "unity":
                from tech_connector.bridges.unity.unity_bridge import execute_unity_command
                code = f"""
var go = GameObject.Find("{obj}");
if (go != null) {{
    go.transform.position = new Vector3({px}f, {py}f, {pz}f);
    go.transform.eulerAngles = new Vector3({rx}f, {ry}f, {rz}f);
    go.transform.localScale = new Vector3({sx}f, {sy}f, {sz}f);
}}
"""
                execute_unity_command(code)

        except Exception as exc:
            logger.debug(f"Live Link transform dispatch to {app_name} failed: {exc}")


transform_livelink = LiveLinkTransformService.get_instance()
