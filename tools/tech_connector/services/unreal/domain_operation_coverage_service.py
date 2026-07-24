from __future__ import annotations

"""Coverage audit for domain operations that may need Python or C++ authoring.

This is the gate before adding AIStudioBridge bodies: if Unreal Python already
has a functional implementation, the planner should prefer it. If a Python
wrapper exists but only returns a ``requires_*`` status, this service records
the reflected API evidence needed to implement the Python path first.
"""

from pathlib import Path
from typing import Any
import ast
from functools import lru_cache
import sqlite3

from tech_connector.services.unreal.cpp_domain_wrapper_requirements_service import (
    DOMAIN_WRAPPER_REQUIREMENTS,
)


ROOT = Path(__file__).resolve().parents[3]


PYTHON_IMPLEMENTATIONS: dict[str, str] = {
    "niagara.create_emitter": "unreal_tools.niagara.create_emitter",
    "niagara.delete_emitter": "unreal_tools.niagara.delete_emitter",
    "niagara.list_module_inputs": "unreal_tools.niagara.list_module_inputs",
    "niagara.set_module_input": "unreal_tools.niagara.set_module_input",
    "niagara.set_renderer_property": "unreal_tools.niagara.set_renderer_property",
    "niagara.set_emitter_property": "unreal_tools.niagara.set_emitter_property",
    "niagara.set_user_parameter": "unreal_tools.niagara.set_user_parameter",
    "physics.set_profile_property": "unreal_tools.physics.set_profile_property",
    "retarget.create_ik_rig": "unreal_tools.retarget.create_ik_rig",
    "retarget.add_ik_chain": "unreal_tools.retarget.add_ik_chain",
    "retarget.create_ik_retargeter": "unreal_tools.retarget.create_ik_retargeter",
    "retarget.set_chain_mapping": "unreal_tools.retarget.set_chain_mapping",
    "retarget.set_profile_property": "unreal_tools.retarget.set_profile_property",
    "retarget.set_root_settings": "unreal_tools.retarget.set_root_settings",
    "motion_matching.create_database": "unreal_tools.motion_matching.create_pose_search_database",
    "motion_matching.create_schema": "unreal_tools.motion_matching.create_schema",
    "motion_matching.add_schema_channel": "unreal_tools.motion_matching.add_schema_channel",
    "motion_matching.add_animation": "unreal_tools.motion_matching.add_animation",
    "motion_matching.remove_animation": "unreal_tools.motion_matching.remove_animation",
    "motion_matching.set_database_property": "unreal_tools.motion_matching.set_database_property",
}


DOMAIN_CONTEXT_BUILDERS: dict[str, str] = {
    "niagara": "tech_connector.services.unreal.contexts.niagara_context.NiagaraContextBuilder",
    "pose_search": "tech_connector.services.unreal.contexts.motion_matching_context.MotionMatchingContextBuilder",
    "ik_retarget": "tech_connector.services.unreal.contexts.retarget_context.RetargetContextBuilder",
    "physics": "tech_connector.services.unreal.contexts.physics_context.PhysicsContextBuilder",
}


REFLECTED_API_SYMBOLS: dict[str, tuple[str, ...]] = {
    "niagara.create_emitter": ("unreal.NiagaraEmitterFactoryNew", "unreal.NiagaraSystemFactoryNew", "unreal.AssetToolsHelpers"),
    "niagara.delete_emitter": ("unreal.NiagaraSystem", "unreal.NiagaraEmitter"),
    "niagara.list_module_inputs": ("unreal.NiagaraParameterStore", "unreal.NiagaraScriptSourceBase", "unreal.NiagaraScript"),
    "niagara.set_module_input": ("unreal.NiagaraParameterStore", "unreal.NiagaraScriptSourceBase"),
    "niagara.set_renderer_property": ("unreal.NiagaraRendererProperties", "unreal.NiagaraSpriteRendererProperties", "unreal.NiagaraMeshRendererProperties"),
    "niagara.set_emitter_property": ("unreal.NiagaraEmitter", "unreal.NiagaraSystem"),
    "niagara.set_user_parameter": ("unreal.NiagaraParameterStore",),
    "physics.set_profile_property": ("unreal.PhysicsAsset", "unreal.ConstraintProfileProperties", "unreal.PhysicalAnimationProfile"),
    "retarget.create_ik_rig": ("unreal.IKRigDefinitionFactory", "unreal.IKRigController", "unreal.IKRigDefinition"),
    "retarget.add_ik_chain": ("unreal.IKRigController.add_retarget_chain", "unreal.IKRigController.get_retarget_chains"),
    "retarget.create_ik_retargeter": ("unreal.IKRetargetFactory", "unreal.IKRetargeterController", "unreal.IKRetargeter"),
    "retarget.set_chain_mapping": ("unreal.IKRetargeterController.auto_map_chains", "unreal.IKRetargeterController.get_source_chain"),
    "retarget.set_profile_property": ("unreal.IKRetargeterController",),
    "retarget.set_root_settings": ("unreal.IKRetargeterController",),
    "motion_matching.create_database": ("unreal.PoseSearchDatabaseFactory", "unreal.PoseSearchDatabase", "unreal.AssetToolsHelpers"),
    "motion_matching.create_schema": ("unreal.PoseSearchSchemaFactory", "unreal.PoseSearchSchema", "unreal.AssetToolsHelpers"),
    "motion_matching.add_schema_channel": ("unreal.PoseSearchFeatureChannel", "unreal.PoseSearchSchema"),
    "motion_matching.add_animation": ("unreal.PoseSearchDatabase", "unreal.PoseSearchDatabaseAnimationAssetBase"),
    "motion_matching.remove_animation": ("unreal.PoseSearchDatabase", "unreal.PoseSearchDatabaseAnimationAssetBase"),
    "motion_matching.set_database_property": ("unreal.PoseSearchDatabase", "unreal.PoseSearchSchema"),
}


def audit_domain_operation_coverage(project_root: str | None = None) -> dict[str, Any]:
    operations = sorted({*[item.operation for item in DOMAIN_WRAPPER_REQUIREMENTS], *PYTHON_IMPLEMENTATIONS})
    rows = [classify_domain_operation(operation, project_root) for operation in operations]
    return {
        "ok": all(row["decision"] != "unknown_gap" for row in rows),
        "counts": {
            "operations": len(rows),
            "python_functional": sum(1 for row in rows if row["python_status"] == "functional"),
            "python_stubbed": sum(1 for row in rows if row["python_status"] == "stubbed"),
            "python_missing": sum(1 for row in rows if row["python_status"] == "missing"),
            "implement_python_first": sum(1 for row in rows if row["decision"] == "implement_python_first"),
            "cpp_required": sum(1 for row in rows if row["decision"] == "cpp_required"),
            "cpp_preferred": sum(1 for row in rows if row["decision"] == "cpp_preferred"),
        },
        "coverage": rows,
    }


def classify_domain_operation(operation: str, project_root: str | None = None) -> dict[str, Any]:
    requirement = next((item for item in DOMAIN_WRAPPER_REQUIREMENTS if item.operation == operation), None)
    domain = requirement.domain if requirement else operation.split(".", 1)[0]
    python_impl = PYTHON_IMPLEMENTATIONS.get(operation, "")
    wrapper = _inspect_python_function(python_impl)
    api_evidence = _reflected_api_evidence(operation, project_root)
    context_builder = DOMAIN_CONTEXT_BUILDERS.get(domain, "")
    has_context = _context_builder_exists(context_builder)

    if wrapper["status"] == "functional":
        decision = "python_native"
    elif api_evidence:
        decision = "implement_python_first"
    elif has_context:
        decision = "cpp_preferred"
    else:
        decision = "cpp_required"

    return {
        "operation": operation,
        "domain": domain,
        "python_implementation": python_impl,
        "python_status": wrapper["status"],
        "python_reason": wrapper["reason"],
        "context_builder": context_builder,
        "context_builder_exists": has_context,
        "reflected_api_evidence": api_evidence,
        "cpp_wrapper_function": requirement.wrapper_function if requirement else "",
        "cpp_python_call": requirement.python_call if requirement else "",
        "decision": decision,
    }


def _inspect_python_function(qualified_name: str) -> dict[str, str]:
    if not qualified_name:
        return {"status": "missing", "reason": "no python implementation registered"}
    module_name, function_name = qualified_name.rsplit(".", 1)
    path = ROOT / (module_name.replace(".", "/") + ".py")
    if not path.is_file():
        return {"status": "missing", "reason": f"module not found: {path}"}
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"status": "missing", "reason": f"syntax error: {exc}"}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            body = ast.get_source_segment(source, node) or ""
            if "ok=False" in body and "requires_" in body:
                return {"status": "stubbed", "reason": "function exists but returns a requires_* status"}
            if "import unreal" in body or "unreal." in body:
                return {"status": "functional", "reason": "function body calls Unreal Python APIs"}
            return {"status": "unknown", "reason": "function exists but Unreal mutation path is not obvious"}
    return {"status": "missing", "reason": f"function not found: {qualified_name}"}


def _context_builder_exists(qualified_name: str) -> bool:
    if not qualified_name:
        return False
    module_name, class_name = qualified_name.rsplit(".", 1)
    path = ROOT / (module_name.replace(".", "/") + ".py")
    if not path.is_file():
        return False
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    return any(isinstance(node, ast.ClassDef) and node.name == class_name for node in tree.body)


def _reflected_api_evidence(operation: str, project_root: str | None = None) -> list[dict[str, str]]:
    symbols = REFLECTED_API_SYMBOLS.get(operation) or ()
    if not symbols:
        return []
    rows = _load_reflected_api_symbol_rows(project_root)
    return [rows[symbol] for symbol in symbols if symbol in rows]


@lru_cache(maxsize=8)
def _load_reflected_api_symbol_rows(project_root: str | None = None) -> dict[str, dict[str, str]]:
    symbols = sorted({symbol for values in REFLECTED_API_SYMBOLS.values() for symbol in values})
    if not symbols:
        return {}
    try:
        from tech_connector.bridges.unreal.unreal_intelligence import resolve_db_path
    except Exception:
        return {}
    db_path = resolve_db_path(project_root)
    if not db_path.is_file():
        return {}
    rows: dict[str, dict[str, str]] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" for _ in symbols)
            cursor = conn.execute(
                "SELECT qualified_name, object_type, signature FROM python_api "
                f"WHERE dcc=? AND qualified_name IN ({placeholders})",
                ("Unreal", *symbols),
            )
            for row in cursor:
                symbol = str(row["qualified_name"] or "")
                rows[symbol] = {
                    "symbol": symbol,
                    "qualified_name": symbol,
                    "object_type": str(row["object_type"] or ""),
                    "signature": str(row["signature"] or ""),
                }
        finally:
            conn.close()
    except sqlite3.Error:
        return rows
    return rows
