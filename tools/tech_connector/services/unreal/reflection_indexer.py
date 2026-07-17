from __future__ import annotations

"""Bridge-driven Unreal Python reflection indexing.

The reflection scan runs inside Unreal through the existing HTTP bridge, then
persists the returned metadata into the existing DCC intelligence database.
"""

import json
import time
from typing import Any

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.bridges.unreal.unreal_intelligence import ensure_project, open_store

DCC = "Unreal"


REFLECTION_SCRIPT = r'''
import inspect
import json
import time

import unreal


def safe_str(value):
    try:
        return str(value)
    except Exception:
        return ""


def short_doc(obj, limit=4000):
    try:
        doc = inspect.getdoc(obj) or getattr(obj, "__doc__", "") or ""
        return safe_str(doc)[:limit]
    except Exception:
        return ""


def signature_text(obj):
    try:
        return str(inspect.signature(obj))
    except Exception:
        doc = short_doc(obj, limit=1000)
        first = doc.splitlines()[0].strip() if doc else ""
        if "(" in first and ")" in first:
            return first
        return ""


def annotation_name(value):
    if value is inspect._empty:
        return ""
    return safe_str(value).replace("<class '", "").replace("'>", "")


def params_for(obj):
    try:
        sig = inspect.signature(obj)
    except Exception:
        return []
    out = []
    for name, param in sig.parameters.items():
        out.append({
            "name": name,
            "kind": safe_str(param.kind),
            "type": annotation_name(param.annotation),
            "default": "" if param.default is inspect._empty else safe_str(param.default),
            "required": param.default is inspect._empty and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ),
        })
    return out


def classify(name, obj):
    text = safe_str(type(obj)).lower() + " " + safe_str(obj).lower() + " " + name.lower()
    if inspect.ismodule(obj):
        return "module"
    if inspect.isclass(obj):
        if "enum" in text:
            return "enum"
        if "delegate" in text:
            return "delegate"
        if "struct" in text:
            return "struct"
        return "class"
    if callable(obj):
        if "delegate" in text:
            return "delegate"
        return "function"
    if "enum" in text:
        return "enum"
    if "delegate" in text:
        return "delegate"
    return "property"


def class_members(cls, class_name, max_members=220):
    members = []
    for member_name in dir(cls)[:max_members]:
        if member_name.startswith("__") and member_name.endswith("__"):
            continue
        try:
            member = getattr(cls, member_name)
        except Exception:
            continue
        kind = classify(member_name, member)
        if kind == "function":
            kind = "method"
        row = {
            "name": member_name,
            "qualified_name": class_name + "." + member_name,
            "kind": kind,
            "signature": signature_text(member) if callable(member) else "",
            "parameters": params_for(member) if callable(member) else [],
            "return_type": "",
            "default": "" if callable(member) else safe_str(member)[:500],
            "docstring": short_doc(member, limit=1200),
            "callable_path": class_name + "." + member_name if callable(member) else "",
        }
        try:
            sig = inspect.signature(member)
            row["return_type"] = annotation_name(sig.return_annotation)
        except Exception:
            pass
        members.append(row)
    return members


def enum_values(obj):
    values = []
    try:
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:
                continue
            if not callable(value):
                values.append({"name": name, "value": safe_str(value)})
    except Exception:
        pass
    return values[:500]


started = time.time()
items = []
names = [name for name in dir(unreal) if not name.startswith("_")]
for name in names:
    try:
        obj = getattr(unreal, name)
    except Exception:
        continue
    kind = classify(name, obj)
    qualified_name = "unreal." + name
    row = {
        "name": name,
        "qualified_name": qualified_name,
        "module": "unreal",
        "kind": kind,
        "signature": signature_text(obj) if callable(obj) else "",
        "parameters": params_for(obj) if callable(obj) else [],
        "return_type": "",
        "base_classes": [],
        "properties": [],
        "methods": [],
        "enum_values": [],
        "docstring": short_doc(obj),
        "callable_path": qualified_name if callable(obj) else "",
    }
    try:
        sig = inspect.signature(obj)
        row["return_type"] = annotation_name(sig.return_annotation)
    except Exception:
        pass
    if inspect.isclass(obj):
        try:
            row["base_classes"] = [
                base.__module__ + "." + base.__name__
                for base in getattr(obj, "__mro__", ())[1:]
                if getattr(base, "__name__", "object") != "object"
            ]
        except Exception:
            row["base_classes"] = []
        members = class_members(obj, qualified_name)
        row["methods"] = [m for m in members if m.get("kind") == "method"]
        row["properties"] = [m for m in members if m.get("kind") not in {"method"}]
    if kind == "enum":
        row["enum_values"] = enum_values(obj)
    items.append(row)

print(json.dumps({
    "success": True,
    "source": "unreal_reflection",
    "module": "unreal",
    "duration_ms": round((time.time() - started) * 1000, 2),
    "count": len(items),
    "items": items,
}, default=str))
'''


def _response_payload(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("result"), dict):
            return data["result"]
        if data.get("items"):
            return data
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            pass
    raw = response.get("raw")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            pass
    return {"success": False, "error": response.get("error") or "Reflection response did not contain JSON payload."}


def _param_schema(parameters: list[dict[str, Any]]) -> dict[str, Any]:
    required = [p.get("name") for p in parameters if p.get("required") and p.get("name")]
    properties = {}
    for param in parameters:
        name = param.get("name")
        if not name:
            continue
        properties[name] = {
            "type": param.get("type") or "Any",
            "kind": param.get("kind") or "",
            "default": param.get("default") or "",
            "required": bool(param.get("required")),
        }
    return {"type": "object", "required": required, "properties": properties}


def persist_reflection_payload(payload: dict[str, Any], project_root: str | None = None) -> dict[str, Any]:
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        counts = {
            "modules": 0,
            "classes": 0,
            "structs": 0,
            "enums": 0,
            "functions": 0,
            "methods": 0,
            "properties": 0,
            "delegates": 0,
            "python_api": 0,
            "symbols": 0,
        }

        module_name = payload.get("module") or "unreal"
        store.upsert_python_api(
            project.id,
            DCC,
            qualified_name=module_name,
            object_type="module",
            signature="",
            docstring="Unreal Python API module reflected from a live Unreal editor.",
            source="unreal_reflection",
            tags=["unreal", "module", "reflection"],
            metadata={"source": "unreal_reflection", "duration_ms": payload.get("duration_ms")},
        )
        store.upsert_symbol(
            project.id,
            DCC,
            symbol_key=module_name,
            symbol_kind="module",
            display_name=module_name,
            qualified_name=module_name,
            source_ref="unreal_reflection",
            summary="Live Unreal Python module",
            metadata={"source": "unreal_reflection"},
        )
        counts["modules"] += 1
        counts["python_api"] += 1
        counts["symbols"] += 1

        for item in payload.get("items") or []:
            kind = item.get("kind") or "unknown"
            qualified_name = item.get("qualified_name") or item.get("name")
            if not qualified_name:
                continue
            name = item.get("name") or qualified_name.rsplit(".", 1)[-1]
            metadata = {
                "source": "unreal_reflection",
                "module": item.get("module") or module_name,
                "base_classes": item.get("base_classes") or [],
                "parameters": item.get("parameters") or [],
                "return_type": item.get("return_type") or "",
                "properties": item.get("properties") or [],
                "methods": item.get("methods") or [],
                "enum_values": item.get("enum_values") or [],
                "callable_path": item.get("callable_path") or "",
            }
            tags = ["unreal", "reflection", kind]
            store.upsert_python_api(
                project.id,
                DCC,
                qualified_name=qualified_name,
                object_type=kind,
                signature=item.get("signature") or "",
                docstring=item.get("docstring") or "",
                source="unreal_reflection",
                tags=tags,
                metadata=metadata,
            )
            store.upsert_symbol(
                project.id,
                DCC,
                symbol_key=qualified_name,
                symbol_kind=kind,
                display_name=name,
                qualified_name=qualified_name,
                source_ref="unreal_reflection",
                summary=item.get("docstring") or item.get("signature") or kind,
                metadata=metadata,
            )
            counts["python_api"] += 1
            counts["symbols"] += 1
            count_key = {
                "class": "classes",
                "struct": "structs",
                "enum": "enums",
                "function": "functions",
                "delegate": "delegates",
                "property": "properties",
            }.get(kind)
            if count_key:
                counts[count_key] += 1

            if kind in {"class", "struct"}:
                store.upsert_class(
                    project.id,
                    DCC,
                    class_name=qualified_name,
                    module_name=item.get("module") or module_name,
                    source_path="unreal_reflection",
                    base_class=", ".join(item.get("base_classes") or []),
                    metadata=metadata,
                )
                for base in item.get("base_classes") or []:
                    store.add_dependency(
                        project.id,
                        DCC,
                        source_kind=kind,
                        source_ref=qualified_name,
                        target_kind="class",
                        target_ref=base,
                        relation="inherits",
                        metadata={"source": "unreal_reflection"},
                    )

            if kind == "function":
                store.upsert_function(
                    project.id,
                    DCC,
                    function_name=name,
                    qualified_name=qualified_name,
                    source_path="unreal_reflection",
                    signature=item.get("signature") or "",
                    docstring=item.get("docstring") or "",
                    metadata={**metadata, "input_schema": _param_schema(item.get("parameters") or [])},
                )

            for method in item.get("methods") or []:
                method_qn = method.get("qualified_name")
                if not method_qn:
                    continue
                method_meta = {
                    "source": "unreal_reflection",
                    "owner": qualified_name,
                    "parameters": method.get("parameters") or [],
                    "return_type": method.get("return_type") or "",
                    "callable_path": method.get("callable_path") or method_qn,
                    "input_schema": _param_schema(method.get("parameters") or []),
                }
                store.upsert_function(
                    project.id,
                    DCC,
                    function_name=method.get("name") or method_qn.rsplit(".", 1)[-1],
                    qualified_name=method_qn,
                    source_path="unreal_reflection",
                    class_name=qualified_name,
                    signature=method.get("signature") or "",
                    docstring=method.get("docstring") or "",
                    metadata=method_meta,
                )
                store.upsert_python_api(
                    project.id,
                    DCC,
                    qualified_name=method_qn,
                    object_type="method",
                    signature=method.get("signature") or "",
                    docstring=method.get("docstring") or "",
                    source="unreal_reflection",
                    tags=["unreal", "reflection", "method"],
                    metadata=method_meta,
                )
                store.upsert_symbol(
                    project.id,
                    DCC,
                    symbol_key=method_qn,
                    symbol_kind="method",
                    display_name=method.get("name"),
                    qualified_name=method_qn,
                    source_ref="unreal_reflection",
                    summary=method.get("docstring") or method.get("signature") or "method",
                    metadata=method_meta,
                )
                counts["methods"] += 1
                counts["functions"] += 1
                counts["python_api"] += 1
                counts["symbols"] += 1
                store.add_dependency(
                    project.id,
                    DCC,
                    source_kind="class",
                    source_ref=qualified_name,
                    target_kind="method",
                    target_ref=method_qn,
                    relation="owns",
                    metadata={"source": "unreal_reflection"},
                )

            for prop in item.get("properties") or []:
                prop_qn = prop.get("qualified_name")
                if not prop_qn:
                    continue
                store.upsert_python_api(
                    project.id,
                    DCC,
                    qualified_name=prop_qn,
                    object_type=prop.get("kind") or "property",
                    signature="",
                    docstring=prop.get("docstring") or "",
                    source="unreal_reflection",
                    tags=["unreal", "reflection", prop.get("kind") or "property"],
                    metadata={"source": "unreal_reflection", "owner": qualified_name, "default": prop.get("default")},
                )
                store.upsert_symbol(
                    project.id,
                    DCC,
                    symbol_key=prop_qn,
                    symbol_kind=prop.get("kind") or "property",
                    display_name=prop.get("name"),
                    qualified_name=prop_qn,
                    source_ref="unreal_reflection",
                    summary=prop.get("docstring") or prop.get("default") or "property",
                    metadata={"source": "unreal_reflection", "owner": qualified_name},
                )
                counts["properties"] += 1
                counts["python_api"] += 1
                counts["symbols"] += 1
                store.add_dependency(
                    project.id,
                    DCC,
                    source_kind="class",
                    source_ref=qualified_name,
                    target_kind="property",
                    target_ref=prop_qn,
                    relation="owns",
                    metadata={"source": "unreal_reflection"},
                )

        return {
            "success": True,
            "project_id": project.id,
            "source_count": payload.get("count"),
            "duration_ms": payload.get("duration_ms"),
            "counts": counts,
        }
    finally:
        store.close()


def refresh_unreal_reflection_index(project_root: str | None = None, *, timeout: float = 60.0) -> dict[str, Any]:
    started = time.monotonic()
    response = UnrealBridge().execute_python(REFLECTION_SCRIPT, timeout=timeout, reset_globals=True)
    payload = _response_payload(response)
    if not payload.get("success"):
        return {
            "success": False,
            "stage": "reflection_bridge",
            "error": payload.get("error") or response.get("error") or "Unreal reflection failed.",
            "bridge_response": response,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
    persisted = persist_reflection_payload(payload, project_root)
    return {
        "success": bool(persisted.get("success")),
        "stage": "reflection_index",
        "reflection": {
            "count": payload.get("count"),
            "duration_ms": payload.get("duration_ms"),
        },
        "persisted": persisted,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
    }
