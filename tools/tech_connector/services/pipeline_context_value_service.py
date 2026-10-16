"""Resolve pipeline input values from the live context of a DCC host."""

from __future__ import annotations

import ast
import json
import re
from typing import Any


HOST_ALIASES = {
    "3ds_max": "3dsmax",
    "3ds max": "3dsmax",
    "max": "3dsmax",
    "mobu": "motionbuilder",
    "substance": "substance_painter",
}

HOST_LABELS = {
    "maya": "Maya",
    "blender": "Blender",
    "unreal": "Unreal",
    "unity": "Unity",
    "houdini": "Houdini",
    "motionbuilder": "MotionBuilder",
    "3dsmax": "3ds Max",
    "substance_painter": "Substance Painter",
}

_SELECTION_NAMES = {
    "selection",
    "selected",
    "objects",
    "object",
    "nodes",
    "node",
    "joints",
    "joint",
    "meshes",
    "mesh",
    "actors",
    "actor",
    "assets",
    "asset",
    "components",
    "component",
    "materials",
    "material",
    "items",
    "item",
    "targets",
    "target",
    "source_assets",
    "selected_assets",
    "selected_actors",
    "selected_objects",
}


def normalize_pipeline_host(value: Any) -> str:
    host = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return HOST_ALIASES.get(host, host)


def pipeline_symbol_host(symbol: dict[str, Any] | None) -> str:
    symbol = symbol or {}
    for key in ("host", "provider_id", "dcc", "application", "package"):
        host = normalize_pipeline_host(symbol.get(key))
        if host in HOST_LABELS:
            return host
    searchable = " ".join(
        str(symbol.get(key) or "")
        for key in ("name", "function_path", "module", "file_path", "operation")
    ).lower()
    for host in HOST_LABELS:
        aliases = {host, host.replace("_", " ")}
        if host == "3dsmax":
            aliases.update({"3ds max", "3ds_max", "max_tools"})
        if any(alias in searchable for alias in aliases):
            return host
    return ""


def selection_parameter_spec(
    symbol: dict[str, Any] | None,
    name: str,
    annotation: str = "",
) -> dict[str, Any] | None:
    """Describe a live-selection action for a selection-shaped input."""

    normalized_name = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")
    tokens = {token for token in normalized_name.split("_") if token}
    selection_shaped = normalized_name in _SELECTION_NAMES or bool(
        tokens.intersection(_SELECTION_NAMES)
    )
    if not selection_shaped:
        return None
    host = pipeline_symbol_host(symbol)
    if not host:
        return None
    annotation_l = str(annotation or "").lower()
    multiple = (
        normalized_name.endswith("s")
        or normalized_name in {"selection", "selected"}
        or any(marker in annotation_l for marker in ("list", "tuple", "set", "sequence", "iterable"))
    )
    return {
        "host": host,
        "host_label": HOST_LABELS.get(host, host.replace("_", " ").title()),
        "input": normalized_name,
        "multiple": multiple,
        "label": f"Use {HOST_LABELS.get(host, host.title())} Selection",
    }


def _parse_candidate(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return []
    for candidate in (text, *reversed([line.strip() for line in text.splitlines() if line.strip()])):
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            pass
        try:
            return ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            pass
    return text


def _selection_strings(value: Any, *, input_name: str = "") -> list[str]:
    value = _parse_candidate(value)
    if isinstance(value, dict):
        input_l = str(input_name or "").lower()
        preferred = (
            ("selected_assets", "assets", "selection")
            if "asset" in input_l or "material" in input_l
            else ("selected_actors", "selected_objects", "objects", "selection", "selected_assets")
        )
        for key in preferred:
            if key in value:
                return _selection_strings(value.get(key), input_name=input_name)
        for key in ("result", "data", "python_result", "python_stdout", "stdout", "raw"):
            if key in value:
                parsed = _selection_strings(value.get(key), input_name=input_name)
                if parsed:
                    return parsed
        candidate = value.get("path") or value.get("native_id") or value.get("name")
        return [str(candidate)] if candidate not in (None, "") else []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            if isinstance(item, dict):
                candidate = item.get("path") or item.get("native_id") or item.get("name")
            else:
                candidate = item
            if candidate not in (None, ""):
                result.append(str(candidate))
        return result
    return [str(value)] if value not in (None, "") else []


def read_pipeline_host_selection(
    command_router: Any,
    *,
    host: str,
    input_name: str,
    multiple: bool = True,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Read and normalize the active selection without mutating the host scene."""

    host = normalize_pipeline_host(host)
    bridge_name = "max" if host == "3dsmax" else host
    bridge = getattr(command_router, bridge_name, None) if command_router is not None else None
    if bridge is None:
        return {"ok": False, "host": host, "error": f"{HOST_LABELS.get(host, host)} bridge is unavailable."}

    raw: Any = None
    if host == "unreal" and hasattr(bridge, "health_check"):
        raw = bridge.health_check(timeout=min(max(float(timeout), 0.1), 5.0))
        if not raw.get("connected"):
            return {
                "ok": False,
                "host": host,
                "error": str(raw.get("error") or "Unreal bridge is offline."),
            }
    elif hasattr(bridge, "get_selection_code") and hasattr(bridge, "execute"):
        port = bridge.find_port() if hasattr(bridge, "find_port") else True
        if not port:
            return {
                "ok": False,
                "host": host,
                "error": f"{HOST_LABELS.get(host, host)} bridge is offline.",
            }
        ok, raw = bridge.execute(bridge.get_selection_code(), timeout=timeout)
        if not ok:
            return {"ok": False, "host": host, "error": str(raw or "Selection query failed.")}
    else:
        return {
            "ok": False,
            "host": host,
            "error": f"{HOST_LABELS.get(host, host)} does not expose live selection through its bridge yet.",
        }

    selection = _selection_strings(raw, input_name=input_name)
    if not selection:
        return {
            "ok": False,
            "host": host,
            "error": f"Nothing is selected in {HOST_LABELS.get(host, host)}.",
            "selection": [],
        }
    value: Any = selection if multiple else selection[0]
    return {
        "ok": True,
        "host": host,
        "host_label": HOST_LABELS.get(host, host),
        "selection": selection,
        "value": value,
        "count": len(selection),
    }

