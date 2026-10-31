from __future__ import annotations

"""Runtime dispatch for generated Pipeline View host-operation nodes."""

from datetime import datetime, timezone
import json
import time
from typing import Any, Callable
import uuid


PIPELINE_OPERATION_EVENT_SCHEMA = "tech_connector.pipeline_operation_event.v1"


class PipelineOperationCancelled(RuntimeError):
    """Raised when an operation is cancelled before it reaches a host."""


def _cancelled(token: Any) -> bool:
    if token is None:
        return False
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    value = getattr(token, "cancelled", token)
    return bool(value() if callable(value) else value)


def _emit(callback: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(dict(event))
    except Exception:
        # Observability must never turn a successful DCC edit into a failure.
        return


def _event(
    event_type: str, *, execution_id: str, host: str, operation: str,
    callable_name: str, attempt: int, maximum_attempts: int,
    timeout_seconds: float, started_at: float, message: str = "",
) -> dict[str, Any]:
    return {
        "schema": PIPELINE_OPERATION_EVENT_SCHEMA,
        "event": event_type,
        "execution_id": execution_id,
        "host": host,
        "operation": operation,
        "callable": callable_name,
        "attempt": attempt,
        "maximum_attempts": maximum_attempts,
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": round(max(0.0, time.perf_counter() - started_at), 6),
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _transient_failure(error: Exception) -> bool:
    text = str(error).casefold()
    return any(marker in text for marker in (
        "connection refused", "connection reset", "connection aborted",
        "timed out", "timeout", "temporarily unavailable", "host unavailable",
        "session unavailable", "session not found", "broken pipe",
    ))


def _wait_for_retry(seconds: float, cancel_token: Any) -> None:
    remaining = max(0.0, min(5.0, float(seconds)))
    deadline = time.monotonic() + remaining
    while remaining > 0.0:
        if _cancelled(cancel_token):
            raise PipelineOperationCancelled("Pipeline operation cancelled before retry.")
        time.sleep(min(0.05, remaining))
        remaining = deadline - time.monotonic()


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


def _canonicalize_export_result(operation: str, result: dict[str, Any]) -> dict[str, Any]:
    """Expose the typed FBX handoff key without discarding host-native path fields."""

    if operation not in {"io.export_fbx", "animation.export", "blender.export_fbx", "io.export"}:
        return result
    if result.get("fbx_path"):
        return result
    for key in ("export_path", "filepath", "output_path"):
        path = result.get(key)
        if isinstance(path, str) and path.strip().lower().endswith(".fbx"):
            return {**result, "fbx_path": path}
    return result


def _read_dcc_export_scope(
    host: str,
    spec: dict[str, Any],
    *,
    session_port: int | None,
    timeout_seconds: float,
    bridge: Any = None,
) -> list[str]:
    scope = str(spec.get("scope") or "current_selection_or_subject")
    subject = str(spec.get("subject") or "asset")
    requested_name = str(spec.get("name") or "")
    if host == "blender":
        from tech_connector.bridges.blender.blender_bridge import BlenderBridge

        code = f'''import bpy, json
scope = {scope!r}
subject = {subject!r}
requested_name = {requested_name!r}
selected = list(bpy.context.selected_objects)
scene_objects = list(bpy.context.scene.objects)
result = []
def add(obj):
    if obj is not None and obj.name not in result:
        result.append(obj.name)
if scope == "named_object":
    obj = bpy.data.objects.get(requested_name)
    if obj is not None and obj in scene_objects and obj.type == "MESH":
        add(obj)
elif scope == "scene_contents":
    for obj in scene_objects:
        if obj.type in {{"MESH", "ARMATURE", "EMPTY", "CURVE"}}:
            add(obj)
elif scope == "active_object":
    add(bpy.context.object)
elif scope == "rig_contents":
    armatures = []
    for obj in selected + ([bpy.context.object] if bpy.context.object else []):
        armature = obj if obj and obj.type == "ARMATURE" else (obj.find_armature() if obj else None)
        if armature is not None and armature not in armatures:
            armatures.append(armature)
    if not armatures:
        armatures = [obj for obj in scene_objects if obj.type == "ARMATURE" and getattr(getattr(obj, "animation_data", None), "action", None)]
    if not armatures and len([obj for obj in scene_objects if obj.type == "ARMATURE"]) == 1:
        armatures = [obj for obj in scene_objects if obj.type == "ARMATURE"]
    for armature in armatures:
        add(armature)
        for obj in scene_objects:
            if obj.find_armature() == armature:
                add(obj)
            parent = obj.parent
            while parent is not None:
                if parent == armature:
                    add(obj)
                    break
                parent = parent.parent
elif scope == "selected_or_scene_meshes":
    meshes = [obj for obj in selected if obj.type == "MESH"] or [obj for obj in scene_objects if obj.type == "MESH"]
    for obj in meshes:
        add(obj)
else:
    candidates = selected
    if not candidates and subject == "static_mesh":
        candidates = [obj for obj in scene_objects if obj.type == "MESH"]
    for obj in candidates:
        add(obj)
print(json.dumps({{"selection": result, "scope": scope}}))'''
        bridge = bridge or BlenderBridge()
        response = (
            bridge.execute_on_port(code, port=int(session_port), timeout=timeout_seconds)
            if session_port is not None
            else bridge.execute(code, timeout=timeout_seconds)
        )
    elif host == "maya":
        from tech_connector.bridges.maya.maya_bridge import MayaBridge

        code = f'''import json
import maya.cmds as cmds
scope = {scope!r}
requested_name = {requested_name!r}
selected = cmds.ls(selection=True, long=True) or []
result = []
def add(values):
    for value in values or []:
        if value and value not in result:
            result.append(value)
if scope == "named_object":
    candidates = cmds.ls(requested_name, long=True, type="transform") or []
    if len(candidates) == 1 and (cmds.listRelatives(candidates[0], shapes=True, fullPath=True, type="mesh") or []):
        add(candidates)
elif scope == "scene_contents":
    add(cmds.ls(dag=True, long=True, type="transform") or [])
elif scope == "active_object":
    add(selected[:1])
elif scope == "selected_or_scene_meshes":
    if selected:
        add(selected)
    else:
        for shape in cmds.ls(type="mesh", long=True) or []:
            if not cmds.getAttr(shape + ".intermediateObject"):
                add(cmds.listRelatives(shape, parent=True, fullPath=True) or [])
elif scope == "rig_contents":
    selected_dag = [value for value in selected if cmds.objectType(value, isAType="dagNode")]
    joints = cmds.ls(selected_dag, dag=True, long=True, type="joint") or []
    skin_clusters = set()
    for value in selected_dag + joints:
        history = cmds.listHistory(value) or []
        skin_clusters.update(cmds.ls(history, type="skinCluster") or [])
        skin_clusters.update(cmds.listConnections(value, type="skinCluster") or [])
    if not skin_clusters:
        scene_skins = cmds.ls(type="skinCluster") or []
        if len(scene_skins) == 1:
            skin_clusters.add(scene_skins[0])
    for skin in sorted(skin_clusters):
        influences = cmds.skinCluster(skin, query=True, influence=True) or []
        add(cmds.ls(influences, long=True) or influences)
        for geometry in cmds.skinCluster(skin, query=True, geometry=True) or []:
            parents = cmds.listRelatives(geometry, parent=True, fullPath=True) or []
            add(parents or cmds.ls(geometry, long=True) or [geometry])
    add(joints)
    if not skin_clusters:
        add(selected_dag)
else:
    add(selected)
print(json.dumps({{"selection": result, "scope": scope}}))'''
        bridge = bridge or MayaBridge()
        response = (
            bridge.execute_on_port(code, port=int(session_port), timeout=timeout_seconds)
            if session_port is not None
            else bridge.execute(code, timeout=timeout_seconds)
        )
    else:
        raise RuntimeError(f"Live export-scope resolution is not implemented for {host!r}.")
    payload = _unwrap(response)
    selection = payload.get("selection") or payload.get("objects") or []
    resolved = [str(value) for value in selection if str(value)]
    if scope == "named_object" and resolved and (
        len(resolved) != 1 or resolved[0].rsplit("|", 1)[-1] != requested_name
    ):
        raise RuntimeError(
            f"Named mesh {requested_name} resolved unexpected {host} objects: {resolved}."
        )
    if not resolved:
        raise RuntimeError(
            f"The {spec.get('label') or scope} export scope resolved no {host} objects."
        )
    return resolved


def resolve_pipeline_context_params(
    params: dict[str, Any] | None,
    *,
    host: str,
    session_port: int | None = None,
    timeout_seconds: float = 120.0,
    context_reader: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Resolve typed live-context markers immediately before host dispatch."""

    def resolve(value: Any) -> Any:
        marker = value.get("$pipeline_context") if isinstance(value, dict) else ""
        if marker in {"dcc_export_scope_v1", "dcc_input_context_v1"}:
            context_spec = dict(value)
            if marker == "dcc_input_context_v1":
                context_spec["scope"] = (
                    "active_object"
                    if value.get("context_kind") == "active_object"
                    else "current_selection"
                )
            result = (
                context_reader(dict(context_spec))
                if context_reader is not None
                else _read_dcc_export_scope(
                    host,
                    context_spec,
                    session_port=session_port,
                    timeout_seconds=timeout_seconds,
                )
            )
            resolved = [str(item) for item in (result or []) if str(item)]
            if not resolved:
                raise RuntimeError(
                    f"The {value.get('label') or value.get('scope') or value.get('context_kind')} "
                    "context resolved no objects."
                )
            return resolved if bool(value.get("multiple", True)) else resolved[0]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, tuple):
            return tuple(resolve(item) for item in value)
        return value

    return {key: resolve(value) for key, value in dict(params or {}).items()}


def _execute_pipeline_operation_once(
    host: str,
    operation: str,
    callable_name: str,
    params: dict[str, Any] | None = None,
    *,
    session_port: int | None = None,
    timeout_seconds: float = 120.0,
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
            UnrealBridge(forced_port=session_port).execute_python(code, timeout=timeout_seconds, reset_globals=True)
        )

    if host == "maya" and callable_name.startswith("ai_studio.maya.generated."):
        from tech_connector.bridges.maya.maya_bridge import MayaBridge
        from tech_connector.game_engine.integration.dcc_operation_service import maya_operation_code

        bridge = MayaBridge()
        code = maya_operation_code(operation, kwargs)
        response = (
            bridge.execute_on_port(code, port=int(session_port), timeout=timeout_seconds)
            if session_port is not None else bridge.execute(code, timeout=timeout_seconds)
        )
        return _unwrap(response)

    if host == "blender" and callable_name.startswith("ai_studio.blender.generated."):
        from tech_connector.bridges.blender.blender_bridge import BlenderBridge
        from tech_connector.game_engine.integration.dcc_operation_service import blender_operation_code

        bridge = BlenderBridge()
        code = blender_operation_code(operation, kwargs)
        response = (
            bridge.execute_on_port(code, port=int(session_port), timeout=timeout_seconds)
            if session_port is not None else bridge.execute(code, timeout=timeout_seconds)
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
                timeout=timeout_seconds,
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

    if host == "tech_connector":
        import importlib

        module_name, separator, function_name = callable_name.rpartition(".")
        if not separator:
            raise ValueError(f"Tech Connector callable must be module-qualified: {callable_name}")
        function = getattr(importlib.import_module(module_name), function_name)
        result = function(**kwargs)
        return _unwrap(result)

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
            timeout=timeout_seconds,
        ))
    if host == "maya" and operation in {"animation.fbx_to_control_rig", "animation.fbx_to_engine"}:
        from tech_connector.bridges.host_bridge import call_python_function_via_execute

        return _unwrap(call_python_function_via_execute(
            bridge,
            callable_name,
            kwargs=kwargs,
            sys_paths=getattr(bridge, "SYS_PATHS", ()),
            timeout=timeout_seconds,
        ))
    if not hasattr(bridge, "call_function"):
        raise RuntimeError(f"{bridge_type.__name__} does not expose call_function")
    return _unwrap(bridge.call_function(callable_name, kwargs=kwargs))


def execute_pipeline_operation(
    host: str,
    operation: str,
    callable_name: str,
    params: dict[str, Any] | None = None,
    *,
    session_port: int | None = None,
    timeout_seconds: float = 120.0,
    cancel_token: Any = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    telemetry_sink: Callable[[dict[str, Any]], None] | None = None,
    retry_attempts: int = 0,
    retry_backoff_seconds: float = 0.25,
    retry_safe: bool = False,
    execution_id: str = "",
) -> dict[str, Any]:
    """Execute one host operation with bounded, observable lifecycle behavior.

    Retries are deliberately opt-in twice: callers must request attempts and
    assert ``retry_safe`` so mutating DCC operations are never duplicated by
    accident. Existing callers receive the same unwrapped result dictionary.
    """

    normalized_host = str(host or "").strip().lower()
    normalized_operation = str(operation or "").strip()
    normalized_callable = str(callable_name or "").strip()
    try:
        bounded_timeout = max(0.1, min(3600.0, float(timeout_seconds)))
    except (TypeError, ValueError):
        bounded_timeout = 120.0
    requested_retries = max(0, min(5, int(retry_attempts or 0)))
    maximum_attempts = 1 + (requested_retries if retry_safe else 0)
    correlation_id = str(execution_id or uuid.uuid4())
    started_at = time.perf_counter()

    def publish(kind: str, attempt: int, message: str = "") -> dict[str, Any]:
        payload = _event(
            kind, execution_id=correlation_id, host=normalized_host,
            operation=normalized_operation, callable_name=normalized_callable,
            attempt=attempt, maximum_attempts=maximum_attempts,
            timeout_seconds=bounded_timeout, started_at=started_at, message=message,
        )
        _emit(progress_callback, payload)
        _emit(telemetry_sink, payload)
        return payload

    publish("queued", 0, "Operation accepted for host dispatch.")
    if _cancelled(cancel_token):
        message = "Pipeline operation cancelled before host dispatch."
        publish("cancelled", 0, message)
        raise PipelineOperationCancelled(message)

    try:
        resolved_params = resolve_pipeline_context_params(
            params,
            host=normalized_host,
            session_port=session_port,
            timeout_seconds=bounded_timeout,
        )
    except Exception as error:
        publish("failed", 0, f"Could not resolve live pipeline context: {error}")
        raise

    for attempt in range(1, maximum_attempts + 1):
        publish("dispatching", attempt, f"Dispatching to {normalized_host or 'host'}.")
        try:
            result = _execute_pipeline_operation_once(
                normalized_host, normalized_operation, normalized_callable, resolved_params,
                session_port=session_port, timeout_seconds=bounded_timeout,
            )
            result = _canonicalize_export_result(normalized_operation, result)
        except Exception as error:
            can_retry = attempt < maximum_attempts and _transient_failure(error)
            if can_retry:
                publish("retrying", attempt, f"Transient host failure: {error}")
                _wait_for_retry(retry_backoff_seconds * attempt, cancel_token)
                continue
            publish("failed", attempt, str(error))
            raise
        if _cancelled(cancel_token):
            publish(
                "completed_after_cancel_request", attempt,
                "Host completed before cancellation could be applied safely.",
            )
        else:
            publish("completed", attempt, "Host operation completed.")
        return result
    raise RuntimeError("Pipeline operation exhausted its execution attempts.")


__all__ = [
    "PIPELINE_OPERATION_EVENT_SCHEMA",
    "PipelineOperationCancelled",
    "execute_pipeline_operation",
    "resolve_pipeline_context_params",
]

