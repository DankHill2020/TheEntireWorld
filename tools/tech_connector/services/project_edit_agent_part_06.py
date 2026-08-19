"""Shared imports and constants for project edit agent implementation."""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import time
import textwrap
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


PROJECT_EDIT_CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "modify",
                            "replace_symbol",
                            "insert_before_symbol",
                            "insert_after_symbol",
                            "replace_text",
                            "insert_before_text",
                            "insert_after_text",
                            "ensure_import",
                        ],
                    },
                    "path": {"type": "string"},
                    "target_symbol": {"type": "string"},
                    "original_content": {"type": "string"},
                    "new_content": {"type": "string"},
                },
                "required": ["action", "path", "target_symbol", "original_content", "new_content"],
                "additionalProperties": False,
            },
        },
        "report": {
            "type": "object",
            "properties": {
                "changed": {"type": "array", "items": {"type": "string"}},
                "reused": {"type": "array", "items": {"type": "string"}},
                "verification": {"type": "array", "items": {"type": "string"}},
                "remaining_gaps": {"type": "array", "items": {"type": "string"}},
                "requirement_coverage": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "requirement": {"type": "string"},
                            "production_owners": {"type": "array", "items": {"type": "string"}},
                            "test_owners": {"type": "array", "items": {"type": "string"}},
                            "validation": {"type": "array", "items": {"type": "string"}},
                            "status": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "requirement",
                            "production_owners",
                            "test_owners",
                            "validation",
                            "status",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "changed",
                "reused",
                "verification",
                "remaining_gaps",
                "requirement_coverage",
            ],
            "additionalProperties": False,
        },
        "blocked_reason": {"type": "string"},
    },
    "required": ["changes", "report", "blocked_reason"],
    "additionalProperties": False,
}

PROJECT_EDIT_SYNTAX_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"corrected_source": {"type": "string"}},
    "required": ["corrected_source"],
    "additionalProperties": False,
}

PROJECT_EDIT_FUNCTION_REPAIR_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "algorithm_steps": {"type": "array", "items": {"type": "string"}},
        "preserve": {"type": "array", "items": {"type": "string"}},
        "postconditions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["root_cause", "algorithm_steps", "preserve", "postconditions"],
    "additionalProperties": False,
}

PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": {
            "type": "object",
            "properties": {
                "canonical_owners": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
                "signatures": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "shared_invariants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "data_layout": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "errors": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
            },
            "required": [
                "canonical_owners",
                "signatures",
                "shared_invariants",
                "data_layout",
                "errors",
            ],
            "additionalProperties": False,
            "description": (
                "Concrete package-wide API/data contracts: canonical owners, exact signatures "
                "and defaults, shared layouts/constants, bounds, and errors."
            ),
        },
        "files": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "contracts": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "algorithm_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "validation_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "contracts",
                    "algorithm_steps",
                    "validation_steps",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["integration_contracts", "files"],
    "additionalProperties": False,
}

PROJECT_EDIT_INTEGRATION_CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA[
            "properties"
        ]["integration_contracts"],
    },
    "required": ["integration_contracts"],
    "additionalProperties": False,
}

PROJECT_EDIT_FILE_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "minItems": 2,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}

from tech_connector.services.project_edit_agent_part_01 import (
    ProjectEditApplyResult,
    ProjectEditLeafWorkUnits,
    ProjectEditPlan,
    ProjectEditPromptStage,
    _build_project_edit_intelligence_packet,
    _fallback_project_edit_discovery,
    _generated_artifact_project_discovery,
    _lightweight_project_edit_intelligence_packet,
    _project_edit_needs_deep_intelligence,
    _render_project_edit_intelligence_packet,
    build_code_agent_adaptive_plan,
    render_code_agent_adaptive_plan,
    render_code_agent_expert_context,
)

from tech_connector.services.project_edit_agent_part_02 import (
    _HOST_RUNTIME_MODULES,
    _PLACEHOLDER_PUBLIC_NAMES,
    _compact_indexed_import_context,
    _edit_error_for_forbidden_path,
    _expected_widget_accessor,
    _has_factory_argument_call,
    _has_main_window_entrypoint,
    _has_optional_import_guard,
    _has_widget_class_surface,
    _imported_modules,
    _imported_name_bindings,
    _infer_explicit_runtime_api_requests,
    _infer_prompt_requirements,
    _infer_signal_handler_requirements,
    _infer_ui_widget_requirements,
    _is_forbidden_edit_path,
    _is_placeholder_callable,
    _is_placeholder_class,
    _iter_signal_connects,
    _method_updates_widget,
    _method_uses_widget_access,
    _progress_callback_contract_issues,
    _project_edit_requests_new_artifact_plan,
    _project_edit_requires_patch,
    _qt_widget_import_coverage,
    _runtime_api_calls_in_tree,
    _runtime_api_paths_in_tree,
    _unresolved_module_scope_names,
    _widget_ctor_base_name,
    _widget_ctor_is_imported,
    _widget_expected_constructors,
    format_project_edit_generated_python,
)

from tech_connector.services.project_edit_agent_part_03 import (
    _RUNTIME_API_VALIDATION_CACHE,
    _callable_definition_map,
    _dynamic_host_api_member_issues,
    _generated_docstring_contract_issues,
    _generated_source_presentation_issues,
    _host_result_and_redundant_guard_issues,
    _import_specs,
    _imported_call_api_contracts,
    _incomplete_generated_type_hints,
    _invalid_runtime_api_contracts,
    _missing_explicit_bool_rejections,
    _official_unreal_call_signature_issues,
    _official_unreal_editor_property_issues,
    _prime_runtime_api_validation_cache,
    _public_definition_map,
    _qt_progress_surface_issues,
    _quality_result,
    _requested_identifier_contracts,
    _requested_pre_side_effect_contract_issues,
    _resolved_runtime_chain_exists,
    _sanitize_python_candidate_text,
    _tree_uses_identifier,
    _unresolved_generated_names,
    _unresolved_generated_names_by_callable,
)

from tech_connector.services.project_edit_agent_part_04 import (
    _is_test_path,
    _resolve_import_spec,
)

from tech_connector.services.project_edit_agent_part_05 import (
    _build_explicit_active_edit_discovery,
    _is_self_import,
    _leaf_ranking_terms,
    _objective_requires_validation_result_collection,
    _requested_public_symbol_names,
    _requires_behavior_test,
    _resolve_model_changes,
    _validate_candidate_changes_in_disposable_workspace,
    ensure_project_edit_requested_docstrings,
)


def _validate_candidate_changes(
    changes: list[dict[str, Any]],
    *,
    project_root: str | None,
    request_prompt: str,
    allowed_external_paths: set[str] | None = None,
    behavioral_proof_deferred: bool = False,
) -> list[dict[str, Any]]:
    """Validate generated Python in memory before a diff can be approved."""

    validation_started = time.perf_counter()
    _RUNTIME_API_VALIDATION_CACHE.clear()
    disposable_elapsed_ms = 0.0
    results: list[dict[str, Any]] = []
    inferred_requirements = _infer_prompt_requirements(request_prompt)
    inferred_widget_requirements = _infer_ui_widget_requirements(request_prompt)
    disposable_external_paths = {
        str(Path(path).resolve()).casefold()
        for path in (allowed_external_paths or set())
    }
    candidate_sources = {
        str(Path(str(item.get("path") or "")).resolve()): str(item.get("after") or "")
        for item in changes
        if str(item.get("path") or "")
    }
    final_candidate_path = next(
        reversed(candidate_sources),
        "",
    )
    candidate_module_trees: dict[str, ast.Module] = {}
    root_path = Path(project_root).resolve() if project_root else None
    for path_text, source in candidate_sources.items():
        candidate_path = Path(path_text)
        if candidate_path.suffix.lower() != ".py" or root_path is None:
            continue
        try:
            relative = candidate_path.relative_to(root_path).with_suffix("")
            module_parts = list(relative.parts)
            if module_parts and module_parts[-1] == "__init__":
                module_parts.pop()
            module_name = ".".join(module_parts)
            if module_name:
                candidate_module_trees[module_name] = ast.parse(
                    source,
                    filename=path_text,
                )
        except (SyntaxError, ValueError):
            continue
    package_generated_runtime_apis: set[str] = set()
    for path_text, source in candidate_sources.items():
        if _is_test_path(Path(path_text)):
            continue
        try:
            package_generated_runtime_apis.update(
                _runtime_api_calls_in_tree(ast.parse(source, filename=path_text))
            )
        except SyntaxError:
            continue
    _prime_runtime_api_validation_cache(
        {
            *_infer_explicit_runtime_api_requests(request_prompt),
            *package_generated_runtime_apis,
            *(
                path
                for tree in candidate_module_trees.values()
                for path in _runtime_api_paths_in_tree(tree)
            ),
        },
        project_root,
    )

    def patch_target_exists(
        target: str,
        seen: set[str] | None = None,
    ) -> bool:
        target = str(target or "").strip()
        if not target or "." not in target:
            return False
        seen = set(seen or ())
        if target in seen:
            return False
        seen.add(target)
        candidate_module = next(
            (
                module_name
                for module_name in sorted(
                    candidate_module_trees,
                    key=len,
                    reverse=True,
                )
                if target.startswith(module_name + ".")
            ),
            "",
        )
        if candidate_module:
            tree = candidate_module_trees[candidate_module]
            remaining = target[len(candidate_module) + 1 :].split(".")
            top_level = {
                node.name: node
                for node in tree.body
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            imported_bindings: dict[str, str] = {}
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_bindings[alias.asname or alias.name.split(".")[0]] = (
                            alias.name
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        imported_bindings[alias.asname or alias.name] = (
                            f"{node.module}.{alias.name}"
                        )
            first = remaining.pop(0)
            current_node = top_level.get(first)
            if current_node is not None:
                for attribute in remaining:
                    if not isinstance(current_node, ast.ClassDef):
                        return False
                    current_node = next(
                        (
                            child
                            for child in current_node.body
                            if isinstance(
                                child,
                                (
                                    ast.ClassDef,
                                    ast.FunctionDef,
                                    ast.AsyncFunctionDef,
                                ),
                            )
                            and child.name == attribute
                        ),
                        None,
                    )
                    if current_node is None:
                        return False
                return True
            imported_path = imported_bindings.get(first)
            if not imported_path:
                return False
            if not remaining:
                return True
            runtime_parts = imported_path.split(".") + remaining
            forwarded_target = ".".join(runtime_parts)
            if any(
                forwarded_target == module_name
                or forwarded_target.startswith(module_name + ".")
                for module_name in candidate_module_trees
            ):
                return patch_target_exists(forwarded_target, seen)
        else:
            runtime_parts = target.split(".")

        if any(
            ast.unparse(call.func) == target
            for tree in candidate_module_trees.values()
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
        ):
            return True
        if runtime_parts and runtime_parts[0] in _HOST_RUNTIME_MODULES:
            if ".".join(runtime_parts) in package_generated_runtime_apis:
                return True
            runtime_resolution = _resolved_runtime_chain_exists(
                ".".join(runtime_parts),
                project_root=project_root,
            )
            if runtime_resolution is not None:
                return runtime_resolution

        runtime_object: Any = None
        consumed = 0
        for index in range(len(runtime_parts), 0, -1):
            module_name = ".".join(runtime_parts[:index])
            try:
                runtime_object = importlib.import_module(module_name)
            except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
                continue
            consumed = index
            break
        if runtime_object is None:
            return False
        for attribute in runtime_parts[consumed:]:
            if not hasattr(runtime_object, attribute):
                return False
            runtime_object = getattr(runtime_object, attribute)
        return True

    standalone_entrypoint_symbols = list(dict.fromkeys(
        re.findall(
            r"__main__[^\n.;]*?\b(?:runs?|calls?|invokes?)\s+"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            request_prompt,
            flags=re.IGNORECASE,
        )
    ))
    requested_symbols = _requested_public_symbol_names(request_prompt)
    requested_symbols.update(standalone_entrypoint_symbols)
    requested_verification_symbols = set(re.findall(
        r"\b(?:add|define|implement|include|provide|expose)\s+"
        r"(?:an?\s+|the\s+)?"
        r"([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
        r"[^.!?\n]{0,180}\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|"
        r"validates?|self[- ]test|fake\s+"
        r"(?:clock|client|host|service))\b",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    requested_signal_handlers = _infer_signal_handler_requirements(request_prompt)
    available_public_symbols: set[str] = set()
    explicit_single_file_scope = bool(
        re.search(
            r"\b(?:exactly|only)\s+(?:one|1)\s+"
            r"(?:new\s+)?(?:[A-Za-z0-9_+-]+\s+){0,3}files?\b"
            r"|\bno\s+(?:other|extra|additional)\s+files?\b"
            r"|\bdo\s+not\s+(?:add|create|generate|write)\s+(?:any\s+)?"
            r"(?:other|extra|additional)\s+files?\b",
            request_prompt,
            flags=re.IGNORECASE,
        )
    )
    standalone_self_test = (
        len(candidate_sources) == 1
        and any(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in (
                    set(standalone_entrypoint_symbols)
                    | requested_verification_symbols
                )
                and any(isinstance(child, ast.Assert) for child in ast.walk(node))
                for node in tree.body
            )
            and (
                not standalone_entrypoint_symbols
                or any(
                    isinstance(node, ast.If)
                    and "__name__" in ast.unparse(node.test)
                    and "__main__" in ast.unparse(node.test)
                    and any(
                        isinstance(call.func, ast.Name)
                        and call.func.id in standalone_entrypoint_symbols
                        for call in ast.walk(node)
                        if isinstance(call, ast.Call)
                    )
                    for node in tree.body
                )
            )
            for tree in candidate_module_trees.values()
        )
    )
    changed_test = (
        any(_is_test_path(Path(str(item.get("path") or ""))) for item in changes)
        or standalone_self_test
        or (
            explicit_single_file_scope
            and len(candidate_sources) == 1
        )
    )
    for item in changes:
        path = Path(str(item.get("path") or ""))
        if _is_forbidden_edit_path(str(path)):
            results.append(_quality_result(
                False,
                path,
                "forbidden_edit_path",
                _edit_error_for_forbidden_path(str(path)),
            ))
            continue
        if path.suffix.lower() != ".py":
            continue
        before = str(item.get("before") or "")
        after = _sanitize_python_candidate_text(item.get("after"))
        is_new_file = before.strip() == ""
        try:
            after_tree = ast.parse(after, filename=str(path))
            compile(after_tree, str(path), "exec")
            results.append(_quality_result(True, path, "syntax", "Python parses and compiles in memory."))
        except (SyntaxError, ValueError) as exc:
            results.append(_quality_result(False, path, "syntax", f"Python syntax validation failed: {exc}"))
            continue

        try:
            before_tree = ast.parse(before, filename=str(path)) if before else ast.parse("")
        except SyntaxError:
            before_tree = ast.parse("")
        disposable_external = (
            str(path.resolve()).casefold() in disposable_external_paths
        )
        presentation_issues = (
            []
            if disposable_external
            else _generated_source_presentation_issues(after, after_tree)
        )
        prior_presentation_issues = _generated_source_presentation_issues(
            before,
            before_tree,
        ) if before else []
        new_presentation_issues = sorted(
            set(presentation_issues) - set(prior_presentation_issues)
        )
        results.append(_quality_result(
            not new_presentation_issues,
            path,
            "source_presentation",
            "Generated Python has no dead string literals, redundant lock nesting, "
            "overlong lines, or malformed docstring layout."
            if not new_presentation_issues
            else "Generated Python presentation defects: "
            + "; ".join(new_presentation_issues),
        ))
        callback_issues = _progress_callback_contract_issues(
            after_tree,
            request_prompt,
        )
        results.append(_quality_result(
            not callback_issues,
            path,
            "progress_callback_contract",
            "Progress callback calls and proofs use integer current/total steps."
            if not callback_issues
            else "Invalid progress callback contract: " + "; ".join(callback_issues),
        ))
        side_effect_contract_issues = (
            []
            if _is_test_path(path)
            else _requested_pre_side_effect_contract_issues(
                after_tree,
                request_prompt,
            )
        )
        results.append(_quality_result(
            not side_effect_contract_issues,
            path,
            "pre_side_effect_contract",
            "Requested input, path, cardinality, and host-side-effect guards are present."
            if not side_effect_contract_issues
            else "Invalid pre-side-effect contract: "
            + "; ".join(side_effect_contract_issues),
        ))
        host_result_issues = (
            []
            if _is_test_path(path)
            else _host_result_and_redundant_guard_issues(
                after_tree,
                request_prompt,
            )
        )
        results.append(_quality_result(
            not host_result_issues,
            path,
            "host_result_contract",
            "Host load/save results and normalized-value guards are explicit."
            if not host_result_issues
            else "Invalid host result contract: "
            + "; ".join(host_result_issues),
        ))
        qt_progress_issues = (
            []
            if _is_test_path(path)
            else _qt_progress_surface_issues(after_tree, request_prompt, path)
        )
        results.append(_quality_result(
            not qt_progress_issues,
            path,
            "qt_progress_surface",
            "Qt progress callbacks expose integer range, value, and status."
            if not qt_progress_issues
            else "Invalid Qt progress surface: "
            + "; ".join(qt_progress_issues),
        ))
        dynamic_host_issues = (
            []
            if _is_test_path(path)
            else _dynamic_host_api_member_issues(after_tree)
        )
        results.append(_quality_result(
            not dynamic_host_issues,
            path,
            "dynamic_host_api_members",
            "Host API member ownership is statically verifiable."
            if not dynamic_host_issues
            else f"Unverifiable dynamic host API usage in {path}: "
            + "; ".join(dynamic_host_issues),
        ))
        unreal_signature_issues = (
            []
            if _is_test_path(path)
            else _official_unreal_call_signature_issues(after_tree)
        )
        results.append(_quality_result(
            not unreal_signature_issues,
            path,
            "official_unreal_signatures",
            "Unreal calls match cached authoritative signatures."
            if not unreal_signature_issues
            else "Invalid authoritative Unreal call signature in "
            f"{path}: " + "; ".join(unreal_signature_issues),
        ))
        unreal_property_issues = (
            []
            if _is_test_path(path)
            else _official_unreal_editor_property_issues(
                after_tree,
                request_prompt,
            )
        )
        results.append(_quality_result(
            not unreal_property_issues,
            path,
            "official_unreal_editor_properties",
            "String-based Unreal editor properties match official API names."
            if not unreal_property_issues
            else "Invalid authoritative Unreal editor property in "
            f"{path}: " + "; ".join(unreal_property_issues),
        ))

        before_defs = _public_definition_map(before_tree)
        after_defs = _public_definition_map(after_tree)
        if not _is_test_path(path):
            available_public_symbols.update(name.rsplit(".", 1)[-1] for name in after_defs)
        introduced = {
            name: node for name, node in after_defs.items()
            if name not in before_defs
        }
        changed_public_definitions = {
            name: node
            for name, node in after_defs.items()
            if name not in before_defs
            or ast.dump(node, include_attributes=False)
            != ast.dump(before_defs[name], include_attributes=False)
        }
        before_top_level_defs = {
            name.rsplit(".", 1)[-1]
            for name in before_defs
        }
        imported_modules = _imported_modules(after_tree)
        imported_names = _imported_name_bindings(after_tree)
        path_ui_hint = bool(re.search(
            r"(?:^|[_-])(dialog|window|widget|panel|ui)(?:[_-]|$)",
            path.stem.lower(),
        ))
        imported_qt_surface = any(
            module.lower().startswith(("pyside", "pyqt"))
            for module in imported_modules
        ) or any(
            name.startswith("Q") or name in {"Signal", "Slot"}
            for name in imported_names
        )
        owns_ui_surface = (
            not _is_test_path(path)
            and inferred_requirements["needs_qt_import"]
            and (path_ui_hint or imported_qt_surface)
        )
        file_requirements = dict(inferred_requirements)
        if not owns_ui_surface:
            file_requirements["needs_qt_import"] = False
            file_requirements["needs_signal_connect"] = False
            file_requirements["needs_widget_entrypoint"] = False
        file_widget_requirements = (
            inferred_widget_requirements if owns_ui_surface else []
        )
        file_signal_handlers = requested_signal_handlers if owns_ui_surface else set()
        class_definitions = {
            node.name: node
            for node in after_tree.body
            if isinstance(node, ast.ClassDef)
        }
        unreal_referenced = _tree_uses_identifier(after_tree, "unreal")
        maya_referenced = (
            _tree_uses_identifier(after_tree, "maya")
            or _tree_uses_identifier(after_tree, "cmds")
        )
        cross_dcc = (
            inferred_requirements["needs_unreal_import"]
            and inferred_requirements["needs_maya_import"]
        )
        if (
            not _is_test_path(path)
            and cross_dcc
            and unreal_referenced
            and maya_referenced
        ):
            results.append(_quality_result(
                False,
                path,
                "bridge_architecture:cross_dcc",
                (
                    "A multi-DCC module directly references both Unreal and Maya SDKs. "
                    "Coordinators must use an indexed bridge/adapter and place native SDK "
                    "calls in separate host-local leaf modules; merely localizing both "
                    "imports is not a valid cross-DCC pipeline."
                ),
            ))
        if (
            not _is_test_path(path)
            and inferred_requirements["needs_unreal_import"]
            and unreal_referenced
        ):
            has_unreal_import = "unreal" in imported_modules
            has_unreal_guard = _has_optional_import_guard(after_tree, "unreal")
            has_unreal_bridge_ref = any(
                _tree_uses_identifier(after_tree, identifier)
                for identifier in (
                    "ProjectIntelligenceService",
                    "execute_unreal_capability",
                    "validate_unreal_capability",
                    "resolve_unreal_capability",
                )
            )
            results.append(_quality_result(
                has_unreal_import or has_unreal_guard or has_unreal_bridge_ref,
                path,
                "import_guard:unreal",
                (
                    "Unreal is imported with a standard top-level import or guarded runtime-safe fallback."
                    if (has_unreal_import or has_unreal_guard or has_unreal_bridge_ref)
                    else "Add Unreal host-module access through either import, optional guarded import, or bridge client/path."
                ),
            ))
        if (
            not _is_test_path(path)
            and inferred_requirements["needs_maya_import"]
            and maya_referenced
        ):
            has_maya_import = "maya" in imported_modules or "cmds" in imported_modules
            has_maya_guard = _has_optional_import_guard(after_tree, "maya")
            results.append(_quality_result(
                has_maya_import or has_maya_guard,
                path,
                "import_guard:maya",
                (
                    "Maya command access is imported with a standard top-level import or guarded runtime-safe fallback."
                    if (has_maya_import or has_maya_guard)
                    else "Add import/availability handling for Maya commands (preferred: `import maya.cmds as cmds` or `import maya`, fallback-safe: try/except ImportError or `if \"maya\" in sys.modules:`) when used."
                ),
            ))
        added_widget_classes = [
            name.rsplit(".", 1)[-1]
            for name, node in introduced.items()
            if (
                isinstance(node, ast.ClassDef)
                and any(token in name.lower() for token in ("dialog", "widget", "window"))
            )
        ]
        if (
            file_requirements["needs_widget_entrypoint"]
            and (
                is_new_file
                or (
                    added_widget_classes
                    and _has_widget_class_surface(after_tree, file_widget_requirements)
                )
            )
        ):
            has_entrypoint = _has_main_window_entrypoint(after_tree)
            results.append(_quality_result(
                has_entrypoint,
                path,
                "ui_entrypoint",
                (
                    "New widget/dialog/window module defines a guarded launch entrypoint (if __name__ == \"__main__\") with show()."
                    if has_entrypoint
                    else "For a newly created UI window/widget/dialog file, include a `if __name__ == \"__main__\":` block that constructs and shows the window."
                ),
            ))
        if file_requirements["needs_qt_import"] and not _qt_widget_import_coverage(
            {module.lower() for module in imported_modules},
            imported_names,
        ):
            results.append(_quality_result(
                False,
                path,
                "import_guard:qt",
                "Prompt requests UI behavior, but generated code is not importing a Qt-compatible symbol surface.",
            ))
        (
            class_connects,
            module_level_connects,
            class_connected_self_handlers,
            class_connecting_methods,
            init_calls,
            class_methods_by_class,
            class_method_calls,
            class_widget_defs,
            class_method_nodes,
            class_signal_targets,
            class_widget_ctors,
        ) = _iter_signal_connects(after_tree)
        class_active_methods: dict[str, set[str]] = {}
        for class_name in (
            set(class_methods_by_class)
            | set(init_calls)
            | set(class_connected_self_handlers)
        ):
            seed_methods = (
                set(init_calls.get(class_name, set()))
                | set(class_connected_self_handlers.get(class_name, set()))
                | {"__init__"}
            )
            worklist = list(seed_methods)
            seen = set(seed_methods)
            while worklist:
                method = worklist.pop(0)
                referenced_methods = set(
                    class_method_calls.get(class_name, {}).get(method, set())
                )
                method_node = class_method_nodes.get(class_name, {}).get(method)
                if method_node is not None:
                    referenced_methods.update(
                        node.attr
                        for node in ast.walk(method_node)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in {"self", "cls"}
                        and node.attr
                        in class_methods_by_class.get(class_name, set())
                    )
                for callee in referenced_methods:
                    if callee in seen:
                        continue
                    seen.add(callee)
                    worklist.append(callee)
            class_active_methods[class_name] = seen
        for class_name in class_methods_by_class:
            class_active_methods.setdefault(class_name, {"__init__"})
        for class_name, method_nodes in class_method_nodes.items():
            connection_locations: dict[str, list[str]] = {}
            for method_name in sorted(
                class_active_methods.get(class_name, {"__init__"})
            ):
                method_node = method_nodes.get(method_name)
                if method_node is None:
                    continue
                for call in ast.walk(method_node):
                    if not (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "connect"
                        and call.args
                    ):
                        continue
                    key = "|".join((
                        ast.dump(call.func.value, include_attributes=False),
                        ast.dump(call.args[0], include_attributes=False),
                    ))
                    connection_locations.setdefault(key, []).append(method_name)
            duplicate_locations = [
                locations
                for locations in connection_locations.values()
                if len(locations) > 1
            ]
            if duplicate_locations:
                results.append(_quality_result(
                    False,
                    path,
                    f"duplicate_signal_connection:{class_name}",
                    (
                        f"{class_name} connects the same signal and handler "
                        "more than once along its constructor-reachable path: "
                        + "; ".join(
                            ", ".join(locations)
                            for locations in duplicate_locations
                        )
                    ),
                ))
        flagged_api_bases: set[str] = set()
        for class_name, class_node in class_definitions.items():
            for base_node in class_node.bases:
                if not isinstance(base_node, ast.Name):
                    continue
                base_name = base_node.id
                if base_name not in class_definitions:
                    continue
                if base_name in before_top_level_defs or base_name in flagged_api_bases:
                    continue
                base_node_definition = class_definitions[base_name]
                if (
                    base_name not in requested_symbols
                    and _is_placeholder_class(base_node_definition)
                ):
                    flagged_api_bases.add(base_name)
                    results.append(_quality_result(
                        False,
                        path,
                        f"local_placeholder_api_base:{base_name}",
                        (
                            f"Class `{base_name}` looks like a local placeholder API base; "
                            "prefer importing the canonical implementation instead of defining a stub."
                        ),
                    ))
        if file_requirements["needs_signal_connect"]:
            has_connect_statements = any(connects for connects in class_connects.values())
            if not has_connect_statements:
                results.append(_quality_result(
                    False,
                    path,
                    "signal_connect_present",
                    "Prompt requests UI signal wiring but no `.connect(...)` calls were found in the generated class code.",
                ))
            if module_level_connects:
                results.append(_quality_result(
                    False,
                    path,
                    "signal_connect_scope",
                    "Signal connections must be configured inside class construction paths, not at module scope.",
                ))
            for class_name, handlers in class_connected_self_handlers.items():
                missing_handlers = sorted(
                    handler
                    for handler in handlers
                    if handler not in class_methods_by_class.get(class_name, set())
                )
                results.append(_quality_result(
                    not missing_handlers,
                    path,
                    f"signal_connect_method:{class_name}",
                    (
                        f"All signal handlers for {class_name} resolve to existing methods."
                        if not missing_handlers
                    else f"{class_name} has missing signal handler methods: "
                    + ", ".join(missing_handlers)
                ),
                ))
                for _, handler in class_signal_targets.get(class_name, []):
                    if not handler:
                        continue
                    handler_node = class_method_nodes.get(class_name, {}).get(handler)
                    if handler_node and _is_placeholder_callable(handler_node):
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_signal_handler_placeholder:{handler}",
                            f"Signal handler `{handler}` in {class_name} is a placeholder method and never implemented.",
                        ))
            if file_signal_handlers:
                connected_handlers = {
                    handler
                    for pairs in class_signal_targets.values()
                    for _, handler in pairs
                    if handler
                }
                for handler in sorted(file_signal_handlers):
                    if handler not in connected_handlers:
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_signal_handler_missing:{handler}",
                            f"Prompt requests a signal handler `{handler}`, but no `.connect(...)` targets it.",
                        ))
            for class_name, connected_methods in class_connecting_methods.items():
                init_reachable = set(init_calls.get(class_name, set()))
                worklist = list(init_reachable)
                seen = set(init_reachable)
                while worklist:
                    method = worklist.pop(0)
                    for callee in class_method_calls.get(class_name, {}).get(method, set()):
                        if callee in seen:
                            continue
                        seen.add(callee)
                        worklist.append(callee)
                missing_constructors = sorted(
                    method
                    for method in connected_methods
                    if method != "__init__" and method not in seen
                )
                if connected_methods:
                    results.append(_quality_result(
                        not missing_constructors,
                        path,
                        f"signal_connect_in_init:{class_name}",
                        (
                            f"Signal connection setup methods in {class_name} are reachable from class construction."
                            if not missing_constructors
                            else f"{class_name} has connection setup methods not reachable from __init__: "
                            + ", ".join(missing_constructors)
                        ),
                    ))
        if file_widget_requirements:
            imported_names = _imported_name_bindings(after_tree)
            top_level_names = {
                node.name
                for node in after_tree.body
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for widget_name, widget_kind in file_widget_requirements:
                owning_classes = sorted(
                    class_name
                    for class_name, widgets in class_widget_defs.items()
                    if widget_name in widgets
                )
                if not owning_classes:
                    results.append(_quality_result(
                        False,
                        path,
                        f"ui_widget_declared:{widget_name}",
                        f"Prompt requests `{widget_name}`, but no class assigns `self.{widget_name}`.",
                    ))
                    continue
                class_name = owning_classes[0]
                ctor_name = class_widget_ctors.get(class_name, {}).get(widget_name)
                if not ctor_name:
                    results.append(_quality_result(
                        False,
                        path,
                        f"ui_widget_constructor:{widget_name}",
                        f"Prompt requests `{widget_name}`, but `{class_name}` assigns it without a constructor call.",
                    ))
                else:
                    expected_ctors = _widget_expected_constructors(widget_kind)
                    ctor_name_tail = _widget_ctor_base_name(ctor_name)
                    if expected_ctors and ctor_name_tail not in expected_ctors:
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_widget_constructor:{widget_name}:kind",
                            (
                                f"{widget_name} uses `{ctor_name}`, expected a widget constructor for a {widget_kind} widget "
                                f"like {', '.join(sorted(expected_ctors))}."
                            ),
                        ))
                    if "*" not in imported_names and not _widget_ctor_is_imported(
                        ctor_name,
                        imported_names,
                        top_level_names,
                    ):
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_widget_import:{widget_name}",
                            f"Add explicit import for `{ctor_name}` used by `{widget_name}`.",
                        ))
                if widget_kind == "button":
                    button_links = [
                        (widget, handler)
                        for widget, handler in class_signal_targets.get(class_name, [])
                        if widget == widget_name
                    ]
                    if not button_links:
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_widget_connected:{widget_name}",
                            (
                                f"`{widget_name}` has no signal wiring for `{class_name}`. "
                                "Connect it during construction using a class method handler."
                            ),
                        ))
                    else:
                        handlers = sorted(
                            handler
                            for _, handler in button_links
                            if handler
                        )
                        if handlers:
                            missing = sorted(
                                handler
                                for handler in handlers
                                if handler not in class_methods_by_class.get(class_name, set())
                            )
                            results.append(_quality_result(
                                not missing,
                                path,
                                f"ui_widget_connected:{widget_name}:method_exists",
                                (
                                    f"{widget_name} is connected to existing methods on {class_name}."
                                    if not missing
                                    else f"{widget_name} connects to missing methods: "
                                    + ", ".join(missing)
                                ),
                            ))
                        else:
                            results.append(_quality_result(
                                False,
                                path,
                                f"ui_widget_connected:{widget_name}:method_exists",
                                f"{widget_name} is connected to non-method callables; use a class handler.",
                            ))
                expected_accessor = _expected_widget_accessor(widget_name, widget_kind)
                active_methods = class_active_methods.get(class_name, {"__init__"})
                handler_reads_widget = False
                output_widget = (
                    widget_name.endswith(("_label", "_preview", "_output"))
                    or bool(
                        re.search(
                            rf"\bread[- ]only\b[^.!?\n]{{0,100}}"
                            rf"\b{re.escape(widget_name)}\b"
                            rf"|\b{re.escape(widget_name)}\b[^.!?\n]{{0,100}}"
                            r"\bread[- ]only\b",
                            request_prompt,
                            flags=re.IGNORECASE,
                        )
                    )
                )
                for method_name, method_node in class_method_nodes.get(class_name, {}).items():
                    if method_name not in active_methods and method_name != "__init__":
                        continue
                    if (
                        output_widget
                        and method_name != "__init__"
                        and _method_updates_widget(method_node, widget_name)
                    ) or _method_uses_widget_access(
                        method_node,
                        widget_name,
                        expected_accessor,
                    ):
                        handler_reads_widget = True
                        break
                results.append(_quality_result(
                    handler_reads_widget if widget_kind != "button" else True,
                    path,
                    f"ui_widget_used:{widget_name}",
                    (
                        f"{widget_name} is consumed by construction-reachable handlers."
                        if (handler_reads_widget or widget_kind == "button")
                        else (
                            f"{widget_name} is never read in connected/constructing handlers. "
                            f"Use `self.{widget_name}` values in a handler."
                        )
                    ),
                ))
        if (
            not _is_test_path(path)
            and inferred_requirements["needs_factory_create_asset"]
            and unreal_referenced
            and not _has_factory_argument_call(after_tree)
        ):
            create_asset_owners: list[str] = []
            for top_level in after_tree.body:
                if isinstance(
                    top_level,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and any(
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "create_asset"
                    for call in ast.walk(top_level)
                    if isinstance(call, ast.Call)
                ):
                    create_asset_owners.append(top_level.name)
                elif isinstance(top_level, ast.ClassDef):
                    create_asset_owners.extend(
                        f"{top_level.name}.{method.name}"
                        for method in top_level.body
                        if isinstance(
                            method,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and any(
                            isinstance(call.func, ast.Attribute)
                            and call.func.attr == "create_asset"
                            for call in ast.walk(method)
                            if isinstance(call, ast.Call)
                        )
                    )
            owner_marker = (
                f"[scope:callable][owner:{create_asset_owners[0]}] "
                if len(create_asset_owners) == 1
                else "[scope:module] "
            )
            results.append(_quality_result(
                False,
                path,
                "create_asset_factory",
                owner_marker
                + "Prompt asks for Unreal asset creation via create_asset; "
                "include the verified factory argument in the exact indexed "
                "create_asset signature.",
            ))
        screen_color_picker_requested = bool(
            re.search(r"\b(?:pick|sample|capture|eyedropper)\b", request_prompt, re.I)
            and re.search(r"\bcolou?r\b", request_prompt, re.I)
            and re.search(
                r"\b(?:anywhere|any point|outside|desktop|screen)\b",
                request_prompt,
                re.I,
            )
        )
        if screen_color_picker_requested and not Path(path).name.startswith("test_"):
            rendered_source = ast.unparse(after_tree)
            captures_desktop = bool(
                re.search(r"\.grabWindow\s*\(\s*0\s*\)", rendered_source)
                or re.search(r"\.grab_window\s*\(\s*0\s*\)", rendered_source)
            )
            samples_pixel = bool(
                re.search(r"\.(?:pixelColor|pixel_color|pixel)\s*\(", rendered_source)
            )
            interactive_pick = bool(
                re.search(
                    r"\b(?:mousePressEvent|mouseReleaseEvent|eventFilter)\b",
                    rendered_source,
                )
            )
            event_filter_hooked = not re.search(
                r"\bdef\s+eventFilter\s*\(",
                rendered_source,
            ) or bool(
                re.search(r"\.installEventFilter\s*\(", rendered_source)
            )
            global_pick_surface = bool(
                re.search(
                    r"\b(?:showFullScreen|show_full_screen|FullScreen|"
                    r"grabMouse|grab_mouse|virtualGeometry|virtual_geometry)\b",
                    rendered_source,
                )
            )
            crosshair_cursor = bool(
                re.search(r"\b(?:CrossCursor|setCursor|set_cursor)\b", rendered_source)
            )
            capture_method_safety: list[bool] = []
            activation_surface_ready = False
            click_uses_global_position = False
            saves_previous_color = False
            restores_previous_color = False
            activation_owner_names: set[str] = set()
            capture_owner_names: set[str] = set()
            event_owner_names: set[str] = set()
            click_owner_names: set[str] = set()
            cancellation_owner_names: set[str] = set()
            timer_owner_names: set[str] = set()
            activation_signal_owner_names: set[str] = set()
            for class_node in [
                node for node in after_tree.body if isinstance(node, ast.ClassDef)
            ]:
                method_map = {
                    method.name: method
                    for method in class_node.body
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                for call in ast.walk(class_node):
                    if (
                        not isinstance(call, ast.Call)
                        or not isinstance(call.func, ast.Attribute)
                        or call.func.attr != "connect"
                        or not isinstance(call.func.value, ast.Attribute)
                        or not call.args
                        or not isinstance(call.args[0], ast.Attribute)
                        or not isinstance(call.args[0].value, ast.Name)
                        or call.args[0].value.id != "self"
                    ):
                        continue
                    qualified_owner = (
                        f"{class_node.name}.{call.args[0].attr}"
                    )
                    signal_name = call.func.value.attr
                    if signal_name == "timeout":
                        timer_owner_names.add(qualified_owner)
                    elif signal_name in {
                        "clicked",
                        "pressed",
                        "released",
                        "triggered",
                    }:
                        activation_signal_owner_names.add(qualified_owner)
                connected_handlers = {
                    handler
                    for _widget, handler in class_signal_targets.get(
                        class_node.name,
                        [],
                    )
                    if handler
                }
                activation_methods = {
                    owner.split(".", 1)[1]
                    for owner in activation_signal_owner_names
                    if owner.startswith(class_node.name + ".")
                } or set(connected_handlers)
                pending_methods = list(activation_methods)
                while pending_methods:
                    method_name = pending_methods.pop()
                    method = method_map.get(method_name)
                    if method is None:
                        continue
                    for call in ast.walk(method):
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "self"
                            and call.func.attr in method_map
                            and call.func.attr not in activation_methods
                        ):
                            activation_methods.add(call.func.attr)
                            pending_methods.append(call.func.attr)
                activation_owner_names.update(
                    f"{class_node.name}.{method_name}"
                    for method_name in activation_methods
                    if method_name in method_map
                )
                activation_surface_ready = activation_surface_ready or any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "show",
                        "showFullScreen",
                        "show_full_screen",
                    }
                    and (
                        "overlay" in ast.unparse(call.func.value).casefold()
                        or "surface" in ast.unparse(call.func.value).casefold()
                    )
                    for method_name in activation_methods
                    for method in [method_map.get(method_name)]
                    if method is not None
                    for call in ast.walk(method)
                )
                event_methods = [
                    method
                    for name, method in method_map.items()
                    if name in {
                        "eventFilter",
                        "mousePressEvent",
                        "mouseReleaseEvent",
                        "keyPressEvent",
                        "keyReleaseEvent",
                    }
                ]
                event_owner_names.update(
                    f"{class_node.name}.{method.name}"
                    for method in event_methods
                )
                click_owner_names.update(
                    f"{class_node.name}.{method.name}"
                    for method in event_methods
                    if re.search(
                        r"\bLeftButton\b",
                        ast.unparse(method),
                    )
                )
                cancellation_owner_names.update(
                    f"{class_node.name}.{method.name}"
                    for method in event_methods
                    if re.search(
                        r"\b(?:Key_Escape|Key\.Escape)\b",
                        ast.unparse(method),
                    )
                )
                click_uses_global_position = click_uses_global_position or any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "globalPosition",
                        "globalPos",
                    }
                    for method in event_methods
                    for call in ast.walk(method)
                )
                saves_previous_color = saves_previous_color or any(
                    isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and any(
                            marker in target.attr.casefold()
                            for marker in ("previous", "prior", "original")
                        )
                        for target in node.targets
                    )
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr in {
                        "text",
                        "currentText",
                        "value",
                    }
                    for node in ast.walk(class_node)
                )
                restores_previous_color = restores_previous_color or any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "setText",
                        "setCurrentText",
                        "setValue",
                    }
                    and any(
                        isinstance(argument, ast.Attribute)
                        and isinstance(argument.value, ast.Name)
                        and argument.value.id == "self"
                        and any(
                            marker in argument.attr.casefold()
                            for marker in ("previous", "prior", "original")
                        )
                        for argument in call.args
                    )
                    for method in event_methods
                    for call in ast.walk(method)
                )
                for method in [
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]:
                    calls = [
                        call
                        for call in ast.walk(method)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                    ]
                    grab_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {"grabWindow", "grab_window"}
                    ]
                    if not grab_lines:
                        continue
                    capture_owner_names.add(
                        f"{class_node.name}.{method.name}"
                    )
                    hide_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {
                            "hide",
                            "setVisible",
                            "set_visible",
                            "close",
                            "hide_overlay",
                        }
                        and (
                            "overlay" in ast.unparse(call.func.value).casefold()
                            or "surface" in ast.unparse(call.func.value).casefold()
                            or "overlay" in call.func.attr.casefold()
                        )
                    ]
                    flush_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {"processEvents", "process_events"}
                    ]
                    show_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {
                            "show",
                            "showFullScreen",
                            "show_full_screen",
                        }
                        and (
                            "overlay" in ast.unparse(call.func.value).casefold()
                            or "surface" in ast.unparse(call.func.value).casefold()
                            or "overlay" in call.func.attr.casefold()
                        )
                    ]
                    first_grab = min(grab_lines)
                    capture_method_safety.append(
                        (
                            any(line < first_grab for line in hide_lines)
                            and any(line < first_grab for line in flush_lines)
                        )
                        or any(first_grab < line for line in show_lines)
                    )
            avoids_overlay_capture = bool(capture_method_safety) and all(
                capture_method_safety
            )
            cancellation_restore_requested = bool(
                re.search(
                    r"\b(?:cancel|escape)\b[^.!?\n]{0,120}\brestor"
                    r"|\brestor[^.!?\n]{0,120}\b(?:cancel|escape)\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                )
            )
            cancellation_state_valid = (
                not cancellation_restore_requested
                or (saves_previous_color and restores_previous_color)
            )
            default_screen_owners = (
                activation_owner_names
                or event_owner_names
                or capture_owner_names
            )
            screen_behavior_checks = (
                (
                    captures_desktop,
                    "capture the desktop with QScreen.grabWindow(0)",
                    capture_owner_names or timer_owner_names,
                ),
                (
                    samples_pixel,
                    "read a pixel from the captured image",
                    capture_owner_names or timer_owner_names,
                ),
                (
                    interactive_pick,
                    "handle mouse input while eyedropper mode is active",
                    event_owner_names,
                ),
                (
                    crosshair_cursor,
                    "show a crosshair cursor",
                    activation_owner_names or default_screen_owners,
                ),
                (
                    global_pick_surface,
                    "provide a screen-wide pick surface or global input",
                    activation_owner_names or default_screen_owners,
                ),
                (
                    avoids_overlay_capture,
                    "hide the actual overlay and flush events before capture",
                    capture_owner_names or timer_owner_names,
                ),
                (
                    event_filter_hooked,
                    "install the declared event filter",
                    activation_owner_names or event_owner_names,
                ),
                (
                    activation_surface_ready,
                    "show the pick surface from the connected activation path",
                    activation_owner_names or default_screen_owners,
                ),
                (
                    click_uses_global_position,
                    "sample the exact left-click global position",
                    click_owner_names,
                ),
                (
                    cancellation_state_valid,
                    "save and restore the pre-pick color on cancellation",
                    cancellation_owner_names,
                ),
            )
            requires_class_owned_repair = any(
                not passed and not owners
                for passed, _description, owners in screen_behavior_checks
            )
            missing_screen_behaviors = [
                description
                + "".join(
                    f" [owner:{owner}]"
                    for owner in sorted(owners)
                )
                for passed, description, owners in screen_behavior_checks
                if not passed
            ]
            results.append(_quality_result(
                captures_desktop
                and samples_pixel
                and interactive_pick
                and crosshair_cursor
                and global_pick_surface
                and avoids_overlay_capture
                and event_filter_hooked
                and activation_surface_ready
                and click_uses_global_position
                and cancellation_state_valid,
                path,
                "screen_color_sampling",
                (
                    "Screen color picker provides a global/full-screen pick surface, "
                    "uses a crosshair, avoids capturing its own overlay, captures a "
                    "desktop QScreen, and samples the user-selected pixel."
                    if captures_desktop
                    and samples_pixel
                    and interactive_pick
                    and global_pick_surface
                    and crosshair_cursor
                    and avoids_overlay_capture
                    and event_filter_hooked
                    and activation_surface_ready
                    and click_uses_global_position
                    and cancellation_state_valid
                    else (
                        "Missing eyedropper behaviors: "
                        + "; ".join(missing_screen_behaviors)
                        + (
                            " [repair-scope:class]"
                            if requires_class_owned_repair
                            else ""
                        )
                        + ". A screen-wide color picker must use a real eyedropper interaction: "
                        "provide a full-screen/virtual-desktop pick surface (or verified "
                        "global input), use a crosshair, hide/process events before capture "
                        "or capture before showing the overlay, call QScreen.grabWindow(0), "
                        "obtain the clicked global position, and read the corresponding "
                        "image pixel, and install any declared eventFilter on the overlay. "
                        "Show the pick surface from the activation handler, hide that "
                        "surface rather than the dialog before capture, sample the exact "
                        "click global position when committing, and preserve/restore "
                        "the prior value when cancellation requires restoration. "
                        "A small ordinary window or QColorDialog alone does not pick from "
                        "anywhere on screen."
                    )
                ),
            ))
        invalid_api_contracts, unverifiable_api_contracts = _invalid_runtime_api_contracts(
            request_prompt,
            after_tree,
            project_root=project_root,
        )
        requested_runtime_apis = _infer_explicit_runtime_api_requests(request_prompt)
        generated_runtime_apis = _runtime_api_calls_in_tree(after_tree)
        missing_requested_runtime_apis = (
            []
            if _is_test_path(path)
            else sorted(
                requested
                for requested in requested_runtime_apis
                if not any(
                    generated == requested
                    or generated.startswith(requested + ".")
                    or requested.startswith(generated + ".")
                    for generated in package_generated_runtime_apis
                )
            )
        )
        results.append(_quality_result(
            not missing_requested_runtime_apis,
            path,
            "requested_runtime_api_coverage",
            "Explicitly requested runtime API call chains are used."
            if not missing_requested_runtime_apis
            else "Generated code replaced or omitted explicitly requested runtime API "
            "call chains: "
            + ", ".join(missing_requested_runtime_apis),
        ))
        if root_path is not None:
            try:
                current_module = ".".join(
                    Path(path).resolve().relative_to(root_path).with_suffix("").parts
                )
            except (OSError, ValueError):
                current_module = Path(path).stem
        else:
            current_module = Path(path).stem
        invalid_imported_calls, unresolved_imported_calls = _imported_call_api_contracts(
            after_tree,
            current_module=current_module,
            candidate_module_trees=candidate_module_trees,
            project_root=project_root,
        )
        results.append(_quality_result(
            not invalid_imported_calls,
            path,
            "imported_api_members",
            "Imported callable members resolve to real generated or installed API symbols."
            if not invalid_imported_calls
            else "Imported callable members do not exist: "
            + ", ".join(invalid_imported_calls),
        ))
        results.append(_quality_result(
            not unresolved_imported_calls,
            path,
            "imported_api_evidence",
            "Every imported call has resolvable API evidence."
            if not unresolved_imported_calls
            else "Capability gap: imported calls lack project, plugin, catalog, installed, "
            "or official API evidence: "
            + ", ".join(unresolved_imported_calls),
        ))
        if invalid_api_contracts:
            results.append(_quality_result(
                False,
                path,
                "api_contract",
                "Prompt requested explicit runtime APIs that are not present in "
                f"{path}: "
                + ", ".join(invalid_api_contracts),
            ))
        elif unverifiable_api_contracts:
            results.append(_quality_result(
                False,
                path,
                "api_contract",
                "Capability gap in "
                f"{path}: host runtime calls lack indexed, bridge, installed, "
                "or official API evidence: "
                + ", ".join(unverifiable_api_contracts),
            ))
        if not _is_test_path(path):
            docstring_scope = (
                changed_public_definitions
                if "docstring" in request_prompt.lower()
                else introduced
            )
            missing_docs = sorted(
                name for name, node in docstring_scope.items()
                if not ast.get_docstring(node)
            )
            results.append(_quality_result(
                not missing_docs,
                path,
                "public_docstrings",
                "New public callables have docstrings."
                if not missing_docs
                else "New public callables need useful docstrings: " + ", ".join(missing_docs),
            ))
            docstring_contract_issues = sorted(
                issue
                for name, node in docstring_scope.items()
                if ast.get_docstring(node)
                for issue in _generated_docstring_contract_issues(name, node)
            )
            results.append(_quality_result(
                not docstring_contract_issues,
                path,
                "public_docstring_contract",
                "New public callable docstrings describe behavior, parameters, and returned values."
                if not docstring_contract_issues
                else "Requested useful docstrings are too vague: "
                + "; ".join(docstring_contract_issues),
            ))
            placeholder_names = sorted(
                name for name in introduced
                if name.rsplit(".", 1)[-1].lower() in _PLACEHOLDER_PUBLIC_NAMES
            )
            results.append(_quality_result(
                not placeholder_names,
                path,
                "clear_names",
                "New public callable names are domain-specific."
                if not placeholder_names
                else "Replace placeholder public names: " + ", ".join(placeholder_names),
            ))
            placeholder_callables = sorted(
                name
                for name, node in introduced.items()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(
                    isinstance(statement, ast.Pass)
                    or (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Constant)
                        and statement.value.value is Ellipsis
                    )
                    for statement in node.body
                )
            )
            results.append(_quality_result(
                not placeholder_callables,
                path,
                "placeholder_callables",
                "Generated production callables have substantive bodies."
                if not placeholder_callables
                else "Generated production callables are placeholders: "
                + ", ".join(placeholder_callables),
            ))
            if "docstring" in request_prompt.lower():
                undocumented = sorted(
                    name for name, node in changed_public_definitions.items()
                    if not ast.get_docstring(node)
                )
                results.append(_quality_result(
                    not undocumented,
                    path,
                    "requested_docstrings",
                    "Requested public callable docstrings are present."
                    if not undocumented
                    else "Requested docstrings are missing: " + ", ".join(undocumented),
                ))
            incomplete_type_hints = _incomplete_generated_type_hints(after_tree)
            results.append(_quality_result(
                not incomplete_type_hints,
                path,
                "complete_type_hints",
                "Every generated callable has complete, valid type hints."
                if not incomplete_type_hints
                else "Requested complete type hints are invalid or missing: "
                + ", ".join(incomplete_type_hints),
            ))
            missing_bool_rejections = _missing_explicit_bool_rejections(
                after_tree,
                request_prompt,
            )
            results.append(_quality_result(
                not missing_bool_rejections,
                path,
                "explicit_bool_rejection",
                "Every explicitly invalid boolean input is rejected."
                if not missing_bool_rejections
                else "Explicitly invalid boolean inputs are not proven rejected in: "
                + ", ".join(missing_bool_rejections),
            ))
            unresolved_by_callable = _unresolved_generated_names_by_callable(after_tree)
            introduced_callable_ids = {
                id(node)
                for node in introduced.values()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            unresolved = sorted({
                name
                for node_id, names in unresolved_by_callable.items()
                for name in names
                if node_id in introduced_callable_ids
            })
            unresolved = sorted({
                *unresolved,
                *_unresolved_module_scope_names(after_tree),
                *(
                    name
                    for name in _unresolved_generated_names(after_tree)
                    if name.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
                ),
            })
            unresolved_owners = sorted(
                name
                for name, node in _callable_definition_map(after_tree).items()
                if id(node) in introduced_callable_ids and unresolved_by_callable.get(id(node))
            )
            results.append(_quality_result(
                not unresolved,
                path,
                "undefined_names",
                "Generated callables do not reference undefined Python names."
                if not unresolved
                else "Generated callables reference undefined names in "
                + ", ".join(unresolved_owners or ["<module>"])
                + ": "
                + ", ".join(unresolved),
            ))
            removed_identifiers, rename_pairs = _requested_identifier_contracts(request_prompt)
            remaining_removed = sorted(
                identifier
                for identifier in removed_identifiers
                if _tree_uses_identifier(after_tree, identifier)
            )
            remaining_renamed = sorted(
                source_name
                for source_name, _target_name in rename_pairs
                if _tree_uses_identifier(after_tree, source_name)
            )
            results.append(_quality_result(
                not remaining_removed,
                path,
                "requested_identifier_removal",
                "Explicitly requested dead identifiers were removed."
                if not remaining_removed
                else "Requested removed identifiers remain: " + ", ".join(remaining_removed),
            ))
            results.append(_quality_result(
                not remaining_renamed,
                path,
                "requested_identifier_renames",
                "Explicitly requested identifier renames were completed."
                if not remaining_renamed
                else "Requested renamed identifiers remain: " + ", ".join(remaining_renamed),
            ))
            unrequested_public = sorted(
                name
                for name in introduced
                if (removed_identifiers or rename_pairs)
                and before_defs
                and name.rsplit(".", 1)[-1] not in requested_symbols
                and not re.search(
                    rf"\b{re.escape(name.rsplit('.', 1)[-1])}\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                )
            )
            results.append(_quality_result(
                not unrequested_public,
                path,
                "public_scope",
                "No unrelated public callables were introduced."
                if not unrequested_public
                else "Unrequested public callables were introduced: " + ", ".join(unrequested_public),
            ))
        else:
            placeholder_tests = sorted(
                name
                for name, node in after_defs.items()
                if name.rsplit(".", 1)[-1].startswith("test_")
                and any(isinstance(child, ast.Pass) for child in ast.walk(node))
            )
            results.append(_quality_result(
                not placeholder_tests,
                path,
                "placeholder_tests",
                "Focused tests contain substantive assertions."
                if not placeholder_tests
                else "Generated test methods are placeholders: " + ", ".join(placeholder_tests),
            ))
            proof_issues: list[str] = []
            proof_details: list[str] = []
            prompt_lower = request_prompt.lower()
            imported_modules = {
                node.module
                for node in after_tree.body
                if isinstance(node, ast.ImportFrom) and node.module
            }
            imported_modules.update(
                alias.name
                for node in after_tree.body
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            for name, node in after_defs.items():
                test_name = name.rsplit(".", 1)[-1].lower()
                if not test_name.startswith("test_"):
                    continue
                assertion_names = {
                    child.func.attr
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                }
                has_direct_behavior_assertion = any(
                    isinstance(child, ast.Assert)
                    or (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and (
                            child.func.attr.startswith("assert")
                            or child.func.attr == "raises"
                        )
                    )
                    for child in ast.walk(node)
                )
                if not has_direct_behavior_assertion:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: executes behavior without a direct assertion or "
                        "expected-exception assertion in the test method"
                    )
                stored_names = {
                    child.id
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Store)
                }
                loaded_names = {
                    child.id
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                }
                unused_fixtures = sorted(
                    value
                    for value in stored_names - loaded_names
                    if value not in {"self", "cls"}
                    and not value.startswith("_")
                )
                if unused_fixtures:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: fixture variables never consumed: "
                        + ", ".join(unused_fixtures)
                    )
                mocked_owner_methods = sorted({
                    str(child.args[1].value)
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "patch"
                    and child.func.attr == "object"
                    and len(child.args) >= 2
                    and isinstance(child.args[1], ast.Constant)
                    and isinstance(child.args[1].value, str)
                    and (
                        "_" + str(child.args[1].value).casefold() + "_"
                        in "_" + test_name + "_"
                    )
                })
                if mocked_owner_methods:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: mocks production method under test: "
                        + ", ".join(mocked_owner_methods)
                    )
                command_fixtures = [
                    child
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and (
                        any(
                            keyword.arg == "command"
                            and isinstance(keyword.value, ast.Constant)
                            and isinstance(keyword.value.value, str)
                            for keyword in child.keywords
                        )
                        or (
                            isinstance(child.func, ast.Name)
                            and child.func.id.endswith(("JobSpec", "CommandSpec"))
                            and len(child.args) >= 2
                            and isinstance(child.args[1], ast.Constant)
                            and isinstance(child.args[1].value, str)
                        )
                    )
                ]
                has_process_mock = any(
                    isinstance(child, ast.Call)
                    and (
                        (
                            isinstance(child.func, ast.Name)
                            and child.func.id in {"patch", "patch.object", "AsyncMock"}
                        )
                        or (
                            isinstance(child.func, ast.Attribute)
                            and (
                                child.func.attr == "patch"
                                or (
                                    child.func.attr == "object"
                                    and isinstance(child.func.value, ast.Name)
                                    and child.func.value.id == "patch"
                                )
                            )
                        )
                    )
                    for child in ast.walk(node)
                ) or any(
                    isinstance(child, ast.With)
                    and "patch(" in ast.unparse(child)
                    for child in ast.walk(node)
                )
                if command_fixtures and not has_process_mock:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: external command fixtures require a mocked or "
                        "injected process boundary"
                    )
                patch_targets = [
                    str(child.args[0].value)
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and child.args
                    and isinstance(child.args[0], ast.Constant)
                    and isinstance(child.args[0].value, str)
                    and (
                        (
                            isinstance(child.func, ast.Name)
                            and child.func.id == "patch"
                        )
                        or (
                            isinstance(child.func, ast.Attribute)
                            and child.func.attr == "patch"
                        )
                    )
                ]
                invalid_patch_targets = [
                    target
                    for target in patch_targets
                    if not patch_target_exists(target)
                ]
                if invalid_patch_targets:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: patch targets do not resolve to real generated or "
                        "installed API symbols: "
                        + ", ".join(invalid_patch_targets)
                    )
                query_terms = ("report", "find", "return", "list", "order")
                prompt_requires_error = bool(re.search(
                    r"\b(?:raise|raises|reject|error|exception)\b"
                    r"|\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                ))
                if (
                    any(term in test_name for term in query_terms)
                    and "assertRaises" in assertion_names
                    and not prompt_requires_error
                ):
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: query/report behavior is asserted only as an "
                        "exception even though the request does not require one"
                    )
                if (
                    "add with summary" in prompt_lower
                    and "summary" in test_name
                    and not assertion_names.intersection({"assertEqual", "assertDictEqual"})
                ):
                    proof_issues.append(name)
                if (
                    "dynamic default path" in prompt_lower
                    and "dynamic" in test_name
                    and "path" in test_name
                    and not any(
                        isinstance(child, ast.Attribute) and child.attr == "expanduser"
                        for child in ast.walk(node)
                    )
                ):
                    proof_issues.append(name)
            proof_issues = sorted(set(proof_issues))
            results.append(_quality_result(
                not proof_issues,
                path,
                "behavioral_test_proof",
                "Focused tests prove the named requested behavior."
                if not proof_issues
                else "Generated test methods need stronger behavioral proof: "
                + ", ".join(proof_issues)
                + (
                    "; " + " | ".join(proof_details)
                    if proof_details
                    else ""
                ),
            ))
            unresolved = _unresolved_generated_names(after_tree)
            unresolved = {
                name
                for name in unresolved
                if name.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
            }
            unresolved_by_callable = _unresolved_generated_names_by_callable(after_tree)
            unresolved_owners = sorted(
                name
                for name, node in _callable_definition_map(after_tree).items()
                if {
                    value
                    for value in unresolved_by_callable.get(id(node), set())
                    if value.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
                }
            )
            results.append(_quality_result(
                not unresolved,
                path,
                "undefined_test_names",
                "Generated tests do not reference undefined Python names."
                if not unresolved
                else "Generated callables reference undefined names in "
                + ", ".join(unresolved_owners or ["<module>"])
                + ": "
                + ", ".join(unresolved),
            ))

        before_imports = _import_specs(before_tree)
        new_imports = [spec for spec in _import_specs(after_tree) if spec not in before_imports]
        if not new_imports:
            results.append(_quality_result(True, path, "imports", "No unresolved new imports were introduced."))
        for module, level, imported_name in new_imports:
            if _is_self_import(path, module, level, project_root=project_root):
                label = "." * level + module
                results.append(_quality_result(
                    False,
                    path,
                    f"import:{label}",
                    f"A module cannot import its requested implementation from itself: {label}.",
                ))
                continue
            ok, detail = _resolve_import_spec(
                path,
                module,
                level,
                imported_name,
                project_root=project_root,
                candidate_sources=candidate_sources,
            )
            label = "." * level + module
            if imported_name and imported_name != "*":
                label += f".{imported_name}"
            results.append(_quality_result(ok, path, f"import:{label}", detail))

        missing_requested_symbols = sorted(requested_symbols - available_public_symbols)
        if requested_symbols:
            results.append({
                "ok": not missing_requested_symbols,
                "path": "",
                "check": "requested_symbols",
                "command": "candidate:requested_symbols",
                "message": (
                    "Every explicitly requested public symbol exists in the candidate."
                    if not missing_requested_symbols
                    else "Candidate did not implement requested public symbols: "
                    + ", ".join(missing_requested_symbols)
                ),
            })

        if _requires_behavior_test(request_prompt):
            disposable_harness_required = bool(re.search(
                r"\bvalidation\s+artifacts?\s+(?:must\s+be\s+)?temporary\b"
                r"|\b(?:do\s+not|don't|without|no)\s+"
                r"(?:(?:create|add|generate|write|include|produce|use)\s+)?"
                r"(?:any\s+|new\s+|project\s+)*"
                r"(?:test\s+files?|tests?)\b",
                request_prompt,
                flags=re.IGNORECASE,
            )) or behavioral_proof_deferred
            standalone_owner = (
                standalone_entrypoint_symbols[0]
                if standalone_entrypoint_symbols
                else ""
            )
            behavior_failure = (
                f"[scope:module][owner:{standalone_owner}] The explicitly requested "
                f"standalone behavior-proof contract is incomplete: require a "
                f"module-level {standalone_owner}() with assertions and a __main__ "
                "block that calls it."
                if explicit_single_file_scope and standalone_owner
                else "[scope:package] Behavior-changing work requires a focused test file "
                "with automated behavioral proof before preview approval."
            )
            results.append({
                "ok": changed_test or disposable_harness_required,
                "path": "",
                "check": "behavior_tests",
                "command": "focused behavior test required",
                "message": (
                    "The candidate includes focused automated test changes for the requested behavior."
                    if changed_test
                    else (
                        "Focused behavioral proof is deferred to the required "
                        "disposable validation harness and may not be returned as "
                        "a project artifact."
                    )
                    if disposable_harness_required
                    else behavior_failure
                ),
            })
        static_failures = [
            result
            for result in results
            if not result.get("ok")
        ]
        is_final_candidate = (
            str(path.resolve()) == final_candidate_path
        )
        if changed_test and is_final_candidate and not static_failures:
            disposable_started = time.perf_counter()
            disposable_results = _validate_candidate_changes_in_disposable_workspace(
                changes,
                project_root=project_root,
                request_prompt=request_prompt,
                allowed_external_paths=allowed_external_paths,
            )
            disposable_elapsed_ms += (
                time.perf_counter() - disposable_started
            ) * 1000.0
            results.extend(disposable_results)
    total_elapsed_ms = (time.perf_counter() - validation_started) * 1000.0
    results.append({
        "ok": True,
        "path": "",
        "check": "validation_timing",
        "command": "candidate:validation_timing",
        "message": (
            f"Validation timing: static={max(0.0, total_elapsed_ms - disposable_elapsed_ms):.0f}ms, "
            f"disposable={disposable_elapsed_ms:.0f}ms, total={total_elapsed_ms:.0f}ms."
        ),
    })
    return results


def preview_project_edit_agent_response(
    model_response: str,
    *,
    project_root: str | None = None,
    request_prompt: str = "",
    allowed_external_paths: set[str] | None = None,
    behavioral_proof_deferred: bool = False,
) -> ProjectEditApplyResult:
    """Parse and resolve model-produced file changes without writing them."""

    changes, errors = _resolve_model_changes(
        model_response,
        project_root=project_root,
        allowed_external_paths=allowed_external_paths,
    )
    if changes and not errors:
        generated_records = [
            (
                str(item.get("path") or ""),
                str(item.get("before") or ""),
                str(item.get("after") or ""),
            )
            for item in changes
            if str(item.get("path") or "").lower().endswith(".py")
        ]
        normalized_records, _docstring_fixes = ensure_project_edit_requested_docstrings(
            generated_records,
            request_prompt=request_prompt,
            force=False,
        )
        normalized_records, _formatting_fixes = format_project_edit_generated_python(
            normalized_records,
        )
        normalized_by_path = {
            path: source for path, _original, source in normalized_records
        }
        for item in changes:
            path = str(item.get("path") or "")
            if path in normalized_by_path:
                item["after"] = normalized_by_path[path]
                item["new_content"] = normalized_by_path[path]
    validation = _validate_candidate_changes(
        changes,
        project_root=project_root,
        request_prompt=request_prompt,
        allowed_external_paths=allowed_external_paths,
        behavioral_proof_deferred=behavioral_proof_deferred,
    ) if changes and not errors else []
    validation_errors = [
        str(item.get("message") or item.get("check") or "Candidate quality validation failed.")
        for item in validation
        if not item.get("ok")
    ]
    errors.extend(validation_errors)
    return ProjectEditApplyResult(
        ok=not errors and bool(changes),
        status="preview_ready" if changes and not errors else "preview_failed",
        changes=changes,
        validation=validation,
        errors=errors or ([] if changes else ["No <modify_file> or <create_file> changes found."]),
    )


def _validate_changes(
    changes: list[dict[str, Any]],
    *,
    project_root: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    test_paths: list[Path] = []
    for item in changes:
        path = Path(str(item.get("path") or ""))
        if path.suffix.lower() != ".py":
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            results.append(
                {
                    "ok": True,
                    "path": str(path),
                    "command": f"py_compile {path.name}",
                    "message": "Python syntax check passed.",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "path": str(path),
                    "command": f"py_compile {path.name}",
                    "message": str(exc),
                }
            )
        if _is_test_path(path):
            test_paths.append(path)

    for path in test_paths:
        root = Path(project_root) if project_root else path.parent
        env = os.environ.copy()
        python_paths = [str(root), str(path.parent)]
        if env.get("PYTHONPATH"):
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(python_paths))
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(path.parent),
            "-p",
            path.name,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
            output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
            match = re.search(r"Ran\s+(\d+)\s+tests?", output)
            ran_tests = int(match.group(1)) if match else 0
            ok = completed.returncode == 0 and ran_tests > 0
            message = (
                f"Focused behavior tests passed ({ran_tests} test{'s' if ran_tests != 1 else ''})."
                if ok
                else f"Focused behavior test failed or ran no tests: {output[-2000:]}"
            )
        except subprocess.TimeoutExpired:
            ok = False
            message = "Focused behavior test exceeded the 120 second timeout."
        except OSError as exc:
            ok = False
            message = f"Focused behavior test could not start: {exc}"
        results.append({
            "ok": ok,
            "path": str(path),
            "command": " ".join(command),
            "message": message,
        })
    return results


def _change_staleness_error(item: dict[str, Any]) -> str:
    """Return an error when source changed after preview generation.

    :param item: Resolved project-edit change.
    :return: Staleness error or an empty string.
    """

    path = Path(str(item.get("path") or ""))
    action = str(item.get("action") or "modify")
    if action == "create":
        return f"{path}: create target now exists; refusing to overwrite it." if path.exists() else ""
    if not path.exists():
        return f"{path}: source was removed after preview."
    try:
        current = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"{path}: source could not be re-read before apply: {exc}"
    if current != str(item.get("before") or ""):
        return f"{path}: source changed after preview; regenerate the edit against current content."
    return ""


def _write_text_atomically(path: Path, content: str) -> None:
    """Replace one text file atomically after writing a sibling temporary file.

    :param path: Destination path.
    :param content: Complete replacement text.
    :return: None.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tech-connector-",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline=None) as stream:
            stream.write(str(content))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _rollback_written_changes(session: Any, written: list[dict[str, Any]]) -> tuple[bool, str, list[str]]:
    """Rollback only changes that reached their destination paths.

    :param session: Saved change session.
    :param written: Successfully written change rows.
    :return: Rollback status, message, and restored paths.
    """

    if not written:
        return True, "No files required rollback.", []
    from tech_connector.services.change_history_service import undo_change_session

    written_paths = {
        str(Path(str(item.get("path") or "")).resolve()) for item in written
    }
    rollback_session = type(session)(
        session_id=session.session_id,
        created_at=session.created_at,
        summary=session.summary,
        files=[item for item in session.files if item.path in written_paths],
    )
    return undo_change_session(rollback_session)


def apply_project_edit_agent_response(
    model_response: str,
    *,
    project_root: str | None = None,
    validate: bool = True,
    request_prompt: str = "",
    behavioral_proof_satisfied: bool = False,
) -> ProjectEditApplyResult:
    """Apply a validated model edit as a rollback-safe transaction.

    :param model_response: Structured model-produced changes.
    :param project_root: Optional project boundary.
    :param validate: Whether to run post-write validation.
    :param request_prompt: Original user request.
    :param behavioral_proof_satisfied: Whether disposable proof already passed.
    :return: Application, validation, and rollback result.
    """

    preview = preview_project_edit_agent_response(
        model_response,
        project_root=project_root,
        request_prompt=request_prompt,
        behavioral_proof_deferred=behavioral_proof_satisfied,
    )
    if not preview.ok:
        return preview

    pending = {
        item["path"]: {
            "action": item["action"],
            "original_content": item.get("before", ""),
            "new_content": item.get("after", ""),
            "current": item.get("after", ""),
        }
        for item in preview.changes
    }

    stale_errors = [
        error for item in preview.changes
        if (error := _change_staleness_error(item))
    ]
    if stale_errors:
        return ProjectEditApplyResult(
            ok=False,
            status="stale_source",
            changes=preview.changes,
            validation=preview.validation,
            errors=stale_errors,
        )

    change_session_path = ""
    try:
        from tech_connector.services.change_history_service import create_change_session, save_change_session

        session = create_change_session(pending, summary="Project Edit Agent changes")
        change_session_path = str(save_change_session(session))
    except Exception as exc:
        preview.errors.append(f"Could not save undo session: {exc}")
        return ProjectEditApplyResult(
            ok=False,
            status="undo_session_failed",
            changes=preview.changes,
            errors=preview.errors,
        )

    write_errors: list[str] = []
    written: list[dict[str, Any]] = []
    for item in preview.changes:
        path = Path(item["path"])
        stale_error = _change_staleness_error(item)
        if stale_error:
            write_errors.append(stale_error)
            break
        try:
            _write_text_atomically(path, item.get("after", ""))
            written.append(item)
        except Exception as exc:
            write_errors.append(f"{path}: {exc}")
            break

    if write_errors:
        rollback_ok, rollback_message, _restored = _rollback_written_changes(
            session,
            written,
        )
        if rollback_ok:
            from tech_connector.services.change_history_service import (
                deactivate_change_session,
            )

            deactivate_change_session(session)
        errors = [*write_errors, f"Rollback: {rollback_message}"]
        return ProjectEditApplyResult(
            ok=False,
            status=(
                "write_failed_rolled_back"
                if rollback_ok
                else "write_failed_rollback_incomplete"
            ),
            changes=written,
            validation=[],
            change_session_path=change_session_path,
            errors=errors,
        )

    validation = _validate_changes(written, project_root=project_root) if validate else []
    validation_failed = [item for item in validation if not item.get("ok")]
    if validation_failed:
        rollback_ok, rollback_message, _restored = _rollback_written_changes(
            session,
            written,
        )
        if rollback_ok:
            from tech_connector.services.change_history_service import (
                deactivate_change_session,
            )

            deactivate_change_session(session)
        return ProjectEditApplyResult(
            ok=False,
            status=(
                "validation_failed_rolled_back"
                if rollback_ok
                else "validation_failed_rollback_incomplete"
            ),
            changes=written,
            validation=validation,
            change_session_path=change_session_path,
            errors=[
                *[str(item.get("message")) for item in validation_failed],
                f"Rollback: {rollback_message}",
            ],
        )
    return ProjectEditApplyResult(
        ok=True,
        status="applied",
        changes=written,
        validation=validation,
        change_session_path=change_session_path,
        errors=[],
    )


def validate_project_edit_paths(paths: list[str]) -> list[dict[str, Any]]:
    """Validate changed files using the same checks as the project edit agent."""

    return _validate_changes([{"path": path} for path in paths])


def _stage(key: str, label: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": "completed"}


def build_project_edit_plan_from_leaf_work_units(
    prompt: str,
    work_units: ProjectEditLeafWorkUnits,
) -> ProjectEditPlan:
    """Rehydrate the minimal grounded plan needed by approved execution."""

    target = Path(work_units.target_path)
    module_parts = work_units.owner_module.split(".")
    project_root = target.parents[max(0, len(module_parts) - 1)]
    best_target = {
        "path": work_units.target_path,
        "score": 100,
        "index_revision": work_units.target_revision,
        "symbols": [{
            "path": work_units.target_path,
            "name": work_units.integration_symbol.rsplit(".", 1)[-1],
            "qualname": work_units.integration_symbol,
            "kind": "function",
            "source": work_units.integration_source,
        }],
        "chunks": [],
    }
    discovery = {
        "question": prompt,
        "terms": sorted(_leaf_ranking_terms(prompt)),
        "scope": "approved_snapshot",
        "project_roots": [str(project_root)],
        "active_path": work_units.target_path,
        "best_target": best_target,
        "candidates": [best_target, {
            "path": work_units.test_path,
            "score": 90,
            "index_revision": work_units.test_revision,
            "symbols": [{
                "path": work_units.test_path,
                "name": work_units.test_anchor_symbol.rsplit(".", 1)[-1],
                "qualname": work_units.test_anchor_symbol,
                "kind": "method",
                "source": work_units.test_anchor_source,
            }],
            "chunks": [],
        }],
        "confidence": "high",
        "evidence_mode": "approved_index_handoff",
        "index_revision": work_units.target_revision,
    }
    intelligence = _lightweight_project_edit_intelligence_packet(prompt, discovery)
    adaptive = build_code_agent_adaptive_plan(
        prompt,
        discovery=discovery,
        active_path=work_units.target_path,
        intelligence_packet=intelligence,
    )
    from tech_connector.services.project_service import build_project_edit_target_prompt, format_edit_target_context

    context = format_edit_target_context(discovery)
    return ProjectEditPlan(
        prompt=prompt,
        active_path=work_units.target_path,
        discovery=discovery,
        discovery_context=context,
        intelligence_packet=intelligence,
        adaptive_plan=adaptive,
        success_contract=list(adaptive.get("success_contract") or []),
        model_prompt=build_project_edit_target_prompt(
            question=prompt,
            discovery_context=context,
            active_path=work_units.target_path,
        ),
        stages=[_stage("approved_handoff", "Restored approved indexed work units")],
    )


def _trim_text(text: str, max_chars: int) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 80
    return text[:head].rstrip() + "\n\n... [middle omitted for staged prompt] ...\n\n" + text[-tail:].lstrip()


def build_project_edit_leaf_stage(
    work_units: ProjectEditLeafWorkUnits,
    *,
    kind: str,
    attempt: int,
    objective: str,
    approved_plan: str,
    dependency_source: str = "",
) -> ProjectEditPromptStage:
    """Build one source-only subagent task with no file mutation authority."""

    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in {"define", "integrate", "test"}:
        raise ValueError(f"Unsupported project edit leaf task: {kind}")
    if normalized_kind in {"define", "test"}:
        profile = "micro" if attempt <= 1 else "small"
    else:
        profile = "small" if attempt <= 1 else "standard"
    budgets = {
        "define": (4096, 700, 75),
        "integrate": (6144, 1500, 120),
        "test": (5120, 950, 90),
    }
    num_ctx, num_predict, timeout = budgets[normalized_kind]
    exact_source = (
        work_units.integration_source
        if normalized_kind in {"define", "integrate"}
        else work_units.test_anchor_source
    )
    collection_contract = ""
    if _objective_requires_validation_result_collection(objective):
        collection_contract = (
            " The helper receives validation-result dictionaries directly, not ProjectEditApplyResult or another "
            "wrapper object, and returns a list of individual human-readable failure lines, not a joined report "
            "string. Use precise built-in collection annotations equivalent to list[dict[str, object]] and "
            "list[str]. Exclude entries whose ok value is true. The integration function must pass its validation "
            "collection to the helper."
        )
    task_instructions = {
        "define": (
            f"Return only one complete top-level function named {work_units.helper_name}. "
            "Give it a useful docstring and type-aware interface. It must implement the requested behavior "
            "without imports, placeholders, ellipses, or unrelated helpers. Use built-in list and dict "
            "annotations rather than typing.List or typing.Dict. Do not use f-strings; use str(), concatenation, "
            "or format() so dictionary-key quotes cannot corrupt the generated source."
            + collection_contract
        ),
        "integrate": (
            f"Return a complete replacement for {work_units.integration_symbol}. Preserve its signature, "
            f"docstring, and unrelated behavior, and make the smallest edit that calls {work_units.helper_name}. "
            "Do not add imports or any other function."
            + collection_contract
        ),
        "test": (
            f"Return one complete unittest method whose name starts with test_. Directly exercise "
            f"{work_units.helper_name} with focused success and failure-shaped inputs. Use the existing test style, "
            "but do not include a class wrapper, imports, placeholders, or unrelated tests. Your first non-whitespace "
            "text must be def test_ and the response must contain exactly that one method."
        ),
    }[normalized_kind]
    prompt = f"""Exact existing source boundary:
```python
{exact_source}
```

User objective:
{objective}

Approved implementation plan:
{_trim_text(approved_plan, 3500)}

Dependency source produced by an earlier bounded worker:
```python
{dependency_source or '(none)'}
```

Bounded task:
{task_instructions}

Return raw Python source only, with no JSON, Markdown fences, or explanation.
The source must parse independently after dedenting. You do not own files, imports, composition, or writes.
"""
    return ProjectEditPromptStage(
        key=f"leaf_{normalized_kind}_{attempt}",
        label=f"Generating bounded {normalized_kind} work unit ({attempt}/2)",
        system_prompt=(
            "You are a bounded Python code subagent. Produce only the requested leaf source. "
            "The deterministic integrator owns files, imports, composition, and validation."
        ),
        user_prompt=prompt,
        model_tier="local_code",
        num_ctx=num_ctx if profile in {"micro", "small"} else max(num_ctx, 6144),
        num_predict=num_predict,
        timeout=timeout,
        no_progress_seconds=15,
        prefer_coder=True,
        coder_preference=profile,
        response_format="",
    )


def _format_candidate_line(item: dict[str, Any]) -> str:
    name = item.get("name") or item.get("symbol") or item.get("label") or "(unnamed)"
    kind = item.get("kind") or item.get("type") or ""
    path = item.get("path") or item.get("file") or ""
    line = item.get("line") or item.get("lineno") or ""
    summary = str(item.get("summary") or item.get("signature") or item.get("text") or "")
    location = f"{path}:{line}" if path and line else str(path or "")
    parts = [str(name)]
    if kind:
        parts.append(f"kind={kind}")
    if location:
        parts.append(f"location={location}")
    if summary:
        parts.append(f"summary={_trim_text(summary, 220)}")
    symbols = item.get("symbols") or []
    symbol_names = [
        str(symbol.get("name") if isinstance(symbol, dict) else symbol).strip()
        for symbol in symbols[:8]
    ]
    symbol_names = [name for name in symbol_names if name]
    if symbol_names:
        parts.append(f"symbols={', '.join(symbol_names)}")
    return "- " + " | ".join(parts)


def _compact_discovery_evidence(plan: ProjectEditPlan) -> str:
    discovery = dict(plan.discovery or {})
    lines = [
        f"Active path: {plan.active_path or '(none)'}",
        f"Target confidence: {discovery.get('confidence') or 'unknown'}",
    ]
    best = discovery.get("best_target")
    if isinstance(best, dict) and best:
        lines.append("Best target:")
        lines.append(_format_candidate_line(best))
    candidates = [item for item in discovery.get("candidates") or [] if isinstance(item, dict)]
    if candidates:
        lines.append("Top candidates:")
        for item in candidates[:5]:
            lines.append(_format_candidate_line(item))
    if not best and not candidates:
        context = _trim_text(plan.discovery_context, 1800)
        if context:
            lines.append("Discovery context:")
            lines.append(context)
    return "\n".join(lines)


def render_grounded_project_edit_handoff(
    plan: ProjectEditPlan,
    *,
    rejected_plan_errors: list[str] | None = None,
) -> str:
    """Render a deterministic handoff when model planning is absent or ungrounded."""

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    target_path = str(best_target.get("path") or plan.active_path or "").strip()
    confidence = str(discovery.get("confidence") or "unknown")
    requires_patch = _project_edit_requires_patch(plan.prompt)
    generated_artifact = discovery.get("evidence_mode") == "generated_artifact_scope"
    planned_files = [] if generated_artifact else [target_path] if target_path else []
    roots = [Path(str(root)) for root in discovery.get("project_roots") or [] if str(root).strip()]
    if target_path and re.search(r"\b(test|tests|unittest|coverage)\b", plan.prompt, flags=re.IGNORECASE):
        for root in roots:
            test_path = root / "tests" / f"test_{Path(target_path).stem}.py"
            if test_path.is_file():
                planned_files.append(str(test_path))
                break
    lines = [
        "Implementation Plan",
        f"Objective: {plan.prompt}",
        f"Mutation requested: {'yes, generate a preview after approval' if requires_patch else 'no'}.",
        (
            f"Generated-artifact project scope: {target_path}."
            if generated_artifact
            else f"Best evidence-backed target: {target_path or '(no target established)' }."
        ),
        f"Target confidence: {confidence}.",
        "Existing symbols and behavior to reuse or inspect:",
        _compact_discovery_evidence(plan),
        "Proposed changes:",
        f"- {'Generate the smallest focused implementation and matching tests for the stated objective.' if requires_patch else 'Return the evidence-backed analysis without producing a patch.'}",
        "Planned files: " + (
            "selected after approval by a validated dependency-ordered artifact manifest"
            if generated_artifact
            else ", ".join(planned_files) if planned_files else "not established"
        ),
        f"Next stage after approval: {'generate a focused patch preview' if requires_patch else 'return the evidence-backed analysis'}.",
        "Completion gates: parse and compile changed Python; account for imports; run focused tests; "
        "verify host/UI boundaries; leave no unresolved required gap.",
        "Plan self-check: target evidence is present, requested tests are included, file scope is explicit, "
        "and implementation remains deferred until approval.",
        "Approval scope: approval permits code generation and diff preview only; it does not write files.",
    ]
    if rejected_plan_errors:
        lines.append("Planner output was replaced because it failed the grounded handoff contract.")
    if not target_path or confidence not in {"high", "medium"}:
        lines.append("Blocker: continue project search before mutation until a supported target is established.")
    return "\n".join(lines)


def _focused_project_edit_source_context(plan: ProjectEditPlan, *, max_chars: int) -> str:
    """Return ranked source excerpts from the index or a bounded explicit target."""

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    target_path = Path(str(best_target.get("path") or plan.active_path or ""))
    if target_path.suffix.lower() != ".py":
        return ""
    roots = [Path(str(root)) for root in discovery.get("project_roots") or [] if str(root).strip()]
    paths = [target_path]
    if target_path.is_file():
        split_prefixes = {
            target_path.stem,
            target_path.stem.removesuffix("_service"),
        }
        split_modules = sorted({
            path
            for prefix in split_prefixes
            for path in target_path.parent.glob(f"{prefix}_part_*.py")
        })
        paths.extend(path for path in split_modules if path not in paths)
    for item in discovery.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        candidate_path = Path(str(item.get("path") or ""))
        if candidate_path.suffix.lower() == ".py" and candidate_path not in paths:
            paths.append(candidate_path)
    for root in roots:
        test_path = root / "tests" / f"test_{target_path.stem}.py"
        if test_path not in paths:
            paths.append(test_path)
        break
    paths = paths[:8]

    raw_terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", plan.prompt or "")
    terms: set[str] = set()
    ignored = {
        "add", "agent", "apply", "changes", "concise", "coverage", "dictionaries", "edit",
        "focused", "function", "human", "named", "only", "preview", "produce", "project",
        "readable", "reported", "result", "returns", "reusable", "reuse", "service",
        "unittest", "where",
    }
    for raw in raw_terms:
        for term in raw.lower().split("_"):
            if len(term) >= 4 and term not in ignored:
                terms.add(term)
    terms.update({"validation", "failure", "error", "report"})

    from tech_connector.services.file_index_service import file_index_service

    ranked: list[tuple[int, str, int, str]] = []
    source_headers: list[tuple[str, str]] = []
    for path in paths:
        snapshot = file_index_service.get_file_snapshot(str(path), symbol_limit=500)
        if snapshot is None or not (
            list(snapshot.get("symbols") or [])
            or list(snapshot.get("imports") or [])
        ):
            snapshot = file_index_service.get_bounded_python_snapshot(
                str(path),
                project_roots=[str(root) for root in roots],
                symbol_limit=500,
            )
        if snapshot is None:
            continue
        indexed_path = str(snapshot.get("path") or path)
        header = _compact_indexed_import_context(list(snapshot.get("imports") or []))
        if header and len(header) <= 1800:
            source_headers.append((indexed_path, header))
        for symbol in snapshot.get("symbols") or []:
            if str(symbol.get("kind") or "").lower() not in {
                "function", "async_function", "method", "async_method", "class"
            }:
                continue
            segment = str(symbol.get("source") or "")
            name = str(symbol.get("name") or "")
            lowered_name = name.lower()
            lowered_segment = segment.lower()
            score = sum(8 for term in terms if term in lowered_name)
            score += sum(min(lowered_segment.count(term), 3) for term in terms)
            if terms.intersection({"error", "failure", "report", "validation"}) and any(
                marker in lowered_name for marker in ("format", "render", "report", "summarize")
            ):
                score += 12
            if Path(indexed_path) != target_path:
                score += 2
            if score:
                ranked.append((score, indexed_path, int(symbol.get("start_line") or 1), segment))

    lines: list[str] = []
    included_test_excerpts = 0
    included_symbol_blocks = 0
    included_by_path: dict[str, int] = {}
    for _score, path, line, segment in sorted(ranked, key=lambda item: (-item[0], item[1], item[2])):
        is_test_excerpt = _is_test_path(Path(path))
        if is_test_excerpt and included_test_excerpts >= 1:
            continue
        if included_by_path.get(path, 0) >= 2:
            continue
        excerpt = segment if len(segment) <= 1800 else _trim_text(segment, 1800)
        block = f"File: {path}:{line}\n```python\n{excerpt}\n```"
        if lines and len("\n\n".join(lines + [block])) > max_chars:
            continue
        lines.append(block)
        included_symbol_blocks += 1
        included_by_path[path] = included_by_path.get(path, 0) + 1
        if is_test_excerpt:
            included_test_excerpts += 1
        if included_symbol_blocks >= 10:
            break
    for path, header in source_headers:
        block = f"Import summary: {path}\n```python\n{header}\n```"
        if not lines or len("\n\n".join(lines + [block])) <= max_chars:
            lines.append(block)
    return _trim_text("\n\n".join(lines), max_chars)


def build_project_edit_model_stages(plan: ProjectEditPlan) -> list[ProjectEditPromptStage]:
    """Build smaller LLM stages so large code edits do not rely on one huge call."""

    from tech_connector.services.ollama_resource_service import choose_project_edit_coder_profile

    objective = plan.prompt
    evidence_targets = [
        item
        for item in (plan.discovery.get("candidates") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    objective_lower = objective.lower()
    mentioned_target_count = len({
        str(item.get("path"))
        for item in evidence_targets
        if Path(str(item.get("path"))).name.lower() in objective_lower
    })
    coder_profile = choose_project_edit_coder_profile(
        prompt=objective,
        target_count=max(1, mentioned_target_count),
    )
    patch_budgets = {
        "micro": (5120, 1100, 120, 18),
        "small": (6144, 1350, 135, 20),
        "standard": (7168, 1550, 165, 22),
        "quality": (8192, 1800, 210, 25),
    }
    patch_ctx, patch_predict, patch_timeout, patch_no_progress = patch_budgets.get(
        coder_profile,
        patch_budgets["micro"],
    )
    compact_discovery = _compact_discovery_evidence(plan)
    context_limits = {
        "micro": (1600, 800, 450, 4500),
        "small": (2200, 1100, 650, 5500),
        "standard": (2200, 1000, 650, 5200),
        "quality": (3800, 1800, 1200, 7500),
    }
    discovery_limit, adaptive_limit, expert_limit, source_limit = context_limits.get(
        coder_profile,
        context_limits["small"],
    )
    discovery = _trim_text(plan.discovery_context, discovery_limit)
    adaptive = _trim_text(render_code_agent_adaptive_plan(plan.adaptive_plan), adaptive_limit)
    experts = _trim_text(render_code_agent_expert_context(plan.domain_experts), expert_limit)
    focused_source = _focused_project_edit_source_context(plan, max_chars=source_limit)
    planning_source = _trim_text(focused_source, 4000)
    target_path = str((plan.discovery.get("best_target") or {}).get("path") or plan.active_path or "")
    common_system = (
        "You are a senior Python/PySide/Maya/Unreal tools engineer inside Tech Connector. "
        "Use only the supplied project evidence. Reuse existing functions, classes, and helpers. "
        "Do not invent files, APIs, imports, attributes, signatures, or call sites. Resolve required "
        "symbols lazily from generated/current code, indexed internal code, plugin/catalog source, then "
        "installed or official API evidence. Search only a specifically named unresolved gap. Every "
        "external call needs evidence for its exact qualified owner, callable member, and signature; "
        "module importability alone is not evidence that a member exists. Never emit speculative code "
        "for an unresolved gap. Work iteratively: implement what is evidenced, "
        "identify gaps, resolve them from project patterns or authoritative APIs, bridge them with real code, "
        "then validate and repeat. Completion requires working behavior, not a plausible-looking patch. "
        "During planning, never emit code, pseudocode, code fences, or replacement bodies."
    )
    quick_plan_prompt = f"""Focused exact source excerpts:
{planning_source or '(no source excerpt could be resolved)'}

User objective:
{objective}

Compact target evidence:
{compact_discovery}

Selected expert lenses:
{experts or '(none)'}

Stage task:
Create an approval-ready implementation plan. Do not emit XML patches or implementation code.
When the request asks for a change, including preview-only changes, plan patch generation rather than a search-only answer.
Use exact files and existing symbol names from the evidence. Do not describe behavior as "likely" or inferred.
Keep the response under 450 words. Describe signatures and behavior in prose only.
Before returning, compare the proposed changes with the objective and evidence. Resolve contradictory file scope,
unsupported symbols, missing tests, and any claim that conflicts with another section.

Return exactly these prose sections:
Intent:
Evidence-backed targets:
Existing symbols to reuse:
Proposed changes:
Tests and verification:
Blockers:
Plan self-check:
Approval scope:
"""
    patch_prompt = f"""Focused exact source excerpts:
{focused_source or '(no source excerpt could be resolved)'}

User objective:
{objective}

Chosen target:
{target_path or '(none)'}

Focused target-discovery evidence:
{discovery}

Selected expert lenses:
{experts or '(none)'}

Adaptive execution contract:
{adaptive}

Stage task:
Produce the smallest safe patchable implementation that completes the objective, or explicitly stop with a blocker.

Preview contract:
- A preview still requires a complete structured change payload; the application will not write it until the user approves.
- "Do not apply" means emit a patch preview without touching files. It does not mean return an empty changes list.

Rules:
- Reuse the original project function rather than duplicating it.
- Use project-local classes/helpers/patterns when evidence shows they fit.
- Keep changes narrow and testable.
- Give new public functions/classes clear domain names and type-aware interfaces. Document each public callable with a behavioral summary, one `:param name:` field per public parameter, and `:return:` whenever it returns a value.
- Account for every new import. Use only standard-library, installed, project-local, or explicitly host-provided modules.
- Add or update focused unittest tests that prove the requested behavior and failure handling and can run without a live DCC by mocking host boundaries.
- Ensure all emitted Python parses and all test imports resolve before claiming completion.
- If target confidence is low or evidence is insufficient, do not invent. Return a blocker report.
- Return exactly one JSON object with this shape and no Markdown fences:
  {{"changes": [{{"action": "replace_symbol", "path": "absolute/or/relative/path.py", "target_symbol": "existing_function_or_Class.method", "original_content": "", "new_content": "complete replacement symbol source"}}], "report": {{"changed": [], "reused": [], "verification": [], "remaining_gaps": [], "requirement_coverage": []}}, "blocked_reason": ""}}
- Prefer action "replace_symbol" for Python edits. Name an exact indexed symbol and provide its complete replacement source; the AST resolver owns exact source matching and indentation.
- For replace_symbol, copy the exact existing symbol from the source excerpt and make the smallest necessary edit. Preserve its docstring, quote style, and unrelated lines.
- To add a new helper, use "insert_before_symbol" with an existing function at the same scope as target_symbol.
- To add a test method, use "insert_after_symbol" with an existing Class.method as target_symbol.
- To add one import without rewriting an import block, use "ensure_import" with the module in target_symbol and the imported name in new_content.
- For non-Python files, use replace_text/insert_before_text/insert_after_text with an exact, unique source excerpt in target_symbol. These actions are language-neutral and never interpret the anchor as a Python symbol.
- Multiple operations on one file are composed transactionally in list order.
- Use action "create" only for clearly required new files; set target_symbol and original_content to empty strings and place the full file in new_content.
- Use action "modify" only when no symbol boundary fits; copy original_content exactly from supplied excerpts. Never use ellipses.

Required report after patch tags:
1. What was changed.
2. Existing systems reused.
3. Verification to run.
4. Static vs runtime verification.
5. Rollback path.
6. Remaining gaps, if any; do not claim completion while a required gate is unverified.
"""
    stages = [
        ProjectEditPromptStage(
            key="target_selection_plan",
            label="Selecting target and first implementation plan",
            system_prompt=common_system,
            user_prompt=quick_plan_prompt,
            model_tier="local_plan",
            num_ctx=4096,
            num_predict=550,
            timeout=180,
            no_progress_seconds=25,
            prefer_coder=False,
        )
    ]
    if (
        _project_edit_requires_patch(objective)
        or _project_edit_requests_new_artifact_plan(objective)
    ):
        stages.append(
            ProjectEditPromptStage(
                key="patch_generation",
                label="Generating patchable code changes",
                system_prompt=common_system,
                user_prompt=patch_prompt,
                model_tier="local_code",
                num_ctx=patch_ctx,
                num_predict=patch_predict,
                timeout=patch_timeout,
                no_progress_seconds=patch_no_progress,
                prefer_coder=True,
                coder_preference=coder_profile,
                response_format=PROJECT_EDIT_CHANGE_SCHEMA,
            )
        )
    return stages


def build_project_edit_repair_stage(
    plan: ProjectEditPlan,
    candidate_response: str,
    validation_failures: list[str],
    *,
    attempt: int,
    approved_plan: str = "",
) -> ProjectEditPromptStage:
    """Build a focused repair pass from deterministic candidate failures."""

    from tech_connector.services.ollama_resource_service import choose_project_edit_coder_profile

    failure_text = "\n".join(f"- {item}" for item in validation_failures) or "- Candidate validation failed."
    syntax_reset = any(
        marker in str(item).lower()
        for item in validation_failures
        for marker in ("syntax", "did not parse", "unterminated", "eol while scanning", "f-string")
    )
    implementation_reset = any(
        marker in str(item).lower()
        for item in validation_failures
        for marker in ("requested public symbols", "cannot import its requested implementation from itself")
    )
    completion_focus = any(
        marker in str(item).lower()
        for item in validation_failures
        for marker in ("need useful docstrings", "focused test file")
    )
    repair_strategy = (
        "Implementation reset: discard the entire rejected changes list. Define every missing requested symbol as real "
        "source using insert_before_symbol or insert_after_symbol anchored to an existing symbol. Wire the definition "
        "into the approved existing behavior, update the focused test import, and add the requested test. Never import "
        "a requested symbol from the module in which it is being defined."
        if implementation_reset
        else
        "Syntax reset: discard every candidate new_content value for the affected Python file. "
        "Re-copy each affected existing symbol from the exact source excerpt, preserve its quote style, "
        "and reapply only the requested behavior change."
        if syntax_reset
        else
        "Completion focus: preserve all passing operations. Add a useful docstring directly to each named public "
        "callable reported by the gate. For missing test coverage, include an operation on the existing focused test "
        "file, import the requested public symbol from its owner module, and add assertions for success and failure cases."
        if completion_focus
        else "Preserve candidate operations that already satisfy the gates; replace only failing operations and dependencies."
    )
    coder_profile = choose_project_edit_coder_profile(
        prompt=plan.prompt,
        repair_attempt=attempt,
    )
    repair_budgets = {
        "small": (5632, 1150, 105, 18, 9000),
        "standard": (6144, 1300, 135, 20, 10000),
        "quality": (7168, 1500, 210, 22, 11000),
    }
    repair_ctx, repair_predict, repair_timeout, repair_no_progress, candidate_limit = repair_budgets.get(
        coder_profile,
        repair_budgets["quality"],
    )
    repair_source_limits = {"small": 5000, "standard": 6000, "quality": 7000}
    focused_source = _focused_project_edit_source_context(
        plan,
        max_chars=repair_source_limits.get(coder_profile, 7000),
    )
    candidate_context = (
        "(discarded because the candidate failed a core implementation or syntax contract)"
        if implementation_reset or syntax_reset
        else _trim_text(candidate_response, candidate_limit)
    )
    prompt = f"""Original user objective:
{plan.prompt}

User-approved implementation plan:
{_trim_text(approved_plan, 5000) if approved_plan else '(approved plan unavailable; follow the grounded objective and source evidence)'}

Current exact source excerpts:
{focused_source or '(no exact source excerpt was resolved)'}

Deterministic quality failures:
{failure_text}

Repair strategy:
{repair_strategy}

Rejected candidate response:
{candidate_context}

Repair task:
Return a corrected, complete replacement response. Reuse only evidenced project APIs and paths.
Return one valid JSON change object, fixing every reported syntax, import, naming, docstring, and test-coverage issue.
Even when the user requested preview-only or said not to apply changes, emit a non-empty changes list; do not write files.
Focus only on the listed failures and their direct dependencies.
Include focused tests for behavior changes. Do not claim success for checks that were not represented in the patch.
The response must be exactly one JSON object with keys changes, report, and blocked_reason, with no Markdown or prose.
Use exact original_content text from the source excerpts. Never use ellipses, simulated bodies, or placeholder comments.
When a prior failure says an original block did not match, switch that change to replace_symbol with an exact existing target_symbol.
When a target symbol is new and does not exist yet, use insert_before_symbol or insert_after_symbol anchored to an existing symbol instead.
Use a bare function name for top-level target_symbol values and Class.method only for methods nested in a class.
Mentally compile every new_content string. Avoid quote delimiters that conflict with quotes inside f-string expressions.
Update the focused test import block when a new public service symbol is used by name.
If a required fact remains unknown, return an empty changes list and put the exact missing evidence in blocked_reason.
"""
    return ProjectEditPromptStage(
        key=f"quality_repair_{attempt}",
        label=f"Repairing implementation quality failures ({attempt}/5)",
        system_prompt=(
            "You are the final code-quality repair engineer. Produce importable, test-backed project code. "
            "Never replace an unresolved capability with a guessed function or placeholder implementation. "
            "A requested new symbol must be defined in its owner module, never self-imported."
        ),
        user_prompt=prompt,
        model_tier="local_code",
        num_ctx=repair_ctx,
        num_predict=repair_predict,
        timeout=repair_timeout,
        no_progress_seconds=repair_no_progress,
        prefer_coder=True,
        coder_preference=coder_profile,
        response_format=PROJECT_EDIT_CHANGE_SCHEMA,
    )


def _infer_code_agent_host(prompt: str, discovery: dict[str, Any], active_path: str | None) -> str:
    text = " ".join(
        [
            str(prompt or ""),
            str(active_path or ""),
            " ".join(str(root) for root in discovery.get("project_roots") or []),
            str((discovery.get("best_target") or {}).get("path") or ""),
        ]
    ).lower().replace("\\", "/")
    if "maya" in text or "cmds" in text or "/maya_tools/" in text:
        return "maya"
    if "unreal" in text or "blueprint" in text or "/unreal" in text:
        return "unreal"
    if "blender" in text or "/blender" in text:
        return "blender"
    if "houdini" in text:
        return "houdini"
    return "python"


def select_code_agent_experts(
    prompt: str,
    *,
    discovery: dict[str, Any] | None = None,
    active_path: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Select existing domain experts that should advise a project code edit."""

    discovery = dict(discovery or {})
    host = _infer_code_agent_host(prompt, discovery, active_path)
    expert_prompt = " ".join(
        [
            str(prompt or ""),
            str(active_path or ""),
            str((discovery.get("best_target") or {}).get("path") or ""),
            " ".join(str(item.get("path") or "") for item in discovery.get("candidates") or [] if isinstance(item, dict)),
        ]
    )
    decision = {
        "route": "code_edit",
        "intent_category": "project_edit",
        "host": host,
        "mutation_scope": "code_change",
        "provider": "project_index",
    }
    try:
        from tech_connector.services.domain_expert_service import select_domain_experts

        return select_domain_experts(expert_prompt, decision, limit=limit)
    except Exception:
        return []


def build_project_edit_agent_request(
    prompt: str,
    *,
    active_path: str | None = None,
    limit: int = 8,
) -> ProjectEditPlan:
    """Build the grounded edit request sent to the coding model."""

    from tech_connector.services.project_service import (
        build_project_edit_target_prompt,
        discover_edit_targets,
        format_edit_target_context,
    )

    from tech_connector.services.prompt.artifact_contract_service import restricts_live_mutation

    generated_artifact = (
        _project_edit_requires_patch(prompt)
        or _project_edit_requests_new_artifact_plan(prompt)
    ) and restricts_live_mutation(prompt)
    discovery = (
        _generated_artifact_project_discovery(prompt, active_path=active_path)
        if generated_artifact
        else _build_explicit_active_edit_discovery(
            prompt,
            active_path=active_path,
            limit=limit,
        )
    )
    if discovery is None:
        try:
            discovery = discover_edit_targets(prompt, active_path=active_path, limit=limit)
        except Exception as exc:
            discovery = _fallback_project_edit_discovery(
                prompt,
                active_path=active_path,
                error=exc,
            )
    discovery_context = format_edit_target_context(discovery)
    if not generated_artifact and _project_edit_needs_deep_intelligence(prompt, discovery):
        intelligence_packet = _build_project_edit_intelligence_packet(
            prompt,
            active_path=active_path,
            limit=limit,
        )
    else:
        intelligence_packet = _lightweight_project_edit_intelligence_packet(
            prompt,
            discovery,
        )
    adaptive_plan = build_code_agent_adaptive_plan(
        prompt,
        discovery=discovery,
        active_path=active_path,
        intelligence_packet=intelligence_packet,
    )
    domain_experts = select_code_agent_experts(
        prompt,
        discovery=discovery,
        active_path=active_path,
    )
    model_prompt = build_project_edit_target_prompt(
        question=prompt,
        discovery_context=discovery_context,
        active_path=None if generated_artifact else active_path,
        generated_artifact=generated_artifact,
        live_tree_mutation_allowed=not generated_artifact,
    )
    adaptive_section = render_code_agent_adaptive_plan(adaptive_plan)
    if adaptive_section:
        model_prompt = f"{model_prompt}\n\n{adaptive_section}\n"
    expert_section = render_code_agent_expert_context(domain_experts)
    if expert_section:
        model_prompt = f"{model_prompt}\n\n{expert_section}\n"
    intelligence_section = _render_project_edit_intelligence_packet(intelligence_packet)
    if intelligence_section:
        model_prompt = f"{model_prompt}\n\n{intelligence_section}\n"
    return ProjectEditPlan(
        prompt=prompt,
        active_path=active_path or "",
        discovery=discovery,
        discovery_context=discovery_context,
        intelligence_packet=intelligence_packet,
        adaptive_plan=adaptive_plan,
        domain_experts=domain_experts,
        success_contract=list(adaptive_plan.get("success_contract") or []),
        model_prompt=model_prompt,
        stages=[
            _stage("request", "Accepted project edit request"),
            _stage("code_intelligence", "Built IDE-style code intelligence packet"),
            _stage("target_discovery", "Gathered indexed target evidence"),
            _stage("expert_selection", "Selected code and domain expert lenses"),
            _stage("adaptive_planning", "Built objective-to-output code plan"),
            _stage("planning", "Prepared grounded coding-model prompt"),
        ],
    )


def _line_delta(before: str, after: str) -> str:
    before_lines = len((before or "").splitlines())
    after_lines = len((after or "").splitlines())
    delta = after_lines - before_lines
    return f"{before_lines} -> {after_lines} lines, delta {delta:+d}"


def render_project_edit_agent_report(result: ProjectEditApplyResult) -> str:
    """Render a concise Codex-style report for chat."""

    lines = [
        "Project Edit Agent Report",
        f"Status: {result.status}",
        f"Outcome: {'complete' if result.ok else 'needs attention'}",
        "",
        "Files:",
    ]
    if not result.changes:
        lines.append("- No file changes were applied.")
    for item in result.changes:
        before = item.get("before", "")
        after = item.get("after", "")
        delta = _line_delta(before, after)
        lines.append(f"- {item.get('action')} {item.get('path')} ({delta})")
    if result.change_session_path:
        lines.extend(["", f"Undo session: {result.change_session_path}"])
    if result.validation:
        lines.append("")
        lines.append("Validation:")
        for item in result.validation:
            label = "passed" if item.get("ok") else "failed"
            lines.append(f"- {label}: {item.get('command') or item.get('path')} - {item.get('message')}")
    if result.errors:
        lines.append("")
        lines.append("Warnings / Errors:")
        lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines)
