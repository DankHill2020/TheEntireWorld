"""Factories and bridge-backed adapters for the shared rigging workspace."""

from __future__ import annotations

import json
from typing import Any, Callable

from tech_connector.game_engine.authoring.rigging_workspace_service import (
    RIGGING_CAPABILITIES,
    RiggingOperationResult,
)
from tech_connector.game_engine.integration.tc_rigging_host_adapter import TCRiggingHostAdapter


Executor = Callable[[str, float], tuple[bool, str]]


MAYA_CAPABILITY_STATUS = {key: "translated" for key in RIGGING_CAPABILITIES}

BLENDER_NATIVE_KEYS = {
    "definition.auto_map", "definition.assign_slot", "definition.clear_slot",
    "definition.mirror_slots", "definition.validate", "definition.set_reference_pose",
    "definition.import", "definition.export", "rig.build_full", "rig.build_module",
    "rig.remove_module", "rig.rebuild_module", "rig.create_control",
    "rig.create_constraint", "rig.create_ik_fk_limb", "rig.set_ik_fk_blend", "rig.create_ribbon",
    "rig.create_twist", "rig.create_curve_joints", "rig.create_face_module",
    "skin.surface_spatial_smooth_brush",
    "retarget.create_definition", "retarget.validate_definition",
}
BLENDER_CAPABILITY_STATUS = {
    key: ("translated" if key in BLENDER_NATIVE_KEYS else "unsupported")
    for key in RIGGING_CAPABILITIES
}

MAX_NATIVE_KEYS = {
    "definition.auto_map", "definition.assign_slot", "definition.clear_slot",
    "definition.mirror_slots", "definition.validate", "definition.set_reference_pose",
    "definition.import", "definition.export", "rig.build_full", "rig.build_module",
    "rig.remove_module", "rig.rebuild_module", "rig.create_control",
    "rig.create_constraint", "rig.create_ik_fk_limb", "rig.set_ik_fk_blend",
    "rig.create_ribbon", "rig.create_twist", "rig.create_curve_joints", "rig.create_face_module",
    "skin.surface_spatial_smooth_brush",
    "retarget.create_definition", "retarget.validate_definition", "retarget.solve_pose",
    "retarget.preview",
}
MAX_CAPABILITY_STATUS = {
    key: ("translated" if key in MAX_NATIVE_KEYS else "unsupported")
    for key in RIGGING_CAPABILITIES
}

MOTIONBUILDER_NATIVE_KEYS = {
    "definition.auto_map", "definition.assign_slot", "definition.clear_slot",
    "definition.mirror_slots", "definition.validate", "definition.set_reference_pose",
    "definition.import", "definition.export", "rig.create_control", "rig.create_constraint",
    "rig.create_ik_fk_limb", "rig.set_ik_fk_blend", "rig.create_space_switch", "rig.set_space",
    "rig.store_connections", "rig.restore_connections",
    "retarget.create_definition", "retarget.validate_definition", "retarget.solve_pose",
    "retarget.preview", "retarget.bake", "retarget.transfer_take",
}
MOTIONBUILDER_CAPABILITY_STATUS = {
    key: ("translated" if key in MOTIONBUILDER_NATIVE_KEYS else "unsupported")
    for key in RIGGING_CAPABILITIES
}


class PythonHostRiggingAdapter:
    """Call a tiny host-side adapter through either direct Python or a socket bridge."""

    def __init__(self, host_id: str, executor: Executor, backend_module: str, statuses: dict[str, str]):
        self._host_id = str(host_id)
        self._executor = executor
        self._backend_module = str(backend_module)
        self._statuses = dict(statuses)

    @property
    def host_id(self) -> str:
        return self._host_id

    def capabilities(self) -> dict[str, str]:
        return dict(self._statuses)

    def scene_joints(self) -> list[dict[str, Any]]:
        result = self._call("scene_joints", {})
        return list(result.data.get("joints") or []) if result.ok else []

    def selection(self) -> list[str]:
        result = self._call("selection", {})
        return [str(value) for value in result.data.get("selection") or []] if result.ok else []

    def execute(self, capability: str, payload: dict[str, Any]) -> RiggingOperationResult:
        return self._call("execute", {"capability": capability, "payload": payload}, capability=capability)

    def _call(self, function_name: str, payload: dict[str, Any], *, capability: str = "host.query") -> RiggingOperationResult:
        encoded = json.dumps(payload, default=_json_default)
        script = (
            "import importlib\n"
            "import json\n"
            f"_tc_rigging_module = importlib.import_module({self._backend_module!r})\n"
            "_tc_rigging_module = importlib.reload(_tc_rigging_module)\n"
            "_tc_reload_dependencies = getattr(_tc_rigging_module, 'reload_dependencies', None)\n"
            "if callable(_tc_reload_dependencies):\n"
            "    _tc_reload_dependencies()\n"
            f"_tc_rigging_call = getattr(_tc_rigging_module, {function_name!r})\n"
            f"_tc_result = _tc_rigging_call(**json.loads({encoded!r}))\n"
            "print('__TC_RIGGING_RESULT__' + json.dumps(_tc_result, default=str))\n"
        )
        ok, raw = self._executor(script, 60.0)
        if not ok:
            return RiggingOperationResult(False, capability, self.host_id, str(raw or "Host execution failed."))
        marker = "__TC_RIGGING_RESULT__"
        text = str(raw or "")
        index = text.rfind(marker)
        if index < 0:
            return RiggingOperationResult(False, capability, self.host_id, "Host adapter returned no structured result.")
        try:
            data = json.loads(text[index + len(marker):].strip().splitlines()[0])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return RiggingOperationResult(False, capability, self.host_id, f"Invalid host adapter result: {exc}")
        return RiggingOperationResult(
            ok=bool(data.get("ok", False)), capability=str(data.get("capability") or capability),
            host=str(data.get("host") or self.host_id), message=str(data.get("message") or ""),
            created_ids=[str(value) for value in data.get("created_ids") or []],
            changed_ids=[str(value) for value in data.get("changed_ids") or []],
            removed_ids=[str(value) for value in data.get("removed_ids") or []],
            data=dict(data.get("data") or {}), warnings=[str(value) for value in data.get("warnings") or []],
        )


def maya_rigging_adapter(*, embedded: bool = False) -> PythonHostRiggingAdapter:
    if embedded:
        def executor(code: str, _timeout: float) -> tuple[bool, str]:
            import contextlib
            import io
            stream = io.StringIO()
            try:
                with contextlib.redirect_stdout(stream):
                    exec(code, {"__name__": "__tc_maya_rigging__"})
                return True, stream.getvalue()
            except Exception as exc:
                return False, str(exc)
    else:
        from tech_connector.bridges.maya.maya_bridge import MayaBridge
        bridge = MayaBridge()
        executor = lambda code, timeout: bridge.execute(code, timeout=timeout)
    return PythonHostRiggingAdapter(
        "maya", executor, "maya_tools.Rigging.rigging_host_adapter", MAYA_CAPABILITY_STATUS
    )


def motionbuilder_rigging_adapter(*, embedded: bool = False) -> PythonHostRiggingAdapter:
    if embedded:
        def executor(code: str, _timeout: float) -> tuple[bool, str]:
            import contextlib
            import io
            stream = io.StringIO()
            try:
                with contextlib.redirect_stdout(stream):
                    exec(code, {"__name__": "__tc_mobu_rigging__"})
                return True, stream.getvalue()
            except Exception as exc:
                return False, str(exc)
    else:
        from tech_connector.bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge
        bridge = MotionBuilderBridge()
        executor = lambda code, timeout: bridge.execute(code, timeout=timeout)
    return PythonHostRiggingAdapter(
        "motionbuilder", executor,
        "motionbuilder_tools.Rigging.rigging_host_adapter",
        MOTIONBUILDER_CAPABILITY_STATUS,
    )


def blender_rigging_adapter(*, embedded: bool = False) -> PythonHostRiggingAdapter:
    if embedded:
        def executor(code: str, _timeout: float) -> tuple[bool, str]:
            import contextlib
            import io
            stream = io.StringIO()
            try:
                with contextlib.redirect_stdout(stream):
                    exec(code, {"__name__": "__tc_blender_rigging__"})
                return True, stream.getvalue()
            except Exception as exc:
                return False, str(exc)
    else:
        from tech_connector.bridges.blender.blender_bridge import BlenderBridge
        bridge = BlenderBridge()
        executor = lambda code, timeout: bridge.execute(code, timeout=timeout)
    return PythonHostRiggingAdapter(
        "blender", executor, "blender_tools.Rigging.rigging_host_adapter", BLENDER_CAPABILITY_STATUS
    )


def max_rigging_adapter(*, embedded: bool = False) -> PythonHostRiggingAdapter:
    if embedded:
        def executor(code: str, _timeout: float) -> tuple[bool, str]:
            import contextlib
            import io
            stream = io.StringIO()
            try:
                with contextlib.redirect_stdout(stream):
                    exec(code, {"__name__": "__tc_3dsmax_rigging__"})
                return True, stream.getvalue()
            except Exception as exc:
                return False, str(exc)
    else:
        from tech_connector.bridges.max.max_bridge import MaxBridge
        bridge = MaxBridge()
        executor = lambda code, timeout: bridge.execute(code, timeout=timeout)
    return PythonHostRiggingAdapter(
        "3dsmax", executor, "max_tools.Rigging.rigging_host_adapter", MAX_CAPABILITY_STATUS
    )


def create_rigging_adapter(host: str, *, graph=None, embedded: bool = False, selected_ids=None):
    key = str(host or "tech_connector").strip().lower().replace(" ", "")
    if key in {"tech_connector", "tc", "local"}:
        return TCRiggingHostAdapter(graph, selected_ids=selected_ids)
    if key in {"maya", "mayabridge"}:
        return maya_rigging_adapter(embedded=embedded)
    if key in {"blender", "blenderbridge"}:
        return blender_rigging_adapter(embedded=embedded)
    if key in {"3dsmax", "3dsmaxbridge", "max", "maxbridge"}:
        return max_rigging_adapter(embedded=embedded)
    if key in {"motionbuilder", "mobu", "motionbuilderbridge"}:
        return motionbuilder_rigging_adapter(embedded=embedded)
    raise ValueError(f"Unsupported rigging host: {host}")


def _json_default(value: Any):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


__all__ = [
    "BLENDER_CAPABILITY_STATUS", "MAX_CAPABILITY_STATUS", "MAYA_CAPABILITY_STATUS",
    "MOTIONBUILDER_CAPABILITY_STATUS", "PythonHostRiggingAdapter", "blender_rigging_adapter",
    "create_rigging_adapter", "max_rigging_adapter", "maya_rigging_adapter", "motionbuilder_rigging_adapter",
]

