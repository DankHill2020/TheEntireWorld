from __future__ import annotations

"""Unreal capability graph helpers backed by the DCC intelligence store.

This module keeps Unreal's existing static capability registry, typed operation
catalog, Python API index, and symbol index queryable through one deterministic
surface. It intentionally reuses ``dcc_intelligence`` rather than introducing a
new index.
"""

import json
import time
from typing import Any

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.bridges.unreal.unreal_intelligence import ensure_project, open_store
from tech_connector.services.unreal.capability_registry import UNREAL_CAPABILITIES
from tech_connector.services.unreal.unreal_operation_service import (
    UNREAL_OPERATIONS,
    unreal_operation_payload,
    unreal_prompt_to_operation,
)

DCC = "Unreal"


def _entrypoint_for_spec(spec) -> str:
    if spec.mode == "operation":
        return spec.operation
    if spec.mode == "function":
        return spec.function
    if spec.mode == "context_call":
        return spec.context_call
    return spec.function or spec.operation or spec.context_call


def _arg_schema(args: list[dict[str, Any]]) -> dict[str, Any]:
    required = [arg["name"] for arg in args if arg.get("required", True)]
    properties = {}
    for arg in args:
        properties[arg["name"]] = {
            "kind": arg.get("kind") or "unknown",
            "required": bool(arg.get("required", True)),
            "cardinality": arg.get("cardinality") or "one",
            "aliases": list(arg.get("aliases") or []),
            "default": arg.get("default"),
            "description": arg.get("description") or "",
        }
    return {"type": "object", "required": required, "properties": properties}


def _json_row_value(row: dict[str, Any], key: str, fallback: Any) -> Any:
    value = row.get(key)
    if not value:
        return fallback


def _tokens(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text or "")
    return {part for part in normalized.split() if len(part) > 2}


def _score_row(row: dict[str, Any], query: str, fields: tuple[str, ...]) -> int:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0
    haystack = " ".join(str(row.get(field) or "") for field in fields)
    metadata = _json_row_value(row, "metadata_json", {})
    if metadata:
        haystack += " " + json.dumps(metadata, default=str)
    hay_tokens = _tokens(haystack)
    score = len(query_tokens & hay_tokens) * 10
    compact_query = (query or "").lower().replace(" ", "_")
    compact_hay = haystack.lower().replace(" ", "_")
    if compact_query and compact_query in compact_hay:
        score += 30
    return score


def _stage(name: str, started: float, **data: Any) -> dict[str, Any]:
    return {
        "stage": name,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        **data,
    }


def _schema_from_function_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    schema = metadata.get("input_schema")
    if isinstance(schema, dict):
        return schema
    required = list(metadata.get("required") or [])
    properties = {}
    for key in required:
        properties[key] = {"required": True, "type": "Any"}
    for key, value in (metadata.get("optional") or {}).items():
        properties[key] = {"required": False, "type": "Any", "default": value}
    for param in metadata.get("parameters") or []:
        name = param.get("name")
        if not name:
            continue
        properties[name] = {
            "required": bool(param.get("required")),
            "type": param.get("type") or "Any",
            "default": param.get("default") or "",
        }
        if param.get("required") and name not in required:
            required.append(name)
    return {"type": "object", "required": required, "properties": properties}


def _validate_value(name: str, value: Any, spec: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    expected = str(spec.get("type") or spec.get("kind") or "Any")
    expected_lower = expected.lower()
    if value in (None, "") and spec.get("required"):
        return [{"param": name, "code": "missing_required", "message": f"{name} is required."}]
    if value in (None, ""):
        return []
    if "array" in expected_lower or "list" in expected_lower or spec.get("cardinality") == "many":
        if not isinstance(value, list):
            errors.append({"param": name, "code": "type_mismatch", "expected": "array", "actual": type(value).__name__})
    elif any(term in expected_lower for term in ("bool", "boolean")) and not isinstance(value, bool):
        errors.append({"param": name, "code": "type_mismatch", "expected": "bool", "actual": type(value).__name__})
    elif any(term in expected_lower for term in ("int", "float", "double", "number")) and not isinstance(value, (int, float)):
        errors.append({"param": name, "code": "type_mismatch", "expected": expected, "actual": type(value).__name__})
    elif "str" in expected_lower or "name" in expected_lower or "path" in expected_lower:
        if not isinstance(value, str):
            errors.append({"param": name, "code": "type_mismatch", "expected": "string", "actual": type(value).__name__})
    if ("asset" in name.lower() and "path" in name.lower()) or "asset_path" in expected_lower:
        if isinstance(value, str) and not (value.startswith("/Game/") or value.startswith("/Script/") or value.startswith("/Engine/") or value.startswith("/Plugin/")):
            errors.append({"param": name, "code": "invalid_asset_path", "message": "Asset paths should use Unreal package paths such as /Game/Folder/Asset."})
    enum_values = spec.get("enum_values") or spec.get("choices") or []
    if enum_values:
        allowed = [item.get("name", item) if isinstance(item, dict) else item for item in enum_values]
        if value not in allowed:
            errors.append({"param": name, "code": "invalid_enum", "allowed": allowed, "actual": value})
    return errors


def _validate_schema(schema: dict[str, Any], params: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    required = list(schema.get("required") or [])
    properties = schema.get("properties") or {}
    missing = [key for key in required if key not in params or params.get(key) in (None, "")]
    errors: list[dict[str, Any]] = []
    for key in missing:
        errors.append({"param": key, "code": "missing_required", "message": f"{key} is required."})
    for key, value in params.items():
        spec = properties.get(key)
        if isinstance(spec, dict):
            errors.extend(_validate_value(key, value, spec))
    return missing, errors
    try:
        return json.loads(value)
    except Exception:
        return fallback


def sync_unreal_capability_graph(project_root: str | None = None) -> dict[str, Any]:
    """Upsert registered Unreal capabilities and operation specs into the graph."""
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        capability_count = 0
        function_count = 0

        for name, spec in UNREAL_CAPABILITIES.items():
            data = spec.to_dict()
            entrypoint = _entrypoint_for_spec(spec)
            tags = sorted(set([*data.get("tags", []), spec.domain, spec.phase, spec.mode, "unreal"]))
            store.upsert_capability(
                project.id,
                DCC,
                name=name,
                description=spec.description,
                entrypoint=entrypoint,
                source_path="services/unreal/capability_registry.py",
                risk_level=spec.risk,
                input_schema=_arg_schema(data.get("expects") or []),
                output_schema={"produces": list(spec.produces)},
                tags=tags,
                metadata={
                    "source": "unreal_capability_registry",
                    "mode": spec.mode,
                    "domain": spec.domain,
                    "phase": spec.phase,
                    "read_only": spec.read_only,
                    "timeout": spec.timeout,
                    "requires_live_unreal": spec.requires_live_unreal,
                    "requires_project": spec.requires_project,
                    "requires_selection": spec.requires_selection,
                    "requires_asset_types": list(spec.requires_asset_types),
                    "supports_dry_run": spec.supports_dry_run,
                    "supports_batch": spec.supports_batch,
                    "aliases": list(spec.aliases),
                    "preflight": list(spec.preflight),
                    "validate": list(spec.validate),
                    "rollback": list(spec.rollback),
                    "permissions": list(spec.permissions),
                    "fallback_capabilities": list(spec.fallback_capabilities),
                    "recommended_model": spec.recommended_model,
                    "enabled": spec.enabled,
                    "version": spec.version,
                    "spec": data,
                },
            )
            store.upsert_symbol(
                project.id,
                DCC,
                symbol_key=f"capability.{name}",
                symbol_kind="capability",
                display_name=name,
                qualified_name=entrypoint,
                source_ref="services/unreal/capability_registry.py",
                summary=spec.description,
                metadata={"tags": tags, "risk_level": spec.risk, "mode": spec.mode},
            )
            if entrypoint:
                store.add_dependency(
                    project.id,
                    DCC,
                    source_kind="capability",
                    source_ref=name,
                    target_kind=spec.mode,
                    target_ref=entrypoint,
                    relation="executes",
                    metadata={"source": "unreal_capability_registry"},
                )
            capability_count += 1

        for key, op in UNREAL_OPERATIONS.items():
            tags = sorted(set(["unreal", "operation", *key.replace(".", " ").split()]))
            input_schema = {
                "type": "object",
                "required": list(op.required),
                "properties": {
                    **{name: {"required": True, "default": None} for name in op.required},
                    **{name: {"required": False, "default": value} for name, value in op.optional.items()},
                },
            }
            risk = "medium" if op.mutates_project else "read_only"
            store.upsert_capability(
                project.id,
                DCC,
                name=key,
                description=op.description,
                entrypoint=op.function,
                source_path="services/unreal/unreal_operation_service.py",
                risk_level=risk,
                input_schema=input_schema,
                output_schema={"result": "bridge_response"},
                tags=tags,
                metadata={
                    "source": "unreal_operation_service",
                    "operation_key": key,
                    "label": op.label,
                    "function": op.function,
                    "required": list(op.required),
                    "optional": op.optional,
                    "mutates_project": op.mutates_project,
                },
            )
            store.upsert_function(
                project.id,
                DCC,
                function_name=op.function.rsplit(".", 1)[-1],
                qualified_name=op.function,
                source_path="services/unreal/unreal_operation_service.py",
                signature=f"{op.function}(**operation_payload)",
                docstring=op.description,
                metadata={
                    "source": "unreal_operation_service",
                    "operation_key": key,
                    "required": list(op.required),
                    "optional": op.optional,
                    "mutates_project": op.mutates_project,
                },
            )
            store.upsert_symbol(
                project.id,
                DCC,
                symbol_key=f"operation.{key}",
                symbol_kind="operation",
                display_name=op.label,
                qualified_name=op.function,
                source_ref="services/unreal/unreal_operation_service.py",
                summary=op.description,
                metadata={"tags": tags, "risk_level": risk},
            )
            store.add_dependency(
                project.id,
                DCC,
                source_kind="operation",
                source_ref=key,
                target_kind="function",
                target_ref=op.function,
                relation="executes",
                metadata={"source": "unreal_operation_service"},
            )
            capability_count += 1
            function_count += 1

        return {
            "success": True,
            "project_id": project.id,
            "capabilities_indexed": capability_count,
            "functions_indexed": function_count,
        }
    finally:
        store.close()


def search_unreal_capability_graph(
    query: str,
    project_root: str | None = None,
    *,
    limit: int = 20,
    sync: bool = True,
) -> dict[str, Any]:
    if sync:
        sync_unreal_capability_graph(project_root)
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        q = query or ""
        return {
            "success": True,
            "query": q,
            "project_id": project.id,
            "capabilities": store.search_capabilities(project.id, q, limit=limit),
            "functions": store.search_functions(project.id, q, limit=limit, dcc=DCC),
            "python_api": store.search_python_api(project.id, DCC, q, limit=limit),
            "symbols": store.search_symbols(project.id, DCC, q, limit=limit),
        }
    finally:
        store.close()


def resolve_unreal_graph_item(
    name: str,
    project_root: str | None = None,
    *,
    sync: bool = True,
) -> dict[str, Any]:
    if sync:
        sync_unreal_capability_graph(project_root)
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        rows = {
            "capabilities": store.search_capabilities(project.id, name, limit=10),
            "functions": store.search_functions(project.id, name, limit=10, dcc=DCC),
            "python_api": store.search_python_api(project.id, DCC, name, limit=10),
            "symbols": store.get_symbol(project.id, DCC, name, limit=10)
            or store.search_symbols(project.id, DCC, name, limit=10),
        }
        return {"success": True, "query": name, "project_id": project.id, **rows}
    finally:
        store.close()


def resolve_unreal_capability(
    request: str,
    project_root: str | None = None,
    *,
    limit: int = 10,
    sync: bool = True,
) -> dict[str, Any]:
    """Resolve a natural request to an indexed Unreal callable."""
    started = time.monotonic()
    diagnostics: list[dict[str, Any]] = []
    text = request or ""
    if sync:
        t0 = time.monotonic()
        sync_result = sync_unreal_capability_graph(project_root)
        diagnostics.append(_stage("capability_graph_sync", t0, result=sync_result))

    operation_key = unreal_prompt_to_operation(text)
    q = text.lower()
    operation_is_explicit = operation_key != "level.scan_loaded" or any(
        term in q for term in ("loaded level", "current level", "level actors", "actors in")
    )
    if operation_is_explicit and operation_key in UNREAL_OPERATIONS:
        op = UNREAL_OPERATIONS[operation_key]
        resolution = {
            "kind": "operation",
            "name": operation_key,
            "entrypoint": op.function,
            "label": op.label,
            "description": op.description,
            "risk": "medium" if op.mutates_project else "read_only",
            "required": list(op.required),
            "optional": op.optional,
            "source": "unreal_operation_service",
            "score": 100,
        }
        diagnostics.append(_stage("function_resolution", started, strategy="operation_inference", selected=resolution))
        return {
            "success": True,
            "request": text,
            "resolution": resolution,
            "candidates": [resolution],
            "diagnostics": diagnostics,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }

    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        candidates: list[dict[str, Any]] = []
        search_terms = [text, *_tokens(text)]
        seen_rows: set[tuple[str, Any]] = set()

        def add_candidate(kind: str, row: dict[str, Any], fields: tuple[str, ...]) -> None:
            marker = (kind, row.get("id") or row.get("qualified_name") or row.get("name") or row.get("symbol_key"))
            if marker in seen_rows:
                return
            seen_rows.add(marker)
            score = _score_row(row, text, fields)
            candidates.append({
                "kind": kind,
                "name": row.get("name") or row.get("qualified_name") or row.get("symbol_key"),
                "entrypoint": row.get("entrypoint") or row.get("qualified_name"),
                "description": row.get("description") or row.get("docstring") or row.get("summary"),
                "signature": row.get("signature"),
                "risk": row.get("risk_level"),
                "source": row.get("source_path") or row.get("source"),
                "score": score,
                "row": row,
            })

        for term in search_terms:
            for row in store.search_capabilities(project.id, term, limit=limit):
                add_candidate("capability", row, ("name", "description", "entrypoint", "tags_json"))
            for row in store.search_functions(project.id, term, limit=limit, dcc=DCC):
                add_candidate("function", row, ("function_name", "qualified_name", "signature", "docstring"))
            for row in store.search_python_api(project.id, DCC, term, limit=limit):
                if row.get("object_type") not in {"function", "method"}:
                    continue
                add_candidate(row.get("object_type") or "python_api", row, ("qualified_name", "signature", "docstring", "object_type"))
        candidates.sort(key=lambda item: (item.get("score") or 0, len(str(item.get("entrypoint") or ""))), reverse=True)
        selected = candidates[0] if candidates and candidates[0].get("score", 0) > 0 else None
        diagnostics.append(_stage("function_resolution", started, strategy="metadata_search", selected=selected, candidate_count=len(candidates)))
        return {
            "success": bool(selected),
            "request": text,
            "resolution": selected,
            "candidates": candidates[:limit],
            "diagnostics": diagnostics,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "error": "" if selected else "No indexed Unreal callable matched the request.",
        }
    finally:
        store.close()


def validate_unreal_graph_call(
    name: str,
    payload: dict[str, Any] | None = None,
    project_root: str | None = None,
    *,
    sync: bool = True,
) -> dict[str, Any]:
    """Validate required inputs for an indexed Unreal operation/capability."""
    if sync:
        sync_unreal_capability_graph(project_root)
    payload = dict(payload or {})
    params = dict(payload.get("kwargs") or payload.get("params") or payload)
    try:
        from tech_connector.services.unreal.unreal_operation_service import normalize_unreal_package_path
        for p_key in ("asset_path", "target_path", "blueprint_path"):
            if p_key in params and isinstance(params[p_key], str):
                default_name = "NE_AIStudioEmitter" if "niagara" in name else ("BP_NewBlueprint" if "blueprint" in name else "Asset")
                params[p_key] = normalize_unreal_package_path(params[p_key], default_name=default_name)
    except Exception:
        pass

    if name in UNREAL_OPERATIONS:
        try:
            operation_payload = unreal_operation_payload(name, params)
            op = UNREAL_OPERATIONS[name]
            schema = {
                "required": list(op.required),
                "properties": {
                    **{key: {"required": True, "type": "Any"} for key in op.required},
                    **{key: {"required": False, "type": "Any", "default": value} for key, value in op.optional.items()},
                },
            }
            missing, validation_errors = _validate_schema(schema, params)
            if validation_errors:
                return {
                    "success": True,
                    "valid": False,
                    "kind": "operation",
                    "name": name,
                    "missing": missing,
                    "errors": validation_errors,
                    "payload": operation_payload,
                }
            return {
                "success": True,
                "valid": True,
                "kind": "operation",
                "name": name,
                "payload": operation_payload,
                "missing": [],
                "errors": [],
            }
        except Exception as exc:
            op = UNREAL_OPERATIONS[name]
            missing = [
                key for key in op.required
                if key not in params or params.get(key) in (None, "")
            ]
            return {
                "success": True,
                "valid": False,
                "kind": "operation",
                "name": name,
                "missing": missing,
                "errors": [str(exc)],
            }

    if name in UNREAL_CAPABILITIES:
        spec = UNREAL_CAPABILITIES[name]
        schema = _arg_schema([arg.to_dict() for arg in spec.expects])
        missing, validation_errors = _validate_schema(schema, params)
        return {
            "success": True,
            "valid": not validation_errors,
            "kind": "capability",
            "name": name,
            "entrypoint": _entrypoint_for_spec(spec),
            "mode": spec.mode,
            "risk": spec.risk,
            "missing": missing,
            "errors": validation_errors,
        }

    resolved = resolve_unreal_graph_item(name, project_root, sync=False)
    functions = resolved.get("functions") or []
    if functions:
        row = functions[0]
        metadata = _json_row_value(row, "metadata_json", {})
        schema = _schema_from_function_metadata(metadata)
        missing, validation_errors = _validate_schema(schema, params)
        return {
            "success": True,
            "valid": not validation_errors,
            "kind": "function",
            "name": row.get("qualified_name") or name,
            "missing": missing,
            "errors": validation_errors,
            "metadata": metadata,
        }

    return {
        "success": True,
        "valid": False,
        "kind": "unknown",
        "name": name,
        "missing": [],
        "errors": ["No indexed Unreal capability, operation, or function matched this name."],
    }


def execute_unreal_capability(
    request_or_name: str,
    payload: dict[str, Any] | None = None,
    project_root: str | None = None,
    *,
    timeout: float = 30.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the canonical deterministic Unreal execution pipeline."""
    started = time.monotonic()
    diagnostics: list[dict[str, Any]] = []
    request = request_or_name or ""
    payload = dict(payload or {})

    t0 = time.monotonic()
    resolution_result = resolve_unreal_capability(request, project_root, sync=True)
    diagnostics.append(_stage("capability_search_and_resolution", t0, result=resolution_result))
    resolution = resolution_result.get("resolution")
    if not resolution:
        return {
            "success": False,
            "stage": "function_resolution",
            "request": request,
            "diagnostics": diagnostics,
            "error": resolution_result.get("error") or "No callable resolved.",
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }

    name = resolution.get("name") or resolution.get("entrypoint") or request
    if resolution.get("kind") in {"function", "method"} and resolution.get("entrypoint"):
        name = resolution["entrypoint"]

    t0 = time.monotonic()
    validation = validate_unreal_graph_call(name, payload, project_root, sync=False)
    diagnostics.append(_stage("argument_validation", t0, result=validation))
    if not validation.get("valid"):
        return {
            "success": False,
            "stage": "argument_validation",
            "request": request,
            "resolution": resolution,
            "validation": validation,
            "diagnostics": diagnostics,
            "error": "Argument validation failed.",
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }

    execution_payload = validation.get("payload")
    function_path = None
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    operation = name
    if isinstance(execution_payload, dict):
        function_path = execution_payload.get("function")
        args = list(execution_payload.get("args") or [])
        kwargs = dict(execution_payload.get("kwargs") or {})
        operation = execution_payload.get("operation") or operation
    else:
        function_path = resolution.get("entrypoint") or name
        kwargs = dict(payload.get("kwargs") or payload)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "request": request,
            "resolution": resolution,
            "validation": validation,
            "execution_payload": {"function": function_path, "args": args, "kwargs": kwargs, "operation": operation},
            "diagnostics": diagnostics,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }

    t0 = time.monotonic()
    bridge = UnrealBridge()
    if str(function_path or "").startswith("unreal."):
        source = f"""
import json
import unreal

function_path = {function_path!r}
args = {json.dumps(args, default=str)}
kwargs = {json.dumps(kwargs, default=str)}
target = unreal
for part in function_path.split('.')[1:]:
    target = getattr(target, part)
result = target(*args, **kwargs)
try:
    encoded = result
    json.dumps(encoded)
except Exception:
    encoded = str(result)
print(json.dumps({{"ok": True, "function": function_path, "result": encoded}}, default=str))
"""
        bridge_result = bridge.execute_python(
            source,
            timeout=timeout,
            reset_globals=True,
        )
    else:
        bridge_result = bridge.safe_call(
            function_path,
            args=args,
            kwargs=kwargs,
            timeout=timeout,
            label="capability_graph_execute",
            operation=operation,
        )
    diagnostics.append(_stage("bridge_execution", t0, result={
        "ok": bridge_result.get("ok"),
        "request_id": bridge_result.get("request_id"),
        "duration_ms": bridge_result.get("duration_ms"),
        "endpoint": bridge_result.get("endpoint"),
        "errors": bridge_result.get("errors"),
    }))
    return {
        "success": bool(bridge_result.get("ok")),
        "stage": "structured_result",
        "request": request,
        "resolution": resolution,
        "validation": validation,
        "execution_payload": {"function": function_path, "args": args, "kwargs": kwargs, "operation": operation},
        "bridge_result": bridge_result,
        "diagnostics": diagnostics,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
    }
