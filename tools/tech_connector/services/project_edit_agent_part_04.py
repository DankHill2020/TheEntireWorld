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

from tech_connector.services.project_edit_agent_part_01 import (
    ProjectEditPlan,
    ProjectEditPromptStage,
    _chunk_manifest_declarations,
    _project_edit_protocol_term_present,
    _remove_generated_top_level_await,
    _required_project_edit_protocol_terms,
    _select_artifact_requirement_owner,
)

from tech_connector.services.project_edit_agent_part_02 import (
    _HOST_RUNTIME_MODULES,
    _edit_python_symbol_source,
    _generated_module_import_side_effects,
    _is_placeholder_callable,
    _remove_generated_top_level_calls,
    _remove_redundant_generated_initializers,
)

from tech_connector.services.project_edit_agent_part_03 import (
    _callable_definition_map,
    _import_specs,
    _local_module_exports,
    _local_module_path,
    _resolve_local_module_symbol_fallback,
    _tree_uses_identifier,
    _unresolved_generated_names,
    _verified_installed_qt_symbol,
    resolve_project_edit_standard_library_symbols,
)


def apply_project_edit_generated_class_repair(
    generated_files: list[tuple[str, str, str]],
    *,
    path: str,
    class_name: str,
    replacement_response: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Splice one complete class replacement into a newly generated module."""

    replacement = str(replacement_response or "").strip()
    replacement = re.sub(r"^```(?:python|py)?\s*", "", replacement, flags=re.IGNORECASE)
    replacement = re.sub(r"\s*```$", "", replacement)
    try:
        replacement_tree = ast.parse(
            textwrap.dedent(replacement),
            filename=f"<class-repair:{class_name}>",
        )
    except SyntaxError as exc:
        return generated_files, [f"Class repair did not parse: {exc}"]
    declarations = [
        node
        for node in replacement_tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(declarations) != 1:
        return generated_files, [
            f"Class repair must contain exactly one class named {class_name}."
        ]
    class_node = declarations[0]
    placeholders = [
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_placeholder_callable(node)
    ]
    if placeholders:
        return generated_files, [
            f"Class repair contains placeholder methods: {', '.join(placeholders)}"
        ]
    class_source = ast.unparse(class_node)
    updated = list(generated_files)
    for index, (path_text, original, source) in enumerate(updated):
        if Path(path_text).resolve() != Path(path).resolve():
            continue
        try:
            unresolved_before = set(
                _unresolved_generated_names(ast.parse(source, filename=path_text))
            )
        except SyntaxError as exc:
            return generated_files, [f"Generated class owner did not parse: {exc}"]
        matched, corrected, error = _edit_python_symbol_source(
            source,
            target_symbol=class_name,
            replacement=class_source,
            filename=path_text,
            operation="replace_symbol",
        )
        if not matched:
            return generated_files, [
                error or f"Could not replace generated class {class_name}."
            ]
        try:
            corrected_tree = ast.parse(corrected, filename=path_text)
            compile(corrected_tree, path_text, "exec")
        except (SyntaxError, ValueError) as exc:
            return generated_files, [f"Repaired class owner did not compile: {exc}"]
        corrected_records, _fixes = resolve_project_edit_standard_library_symbols(
            [(path_text, original, corrected)]
        )
        corrected = corrected_records[0][2]
        corrected_tree = ast.parse(corrected, filename=path_text)
        package_symbols: set[str] = set()
        for package_path, _package_original, package_source in generated_files:
            try:
                package_tree = ast.parse(package_source, filename=package_path)
            except SyntaxError:
                continue
            package_symbols.update(
                node.name
                for node in package_tree.body
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
            )
        unresolved = sorted(
            (
                set(_unresolved_generated_names(corrected_tree))
                - unresolved_before
            )
            - package_symbols
        )
        unresolved = [
            name for name in unresolved if not _verified_installed_qt_symbol(name)
        ]
        if "hashable" in unresolved:
            class NormalizeHashableAnnotation(ast.NodeTransformer):
                """Replace the invalid lowercase pseudo-type with object.

                :return: AST transformer for repaired class annotations.
                """

                def visit_Name(self, node: ast.Name) -> ast.AST:
                    if node.id == "hashable" and isinstance(node.ctx, ast.Load):
                        return ast.copy_location(
                            ast.Name(id="object", ctx=node.ctx),
                            node,
                        )
                    return node

            corrected_tree = NormalizeHashableAnnotation().visit(corrected_tree)
            ast.fix_missing_locations(corrected_tree)
            corrected = ast.unparse(corrected_tree).rstrip() + "\n"
            compile(corrected_tree, path_text, "exec")
            unresolved.remove("hashable")
        if unresolved:
            return generated_files, [
                "Repaired class owner references undefined names: "
                + ", ".join(unresolved)
            ]
        updated[index] = (path_text, original, corrected)
        return updated, []
    return generated_files, [f"Generated class repair path was not found: {path}"]


def apply_project_edit_generated_class_set_repair(
    generated_files: list[tuple[str, str, str]],
    *,
    class_targets: list[tuple[str, str]],
    replacement_response: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Extract and splice a coherent response as separate class-only patches."""

    raw_text = str(replacement_response or "").strip()
    fenced_blocks = re.findall(
        r"```(?:python|py)?\s*(.*?)```",
        raw_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    candidates = fenced_blocks or [raw_text]
    by_name: dict[str, list[ast.ClassDef]] = {}
    imports_by_name: dict[str, list[ast.Import | ast.ImportFrom]] = {}
    parse_errors: list[SyntaxError] = []
    for candidate in candidates:
        text = candidate.strip()
        try:
            tree = ast.parse(text, filename="<class-set-repair>")
        except SyntaxError as exc:
            parse_errors.append(exc)
            tree = None
            lines = text.splitlines()
            for end in range(len(lines) - 1, 0, -1):
                try:
                    prefix_tree = ast.parse(
                        "\n".join(lines[:end]),
                        filename="<class-set-repair>",
                    )
                except SyntaxError:
                    continue
                if any(isinstance(node, ast.ClassDef) for node in prefix_tree.body):
                    tree = prefix_tree
                    break
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                by_name.setdefault(node.name, []).append(node)
                imports_by_name.setdefault(node.name, []).extend(
                    import_node
                    for import_node in tree.body
                    if isinstance(import_node, (ast.Import, ast.ImportFrom))
                )
    if not by_name and parse_errors:
        return generated_files, [
            f"Class-set repair did not parse: {parse_errors[-1]}"
        ]
    missing = [
        name
        for _path, name in class_targets
        if not by_name.get(name)
    ]
    if missing:
        return generated_files, [
            "Class-set repair is missing required target(s): "
            + ", ".join(missing)
        ]
    selected_classes = {
        name: max(
            by_name[name],
            key=lambda node: (
                sum(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for child in node.body
                ),
                len(ast.unparse(node)),
            ),
        )
        for _path, name in class_targets
    }
    updated = generated_files
    for path, class_name in class_targets:
        required_imports = list(dict.fromkeys(
            ast.unparse(node)
            for node in imports_by_name.get(class_name, [])
        ))
        if required_imports:
            preimported = list(updated)
            for index, (path_text, original, source) in enumerate(preimported):
                if Path(path_text).resolve() != Path(path).resolve():
                    continue
                source_tree = ast.parse(source, filename=path_text)
                existing_imports = {
                    ast.unparse(node)
                    for node in source_tree.body
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                }
                missing_imports = [
                    statement
                    for statement in required_imports
                    if statement not in existing_imports
                ]
                if not missing_imports:
                    break
                lines = source.splitlines(keepends=True)
                insertion_line = 0
                for node in source_tree.body:
                    if (
                        isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                        and node is source_tree.body[0]
                    ) or isinstance(node, (ast.Import, ast.ImportFrom)):
                        insertion_line = max(
                            insertion_line,
                            int(node.end_lineno or node.lineno),
                        )
                        continue
                    break
                lines[insertion_line:insertion_line] = [
                    statement + "\n" for statement in missing_imports
                ]
                corrected = "".join(lines)
                compile(corrected, path_text, "exec")
                preimported[index] = (path_text, original, corrected)
                break
            updated = preimported
        class_source = ast.unparse(selected_classes[class_name])
        updated, errors = apply_project_edit_generated_class_repair(
            updated,
            path=path,
            class_name=class_name,
            replacement_response=class_source,
        )
        if errors:
            return generated_files, errors
    return updated, []


def apply_project_edit_generated_symbol_repair(
    generated_files: list[tuple[str, str, str]],
    *,
    path: str,
    symbol: str,
    replacement_response: str,
    forbidden_names: list[str] | None = None,
    approved_signature: str = "",
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Parse and splice one model-repaired callable into a generated file."""

    replacement = str(replacement_response or "").strip()
    replacement = re.sub(r"^```(?:python|py)?\s*", "", replacement, flags=re.IGNORECASE)
    replacement = re.sub(r"\s*```$", "", replacement)
    try:
        tree = ast.parse(textwrap.dedent(replacement), filename=f"<repair:{symbol}>")
        compile(tree, f"<repair:{symbol}>", "exec")
    except (SyntaxError, ValueError) as exc:
        return generated_files, [f"Repaired symbol did not parse and compile: {exc}"]
    expected_name = symbol.rsplit(".", 1)[-1]
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == expected_name
    ]
    if len(definitions) != 1:
        return generated_files, [f"Repair must return exactly one function named {expected_name}."]
    nested_definitions = [
        node
        for node in ast.walk(definitions[0])
        if node is not definitions[0]
        and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    is_disposable_test = Path(path).name.startswith("test_")
    existing_nested_names: set[str] = set()
    for current_path, _original, current_source in generated_files:
        if str(Path(current_path).resolve()) != str(Path(path).resolve()):
            continue
        try:
            current_tree = ast.parse(current_source, filename=current_path)
        except SyntaxError:
            break
        current_definition: ast.AST | None = None
        if "." in symbol:
            class_name, method_name = symbol.split(".", 1)
            class_node = next(
                (
                    node
                    for node in current_tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            if class_node is not None:
                current_definition = next(
                    (
                        node
                        for node in class_node.body
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == method_name
                    ),
                    None,
                )
        else:
            current_definition = next(
                (
                    node
                    for node in current_tree.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == expected_name
                ),
                None,
            )
        if current_definition is not None:
            existing_nested_names = {
                str(getattr(node, "name", "") or "")
                for node in ast.walk(current_definition)
                if node is not current_definition
                and isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
            }
        break
    introduced_nested_classes = [
        node
        for node in nested_definitions
        if isinstance(node, ast.ClassDef)
        if str(getattr(node, "name", "") or "") not in existing_nested_names
    ]
    verification_callable = (
        expected_name in {"run_self_test", "self_test"}
        or expected_name.startswith("test_")
    )
    if (
        introduced_nested_classes
        and not is_disposable_test
        and not verification_callable
    ):
        nested_names = ", ".join(
            sorted({
                str(getattr(node, "name", "") or "")
                for node in introduced_nested_classes
            })
        )
        return generated_files, [
            (
                f"Repair for {expected_name} introduced local class declaration(s): "
                f"{nested_names}. Return only the owned callable implementation; "
                "new classes require their own declared symbol owners."
            )
        ]
    parsed_replacement = textwrap.dedent(replacement)
    replacement_lines = parsed_replacement.splitlines()
    replacement_definition = definitions[0]
    replacement_start = min(
        [int(replacement_definition.lineno)]
        + [
            int(decorator.lineno)
            for decorator in replacement_definition.decorator_list
        ]
    )
    replacement_end = int(
        replacement_definition.end_lineno or replacement_definition.lineno
    )
    replacement = "\n".join(
        replacement_lines[replacement_start - 1:replacement_end]
    ).strip()
    repaired_tree = ast.parse(replacement, filename=f"<repair:{symbol}>")
    repaired_definition = repaired_tree.body[0]
    if current_definition is not None and ast.dump(
        repaired_definition,
        include_attributes=False,
    ) == ast.dump(
        current_definition,
        include_attributes=False,
    ):
        return generated_files, [
            (
                f"Repair response for {symbol} is AST-equivalent to the "
                "rejected source."
            )
        ]
    meaningful_body = [
        statement
        for statement in repaired_definition.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if meaningful_body and all(
        isinstance(statement, ast.Pass)
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        )
        for statement in meaningful_body
    ):
        return generated_files, [f"Repaired symbol {expected_name} contains a placeholder pass body."]
    forbidden_set = set(forbidden_names or ())
    retained_forbidden = sorted(
        {
            node.id
            for node in ast.walk(repaired_definition)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in forbidden_set
        }
        | {
            node.attr
            for node in ast.walk(repaired_definition)
            if isinstance(node, ast.Attribute)
            and node.attr in forbidden_set
        }
    )
    if retained_forbidden:
        return generated_files, [
            f"Repaired symbol {expected_name} retained proven-invalid names: "
            + ", ".join(retained_forbidden)
        ]

    updated = list(generated_files)
    for index, (path_text, original, source) in enumerate(updated):
        if Path(path_text).resolve() != Path(path).resolve():
            continue
        try:
            owner_tree = ast.parse(source, filename=path_text)
        except SyntaxError as exc:
            source_lines = source.splitlines(keepends=True)
            target_indent = ""
            target_start = -1
            target_end = len(source_lines)
            class_name = symbol.split(".", 1)[0] if "." in symbol else ""
            class_indent = -1
            active_class = ""
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
                function_match = re.match(
                    rf"(?:async\s+)?def\s+{re.escape(expected_name)}\s*\(",
                    stripped,
                )
                if not function_match:
                    continue
                if class_name and active_class != class_name:
                    continue
                if not class_name and active_class:
                    continue
                target_indent = indent_text
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
            if target_start < 0:
                return generated_files, [
                    f"Generated repair owner did not parse and lexical owner "
                    f"{symbol} was not found: {exc}"
                ]
            indented_replacement = "\n".join(
                target_indent + line if line.strip() else ""
                for line in replacement.splitlines()
            ).rstrip() + "\n"
            corrected = "".join([
                *source_lines[:target_start],
                indented_replacement,
                *source_lines[target_end:],
            ])
            try:
                compile(ast.parse(corrected, filename=path_text), path_text, "exec")
            except (SyntaxError, ValueError) as repaired_exc:
                return generated_files, [
                    f"Lexical repair for {symbol} did not restore module syntax: "
                    f"{repaired_exc}"
                ]
            updated[index] = (path_text, original, corrected)
            return updated, []
        symbol_parts = symbol.split(".")
        if len(symbol_parts) == 2:
            owner_class = next(
                (
                    node
                    for node in owner_tree.body
                    if isinstance(node, ast.ClassDef) and node.name == symbol_parts[0]
                ),
                None,
            )
            original_definitions = [
                node
                for node in (owner_class.body if owner_class is not None else [])
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == expected_name
            ]
        else:
            original_definitions = [
                node
                for node in owner_tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == expected_name
            ]
        if len(original_definitions) != 1:
            return generated_files, [
                f"Generated repair owner does not contain exactly one {expected_name} callable."
            ]
        original_definition = original_definitions[0]
        def argument_shape(arguments: ast.arguments) -> tuple[Any, ...]:
            return (
                tuple(item.arg for item in arguments.posonlyargs),
                tuple(item.arg for item in arguments.args),
                arguments.vararg.arg if arguments.vararg else "",
                tuple(item.arg for item in arguments.kwonlyargs),
                arguments.kwarg.arg if arguments.kwarg else "",
                tuple(
                    ast.dump(item, include_attributes=False)
                    for item in arguments.defaults
                ),
                tuple(
                    ast.dump(item, include_attributes=False)
                    if item is not None else ""
                    for item in arguments.kw_defaults
                ),
            )

        approved_definition: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        if approved_signature:
            try:
                approved_tree = ast.parse(
                    approved_signature.rstrip().rstrip(":")
                    + ":\n    pass",
                    filename=f"<approved:{symbol}>",
                )
                approved_candidate = approved_tree.body[0]
                if isinstance(
                    approved_candidate,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    approved_definition = approved_candidate
            except (IndexError, SyntaxError):
                approved_definition = None
        approved_signature_correction = bool(
            approved_definition is not None
            and argument_shape(original_definition.args)
            != argument_shape(approved_definition.args)
            and argument_shape(repaired_definition.args)
            == argument_shape(approved_definition.args)
        )
        if (
            original_definition.decorator_list
            and not repaired_definition.decorator_list
            and not approved_signature_correction
        ):
            original_decorators = [
                ast.get_source_segment(source, decorator) or ast.unparse(decorator)
                for decorator in original_definition.decorator_list
            ]
            replacement = "\n".join([
                *(
                    decorator
                    if decorator.lstrip().startswith("@")
                    else "@" + decorator
                    for decorator in original_decorators
                ),
                replacement,
            ])
            repaired_tree = ast.parse(
                replacement,
                filename=f"<repair:{symbol}>",
            )
            repaired_definition = repaired_tree.body[0]
        if isinstance(original_definition, ast.AsyncFunctionDef) != isinstance(
            repaired_definition, ast.AsyncFunctionDef
        ):
            return generated_files, [f"Repair changed async form for {symbol}."]

        if argument_shape(original_definition.args) != argument_shape(
            repaired_definition.args
        ) and not approved_signature_correction:
            return generated_files, [f"Repair changed the callable signature for {symbol}."]

        original_parameters = [
            *original_definition.args.posonlyargs,
            *original_definition.args.args,
            *original_definition.args.kwonlyargs,
            *(
                [original_definition.args.vararg]
                if original_definition.args.vararg
                else []
            ),
            *(
                [original_definition.args.kwarg]
                if original_definition.args.kwarg
                else []
            ),
        ]
        repaired_parameters = [
            *repaired_definition.args.posonlyargs,
            *repaired_definition.args.args,
            *repaired_definition.args.kwonlyargs,
            *(
                [repaired_definition.args.vararg]
                if repaired_definition.args.vararg
                else []
            ),
            *(
                [repaired_definition.args.kwarg]
                if repaired_definition.args.kwarg
                else []
            ),
        ]
        for original_parameter, repaired_parameter in zip(
            original_parameters,
            repaired_parameters,
        ):
            original_annotation_text = (
                ast.unparse(original_parameter.annotation)
                if original_parameter.annotation is not None
                else ""
            )
            if (
                original_parameter.annotation is not None
                and original_annotation_text not in {"Any", "object"}
                and ast.dump(
                    original_parameter.annotation,
                    include_attributes=False,
                )
                != ast.dump(
                    repaired_parameter.annotation,
                    include_attributes=False,
                )
            ):
                return generated_files, [
                    f"Repair changed the annotation for "
                    f"{symbol}.{original_parameter.arg}."
                ]
        original_return = (
            ast.dump(original_definition.returns, include_attributes=False)
            if original_definition.returns is not None
            else ""
        )
        repaired_return = (
            ast.dump(repaired_definition.returns, include_attributes=False)
            if repaired_definition.returns is not None
            else ""
        )
        original_return_text = (
            ast.unparse(original_definition.returns)
            if original_definition.returns is not None
            else ""
        )
        repaired_return_text = (
            ast.unparse(repaired_definition.returns)
            if repaired_definition.returns is not None
            else ""
        )
        coarse_container_return = bool(
            original_return_text.startswith(("tuple[", "list[", "dict[", "set["))
            and any(token in original_return_text for token in ("object", "Any"))
            and repaired_return_text.split("[", 1)[0]
            == original_return_text.split("[", 1)[0]
        )
        if (
            original_return
            and original_return_text not in {"Any", "object"}
            and original_return != repaired_return
            and str(original or "").strip()
            and not coarse_container_return
        ):
            return generated_files, [f"Repair changed the return annotation for {symbol}."]
        if [
            ast.dump(item, include_attributes=False)
            for item in original_definition.decorator_list
        ] != [
            ast.dump(item, include_attributes=False)
            for item in repaired_definition.decorator_list
        ]:
            return generated_files, [f"Repair changed decorators for {symbol}."]
        unresolved_before = set(_unresolved_generated_names(owner_tree))
        matched, corrected, error = _edit_python_symbol_source(
            source,
            target_symbol=symbol,
            replacement=replacement,
            filename=path_text,
            operation="replace_symbol",
        )
        if not matched:
            return generated_files, [error or f"Could not replace generated symbol {symbol}."]
        try:
            corrected_tree = ast.parse(corrected, filename=path_text)
            compile(corrected_tree, path_text, "exec")
        except (SyntaxError, ValueError) as exc:
            return generated_files, [f"Repaired owner module did not compile: {exc}"]
        introduced_unresolved = sorted(
            set(_unresolved_generated_names(corrected_tree)) - unresolved_before
        )
        introduced_unresolved = [
            name
            for name in introduced_unresolved
            if not _verified_installed_qt_symbol(name)
        ]
        introduced_unresolved = [
            name
            for name in introduced_unresolved
            if name.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
        ]
        if introduced_unresolved:
            resolved_records, _import_fixes = (
                resolve_project_edit_standard_library_symbols([
                    (path_text, original, corrected)
                ])
            )
            corrected = resolved_records[0][2]
            corrected_tree = ast.parse(corrected, filename=path_text)
            compile(corrected_tree, path_text, "exec")
            introduced_unresolved = sorted(
                set(_unresolved_generated_names(corrected_tree)) - unresolved_before
            )
        invented_exceptions = {
            name
            for name in introduced_unresolved
            if name.endswith(("Error", "Exception"))
        }
        if introduced_unresolved and invented_exceptions == set(introduced_unresolved):
            class _UseRuntimeError(ast.NodeTransformer):
                def visit_Name(self, child: ast.Name) -> ast.AST:
                    if (
                        isinstance(child.ctx, ast.Load)
                        and child.id in invented_exceptions
                    ):
                        return ast.copy_location(
                            ast.Name(id="RuntimeError", ctx=child.ctx),
                            child,
                        )
                    return child

            corrected_tree = _UseRuntimeError().visit(corrected_tree)
            ast.fix_missing_locations(corrected_tree)
            corrected = ast.unparse(corrected_tree).rstrip() + "\n"
            compile(corrected_tree, path_text, "exec")
            introduced_unresolved = sorted(
                set(_unresolved_generated_names(corrected_tree)) - unresolved_before
            )
        if introduced_unresolved:
            return generated_files, [
                "Repaired owner module introduces undefined names: "
                + ", ".join(introduced_unresolved)
            ]
        updated[index] = (path_text, original, corrected)
        return updated, []
    return generated_files, [f"Generated repair path was not found: {path}"]


def _resolve_import_spec(
    target_path: Path,
    module: str,
    level: int,
    imported_name: str,
    *,
    project_root: str | None,
    candidate_sources: dict[str, str],
) -> tuple[bool, str]:
    top_level = module.split(".", 1)[0] if module else imported_name.split(".", 1)[0]
    if top_level in _HOST_RUNTIME_MODULES:
        return True, f"Host-provided runtime import is explicitly accounted for: {top_level}."
    if level == 0 and top_level in getattr(sys, "stdlib_module_names", set()):
        if imported_name and imported_name != "*":
            try:
                stdlib_module = importlib.import_module(module)
            except (ImportError, ModuleNotFoundError) as exc:
                return False, f"Standard-library import failed: {module}: {exc}"
            public_exports = getattr(stdlib_module, "__all__", None)
            is_public_attribute = (
                hasattr(stdlib_module, imported_name)
                and (
                    public_exports is None
                    or imported_name in public_exports
                )
            )
            if not is_public_attribute:
                try:
                    child_spec = importlib.util.find_spec(
                        f"{module}.{imported_name}"
                    )
                except (ImportError, ModuleNotFoundError, ValueError):
                    child_spec = None
                if child_spec is None:
                    return False, (
                        f"Standard-library module {module!r} does not expose "
                        f"{imported_name!r}."
                    )
        return True, f"Standard-library import resolved: {module or imported_name}."

    local_path = _local_module_path(
        target_path,
        module,
        level,
        project_root=project_root,
        candidate_paths=set(candidate_sources),
    )
    if local_path is not None:
        if imported_name and imported_name != "*" and local_path.suffix == ".py":
            child = local_path.parent / imported_name
            child_file = child.with_suffix(".py")
            child_init = child / "__init__.py"
            source_override = candidate_sources.get(str(local_path.resolve()))
            if not _local_module_exports(local_path, imported_name, source_override=source_override):
                if not (
                    child_file.is_file()
                    or child_init.is_file()
                    or str(child_file.resolve()) in candidate_sources
                    or str(child_init.resolve()) in candidate_sources
                ):
                    fallback_module = _resolve_local_module_symbol_fallback(
                        local_path,
                        source_override,
                        imported_name,
                    )
                    if fallback_module is not None:
                        return True, (
                            f"Project-local import does not expose {imported_name!r}; "
                            f"resolved via {fallback_module}."
                        )
                    return False, f"Project-local import does not expose {imported_name!r}: {local_path}."
        return True, f"Project-local import resolved statically: {local_path}."

    if level == 0:
        try:
            if importlib.util.find_spec(top_level) is not None:
                return True, f"Installed dependency resolved: {top_level}."
        except (ImportError, AttributeError, ValueError):
            pass
    import_label = "." * level + module + (f".{imported_name}" if imported_name else "")
    return False, f"New import could not be resolved or accounted for: {import_label}."


def _is_test_path(path: Path) -> bool:
    stem = path.stem.lower()
    return (
        stem.startswith("test_")
        or stem.endswith(("_test", "_tests"))
        or any(part.lower() in {"test", "tests"} for part in path.parts)
    )


def build_project_edit_file_generation_stages(
    plan: ProjectEditPlan,
) -> list[tuple[str, str, ProjectEditPromptStage]]:
    """Build bounded full-file stages for an explicitly named multi-file edit."""

    discovery = dict(plan.discovery or {})
    if discovery.get("evidence_mode") != "explicit_index_snapshot":
        return []
    candidates = [
        item
        for item in discovery.get("candidates") or []
        if isinstance(item, dict) and Path(str(item.get("path") or "")).suffix.lower() == ".py"
    ]
    unique: dict[str, dict[str, Any]] = {}
    for item in candidates:
        unique.setdefault(str(Path(str(item.get("path"))).resolve()), item)
    if len(unique) < 3:
        return []

    active = str(Path(str(discovery.get("active_path") or plan.active_path or "")).resolve())
    ordered_paths = sorted(
        unique,
        key=lambda value: (
            2 if _is_test_path(Path(value)) else 1 if value == active else 0,
            value.lower(),
        ),
    )
    stages: list[tuple[str, str, ProjectEditPromptStage]] = []
    for index, path_text in enumerate(ordered_paths, start=1):
        path = Path(path_text)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return []
        is_test = _is_test_path(path)
        stage = ProjectEditPromptStage(
            key=f"file_generation_{index}",
            label=f"Generating {path.name}",
            system_prompt=(
                "You are a bounded senior Python implementation worker. Return one complete importable Python "
                "file as raw source. Do not return JSON, Markdown, commentary, a diff, or a partial symbol."
            ),
            user_prompt=f"""User objective:
{plan.prompt}

File owned by this stage:
{path}

Exact current file:
```python
{source}
```

Task:
Return the complete final source for this file after fulfilling every part of the objective owned by it.
Preserve behavior not changed by the request. Resolve project-local imports at function scope when needed to avoid cycles.
Use clear parameter and local names. Document every public callable with a behavioral summary, one `:param name:` field per public parameter, and `:return:` whenever it returns a value.
{"Implement substantive unittest methods for every requested behavior; a pass-only test class is forbidden. Every test_* method must directly assert an explicit expected value, state transition, ordered result, callback argument sequence, or requested exception. Merely calling production code, relying on assertions inside an indirectly invoked callback, or checking only broad types is not behavioral proof." if is_test else "Implement production behavior fully; do not add placeholders, pass bodies, or speculative APIs."}
{"Call only public functions, classes, and methods visibly defined in the completed dependency context. Never invent convenience APIs for a test." if is_test else ""}
The first response character must belong to valid Python source. Return raw Python only.
""",
            model_tier="local_code",
            num_ctx=6144,
            num_predict=1300 if is_test else 1100,
            timeout=90,
            no_progress_seconds=22,
            prefer_coder=True,
            coder_preference="standard" if is_test else "small",
            response_format="",
        )
        stages.append((path_text, source, stage))
    return stages


def _artifact_manifest_item_is_test(item: dict[str, Any]) -> bool:
    """Infer test ownership from the complete manifest row, not one model boolean."""

    path = Path(str(item.get("path") or "").replace("\\", "/"))
    evidence = " ".join([
        path.stem,
        str(item.get("purpose") or ""),
    ]).lower()
    return bool(item.get("is_test")) or _is_test_path(path) or bool(
        re.search(r"\b(?:tests?|unittest|testcase|coverage|behavioral proof)\b", evidence)
    )


def parse_project_edit_artifact_manifest(
    response: str,
    *,
    project_root: str,
    requirement_ledger: list[dict[str, str]] | None = None,
    strict_architecture: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate and dependency-order a generated artifact manifest."""

    try:
        payload = json.loads(str(response or ""))
    except (TypeError, ValueError) as exc:
        return [], [f"Artifact manifest JSON did not parse: {exc}"]
    raw_files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(raw_files, list) or len(raw_files) < 2:
        return [], ["Artifact manifest must contain focused production and test files."]
    raw_contracts = (
        payload.get("integration_contracts") if isinstance(payload, dict) else []
    ) or []
    if isinstance(raw_contracts, dict):
        integration_contracts = [
            f"{field}: {str(value).strip()}"
            for field in (
                "canonical_owners",
                "signatures",
                "shared_invariants",
                "data_layout",
                "errors",
            )
            for value in raw_contracts.get(field) or []
            if str(value).strip()
        ]
    else:
        integration_contracts = [
            str(value).strip()
            for value in raw_contracts
            if str(value).strip()
        ]
    if not integration_contracts:
        integration_contracts = list(dict.fromkeys(
            str(value).strip()
            for raw in raw_files
            if isinstance(raw, dict)
            for value in raw.get("integration_contracts") or []
            if str(value).strip()
        ))

    root = Path(project_root).resolve()
    authoritative_requirements = {
        str(item.get("id") or ""): str(item.get("text") or "")
        for item in requirement_ledger or []
        if str(item.get("id") or "") and str(item.get("text") or "")
        and str(item.get("scope") or "artifact") == "artifact"
    }
    normalized_paths: dict[str, str] = {}
    for raw in raw_files:
        item = dict(raw) if isinstance(raw, dict) else {}
        original_path = str(item.get("path") or "").replace("\\", "/").strip("/")
        path = Path(original_path)
        if path.is_absolute():
            try:
                normalized_paths[original_path] = str(path.resolve().relative_to(root)).replace("\\", "/")
                path = Path(normalized_paths[original_path])
            except ValueError:
                pass
        if (
            len(path.parts) >= 2
            and path.parts[0].lower() == "src"
            and (root / path.parts[1]).is_dir()
        ):
            normalized_paths[original_path] = str(Path(*path.parts[1:])).replace("\\", "/")
            path = Path(normalized_paths[original_path])
        declared_test = _artifact_manifest_item_is_test(item)
        if (
            declared_test
            and original_path
            and not path.is_absolute()
            and path.suffix.lower() == ".py"
            and not any(part.startswith(".") for part in path.parts)
            and tuple(part.lower() for part in path.parts[:3])
            != ("examples", "tech_connector", "tests")
        ):
            filename = path.name
            if not filename.startswith("test_"):
                filename = f"test_{filename}"
            normalized_paths[original_path] = f"tech_connector/examples/tests/{filename}"
        elif (
            not declared_test
            and original_path
            and path.parent == Path(".")
            and path.suffix.lower() == ".py"
        ):
            normalized_paths[original_path] = f"tech_connector/services/generated/{path.name}"

    files: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for raw in raw_files:
        item = dict(raw) if isinstance(raw, dict) else {}
        declared_test = _artifact_manifest_item_is_test(item)
        original_path = str(item.get("path") or "").replace("\\", "/").strip("/")
        path_text = normalized_paths.get(original_path, original_path)
        path = Path(path_text)
        if (
            not declared_test
            and path.parent == Path(".")
            and path.suffix.lower() == ".py"
        ):
            path_text = f"tech_connector/services/generated/{path.name}"
            path = Path(path_text)
        parts = path.parts
        if (
            not path_text
            or path.is_absolute()
            or path.suffix.lower() != ".py"
            or any(part.startswith(".") for part in parts)
            or any(part.lower().endswith((".sqlite", ".sqlite3", ".db")) for part in parts)
        ):
            errors.append(f"Artifact manifest has an unsafe or non-Python path: {path_text or '(empty)'}")
            continue
        resolved = (root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"Artifact manifest path escapes the project root: {path_text}")
            continue
        requirements = [
            str(value).strip() for value in item.get("requirements") or [] if str(value).strip()
        ]
        requirement_ids = [
            str(value).strip() for value in item.get("requirement_ids") or [] if str(value).strip()
        ]
        if authoritative_requirements:
            requirement_ids = [
                f"R{value}" if value.isdigit() and f"R{value}" in authoritative_requirements else value
                for value in requirement_ids
            ]
            unknown_ids = [value for value in requirement_ids if value not in authoritative_requirements]
            if unknown_ids:
                errors.append(
                    f"Artifact manifest uses unknown requirement IDs ({path_text}): {', '.join(unknown_ids)}"
                )
            requirements = [
                authoritative_requirements[value]
                for value in requirement_ids
                if value in authoritative_requirements
            ]
        purpose = str(item.get("purpose") or "").strip()
        if not purpose or not requirements:
            errors.append(f"Artifact manifest file lacks purpose or owned requirements: {path_text}")
        contracts = [
            str(value).strip() for value in item.get("contracts") or [] if str(value).strip()
        ]
        algorithm_steps = [
            str(value).strip() for value in item.get("algorithm_steps") or [] if str(value).strip()
        ]
        validation_steps = [
            str(value).strip() for value in item.get("validation_steps") or [] if str(value).strip()
        ]
        public_symbols: list[str] = []
        for value in item.get("public_symbols") or []:
            raw_symbol = str(value).strip()
            if not raw_symbol:
                continue
            public_symbols.extend(
                part.strip(" '\"")
                for part in re.split(r"['\"]\s*,\s*['\"]", raw_symbol)
                if part.strip(" '\"")
            )
        inferred_test = _is_test_path(path)
        if declared_test != inferred_test:
            errors.append(
                "Artifact manifest test classification does not match its path: "
                f"{path_text}. Test files must use tech_connector/examples/tests/test_*.py with is_test=true; "
                "production files must use is_test=false."
            )
        manifest_entry = {
            "path": path_text,
            "absolute_path": str(resolved),
            "purpose": purpose,
            "requirements": requirements,
            "requirement_ids": requirement_ids,
            "public_symbols": public_symbols,
            "contracts": contracts,
            "algorithm_steps": algorithm_steps,
            "validation_steps": validation_steps,
            "integration_contracts": integration_contracts,
            "ownership_attributions": [],
            "dependency_repairs": [],
            "depends_on": [
                normalized_paths.get(
                    str(value).replace("\\", "/").strip("/"),
                    str(value).replace("\\", "/").strip("/"),
                )
                for value in item.get("depends_on") or []
                if str(value).strip()
                and str(value).split(".", 1)[0] not in set(getattr(sys, "stdlib_module_names", ()))
            ],
            "is_test": inferred_test,
        }
        existing = files.get(path_text)
        if existing is None:
            files[path_text] = manifest_entry
        elif existing["is_test"] != manifest_entry["is_test"]:
            errors.append(
                f"Artifact manifest assigns conflicting roles to one path: {path_text}"
            )
        else:
            for key in (
                "requirements",
                "requirement_ids",
                "public_symbols",
                "contracts",
                "algorithm_steps",
                "validation_steps",
                "depends_on",
            ):
                existing[key] = list(dict.fromkeys([*existing[key], *manifest_entry[key]]))
            if manifest_entry["purpose"] not in existing["purpose"]:
                existing["purpose"] += "; " + manifest_entry["purpose"]

    if strict_architecture and len(files) > 5:
        while len(files) > 5:
            role_groups = [
                [item for item in files.values() if not item["is_test"]],
                [item for item in files.values() if item["is_test"]],
            ]
            merge_group = next(
                (group for group in role_groups if len(group) > 1),
                [],
            )
            if not merge_group:
                break
            source = min(
                merge_group,
                key=lambda item: (
                    len(item["requirement_ids"]),
                    len(item["public_symbols"]),
                    item["path"],
                ),
            )
            targets = {
                item["path"]: item
                for item in merge_group
                if item is not source
            }
            target = _select_artifact_requirement_owner(
                targets,
                " ".join([
                    source["purpose"],
                    *source["requirements"],
                    *source["public_symbols"],
                ]),
            )
            source_path = source["path"]
            target_path = target["path"]
            target["purpose"] += "; " + source["purpose"]
            for key in (
                "requirements",
                "requirement_ids",
                "public_symbols",
                "contracts",
                "algorithm_steps",
                "validation_steps",
            ):
                target[key] = list(dict.fromkeys([*target[key], *source[key]]))
            target["ownership_attributions"] = [
                *target["ownership_attributions"],
                *source["ownership_attributions"],
            ]
            target["depends_on"] = list(dict.fromkeys([
                target_path if dependency == source_path else dependency
                for dependency in [*target["depends_on"], *source["depends_on"]]
                if dependency not in {source_path, target_path}
            ]))
            target["dependency_repairs"].append(
                f"Combined bounded owner {source_path} into {target_path}."
            )
            del files[source_path]
            for item in files.values():
                item["depends_on"] = list(dict.fromkeys(
                    target_path if dependency == source_path else dependency
                    for dependency in item["depends_on"]
                    if (target_path if dependency == source_path else dependency)
                    != item["path"]
                ))

    if strict_architecture:
        symbol_owners: dict[str, list[str]] = {}
        for item in files.values():
            if item["is_test"]:
                continue
            for public_symbol in item["public_symbols"]:
                symbol_name = public_symbol.split("(", 1)[0].rsplit(".", 1)[-1]
                symbol_owners.setdefault(symbol_name, []).append(item["path"])
        duplicate_owners = {
            symbol: owners
            for symbol, owners in symbol_owners.items()
            if len(set(owners)) > 1
            and symbol[:1].isupper()
        }
        if duplicate_owners:
            return [], [
                "Artifact manifest assigns one production API to multiple owners: "
                + "; ".join(
                    f"{symbol} -> {', '.join(sorted(set(owners)))}"
                    for symbol, owners in sorted(duplicate_owners.items())
                )
            ]

    if strict_architecture:
        signature_contracts = [
            value.split(":", 1)[-1].strip()
            for value in integration_contracts
            if value.startswith("signatures:")
        ]
        state_contracts = [
            value
            for value in integration_contracts
            if value.startswith(("shared_invariants:", "data_layout:", "errors:"))
        ]

        def contract_terms(value: str) -> set[str]:
            expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
            return {
                token
                for token in re.findall(r"[a-z0-9]+", expanded.lower())
                if token not in {
                    "a", "an", "and", "class", "handler", "manager",
                    "module", "object", "returns", "the",
                }
            }

        for item in files.values():
            if item["is_test"]:
                continue
            for public_symbol in item["public_symbols"]:
                symbol_name = public_symbol.split("(", 1)[0].rsplit(".", 1)[-1]
                if symbol_name.endswith(("Error", "Exception")):
                    continue
                symbol_terms = contract_terms(symbol_name)
                ranked_signatures = sorted(
                    (
                        (len(symbol_terms & contract_terms(signature)), signature)
                        for signature in signature_contracts
                    ),
                    reverse=True,
                )
                best_score = ranked_signatures[0][0] if ranked_signatures else 0
                matched = [
                    signature
                    for score, signature in ranked_signatures
                    if score > 0 and score == best_score
                ][:2]
                for signature in matched:
                    item["contracts"].append(
                        f"{symbol_name} implements exact package signature {signature}."
                    )
                    item["algorithm_steps"].append(
                        f"Implement {signature} using the accepted package state, "
                        "invariants, synchronization, and error contracts."
                    )
            if state_contracts:
                item["contracts"].append(
                    "Relevant accepted state and failure contracts: "
                    + " | ".join(state_contracts)
                )
            item["contracts"] = list(dict.fromkeys(item["contracts"]))
            item["algorithm_steps"] = list(dict.fromkeys(item["algorithm_steps"]))

    if strict_architecture:
        if not integration_contracts:
            errors.append(
                "Artifact manifest lacks package-wide integration_contracts."
            )
        else:
            path_like_contracts = [
                value
                for value in integration_contracts
                if not value.startswith("canonical_owners:")
                and (
                    value.lower().endswith(".py")
                    or re.match(r"^[A-Za-z]:[\\/]", value)
                    or (
                        ("/" in value or "\\" in value)
                        and len(value.split()) <= 3
                    )
                )
            ]
            if path_like_contracts:
                errors.append(
                    "Artifact integration_contracts contain file paths instead of executable "
                    "cross-file contracts: " + ", ".join(path_like_contracts)
                )
            contract_blob = " ".join(integration_contracts)
            if not re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\s*\([^)]*\)", contract_blob):
                errors.append(
                    "Artifact integration_contracts lack an exact callable signature with defaults."
                )
            requirement_blob = " ".join(authoritative_requirements.values()).lower()
            contract_lower = contract_blob.lower()
            required_protocol_terms = _required_project_edit_protocol_terms(
                requirement_blob
            )
            missing_protocol_terms = [
                term
                for term in required_protocol_terms
                if not _project_edit_protocol_term_present(term, contract_lower)
            ]
            if missing_protocol_terms:
                errors.append(
                    "Artifact integration_contracts omit prompt-critical protocol terms: "
                    + ", ".join(missing_protocol_terms)
                )
            if (
                any(term in requirement_blob for term in ("binary", "byte", "frame"))
                and not any(
                    term in contract_lower
                    for term in ("layout", "field order", "offset", "struct", "byte order")
                )
            ):
                errors.append(
                    "Artifact integration_contracts do not define the shared binary/data layout."
                )
        for path_text, item in files.items():
            missing_contract_parts = []
            if not item["contracts"]:
                missing_contract_parts.append("contracts")
            if not item["algorithm_steps"]:
                missing_contract_parts.append("algorithm_steps")
            if not item["validation_steps"]:
                missing_contract_parts.append("validation_steps")
            if not item["is_test"] and not item["public_symbols"]:
                missing_contract_parts.append("public_symbols")
            if missing_contract_parts:
                errors.append(
                    f"Artifact manifest lacks executable architecture details ({path_text}): "
                    + ", ".join(missing_contract_parts)
                )
    if errors:
        return [], errors
    if not any(not item["is_test"] for item in files.values()) or not any(
        item["is_test"] for item in files.values()
    ):
        return [], ["Artifact manifest must include at least one production file and one test file."]
    production_symbols = {
        str(symbol).split("(", 1)[0].rsplit(".", 1)[-1].strip()
        for item in files.values()
        if not item["is_test"]
        for symbol in item["public_symbols"]
        if str(symbol).strip()
    }
    duplicated_test_symbols = sorted({
        str(symbol).split("(", 1)[0].rsplit(".", 1)[-1].strip()
        for item in files.values()
        if item["is_test"]
        for symbol in item["public_symbols"]
        if str(symbol).strip()
    } & production_symbols)
    if duplicated_test_symbols:
        return [], [
            "Artifact test files must import production APIs instead of redeclaring them: "
            + ", ".join(duplicated_test_symbols)
        ]

    if authoritative_requirements:
        assigned = {
            requirement_id
            for item in files.values()
            for requirement_id in item["requirement_ids"]
        }
        missing_ids = [value for value in authoritative_requirements if value not in assigned]
        for requirement_id in missing_ids:
            requirement_text = authoritative_requirements[requirement_id]
            for owner_kind in (False, True) if strict_architecture else (None,):
                candidates = {
                    path: item
                    for path, item in files.items()
                    if owner_kind is None or bool(item["is_test"]) == owner_kind
                }
                if not candidates:
                    continue
                owner = _select_artifact_requirement_owner(candidates, requirement_text)
                owner["requirement_ids"].append(requirement_id)
                owner["requirements"].append(requirement_text)
                owner["ownership_attributions"].append({
                    "requirement_id": requirement_id,
                    "reason": "deterministic semantic ownership fallback",
                })

        if strict_architecture:
            for requirement_id in authoritative_requirements:
                requirement_text = authoritative_requirements[requirement_id]
                owners = [
                    item for item in files.values()
                    if requirement_id in item["requirement_ids"]
                ]
                if not any(not item["is_test"] for item in owners):
                    production = {
                        path: item for path, item in files.items() if not item["is_test"]
                    }
                    if production:
                        owner = _select_artifact_requirement_owner(production, requirement_text)
                        owner["requirement_ids"].append(requirement_id)
                        owner["requirements"].append(requirement_text)
                        owner["ownership_attributions"].append({
                            "requirement_id": requirement_id,
                            "reason": "missing production owner inferred deterministically",
                        })
                if not any(item["is_test"] for item in owners):
                    tests = {
                        path: item for path, item in files.items() if item["is_test"]
                    }
                    if tests:
                        owner = _select_artifact_requirement_owner(tests, requirement_text)
                        owner["requirement_ids"].append(requirement_id)
                        owner["requirements"].append(requirement_text)
                        owner["ownership_attributions"].append({
                            "requirement_id": requirement_id,
                            "reason": "missing behavioral proof owner inferred deterministically",
                        })

    if strict_architecture:
        seen_test_contracts: dict[tuple[tuple[str, ...], str], str] = {}
        for item in files.values():
            if not item["is_test"]:
                continue
            signature = (
                tuple(sorted(item["requirement_ids"])),
                " ".join(item["purpose"].lower().split()),
            )
            prior = seen_test_contracts.get(signature)
            if prior:
                errors.append(
                    "Artifact manifest duplicates test responsibility: "
                    f"{prior} and {item['path']} own the same requirement set."
                )
            else:
                seen_test_contracts[signature] = item["path"]

    for item in files.values():
        reconciled_dependencies = []
        for dependency in item["depends_on"]:
            if dependency in files:
                reconciled_dependencies.append(dependency)
                continue
            dependency_path = Path(dependency)
            matches = [
                path
                for path in files
                if Path(path).name == dependency_path.name
                or Path(path).stem == dependency_path.stem
            ]
            if len(matches) == 1:
                reconciled_dependencies.append(matches[0])
            else:
                reconciled_dependencies.append(dependency)
        item["depends_on"] = list(dict.fromkeys(reconciled_dependencies))
        if not item["is_test"]:
            item["depends_on"] = [
                dependency
                for dependency in item["depends_on"]
                if not (
                    (dependency in files and files[dependency]["is_test"])
                    or _is_test_path(Path(dependency))
                )
            ]
        unknown = [dependency for dependency in item["depends_on"] if dependency not in files]
        if unknown:
            if strict_architecture:
                item["depends_on"] = [
                    dependency
                    for dependency in item["depends_on"]
                    if dependency not in unknown
                ]
                item["dependency_repairs"].append(
                    "Collapsed absent manifest dependency into this file's owned "
                    "implementation: " + ", ".join(unknown)
                )
            else:
                errors.append(
                    f"Artifact manifest dependency is not another manifest path ({item['path']}): {', '.join(unknown)}"
                )
        item["depends_on"] = [
            dependency for dependency in item["depends_on"] if dependency != item["path"]
        ]
    production_paths = [item["path"] for item in files.values() if not item["is_test"]]
    for item in files.values():
        if item["is_test"]:
            item["depends_on"] = list(dict.fromkeys([*item["depends_on"], *production_paths]))
    if errors:
        return [], errors

    ordered: list[dict[str, Any]] = []
    pending = dict(files)
    while pending:
        ready = [
            item for item in pending.values()
            if all(dependency not in pending for dependency in item["depends_on"])
        ]
        if not ready:
            return [], ["Artifact manifest contains a dependency cycle."]
        ready.sort(key=lambda item: (item["is_test"], item["path"].lower()))
        for item in ready:
            ordered.append(item)
            pending.pop(item["path"])
    return ordered, []


def _reconcile_existing_explicit_symbols(
    item: dict[str, Any],
    requirement_text: str,
) -> list[Any]:
    """Prefer explicitly named existing declarations over filename placeholders.

    :param item: Artifact-manifest file record.
    :param requirement_text: Combined authoritative request requirements.
    :return: Reconciled public-symbol declarations for semantic planning.
    """

    public_symbols = list(item.get("public_symbols") or [])
    path = Path(str(item.get("absolute_path") or item.get("path") or ""))
    if not path.is_file() or path.suffix.casefold() != ".py":
        return public_symbols
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return public_symbols
    existing_nodes = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    existing = {
        name: (
            "class"
            if isinstance(node, ast.ClassDef)
            else "async_function"
            if isinstance(node, ast.AsyncFunctionDef)
            else "function"
        )
        for name, node in existing_nodes.items()
    }
    existing_method_owners: dict[str, list[str]] = {}
    for class_name, node in existing_nodes.items():
        if not isinstance(node, ast.ClassDef):
            continue
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                existing_method_owners.setdefault(method.name, []).append(class_name)

    def symbol_name(value: Any) -> str:
        if isinstance(value, Mapping):
            return str(
                value.get("qualified_name")
                or value.get("name")
                or value.get("owner")
                or ""
            ).split("(", 1)[0].rsplit(".", 1)[-1].strip()
        return str(value).split("(", 1)[0].rsplit(".", 1)[-1].strip()

    mentioned_existing = {
        name: kind
        for name, kind in existing.items()
        if re.search(rf"(?<![.\w]){re.escape(name)}\b", requirement_text)
    }
    if not mentioned_existing:
        return public_symbols
    reconciled: list[Any] = []
    for value in public_symbols:
        name = symbol_name(value)
        inferred = bool(
            isinstance(value, Mapping) and value.get("inferred_from_request")
        )
        explicitly_created = bool(
            name
            and re.search(
                r"\b(?:add|create|define|implement|introduce|write)\b"
                rf"[^.!?\n]{{0,100}}(?<![.\w]){re.escape(name)}\b",
                requirement_text,
                flags=re.IGNORECASE,
            )
        )
        filename_placeholder = bool(
            name
            and name.casefold() == path.stem.casefold()
            and name not in existing
        )
        method_owners = existing_method_owners.get(name) or []
        existing_owned_method = bool(
            name not in existing
            and len(method_owners) == 1
            and re.search(
                rf"(?<![.\w]){re.escape(method_owners[0])}\b",
                requirement_text,
            )
            and not re.search(
                rf"\b(?:module[- ]level|top[- ]level|standalone)\s+"
                rf"(?:function\s+)?{re.escape(name)}\b"
                rf"|\bfunction\s+{re.escape(name)}\b",
                requirement_text,
                flags=re.IGNORECASE,
            )
        )
        if existing_owned_method:
            # The class declaration already carries exact method signatures.
            # Keeping a bare duplicate would invent a module-level function.
            continue
        if (
            (inferred or filename_placeholder)
            and name not in existing
            and not explicitly_created
        ):
            continue
        if name in existing:
            existing_symbol = (
                dict(value)
                if isinstance(value, Mapping)
                else {
                    "name": name,
                    "qualified_name": name,
                }
            )
            existing_symbol["kind"] = existing[name]
            existing_symbol["existing_declaration"] = True
            node = existing_nodes[name]
            if isinstance(node, ast.ClassDef):
                existing_symbol["inferred_callable_signatures"] = [
                    (
                        f"{'async def' if isinstance(method, ast.AsyncFunctionDef) else 'def'} "
                        f"{method.name}({ast.unparse(method.args)})"
                        + (
                            f" -> {ast.unparse(method.returns)}"
                            if method.returns is not None
                            else ""
                        )
                    )
                    for method in node.body
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and (
                        not method.name.startswith("_")
                        or method.name in {"__init__", "__len__"}
                    )
                ]
            reconciled.append(existing_symbol)
            continue
        reconciled.append(value)
    known_names = {symbol_name(value) for value in reconciled}
    for name, kind in mentioned_existing.items():
        if name in known_names:
            continue
        symbol: dict[str, Any] = {
            "name": name,
            "qualified_name": name,
            "kind": kind,
            "existing_declaration": True,
        }
        node = existing_nodes[name]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            signature = f"{prefix} {name}({ast.unparse(node.args)})"
            if node.returns is not None:
                signature += f" -> {ast.unparse(node.returns)}"
            symbol["inferred_callable_signatures"] = [signature]
        reconciled.append(symbol)
    return reconciled


def build_deterministic_project_edit_chunk_plan(
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve only requirements whose implementation owner is structurally proven."""

    combined_requirement_text = " ".join(
        str(row.get("text") or row.get("requirement") or "")
        for row in requirement_ledger
    )
    for item in manifest:
        public_symbols = _reconcile_existing_explicit_symbols(
            item,
            combined_requirement_text,
        )
        item["public_symbols"] = public_symbols

        def public_symbol_name(value: Any) -> str:
            if isinstance(value, Mapping):
                return str(value.get("name") or value.get("owner") or "")
            return str(value).split("(", 1)[0].strip()

        requirement_texts = [
            str(row.get("text") or row.get("requirement") or "")
            for row in requirement_ledger
        ]
        ui_surface_requested = bool(
            re.search(
                r"\b(?:qt|pyside[26]?|pyqt[56]?)\b",
                combined_requirement_text,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\b(?:ui|dialog|window|widget|panel)\b",
                combined_requirement_text,
                flags=re.IGNORECASE,
            )
        )
        explicitly_named_class = bool(re.search(
            r"\b[A-Z][A-Za-z0-9_]*(?:Dialog|Window|Widget|Panel|UI)\b",
            combined_requirement_text,
        ))
        has_class_symbol = any(
            (
                isinstance(value, Mapping)
                and str(value.get("kind") or "").casefold() == "class"
            )
            or public_symbol_name(value).rsplit(".", 1)[-1].endswith(
                ("Dialog", "Window", "Widget", "Panel", "Dock")
            )
            for value in public_symbols
        )
        if (
            ui_surface_requested
            and not explicitly_named_class
            and not has_class_symbol
        ):
            from tech_connector.services.capability_resolution_service import (
                extract_capability_intents,
            )

            intents = extract_capability_intents(combined_requirement_text)
            primary_intent = next(
                (
                    intent
                    for intent in intents
                    if intent.action not in {"create", "build"}
                ),
                intents[0] if intents else None,
            )
            name_parts: list[str] = []
            if primary_intent is not None:
                contextual_terms = {
                    str(host).casefold() for host in primary_intent.hosts
                }
                contextual_terms.update({
                    "api",
                    "build",
                    "capability",
                    "code",
                    "control",
                    "controls",
                    "create",
                    "expose",
                    "exposes",
                    "file",
                    "function",
                    "internal",
                    "method",
                    "panel",
                    "pyside",
                    "pyside2",
                    "pyside6",
                    "pyqt",
                    "pyqt5",
                    "pyqt6",
                    "qt",
                    "tool",
                    "ui",
                    "use",
                    "uses",
                    "widget",
                    "window",
                    "write",
                    "writing",
                })
                name_parts.extend(
                    term
                    for term in primary_intent.object_terms
                    if term.casefold() not in contextual_terms
                )
                name_parts = list(dict.fromkeys(name_parts))[:3]
                if (
                    primary_intent.action.casefold() not in contextual_terms
                    and primary_intent.action.casefold()
                    not in {part.casefold() for part in name_parts}
                ):
                    name_parts.append(primary_intent.action)
            if not name_parts:
                name_parts.extend(
                    part
                    for part in Path(
                        str(item.get("absolute_path") or item.get("path") or "tool")
                    ).stem.split("_")
                    if part
                )
            inferred_class_name = "".join(
                part[:1].upper() + part[1:]
                for part in name_parts
                if part
            ) + "Dialog"
            public_symbols = [{
                "name": inferred_class_name,
                "qualified_name": inferred_class_name,
                "kind": "class",
                "inferred_from_request": True,
            }]

        def has_declaration_evidence(value: Any) -> bool:
            if (
                isinstance(value, Mapping)
                and bool(
                    value.get("inferred_from_request")
                    or value.get("existing_declaration")
                )
            ):
                return True
            symbol_name = public_symbol_name(value).rsplit(".", 1)[-1]
            if not symbol_name or not symbol_name[:1].isupper():
                return True
            declaration_nouns = (
                r"class|dataclass|dialog|window|widget|service|manager|"
                r"adapter|record|model|exception|enum|protocol"
            )
            return any(
                re.search(
                    rf"\b{re.escape(symbol_name)}\b\s+(?:{declaration_nouns})\b"
                    rf"|\b(?:{declaration_nouns})\s+(?:named\s+|called\s+)?"
                    rf"\b{re.escape(symbol_name)}\b"
                    rf"|\b(?:add|build|create|define|defining|implement|"
                    rf"introduce|provide|write)\s+(?:an?\s+|the\s+|new\s+)*"
                    rf"\b{re.escape(symbol_name)}\b",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in requirement_texts
            )

        public_symbols = [
            value for value in public_symbols if has_declaration_evidence(value)
        ]

        verification_function_symbols = list(dict.fromkeys(
            match.group(1)
            for row in requirement_ledger
            for text in [
                str(row.get("text") or row.get("requirement") or "")
            ]
            for match in [
                re.search(
                    r"\b(?:add|define|implement|include|provide|expose)\s+"
                    r"(?:an?\s+|the\s+)?"
                    r"([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
                    r"[^.!?\n]{0,180}\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|"
                    r"validates?|self[- ]test|fake\s+"
                    r"(?:clock|client|host|service))\b",
                    text,
                    flags=re.IGNORECASE,
                )
            ]
            if match
        ))
        for verification_symbol in verification_function_symbols:
            if verification_symbol not in {
                public_symbol_name(value).rsplit(".", 1)[-1]
                for value in public_symbols
            }:
                public_symbols.append(verification_symbol)
        item["public_symbols"] = public_symbols

        class_symbols = [
            public_symbol_name(value)
            for value in public_symbols
            if public_symbol_name(value).rsplit(".", 1)[-1][:1].isupper()
        ]
        if len(class_symbols) != 1:
            continue
        class_name = class_symbols[0].rsplit(".", 1)[-1]
        class_requirement_index = next(
            (
                index
                for index, row in enumerate(requirement_ledger)
                if re.search(
                    rf"\b{re.escape(class_name)}\b",
                    str(row.get("text") or row.get("requirement") or ""),
                )
                and re.search(
                    r"\b(?:class|dataclass|dialog|window|widget|service|manager|"
                    r"adapter|record|model)\b",
                    str(row.get("text") or row.get("requirement") or ""),
                    flags=re.IGNORECASE,
                )
            ),
            None,
        )
        if class_requirement_index is None:
            continue
        retained_symbols: list[Any] = []
        for value in public_symbols:
            symbol_name = public_symbol_name(value).rsplit(".", 1)[-1]
            if not symbol_name or not symbol_name[:1].islower():
                retained_symbols.append(value)
                continue
            continuation_rows = [
                str(row.get("text") or row.get("requirement") or "")
                for index, row in enumerate(requirement_ledger)
                if index > class_requirement_index
                and re.search(
                    rf"(?<![.\w]){re.escape(symbol_name)}\s*\(",
                    str(row.get("text") or row.get("requirement") or ""),
                )
            ]
            explicitly_module_owned = any(
                re.search(
                    rf"\b(?:top[- ]level|module[- ]level|standalone)\b"
                    rf"[^.!?\n]{{0,60}}\b{re.escape(symbol_name)}\b"
                    rf"|\b(?:function|callable)\s+{re.escape(symbol_name)}\b"
                    rf"|\b{re.escape(symbol_name)}\s+(?:function|callable)\b",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in continuation_rows
            )
            verification_helper = any(
                re.search(
                    r"\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|validates?|"
                    r"self[- ]test|fake\s+(?:clock|client|host|service))\b",
                    text,
                    flags=re.IGNORECASE,
                )
                and re.search(
                    rf"\b(?:add|define|implement|include|provide|expose)\b"
                    rf"[^.!?\n]{{0,80}}\b{re.escape(symbol_name)}\s*\(",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in continuation_rows
            )
            class_continuation = any(
                re.search(
                    rf"\b(?:add|define|implement|include|provide|expose)\b"
                    rf"[^.!?\n]{{0,80}}\b{re.escape(symbol_name)}\s*\(",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in continuation_rows
            )
            if (
                class_continuation
                and not explicitly_module_owned
                and not verification_helper
            ):
                continue
            retained_symbols.append(value)
        item["public_symbols"] = retained_symbols

    declarations = _chunk_manifest_declarations(manifest)
    declaration_by_id = {
        item["declaration_id"]: item for item in declarations
    }
    file_items = {
        str(item.get("absolute_path") or item.get("path") or ""): item
        for item in manifest
    }
    files_by_requirement: dict[str, list[str]] = {}
    for path, item in file_items.items():
        for requirement_id in item.get("requirement_ids") or []:
            files_by_requirement.setdefault(str(requirement_id), []).append(path)
    passive_owner_names = {
        owner
        for raw_requirement in requirement_ledger
        for text in [
            str(
                raw_requirement.get("text")
                or raw_requirement.get("requirement")
                or raw_requirement.get("description")
                or ""
            )
        ]
        for owner in [
            *re.findall(
                r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception))\b",
                text,
            ),
            *re.findall(
                r"\b(?:immutable\s+)?([A-Z][A-Za-z0-9_]*)\s+"
                r"(?:dataclass|record|enum|protocol)\b"
                r"|\b(?:dataclass|record|enum|protocol)\s+"
                r"([A-Z][A-Za-z0-9_]*)\b",
                text,
                flags=re.IGNORECASE,
            ),
        ]
        for owner in (
            [owner]
            if isinstance(owner, str)
            else [value for value in owner if value]
        )
        if owner
    }
    explicit_state_owner_names = {
        owner
        for raw_requirement in requirement_ledger
        for text in [
            str(
                raw_requirement.get("text")
                or raw_requirement.get("requirement")
                or raw_requirement.get("description")
                or ""
            )
        ]
        for owner in [
            *[
                match[0]
                for match in re.findall(
                    r"\b([A-Z][A-Za-z0-9_]*)\."
                    r"([a-z_][A-Za-z0-9_]*)\s*\(",
                    text,
                )
            ],
            *[
                match[0]
                for match in re.findall(
                    r"\b([A-Z][A-Za-z0-9_]*)\s+with\s+"
                    r"([a-z_][A-Za-z0-9_]*)\s*\(",
                    text,
                    flags=re.IGNORECASE,
                )
            ],
        ]
    }

    assignments: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    active_declarations_by_path: dict[str, list[str]] = {}
    declaration_actions = (
        r"\b(?:add|create|implement|define|write|build|introduce|provide)\b"
    )
    module_roles = {
        "module",
        "module_behavior",
        "entry_point",
        "file_contract",
        "package_contract",
        "imports",
    }
    for raw_requirement in requirement_ledger:
        requirement_id = str(
            raw_requirement.get("id")
            or raw_requirement.get("requirement_id")
            or ""
        ).strip()
        text = str(
            raw_requirement.get("text")
            or raw_requirement.get("requirement")
            or raw_requirement.get("description")
            or ""
        ).strip()
        semantic_role = str(
            raw_requirement.get("semantic_role")
            or raw_requirement.get("role")
            or ""
        ).strip()
        explicit_path = str(
            raw_requirement.get("path")
            or raw_requirement.get("file")
            or ""
        ).strip()
        requirement_paths = (
            [explicit_path]
            if explicit_path
            else list(files_by_requirement.get(requirement_id) or [])
        )
        normalized_requirement_text = text.replace("\\", "/").casefold()
        explicitly_mentioned_paths = [
            path
            for path in file_items
            if Path(path).name.casefold() in normalized_requirement_text
        ]
        if len(explicitly_mentioned_paths) > 1:
            requirement_paths = list(
                dict.fromkeys(
                    [*requirement_paths, *explicitly_mentioned_paths]
                )
            )
        file_declarations = [
            item
            for item in declarations
            if not requirement_paths or item["path"] in requirement_paths
        ]
        module_declarations = [
            item for item in file_declarations if item["owner"] == "<module>"
        ]
        named_declaration_ids = [
            item["declaration_id"]
            for item in file_declarations
            if item["owner"] != "<module>"
            and re.search(
                rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                text,
            )
        ]
        explicit_owner = str(
            raw_requirement.get("owner")
            or raw_requirement.get("resolved_owner")
            or ""
        ).strip()
        owners: list[str] = []
        multi_owner_proven = False
        explicitly_introduced_callable_ids = [
            item["declaration_id"]
            for item in file_declarations
            if item["kind"] == "function"
            and re.search(
                declaration_actions
                + rf"[^.!?\n]{{0,80}}\b"
                + re.escape(item["owner"].rsplit(".", 1)[-1])
                + r"\s*\(",
                text,
                flags=re.IGNORECASE,
            )
        ]
        if (
            not explicit_owner
            and len(explicitly_introduced_callable_ids) == 1
        ):
            owners = explicitly_introduced_callable_ids
        non_error_classes = [
            item
            for item in file_declarations
            if (
                item["kind"] == "class"
                or item["owner"].rsplit(".", 1)[-1][:1].isupper()
            )
            and not item["owner"].rsplit(".", 1)[-1].endswith(
                ("Error", "Exception")
            )
        ]
        error_classes = [
            item
            for item in file_declarations
            if item["owner"].rsplit(".", 1)[-1].endswith(
                ("Error", "Exception")
            )
        ]
        cross_cutting_constraint = bool(
            re.search(
                r"\b(?:use only|standard library|no external|without external"
                r"|all generated files|entire package|package-wide"
                r"|(?:both|each|all|every)\s+files?)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        callable_quality_constraint = bool(
            re.search(
                r"\b(?:detailed|complete|descriptive)\b"
                r"[^.!?\n]{0,120}\bdocstrings?\b"
                r"|\b(?:clear|consistent|project[- ]style)\b"
                r"[^.!?\n]{0,120}\bdocstrings?\b"
                r"|\bdocstrings?\b[^.!?\n]{0,120}\b"
                r"(?:clear|consistent|project\s+(?:format|style))\b"
                r"|\bdocstrings?\b[^.!?\n]{0,80}\b"
                r"(?:where applicable|public callables?|parameters?|returns?)\b"
                r"|\b(?:complete|explicit|full)\b[^.!?\n]{0,80}\b"
                r"(?:type hints?|annotations?)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if not explicit_owner and callable_quality_constraint:
            owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"] != "<module>"
            ]
            if not owners:
                owners = [
                    item["declaration_id"] for item in module_declarations
                ]
            multi_owner_proven = len(owners) > 1
        if (
            not explicit_owner
            and not owners
            and len(named_declaration_ids) > 1
            and re.search(
                r"\b(?:delegate|integrate|route|update|wire)\w*\b",
                text,
                flags=re.IGNORECASE,
            )
            and (
                semantic_role.casefold() == "integration"
                or re.search(
                    r"\bdelegat\w*\b[^.!?\n]{0,160}\bpreserv\w*\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
        ):
            owners = list(dict.fromkeys(named_declaration_ids))
            multi_owner_proven = True
        if not explicit_owner and cross_cutting_constraint:
            owners = [
                item["declaration_id"] for item in file_declarations
            ]
            multi_owner_proven = len(owners) > 1
        if explicit_owner:
            owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"] == explicit_owner
                or item["owner"].endswith(f".{explicit_owner}")
            ]

        inferred_ui_owners = [
            item["declaration_id"]
            for item in file_declarations
            if item["owner"] != "<module>"
            and bool(item.get("inferred_from_request"))
            and (
                item.get("kind") == "class"
                or item["owner"].rsplit(".", 1)[-1].endswith(
                    ("Dialog", "Window", "Widget", "Panel", "Dock")
                )
            )
        ]
        ui_behavior_requirement = bool(
            re.search(
                r"\b(?:qt|pyside[26]?|pyqt[56]?)\b",
                text,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\b(?:ui|dialog|window|widget|panel|control|input|"
                r"button|field|filter|selection)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if (
            not explicit_owner
            and not owners
            and ui_behavior_requirement
            and len(inferred_ui_owners) == 1
        ):
            owners = inferred_ui_owners

        package_or_file_contract = bool(re.search(
            r"\b(?:create|add|build|generate|write|produce)\b"
            r"[^.!?\n]{0,140}\b(?:package|files?|modules?)\b"
            r"|\b(?:under|inside|within)\s+[A-Za-z_][A-Za-z0-9_./\\-]*"
            r"\s*:\s*[^.!?\n]*\.py\b"
            r"|\bdo\s+not\s+write\b[^.!?\n]{0,120}\b"
            r"(?:project\s+root|workspace|directory)\b",
            text,
            flags=re.IGNORECASE,
        ))
        if (
            not explicit_owner
            and not owners
            and package_or_file_contract
            and module_declarations
        ):
            owners = [
                item["declaration_id"] for item in module_declarations
            ]
            multi_owner_proven = len(owners) > 1

        import_requirement = bool(
            re.match(
                r"^\s*(?:in\s+\S+\s+)?imports?\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if (
            not explicit_owner
            and not owners
            and import_requirement
            and len(module_declarations) == 1
        ):
            owners = [module_declarations[0]["declaration_id"]]
            semantic_role = "import"

        test_file_requirement = bool(
            requirement_paths
            and all(
                _is_test_path(Path(requirement_path))
                for requirement_path in requirement_paths
            )
        )
        if (
            not explicit_owner
            and not owners
            and test_file_requirement
            and module_declarations
        ):
            owners = [
                item["declaration_id"] for item in module_declarations
            ]
            multi_owner_proven = len(owners) > 1

        proof_requirement = bool(
            re.match(r"^\s*Test proof\s*:", text, flags=re.IGNORECASE)
        )
        test_module_declarations = [
            item
            for item in declarations
            if item["owner"] == "<module>"
            and _is_test_path(Path(item["path"]))
        ]
        if (
            not explicit_owner
            and not owners
            and proof_requirement
            and len(test_module_declarations) == 1
        ):
            owners = [test_module_declarations[0]["declaration_id"]]

        if not explicit_owner and not owners:
            declared_error_ids = [
                item["declaration_id"]
                for item in error_classes
                if re.match(
                    rf"^\s*(?:and\s+)?"
                    rf"{re.escape(item['owner'].rsplit('.', 1)[-1])}\b"
                    r"(?:\s+(?:containing|with|that|which)\b[^.!?\n]*)?\s*$",
                    text,
                    flags=re.IGNORECASE,
                )
            ]
            if len(declared_error_ids) == 1:
                owners = declared_error_ids

        if not explicit_owner and not owners:
            qualified_owner_names = set(re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\.[a-z_][A-Za-z0-9_]*\s*\(",
                text,
            ))
            qualified_owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"].rsplit(".", 1)[-1]
                in qualified_owner_names
            ]
            if qualified_owners:
                owners = list(dict.fromkeys(qualified_owners))
                multi_owner_proven = len(owners) > 1

        if not explicit_owner and not owners:
            state_owner_candidates = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"].rsplit(".", 1)[-1]
                in explicit_state_owner_names
                and item["owner"].rsplit(".", 1)[-1]
                not in passive_owner_names
            ]
            operational_behavior = bool(re.search(
                r"\b(?:accept|allow|apply|call|cancel|check|connect|dequeue|"
                r"enqueue|execute|find|load|normalize|order|populate|progress|"
                r"raise|reject|report|return|run|save|schedule|set|snapshot|"
                r"update|validate)\w*\b",
                text,
                flags=re.IGNORECASE,
            ))
            declaration_only = bool(
                re.search(declaration_actions, text, flags=re.IGNORECASE)
                and named_declaration_ids
                and all(
                    declaration_by_id[declaration_id]["owner"].rsplit(
                        ".", 1
                    )[-1]
                    in passive_owner_names
                    for declaration_id in named_declaration_ids
                )
            )
            if (
                len(state_owner_candidates) == 1
                and operational_behavior
                and not declaration_only
            ):
                owners = state_owner_candidates

        if (
            not explicit_owner
            and not owners
        ):
            continuation_candidates = list(dict.fromkeys(
                declaration_id
                for path in requirement_paths
                for declaration_id in active_declarations_by_path.get(path, [])
            ))
            continuation_is_explicit = bool(re.match(
                r"^\s*(?:it|this|that|they|these|those)\b",
                text,
                flags=re.IGNORECASE,
            ))
            continuation_is_function_behavior = bool(
                len(continuation_candidates) == 1
                and declaration_by_id[
                    continuation_candidates[0]
                ]["kind"] == "function"
                and re.search(
                    r"\b(?:accept|add|allow|apply|build|call|check|close|connect|"
                    r"convert|create|delete|dequeue|destroy|dispose|emit|enqueue|"
                    r"export|find|get|generate|import|load|normalize|parse|raise|"
                    r"read|reject|release|report|return|save|set|snapshot|spawn|"
                    r"update|use|validate|write)\w*\b",
                    text,
                    flags=re.IGNORECASE,
                )
                and not re.search(
                    r"\b(?:module entry point|run as (?:a )?script|"
                    r"standalone\s+entry\s+point|if\s+__name__|__main__)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            if (
                len(continuation_candidates) == 1
                and (
                    continuation_is_explicit
                    or continuation_is_function_behavior
                )
            ):
                owners = continuation_candidates

        if not explicit_owner and not owners:
            introduced_declarations = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"] != "<module>"
                and re.search(
                    rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                    text,
                )
            ]
            if (
                len(introduced_declarations) > 1
                and re.search(declaration_actions, text, flags=re.IGNORECASE)
                and not re.search(
                    r"\b(?:reject|raise|throw|fail)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            ):
                owners = introduced_declarations
                multi_owner_proven = True

        if not explicit_owner and not owners:
            direct_owner_names = list(dict.fromkeys(re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\s+"
                r"(?:must|should|shall|will|provides?|implements?|exposes?)\b",
                text,
                flags=re.IGNORECASE,
            )))
            direct_owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"].rsplit(".", 1)[-1] in direct_owner_names
            ]
            if direct_owners:
                owners = direct_owners
                multi_owner_proven = len(owners) > 1

        if (
            not explicit_owner
            and not owners
            and len(non_error_classes) == 1
            and (
                re.search(
                    r"\b(?:thread-safe|deterministic|FIFO|immutable snapshot|"
                    r"insertion order|without mutating|state|cycle|self-depend|"
                    r"unique|non-blank|pending|identifier|IDs?|"
                    r"priority|must\s+be\s+an?\s+(?:int|integer|string)|"
                    r"not\s+bool|"
                    r"allow|dequeue|enqueue|reject|raise)\b",
                    text,
                    flags=re.IGNORECASE,
                )
                or (
                    error_classes
                    and any(
                        re.search(
                            rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                            text,
                        )
                        for item in error_classes
                    )
                )
            )
        ):
            owners = [non_error_classes[0]["declaration_id"]]

        workflow_artifact_constraint = bool(re.search(
            r"\b(?:do\s+not|don't|without|no)\s+"
            r"(?:(?:create|add|generate|write|include|produce|use)\s+)?"
            r"(?:any\s+|new\s+|project\s+)*"
            r"(?:test\s+files?|tests?)\b"
            r"|\bvalidation\s+artifacts?\s+(?:must\s+be\s+)?temporary\b",
            text,
            flags=re.IGNORECASE,
        ))
        if not owners and not named_declaration_ids and (
            semantic_role in module_roles
            or workflow_artifact_constraint
            or re.search(
                r"\b(?:module entry point|run as (?:a )?script|executed as (?:a )?script"
                r"|runs?\s+standalone|standalone\s+entry\s+point"
                r"|runnable\s+(?:main\s+)?example"
                r"|create(?: exactly)? (?:one|two|three|a|\w+)?\s*new "
                r"(?:files?|modules?)"
                r"|new Python file|if\s+__name__"
                r"|(?:do\s+not|don't|without|no)\s+"
                r"(?:create|add|generate|write|include|produce|use|new|project\s+)*"
                r"(?:test\s+files?|tests?)"
                r"|validation\s+artifacts?\s+(?:must\s+be\s+)?temporary)\b",
                text,
                flags=re.IGNORECASE,
            )
        ) and module_declarations:
            owners = [
                item["declaration_id"] for item in module_declarations
            ]
            multi_owner_proven = len(owners) > 1

        if not explicit_owner and not owners:
            declared_candidates: list[str] = []
            for item in file_declarations:
                if item["owner"] == "<module>":
                    continue
                symbol = item["owner"].split("(", 1)[0].rsplit(".", 1)[-1]
                if re.search(
                    declaration_actions
                    + rf"[^.!?\n]{{0,100}}\b{re.escape(symbol)}\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"\b{re.escape(symbol)}\b[^.!?\n]{{0,40}}"
                    r"\b(?:class|function|callable)\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"\b{re.escape(symbol)}\b\s+"
                    r"[A-Z][A-Za-z0-9_.]*\s+"
                    r"(?:containing|with|that|which|inheriting|subclassing|extending)\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"\b{re.escape(symbol)}\b\s+"
                    r"(?:inheriting\s+from|subclassing|extends)\s+"
                    r"[A-Z][A-Za-z0-9_.]*\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"^\s*{re.escape(symbol)}\b\s+"
                    r"(?:must|should|shall|will|exposes?|provides?|implements?|uses?)\b",
                    text,
                    flags=re.IGNORECASE,
                ) or (
                    len(requirement_paths) == 1
                    and re.search(rf"\b{re.escape(symbol)}\b", text)
                ):
                    declared_candidates.append(item["declaration_id"])
            if len(declared_candidates) == 1:
                owners.extend(declared_candidates)
                multi_owner_proven = len(owners) > 1
            elif len(declared_candidates) > 1 and (
                len(requirement_paths) == 1
                or re.search(
                    r"\b(?:both|each|all|every)\s+(?:of\s+the\s+)?files?\b",
                    text,
                    flags=re.IGNORECASE,
                )
            ):
                owners.extend(declared_candidates)
                multi_owner_proven = True
            owners = list(dict.fromkeys(owners))

        if not owners and re.search(
            r"\b(?:method|constructor|property|attribute|signal|slot)\b",
            text,
            flags=re.IGNORECASE,
        ):
            class_candidates = [
                item["declaration_id"]
                for item in file_declarations
                if item["kind"] == "class"
                or item["owner"].rsplit(".", 1)[-1][:1].isupper()
            ]
            if len(class_candidates) == 1:
                owners = class_candidates

        if not explicit_owner and not owners and len(requirement_paths) == 1:
            existing_callable_candidates = [
                item["declaration_id"]
                for item in file_declarations
                if item["kind"] in {"function", "async_function"}
                and bool(item.get("existing_declaration"))
            ]
            if len(existing_callable_candidates) == 1:
                owners = existing_callable_candidates

        if not owners:
            class_candidates = [
                item["declaration_id"]
                for item in file_declarations
                if item["kind"] == "class"
                or item["owner"].rsplit(".", 1)[-1][:1].isupper()
            ]
            class_owned_behavior = bool(
                re.search(
                    r"\b[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)"
                    r"|\.(?:clicked|triggered|toggled|accepted|rejected)\b"
                    r"|\b(?:dialogs?|windows?|widgets?|buttons?|inputs?|labels?|"
                    r"spinboxes?|comboboxes?|event\s+filters?|mouse|keyboard|escape)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            module_owned_behavior = bool(
                re.search(
                    r"\b(?:module entry point|run as (?:a )?script|"
                    r"runs?\s+standalone|standalone\s+entry\s+point|"
                    r"executed as (?:a )?script|if\s+__name__)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            if (
                len(class_candidates) == 1
                and class_owned_behavior
                and not module_owned_behavior
                and not any(
                    item["kind"] == "function"
                    for item in file_declarations
                )
            ):
                owners = class_candidates

        module_owned_behavior = bool(
            re.search(
                r"\b(?:module entry point|run as (?:a )?script|"
                r"runs?\s+standalone|standalone\s+entry\s+point|"
                r"executed as (?:a )?script|if\s+__name__|"
                r"runnable\s+(?:main\s+)?example|"
                r"runnable\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?__main__|"
                r"__main__)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        class_owned_behavior = bool(
            re.search(
                r"\b(?:class|constructor|method|event\s+handling|cleanup|"
                r"dialogs?|windows?|widgets?|buttons?|inputs?|labels?|"
                r"spinboxes?|comboboxes?|signals?|clicked|progress|mouse|"
                r"keyboard|escape)\b"
                r"|\bQ[A-Z][A-Za-z0-9_]*(?:Widget|Button|Bar|Label|Box)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        class_candidates = [
            item["declaration_id"]
            for item in file_declarations
            if item["kind"] == "class"
            or item["owner"].rsplit(".", 1)[-1][:1].isupper()
        ]
        if module_owned_behavior and module_declarations:
            if class_owned_behavior and len(class_candidates) == 1:
                owners.append(class_candidates[0])
            owners.extend(
                item["declaration_id"] for item in module_declarations
            )
            owners = list(dict.fromkeys(owners))
            multi_owner_proven = len(owners) > 1

        if owners and (len(owners) == 1 or multi_owner_proven):
            owner_id = owners[0]
            owner_declaration = declaration_by_id[owner_id]
            resolved_role = (
                "constraint"
                if cross_cutting_constraint
                else semantic_role or "behavior"
            )
            if re.search(
                r"(?:self[-_ ]?test|\btests?\b|\bproof\b|\bprov(?:e[sd]?|ing)\b"
                r"|\bverif(?:y|ies|ication)\b)",
                text,
                flags=re.IGNORECASE,
            ) and any(
                declaration_by_id[item]["kind"] == "function"
                for item in owners
            ):
                resolved_role = "verification"
            dependencies: list[str] = []
            dependencies.extend(
                item["declaration_id"]
                for item in error_classes
                if item["declaration_id"] not in owners
                and re.search(
                    rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                    text,
                )
            )
            if all(
                declaration_by_id[item]["owner"] == "<module>"
                for item in owners
            ):
                if len(owners) == 1:
                    module_path = declaration_by_id[owners[0]]["path"]
                    dependencies.extend([
                        item["declaration_id"]
                        for item in file_declarations
                        if item["owner"] != "<module>"
                        and item["path"] == module_path
                    ])
            elif resolved_role == "verification" and len(owners) == 1:
                dependencies.extend([
                    item["declaration_id"]
                    for item in file_declarations
                    if item["declaration_id"] != owner_id
                    and item["owner"] != "<module>"
                    and item["kind"] != "function"
                ])
            dependencies = list(dict.fromkeys(dependencies))
            assignments.append({
                "requirement_id": requirement_id,
                "semantic_role": resolved_role,
                "declaration_ids": owners,
                "depends_on": dependencies,
                "reason": "deterministic structural ownership",
            })
        else:
            unresolved.append({
                "id": requirement_id,
                "text": text,
                "semantic_role": semantic_role,
                "path": (
                    explicit_path
                    or (
                        requirement_paths[0]
                        if len(requirement_paths) == 1
                        else ""
                    )
                ),
            })
        if (
            len(named_declaration_ids) == 1
            and (
                re.search(declaration_actions, text, flags=re.IGNORECASE)
                or re.fullmatch(
                    r"\s*[a-z_][A-Za-z0-9_]*\s*\([^()\n]*\)\s*",
                    text,
                )
            )
        ):
            for path in requirement_paths:
                active_declarations_by_path[path] = list(
                    dict.fromkeys(named_declaration_ids)
                )
    return assignments, unresolved


def parse_project_edit_generated_file(
    source_response: str,
    *,
    path: str,
    expected_public_symbols: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Normalize and validate one raw full-file generation result."""

    source = str(source_response or "").strip()
    fenced_blocks = re.findall(
        r"```(?:python|py)?\s*(.*?)```",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_blocks:
        source = "\n\n".join(
            block.strip("\r\n") for block in fenced_blocks if block.strip()
        )
    else:
        source = re.sub(
            r"^```(?:python|py)?\s*",
            "",
            source,
            flags=re.IGNORECASE,
        )
        source = re.sub(r"\s*```$", "", source)
    if not source:
        return "", [f"Generated file returned no source: {path}"]
    try:
        tree = ast.parse(source, filename=path)
        source = _remove_redundant_generated_initializers(source, tree)
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec")
    except (SyntaxError, ValueError) as exc:
        syntax_detail = ""
        if isinstance(exc, SyntaxError):
            offending_text = str(exc.text or "").rstrip()
            syntax_detail = (
                f"; offending source line {exc.lineno}: {offending_text}"
                if offending_text
                else ""
            )
        sanitized = _remove_generated_top_level_await(source, path=path)
        if sanitized != source:
            try:
                tree = ast.parse(sanitized, filename=path)
                compile(tree, path, "exec")
                source = sanitized
            except (SyntaxError, ValueError):
                return source.rstrip() + "\n", [
                    f"Generated file did not parse and compile ({Path(path).name}): "
                    f"{exc}{syntax_detail}"
                ]
        else:
            return source.rstrip() + "\n", [
                f"Generated file did not parse and compile ({Path(path).name}): "
                f"{exc}{syntax_detail}"
            ]
    expected = {
        match.group(0)
        for value in expected_public_symbols or []
        if (
            match := re.match(
                r"[A-Za-z_]\w*",
                str(value).split("(", 1)[0].rsplit(".", 1)[-1].strip(),
            )
        )
    }
    declared_symbols = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    declared_symbols.update(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param))
    )
    missing_symbols = sorted(expected - declared_symbols)
    if missing_symbols:
        return source.rstrip() + "\n", [
            f"Generated file omitted manifest-declared public symbols ({Path(path).name}): "
            + ", ".join(missing_symbols)
        ]
    if _is_test_path(Path(path)):
        tests = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        ]
        if not tests:
            return source.rstrip() + "\n", [
                f"Generated test file defines no test_* methods: {path}"
            ]
        if all(any(isinstance(item, ast.Pass) for item in ast.walk(test)) for test in tests):
            return source.rstrip() + "\n", [
                f"Generated test file contains only placeholder tests: {path}"
            ]
    else:
        placeholders = [
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
        if placeholders:
            return source.rstrip() + "\n", [
                f"Generated production file contains placeholder callable bodies ({Path(path).name}): "
                + ", ".join(sorted(placeholders))
            ]
        source = _remove_generated_top_level_calls(source, tree=tree)
        tree = ast.parse(source, filename=path)
        side_effects = _generated_module_import_side_effects(tree)
        if side_effects:
            return source.rstrip() + "\n", [
                f"Generated production file executes behavior at import time ({Path(path).name}): "
                + ", ".join(side_effects)
            ]
    return source.rstrip() + "\n", []


def validate_project_edit_generated_module_graph(
    source: str,
    *,
    path: str,
    project_root: str,
    generated_files: list[tuple[str, str, str]],
    declared_dependencies: list[str] | None = None,
) -> list[str]:
    """Validate imports against completed generated files and declared manifest edges."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [f"Generated module graph could not parse {Path(path).name}: {exc}"]

    target_path = Path(path).resolve()
    candidate_sources = {
        str(Path(file_path).resolve()): generated_source
        for file_path, _original, generated_source in generated_files
    }
    candidate_sources[str(target_path)] = source
    declared = {
        str((Path(project_root) / dependency).resolve())
        for dependency in declared_dependencies or []
    }
    errors: list[str] = []
    if not _is_test_path(target_path):
        current_classes = {
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
        }
        for dependency_path, dependency_source in candidate_sources.items():
            if dependency_path == str(target_path):
                continue
            try:
                dependency_tree = ast.parse(dependency_source, filename=dependency_path)
            except SyntaxError:
                continue
            dependency_classes = {
                node.name
                for node in dependency_tree.body
                if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
            }
            duplicate_classes = sorted(current_classes.intersection(dependency_classes))
            if duplicate_classes:
                errors.append(
                    f"Generated module duplicates dependency-owned public type "
                    f"({Path(path).name} -> {Path(dependency_path).name}): "
                    f"{', '.join(duplicate_classes)}. Import and reuse the canonical type."
                )
    for module, level, imported_name in _import_specs(tree):
        ok, detail = _resolve_import_spec(
            target_path,
            module,
            level,
            imported_name,
            project_root=project_root,
            candidate_sources=candidate_sources,
        )
        if not ok:
            errors.append(detail)
            continue
        local_path = _local_module_path(
            target_path,
            module,
            level,
            project_root=project_root,
            candidate_paths=set(candidate_sources),
        )
        if (
            local_path is not None
            and local_path.resolve() != target_path
            and str(local_path.resolve()) in candidate_sources
            and str(local_path.resolve()) not in declared
        ):
            errors.append(
                f"Generated import is missing its manifest dependency edge "
                f"({Path(path).name} -> {local_path.name})."
            )
    return list(dict.fromkeys(errors))


def resolve_project_edit_failure_symbol(
    generated_files: list[tuple[str, str, str]],
    validation_errors: list[str],
    *,
    deprioritized_symbols: set[str] | None = None,
) -> dict[str, str]:
    """Resolve the smallest generated callable implicated by a validation traceback."""

    failure_text = "\n".join(str(item) for item in validation_errors)
    deprioritized = set(deprioritized_symbols or ())
    if any(
        marker in failure_text.lower()
        for marker in (
            "new import could not be resolved",
            "missing its manifest dependency edge",
            "project-local import does not expose",
            "executes behavior at import time",
        )
    ):
        return {}
    placeholder_tests: list[str] = []
    for group in re.findall(
        r"Generated test methods (?:are placeholders|need stronger behavioral proof):\s*"
        r"([A-Za-z0-9_., ]+)",
        failure_text,
    ):
        placeholder_tests.extend(
            item.rsplit(".", 1)[-1].strip()
            for item in group.split(",")
            if item.strip()
        )
    placeholder_callables: list[str] = []
    for group in re.findall(
        r"Generated production callables are placeholders:\s*([A-Za-z0-9_., ]+)",
        failure_text,
    ):
        placeholder_callables.extend(
            item.strip() for item in group.split(",") if item.strip()
        )
    failing_tests = list(dict.fromkeys(
        placeholder_tests
        + re.findall(r"(?:ERROR|FAIL):\s+(test_[A-Za-z0-9_]+)", failure_text)
    ))
    if re.search(r"\bin setUp\b", failure_text):
        for path_text, _original, source in generated_files:
            if not _is_test_path(Path(path_text)) or Path(path_text).name not in failure_text:
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                setup = next(
                    (
                        node for node in class_node.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "setUp"
                    ),
                    None,
                )
                symbol = f"{class_node.name}.setUp"
                if setup is not None and symbol not in deprioritized:
                    return {
                        "path": path_text,
                        "symbol": symbol,
                        "source": ast.get_source_segment(source, setup) or "",
                    }
    if len(placeholder_tests) > 3:
        return {}
    for path_text, _original, source in generated_files:
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for target_symbol in placeholder_callables:
            parts = target_symbol.split(".")
            if len(parts) == 2:
                owner = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == parts[0]
                    ),
                    None,
                )
                node = next(
                    (
                        child
                        for child in (owner.body if owner is not None else [])
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == parts[1]
                    ),
                    None,
                )
            else:
                node = next(
                    (
                        child
                        for child in tree.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == parts[-1]
                    ),
                    None,
                )
            if node is not None and target_symbol not in deprioritized:
                return {
                    "path": path_text,
                    "symbol": target_symbol,
                    "source": ast.get_source_segment(source, node) or "",
                }
    for path_text, _original, source in generated_files:
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        ordered_placeholders = sorted(
            placeholder_tests,
            key=lambda name: any(symbol.endswith(f".{name}") for symbol in deprioritized),
        )
        fresh_placeholders = [
            name for name in ordered_placeholders
            if not any(symbol.endswith(f".{name}") for symbol in deprioritized)
        ]
        for failing_test in fresh_placeholders:
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                node = next(
                    (
                        child for child in class_node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == failing_test
                    ),
                    None,
                )
                if node is not None:
                    return {
                        "path": path_text,
                        "symbol": f"{class_node.name}.{node.name}",
                        "source": ast.get_source_segment(source, node) or "",
                    }
    undefined_symbols = [
        item.strip()
        for group in re.findall(
            r"Generated callables reference undefined names in ([A-Za-z0-9_., ]+):",
            failure_text,
        )
        for item in group.split(",")
        if item.strip()
    ]
    contract_identifiers = [
        identifier.strip()
        for group in re.findall(
            r"Requested (?:removed|renamed) identifiers remain:\s*([A-Za-z0-9_., ]+)",
            failure_text,
        )
        for identifier in group.split(",")
        if identifier.strip()
    ]
    unrequested_symbols = [
        symbol.strip()
        for group in re.findall(
            r"Unrequested public callables were introduced:\s*([A-Za-z0-9_., ]+)",
            failure_text,
        )
        for symbol in group.split(",")
        if symbol.strip()
    ]
    for path_text, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for target_symbol in unrequested_symbols:
            parts = target_symbol.split(".")
            candidates = [
                node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == parts[-1]
            ]
            if candidates:
                node = candidates[0]
                return {
                    "path": path_text,
                    "symbol": target_symbol,
                    "source": ast.get_source_segment(source, node) or "",
                }
        for identifier in contract_identifiers:
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                for node in class_node.body:
                    if (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and _tree_uses_identifier(node, identifier)
                    ):
                        return {
                            "path": path_text,
                            "symbol": f"{class_node.name}.{node.name}",
                            "source": ast.get_source_segment(source, node) or "",
                        }
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and _tree_uses_identifier(node, identifier)
                ):
                    return {
                        "path": path_text,
                        "symbol": node.name,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    for path_text, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        ordered_undefined = sorted(
            (symbol for symbol in undefined_symbols if symbol not in deprioritized),
        )
        for target_symbol in ordered_undefined:
            parts = target_symbol.split(".")
            if len(parts) == 2:
                class_node = next(
                    (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == parts[0]),
                    None,
                )
                if class_node is not None:
                    node = next(
                        (
                            child for child in class_node.body
                            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and child.name == parts[1]
                        ),
                        None,
                    )
                    if node is not None:
                        return {
                            "path": path_text,
                            "symbol": target_symbol,
                            "source": ast.get_source_segment(source, node) or "",
                        }
            elif len(parts) == 1:
                node = next(
                    (
                        child for child in tree.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == parts[0]
                    ),
                    None,
                )
                if node is not None:
                    return {
                        "path": path_text,
                        "symbol": target_symbol,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    production_frames = re.findall(
        r'File "[^"]*[\\/](?P<name>[^"\\/]+\.py)", line (?P<line>\d+), '
        r'in (?P<symbol>[A-Za-z_]\w*)',
        failure_text,
    )
    for filename, line_text, symbol_name in reversed(production_frames):
        for path_text, _original, source in generated_files:
            if (
                _is_test_path(Path(path_text))
                or Path(path_text).name.lower() != filename.lower()
            ):
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            line = int(line_text)
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                for node in class_node.body:
                    if (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == symbol_name
                        and node.lineno <= line <= int(node.end_lineno or node.lineno)
                    ):
                        qualified = f"{class_node.name}.{node.name}"
                        if qualified not in deprioritized:
                            return {
                                "path": path_text,
                                "symbol": qualified,
                                "source": ast.get_source_segment(source, node) or "",
                            }
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == symbol_name
                    and node.lineno <= line <= int(node.end_lineno or node.lineno)
                    and node.name not in deprioritized
                ):
                    return {
                        "path": path_text,
                        "symbol": node.name,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    production_callables: dict[str, dict[str, str]] = {}
    for path_text, _original, source in generated_files:
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                production_callables[node.name] = {
                    "path": path_text,
                    "symbol": node.name,
                    "source": ast.get_source_segment(source, node) or "",
                }
    if "assertionerror" in failure_text.lower() and failing_tests:
        for path_text, _original, source in generated_files:
            if not _is_test_path(Path(path_text)):
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            for test_node in [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in failing_tests
            ]:
                called_production = list(dict.fromkeys(
                    child.func.id
                    for child in ast.walk(test_node)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id in production_callables
                    and child.func.id not in deprioritized
                ))
                if len(called_production) == 1:
                    return production_callables[called_production[0]]
    for path_text, _original, source in generated_files:
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            if failure_text.lower().count("permissionerror") > 1:
                setup = next(
                    (
                        node for node in class_node.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "setUp"
                    ),
                    None,
                )
                if setup is not None:
                    return {
                        "path": path_text,
                        "symbol": f"{class_node.name}.setUp",
                        "source": ast.get_source_segment(source, setup) or "",
                    }
            ordered_failures = sorted(
                failing_tests,
                key=lambda name: f"{class_node.name}.{name}" in deprioritized,
            )
            for failing_test in ordered_failures:
                qualified = f"{class_node.name}.{failing_test}"
                if qualified in deprioritized:
                    continue
                node = next(
                    (
                        child for child in class_node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == failing_test
                    ),
                    None,
                )
                if node is not None:
                    return {
                        "path": path_text,
                        "symbol": qualified,
                        "source": ast.get_source_segment(source, node) or "",
                    }

    frames = re.findall(
        r'File "[^"]*[\\/](?P<name>[^"\\/]+\.py)", line (?P<line>\d+), in (?P<symbol>[A-Za-z_]\w*)',
        failure_text,
    )
    for filename, line_text, symbol_name in reversed(frames):
        for path_text, _original, source in generated_files:
            if Path(path_text).name.lower() != filename.lower():
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            line = int(line_text)
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                for node in class_node.body:
                    if (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == symbol_name
                        and node.lineno <= line <= int(node.end_lineno or node.lineno)
                    ):
                        return {
                            "path": path_text,
                            "symbol": f"{class_node.name}.{node.name}",
                            "source": ast.get_source_segment(source, node) or "",
                        }
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == symbol_name
                    and node.lineno <= line <= int(node.end_lineno or node.lineno)
                ):
                    return {
                        "path": path_text,
                        "symbol": node.name,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    return {}
