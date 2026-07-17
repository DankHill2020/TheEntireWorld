from __future__ import annotations

"""Shared DCC context-call registry.

This module is intentionally lightweight and host-agnostic. It gives Tech Connector a
single place to map "context needs" such as current selection, current scene, or
editor state to either:

1. A named bridge function call, when the DCC already exposes a stable tool.
2. A vetted read-only Python snippet, when the bridge can execute Python but no
   named function exists yet.

The chat/UI layer should ask for registry calls by key. It should not hardcode
DCC Python strings.
"""

from dataclasses import dataclass, field
import json
import textwrap
from typing import Any, Mapping


@dataclass(frozen=True)
class ContextCall:
    key: str
    dcc: str
    mode: str  # "function" or "python"
    description: str = ""
    function: str = ""
    code: str = ""
    read_only: bool = True
    timeout: float = 3.0
    aliases: tuple[str, ...] = field(default_factory=tuple)
    returns_json: bool = True


def _dedent(source: str) -> str:
    return textwrap.dedent(source or "").strip() + "\n"


UNREAL_SELECTION_CODE = _dedent(
    r"""
    import json
    import unreal

    out = {
        "dcc": "unreal",
        "kind": "selection.current",
        "selected_assets": [],
        "selected_actors": [],
        "warnings": [],
    }

    try:
        out["selected_assets"] = [
            {
                "name": str(a.get_name()) if hasattr(a, "get_name") else str(a),
                "path": str(a.get_path_name()) if hasattr(a, "get_path_name") else str(a),
                "class": str(a.get_class().get_name()) if hasattr(a, "get_class") else "",
                "type": "asset",
            }
            for a in unreal.EditorUtilityLibrary.get_selected_assets()
        ]
    except Exception as exc:
        out["warnings"].append("selected_assets:" + str(exc))

    try:
        out["selected_actors"] = [
            {
                "name": str(a.get_name()) if hasattr(a, "get_name") else str(a),
                "path": str(a.get_path_name()) if hasattr(a, "get_path_name") else str(a),
                "class": str(a.get_class().get_name()) if hasattr(a, "get_class") else "",
                "type": "actor",
            }
            for a in unreal.EditorLevelLibrary.get_selected_level_actors()
        ]
    except Exception as exc:
        out["warnings"].append("selected_actors:" + str(exc))

    print(json.dumps(out))
    """
)

UNREAL_LEVEL_CODE = _dedent(
    r"""
    import json
    import unreal

    out = {
        "dcc": "unreal",
        "kind": "level.current",
        "loaded_level": None,
        "loaded_level_short": None,
        "selected_actors": [],
        "warnings": [],
    }

    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        if world:
            out["loaded_level"] = world.get_path_name() if hasattr(world, "get_path_name") else world.get_name()
            raw = out["loaded_level"] or ""
            out["loaded_level_short"] = str(raw).replace("\\", "/").rsplit("/", 1)[-1].split(".")[-1]
    except Exception as exc:
        out["warnings"].append("loaded_level:" + str(exc))

    try:
        out["selected_actors"] = [
            str(a.get_path_name()) if hasattr(a, "get_path_name") else str(a)
            for a in unreal.EditorLevelLibrary.get_selected_level_actors()
        ]
    except Exception as exc:
        out["warnings"].append("selected_actors:" + str(exc))

    print(json.dumps(out))
    """
)

UNREAL_EDITOR_STATE_CODE = _dedent(
    r"""
    import json
    import unreal

    out = {
        "dcc": "unreal",
        "kind": "editor.state",
        "engine_version": None,
        "project_name": None,
        "project_file": None,
        "loaded_level": None,
        "loaded_level_short": None,
        "selected_assets": [],
        "selected_actors": [],
        "warnings": [],
    }

    try:
        out["engine_version"] = unreal.SystemLibrary.get_engine_version()
    except Exception as exc:
        out["warnings"].append("engine_version:" + str(exc))

    try:
        project_file = unreal.Paths.get_project_file_path()
        out["project_file"] = project_file or None
        if project_file:
            out["project_name"] = unreal.Paths.get_base_filename(project_file)
    except Exception as exc:
        out["warnings"].append("project:" + str(exc))

    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        if world:
            out["loaded_level"] = world.get_path_name() if hasattr(world, "get_path_name") else world.get_name()
            raw = out["loaded_level"] or ""
            out["loaded_level_short"] = str(raw).replace("\\", "/").rsplit("/", 1)[-1].split(".")[-1]
    except Exception as exc:
        out["warnings"].append("loaded_level:" + str(exc))

    try:
        out["selected_assets"] = [
            str(a.get_path_name()) if hasattr(a, "get_path_name") else str(a)
            for a in unreal.EditorUtilityLibrary.get_selected_assets()
        ]
    except Exception as exc:
        out["warnings"].append("selected_assets:" + str(exc))

    try:
        out["selected_actors"] = [
            str(a.get_path_name()) if hasattr(a, "get_path_name") else str(a)
            for a in unreal.EditorLevelLibrary.get_selected_level_actors()
        ]
    except Exception as exc:
        out["warnings"].append("selected_actors:" + str(exc))

    print(json.dumps(out))
    """
)

# Baseline snippets for future DCCs. These entries are deliberately simple and
# read-only so the same registry shape works for Maya, Blender, and MotionBuilder.
MAYA_SELECTION_CODE = _dedent(
    r"""
    import json
    import maya.cmds as cmds
    print(json.dumps({
        "dcc": "maya",
        "kind": "selection.current",
        "selected": cmds.ls(selection=True, long=True) or [],
    }))
    """
)

BLENDER_SELECTION_CODE = _dedent(
    r"""
    import json
    import bpy
    print(json.dumps({
        "dcc": "blender",
        "kind": "selection.current",
        "selected": [
            {"name": obj.name, "type": obj.type}
            for obj in bpy.context.selected_objects
        ],
    }))
    """
)

MOTIONBUILDER_SELECTION_CODE = _dedent(
    r"""
    import json
    from pyfbsdk import FBModelList, FBGetSelectedModels
    models = FBModelList()
    FBGetSelectedModels(models)
    print(json.dumps({
        "dcc": "motionbuilder",
        "kind": "selection.current",
        "selected": [{"name": m.Name, "class": m.ClassName()} for m in models],
    }))
    """
)


_CONTEXT_CALLS: dict[str, ContextCall] = {
    "unreal.selection.current": ContextCall(
        key="unreal.selection.current",
        dcc="unreal",
        mode="python",
        description="Read the current Unreal Content Browser and level actor selection.",
        code=UNREAL_SELECTION_CODE,
        timeout=2.0,
        aliases=("selection.current", "selected.current", "current.selection"),
    ),
    "unreal.level.current": ContextCall(
        key="unreal.level.current",
        dcc="unreal",
        mode="python",
        description="Read the current Unreal editor world/level and selected actors.",
        code=UNREAL_LEVEL_CODE,
        timeout=2.0,
        aliases=("level.current", "scene.current"),
    ),
    "unreal.editor.state": ContextCall(
        key="unreal.editor.state",
        dcc="unreal",
        mode="python",
        description="Read a compact Unreal editor state snapshot.",
        code=UNREAL_EDITOR_STATE_CODE,
        timeout=3.0,
        aliases=("editor.state", "state.current"),
    ),
    "maya.selection.current": ContextCall(
        key="maya.selection.current",
        dcc="maya",
        mode="python",
        description="Read the current Maya selection.",
        code=MAYA_SELECTION_CODE,
        timeout=2.0,
        aliases=("selection.current",),
    ),
    "blender.selection.current": ContextCall(
        key="blender.selection.current",
        dcc="blender",
        mode="python",
        description="Read the current Blender selection.",
        code=BLENDER_SELECTION_CODE,
        timeout=2.0,
        aliases=("selection.current",),
    ),
    "motionbuilder.selection.current": ContextCall(
        key="motionbuilder.selection.current",
        dcc="motionbuilder",
        mode="python",
        description="Read the current MotionBuilder selection.",
        code=MOTIONBUILDER_SELECTION_CODE,
        timeout=2.0,
        aliases=("selection.current",),
    ),
}


# Typed Unreal resolver calls. These prefer named Unreal tool functions where
# available, so common object-resolution operations do not need ad-hoc Python.
_CONTEXT_CALLS.update(
    {
        "unreal.asset.resolve": ContextCall(
            key="unreal.asset.resolve",
            dcc="unreal",
            mode="function",
            description="Resolve an asset name/path into a package path and asset handle.",
            function="unreal_tools.assets.resolve_asset",
            read_only=True,
            timeout=5.0,
            aliases=("asset.resolve", "asset.find", "find.asset"),
        ),
        "unreal.actor.resolve": ContextCall(
            key="unreal.actor.resolve",
            dcc="unreal",
            mode="function",
            description="Resolve an actor name/label/path/tag/asset reference into level actor handles.",
            function="unreal_tools.level.resolve_actor",
            read_only=True,
            timeout=5.0,
            aliases=("actor.resolve", "actor.find", "find.actor"),
        ),
        "unreal.selection.select_actors": ContextCall(
            key="unreal.selection.select_actors",
            dcc="unreal",
            mode="function",
            description="Resolve actor names/assets/classes into actual Actor objects and select them.",
            function="unreal_tools.level.select_actors_by_query",
            read_only=False,
            timeout=5.0,
            aliases=("selection.select_actors", "select.actors", "actor.select"),
        ),
    }
)


def register_context_call(call: ContextCall) -> None:
    """Register or replace a context call at runtime."""
    _CONTEXT_CALLS[call.key] = call


def normalize_dcc_name(dcc: str) -> str:
    text = (dcc or "").strip().lower().replace(" ", "_")
    if text in {"ue", "ue5", "unreal_engine"}:
        return "unreal"
    if text in {"mobu", "motion_builder"}:
        return "motionbuilder"
    return text


def get_context_call(dcc: str, key: str) -> ContextCall | None:
    dcc_name = normalize_dcc_name(dcc)
    raw_key = (key or "").strip()
    candidates = [raw_key]
    if not raw_key.startswith(dcc_name + "."):
        candidates.insert(0, f"{dcc_name}.{raw_key}")
    for candidate in candidates:
        call = _CONTEXT_CALLS.get(candidate)
        if call:
            return call
    for call in _CONTEXT_CALLS.values():
        if call.dcc == dcc_name and raw_key in call.aliases:
            return call
    return None


def list_context_calls(dcc: str | None = None) -> list[dict[str, Any]]:
    dcc_name = normalize_dcc_name(dcc or "")
    rows = []
    for call in sorted(_CONTEXT_CALLS.values(), key=lambda item: item.key):
        if dcc_name and call.dcc != dcc_name:
            continue
        rows.append(
            {
                "key": call.key,
                "dcc": call.dcc,
                "mode": call.mode,
                "description": call.description,
                "function": call.function,
                "read_only": call.read_only,
                "timeout": call.timeout,
                "aliases": list(call.aliases),
            }
        )
    return rows


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def _first_json_line(text: str) -> Any:
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        parsed = _parse_jsonish(line)
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


def _normalize_bridge_response(response: Any) -> dict[str, Any]:
    """Normalize bridge responses from old/new Unreal/Maya/Blender callers."""
    if isinstance(response, tuple) and len(response) == 2:
        ok, payload = response
        payload = _parse_jsonish(payload)
        return {
            "ok": bool(ok),
            "data": payload,
            "error": None if ok else str(payload),
            "raw": payload,
        }

    if isinstance(response, list) and len(response) == 2 and isinstance(response[0], bool):
        ok, payload = response
        payload = _parse_jsonish(payload)
        return {
            "ok": bool(ok),
            "data": payload,
            "error": None if ok else str(payload),
            "raw": payload,
        }

    if not isinstance(response, dict):
        payload = _parse_jsonish(response)
        return {"ok": True, "data": payload, "error": None, "raw": response}

    out = dict(response)
    data = out.get("data", out.get("result"))

    if isinstance(data, list) and len(data) == 2 and isinstance(data[0], bool):
        ok, payload = data
        payload = _parse_jsonish(payload)
        out["ok"] = bool(out.get("ok")) and bool(ok)
        out["data"] = payload
        out["result"] = payload
        if not ok:
            out["error"] = out.get("error") or str(payload)
        data = payload

    if isinstance(data, dict) and "ok" in data and any(k in data for k in ("stdout", "stderr", "traceback")):
        runner = data
        stdout_payload = _first_json_line(str(runner.get("stdout") or ""))
        result_payload = _parse_jsonish(runner.get("result"))
        payload = stdout_payload if stdout_payload is not None else result_payload
        if payload is not None:
            out["data"] = payload
            out["result"] = payload
        out["python_runner"] = runner
        out["python_ok"] = bool(runner.get("ok"))
        if runner.get("error"):
            out["ok"] = False
            out["error"] = str(runner.get("error"))
            out["errors"] = [str(runner.get("error"))]
        return out

    if isinstance(data, str):
        parsed = _parse_jsonish(data)
        if isinstance(parsed, (dict, list)):
            out["data"] = parsed
            out["result"] = parsed
    return out


def _format_code_template(source: str, kwargs: Mapping[str, Any] | None = None) -> str:
    kwargs = dict(kwargs or {})
    if not kwargs:
        return source
    # Be conservative: only format snippets explicitly written with placeholders.
    try:
        return source.format(**kwargs)
    except Exception:
        return source


def execute_context_call(
    dcc: str,
    key: str,
    bridge: Any,
    *,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute a registered context call through a DCC bridge.

    The bridge may expose `safe_call`, `call`, or `execute_python`. The result is
    always normalized into `{ok, data, error, ...}`.
    """
    call = get_context_call(dcc, key)
    if call is None:
        return {
            "ok": False,
            "data": {},
            "error": f"No registered context call for {dcc}.{key}",
        }

    call_timeout = float(timeout if timeout is not None else call.timeout)
    args = list(args or [])
    kwargs = dict(kwargs or {})

    try:
        if call.mode == "function":
            if not call.function:
                return {"ok": False, "data": {}, "error": f"{call.key} has no function path"}
            if hasattr(bridge, "safe_call"):
                response = bridge.safe_call(
                    call.function,
                    args=args,
                    kwargs=kwargs,
                    timeout=call_timeout,
                    retries=0,
                    retry_safe=True,
                    label=f"context:{call.key}",
                    operation=f"context:{call.key}",
                )
            elif hasattr(bridge, "call"):
                response = bridge.call(call.function, args=args, kwargs=kwargs, timeout=call_timeout)
            else:
                return {"ok": False, "data": {}, "error": "Bridge has no callable function execution method"}
            out = _normalize_bridge_response(response)

        elif call.mode == "python":
            source = _format_code_template(call.code, kwargs)
            if hasattr(bridge, "execute_python"):
                response = bridge.execute_python(source, timeout=call_timeout, reset_globals=True)
            elif hasattr(bridge, "call"):
                response = bridge.call("eval", args=[source], kwargs={}, timeout=call_timeout)
            else:
                return {"ok": False, "data": {}, "error": "Bridge has no Python execution method"}
            out = _normalize_bridge_response(response)
        else:
            return {"ok": False, "data": {}, "error": f"Unsupported context call mode: {call.mode}"}

        out.setdefault("ok", bool(out.get("ok")))
        out.setdefault("data", {})
        out["context_call"] = {
            "key": call.key,
            "dcc": call.dcc,
            "mode": call.mode,
            "read_only": call.read_only,
            "timeout": call_timeout,
        }
        return out
    except Exception as exc:
        return {
            "ok": False,
            "data": {},
            "error": str(exc),
            "context_call": {"key": call.key, "dcc": call.dcc, "mode": call.mode},
        }


def execute_python_context_json(
    dcc: str,
    bridge: Any,
    source: str,
    *,
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Execute a vetted/ad-hoc Python snippet and normalize JSON stdout/result.

    This is used by existing Unreal context builders while the registry gains
    more named function coverage. It still routes through the same normalization
    layer as registered calls.
    """
    temp_key = f"{normalize_dcc_name(dcc)}.__ad_hoc_python_json__"
    call = ContextCall(
        key=temp_key,
        dcc=normalize_dcc_name(dcc),
        mode="python",
        description="Ad-hoc read-only Python context snippet",
        code=textwrap.dedent(source or ""),
        timeout=timeout,
        read_only=True,
    )
    _CONTEXT_CALLS[temp_key] = call
    try:
        return execute_context_call(dcc, temp_key, bridge, timeout=timeout)
    finally:
        _CONTEXT_CALLS.pop(temp_key, None)
