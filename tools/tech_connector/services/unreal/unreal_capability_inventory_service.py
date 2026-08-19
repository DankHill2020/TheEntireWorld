from __future__ import annotations

"""Canonical Unreal capability inventory.

Every planner-facing Unreal callable should be discoverable here, regardless of
whether its implementation lives in Python, the AIStudioBridge plugin, or a
declared domain C++ wrapper requirement.
"""

from pathlib import Path
from typing import Any
import ast
from functools import lru_cache
import json
import re
import sqlite3


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_MANIFEST_PATH = ROOT / "plugins" / "AIStudioBridge" / "AIStudioBridgeCapabilities.json"
PLUGIN_HEADER_PATH = ROOT / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Public" / "AIStudioBridgeLibrary.h"
PLUGIN_CPP_PATH = ROOT / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp"


@lru_cache(maxsize=8)
def build_unreal_capability_inventory(project_root: str | None = None) -> dict[str, Any]:
    from tech_connector.services.unreal.capability_registry import UNREAL_CAPABILITIES
    from tech_connector.services.unreal.cpp_domain_wrapper_requirements_service import (
        DOMAIN_WRAPPER_REQUIREMENTS,
    )
    from tech_connector.services.unreal.domain_operation_coverage_service import (
        classify_domain_operation,
    )
    from tech_connector.services.unreal.unreal_operation_service import (
        UNREAL_OPERATIONS,
        UNREAL_OPERATIONS_REQUIRING_IMPLEMENTATION_STRATEGY,
    )

    manifest = _load_plugin_manifest()
    header_functions = _parse_header_functions(PLUGIN_HEADER_PATH)
    cpp_functions = _parse_cpp_functions()
    unreal_tools_rows = _discover_unreal_tools_functions()
    base_unreal_api_count = _count_base_unreal_python_api(project_root)
    base_unreal_api_rows = _load_base_unreal_python_api(project_root)

    plugin_by_function = {
        row["function"]: {
            "kind": "plugin_function",
            "name": row["name"],
            "function": row["function"],
            "python_call": row.get("python_call") or "",
            "aliases": list(row.get("operation_aliases") or []),
            "location": "plugin",
            "source": str(PLUGIN_MANIFEST_PATH),
            "in_header": row["function"] in header_functions,
            "in_cpp": row["function"] in cpp_functions,
            "implementation_state": "implemented" if row["function"] in cpp_functions else "missing_cpp_body",
        }
        for row in manifest.get("capabilities") or []
    }
    operation_rows: dict[str, dict[str, Any]] = {}
    for key, op in UNREAL_OPERATIONS.items():
        plugin_function = _plugin_function_from_python_call(op.function)
        operation_rows[key] = {
            "kind": "operation",
            "name": key,
            "label": op.label,
            "function": op.function,
            "required": list(op.required),
            "optional": dict(op.optional),
            "mutates_project": op.mutates_project,
            "description": op.description,
            "location": "plugin" if plugin_function in plugin_by_function else "python",
            "plugin_function": plugin_function,
            "source": "tech_connector.services.unreal.unreal_operation_service.UNREAL_OPERATIONS",
            "implementation_state": "implemented",
        }

    capability_rows = {
        key: {
            "kind": "capability",
            "name": key,
            "domain": spec.domain,
            "phase": spec.phase,
            "mode": spec.mode,
            "function": spec.function,
            "operation": spec.operation,
            "aliases": list(spec.aliases),
            "enabled": spec.enabled,
            "location": "plugin" if _plugin_function_from_python_call(spec.function) in plugin_by_function else spec.mode,
            "source": "tech_connector.services.unreal.capability_registry.UNREAL_CAPABILITIES",
            "implementation_state": "implemented" if spec.enabled else "disabled",
        }
        for key, spec in UNREAL_CAPABILITIES.items()
    }

    retired_rows = {
        key: {
            "kind": "retired_operation",
            "name": key,
            "location": "needs_cpp_wrapper",
            "source": "tech_connector.services.unreal.unreal_operation_service.UNREAL_OPERATIONS_REQUIRING_IMPLEMENTATION_STRATEGY",
            "implementation_state": "requires_implementation_strategy",
        }
        for key in sorted(UNREAL_OPERATIONS_REQUIRING_IMPLEMENTATION_STRATEGY)
    }
    wrapper_rows: dict[str, dict[str, Any]] = {}
    for row in DOMAIN_WRAPPER_REQUIREMENTS:
        coverage = classify_domain_operation(row.operation, project_root)
        state = {
            "python_native": "implemented_python",
            "implement_python_first": "python_api_available_wrapper_stubbed",
            "cpp_preferred": "cpp_preferred_with_context_readback",
            "cpp_required": "requires_cpp_body",
        }.get(coverage["decision"], "requires_strategy")
        wrapper_rows[row.operation] = {
            "kind": "cpp_domain_wrapper_requirement",
            "name": row.operation,
            "domain": row.domain,
            "function": row.wrapper_function,
            "python_call": row.python_call,
            "location": "plugin_required",
            "source": "tech_connector.services.unreal.cpp_domain_wrapper_requirements_service.DOMAIN_WRAPPER_REQUIREMENTS",
            "implementation_state": state,
            "coverage_decision": coverage["decision"],
            "python_implementation": coverage["python_implementation"],
            "python_status": coverage["python_status"],
            "context_builder": coverage["context_builder"],
            "context_builder_exists": coverage["context_builder_exists"],
            "reflected_api_evidence": coverage["reflected_api_evidence"],
            "required_modules": list(row.required_modules),
            "minimum_contract": list(row.minimum_contract),
            "validation_fixture": row.validation_fixture,
        }

    alias_rows: dict[str, dict[str, Any]] = {}
    for function, row in plugin_by_function.items():
        for alias in row["aliases"]:
            alias_rows[alias] = {
                "kind": "plugin_alias",
                "name": alias,
                "function": row["python_call"],
                "plugin_function": function,
                "location": "plugin",
                "source": str(PLUGIN_MANIFEST_PATH),
                "implementation_state": row["implementation_state"],
                "operation": alias if alias in operation_rows else "",
                "capability": alias if alias in capability_rows else "",
            }

    callables, lookup, lookup_index, lookup_collisions = _build_unified_callable_lookup(
        operations=operation_rows,
        plugin_functions=plugin_by_function,
        capabilities=capability_rows,
        plugin_aliases=alias_rows,
        unreal_tools_functions=unreal_tools_rows,
        base_unreal_python_api=base_unreal_api_rows,
        retired_operations=retired_rows,
        cpp_domain_wrapper_requirements=wrapper_rows,
    )

    missing_from_manifest = sorted((header_functions | cpp_functions) - set(plugin_by_function))
    manifest_without_header = sorted(set(plugin_by_function) - header_functions)
    manifest_without_cpp = sorted(set(plugin_by_function) - cpp_functions)
    alias_without_entry = sorted(
        alias
        for alias in alias_rows
        if alias not in operation_rows and alias not in capability_rows
    )
    retired_without_wrapper_requirement = sorted(
        key
        for key in retired_rows
        if key not in wrapper_rows and not key.startswith("project.")
    )
    unreal_tools_placeholders = [
        {
            "function": key,
            "source": row.get("source"),
            "quality": dict(row.get("implementation_quality") or {}),
        }
        for key, row in unreal_tools_rows.items()
        if row.get("implementation_state") != "implemented"
    ]

    return {
        "ok": not missing_from_manifest
        and not manifest_without_header
        and not manifest_without_cpp
        and not alias_without_entry
        and not retired_without_wrapper_requirement
        and not unreal_tools_placeholders,
        "sources": {
            "plugin_manifest": str(PLUGIN_MANIFEST_PATH),
            "plugin_header": str(PLUGIN_HEADER_PATH),
            "plugin_cpp": str(PLUGIN_CPP_PATH),
            "plugin_implementation_files": [
                str(path) for path in _plugin_implementation_paths()
            ],
            "operations": "tech_connector.services.unreal.unreal_operation_service.UNREAL_OPERATIONS",
            "capabilities": "tech_connector.services.unreal.capability_registry.UNREAL_CAPABILITIES",
            "wrapper_requirements": "tech_connector.services.unreal.cpp_domain_wrapper_requirements_service.DOMAIN_WRAPPER_REQUIREMENTS",
        },
        "counts": {
            "plugin_functions": len(plugin_by_function),
            "operations": len(operation_rows),
            "capabilities": len(capability_rows),
            "unreal_tools_functions": len(unreal_tools_rows),
            "unreal_tools_placeholder_functions": len(unreal_tools_placeholders),
            "base_unreal_python_api": base_unreal_api_count,
            "base_unreal_python_api_materialized": len(base_unreal_api_rows),
            "plugin_aliases": len(alias_rows),
            "retired_operations": len(retired_rows),
            "cpp_domain_wrapper_requirements": len(wrapper_rows),
            "total_callable_surface": len(operation_rows)
            + len(plugin_by_function)
            + len(unreal_tools_rows)
            + base_unreal_api_count,
            "total_inventory_rows": len(callables),
            "lookup_keys": len(lookup),
            "ambiguous_lookup_keys": len(lookup_collisions),
        },
        "callables": callables,
        "lookup": lookup,
        "lookup_index": lookup_index,
        "lookup_collisions": lookup_collisions,
        "plugin_functions": plugin_by_function,
        "operations": operation_rows,
        "capabilities": capability_rows,
        "unreal_tools_functions": unreal_tools_rows,
        "base_unreal_python_api": base_unreal_api_rows,
        "plugin_aliases": alias_rows,
        "retired_operations": retired_rows,
        "cpp_domain_wrapper_requirements": wrapper_rows,
        "gaps": {
            "plugin_functions_missing_from_manifest": missing_from_manifest,
            "manifest_functions_missing_from_header": manifest_without_header,
            "manifest_functions_missing_cpp_body": manifest_without_cpp,
            "plugin_aliases_without_operation_or_capability": alias_without_entry,
            "retired_operations_without_cpp_requirement": retired_without_wrapper_requirement,
            "unreal_tools_placeholder_functions": unreal_tools_placeholders,
        },
    }


def resolve_unreal_inventory_item(name: str, project_root: str | None = None) -> dict[str, Any]:
    inventory = build_unreal_capability_inventory(project_root)
    query = str(name or "")
    canonical_key = (inventory.get("lookup") or {}).get(query)
    if canonical_key:
        item = (inventory.get("callables") or {}).get(canonical_key)
        if item:
            return {
                "ok": True,
                "section": item.get("inventory_section"),
                "canonical_key": canonical_key,
                "item": item,
                "inventory_ok": inventory["ok"],
                "ambiguous_alternates": (inventory.get("lookup_index") or {}).get(query, [])[1:],
            }
    base_api_item = _resolve_base_unreal_python_api_item(query, project_root)
    if base_api_item:
        return {
            "ok": True,
            "section": "base_unreal_python_api",
            "canonical_key": f"base_unreal_python_api.{query}",
            "item": base_api_item,
            "inventory_ok": inventory["ok"],
            "ambiguous_alternates": [],
        }
    lowered = query.lower()
    matches = []
    for key, row in (inventory.get("callables") or {}).items():
            haystack = json.dumps(row, default=str).lower()
            if lowered and lowered in haystack:
                matches.append({"section": row.get("inventory_section"), "key": key, "item": row})
    return {"ok": bool(matches), "query": query, "matches": matches[:25], "inventory_ok": inventory["ok"]}


def _build_unified_callable_lookup(
    **sections: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
    priorities = {
        "operations": 10,
        "plugin_aliases": 20,
        "plugin_functions": 30,
        "unreal_tools_functions": 40,
        "base_unreal_python_api": 50,
        "capabilities": 60,
        "cpp_domain_wrapper_requirements": 70,
        "retired_operations": 80,
    }
    callables: dict[str, dict[str, Any]] = {}
    lookup_candidates: dict[str, list[tuple[int, str]]] = {}

    def add_lookup(value: Any, priority: int, canonical_key: str) -> None:
        key = str(value or "").strip()
        if not key:
            return
        lookup_candidates.setdefault(key, []).append((priority, canonical_key))
        lowered = key.lower()
        if lowered != key:
            lookup_candidates.setdefault(lowered, []).append((priority + 1, canonical_key))

    def add_row(section: str, key: str, row: dict[str, Any]) -> None:
        priority = priorities.get(section, 100)
        canonical_key = f"{section}.{key}"
        item = dict(row)
        item["inventory_section"] = section
        item["canonical_key"] = canonical_key
        callables[canonical_key] = item
        add_lookup(key, 0, canonical_key)
        if item.get("name") != key:
            add_lookup(item.get("name"), priority, canonical_key)
        add_lookup(item.get("function"), priority + 1, canonical_key)
        add_lookup(item.get("python_call"), priority + 1, canonical_key)
        if item.get("python_call"):
            add_lookup(str(item["python_call"]).split("(", 1)[0], priority, canonical_key)
        if item.get("plugin_function"):
            add_lookup(item["plugin_function"], priority + 1, canonical_key)
        for alias in item.get("aliases") or []:
            add_lookup(alias, priority, canonical_key)

    for section, rows in sections.items():
        for key, row in (rows or {}).items():
            add_row(section, key, row)

    lookup_index: dict[str, list[str]] = {}
    lookup: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for key, candidates in lookup_candidates.items():
        ordered = []
        seen = set()
        for _, canonical_key in sorted(candidates, key=lambda pair: (pair[0], pair[1])):
            if canonical_key in seen:
                continue
            seen.add(canonical_key)
            ordered.append(canonical_key)
        lookup_index[key] = ordered
        if ordered:
            lookup[key] = ordered[0]
        if len(ordered) > 1:
            collisions[key] = ordered
    return callables, lookup, lookup_index, collisions


def _load_plugin_manifest() -> dict[str, Any]:
    return json.loads(PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8"))


def _parse_header_functions(path: Path) -> set[str]:
    return set(re.findall(
        r"static\s+FString\s+(\w+)\s*\(",
        path.read_text(encoding="utf-8", errors="replace"),
    ))


def _plugin_implementation_paths() -> tuple[Path, ...]:
    from tech_connector.services.unreal.plugin_source_service import plugin_implementation_paths

    return plugin_implementation_paths()


def _parse_cpp_functions(path: Path | None = None) -> set[str]:
    from tech_connector.services.unreal.plugin_source_service import read_plugin_implementation

    text = (
        path.read_text(encoding="utf-8", errors="replace")
        if path is not None
        else read_plugin_implementation()
    )
    return set(re.findall(
        r"FString\s+UAIStudioBridgeLibrary::(\w+)\s*\(",
        text,
    ))


def _discover_unreal_tools_functions() -> dict[str, dict[str, Any]]:
    from tech_connector.services.unreal.python_callable_quality_service import (
        inspect_python_function_quality,
    )

    root = ROOT / "unreal_tools"
    rows: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return rows
    for path in sorted(root.glob("*.py")):
        if (
            path.name.startswith("_")
            or path.name == "__init__.py"
            or path.stem.endswith(("_head", "_tail"))
        ):
            continue
        module = f"unreal_tools.{path.stem}"
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            qualified = f"{module}.{node.name}"
            args = [arg.arg for arg in node.args.args]
            quality = inspect_python_function_quality(source, node.name)
            rows[qualified] = {
                "kind": "unreal_tools_function",
                "name": qualified,
                "module": module,
                "function": qualified,
                "location": "unreal_tools",
                "source": str(path),
                "required": args,
                "implementation_state": quality["state"],
                "implementation_quality": quality,
                "docstring": ast.get_docstring(node) or "",
            }
    return rows


def _count_base_unreal_python_api(project_root: str | None = None) -> int:
    try:
        from tech_connector.bridges.unreal.unreal_intelligence import resolve_db_path
    except Exception:
        return 0
    db_path = resolve_db_path(project_root)
    if not db_path.is_file():
        return 0
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            return int(conn.execute("SELECT COUNT(*) FROM python_api WHERE dcc=?", ("Unreal",)).fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _load_base_unreal_python_api(project_root: str | None = None, *, limit: int = 0) -> dict[str, dict[str, Any]]:
    """Materialize a bounded preview of the reflected Unreal Python API.

    The full API can exceed hundreds of thousands of rows. The SQLite index is
    still part of the canonical inventory, but loading every row into normal
    planning payloads causes timeouts and enormous traces.
    """
    try:
        from tech_connector.bridges.unreal.unreal_intelligence import resolve_db_path
    except Exception:
        return {}
    db_path = resolve_db_path(project_root)
    if not db_path.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            if limit <= 0:
                return rows
            cursor = conn.execute(
                "SELECT qualified_name, object_type, signature, docstring, source, tags_json, metadata_json "
                "FROM python_api WHERE dcc=? ORDER BY qualified_name LIMIT ?",
                ("Unreal", int(limit)),
            )
            for row in cursor:
                qualified = str(row["qualified_name"] or "")
                if not qualified:
                    continue
                rows[qualified] = {
                    "kind": "base_unreal_python_api",
                    "name": qualified,
                    "function": qualified,
                    "object_type": row["object_type"],
                    "signature": row["signature"],
                    "docstring": row["docstring"],
                    "location": "base_unreal_api",
                    "source": row["source"],
                    "tags": _json_loads(row["tags_json"], []),
                    "metadata": _json_loads(row["metadata_json"], {}),
                    "implementation_state": "documented_or_reflected",
                }
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    return rows


def _resolve_base_unreal_python_api_item(name: str, project_root: str | None = None) -> dict[str, Any] | None:
    if not name:
        return None
    try:
        from tech_connector.bridges.unreal.unreal_intelligence import resolve_db_path
    except Exception:
        return None
    db_path = resolve_db_path(project_root)
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT qualified_name, object_type, signature, docstring, source, tags_json, metadata_json "
                "FROM python_api WHERE dcc=? AND qualified_name=? LIMIT 1",
                ("Unreal", name),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    qualified = str(row["qualified_name"] or "")
    return {
        "kind": "base_unreal_python_api",
        "name": qualified,
        "function": qualified,
        "object_type": row["object_type"],
        "signature": row["signature"],
        "docstring": row["docstring"],
        "location": "base_unreal_api",
        "source": row["source"],
        "tags": _json_loads(row["tags_json"], []),
        "metadata": _json_loads(row["metadata_json"], {}),
        "implementation_state": "documented_or_reflected",
    }


def _plugin_function_from_python_call(function: str) -> str:
    prefix = "unreal.AIStudioBridgeLibrary."
    if not str(function or "").startswith(prefix):
        return ""
    method = str(function)[len(prefix):]
    return "".join(part[:1].upper() + part[1:] for part in method.split("_") if part)


def _json_loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback
