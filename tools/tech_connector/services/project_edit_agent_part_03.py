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

from tech_connector.services.project_edit_agent_part_02 import (
    _HOST_RUNTIME_MODULES,
    _infer_explicit_runtime_api_requests,
    _runtime_api_paths_in_tree,
    summarize_project_edit_generated_interface,
)


def _requested_pre_side_effect_contract_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Validate request-driven input and result guards around host side effects."""

    prompt_lower = str(request_prompt or "").casefold()
    requires_existing_file = bool(
        re.search(r"\brequir\w*\b[^\n.;]{0,80}\bexisting\b[^\n.;]{0,40}\bfile\b", prompt_lower)
    )
    requires_prevalidation = bool(
        re.search(
            r"\bvalidat\w*\b[^\n.;]{0,120}\bbefore\b[^\n.;]{0,80}\bside effect",
            prompt_lower,
        )
    )
    requires_forward_slashes = bool(
        re.search(
            r"\bnormaliz\w*\b[^\n.;]{0,100}\bforward[- ]slash",
            prompt_lower,
        )
    )
    requires_exactly_one = bool(
        re.search(r"\brequir\w*\s+exactly\s+one\b", prompt_lower)
    )
    if not any((
        requires_existing_file,
        requires_prevalidation,
        requires_forward_slashes,
        requires_exactly_one,
    )):
        return []

    request_fields: dict[str, set[str]] = {}
    for class_node in (
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ):
        fields = {
            statement.target.id
            for statement in class_node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }
        if fields:
            request_fields[class_node.name] = fields

    def dotted_name(node: ast.AST) -> str:
        parts: list[str] = []
        cursor = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            parts.append(cursor.id)
        return ".".join(reversed(parts))

    issues: list[str] = []
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for function in functions:
        host_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and dotted_name(call.func).split(".", 1)[0]
            in _HOST_RUNTIME_MODULES
        ]
        if not host_calls:
            continue
        first_host_line = min(
            int(getattr(call, "lineno", 10**9)) for call in host_calls
        )
        owner_prefix = f"[scope:callable][owner:{function.name}] "
        preceding_nodes = [
            node
            for statement in function.body
            if int(getattr(statement, "lineno", 10**9)) < first_host_line
            for node in ast.walk(statement)
        ]
        if requires_existing_file:
            has_existing_file_guard = any(
                isinstance(node, ast.Call)
                and (
                    (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"exists", "is_file"}
                    )
                    or dotted_name(node.func).endswith(
                        ("os.path.exists", "os.path.isfile")
                    )
                )
                for node in preceding_nodes
            )
            if not has_existing_file_guard:
                issues.append(
                    owner_prefix
                    + "require the requested input file to exist before the "
                    "first host-runtime side effect"
                )
            if any(
                isinstance(node, ast.Call)
                and dotted_name(node.func).endswith(
                    "EditorAssetLibrary.does_asset_exist"
                )
                and node.args
                and "file" in ast.unparse(node.args[0]).casefold()
                for node in ast.walk(function)
            ):
                issues.append(
                    owner_prefix
                    + "do not validate a filesystem source with the host asset "
                    "registry; use only the disk file guard for that input"
                )
        if requires_prevalidation:
            parameter_to_fields: dict[str, set[str]] = {}
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            ):
                if isinstance(argument.annotation, ast.Name):
                    fields = request_fields.get(argument.annotation.id)
                    if fields:
                        parameter_to_fields[argument.arg] = fields
            for parameter_name, fields in parameter_to_fields.items():
                referenced_before = {
                    node.attr
                    for node in preceding_nodes
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == parameter_name
                }
                missing_fields = sorted(fields - referenced_before)
                if missing_fields:
                    issues.append(
                        owner_prefix
                        + "validate or normalize every request field before the "
                        "first host-runtime side effect; missing: "
                        + ", ".join(missing_fields)
                    )
                boolean_fields = {
                    field
                    for field in fields
                    if field.casefold() in {"srgb", "enabled", "disabled", "checked"}
                    or field.casefold().endswith(("_flag", "_enabled"))
                }
                for field in sorted(boolean_fields):
                    field_expression = f"{parameter_name}.{field}"
                    has_boolean_validation = any(
                        isinstance(node, ast.Call)
                        and (
                            (
                                isinstance(node.func, ast.Name)
                                and node.func.id == "isinstance"
                                and len(node.args) >= 2
                                and ast.unparse(node.args[0]) == field_expression
                                and isinstance(node.args[1], ast.Name)
                                and node.args[1].id == "bool"
                            )
                            or (
                                isinstance(node.func, ast.Name)
                                and node.func.id == "bool"
                                and node.args
                                and ast.unparse(node.args[0]) == field_expression
                            )
                        )
                        for node in preceding_nodes
                    )
                    if not has_boolean_validation:
                        issues.append(
                            owner_prefix
                            + f"validate or normalize boolean request field "
                            f"{field_expression} before the first host-runtime "
                            "side effect"
                        )
            callback_parameters = {
                argument.arg
                for argument in (
                    *function.args.posonlyargs,
                    *function.args.args,
                    *function.args.kwonlyargs,
                )
                if "callback" in argument.arg.casefold()
            }
            referenced_names = {
                node.id
                for node in preceding_nodes
                if isinstance(node, ast.Name)
            }
            missing_callbacks = sorted(
                callback_parameters - referenced_names
            )
            if missing_callbacks:
                issues.append(
                    owner_prefix
                    + "validate optional callback inputs before the first "
                    "host-runtime side effect; missing: "
                    + ", ".join(missing_callbacks)
                )
        if requires_forward_slashes:
            normalized_names: set[str] = set()
            for assignment in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                valid_replace = any(
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "replace"
                    and len(child.args) >= 2
                    and isinstance(child.args[0], ast.Constant)
                    and child.args[0].value == "\\"
                    and isinstance(child.args[1], ast.Constant)
                    and child.args[1].value == "/"
                    for child in ast.walk(assignment.value)
                )
                if valid_replace:
                    normalized_names.add(assignment.targets[0].id)
            host_path_assignments = [
                assignment
                for assignment in ast.walk(function)
                if isinstance(assignment, ast.Assign)
                and any(
                    isinstance(target, ast.Attribute)
                    and target.attr.casefold().endswith("_path")
                    for target in assignment.targets
                )
            ]
            for assignment in host_path_assignments:
                assigned_names = {
                    node.id
                    for node in ast.walk(assignment.value)
                    if isinstance(node, ast.Name)
                }
                inline_normalization = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "replace"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "\\"
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "/"
                    for node in ast.walk(assignment.value)
                )
                if not inline_normalization and not (
                    assigned_names & normalized_names
                ):
                    target_names = ", ".join(
                        ast.unparse(target)
                        for target in assignment.targets
                    )
                    issues.append(
                        owner_prefix
                        + f"normalize the value assigned to {target_names} with "
                        '.replace("\\\\", "/") before passing it to the host'
                    )
            if (
                re.search(r"\b(?:host|unreal)\s+package\s+paths?\b", prompt_lower)
                and any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"exists", "is_dir", "is_file"}
                    and "destination" in ast.unparse(node.func.value).casefold()
                    for node in preceding_nodes
                )
            ):
                issues.append(
                    owner_prefix
                    + "host package paths must not be validated as filesystem "
                    "directories; validate their string/package form instead"
                )
        if requires_exactly_one:
            import_execution_lines = [
                int(getattr(call, "lineno", 10**9))
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "import_asset_tasks"
            ]
            if import_execution_lines and any(
                isinstance(node, ast.Attribute)
                and node.attr == "imported_object_paths"
                and int(getattr(node, "lineno", 10**9))
                < min(import_execution_lines)
                for node in ast.walk(function)
            ):
                issues.append(
                    owner_prefix
                    + "read imported object paths only after host import execution"
                )
            path_collection_names = {
                target.id
                for assignment in ast.walk(function)
                if isinstance(assignment, ast.Assign)
                and len(assignment.targets) == 1
                and isinstance(assignment.targets[0], ast.Name)
                and any(
                    isinstance(child, ast.Attribute)
                    and "path" in child.attr.casefold()
                    for child in ast.walk(assignment.value)
                )
                for target in assignment.targets
            }
            exact_count_guard = any(
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name)
                and node.left.func.id == "len"
                and len(node.left.args) == 1
                and (
                    any(
                        isinstance(child, ast.Attribute)
                        and "path" in child.attr.casefold()
                        for child in ast.walk(node.left.args[0])
                    )
                    or (
                        isinstance(node.left.args[0], ast.Name)
                        and node.left.args[0].id in path_collection_names
                    )
                )
                and any(
                    isinstance(comparator, ast.Constant)
                    and comparator.value == 1
                    for comparator in node.comparators
                )
                for node in ast.walk(function)
            )
            if not exact_count_guard:
                issues.append(
                    owner_prefix
                    + "enforce the requested exactly-one returned path contract "
                    "with an explicit len(... ) comparison to 1"
                )
    return sorted(set(issues))


def _host_result_and_redundant_guard_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Require checked host load/save results and reject impossible guards."""

    prompt_lower = str(request_prompt or "").casefold()
    checks_loads = bool(
        re.search(r"\bload(?:s|ed|ing)?\b", prompt_lower)
    )
    checks_saves = bool(
        re.search(r"\bsav(?:e|es|ed|ing)\b", prompt_lower)
    )
    issues: list[str] = []
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def direct_call_path(expression: ast.AST) -> str:
        parts: list[str] = []
        cursor = expression
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name) and parts:
            return ".".join([cursor.id, *reversed(parts)])
        return ""

    explicit_save_paths = list(dict.fromkeys(
        path
        for path in re.findall(
            r"\b((?:unreal|maya(?:\.cmds)?|cmds|bpy|pyfbsdk)"
            r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*\(",
            str(request_prompt or ""),
        )
        if path.rsplit(".", 1)[-1].casefold().startswith("save")
    ))
    generated_calls = [
        (
            function,
            direct_call_path(call.func),
        )
        for function in functions
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
    ]
    for expected_path in explicit_save_paths:
        expected_suffix = ".".join(expected_path.split(".")[-2:]).casefold()
        if any(
            actual_path.casefold() == expected_path.casefold()
            or actual_path.casefold().endswith("." + expected_suffix)
            or actual_path.casefold() == expected_suffix
            for _function, actual_path in generated_calls
            if actual_path
        ):
            continue
        ranked_owners: list[tuple[int, str]] = []
        for function in functions:
            score = 0
            for call in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
            ):
                path = direct_call_path(call.func).casefold()
                leaf = path.rsplit(".", 1)[-1]
                if path.startswith(
                    ("unreal.", "maya.", "cmds.", "bpy.", "pyfbsdk.")
                ):
                    score += 2
                if leaf.startswith(("load", "create", "import", "set_")):
                    score += 3
                if leaf in {"set_editor_property", "modify"}:
                    score += 4
            if function.name == "__init__":
                score -= 3
            ranked_owners.append((score, function.name))
        owner = (
            max(ranked_owners, key=lambda item: item[0])[1]
            if ranked_owners
            else "<module>"
        )
        scope = "callable" if owner != "<module>" else "module"
        issues.append(
            f"[scope:{scope}][owner:{owner}] perform requested host save "
            f"operation `{expected_path}` before returning and check its "
            "boolean result"
        )

    for function in functions:
        owner_prefix = f"[scope:callable][owner:{function.name}] "
        parent_by_id = {
            id(child): parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        bool_locals = {
            target.id
            for assignment in ast.walk(function)
            if isinstance(assignment, ast.Assign)
            and isinstance(assignment.value, ast.Call)
            and isinstance(assignment.value.func, ast.Name)
            and assignment.value.func.id == "bool"
            for target in assignment.targets
            if isinstance(target, ast.Name)
        }
        for statement in ast.walk(function):
            if (
                isinstance(statement, ast.If)
                and isinstance(statement.test, ast.Attribute)
                and any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "set_editor_property"
                    and len(call.args) >= 2
                    and isinstance(call.args[1], ast.Constant)
                    and isinstance(call.args[1].value, bool)
                    for call in ast.walk(statement)
                )
            ):
                issues.append(
                    owner_prefix
                    + "set the requested boolean editor property "
                    "unconditionally from the request field so False is applied"
                )
        for guard in (
            node for node in ast.walk(function) if isinstance(node, ast.If)
        ):
            guard_text = ast.unparse(guard.test)
            for local_name in bool_locals:
                if re.search(
                    rf"\b{re.escape(local_name)}\s+is\s+not\s+None\b",
                    guard_text,
                ):
                    issues.append(
                        owner_prefix
                        + f"remove the redundant `{local_name} is not None` "
                        "guard because bool normalization cannot produce None"
                    )

        for assignment in (
            node for node in ast.walk(function) if isinstance(node, ast.Assign)
        ):
            if not (
                checks_loads
                and len(assignment.targets) == 1
                and isinstance(assignment.targets[0], ast.Name)
                and isinstance(assignment.value, ast.Call)
                and isinstance(assignment.value.func, ast.Attribute)
                and (
                    assignment.value.func.attr == "load"
                    or assignment.value.func.attr.startswith("load_")
                )
            ):
                continue
            loaded_name = assignment.targets[0].id
            guarded = any(
                isinstance(candidate, ast.If)
                and int(getattr(candidate, "lineno", 0))
                > int(getattr(assignment, "lineno", 0))
                and re.search(
                    rf"(?:not\s+{re.escape(loaded_name)}\b|"
                    rf"\b{re.escape(loaded_name)}\s+is\s+None\b)",
                    ast.unparse(candidate.test),
                )
                and any(isinstance(child, ast.Raise) for child in ast.walk(candidate))
                for candidate in ast.walk(function)
            )
            if not guarded:
                issues.append(
                    owner_prefix
                    + f"explicitly reject a failed host load when "
                    f"`{loaded_name}` is None before using or returning it"
                )

        if checks_saves:
            for call in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and (
                    node.func.attr == "save"
                    or node.func.attr.startswith("save_")
                )
            ):
                parent = parent_by_id.get(id(call))
                checked_inline = isinstance(parent, (ast.UnaryOp, ast.If))
                assigned_name = ""
                if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
                    target = parent.targets[0]
                    if isinstance(target, ast.Name):
                        assigned_name = target.id
                checked_assignment = bool(
                    assigned_name
                    and any(
                        isinstance(candidate, ast.If)
                        and int(getattr(candidate, "lineno", 0))
                        > int(getattr(parent, "lineno", 0))
                        and assigned_name in ast.unparse(candidate.test)
                        and any(
                            isinstance(child, ast.Raise)
                            for child in ast.walk(candidate)
                        )
                        for candidate in ast.walk(function)
                    )
                )
                if not checked_inline and not checked_assignment:
                    issues.append(
                        owner_prefix
                        + f"check the boolean result of `{call.func.attr}` and "
                        "raise an actionable error when saving fails"
                    )
    return sorted(set(issues))


def _qt_progress_surface_issues(
    tree: ast.AST,
    request_prompt: str,
    path: str = "",
) -> list[str]:
    """Require UI callbacks to expose current, total, and status values."""

    prompt_lower = str(request_prompt or "").casefold()
    qt_module = any(
        (
            isinstance(node, ast.ImportFrom)
            and str(node.module or "").startswith(
                ("PySide", "PyQt", "custom_qt")
            )
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name.startswith(("PySide", "PyQt", "custom_qt"))
                for alias in node.names
            )
        )
        for node in getattr(tree, "body", [])
    )
    if (
        "progress" not in prompt_lower
        or "callback" not in prompt_lower
        or not re.search(r"\b(?:qt|pyside|pyqt|widget|dialog)\b", prompt_lower)
        or not qt_module
    ):
        return []
    issues: list[str] = []
    callback_names: set[str] = set()
    callback_lambda_ids: set[int] = set()
    for call in (
        node for node in ast.walk(tree) if isinstance(node, ast.Call)
    ):
        arguments = [
            (argument, "")
            for argument in call.args
        ] + [
            (keyword.value, str(keyword.arg or ""))
            for keyword in call.keywords
        ]
        for argument, keyword_name in arguments:
            argument_name = (
                argument.id
                if isinstance(argument, ast.Name)
                else argument.attr
                if isinstance(argument, ast.Attribute)
                else ""
            )
            if "progress" not in (
                keyword_name.casefold() + " " + argument_name.casefold()
            ):
                continue
            if isinstance(argument, (ast.Name, ast.Attribute)):
                callback_names.add(argument_name)
            elif isinstance(argument, ast.Lambda):
                callback_lambda_ids.add(id(argument))
    callback_nodes = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in callback_names
        )
        or (isinstance(node, ast.Lambda) and id(node) in callback_lambda_ids)
    ]
    for callback in callback_nodes:
        parameter_offset = (
            1
            if isinstance(callback, (ast.FunctionDef, ast.AsyncFunctionDef))
            and callback.args.args
            and callback.args.args[0].arg in {"self", "cls"}
            else 0
        )
        parameters = [
            argument.arg
            for argument in callback.args.args[
                parameter_offset:parameter_offset + 3
            ]
        ]
        invalid_arity = len(parameters) != 3
        callback_text = ast.unparse(callback)
        missing_parameters = [
            parameter
            for parameter in parameters
            if len(re.findall(rf"\b{re.escape(parameter)}\b", callback_text)) < 2
        ]
        required_methods = {"setRange", "setValue", "setText"}
        called_methods = {
            call.func.attr
            for call in ast.walk(callback)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
        }
        missing_methods = sorted(required_methods - called_methods)
        if invalid_arity or missing_parameters or missing_methods:
            details: list[str] = []
            if invalid_arity:
                details.append(
                    "callback must accept current, total, and message"
                )
            if missing_parameters:
                details.append(
                    "unused callback values: " + ", ".join(missing_parameters)
                )
            if missing_methods:
                details.append(
                    "missing visible updates: " + ", ".join(missing_methods)
                )
            issues.append(
                f"[scope:callable][owner:{callback.name if isinstance(callback, (ast.FunctionDef, ast.AsyncFunctionDef)) else '<lambda>'}] "
                "replace the UI progress callback with a callback that sets "
                "range from total, value from current, and status text from "
                "message; " + "; ".join(details)
            )
    return sorted(set(issues))


def _dynamic_host_api_member_issues(tree: ast.AST) -> list[str]:
    """Reject unverified dynamic member names on host-integrated callables."""

    issues: list[str] = []
    for function in [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _runtime_api_paths_in_tree(node)
    ]:
        dynamic_members = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in {"getattr", "hasattr"}
            and len(call.args) >= 2
            and not (
                isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, str)
            )
        ]
        if dynamic_members:
            issues.append(
                f"[scope:callable][owner:{function.name}] "
                "Host API member names must be exact indexed "
                "members, not dynamically constructed getattr/hasattr names. "
                "Replace the dynamic lookup with an explicit normalized-input "
                "mapping whose values are exact verified enum or API members, "
                "and reject unknown keys"
            )
    return issues


def _official_unreal_call_signature_issues(tree: ast.AST) -> list[str]:
    """Validate Unreal call arity against cached authoritative signatures."""

    try:
        from tech_connector.bridges.unreal.unreal_api_docs import (
            lookup_official_unreal_api,
        )
    except Exception:
        return []

    def direct_api_path(expression: ast.AST) -> str:
        parts: list[str] = []
        cursor = expression
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name) and cursor.id == "unreal" and parts:
            return ".".join(["unreal", *reversed(parts)])
        return ""

    def parameter_contract(signature: str) -> tuple[list[str], int, int] | None:
        match = re.search(r"\((.*)\)\s*(?:→|$)", signature)
        if not match:
            return None
        parameters = [
            value.strip()
            for value in match.group(1).split(",")
            if value.strip()
        ]
        names = [
            re.split(r"\s*(?::|=|\s)\s*", value, maxsplit=1)[0]
            for value in parameters
        ]
        required = sum(
            1
            for value in parameters
            if "=" not in value and not value.startswith(("*", "/"))
        )
        maximum = sum(
            1 for value in parameters if not value.startswith(("*", "/"))
        )
        return names, required, maximum

    issues: list[str] = []
    functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for top_level in tree.body:
        if isinstance(top_level, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append((top_level.name, top_level))
        elif isinstance(top_level, ast.ClassDef):
            functions.extend(
                (f"{top_level.name}.{method.name}", method)
                for method in top_level.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            )

    for owner, function in functions:
        local_api_owners: dict[str, str] = {}
        for assignment in ast.walk(function):
            if not isinstance(assignment, (ast.Assign, ast.AnnAssign)):
                continue
            value = assignment.value
            if not isinstance(value, ast.Call):
                continue
            called_path = direct_api_path(value.func)
            if not called_path:
                continue
            evidence = lookup_official_unreal_api(called_path)
            return_match = re.search(
                r"→\s*([A-Za-z_][A-Za-z0-9_]*)",
                str((evidence or {}).get("signature") or ""),
            )
            if not return_match:
                continue
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    local_api_owners[target.id] = (
                        f"unreal.{return_match.group(1)}"
                    )

        for call in [
            node for node in ast.walk(function) if isinstance(node, ast.Call)
        ]:
            api_path = direct_api_path(call.func)
            if (
                not api_path
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in local_api_owners
            ):
                api_path = (
                    f"{local_api_owners[call.func.value.id]}.{call.func.attr}"
                )
            if not api_path:
                continue
            evidence = lookup_official_unreal_api(api_path)
            signature = str((evidence or {}).get("signature") or "")
            if not evidence or not evidence.get("authoritative_signature"):
                continue
            contract = parameter_contract(signature)
            if contract is None:
                continue
            parameter_names, minimum, maximum = contract
            supplied = len(call.args) + len(call.keywords)
            unknown_keywords = sorted(
                keyword.arg
                for keyword in call.keywords
                if keyword.arg
                and keyword.arg not in parameter_names
            )
            if minimum <= supplied <= maximum and not unknown_keywords:
                continue
            detail = (
                f"expects {minimum}..{maximum} argument(s), received {supplied}"
            )
            if unknown_keywords:
                detail += (
                    "; unknown keyword(s): " + ", ".join(unknown_keywords)
                )
            issues.append(
                f"[scope:callable][owner:{owner}] {api_path} {detail}. "
                f"Authoritative signature: {signature}"
            )
    return sorted(set(issues))


def _official_unreal_editor_property_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Validate string-based Unreal editor properties against official docs."""

    try:
        from tech_connector.bridges.unreal.unreal_api_docs import (
            lookup_official_unreal_api,
        )
    except Exception:
        return []

    prompt_lower = str(request_prompt or "").casefold()
    owner_candidates = [
        owner
        for token, owner in (
            ("texture", "Texture"),
            ("material", "Material"),
            ("static mesh", "StaticMesh"),
            ("skeletal mesh", "SkeletalMesh"),
        )
        if token in prompt_lower
    ]
    if not owner_candidates:
        return []

    issues: list[str] = []
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        property_calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"set_editor_property", "get_editor_property"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ]
        for call in property_calls:
            accessor = call.func.attr
            literal = str(call.args[0].value)
            snake = re.sub(
                r"(?<!^)(?=[A-Z])",
                "_",
                literal,
            ).casefold()
            member_candidates = list(dict.fromkeys([
                literal.casefold(),
                snake,
            ]))
            evidence = None
            for owner in owner_candidates:
                for member in member_candidates:
                    evidence = lookup_official_unreal_api(
                        f"unreal.{owner}.{member}",
                        timeout=3.0,
                    )
                    if evidence:
                        break
                if evidence:
                    break
            if not evidence:
                getter_name = f"get_{snake}"
                getter_evidence = None
                if accessor == "get_editor_property":
                    for owner in [*owner_candidates, "Object"]:
                        getter_evidence = lookup_official_unreal_api(
                            f"unreal.{owner}.{getter_name}",
                            timeout=3.0,
                        )
                        if getter_evidence:
                            break
                if getter_evidence:
                    issues.append(
                        f"[scope:callable][owner:{function.name}] "
                        f"get_editor_property uses unverified literal `{literal}`; "
                        f"use verified Unreal getter `{getter_name}()`. "
                        f"Authoritative source: "
                        f"{getter_evidence.get('source') or ''}"
                    )
                else:
                    issues.append(
                        f"[scope:callable][owner:{function.name}] {accessor} "
                        f"uses unverified Unreal property literal `{literal}`; "
                        "no authoritative property evidence was found"
                    )
                continue
            canonical = str(
                evidence.get("canonical_qualified_name")
                or evidence.get("qualified_name")
                or ""
            ).rsplit(".", 1)[-1]
            if canonical and canonical != literal:
                issues.append(
                    f"[scope:callable][owner:{function.name}] "
                    f"{accessor} uses `{literal}`, expected the exact "
                    f"official Unreal property `{canonical}`. "
                    f"Authoritative source: {evidence.get('source') or ''}"
                )
    return sorted(set(issues))


def _bridge_query_unreal_api_contract(api_path: str, project_root: str | None) -> bool | None:
    """
    Validate Unreal Python API paths from indexed capability/metadata sources.

    Returns True when an indexed entry matches api_path, False when the index is
    empty for the query, and None when metadata lookup is unavailable.
    """

    if not api_path:
        return None
    try:
        from tech_connector.services.unreal.capability_graph_service import resolve_unreal_graph_item
    except Exception:
        return None

    try:
        lookup = resolve_unreal_graph_item(api_path, project_root=project_root, sync=False)
    except Exception:
        return None

    if not isinstance(lookup, dict) or not lookup.get("success"):
        return None

    lowered_target = api_path.strip().lower()
    candidate_keys = ("functions", "capabilities", "symbols", "python_api")
    candidate_rows: list[dict[str, Any]] = []
    for key in candidate_keys:
        rows = lookup.get(key) or []
        candidate_rows.extend(row for row in rows if isinstance(row, dict))

    if not candidate_rows:
        return None

    for row in candidate_rows:
        values = {
            str(row.get("qualified_name") or "").strip().lower(),
            str(row.get("name") or "").strip().lower(),
            str(row.get("symbol_key") or "").strip().lower(),
            str(row.get("entrypoint") or "").strip().lower(),
        }
        if any(
            value
            and (value == lowered_target or value.startswith(f"{lowered_target}.") or lowered_target.startswith(f"{value}."))
            for value in values
        ):
            return True
    return None


_RUNTIME_API_VALIDATION_CACHE: dict[tuple[str, str], bool | None] = {}


def _prime_runtime_api_validation_cache(
    api_paths: set[str],
    project_root: str | None,
) -> None:
    """Resolve qualified Unreal APIs in one exact indexed lookup pass."""

    unreal_paths = sorted(
        path for path in api_paths if str(path).startswith("unreal.")
    )
    if not unreal_paths:
        return
    try:
        from tech_connector.services.unreal.capability_graph_service import (
            validate_unreal_api_paths,
        )

        resolved = validate_unreal_api_paths(unreal_paths, project_root)
    except Exception:
        resolved = {path: None for path in unreal_paths}
    try:
        from tech_connector.services.symbol_evidence_service import (
            resolve_runtime_api_evidence,
        )

        for path in unreal_paths:
            if resolved.get(path) is True:
                continue
            official = resolve_runtime_api_evidence(
                path,
                project_root=project_root or "",
                allow_official_research=True,
            )
            if official is True:
                resolved[path] = True
    except Exception:
        pass
    root_key = str(Path(project_root).resolve()) if project_root else ""
    for path in unreal_paths:
        _RUNTIME_API_VALIDATION_CACHE[(root_key, path)] = resolved.get(path)


def _resolved_runtime_chain_exists(
    api_path: str,
    *,
    project_root: str | None = None,
) -> bool | None:
    """
    Resolve a runtime dot-chain without guessing.

    Returns:
        True: chain exists in imported runtime module.
        False: runtime is importable and chain is missing.
        None: runtime module unavailable in this environment.
    """

    parts = [part for part in (api_path or "").strip().split(".") if part]
    if len(parts) < 2:
        return None
    root = parts[0]
    root_key = str(Path(project_root).resolve()) if project_root else ""
    cache_key = (root_key, api_path)
    if cache_key in _RUNTIME_API_VALIDATION_CACHE:
        return _RUNTIME_API_VALIDATION_CACHE[cache_key]
    if root in _HOST_RUNTIME_MODULES and project_root:
        try:
            from tech_connector.services.symbol_evidence_service import (
                resolve_runtime_api_evidence,
            )

            evidenced = resolve_runtime_api_evidence(
                api_path,
                project_root=project_root,
                allow_official_research=True,
            )
            if evidenced is not None:
                _RUNTIME_API_VALIDATION_CACHE[cache_key] = evidenced
                return evidenced
        except Exception:
            pass
    if root == "unreal":
        bridged = _bridge_query_unreal_api_contract(api_path, project_root)
        if bridged is not None:
            _RUNTIME_API_VALIDATION_CACHE[cache_key] = bridged
            return bridged

    if root in _HOST_RUNTIME_MODULES:
        module_obj = sys.modules.get(root)
        if module_obj is None:
            return None
    else:
        try:
            module_obj = __import__(root)
        except Exception:
            return None

    current = module_obj
    for part in parts[1:]:
        if not hasattr(current, part):
            return False
        try:
            current = getattr(current, part)
        except Exception:
            return False
    return True


def _invalid_runtime_api_contracts(
    request_prompt: str,
    tree: ast.AST | None = None,
    *,
    project_root: str | None = None,
) -> tuple[list[str], list[str]]:
    """
    Cross-check explicitly requested runtime APIs against live introspection.

    Returns (invalid, unverifiable) paths.
    """

    contracts = set(_infer_explicit_runtime_api_requests(request_prompt))
    if tree is not None:
        contracts.update(_runtime_api_paths_in_tree(tree))
    invalid: list[str] = []
    unverifiable: list[str] = []

    def owned_contract(api_path: str) -> str:
        if tree is None:
            return api_path
        owners: list[str] = []
        for top_level in tree.body:
            if isinstance(
                top_level,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ) and api_path in _runtime_api_paths_in_tree(top_level):
                owners.append(top_level.name)
            elif isinstance(top_level, ast.ClassDef):
                owners.extend(
                    f"{top_level.name}.{method.name}"
                    for method in top_level.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and api_path in _runtime_api_paths_in_tree(method)
                )
        return (
            f"[scope:callable][owner:{owners[0]}] {api_path}"
            if len(owners) == 1
            else api_path
        )

    for api_path in sorted(contracts):
        result = _resolved_runtime_chain_exists(api_path, project_root=project_root)
        if result is True:
            continue
        if result is None:
            unverifiable.append(owned_contract(api_path))
        else:
            invalid.append(owned_contract(api_path))

    return invalid, unverifiable


def _imported_call_api_contracts(
    tree: ast.AST,
    *,
    current_module: str,
    candidate_module_trees: dict[str, ast.Module],
    project_root: str | None = None,
) -> tuple[list[str], list[str]]:
    """Validate calls rooted in imports without guessing missing API members."""

    imports: dict[str, str] = {}
    package_parts = current_module.split(".")[:-1]
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            relative_package = list(package_parts)
            if node.level:
                trim = max(0, node.level - 1)
                relative_package = (
                    relative_package[: len(relative_package) - trim]
                    if trim
                    else relative_package
                )
                module_name = ".".join(
                    [*relative_package, *str(node.module or "").split(".")]
                ).strip(".")
            else:
                module_name = str(node.module or "").strip(".")
            for alias in node.names:
                if alias.name == "*":
                    continue
                imports[alias.asname or alias.name] = ".".join(
                    part for part in (module_name, alias.name) if part
                )

    def expression_chain(node: ast.AST) -> list[str]:
        parts: list[str] = []
        cursor = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            parts.append(cursor.id)
            return list(reversed(parts))
        return []

    def generated_symbol_exists(path: str) -> bool | None:
        matching_module = next(
            (
                module_name
                for module_name in sorted(
                    candidate_module_trees,
                    key=len,
                    reverse=True,
                )
                if path == module_name or path.startswith(module_name + ".")
            ),
            "",
        )
        if not matching_module:
            return None
        remainder = path[len(matching_module):].strip(".").split(".")
        remainder = [part for part in remainder if part]
        if not remainder:
            return True
        current_nodes = list(candidate_module_trees[matching_module].body)
        for index, part in enumerate(remainder):
            found: ast.AST | None = None
            for candidate in current_nodes:
                names: list[str] = []
                if isinstance(candidate, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    names = [candidate.name]
                elif isinstance(candidate, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        candidate.targets
                        if isinstance(candidate, ast.Assign)
                        else [candidate.target]
                    )
                    names = [
                        target.id for target in targets if isinstance(target, ast.Name)
                    ]
                elif isinstance(candidate, ast.Import):
                    names = [
                        alias.asname or alias.name.split(".", 1)[0]
                        for alias in candidate.names
                    ]
                elif isinstance(candidate, ast.ImportFrom):
                    names = [alias.asname or alias.name for alias in candidate.names]
                if part in names:
                    found = candidate
                    break
            if found is None:
                return False
            if index == len(remainder) - 1:
                return True
            if isinstance(found, ast.ClassDef):
                current_nodes = list(found.body)
            else:
                return False
        return True

    def installed_symbol_exists(path: str) -> bool | None:
        parts = path.split(".")
        imported_any_owner = False
        for split_at in range(1, len(parts) + 1):
            module_name = ".".join(parts[:split_at])
            try:
                current: Any = __import__(module_name, fromlist=["*"])
            except Exception:
                continue
            imported_any_owner = True
            for part in parts[split_at:]:
                if not hasattr(current, part):
                    current = None
                    break
                try:
                    current = getattr(current, part)
                except Exception:
                    current = None
                    break
            if current is not None:
                return callable(current)

        # Host-facing internal modules can be source-valid even when importing
        # their package would execute an unavailable DCC dependency. Resolve
        # those symbols from Python source before treating an import failure as
        # evidence that the callable was invented.
        for split_at in range(len(parts) - 1, 0, -1):
            module_parts = parts[:split_at]
            remainder = parts[split_at:]
            for search_root in sys.path:
                root = Path(search_root or Path.cwd())
                source_candidates = (
                    root.joinpath(*module_parts).with_suffix(".py"),
                    root.joinpath(*module_parts, "__init__.py"),
                )
                source_path = next(
                    (candidate for candidate in source_candidates if candidate.is_file()),
                    None,
                )
                if source_path is None:
                    continue
                try:
                    source_tree = ast.parse(
                        source_path.read_text(encoding="utf-8"),
                        filename=str(source_path),
                    )
                except (OSError, UnicodeError, SyntaxError):
                    continue
                current_nodes: list[ast.stmt] = list(source_tree.body)
                for index, part in enumerate(remainder):
                    found = next(
                        (
                            candidate
                            for candidate in current_nodes
                            if isinstance(
                                candidate,
                                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and candidate.name == part
                        ),
                        None,
                    )
                    if found is None:
                        break
                    if index == len(remainder) - 1:
                        return isinstance(
                            found,
                            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                    current_nodes = (
                        list(found.body)
                        if isinstance(found, ast.ClassDef)
                        else []
                    )
                else:
                    return True
                return False
        return False if imported_any_owner else None

    invalid: set[str] = set()
    unresolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = expression_chain(node.func)
        if not chain or chain[0] not in imports:
            continue
        imported_parts = [
            part for part in imports[chain[0]].split(".") if part
        ]
        call_tail = list(chain[1:])
        overlap = 0
        for candidate_overlap in range(
            min(len(imported_parts), len(call_tail)),
            0,
            -1,
        ):
            if (
                imported_parts[-candidate_overlap:]
                == call_tail[:candidate_overlap]
            ):
                overlap = candidate_overlap
                break
        qualified = ".".join([
            *imported_parts,
            *call_tail[overlap:],
        ])
        host_local_call = qualified.split(".", 1)[0] in _HOST_RUNTIME_MODULES
        if host_local_call:
            resolution = _resolved_runtime_chain_exists(
                qualified,
                project_root=project_root,
            )
        else:
            resolution = generated_symbol_exists(qualified)
            if resolution is None:
                resolution = installed_symbol_exists(qualified)
        if resolution is False:
            invalid.add(qualified)
        elif resolution is None and not host_local_call:
            unresolved.add(qualified)
    return sorted(invalid), sorted(unresolved)


def _sanitize_python_candidate_text(source: str) -> str:
    """Normalize generated code snippets before parsing/patch application."""

    text = str(source or "")
    had_trailing_newline = text.endswith(("\n", "\r"))
    text = text.strip()
    if not text:
        return text

    # Strip markdown fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:xml|python|py)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    # Strip model metadata headers.
    text = re.sub(r"(?im)^#\s*file:\s*.*\r?\n", "", text)

    # Remove accidental XML/marker wrappers.
    text = re.sub(r"(?is)^\s*<modify_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?is)^\s*<create_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?s)\n\s*</(?:modify_file|create_file)>\s*$", "", text)
    # In cases where the model returns wrapper tags with no matching ORIGINAL block,
    # keep the innermost replacement body.
    text = re.sub(r"(?is)^.*?<modify_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?is)^.*?<create_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?is)\n\s*</(?:modify_file|create_file)>\s*$", "", text)
    text = re.sub(r"\r", "", text)
    replacement_match = re.search(r"<<<<\s*ORIGINAL.*?\n====\n(.*?)\n>>>>", text, flags=re.IGNORECASE | re.DOTALL)
    if replacement_match:
        text = replacement_match.group(1)
    replacement_only_match = re.search(r"<<<<\s*ORIGINAL(?:\n.*)?\n====\n(.*)", text, flags=re.IGNORECASE | re.DOTALL)
    if replacement_only_match:
        text = replacement_only_match.group(1)
    text = re.sub(r"(?is)<<<<\s*ORIGINAL\b.*?(?:\n|$)", "", text)
    text = re.sub(r"(?is)\n>>>>\s*$", "", text)

    normalized = text.strip()
    return normalized + "\n" if had_trailing_newline and normalized else normalized


def _generated_docstring_contract_issues(
    qualified_name: str,
    node: ast.AST,
) -> list[str]:
    """Return signature-derived documentation gaps for one generated callable."""

    issues: list[str] = []
    if isinstance(node, ast.ClassDef):
        if not _generated_docstring_is_useful(qualified_name, node):
            issues.append(
                f"{qualified_name} needs a concrete behavioral summary"
            )
        docstring = str(ast.get_docstring(node) or "")
        for statement in node.body:
            if not (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            ):
                continue
            field = statement.target.id
            if not re.search(
                rf":param\s+(?:[^:\s]+\s+)?{re.escape(field)}\s*:",
                docstring,
            ):
                issues.append(f"{qualified_name} is missing :param {field}:")
        return issues
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return issues

    arguments = [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    parameter_names = [
        argument.arg
        for argument in arguments
        if argument.arg not in {"self", "cls"}
    ]
    if node.args.vararg is not None:
        parameter_names.append(node.args.vararg.arg)
    if node.args.kwarg is not None:
        parameter_names.append(node.args.kwarg.arg)

    docstring = str(ast.get_docstring(node) or "")
    if not _generated_docstring_is_useful(qualified_name, node):
        issues.append(
            f"{qualified_name} needs a concrete behavioral summary"
        )
    if re.search(
        r"\b(?:supplied to this operation|result produced by|"
        r"request value consumed by(?: the documented operation)?|"
        r"containing the validated inputs for this operation|"
        r"produced after the operation completes successfully|"
        r"the calculated [a-z_ ]+ value)\b",
        docstring,
        flags=re.IGNORECASE,
    ):
        issues.append(
            f"{qualified_name} uses generic parameter or return descriptions"
        )
    if re.search(
        r"(?im)^\s*:return:\s*(?:the\s+)?(?:concrete\s+)?result\.?\s*$"
        r"|\bresult\s+result\b",
        docstring,
    ):
        issues.append(
            f"{qualified_name} uses a generic return description"
        )
    for parameter_name in parameter_names:
        if not re.search(
            rf":param\s+(?:[^:\s]+\s+)?{re.escape(parameter_name)}\s*:",
            docstring,
        ):
            issues.append(
                f"{qualified_name} is missing :param {parameter_name}:"
            )

    class ReturnVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.returns_value = False

        def visit_Return(self, return_node: ast.Return) -> None:
            if (
                return_node.value is not None
                and not (
                    isinstance(return_node.value, ast.Constant)
                    and return_node.value.value is None
                )
            ):
                self.returns_value = True

        def visit_Yield(self, _yield_node: ast.Yield) -> None:
            self.returns_value = True

        def visit_YieldFrom(self, _yield_node: ast.YieldFrom) -> None:
            self.returns_value = True

        def visit_FunctionDef(self, _nested: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(
            self,
            _nested: ast.AsyncFunctionDef,
        ) -> None:
            return

        def visit_Lambda(self, _nested: ast.Lambda) -> None:
            return

    return_visitor = ReturnVisitor()
    for statement in node.body:
        return_visitor.visit(statement)
    if (
        return_visitor.returns_value
        and not re.search(r":returns?\s*:", docstring)
    ):
        issues.append(f"{qualified_name} is missing :return:")
    return issues


def _generated_docstring_is_useful(
    qualified_name: str,
    node: ast.AST,
) -> bool:
    """Return whether a generated callable docstring explains more than its name."""

    docstring = str(ast.get_docstring(node) or "").strip()
    summary = re.split(
        r"(?m)^\s*:(?:param|return|returns|raise|raises|type)\b",
        docstring,
        maxsplit=1,
    )[0].strip()
    callable_name = qualified_name.rsplit(".", 1)[-1]
    if (
        re.search(r"(?:[\\/]|\.py\b)", summary, flags=re.IGNORECASE)
        or re.search(
            r"\b(?:requested (?:behavior|change|feature|implementation)|"
            r"provide [a-z0-9_ ]+ behavior|"
            r"apply [a-z0-9_ ]+ and update only its documented state|"
            r"compute and return the [a-z0-9_ ]+ result|"
            r"store validated [-a-z0-9_ ]+ state and expose|"
            r"unrelated state|surrounding state|"
            r"observable behavior|validation invariants?|state contract|"
            r"behavioral contracts?|preserving validated inputs, state transitions, "
            r"and failure behavior|after validating construction inputs)\b",
            summary,
            flags=re.IGNORECASE,
        )
        or re.match(
            rf"^\s*{re.escape(callable_name)}\s+must\b",
            summary,
            flags=re.IGNORECASE,
        )
    ):
        return False
    words = re.findall(r"[A-Za-z0-9]+", summary)
    if len(words) < 4:
        return False
    name_words = {
        word.casefold()
        for word in re.findall(
            r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+",
            qualified_name.rsplit(".", 1)[-1],
        )
    }
    meaningful_words = {
        word.casefold()
        for word in words
        if word.casefold() not in name_words
    }
    return len(meaningful_words) >= 2


def _generated_source_presentation_issues(
    source: str,
    tree: ast.Module,
) -> list[str]:
    """Return deterministic readability defects in generated Python.

    :param source: complete generated Python source
    :param tree: parsed source tree
    :return: stable presentation issue descriptions
    """

    issues: list[str] = []
    for owner_name, owner in [
        ("<module>", tree),
        *(
            (node.name, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        ),
    ]:
        for index, statement in enumerate(owner.body):
            if (
                index > 0
                and isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                issues.append(
                    f"{owner_name} contains a displaced standalone string literal"
                )

    parent_by_node = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def is_instance_lock(node: ast.AST) -> bool:
        return (
            isinstance(node, (ast.With, ast.AsyncWith))
            and len(node.items) == 1
            and isinstance(node.items[0].context_expr, ast.Attribute)
            and isinstance(node.items[0].context_expr.value, ast.Name)
            and node.items[0].context_expr.value.id == "self"
            and node.items[0].context_expr.attr == "_lock"
        )

    for node in ast.walk(tree):
        if not is_instance_lock(node):
            continue
        parent = parent_by_node.get(id(node))
        while parent is not None:
            if is_instance_lock(parent):
                issues.append("nested redundant self._lock context")
                break
            if isinstance(
                parent,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module),
            ):
                break
            parent = parent_by_node.get(id(parent))

    source_lines = source.splitlines()
    for line in source_lines:
        if len(line) > 100 and not line.lstrip().startswith(("#", "http")):
            issues.append(
                f"line exceeds 100 characters: {line.strip()[:48]}"
            )

    for owner in [
        tree,
        *(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ),
    ]:
        body = getattr(owner, "body", None)
        if not body:
            continue
        expression = body[0]
        if not (
            isinstance(expression, ast.Expr)
            and isinstance(expression.value, ast.Constant)
            and isinstance(expression.value.value, str)
            and int(expression.end_lineno or expression.lineno) > expression.lineno
        ):
            continue
        required_indent = " " * int(expression.col_offset or 0)
        physical_lines = source_lines[
            expression.lineno : int(expression.end_lineno or expression.lineno)
        ]
        if any(
            line.strip() and not line.startswith(required_indent)
            for line in physical_lines
        ):
            name = getattr(owner, "name", "<module>")
            issues.append(f"{name} has inconsistently indented docstring content")
    return sorted(set(issues))


def _incomplete_generated_type_hints(tree: ast.AST) -> list[str]:
    """Return generated callables with missing or invalid annotation surfaces."""

    parent_by_node = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def qualified_name(function: ast.AST) -> str:
        parent = parent_by_node.get(id(function))
        if isinstance(parent, ast.ClassDef):
            return f"{parent.name}.{function.name}"
        return str(function.name)

    def invalid_annotation(
        annotation: ast.AST | None,
        *,
        reject_any: bool = False,
    ) -> bool:
        if annotation is None:
            return True
        if reject_any and any(
            isinstance(child, ast.Name) and child.id == "Any"
            for child in ast.walk(annotation)
        ):
            return True
        if any(
            isinstance(child, ast.Name) and child.id == "callable"
            for child in ast.walk(annotation)
        ):
            return True
        if isinstance(annotation, ast.Tuple):
            return True
        return any(
            isinstance(child, ast.Subscript)
            and isinstance(child.slice, ast.Tuple)
            and any(
                isinstance(element, ast.Tuple)
                for element in child.slice.elts
            )
            for child in ast.walk(annotation)
        )

    failures: list[str] = []
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        arguments = [
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        ]
        if function.args.vararg:
            arguments.append(function.args.vararg)
        if function.args.kwarg:
            arguments.append(function.args.kwarg)
        parent = parent_by_node.get(id(function))
        public_surface = (
            not function.name.startswith("_")
            or (
                function.name == "__init__"
                and isinstance(parent, ast.ClassDef)
                and not parent.name.startswith("_")
            )
        )
        missing_parameters = [
            argument.arg
            for argument in arguments
            if argument.arg not in {"self", "cls"}
            and invalid_annotation(
                argument.annotation,
                reject_any=public_surface
                and argument is not function.args.vararg
                and argument is not function.args.kwarg,
            )
        ]
        reasons: list[str] = []
        if missing_parameters:
            reasons.append("parameters " + "/".join(missing_parameters))
        if invalid_annotation(
            function.returns,
            reject_any=public_surface,
        ):
            reasons.append("return")
        invalid_local_annotations = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.AnnAssign)
            and invalid_annotation(node.annotation)
        ]
        if invalid_local_annotations:
            reasons.append("local annotations")
        untyped_empty_collection_attributes = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, (ast.List, ast.Dict, ast.Set))
            and not getattr(node.value, "elts", None)
            and not getattr(node.value, "keys", None)
            and any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                for target in node.targets
            )
        ]
        if untyped_empty_collection_attributes:
            reasons.append("empty collection attributes")
        if reasons:
            failures.append(
                f"{qualified_name(function)} ({'; '.join(reasons)})"
            )
    return sorted(failures)


def _verified_installed_qt_symbol(name: str) -> bool:
    """Return whether an unresolved name is owned by an installed Qt module."""

    if not str(name).startswith("Q") and name != "Qt":
        return False
    for binding in ("PySide6", "PyQt6", "PyQt5", "PySide2"):
        try:
            if importlib.util.find_spec(binding) is None:
                continue
        except (ImportError, ModuleNotFoundError, ValueError):
            continue
        for suffix in ("QtCore", "QtGui", "QtWidgets", "QtTest"):
            try:
                module = importlib.import_module(f"{binding}.{suffix}")
            except (ImportError, ModuleNotFoundError):
                continue
            if hasattr(module, name):
                return True
    return False


def build_project_edit_function_repair_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    target: dict[str, str],
    validation_errors: list[str],
    objective: str,
    requirements: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Describe one failing callable without handing the worker its whole file."""

    path = str(target.get("path") or "")
    symbol = str(target.get("symbol") or "")
    module_source = next(
        (
            source
            for path_text, _original, source in generated_files
            if Path(path_text).resolve() == Path(path).resolve()
        ),
        "",
    )
    if not path or not symbol or not module_source:
        return {}, ["Function repair target is incomplete or no longer exists."]
    parts = symbol.split(".")
    target_source_override = ""
    try:
        tree = ast.parse(module_source, filename=path)
    except SyntaxError as exc:
        source_lines = module_source.splitlines(keepends=True)
        class_name = parts[0] if len(parts) == 2 else ""
        callable_name = parts[-1]
        active_class = ""
        class_indent = -1
        target_start = -1
        target_end = len(source_lines)
        target_indent = ""
        definition_line = -1
        for line_index, line in enumerate(source_lines):
            stripped = line.lstrip()
            if not stripped:
                continue
            indent_text = line[:len(line) - len(stripped)]
            indent_size = len(indent_text.expandtabs(4))
            class_match = re.match(
                r"class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                stripped,
            )
            if class_match:
                active_class = class_match.group(1)
                class_indent = indent_size
                continue
            if active_class and indent_size <= class_indent:
                active_class = ""
                class_indent = -1
            if not re.match(
                rf"(?:async\s+)?def\s+{re.escape(callable_name)}\s*\(",
                stripped,
            ):
                continue
            if class_name and active_class != class_name:
                continue
            if not class_name and active_class:
                continue
            target_indent = indent_text
            definition_line = line_index
            target_start = line_index
            while (
                target_start > 0
                and source_lines[target_start - 1].lstrip().startswith("@")
                and source_lines[target_start - 1].startswith(target_indent)
            ):
                target_start -= 1
            for following_index in range(line_index + 1, len(source_lines)):
                following = source_lines[following_index]
                if not following.strip():
                    continue
                following_indent = len(following) - len(following.lstrip())
                if following_indent <= len(target_indent):
                    target_end = following_index
                    break
            break
        if target_start < 0 or definition_line < 0:
            return {}, [
                f"Function repair owner does not parse and lexical target "
                f"{symbol} was not found: {exc}"
            ]
        target_source_override = textwrap.dedent(
            "".join(source_lines[target_start:target_end])
        ).strip()
        sanitized_lines = list(source_lines)
        prefix_lines = source_lines[target_start:definition_line + 1]
        replacement_lines = [
            *prefix_lines,
            target_indent + "    pass\n",
        ]
        replacement_lines.extend(
            "\n"
            for _ in range(
                max(0, target_end - target_start - len(replacement_lines))
            )
        )
        sanitized_lines[target_start:target_end] = replacement_lines
        try:
            tree = ast.parse("".join(sanitized_lines), filename=path)
        except SyntaxError as sanitized_exc:
            return {}, [
                f"Function repair target {symbol} could not be isolated from its "
                f"syntax failure: {sanitized_exc}"
            ]

    owner: ast.ClassDef | None = None
    candidates: list[ast.FunctionDef | ast.AsyncFunctionDef]
    if len(parts) == 2:
        owner = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == parts[0]
            ),
            None,
        )
        candidates = [
            node
            for node in (owner.body if owner is not None else [])
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == parts[1]
        ]
    else:
        candidates = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == parts[-1]
        ]
    if len(candidates) != 1:
        return {}, [f"Function repair target must resolve to one callable: {symbol}"]
    node = candidates[0]

    module_imports = [
        ast.get_source_segment(module_source, item) or ast.unparse(item)
        for item in tree.body
        if isinstance(item, (ast.Import, ast.ImportFrom))
    ]
    sibling_nodes = [
        item
        for item in (owner.body if owner is not None else tree.body)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item is not node
    ]
    sibling_symbols = [
        f"{owner.name}.{item.name}" if owner is not None else item.name
        for item in sibling_nodes
    ]
    module_symbols = [
        item.name
        for item in tree.body
        if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    sibling_signatures = [
        ast.unparse(item).splitlines()[0]
        for item in sibling_nodes
        if ast.unparse(item)
    ]
    state_context: list[str] = []
    if owner is not None:
        for item in owner.body:
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "__init__"
            ) or isinstance(item, (ast.Assign, ast.AnnAssign)):
                state_context.append(
                    ast.get_source_segment(module_source, item) or ast.unparse(item)
                )
        for sibling in sibling_nodes:
            for statement in ast.walk(sibling):
                if not isinstance(
                    statement,
                    (ast.Assign, ast.AnnAssign, ast.AugAssign),
                ):
                    continue
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                writes_instance_state = any(
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                    for target_node in targets
                    for child in ast.walk(target_node)
                )
                if not writes_instance_state:
                    continue
                rendered = (
                    ast.get_source_segment(module_source, statement)
                    or ast.unparse(statement)
                )
                if rendered not in state_context:
                    state_context.append(rendered)
    callsite_excerpts: list[str] = []
    all_callsite_excerpts: list[str] = []
    for path_text, _original, candidate_source in generated_files:
        try:
            candidate_tree = ast.parse(candidate_source, filename=path_text)
        except SyntaxError:
            continue
        for callable_node in [
            item
            for item in ast.walk(candidate_tree)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            if path_text == path and callable_node is node:
                continue
            calls_target = any(
                isinstance(child, ast.Call)
                and (
                    isinstance(child.func, ast.Name)
                    and child.func.id == node.name
                    or isinstance(child.func, ast.Attribute)
                    and child.func.attr == node.name
                )
                for child in ast.walk(callable_node)
            )
            if not calls_target:
                continue
            parent_by_id = {
                id(child): parent
                for parent in ast.walk(callable_node)
                for child in ast.iter_child_nodes(parent)
            }
            call_node = next(
                (
                    child
                    for child in ast.walk(callable_node)
                    if isinstance(child, ast.Call)
                    and (
                        isinstance(child.func, ast.Name)
                        and child.func.id == node.name
                        or isinstance(child.func, ast.Attribute)
                        and child.func.attr == node.name
                    )
                ),
                None,
            )
            selected_statements: list[ast.stmt] = []
            if call_node is not None:
                call_statement: ast.AST = call_node
                while not isinstance(call_statement, ast.stmt):
                    call_statement = parent_by_id.get(id(call_statement), call_statement)
                    if call_statement is call_node:
                        break
                if not isinstance(call_statement, ast.stmt):
                    continue
                argument_names = {
                    child.id
                    for argument in call_node.args
                    for child in ast.walk(argument)
                    if isinstance(child, ast.Name)
                }
                for statement in ast.walk(callable_node):
                    if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                        continue
                    if int(getattr(statement, "lineno", 0) or 0) >= int(call_statement.lineno):
                        continue
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    assigned_names = {
                        child.id
                        for target_node in targets
                        for child in ast.walk(target_node)
                        if isinstance(child, ast.Name)
                    }
                    value = statement.value
                    if assigned_names & argument_names and isinstance(
                        value,
                        (ast.Constant, ast.Dict, ast.List, ast.Tuple, ast.Set),
                    ):
                        selected_statements.append(statement)
                selected_statements.extend(
                    statement
                    for statement in ast.walk(callable_node)
                    if isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and int(getattr(statement, "lineno", 0) or 0)
                    < int(call_statement.lineno)
                )
                selected_statements.append(call_statement)
                selected_statements.extend(
                    statement
                    for statement in ast.walk(callable_node)
                    if int(getattr(statement, "lineno", 0) or 0) > int(call_statement.lineno)
                    and (
                        isinstance(statement, ast.Assert)
                        or (
                            isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Call)
                            and isinstance(statement.value.func, ast.Attribute)
                            and statement.value.func.attr.startswith("assert")
                        )
                    )
                )
                selected_statements.sort(key=lambda statement: int(statement.lineno))
                preceding = [
                    statement
                    for statement in selected_statements
                    if int(statement.lineno) < int(call_statement.lineno)
                ][-4:]
                selected_statements = preceding + [
                    statement
                    for statement in selected_statements
                    if int(statement.lineno) >= int(call_statement.lineno)
                ][:3]
            excerpt = "\n".join(
                ast.get_source_segment(candidate_source, statement) or ast.unparse(statement)
                for statement in selected_statements[:6]
            )
            if excerpt:
                callsite_excerpts.append(
                    f"{Path(path_text).name}:{callable_node.name}\n{excerpt}"
                )
                complete_caller = (
                    ast.get_source_segment(candidate_source, callable_node)
                    or ast.unparse(callable_node)
                )
                all_callsite_excerpts.append(
                    f"{Path(path_text).name}:{callable_node.name}\n{complete_caller}"
                )
    failure_text = "\n".join(str(item) for item in validation_errors)
    needles = [Path(path).name.lower(), parts[-1].lower(), symbol.lower()]
    lower_failure = failure_text.lower()
    positions = [
        lower_failure.find(needle)
        for needle in needles
        if needle and lower_failure.find(needle) >= 0
    ]
    if positions:
        position = max(positions)
        relevant_failure = failure_text[max(0, position - 1400): position + 3200]
    else:
        relevant_failure = failure_text[-4600:]
    target_failure_text = "\n".join(
        str(error)
        for error in validation_errors
        if (
            "Generated callables reference undefined names in " in str(error)
            and any(
                owner.strip() in {symbol, parts[-1]}
                for owner in str(error).split(":", 1)[0]
                .split(" in ", 1)[-1]
                .split(",")
            )
        )
    ) or relevant_failure
    forbidden_names = sorted({
        value
        for group in re.findall(
            r"Generated callables reference undefined names in [^:]+:\s*"
            r"([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)",
            target_failure_text,
        )
        for value in (item.strip() for item in group.split(","))
        if value
    })
    forbidden_names.extend(
        value
        for value in re.findall(
            r"NameError:\s+name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] is not defined",
            target_failure_text,
        )
        if value not in forbidden_names
    )
    forbidden_names.extend(
        terminal_name
        for qualified_name in re.findall(
            r"\buses\s+`([A-Za-z_][A-Za-z0-9_.]*)`,\s*expected\b",
            failure_text,
            flags=re.IGNORECASE,
        )
        for terminal_name in [qualified_name.rsplit(".", 1)[-1]]
        if terminal_name not in forbidden_names
    )
    forbidden_names = [
        value
        for value in forbidden_names
        if not (
            value.split(".", 1)[0] in _HOST_RUNTIME_MODULES
            or _verified_installed_qt_symbol(value)
            or (
                value[:1].isupper()
                and re.search(
                    rf"\b{re.escape(value)}\b",
                    str(objective or ""),
                )
            )
        )
    ]
    verified_repair_symbols = sorted(
        {
            name
            for name in re.findall(r"\bQ[A-Za-z0-9_]+\b", failure_text)
            if _verified_installed_qt_symbol(name)
        }
    )
    module_symbols.extend(
        name for name in verified_repair_symbols if name not in module_symbols
    )

    source = (
        target_source_override
        or ast.get_source_segment(module_source, node)
        or str(target.get("source") or "")
    )
    rendered_callable = ast.unparse(node)
    signature = rendered_callable.splitlines()[0] if rendered_callable else ""
    generated_interfaces = [
        summarize_project_edit_generated_interface(path_text, generated_source)
        for path_text, _original, generated_source in generated_files
    ]
    derived_requirements = [
        str(value) for value in requirements or [] if str(value).strip()
    ]
    objective_lower = str(objective or "").lower()
    symbol_lower = symbol.lower()
    if node.name.startswith("test_"):
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
            if value not in {"self", "cls"} and not value.startswith("_")
        )
        if unused_fixtures:
            derived_requirements.append(
                "Consume every constructed fixture through the public API before "
                "assertions; currently unused fixtures: "
                + ", ".join(unused_fixtures)
            )
        if (
            any(term in symbol_lower for term in ("report", "find", "list", "order"))
            and not re.search(
                r"\b(?:raise|raises|reject|error|exception)\b",
                objective_lower,
            )
        ):
            derived_requirements.append(
                "Assert the requested returned value; do not use assertRaises for this observable behavior."
            )
        if (
            any(term in symbol_lower for term in ("missing", "unresolved", "not_found"))
            and any(term in objective_lower for term in ("missing", "unresolved", "not found"))
        ):
            derived_requirements.append(
                "Introduce every expected missing/unresolved identifier through a preceding public input or "
                "mutation call before querying and asserting that identifier."
            )
    if (
        any(term in symbol_lower for term in ("cycle", "loop"))
        and any(term in objective_lower for term in ("cycle", "loop"))
    ):
        derived_requirements.append(
            "Start detection from every unvisited candidate, not only candidates whose initial state excludes "
            "the condition being detected; return the detected structures unless the objective requests an error."
        )
    if (
        any(term in objective_lower for term in ("missing target", "missing dependency", "unresolved"))
        and any(term in symbol_lower for term in ("add", "set", "load", "ingest", "import"))
    ):
        derived_requirements.append(
            "Preserve an input that references an unresolved target so the requested missing-state query can "
            "observe it; validate the owning/source identity separately from the unresolved referenced identity."
        )
    if "require the requested input file to exist before" in lower_failure:
        derived_requirements.append(
            "Validate a disk input with pathlib.Path(...).is_file() or "
            "os.path.isfile() before any host-runtime call. A host asset registry "
            "or editor asset-existence API does not validate a filesystem source."
        )
    if "validate optional callback inputs before" in lower_failure:
        derived_requirements.append(
            "Before any host-runtime call, accept None for each optional callback "
            "and raise TypeError when a non-None callback is not callable."
        )
    if "replace the inline ui progress callback" in lower_failure:
        derived_requirements.append(
            "Replace the inline callback with a local callback accepting "
            "(current, total, message). It must consume all three values, call "
            "progress_bar.setRange(0, total), progress_bar.setValue(current), "
            "and status_label.setText(message), then pass that callback to the "
            "backend operation."
        )
    elif "replace the ui progress callback" in lower_failure:
        derived_requirements.append(
            "Use a callback accepting exactly (current, total, message). It "
            "must call progress_bar.setRange(0, total), "
            "progress_bar.setValue(current), and "
            "status_label.setText(message)."
        )
    missing_request_fields = re.findall(
        r"validate or normalize every request field before[^;\r\n]*missing:\s*"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)",
        failure_text,
        flags=re.IGNORECASE,
    )
    for missing_group in missing_request_fields:
        derived_requirements.append(
            "Read, validate, and normalize these request fields before the first "
            "host-runtime call: "
            + ", ".join(
                value.strip()
                for value in missing_group.split(",")
                if value.strip()
            )
            + "."
        )
    if "exactly-one returned path contract" in lower_failure:
        derived_requirements.append(
            "After the host import completes, require len(imported_paths) == 1 "
            "before indexing the sole returned path."
        )
    if "normalize host paths with .replace" in lower_failure:
        derived_requirements.append(
            "Normalize each host package path before the first host-runtime call "
            "using a single-backslash replacement equivalent to "
            r'.replace("\\", "/").'
        )
    if "normalize the value assigned to" in lower_failure:
        derived_requirements.append(
            "Trace every value assigned to a host property ending in `_path` "
            "back to a normalized string produced with a single-backslash "
            r'.replace("\\", "/"); do not normalize an unrelated filename instead.'
        )
    if "host package paths must not be validated as filesystem" in lower_failure:
        derived_requirements.append(
            "Treat host package destinations as host paths, not disk directories. "
            "Validate non-empty package-string form and forward slashes without "
            "calling pathlib.Path.is_dir(), exists(), or is_file() on that value."
        )
    if "validate or normalize boolean request field" in lower_failure:
        derived_requirements.append(
            "Before any host-runtime call, validate boolean-like request fields "
            "with isinstance(value, bool), or normalize them explicitly with bool()."
        )
    if "typeerror:" in lower_failure and "magicmock" in lower_failure:
        derived_requirements.append(
            "Replace mock values that participate in arithmetic, ordering, or "
            "comparison with a deterministic value-producing fake of the required "
            "runtime type. Keep mocks only for call recording and assertion APIs."
        )
    assertion_proven_invalid = any(
        marker in lower_failure
        for marker in (
            "invalid verification expectation",
            "validator-proven invalid assertion",
        )
    )
    if (
        re.search(r"(?:^|_)(?:self_)?test(?:_|$)", node.name)
        and "assertionerror" in lower_failure
        and assertion_proven_invalid
    ):
        failing_assertions = list(dict.fromkeys(
            line.strip()
            for line in failure_text.splitlines()
            if line.strip().startswith("assert ")
        ))
        derived_requirements.append(
            "Replace the traceback assertion that just failed; it is "
            "validator-proven invalid. Do not leave that assertion in place and "
            "append a second fixture afterward."
            + (
                " Invalid assertion: " + failing_assertions[-1]
                if failing_assertions
                else ""
            )
        )
    invalid_assertion_lines = (
        list(dict.fromkeys(
            line.strip()
            for line in failure_text.splitlines()
            if line.strip().startswith("assert ")
        ))
        if assertion_proven_invalid
        else []
    )
    if invalid_assertion_lines:
        invalid_assertion_set = set(invalid_assertion_lines)
        sanitized_source_lines: list[str] = []
        for source_line in source.splitlines():
            if source_line.strip() in invalid_assertion_set:
                indent = source_line[:len(source_line) - len(source_line.lstrip())]
                sanitized_source_lines.append(
                    f"{indent}# INVALID ASSERTION REMOVED BY CONTRACT"
                )
            else:
                sanitized_source_lines.append(source_line)
        source = "\n".join(sanitized_source_lines)
    return {
        "path": path,
        "symbol": symbol,
        "callable_name": node.name,
        "source": source,
        "signature": signature,
        "signature_fingerprint": ast.dump(node.args, include_attributes=False),
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "owner_class": owner.name if owner is not None else "",
        "module_imports": module_imports,
        "module_symbols": module_symbols,
        "generated_interfaces": generated_interfaces,
        "sibling_symbols": sibling_symbols,
        "sibling_signatures": sibling_signatures,
        "state_context": state_context,
        "callsite_excerpts": callsite_excerpts,
        "all_callsite_excerpts": all_callsite_excerpts,
        "forbidden_names": forbidden_names,
        "requirements": list(dict.fromkeys(derived_requirements)),
        "full_requirements": [
            str(value) for value in requirements or [] if str(value).strip()
        ],
        "objective": str(objective or ""),
        "full_objective": str(objective or ""),
        "failure": relevant_failure,
        "all_validation_errors": [
            str(value) for value in validation_errors if str(value).strip()
        ],
        "invalid_assertion_lines": invalid_assertion_lines,
        "atomic_owner_capsule": True,
    }, []


def _unresolved_generated_names_by_callable(tree: ast.AST) -> dict[int, list[str]]:
    """Return unresolved names for each callable independently."""

    module_names = set(dir(builtins))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module_names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            module_names.update(
                child.id
                for target in targets
                for child in ast.walk(target)
                if isinstance(child, ast.Name)
            )

    parent_by_node = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    unresolved_by_callable: dict[int, list[str]] = {}
    for function in [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not isinstance(
            parent_by_node.get(id(node)),
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
        )
    ]:
        arguments = (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
            + ([function.args.vararg] if function.args.vararg else [])
            + ([function.args.kwarg] if function.args.kwarg else [])
        )
        local_names = {argument.arg for argument in arguments}
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                local_names.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                local_names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local_names.add(node.name)
            elif isinstance(node, ast.Lambda):
                local_names.update(
                    argument.arg
                    for argument in (
                        list(node.args.posonlyargs)
                        + list(node.args.args)
                        + list(node.args.kwonlyargs)
                        + ([node.args.vararg] if node.args.vararg else [])
                        + ([node.args.kwarg] if node.args.kwarg else [])
                    )
                )
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node is not function
            ):
                local_names.add(node.name)
                local_names.update(
                    argument.arg
                    for argument in (
                        list(node.args.posonlyargs)
                        + list(node.args.args)
                        + list(node.args.kwonlyargs)
                        + ([node.args.vararg] if node.args.vararg else [])
                        + ([node.args.kwarg] if node.args.kwarg else [])
                    )
                )
            elif isinstance(node, ast.ClassDef):
                local_names.add(node.name)
        unresolved_by_callable[id(function)] = sorted({
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id not in local_names
            and node.id not in module_names
        })
    return unresolved_by_callable


def _unresolved_generated_names(tree: ast.AST) -> list[str]:
    """Return obvious undefined globals without importing generated modules."""

    return sorted({
        name
        for names in _unresolved_generated_names_by_callable(tree).values()
        for name in names
    })


def resolve_project_edit_cross_file_symbols(
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Wire uniquely owned generated symbols into callables that reference them."""

    root = Path(project_root).resolve()
    module_by_path: dict[str, str] = {}
    owners: dict[str, list[str]] = {}
    trees: dict[str, ast.Module] = {}
    for path_text, _original, generated in generated_files:
        try:
            module = ".".join(Path(path_text).resolve().relative_to(root).with_suffix("").parts)
            tree = ast.parse(generated, filename=path_text)
        except (ValueError, SyntaxError):
            continue
        module_by_path[path_text] = module
        trees[path_text] = tree
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                owners.setdefault(node.name, []).append(module)

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        tree = trees.get(path_text)
        module = module_by_path.get(path_text)
        if tree is None or module is None:
            continue
        unresolved = set(_unresolved_generated_names(tree))
        for class_node in (
            node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ):
            for expression in [
                *class_node.bases,
                *[keyword.value for keyword in class_node.keywords],
                *class_node.decorator_list,
            ]:
                unresolved.update(
                    child.id
                    for child in ast.walk(expression)
                    if isinstance(child, ast.Name)
                )
        uniquely_owned = {
            name: modules[0]
            for name, modules in owners.items()
            if name in unresolved and len(modules) == 1 and modules[0] != module
        }
        if not uniquely_owned:
            continue
        lines = source.splitlines(keepends=True)
        edits: list[tuple[int, str]] = []
        callables = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for function in callables:
            used = sorted({
                node.id
                for node in ast.walk(function)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in uniquely_owned
            })
            if not used:
                continue
            insertion_line = function.lineno
            if function.body:
                first = function.body[0]
                insertion_line = first.lineno - 1
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    insertion_line = int(first.end_lineno or first.lineno)
            indent = " " * (int(function.col_offset or 0) + 4)
            imports = "".join(
                f"{indent}from {uniquely_owned[name]} import {name}\n"
                for name in used
            )
            edits.append((insertion_line, imports))
            fixes.extend(
                f"{Path(path_text).name}:{function.name} -> {uniquely_owned[name]}.{name}"
                for name in used
            )
        for insertion_line, import_text in sorted(edits, reverse=True):
            lines[insertion_line:insertion_line] = [import_text]
        updated[index] = (path_text, original, "".join(lines))
    return updated, fixes


def _requested_identifier_contracts(request_prompt: str) -> tuple[set[str], list[tuple[str, str]]]:
    """Extract explicit rename and removal contracts from a natural-language edit request."""

    prompt = str(request_prompt or "")
    removed: set[str] = set()
    for group in re.findall(
        r"(?:^|[.!?]\s+|\b(?:please|also|then)\s+|\band\s+)"
        r"remove\s+(?:the\s+)?"
        r"([A-Za-z_]\w*(?:\s*(?:,|and)\s*[A-Za-z_]\w*)*)",
        prompt,
        flags=re.IGNORECASE,
    ):
        removed.update(re.findall(r"[A-Za-z_]\w*", group))

    renames: list[tuple[str, str]] = []
    for source_group, target_group in re.findall(
        r"\brename\s+([A-Za-z_]\w*(?:/[A-Za-z_]\w*)*)\s+to\s+"
        r"([A-Za-z_]\w*(?:/[A-Za-z_]\w*)*)",
        prompt,
        flags=re.IGNORECASE,
    ):
        sources = source_group.split("/")
        targets = target_group.split("/")
        if len(sources) == len(targets):
            renames.extend(zip(sources, targets))
    return removed, renames


def _tree_uses_identifier(tree: ast.AST, identifier: str) -> bool:
    """Return whether executable Python still defines or references an identifier."""

    return any(
        (isinstance(node, ast.Name) and node.id == identifier)
        or (isinstance(node, ast.arg) and node.arg == identifier)
        or (isinstance(node, ast.Attribute) and node.attr == identifier)
        for node in ast.walk(tree)
    )


def _quality_result(ok: bool, path: Path, check: str, message: str) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "path": str(path),
        "check": check,
        "command": f"candidate:{check}",
        "message": message,
    }


def _public_definition_map(tree: ast.AST) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}

    def walk(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = str(node.name)
            qualified = f"{prefix}.{name}" if prefix else name
            if not name.startswith("_"):
                found[qualified] = node
            if isinstance(node, ast.ClassDef):
                walk(node.body, qualified)

    walk(list(getattr(tree, "body", []) or []))
    return found


def _callable_definition_map(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return qualified callable names, including private lifecycle methods."""

    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def walk(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}.{node.name}" if prefix else node.name
                found[qualified] = node
            elif isinstance(node, ast.ClassDef):
                qualified = f"{prefix}.{node.name}" if prefix else node.name
                walk(node.body, qualified)

    walk(list(getattr(tree, "body", []) or []))
    return found


def apply_project_edit_missing_symbol(
    source: str,
    *,
    path: str,
    symbol: str,
    response: str,
    objective: str = "",
) -> tuple[str, list[str]]:
    """Insert one validated missing module declaration before its entry point."""

    text = str(response or "").strip()
    text = re.sub(r"^```(?:python|py)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        tree = ast.parse(text, filename=f"<missing:{symbol}>")
    except SyntaxError as exc:
        return source, [f"Missing symbol {symbol} did not parse: {exc}"]
    declarations = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
    ]
    declaration: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    container_name = ""
    if len(declarations) == 1 and len(tree.body) == 1:
        declaration = declarations[0]
    elif len(tree.body) == 1 and isinstance(tree.body[0], ast.ClassDef):
        container = tree.body[0]
        member_declarations = [
            node
            for node in container.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == symbol
        ]
        if len(member_declarations) != 1:
            return source, [
                f"Missing symbol repair must return exactly one top-level declaration named {symbol}."
            ]
        declaration = member_declarations[0]
        container_name = container.name
    else:
        return source, [
            f"Missing symbol repair must return exactly one top-level declaration named {symbol}."
        ]
    placeholder_callables = [
        name
        for name, node in _callable_definition_map(tree).items()
        if any(
            isinstance(statement, ast.Pass)
            or (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and statement.value.value is Ellipsis
            )
            for statement in node.body
        )
    ]
    if placeholder_callables:
        return source, [
            f"Missing symbol {symbol} contains placeholder callables: "
            + ", ".join(placeholder_callables)
        ]
    declaration_source = ast.get_source_segment(text, declaration) or ast.unparse(declaration)
    try:
        owner_tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return source, [f"Missing symbol owner did not parse: {exc}"]
    source_lines = source.rstrip().splitlines()
    if container_name:
        owner_containers = [
            node
            for node in owner_tree.body
            if isinstance(node, ast.ClassDef) and node.name == container_name
        ]
        if len(owner_containers) != 1:
            return source, [
                f"Missing member {symbol} requires one existing class named {container_name}."
            ]
        owner_container = owner_containers[0]
        existing_members = [
            node
            for node in owner_container.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == symbol
        ]
        member_source = textwrap.indent(declaration_source.strip(), " " * 4)
        if existing_members:
            existing = existing_members[0]
            start = int(existing.lineno) - 1
            decorators = list(getattr(existing, "decorator_list", []) or [])
            if decorators:
                start = min(int(item.lineno) for item in decorators) - 1
            end = int(existing.end_lineno)
            inserted_lines = [
                *source_lines[:start],
                *member_source.splitlines(),
                *source_lines[end:],
            ]
        else:
            insertion_index = int(owner_container.end_lineno)
            inserted_lines = [
                *source_lines[:insertion_index],
                "",
                *member_source.splitlines(),
                *source_lines[insertion_index:],
            ]
        corrected = "\n".join(inserted_lines).strip() + "\n"
        try:
            compile(ast.parse(corrected, filename=path), path, "exec")
        except (SyntaxError, ValueError) as exc:
            return source, [f"Missing member {container_name}.{symbol} did not integrate: {exc}"]
        return corrected, []

    existing_declarations = [
        node
        for node in owner_tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
    ]
    main_nodes = [
        node
        for node in owner_tree.body
        if isinstance(node, ast.If)
        and "__name__" in ast.unparse(node.test)
        and "__main__" in ast.unparse(node.test)
    ]
    if len(existing_declarations) > 1:
        return source, [
            f"Missing symbol owner contains duplicate top-level declarations named {symbol}."
        ]
    if existing_declarations:
        existing = existing_declarations[0]
        start = int(existing.lineno) - 1
        decorators = list(getattr(existing, "decorator_list", []) or [])
        if decorators:
            start = min(int(item.lineno) for item in decorators) - 1
        end = int(existing.end_lineno)
        inserted_lines = [
            *source_lines[:start],
            *declaration_source.rstrip().splitlines(),
            *source_lines[end:],
        ]
    else:
        insertion_index = (
            min(int(node.lineno) for node in main_nodes) - 1
            if main_nodes
            else len(source_lines)
        )
        inserted_lines = [
            *source_lines[:insertion_index],
            "",
            "",
            *declaration_source.rstrip().splitlines(),
            "",
            "",
            *source_lines[insertion_index:],
        ]
    corrected = "\n".join(inserted_lines).strip() + "\n"
    direct_main_relation = bool(
        re.search(
            rf"__main__[^\n.;]*?\b(?:runs?|calls?|invokes?)\s+"
            rf"{re.escape(symbol)}\s*\(",
            objective,
            flags=re.IGNORECASE,
        )
    )
    if direct_main_relation:
        corrected_tree = ast.parse(corrected, filename=path)
        offsets = [0]
        for line in corrected.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        replacements: list[tuple[int, int, str]] = []
        for main_node in corrected_tree.body:
            if not (
                isinstance(main_node, ast.If)
                and "__name__" in ast.unparse(main_node.test)
                and "__main__" in ast.unparse(main_node.test)
            ):
                continue
            for call in ast.walk(main_node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == symbol
                ):
                    start = offsets[call.lineno - 1] + call.col_offset
                    end = offsets[call.end_lineno - 1] + call.end_col_offset
                    replacements.append((start, end, f"{symbol}()"))
        for start, end, replacement in sorted(replacements, reverse=True):
            corrected = corrected[:start] + replacement + corrected[end:]
    try:
        compile(ast.parse(corrected, filename=path), path, "exec")
    except (SyntaxError, ValueError) as exc:
        return source, [f"Missing symbol {symbol} did not integrate: {exc}"]
    return corrected, []


def _missing_explicit_bool_rejections(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Return requested callables that do not explicitly exclude bool values."""

    relevant_sentences = [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", request_prompt)
        if re.search(r"\bbool(?:ean)?\b", sentence, flags=re.IGNORECASE)
        and re.search(
            r"\b(?:reject|invalid|not\s+accept|raise)\w*\b",
            sentence,
            flags=re.IGNORECASE,
        )
    ]
    if not relevant_sentences:
        return []
    callable_map = _callable_definition_map(tree)
    requested_owners: set[str] = set()
    for sentence in relevant_sentences:
        if re.search(r"\bconstructor\b", sentence, flags=re.IGNORECASE):
            requested_owners.update(
                name for name in callable_map if name.endswith(".__init__")
            )
        before_requirement = re.split(
            r"\b(?:must|should|rejects?|raises?)\b",
            sentence,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        for qualified_name in callable_map:
            leaf_name = qualified_name.rsplit(".", 1)[-1]
            if leaf_name.startswith("__") and leaf_name != "__init__":
                continue
            if re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(leaf_name)}"
                rf"(?:\s*\(|(?![A-Za-z0-9_]))",
                before_requirement,
                flags=re.IGNORECASE,
            ):
                requested_owners.add(qualified_name)

    missing: list[str] = []
    for qualified_name in sorted(requested_owners):
        function = callable_map[qualified_name]
        has_bool_reference = any(
            isinstance(node, ast.Name) and node.id == "bool"
            for node in ast.walk(function)
        )
        has_exact_type_check = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "type"
            for node in ast.walk(function)
        )
        if not has_bool_reference and not has_exact_type_check:
            missing.append(qualified_name)
    return missing


def _import_specs(tree: ast.AST) -> list[tuple[str, int, str]]:
    specs: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            specs.extend((alias.name, 0, "") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            specs.extend((node.module or "", int(node.level or 0), alias.name) for alias in node.names)
    return list(dict.fromkeys(specs))


def _resolve_local_module_symbol_fallback(
    module_path: Path,
    module_source: str | None,
    symbol: str,
) -> str | None:
    if not symbol or module_path.suffix != ".py":
        return None

    try:
        parsed = ast.parse(
            module_source
            if module_source is not None
            else module_path.read_text(encoding="utf-8", errors="replace"),
            filename=str(module_path),
        )
    except (OSError, SyntaxError):
        return None

    candidate_bases: list[tuple[str, str]] = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name
                binding = alias.asname or alias.name.rsplit(".", 1)[-1]
                candidate_bases.append((base, binding))
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            base = node.module
            for alias in node.names:
                if alias.name == "*":
                    continue
                binding = alias.asname or alias.name
                candidate_bases.append((base, binding))
                candidate_bases.append((f"{base}.{binding}", binding))

    for base_module, binding in candidate_bases:
        try:
            module_spec = importlib.util.find_spec(base_module)
        except (AttributeError, ImportError, ModuleNotFoundError, ValueError):
            continue
        if module_spec is None:
            continue
        try:
            base_imported = importlib.import_module(base_module)
        except Exception:
            continue
        if hasattr(base_imported, symbol):
            return base_module
        attribute = getattr(base_imported, binding, None)
        if attribute is not None and hasattr(attribute, symbol):
            return f"{base_module}.{binding}"
    return None


def _existing_module_path(candidate: Path, *, candidate_paths: set[str]) -> Path | None:
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if str(candidate.with_suffix(".py").resolve()) in candidate_paths:
        return candidate.with_suffix(".py")
    package_init = candidate / "__init__.py"
    if package_init.is_file() or str(package_init.resolve()) in candidate_paths:
        return package_init
    return None


def _local_module_path(
    target_path: Path,
    module: str,
    level: int,
    *,
    project_root: str | None,
    candidate_paths: set[str],
) -> Path | None:
    if level:
        base = target_path.parent
        for _index in range(max(0, level - 1)):
            base = base.parent
        candidate = base.joinpath(*[part for part in module.split(".") if part])
        return _existing_module_path(candidate, candidate_paths=candidate_paths)

    roots: list[Path] = []
    if project_root:
        roots.append(Path(project_root))
    if "TOOLSROOT" in os.environ:
        tools_root = Path(os.environ["TOOLSROOT"]).resolve()
        if tools_root.exists():
            roots.append(tools_root)
    package_root = target_path.parent
    while (package_root / "__init__.py").is_file():
        package_root = package_root.parent
    roots.append(package_root)
    for root in roots:
        candidate = root.joinpath(*[part for part in module.split(".") if part])
        resolved = _existing_module_path(candidate, candidate_paths=candidate_paths)
        if resolved is not None:
            return resolved
    return None


def infer_project_edit_generated_dependencies(
    source: str,
    *,
    path: str,
    project_root: str,
    generated_files: list[tuple[str, str, str]],
) -> list[str]:
    """Return completed generated files imported by the current generated source."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    root = Path(project_root).resolve()
    target = Path(path).resolve()
    candidate_paths = {
        str(Path(file_path).resolve())
        for file_path, _original, _generated in generated_files
    }
    dependencies: list[str] = []
    for module, level, imported_name in _import_specs(tree):
        local_path = _local_module_path(
            target,
            module,
            level,
            project_root=project_root,
            candidate_paths=candidate_paths,
        )
        if local_path is None or str(local_path.resolve()) not in candidate_paths:
            continue
        try:
            relative = local_path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        dependencies.append(relative)
    return list(dict.fromkeys(dependencies))


def _local_module_exports(path: Path, name: str, *, source_override: str | None = None) -> bool:
    try:
        source = source_override if source_override is not None else path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name.rsplit(".", 1)[-1]) == name for alias in node.names):
                return True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                return True
    return False


def _repair_local_module_fallback_imports(
    source: str,
    *,
    target_path: Path,
    project_root: str | None,
) -> tuple[str, list[str]]:
    """
    Replace from-imports that target a local module but request symbols that are
    only exposed through that module's imported dependencies.
    """
    try:
        tree = ast.parse(source, filename=str(target_path))
    except SyntaxError:
        return source, []

    replacements: list[tuple[int, int, list[str]]] = []
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.lineno is None or node.end_lineno is None:
            continue
        if node.module is None:
            continue

        local_path = _local_module_path(
            target_path,
            node.module,
            0,
            project_root=project_root,
            candidate_paths=set(),
        )
        if local_path is None:
            continue
        try:
            local_source = local_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            local_source = None

        if local_source is None:
            continue

        keep: list[ast.alias] = []
        fallback: dict[str, list[ast.alias]] = {}
        for alias in node.names:
            if _local_module_exports(
                local_path,
                alias.name,
                source_override=local_source,
            ):
                keep.append(alias)
                continue
            fallback_module = _resolve_local_module_symbol_fallback(
                local_path,
                local_source,
                alias.name,
            )
            if fallback_module is None:
                keep.append(alias)
                continue
            fallback.setdefault(fallback_module, []).append(alias)

        if not fallback:
            continue

        replacement_lines: list[str] = []
        if keep:
            keep_text = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in keep
            )
            replacement_lines.append(f"from {node.module} import {keep_text}")
        for fallback_module, fallback_aliases in sorted(fallback.items()):
            alias_text = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in fallback_aliases
            )
            replacement_lines.append(f"from {fallback_module} import {alias_text}")

        replacements.append((node.lineno - 1, node.end_lineno, replacement_lines))

    if not replacements:
        return source, []

    for start, end, replacement_lines in sorted(replacements, reverse=True):
        lines[start:end] = [f"{item}\n" for item in replacement_lines]
    return "".join(lines), [
        f"{target_path.name}: rewrote local imports using fallback symbol providers."
    ]


def resolve_project_edit_standard_library_symbols(
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str | None = None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """
    Add known standard-library imports required by otherwise complete generated code.
    Also normalize imports when local modules expose symbols through dependencies.
    """

    symbol_imports = {
        "AsyncMock": "from unittest.mock import AsyncMock",
        "MagicMock": "from unittest.mock import MagicMock",
        "Mock": "from unittest.mock import Mock",
        "NamedTemporaryFile": "from tempfile import NamedTemporaryFile",
        "defaultdict": "from collections import defaultdict",
        "deepcopy": "from copy import deepcopy",
        "deque": "from collections import deque",
        "Lock": "from threading import Lock",
        "RLock": "from threading import RLock",
        "TemporaryDirectory": "from tempfile import TemporaryDirectory",
        "json": "import json",
        "os": "import os",
        "tempfile": "import tempfile",
        "unittest": "import unittest",
        "mock": "from unittest import mock",
        "patch": "from unittest.mock import patch",
    }
    import typing as typing_module

    typing_symbols = set(getattr(typing_module, "__all__", ()))
    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        source, repair_fixes = _repair_local_module_fallback_imports(
            source,
            target_path=Path(path_text),
            project_root=project_root,
        )
        if repair_fixes:
            fixes.extend(repair_fixes)
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        unresolved = set(_unresolved_generated_names(tree))
        for class_node in (
            node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ):
            for expression in [
                *class_node.bases,
                *[keyword.value for keyword in class_node.keywords],
                *class_node.decorator_list,
            ]:
                unresolved.update(
                    child.id
                    for child in ast.walk(expression)
                    if isinstance(child, ast.Name)
                )
        updated[index] = (path_text, original, source)
        module_bindings = {
            alias.asname or (
                alias.name.split(".", 1)[0]
                if isinstance(node, ast.Import)
                else alias.name
            )
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
            if alias.name != "*"
        }
        imports = [
            symbol_imports[name]
            for name in sorted(unresolved & symbol_imports.keys())
        ]
        imports.extend(
            f"import {name}"
            for name in sorted(unresolved & set(getattr(sys, "stdlib_module_names", ())))
            if name not in symbol_imports
        )
        imports.extend(
            f"from typing import {name}"
            for name in sorted(unresolved & typing_symbols)
            if name not in module_bindings
        )
        annotation_roots: list[ast.AST] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.annotation is not None:
                annotation_roots.append(node.annotation)
            elif isinstance(node, ast.AnnAssign):
                annotation_roots.append(node.annotation)
            elif isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ) and node.returns is not None:
                annotation_roots.append(node.returns)
        annotation_names = {
            child.id
            for annotation in annotation_roots
            for child in ast.walk(annotation)
            if isinstance(child, ast.Name)
        }
        inferred_typevars = sorted(
            name
            for name in unresolved & annotation_names
            if re.fullmatch(
                r"(?:[TUVK]|KT|VT)(?:_(?:co|contra))?",
                name,
            )
        )
        if inferred_typevars:
            if "TypeVar" not in module_bindings:
                imports.append("from typing import TypeVar")
            imports.extend(
                f'{name} = TypeVar("{name}")'
                for name in inferred_typevars
            )
        if not imports:
            continue
        lines = source.splitlines(keepends=True)
        insertion = 1 if lines and re.match(r"^#.*coding[:=]", lines[0]) else 0
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            insertion = max(
                insertion,
                int(tree.body[0].end_lineno or tree.body[0].lineno),
            )
        while insertion < len(lines) and (
            not lines[insertion].strip()
            or lines[insertion].startswith("import ")
            or lines[insertion].startswith("from ")
        ):
            insertion += 1
        lines[insertion:insertion] = [statement + "\n" for statement in imports]
        updated[index] = (path_text, original, "".join(lines))
        fixes.extend(f"{Path(path_text).name}: added {statement}" for statement in imports)
    return updated, fixes
