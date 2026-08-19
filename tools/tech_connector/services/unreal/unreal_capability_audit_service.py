from __future__ import annotations

"""Audit Unreal capability catalogs against the AIStudioBridge plugin surface."""

from pathlib import Path
from typing import Any
import json
import re


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "AIStudioBridge"
MANIFEST_PATH = PLUGIN_ROOT / "AIStudioBridgeCapabilities.json"
HEADER_PATH = PLUGIN_ROOT / "Source" / "AIStudioBridge" / "Public" / "AIStudioBridgeLibrary.h"
CPP_PATH = PLUGIN_ROOT / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp"


def audit_unreal_capability_catalogs() -> dict[str, Any]:
    manifest = _load_manifest()
    header_functions = _parse_header_functions(HEADER_PATH)
    cpp_bodies = _parse_cpp_bodies()

    from tech_connector.services.unreal.capability_registry import UNREAL_CAPABILITIES
    from tech_connector.services.unreal.cpp_domain_wrapper_requirements_service import (
        audit_cpp_domain_wrapper_requirements,
    )
    from tech_connector.services.unreal.domain_operation_coverage_service import (
        audit_domain_operation_coverage,
    )
    from tech_connector.services.unreal.unreal_capability_inventory_service import (
        build_unreal_capability_inventory,
    )
    from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS

    capability_names = set(UNREAL_CAPABILITIES)
    capability_aliases = {
        alias
        for spec in UNREAL_CAPABILITIES.values()
        for alias in (spec.aliases or ())
    }
    operation_names = set(UNREAL_OPERATIONS)

    plugin_rows: list[dict[str, Any]] = []
    manifest_function_names: set[str] = set()
    manifest_aliases: set[str] = set()
    for item in manifest.get("capabilities") or []:
        function = str(item.get("function") or "")
        name = str(item.get("name") or "")
        aliases = [str(alias) for alias in item.get("operation_aliases") or []]
        manifest_function_names.add(function)
        manifest_aliases.update(aliases)
        body = cpp_bodies.get(function, {})
        status = "missing_cpp_body"
        if body:
            status = "cpp_body_required" if body.get("cpp_body_required") else "implemented"
        plugin_rows.append(
            {
                "name": name,
                "function": function,
                "python_call": item.get("python_call") or "",
                "aliases": aliases,
                "in_header": function in header_functions,
                "in_cpp": function in cpp_bodies,
                "cpp_status": status,
                "safety": _cpp_body_safety(function, body.get("body", "")),
                "alias_coverage": [
                    {
                        "alias": alias,
                        "in_operations": alias in operation_names,
                        "in_capability_registry": alias in capability_names or alias in capability_aliases,
                    }
                    for alias in aliases
                ],
            }
        )

    plugin_function_by_python = {
        f"unreal.AIStudioBridgeLibrary.{_python_method_name(function)}": row
        for row in plugin_rows
        for function in [row["function"]]
    }
    registry_rows: list[dict[str, Any]] = []
    enabled_stubbed_capabilities: list[dict[str, Any]] = []
    enabled_missing_operation_capabilities: list[dict[str, Any]] = []
    for name, spec in sorted(UNREAL_CAPABILITIES.items()):
        row = {
            "name": name,
            "mode": spec.mode,
            "operation": spec.operation,
            "function": spec.function,
            "enabled": spec.enabled,
            "aliases": list(spec.aliases or ()),
            "plugin_status": "",
        }
        plugin_row = plugin_function_by_python.get(spec.function)
        if plugin_row:
            row["plugin_status"] = plugin_row["cpp_status"]
            if spec.enabled and plugin_row["cpp_status"] == "cpp_body_required":
                enabled_stubbed_capabilities.append(row)
        if spec.enabled and spec.mode == "operation" and spec.operation not in operation_names:
            enabled_missing_operation_capabilities.append(row)
        registry_rows.append(row)

    manifest_alias_gaps = [
        coverage
        for row in plugin_rows
        for coverage in row["alias_coverage"]
        if not coverage["in_operations"] and not coverage["in_capability_registry"]
    ]
    operation_callable_chains = _operation_callable_chains(
        UNREAL_OPERATIONS,
        plugin_function_by_python,
    )
    operation_backing_gaps = [
        {
            "operation": row["operation"],
            "function": row["function"],
            "reason": row["failure"],
        }
        for row in operation_callable_chains
        if not row["execution_chain_complete"]
    ]
    manifest_function_gaps = [
        row
        for row in plugin_rows
        if not row["in_header"] or not row["in_cpp"]
    ]
    plugin_body_gaps = [
        row
        for row in plugin_rows
        if row["cpp_status"] in {"missing_cpp_body", "cpp_body_required"}
    ]
    plugin_safety_gaps = [
        {"name": row["name"], "function": row["function"], "failures": row["safety"]["failures"]}
        for row in plugin_rows
        if row["safety"]["failures"]
    ]
    domain_wrapper_requirements = audit_cpp_domain_wrapper_requirements(operation_names)
    domain_operation_coverage = audit_domain_operation_coverage()
    canonical_inventory = build_unreal_capability_inventory()

    return {
        "ok": not manifest_function_gaps
        and not manifest_alias_gaps
        and not enabled_stubbed_capabilities
        and not enabled_missing_operation_capabilities
        and not plugin_safety_gaps
        and not operation_backing_gaps
        and canonical_inventory["ok"],
        "sources": {
            "plugin_manifest": str(MANIFEST_PATH),
            "plugin_header": str(HEADER_PATH),
            "plugin_cpp": str(CPP_PATH),
            "plugin_implementation_files": [
                str(path) for path in _plugin_implementation_paths()
            ],
            "operation_registry": "tech_connector.services.unreal.unreal_operation_service.UNREAL_OPERATIONS",
            "capability_registry": "tech_connector.services.unreal.capability_registry.UNREAL_CAPABILITIES",
        },
        "counts": {
            "plugin_manifest_capabilities": len(plugin_rows),
            "header_functions": len(header_functions),
            "cpp_functions": len(cpp_bodies),
            "operation_registry": len(operation_names),
            "capability_registry": len(capability_names),
            "plugin_body_gaps": len(plugin_body_gaps),
            "plugin_safety_gaps": len(plugin_safety_gaps),
            "manifest_function_gaps": len(manifest_function_gaps),
            "manifest_alias_gaps": len(manifest_alias_gaps),
            "enabled_stubbed_capabilities": len(enabled_stubbed_capabilities),
            "enabled_missing_operation_capabilities": len(enabled_missing_operation_capabilities),
            "operation_backing_gaps": len(operation_backing_gaps),
            "cpp_domain_wrapper_requirements": domain_wrapper_requirements["requirement_count"],
            "domain_ops_python_functional": domain_operation_coverage["counts"]["python_functional"],
            "domain_ops_python_stubbed": domain_operation_coverage["counts"]["python_stubbed"],
            "domain_ops_implement_python_first": domain_operation_coverage["counts"]["implement_python_first"],
            "domain_ops_cpp_required": domain_operation_coverage["counts"]["cpp_required"],
            "canonical_inventory_plugin_functions": canonical_inventory["counts"]["plugin_functions"],
            "canonical_inventory_operations": canonical_inventory["counts"]["operations"],
            "canonical_inventory_unreal_tools_functions": canonical_inventory["counts"]["unreal_tools_functions"],
            "canonical_inventory_unreal_tools_placeholder_functions": canonical_inventory["counts"]["unreal_tools_placeholder_functions"],
            "canonical_inventory_base_unreal_python_api": canonical_inventory["counts"]["base_unreal_python_api"],
            "canonical_inventory_total_callable_surface": canonical_inventory["counts"]["total_callable_surface"],
            "canonical_inventory_total_inventory_rows": canonical_inventory["counts"]["total_inventory_rows"],
            "canonical_inventory_lookup_keys": canonical_inventory["counts"]["lookup_keys"],
        },
        "plugin_capabilities": plugin_rows,
        "registry_capabilities": registry_rows,
        "plugin_body_gaps": plugin_body_gaps,
        "plugin_safety_gaps": plugin_safety_gaps,
        "manifest_function_gaps": manifest_function_gaps,
        "manifest_alias_gaps": manifest_alias_gaps,
        "enabled_stubbed_capabilities": enabled_stubbed_capabilities,
        "enabled_missing_operation_capabilities": enabled_missing_operation_capabilities,
        "operation_backing_gaps": operation_backing_gaps,
        "operation_callable_chains": operation_callable_chains,
        "cpp_domain_wrapper_requirements": domain_wrapper_requirements,
        "domain_operation_coverage": domain_operation_coverage,
        "canonical_inventory": canonical_inventory,
    }


def format_unreal_capability_audit_report(audit: dict[str, Any]) -> str:
    counts = audit.get("counts") or {}
    lines = [
        "Unreal capability audit",
        f"ok: {audit.get('ok')}",
        "counts: "
        + ", ".join(f"{key}={value}" for key, value in counts.items()),
    ]
    body_gaps = audit.get("plugin_body_gaps") or []
    if body_gaps:
        lines.append("plugin body gaps:")
        for row in body_gaps:
            lines.append(
                f"- {row.get('name')} -> {row.get('function')} ({row.get('cpp_status')})"
            )
    alias_gaps = audit.get("manifest_alias_gaps") or []
    safety_gaps = audit.get("plugin_safety_gaps") or []
    if safety_gaps:
        lines.append("plugin safety gaps:")
        for row in safety_gaps:
            lines.append(f"- {row.get('name')} -> {row.get('function')}: {', '.join(row.get('failures') or [])}")
    if alias_gaps:
        lines.append("alias gaps:")
        for row in alias_gaps:
            lines.append(f"- {row.get('alias')}")
    enabled_stubbed = audit.get("enabled_stubbed_capabilities") or []
    if enabled_stubbed:
        lines.append("enabled capabilities backed by stubbed C++:")
        for row in enabled_stubbed:
            lines.append(f"- {row.get('name')} -> {row.get('function')}")
    operation_gaps = audit.get("operation_backing_gaps") or []
    domain_requirements = audit.get("cpp_domain_wrapper_requirements") or {}
    domain_coverage = audit.get("domain_operation_coverage") or {}
    inventory = audit.get("canonical_inventory") or {}
    missing_operation_caps = audit.get("enabled_missing_operation_capabilities") or []
    if missing_operation_caps:
        lines.append("enabled capabilities pointing at missing operations:")
        for row in missing_operation_caps[:25]:
            lines.append(f"- {row.get('name')} -> {row.get('operation')}")
        if len(missing_operation_caps) > 25:
            lines.append(f"- ... {len(missing_operation_caps) - 25} more")
    if operation_gaps:
        lines.append("operation backing gaps:")
        for row in operation_gaps[:25]:
            lines.append(f"- {row.get('operation')} -> {row.get('function')} ({row.get('reason')})")
        if len(operation_gaps) > 25:
            lines.append(f"- ... {len(operation_gaps) - 25} more")
    requirements = domain_requirements.get("requirements") or []
    if requirements:
        lines.append("domain C++ wrapper requirements:")
        for row in requirements[:25]:
            lines.append(f"- {row.get('operation')} -> {row.get('wrapper_function')} [{row.get('domain')}]")
    coverage = domain_coverage.get("coverage") or []
    if coverage:
        lines.append("domain Python/C++ coverage:")
        for row in coverage[:25]:
            lines.append(
                "- "
                + f"{row.get('operation')}: {row.get('decision')} "
                + f"(python={row.get('python_status')}, "
                + f"context={row.get('context_builder_exists')}, "
                + f"api_evidence={len(row.get('reflected_api_evidence') or [])})"
            )
    inventory_gaps = inventory.get("gaps") or {}
    for key, values in inventory_gaps.items():
        if values:
            lines.append(f"{key}:")
            for value in values[:25]:
                lines.append(f"- {value}")
    return "\n".join(lines)


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _parse_header_functions(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"static\s+FString\s+(\w+)\s*\(", text))


def _plugin_implementation_paths() -> tuple[Path, ...]:
    from tech_connector.services.unreal.plugin_source_service import plugin_implementation_paths

    return plugin_implementation_paths()


def _parse_cpp_bodies(path: Path | None = None) -> dict[str, dict[str, Any]]:
    from tech_connector.services.unreal.plugin_source_service import read_plugin_implementation

    text = (
        path.read_text(encoding="utf-8", errors="replace")
        if path is not None
        else read_plugin_implementation()
    )
    matches = list(re.finditer(r"FString\s+UAIStudioBridgeLibrary::(\w+)\s*\(", text))
    bodies: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        bodies[match.group(1)] = {
            "cpp_body_required": "cpp_body_required" in body,
            "sets_ok_true": "SetBoolField(TEXT(\"ok\"), true)" in body,
            "body_chars": len(body),
            "body": body,
        }
    return bodies


def _cpp_body_safety(function_name: str, body: str) -> dict[str, Any]:
    failures: list[str] = []
    if not body:
        return {"ok": False, "failures": ["missing_body"]}
    if "Root->SetBoolField(TEXT(\"ok\"), false)" not in body:
        failures.append("does_not_initialize_ok_false")
    if "TEXT(\"python_call\")" not in body:
        failures.append("does_not_report_python_call")
    editor_only = function_name != "InspectAnimationSequence"
    if editor_only and "#if WITH_EDITOR" not in body:
        failures.append("missing_with_editor_guard")
    mutating_functions = {
        "AddAnimGraphState",
        "AddAnimGraphTransitionRule",
        "DeleteAnimGraphState",
        "DeleteAnimGraphTransition",
        "RenameAnimGraphState",
        "SetAnimGraphTransitionRule",
        "SynthesizeAnimGraphTransitionRuleExpression",
        "WireAnimGraphOutputPose",
    }
    reflected_asset_mutating_functions = {
        "CreateKnownAssetByClassPath",
        "SetReflectedAssetProperty",
        "AddObjectReferenceToReflectedArray",
        "RemoveObjectReferenceFromReflectedArray",
    }
    if function_name in mutating_functions:
        if "FScopedTransaction" not in body:
            failures.append("missing_scoped_transaction")
        if "AnimBlueprint->Modify()" not in body:
            failures.append("missing_blueprint_modify")
        if "FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified" not in body:
            failures.append("missing_structural_modified_mark")
    if function_name in reflected_asset_mutating_functions:
        if "FScopedTransaction" not in body:
            failures.append("missing_scoped_transaction")
        if "->Modify()" not in body:
            failures.append("missing_asset_modify")
        if "AIStudioSaveAssetPackage" not in body:
            failures.append("missing_asset_save")
        if function_name == "SetReflectedAssetProperty" and "TEXT(\"readback\")" not in body:
            failures.append("missing_property_readback")
    if function_name == "CompileAndSaveAnimBlueprint":
        if "Root->SetBoolField(TEXT(\"ok\"), bSaved)" not in body:
            failures.append("compile_save_ok_not_bound_to_saved")
        if "TEXT(\"save_failed\")" not in body:
            failures.append("compile_save_missing_save_failed_status")
    if "cpp_body_required" in body:
        failures.append("contains_cpp_body_required")
    if "implementation_hint" in body:
        failures.append("contains_implementation_hint")
    return {"ok": not failures, "failures": failures}


def _python_method_name(function_name: str) -> str:
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", function_name or "").lower()
    return text


def _operation_callable_chains(
    operations: dict[str, Any],
    plugin_function_by_python: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, operation in sorted(operations.items()):
        function = str(operation.function or "")
        row = {
            "operation": key,
            "function": function,
            "registry_mapping": bool(function),
            "implementation_layer": "",
            "implementation_source": "",
            "reflected_cpp_body": "not_required",
            "python_callable": False,
            "execution_chain_complete": False,
            "failure": "",
        }
        if str(getattr(operation, "execution_mode", "")) == "user_delegated":
            delegation = dict(getattr(operation, "delegation", None) or {})
            row.update({
                "implementation_layer": "user_delegated",
                "implementation_source": str(delegation.get("surface") or "Unreal Editor"),
                "execution_chain_complete": bool(
                    delegation.get("surface")
                    and delegation.get("action")
                    and delegation.get("verification")
                ),
                "failure": "" if delegation else "delegation_contract_missing",
            })
            rows.append(row)
            continue
        if not function:
            row["failure"] = "empty_function"
            rows.append(row)
            continue
        if function.startswith("ai_studio.synthetic."):
            row.update({
                "implementation_layer": "synthetic_dispatch",
                "implementation_source": "prompt_dispatch_service",
                "execution_chain_complete": True,
            })
            rows.append(row)
            continue
        if function.startswith("unreal.AIStudioBridgeLibrary."):
            row["implementation_layer"] = "reflected_cpp_bridge"
            plugin_row = plugin_function_by_python.get(function)
            if not plugin_row:
                row["failure"] = "plugin_function_not_manifested"
            elif plugin_row.get("cpp_status") == "cpp_body_required":
                row["failure"] = "plugin_cpp_body_required"
                row["implementation_source"] = str(CPP_PATH)
                row["reflected_cpp_body"] = "stubbed"
            else:
                row["implementation_source"] = str(CPP_PATH)
                row["reflected_cpp_body"] = "implemented"
                row["python_callable"] = True
                row["execution_chain_complete"] = True
            rows.append(row)
            continue
        if not function.startswith(("tech_connector.", "unreal_tools.", "utilities.")):
            row["failure"] = "unknown_function_namespace"
            rows.append(row)
            continue
        row["implementation_layer"] = "python"
        module_name, _, attr = function.rpartition(".")
        module_path = ROOT / Path(*module_name.split(".")).with_suffix(".py")
        row["implementation_source"] = str(module_path)
        if not module_path.is_file():
            row["failure"] = "module_file_missing"
            rows.append(row)
            continue
        source = module_path.read_text(encoding="utf-8", errors="replace")
        if not re.search(rf"^\s*def\s+{re.escape(attr)}\s*\(", source, re.M):
            row["failure"] = "function_def_missing"
            rows.append(row)
            continue
        from tech_connector.services.unreal.python_callable_quality_service import (
            inspect_python_function_quality,
        )

        quality = inspect_python_function_quality(source, attr)
        row["implementation_quality"] = quality
        if not quality["implemented"]:
            row["failure"] = "python_placeholder_body"
            rows.append(row)
            continue
        row["python_callable"] = True
        row["execution_chain_complete"] = True
        rows.append(row)
    return rows
