from __future__ import annotations

"""Runtime dispatch for generated Pipeline View host-operation nodes."""

import json
from typing import Any


def _unwrap(response: Any) -> dict[str, Any]:
    ok, payload = (
        response
        if isinstance(response, tuple) and len(response) == 2
        else (True, response)
    )
    if not ok:
        raise RuntimeError(str(payload))
    if isinstance(payload, dict):
        if payload.get("ok") is False:
            raise RuntimeError(
                str(
                    payload.get("error")
                    or payload.get("traceback")
                    or payload.get("python_stderr")
                    or payload
                )
            )
        for key in ("python_result", "result", "data"):
            if isinstance(payload.get(key), dict):
                return dict(payload[key])
        text = payload.get("python_stdout") or payload.get("stdout")
        if text:
            payload = text
        else:
            return payload
    if isinstance(payload, str):
        for line in reversed([item.strip() for item in payload.splitlines() if item.strip()]):
            try:
                decoded = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, dict):
                return decoded
    return {"result": payload}


def execute_pipeline_operation(
    host: str,
    operation: str,
    callable_name: str,
    params: dict[str, Any] | None = None,
    *,
    session_port: int | None = None,
) -> dict[str, Any]:
    host = str(host or "").strip().lower()
    operation = str(operation or "").strip()
    callable_name = str(callable_name or "").strip()
    kwargs = dict(params or {})
    if not callable_name:
        raise ValueError(f"No callable is registered for {host}:{operation}")

    if host == "unreal":
        from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

        module_name, _, attribute = callable_name.rpartition(".")
        if not module_name or not attribute:
            raise ValueError(f"Unreal callable must be module-qualified: {callable_name}")
        code = "\n".join(
            [
                "import importlib, json",
                f"_module = importlib.import_module({module_name!r})",
                f"_target = getattr(_module, {attribute!r})",
                f"_result = _target(**{kwargs!r})",
                "print(json.dumps(_result, default=str))",
            ]
        )
        return _unwrap(
            UnrealBridge(forced_port=session_port).execute_python(code, timeout=120.0, reset_globals=True)
        )

    if host == "maya" and callable_name.startswith("ai_studio.maya.generated."):
        from tech_connector.bridges.maya.maya_bridge import MayaBridge
        from tech_connector.game_engine.integration.dcc_operation_service import maya_operation_code

        bridge = MayaBridge()
        code = maya_operation_code(operation, kwargs)
        response = (
            bridge.execute_on_port(code, port=int(session_port), timeout=120.0)
            if session_port is not None else bridge.execute(code, timeout=120.0)
        )
        return _unwrap(response)

    if host == "blender" and callable_name.startswith("ai_studio.blender.generated."):
        from tech_connector.bridges.blender.blender_bridge import BlenderBridge
        from tech_connector.game_engine.integration.dcc_operation_service import blender_operation_code

        bridge = BlenderBridge()
        code = blender_operation_code(operation, kwargs)
        response = (
            bridge.execute_on_port(code, port=int(session_port), timeout=120.0)
            if session_port is not None else bridge.execute(code, timeout=120.0)
        )
        return _unwrap(response)

    if host == "photoshop" and callable_name.startswith("photoshop.command."):
        from tech_connector.bridges.photoshop.photoshop_bridge import PhotoshopBridge

        bridge = PhotoshopBridge()
        command = callable_name.removeprefix("photoshop.command.")
        command_params = {"descriptor": kwargs["descriptor"]} if command == "batch_play" else kwargs
        if session_port is not None:
            return _unwrap(bridge.execute_on_port(
                json.dumps({"command": command, "params": command_params}),
                port=int(session_port),
                timeout=120.0,
            ))
        if command == "batch_play":
            return _unwrap(bridge.execute_command("batch_play", command_params))
        return _unwrap(bridge.execute_command(command, command_params))

    if host == "gimp" and callable_name.startswith("gimp.command."):
        from tech_connector.bridges.gimp.gimp_bridge import GimpBridge

        bridge = GimpBridge()
        command = callable_name.removeprefix("gimp.command.")
        if session_port is not None:
            return _unwrap(bridge.execute_command(command, kwargs, port=int(session_port)))
        return _unwrap(bridge.execute_command(command, kwargs))

    if host == "unity" and callable_name.startswith("unity.command."):
        from tech_connector.bridges.unity.unity_bridge import UnityBridge

        bridge = UnityBridge()
        command = callable_name.removeprefix("unity.command.")
        return _unwrap(bridge.execute_command(command, kwargs, port=session_port))

    bridge_types = {}
    if host == "maya":
        from tech_connector.bridges.maya.maya_bridge import MayaBridge

        bridge_types[host] = MayaBridge
    elif host == "blender":
        from tech_connector.bridges.blender.blender_bridge import BlenderBridge

        bridge_types[host] = BlenderBridge
    elif host == "motionbuilder":
        from tech_connector.bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge

        bridge_types[host] = MotionBuilderBridge
    elif host == "houdini":
        from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge

        bridge_types[host] = HoudiniBridge
    elif host in {"3dsmax", "max"}:
        from tech_connector.bridges.max.max_bridge import MaxBridge

        bridge_types[host] = MaxBridge
    elif host == "substance_painter":
        from tech_connector.bridges.substance_painter.substance_painter_bridge import (
            SubstancePainterBridge,
        )

        bridge_types[host] = SubstancePainterBridge
    elif host == "unity":
        from tech_connector.bridges.unity.unity_bridge import UnityBridge

        bridge_types[host] = UnityBridge
    bridge_type = bridge_types.get(host)
    if not bridge_type:
        raise RuntimeError(f"No Pipeline View runtime bridge is registered for {host!r}")
    bridge = bridge_type()
    if session_port is not None:
        from tech_connector.bridges.host_bridge import PortBoundHostBridge, call_python_function_via_execute

        return _unwrap(call_python_function_via_execute(
            PortBoundHostBridge(bridge, int(session_port)),
            callable_name,
            kwargs=kwargs,
            sys_paths=getattr(bridge, "SYS_PATHS", ()),
        ))
    if not hasattr(bridge, "call_function"):
        raise RuntimeError(f"{bridge_type.__name__} does not expose call_function")
    return _unwrap(bridge.call_function(callable_name, kwargs=kwargs))

