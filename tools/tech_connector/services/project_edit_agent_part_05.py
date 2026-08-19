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
    ProjectEditLeafWorkUnits,
    ProjectEditPlan,
)

from tech_connector.services.project_edit_agent_part_02 import (
    _HOST_RUNTIME_MODULES,
    _edit_error_for_forbidden_path,
    _edit_python_symbol_source,
    _is_forbidden_edit_path,
    _parse_structured_project_changes,
)

from tech_connector.services.project_edit_agent_part_03 import (
    _public_definition_map,
    _requested_identifier_contracts,
    _sanitize_python_candidate_text,
    _tree_uses_identifier,
)

from tech_connector.services.project_edit_agent_part_04 import (
    _is_test_path,
)


def isolate_project_edit_generated_test_fixture(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Give a no-argument generated test fixture a disposable filesystem path."""

    generated_classes = {
        node.name
        for path_text, _original, source in generated_files
        if not _is_test_path(Path(path_text))
        for node in ast.parse(source, filename=path_text).body
        if isinstance(node, ast.ClassDef)
    }
    updated = list(generated_files)
    for index, (path_text, original, source) in enumerate(updated):
        if not _is_test_path(Path(path_text)):
            continue
        tree = ast.parse(source, filename=path_text)
        for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            setup = next(
                (
                    node for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "setUp"
                ),
                None,
            )
            if setup is None:
                continue
            fixture_assignments = [
                node
                for node in setup.body
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in generated_classes
                and not node.value.args
                and not node.value.keywords
            ]
            if not fixture_assignments:
                continue
            assignment = fixture_assignments[0]
            target_text = ast.get_source_segment(source, assignment.targets[0]) or "self.tool"
            class_name = assignment.value.func.id
            replacement = (
                "def setUp(self):\n"
                "    import os\n"
                "    import tempfile\n"
                "    self._generated_workspace = tempfile.TemporaryDirectory()\n"
                "    self.addCleanup(self._generated_workspace.cleanup)\n"
                f"    {target_text} = {class_name}("
                "os.path.join(self._generated_workspace.name, 'generated_test_data.json'))\n"
            )
            matched, corrected, error = _edit_python_symbol_source(
                source,
                target_symbol=f"{class_node.name}.setUp",
                replacement=replacement,
                filename=path_text,
                operation="replace_symbol",
            )
            if not matched:
                return generated_files, [error or f"Could not isolate {class_node.name}.setUp."]
            updated[index] = (path_text, original, corrected)
            return updated, [f"{Path(path_text).name}:{class_node.name}.setUp"]
    return generated_files, []


def normalize_project_edit_async_test_lifecycle(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Use unittest's recognized async fixture lifecycle names."""

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        changed = False
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            is_isolated_async_case = any(
                (
                    isinstance(base, ast.Attribute)
                    and base.attr == "IsolatedAsyncioTestCase"
                )
                or (
                    isinstance(base, ast.Name)
                    and base.id == "IsolatedAsyncioTestCase"
                )
                for base in class_node.bases
            )
            if not is_isolated_async_case:
                continue
            for method in class_node.body:
                if not isinstance(method, ast.AsyncFunctionDef):
                    continue
                replacement = {
                    "setUp": "asyncSetUp",
                    "tearDown": "asyncTearDown",
                }.get(method.name)
                if not replacement:
                    continue
                fixes.append(
                    f"{Path(path_text).name}: renamed async {method.name} to {replacement}"
                )
                method.name = replacement
                changed = True
        if changed:
            ast.fix_missing_locations(tree)
            updated[index] = (
                path_text,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, fixes


def ensure_project_edit_requested_docstrings(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
    force: bool = False,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Insert project-style docstrings for every generated public callable.

    :param generated_files: generated candidate files
    :param request_prompt: original project-edit request
    :param force: whether docstrings are required independent of prompt wording
    :return: updated files and descriptions of inserted docstrings
    """
    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        lines = source.splitlines(keepends=True)
        edits: list[tuple[int, str]] = []
        docstrings_requested = force or bool(re.search(
            r"\bdocstrings?\b|restructuredtext\s+fields?|"
            r":param\s+[a-z_][a-z0-9_]*:",
            request_prompt,
            flags=re.IGNORECASE,
        ))
        if docstrings_requested and ast.get_docstring(tree) is None:
            module_name = Path(path_text).stem.replace("_", " ").strip()
            package_name = Path(path_text).parent.name.replace("_", " ").strip()
            if module_name == "__init__":
                summary = f"Public interface for the {package_name} package."
            else:
                summary = (
                    f"{module_name.capitalize()} operations for the "
                    f"{package_name} package."
                )
            edits.append((0, f'"""{summary}"""\n\n'))
            fixes.append(f"{Path(path_text).name}:<module>")
        for name, node in _public_definition_map(tree).items():
            if ast.get_docstring(node) or not getattr(node, "body", None):
                continue
            bare_name = name.rsplit(".", 1)[-1]
            words = re.sub(r"(?<!^)(?=[A-Z])", " ", bare_name).replace("_", " ").strip().lower()
            description = (
                f"Provide {words} behavior."
                if isinstance(node, ast.ClassDef)
                else f"{words.capitalize()}."
            )
            indent = " " * (int(node.col_offset or 0) + 4)
            first_body_node = node.body[0]
            insertion_lineno = int(first_body_node.lineno)
            if isinstance(first_body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                insertion_lineno = min(
                    [insertion_lineno]
                    + [
                        int(decorator.lineno)
                        for decorator in first_body_node.decorator_list
                    ]
                )
            structured_fields_requested = bool(
                re.search(
                    r"(?:restructuredtext\s+fields?|:param\s+[a-z_][a-z0-9_]*:)",
                    request_prompt,
                    flags=re.IGNORECASE,
                )
            )
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and structured_fields_requested
            ):
                parameters = [
                    argument.arg
                    for argument in [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                    if argument.arg not in {"self", "cls"}
                ]
                if node.args.vararg is not None:
                    parameters.append(node.args.vararg.arg)
                if node.args.kwarg is not None:
                    parameters.append(node.args.kwarg.arg)
                fields = [
                    f"{indent}:param {parameter}: {parameter.replace('_', ' ')}"
                    for parameter in parameters
                ]
                fields.append(f"{indent}:return: {words} result")
                docstring = "\n".join(
                    [
                        f'{indent}"""{description}',
                        "",
                        *fields,
                        f'{indent}"""',
                        "",
                    ]
                )
            else:
                docstring = f'{indent}"""{description}"""\n'
            edits.append((insertion_lineno - 1, docstring))
            fixes.append(f"{Path(path_text).name}:{name}")
        for insertion_line, docstring in sorted(edits, reverse=True):
            lines[insertion_line:insertion_line] = [docstring]
        updated[index] = (path_text, original, "".join(lines))
    return updated, fixes


def enforce_project_edit_requested_test_contracts(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Materialize explicit path-related test contracts from the request."""

    prompt = str(request_prompt or "")
    expanduser_match = re.search(
        r"os\.path\.expanduser\(\s*(['\"])(?P<path>.+?)\1\s*\)",
        prompt,
    )
    wants_invalid_json = "invalid json" in prompt.lower()
    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        class_names = [
            alias.asname or alias.name
            for node in tree.body if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name.lower().endswith("tool")
        ]
        tool_class = class_names[0] if class_names else ""
        replacements: list[tuple[str, str]] = []
        for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            for method in [
                node for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                name_lower = method.name.lower()
                if expanduser_match and "dynamic" in name_lower and "path" in name_lower and tool_class:
                    replacement = (
                        f"def {method.name}(self):\n"
                        f"    tool = {tool_class}()\n"
                        f"    expected_path = os.path.expanduser({expanduser_match.group('path')!r})\n"
                        "    self.assertEqual(tool.path, expected_path)\n"
                    )
                    replacements.append((f"{class_node.name}.{method.name}", replacement))
                elif wants_invalid_json and "invalid" in name_lower and "json" in name_lower:
                    imported_loaders = [
                        (node.module or "", alias.name, alias.asname or alias.name)
                        for node in ast.walk(method) if isinstance(node, ast.ImportFrom)
                        for alias in node.names
                        if "load" in alias.name.lower()
                    ]
                    loader_module, loader_name, loader = (
                        imported_loaders[0]
                        if imported_loaders
                        else ("", "load_tasks", "load_tasks")
                    )
                    loader_import = (
                        f"    from {loader_module} import {loader_name}\n"
                        if loader_module
                        else ""
                    )
                    replacement = (
                        f"def {method.name}(self):\n"
                        f"{loader_import}"
                        "    with open(self.tool.path, 'w', encoding='utf-8') as handle:\n"
                        "        handle.write('invalid json')\n"
                        f"    self.assertEqual({loader}(self.tool.path), [])\n"
                    )
                    replacements.append((f"{class_node.name}.{method.name}", replacement))
        corrected = source
        for symbol, replacement in replacements:
            matched, corrected, _error = _edit_python_symbol_source(
                corrected,
                target_symbol=symbol,
                replacement=replacement,
                filename=path_text,
                operation="replace_symbol",
            )
            if matched:
                fixes.append(f"{Path(path_text).name}: materialized {symbol} test contract")
        updated[index] = (path_text, original, corrected)
    return updated, fixes


def _validate_candidate_changes_in_disposable_workspace(
    changes: list[dict[str, Any]],
    *,
    project_root: str | None,
    request_prompt: str = "",
    allowed_external_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Run the complete generated patch and focused tests outside the real project."""

    if not project_root:
        return [{
            "ok": False,
            "path": "",
            "check": "disposable_workspace",
            "command": "candidate:disposable_workspace",
            "message": "A project root is required for disposable generated-patch validation.",
        }]

    root = Path(project_root).resolve()
    allowed_external = {
        str(Path(path).resolve()).casefold()
        for path in (allowed_external_paths or set())
    }
    patch_files: list[dict[str, str]] = []
    copy_paths: list[str] = []
    python_paths: list[str] = []
    test_paths: list[str] = []
    qt_smoke_targets: list[tuple[str, str]] = []
    verification_targets: list[tuple[str, str]] = []
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
    unavailable_host_roots: set[str] = set()
    dependency_source_roots = list(dict.fromkeys(
        Path(value).resolve()
        for value in (
            root,
            Path(__file__).resolve().parents[2],
            Path(str(os.environ.get("TOOLSROOT") or "")).resolve()
            if str(os.environ.get("TOOLSROOT") or "").strip()
            else None,
        )
        if value is not None
    ))
    inspected_dependency_modules: set[str] = set()

    def inspect_dependency_host_imports(module_name: str) -> None:
        """Collect unavailable host roots from one exact local dependency module."""

        normalized_module = str(module_name or "").strip(".")
        if (
            not normalized_module
            or normalized_module in inspected_dependency_modules
        ):
            return
        inspected_dependency_modules.add(normalized_module)
        relative_module = Path(*normalized_module.split("."))
        dependency_source = next(
            (
                candidate
                for source_root in dependency_source_roots
                for candidate in (
                    source_root / relative_module.with_suffix(".py"),
                    source_root / relative_module / "__init__.py",
                )
                if candidate.is_file()
            ),
            None,
        )
        if dependency_source is None:
            return
        try:
            dependency_tree = ast.parse(
                dependency_source.read_text(encoding="utf-8"),
                filename=str(dependency_source),
            )
        except (OSError, UnicodeError, SyntaxError):
            return
        imported_modules = [
            alias.name
            for node in dependency_tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        imported_modules.extend(
            str(node.module or "")
            for node in dependency_tree.body
            if isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
        )
        for imported_module in imported_modules:
            imported_root = imported_module.split(".", 1)[0]
            if imported_root in _HOST_RUNTIME_MODULES:
                try:
                    host_available = (
                        importlib.util.find_spec(imported_root) is not None
                    )
                except (ImportError, ModuleNotFoundError, ValueError):
                    host_available = False
                if not host_available:
                    unavailable_host_roots.add(imported_root)

    for item in changes:
        path = Path(str(item.get("path") or "")).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            if str(path).casefold() not in allowed_external:
                return [{
                    "ok": False,
                    "path": str(path),
                    "check": "disposable_workspace",
                    "command": "candidate:disposable_workspace",
                    "message": (
                        "Generated patch path is outside the disposable project "
                        f"root: {path}"
                    ),
                }]
            relative = Path("__tech_connector_validation__") / path.name
        relative_text = relative.as_posix()
        patch_files.append({"path": relative_text, "content": str(item.get("after") or "")})
        if path.suffix.lower() == ".py":
            try:
                candidate_tree = ast.parse(
                    str(item.get("after") or ""),
                    filename=str(path),
                )
            except SyntaxError:
                candidate_tree = None
            if candidate_tree is not None:
                verification_targets.extend(
                    (relative_text, node.name)
                    for node in candidate_tree.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name in requested_verification_symbols
                    and any(
                        isinstance(child, ast.Assert)
                        for child in ast.walk(node)
                    )
                )
                qt_imported = any(
                    (
                        isinstance(node, ast.Import)
                        and any(
                            alias.name.startswith(("PySide", "PyQt"))
                            for alias in node.names
                        )
                    )
                    or (
                        isinstance(node, ast.ImportFrom)
                        and str(node.module or "").startswith(("PySide", "PyQt"))
                    )
                    for node in candidate_tree.body
                )
                if qt_imported:
                    for class_node in candidate_tree.body:
                        if not isinstance(class_node, ast.ClassDef):
                            continue
                        base_names = {
                            ast.unparse(base).rsplit(".", 1)[-1]
                            for base in class_node.bases
                        }
                        if base_names & {
                            "QDialog",
                            "QMainWindow",
                            "QWidget",
                        }:
                            qt_smoke_targets.append(
                                (relative_text, class_node.name)
                            )
                            break
                imported_roots = {
                    alias.name.split(".", 1)[0]
                    for node in candidate_tree.body
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imported_roots.update(
                    str(node.module or "").split(".", 1)[0]
                    for node in candidate_tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                )
                imported_modules = {
                    alias.name
                    for node in candidate_tree.body
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imported_modules.update(
                    str(node.module or "")
                    for node in candidate_tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                )
                for imported_module in sorted(imported_modules):
                    inspect_dependency_host_imports(imported_module)
                for imported_root in sorted(imported_roots):
                    dependency_path = root / imported_root
                    dependency_file = root / f"{imported_root}.py"
                    if (
                        dependency_path.exists() or dependency_file.exists()
                    ) and imported_root not in copy_paths:
                        copy_paths.append(imported_root)
                    if imported_root in _HOST_RUNTIME_MODULES:
                        try:
                            host_available = (
                                importlib.util.find_spec(imported_root) is not None
                            )
                        except (ImportError, ModuleNotFoundError, ValueError):
                            host_available = False
                        if not host_available:
                            unavailable_host_roots.add(imported_root)
        if path.suffix.lower() == ".py":
            python_paths.append(relative_text)
            if _is_test_path(path):
                test_paths.append(relative_text)

    for host_root in sorted(unavailable_host_roots):
        if "." in host_root:
            continue
        if host_root == "maya":
            patch_files.extend([
                {
                    "path": "maya/__init__.py",
                    "content": '"""Disposable Maya package stub."""\n',
                },
                {
                    "path": "maya/cmds.py",
                    "content": (
                        '"""Disposable dynamic maya.cmds stub."""\n'
                        "from unittest.mock import MagicMock\n\n"
                        "def __getattr__(name):\n"
                        "    value = MagicMock(name=name)\n"
                        "    globals()[name] = value\n"
                        "    return value\n"
                    ),
                },
            ])
            continue
        patch_files.append({
            "path": f"{host_root}.py",
            "content": (
                '"""Disposable dynamic host API stub for focused tests."""\n'
                "from unittest.mock import MagicMock\n\n"
                "def __getattr__(name):\n"
                "    value = MagicMock(name=name)\n"
                "    globals()[name] = value\n"
                "    return value\n"
            ),
        })

    commands: list[list[str]] = []
    if python_paths:
        commands.append(["python", "-m", "py_compile", *python_paths])
    for test_path in test_paths:
        test = Path(test_path)
        commands.append([
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            test.parent.as_posix() or ".",
            "-p",
            test.name,
        ])
    for verification_path, verification_symbol in verification_targets:
        commands.append([
            "python",
            "-c",
            (
                "import importlib.util, sys; "
                "spec=importlib.util.spec_from_file_location("
                "'generated_verification', sys.argv[1]); "
                "module=importlib.util.module_from_spec(spec); "
                "sys.modules[spec.name]=module; "
                "spec.loader.exec_module(module); "
                "getattr(module, sys.argv[2])()"
            ),
            verification_path,
            verification_symbol,
        ])
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
    if explicit_single_file_scope and not test_paths and len(python_paths) == 1:
        if qt_smoke_targets:
            smoke_path, smoke_class = qt_smoke_targets[0]
            requested_buttons = list(dict.fromkeys(
                re.findall(
                    r"\b([a-z_][A-Za-z0-9_]*(?:_btn|_button))\b",
                    request_prompt,
                )
            ))
            commands.append([
                "python",
                "-c",
                (
                    "import importlib.util, os, sys; "
                    "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen'); "
                    "from PySide6.QtWidgets import QApplication, QPushButton; "
                    "spec=importlib.util.spec_from_file_location('generated_ui', sys.argv[1]); "
                    "module=importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(module); "
                    "app=QApplication.instance() or QApplication([]); "
                    "widget=getattr(module, sys.argv[2])(); "
                    "assert widget is not None; "
                    "buttons=[getattr(widget, name) for name in sys.argv[3:] "
                    "if hasattr(widget, name)]; "
                    "assert all(isinstance(button, QPushButton) for button in buttons); "
                    "[button.click() for button in buttons]; app.processEvents(); "
                    "widget.close(); app.processEvents()"
                ),
                smoke_path,
                smoke_class,
                *requested_buttons,
            ])
        else:
            commands.append(["python", python_paths[0]])

    from tech_connector.services.code_operation_service import validate_patch_in_temp_workspace

    validation = validate_patch_in_temp_workspace(
        source_root=root,
        patch_files=patch_files,
        validation_commands=commands,
        copy_paths=copy_paths,
        additional_python_paths=list(dict.fromkeys(
            value
            for value in (
                str(Path(__file__).resolve().parents[2]),
                str(os.environ.get("TOOLSROOT") or "").strip(),
            )
            if value
        )),
        timeout_seconds=8,
        keep_workspace=False,
    )
    results: list[dict[str, Any]] = []
    for command_result in validation.get("commands") or []:
        command = [str(value) for value in command_result.get("command") or []]
        output = "\n".join(
            part.strip()
            for part in (
                str(command_result.get("stdout") or ""),
                str(command_result.get("stderr") or ""),
            )
            if part.strip()
        )
        is_unittest = len(command) >= 3 and command[1:3] == ["-m", "unittest"]
        match = re.search(r"Ran\s+(\d+)\s+tests?", output) if is_unittest else None
        ran_tests = int(match.group(1)) if match else 0
        ok = command_result.get("exit_code") == 0 and (not is_unittest or ran_tests > 0)
        if ok and is_unittest:
            message = f"Disposable focused behavior tests passed ({ran_tests} test{'s' if ran_tests != 1 else ''})."
        elif ok:
            message = "Disposable generated patch parses and compiles."
        else:
            detail = output[-10000:] or str(
                command_result.get("error")
                or (
                    f"Process exited with code {command_result.get('exit_code')} and no output. "
                    "For Qt tests that construct a QWidget, create or reuse QApplication before "
                    "constructing the widget and use a headless Qt platform."
                    if is_unittest
                    else f"Process exited with code {command_result.get('exit_code')} and no output."
                )
            )
            message = "Disposable generated-patch validation failed: " + detail
        results.append({
            "ok": ok,
            "path": "",
            "check": "disposable_unittest" if is_unittest else "disposable_compile",
            "command": " ".join(command),
            "message": message,
        })
    if not results:
        results.append({
            "ok": False,
            "path": "",
            "check": "disposable_workspace",
            "command": "candidate:disposable_workspace",
            "message": "Disposable generated-patch validation did not execute any commands.",
        })
    return results


def _requires_behavior_test(prompt: str) -> bool:
    lower = str(prompt or "").lower()
    if not lower:
        return False
    if re.search(r"\b(docstring|documentation|comment|comments|formatting|rename only)\b", lower):
        return False
    mutation = bool(re.search(r"\b(add|build|create|fix|implement|improve|patch|refactor|repair|update|wire)\b", lower))
    behavior = bool(re.search(r"\b(behavior|class|feature|function|functionality|helper|method|pipeline|tool|ui|workflow)\b", lower))
    if mutation and re.search(r"\b(test|tests|unittest|coverage)\b", lower):
        return True
    return mutation and behavior


def _requested_public_symbol_names(prompt: str) -> set[str]:
    text = str(prompt or "")
    patterns = (
        r"\b(?:function|class|method|helper)\s+(?:named|called)\s+`?([A-Za-z_]\w*)`?",
        r"\b(?:add|create|implement)\s+(?:a\s+)?(?:new\s+)?(?:function|class|method|helper)\s+`?([A-Za-z_]\w*)`?",
    )
    return {
        match.group(1)
        for pattern in patterns
        for match in re.finditer(pattern, text, flags=re.IGNORECASE)
    }


def enforce_project_edit_explicit_cleanup(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Apply explicit identifier cleanup without rewriting unrelated source."""

    removed_identifiers, rename_pairs = _requested_identifier_contracts(request_prompt)
    if not removed_identifiers and not rename_pairs:
        return generated_files, []

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
            original_tree = ast.parse(original, filename=path_text) if original else ast.parse("")
        except SyntaxError:
            continue

        lines = source.splitlines(keepends=True)
        deletion_ranges: list[tuple[int, int, str]] = []
        for identifier in removed_identifiers:
            statements = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.stmt)
                and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and _tree_uses_identifier(node, identifier)
            ]
            for statement in sorted(
                statements,
                key=lambda node: (int(node.end_lineno or node.lineno) - node.lineno, node.lineno),
            ):
                statement_range = (
                    statement.lineno - 1,
                    int(statement.end_lineno or statement.lineno),
                    identifier,
                )
                if not any(
                    statement_range[0] <= start and statement_range[1] >= end
                    for start, end, _name in deletion_ranges
                ):
                    deletion_ranges.append(statement_range)

        for start, end, identifier in sorted(deletion_ranges, reverse=True):
            del lines[start:end]
            fixes.append(f"{Path(path_text).name}: removed statement using {identifier}")
        cleaned = "".join(lines)

        rename_map = dict(rename_pairs)
        if rename_map:
            rewritten = [
                tokenize.TokenInfo(
                    token.type,
                    rename_map.get(token.string, token.string)
                    if token.type == tokenize.NAME else token.string,
                    token.start,
                    token.end,
                    token.line,
                )
                for token in tokenize.generate_tokens(io.StringIO(cleaned).readline)
            ]
            cleaned = tokenize.untokenize(rewritten)
            for source_name, target_name in rename_pairs:
                if _tree_uses_identifier(tree, source_name) and source_name not in removed_identifiers:
                    fixes.append(f"{Path(path_text).name}: renamed {source_name} to {target_name}")

        try:
            cleaned_tree = ast.parse(cleaned, filename=path_text)
        except SyntaxError:
            continue
        before_defs = _public_definition_map(original_tree)
        after_defs = _public_definition_map(cleaned_tree)
        requested_symbols = _requested_public_symbol_names(request_prompt)
        unrequested_nodes = [
            node
            for name, node in after_defs.items()
            if name not in before_defs
            and name.rsplit(".", 1)[-1] not in requested_symbols
            and not re.search(
                rf"\b{re.escape(name.rsplit('.', 1)[-1])}\b",
                request_prompt,
                flags=re.IGNORECASE,
            )
        ]
        cleaned_lines = cleaned.splitlines(keepends=True)
        for node in sorted(unrequested_nodes, key=lambda item: item.lineno, reverse=True):
            del cleaned_lines[node.lineno - 1:int(node.end_lineno or node.lineno)]
            fixes.append(f"{Path(path_text).name}: removed unrequested public {node.name}")
        final_source = "".join(cleaned_lines).rstrip() + "\n"
        try:
            compile(ast.parse(final_source, filename=path_text), path_text, "exec")
        except (SyntaxError, ValueError):
            continue
        updated[index] = (path_text, original, final_source)
    return updated, fixes


def project_edit_has_core_contract_failure(errors: list[str], request_prompt: str) -> bool:
    """Return whether a candidate failed to define a specifically requested symbol."""

    requested = {name.lower() for name in _requested_public_symbol_names(request_prompt)}
    for error in errors:
        lowered = str(error or "").lower()
        if any(
            marker in lowered
            for marker in (
                "requested public symbols",
                "cannot import its requested implementation from itself",
            )
        ):
            return True
        unresolved_requested_symbol = any(name in lowered for name in requested) and any(
            marker in lowered
            for marker in (
                "symbol was not found",
                "could not resolve symbol",
                "cannot resolve",
            )
        )
        if unresolved_requested_symbol:
            return True
    return False


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _build_explicit_active_edit_discovery(
    prompt: str,
    *,
    active_path: str | None,
    limit: int,
) -> dict[str, Any] | None:
    """Resolve an explicitly named active Python file from indexed facts only."""

    path = Path(str(active_path or ""))
    if path.suffix.lower() != ".py":
        return None
    lowered = str(prompt or "").lower().replace("\\", "/")
    explicit_file = path.name.lower() in lowered or str(path).lower().replace("\\", "/") in lowered
    active_reference = bool(re.search(r"\b(this|current|active)\s+file\b", lowered))
    if not (explicit_file or active_reference):
        return None

    from tech_connector.services.file_index_service import file_index_service

    snapshot = file_index_service.get_file_snapshot(
        str(path),
        symbol_limit=max(24, int(limit or 8) * 4),
    )
    if snapshot is None:
        return None
    terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt or "")
        if term.lower() not in {"add", "and", "file", "function", "method", "only", "the", "this", "with"}
    }
    roots = [str(snapshot.get("root") or "").strip()]
    roots = [root for root in roots if root]
    project_root = Path(roots[0]).resolve() if roots else path.parent.resolve()

    def candidate_from_snapshot(indexed_snapshot: dict[str, Any], score: int) -> dict[str, Any]:
        indexed_path = str(indexed_snapshot.get("path") or "")
        symbols: list[dict[str, Any]] = []
        for indexed_symbol in indexed_snapshot.get("symbols") or []:
            symbol = dict(indexed_symbol)
            qualname = str(symbol.get("qualname") or symbol.get("name") or "")
            source = str(symbol.get("source") or "")
            relevance = sum(12 for term in terms if term in qualname.lower())
            relevance += sum(min(source.lower().count(term), 3) for term in terms)
            symbol.update({"path": indexed_path, "relevance": relevance})
            symbols.append(symbol)
        symbols.sort(key=lambda item: (-int(item.get("relevance") or 0), int(item.get("start_line") or 1)))
        return {
            "path": indexed_path,
            "score": score,
            "symbols": symbols[: max(8, int(limit or 8) * 2)],
            "chunks": [],
            "index_revision": str(indexed_snapshot.get("sha1") or ""),
        }

    candidate = candidate_from_snapshot(snapshot, 100)
    candidates = [candidate]
    named_files = list(dict.fromkeys(
        match.group(0).lower()
        for match in re.finditer(r"(?<![\w.-])[\w.-]+\.py\b", lowered)
    ))
    for filename in named_files:
        if filename == path.name.lower():
            continue
        matches = [
            Path(candidate_path)
            for candidate_path in file_index_service.find_indexed_paths_by_name(filename)
            if _path_is_within(Path(candidate_path), project_root)
            and not any(part.startswith(".") for part in Path(candidate_path).relative_to(project_root).parts)
        ]
        if len(matches) != 1:
            continue
        sibling_snapshot = file_index_service.get_file_snapshot(
            str(matches[0]),
            symbol_limit=max(24, int(limit or 8) * 4),
        )
        if sibling_snapshot is not None:
            candidates.append(candidate_from_snapshot(sibling_snapshot, 95 - len(candidates)))
    return {
        "question": prompt,
        "terms": sorted(terms)[:20],
        "scope": "active_file",
        "project_roots": roots,
        "active_path": candidate["path"],
        "best_target": candidate,
        "candidates": candidates,
        "confidence": "high",
        "evidence_mode": "explicit_index_snapshot",
        "index_revision": str(snapshot.get("sha1") or ""),
    }


def _python_symbol_source_entries(path: Path) -> list[tuple[str, str]]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return []
    entries: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entries.append((node.name, ast.get_source_segment(source, node) or ""))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    entries.append((f"{node.name}.{child.name}", ast.get_source_segment(source, child) or ""))
    return [(name, segment) for name, segment in entries if segment.strip()]


def _indexed_symbol_source_entries(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    """Return callable boundaries already captured by the project index."""

    entries: list[tuple[str, str]] = []
    for item in snapshot.get("symbols") or []:
        kind = str(item.get("kind") or "").lower()
        if kind not in {"function", "async_function", "method", "async_method"}:
            continue
        name = str(item.get("qualname") or item.get("name") or "").strip()
        source = str(item.get("source") or "").strip()
        if name and source:
            entries.append((name, source))
    return entries


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _project_edit_leaf_handoff_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def project_edit_leaf_work_units_handoff(
    work_units: ProjectEditLeafWorkUnits,
) -> dict[str, Any]:
    """Serialize bounded edit ownership without carrying source blobs in UI state."""

    payload = {
        "version": 1,
        "helper_name": work_units.helper_name,
        "target_path": work_units.target_path,
        "integration_symbol": work_units.integration_symbol,
        "test_path": work_units.test_path,
        "test_anchor_symbol": work_units.test_anchor_symbol,
        "owner_module": work_units.owner_module,
        "target_revision": work_units.target_revision,
        "test_revision": work_units.test_revision,
    }
    payload["fingerprint"] = _project_edit_leaf_handoff_fingerprint(payload)
    return payload


def restore_project_edit_leaf_work_units(
    payload: dict[str, Any] | None,
    request_prompt: str,
) -> tuple[ProjectEditLeafWorkUnits | None, list[str]]:
    """Restore approved work units after exact-file revision validation."""

    data = dict(payload or {})
    if int(data.get("version") or 0) != 1:
        return None, ["The approved work-unit handoff version is unsupported."]
    expected_fingerprint = str(data.pop("fingerprint", ""))
    if expected_fingerprint != _project_edit_leaf_handoff_fingerprint(data):
        return None, ["The approved work-unit handoff was modified."]
    helper_name = str(data.get("helper_name") or "")
    if helper_name not in _requested_public_symbol_names(request_prompt):
        return None, ["The approved helper no longer matches the request."]
    owner_module = str(data.get("owner_module") or "")
    if not owner_module or not all(part.isidentifier() for part in owner_module.split(".")):
        return None, ["The approved owner module is invalid."]

    target_path = Path(str(data.get("target_path") or ""))
    test_path = Path(str(data.get("test_path") or ""))
    if target_path.suffix.lower() != ".py" or test_path.suffix.lower() != ".py":
        return None, ["The approved bounded files are not Python source files."]
    revision_errors: list[str] = []
    for label, path, revision in (
        ("target", target_path, str(data.get("target_revision") or "")),
        ("test", test_path, str(data.get("test_revision") or "")),
    ):
        actual = _sha1_file(path)
        if not revision or actual != revision:
            revision_errors.append(
                f"The approved {label} file changed after indexing: {path}. Refresh that file in the index and regenerate the plan."
            )
    if revision_errors:
        return None, revision_errors

    target_entries = dict(_python_symbol_source_entries(target_path))
    test_entries = dict(_python_symbol_source_entries(test_path))
    integration_symbol = str(data.get("integration_symbol") or "")
    test_anchor_symbol = str(data.get("test_anchor_symbol") or "")
    integration_source = target_entries.get(integration_symbol, "")
    test_anchor_source = test_entries.get(test_anchor_symbol, "")
    if not integration_source or not test_anchor_source:
        return None, ["An approved symbol boundary is no longer present in its exact file."]
    return ProjectEditLeafWorkUnits(
        helper_name=helper_name,
        target_path=str(target_path.resolve()),
        integration_symbol=integration_symbol,
        integration_source=integration_source,
        test_path=str(test_path.resolve()),
        test_anchor_symbol=test_anchor_symbol,
        test_anchor_source=test_anchor_source,
        owner_module=owner_module,
        target_revision=str(data.get("target_revision") or ""),
        test_revision=str(data.get("test_revision") or ""),
    ), []


def _leaf_ranking_terms(text: str) -> set[str]:
    ignored = {
        "accepts", "actual", "after", "apply", "changes", "concise", "coverage", "dictionaries",
        "focused", "function", "human", "named", "only", "preview", "produce", "readable", "returns",
        "reusable", "reuse", "unittest", "where", "with",
    }
    return {
        term.lower()
        for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", str(text or ""))
        if term.lower() not in ignored
    }


def _select_leaf_integration_symbol(
    entries: list[tuple[str, str]],
    *,
    approved_plan: str,
    objective: str,
) -> tuple[str, str] | None:
    lowered_plan = str(approved_plan or "").lower()
    lowered_objective = str(objective or "").lower()
    terms = _leaf_ranking_terms(objective)
    ranked: list[tuple[int, int, int, str, str]] = []
    for name, source in entries:
        bare_name = name.rsplit(".", 1)[-1]
        plan_positions = [
            position for candidate in (name.lower(), bare_name.lower())
            if (position := lowered_plan.find(candidate)) >= 0
        ]
        objective_positions = [
            position for candidate in (name.lower(), bare_name.lower())
            if (position := lowered_objective.find(candidate)) >= 0
        ]
        if not plan_positions and not objective_positions:
            continue
        lowered_source = source.lower()
        relevance = sum(12 for term in terms if term in bare_name.lower())
        relevance += sum(min(lowered_source.count(term), 4) for term in terms)
        explicit_objective = 1 if objective_positions else 0
        first_position = min(objective_positions or plan_positions)
        ranked.append((explicit_objective, relevance, -first_position, name, source))
    if not ranked:
        return None
    _objective, _relevance, _position, name, source = max(ranked)
    return name, source


def _select_leaf_test_anchor(
    entries: list[tuple[str, str]],
    *,
    approved_plan: str,
    objective: str,
    helper_name: str,
    integration_symbol: str,
) -> tuple[str, str] | None:
    if not entries:
        return None
    lowered_plan = str(approved_plan or "").lower()
    terms = _leaf_ranking_terms(" ".join((objective, helper_name, integration_symbol)))
    integration_name = integration_symbol.rsplit(".", 1)[-1].lower()
    ranked: list[tuple[int, str, str]] = []
    for name, source in entries:
        bare_name = name.rsplit(".", 1)[-1]
        lowered_source = source.lower()
        score = 200 if name.lower() in lowered_plan or bare_name.lower() in lowered_plan else 0
        if integration_name and re.search(rf"\b{re.escape(integration_name)}\b", lowered_source):
            score += 300
        score += sum(12 for term in terms if term in bare_name.lower())
        score += sum(min(lowered_source.count(term), 4) for term in terms)
        ranked.append((score, name, source))
    _score, name, source = max(ranked)
    return name, source


def compile_project_edit_leaf_work_units(
    plan: ProjectEditPlan,
    approved_plan: str,
) -> ProjectEditLeafWorkUnits | None:
    """Compile bounded leaf tasks when the plan proves every edit boundary."""

    requested_symbols = sorted(_requested_public_symbol_names(plan.prompt))
    if len(requested_symbols) != 1 or not _requires_behavior_test(plan.prompt):
        return None

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    target_path = Path(str(best_target.get("path") or plan.active_path or ""))
    if target_path.suffix.lower() != ".py":
        return None

    roots = [Path(str(root)).resolve() for root in discovery.get("project_roots") or [] if str(root).strip()]
    from tech_connector.services.file_index_service import file_index_service

    target_snapshot = file_index_service.get_file_snapshot(str(target_path), symbol_limit=300)
    if target_snapshot is None:
        return None

    project_root = None
    test_path = None
    test_snapshot = None
    for ancestor in target_path.resolve().parents:
        if roots and not any(ancestor == root or _path_is_within(ancestor, root) for root in roots):
            continue
        candidate = ancestor / "tests" / f"test_{target_path.stem}.py"
        candidate_snapshot = file_index_service.get_file_snapshot(str(candidate), symbol_limit=300)
        if candidate_snapshot is not None:
            project_root = ancestor
            test_path = candidate
            test_snapshot = candidate_snapshot
            break
    if project_root is None or test_path is None or test_snapshot is None:
        return None

    target_symbols = _indexed_symbol_source_entries(target_snapshot)
    integration = _select_leaf_integration_symbol(
        target_symbols,
        approved_plan=approved_plan,
        objective=plan.prompt,
    )
    if integration is None:
        return None

    helper_name = requested_symbols[0]
    test_symbols = [
        entry for entry in _indexed_symbol_source_entries(test_snapshot)
        if entry[0].rsplit(".", 1)[-1].startswith("test_")
    ]
    test_anchor = _select_leaf_test_anchor(
        test_symbols,
        approved_plan=approved_plan,
        objective=plan.prompt,
        helper_name=helper_name,
        integration_symbol=integration[0],
    )
    if test_anchor is None:
        return None

    try:
        relative_module = target_path.resolve().relative_to(project_root).with_suffix("")
    except (OSError, ValueError):
        return None
    if not relative_module.parts or not all(part.isidentifier() for part in relative_module.parts):
        return None

    return ProjectEditLeafWorkUnits(
        helper_name=helper_name,
        target_path=str(target_path.resolve()),
        integration_symbol=integration[0],
        integration_source=integration[1],
        test_path=str(test_path.resolve()),
        test_anchor_symbol=test_anchor[0],
        test_anchor_source=test_anchor[1],
        owner_module=".".join(relative_module.parts),
        target_revision=str(target_snapshot.get("sha1") or ""),
        test_revision=str(test_snapshot.get("sha1") or ""),
    )


def _ast_references_name(node: ast.AST, name: str) -> bool:
    return any(
        (isinstance(child, ast.Name) and child.id == name)
        or (isinstance(child, ast.Attribute) and child.attr == name)
        for child in ast.walk(node)
    )


def _unwrap_single_test_method(
    source: str,
    tree: ast.Module,
    *,
    required_reference: str = "",
) -> str:
    """Extract one relevant generated test from an unnecessary class wrapper."""

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if not classes:
        return ""
    methods = [
        node
        for class_node in classes
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    relevant = [
        method for method in methods
        if not required_reference or _ast_references_name(method, required_reference)
    ]
    if len(relevant) != 1:
        return ""
    segment = ast.get_source_segment(source, relevant[0]) or ""
    return textwrap.dedent(segment).strip("\r\n")


def _objective_requires_validation_result_collection(objective: str) -> bool:
    lowered = str(objective or "").lower()
    return (
        "validation" in lowered
        and bool(re.search(r"\b(dict|dictionaries|results?)\b", lowered))
        and bool(re.search(r"\b(lines?|messages?)\b", lowered))
    )


def _ast_has_validation_failure_filter(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    def references_ok(node: ast.AST) -> bool:
        return any(
            (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "get"
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and child.args[0].value == "ok"
            )
            or (
                isinstance(child, ast.Subscript)
                and isinstance(child.slice, ast.Constant)
                and child.slice.value == "ok"
            )
            for child in ast.walk(node)
        )

    if any(isinstance(node, ast.If) and references_ok(node.test) for node in ast.walk(function)):
        return True
    return any(
        references_ok(condition)
        for node in ast.walk(function)
        if isinstance(node, ast.comprehension)
        for condition in node.ifs
    )


def _validate_project_edit_leaf_objective_contract(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    kind: str,
    objective: str,
    required_reference: str,
) -> list[str]:
    if not _objective_requires_validation_result_collection(objective):
        return []
    if kind == "define":
        positional = list(function.args.posonlyargs) + list(function.args.args)
        if not positional:
            return ["Leaf definition must accept validation result dictionaries directly."]
        parameter = positional[0]
        annotation = ast.unparse(parameter.annotation).lower() if parameter.annotation is not None else ""
        return_annotation = ast.unparse(function.returns).lower() if function.returns is not None else ""
        if "projecteditapplyresult" in annotation or any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == parameter.arg
            and node.attr == "validation"
            for node in ast.walk(function)
        ):
            return ["Leaf definition must accept validation dictionaries, not a result wrapper object."]
        if annotation and "dict" not in annotation:
            return ["Leaf definition needs a precise collection-of-dictionaries input annotation."]
        if return_annotation and "str" in return_annotation and not any(
            collection in return_annotation for collection in ("list", "sequence", "iterable", "tuple")
        ):
            return ["Leaf definition must return individual failure lines as a collection, not one string."]
        if return_annotation and not (
            "str" in return_annotation
            and any(collection in return_annotation for collection in ("list", "sequence", "iterable", "tuple"))
        ):
            return ["Leaf definition needs a precise collection-of-string-lines return annotation."]
        if any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "join"
            for node in ast.walk(function)
        ):
            return ["Leaf definition must return individual failure lines, not a joined report string."]
        if not _ast_has_validation_failure_filter(function):
            return ["Leaf definition must exclude validation entries whose ok value is true."]
    if kind == "integrate" and required_reference:
        wrapper_parameters = {
            arg.arg
            for arg in list(function.args.posonlyargs) + list(function.args.args)
            if arg.annotation is not None
            and "projecteditapplyresult" in ast.unparse(arg.annotation).lower()
        }
        calls = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name) and node.func.id == required_reference
                or isinstance(node.func, ast.Attribute) and node.func.attr == required_reference
            )
        ]
        if calls and all(
            call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id in wrapper_parameters
            for call in calls
        ):
            return ["Leaf integration must pass the validation collection, not its wrapper parameter."]
    return []


def parse_project_edit_leaf_source(
    response: str,
    *,
    kind: str,
    expected_symbol: str,
    required_reference: str = "",
    objective: str = "",
) -> tuple[str, list[str]]:
    """Validate a source-only worker result before deterministic composition."""

    text = str(response or "").strip()
    source: str | None = None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            return "", [f"Leaf {kind} response was not valid JSON: {exc}"]
        source = payload.get("source") if isinstance(payload, dict) else None
    else:
        source = re.sub(r"^```(?:python|py)?\s*", "", text, flags=re.IGNORECASE)
        source = re.sub(r"\s*```$", "", source)
    if not isinstance(source, str) or not source.strip():
        return "", [f"Leaf {kind} response did not contain source."]
    source = textwrap.dedent(source).strip("\r\n")
    try:
        tree = ast.parse(source, filename=f"<project-edit-{kind}>")
        compile(tree, f"<project-edit-{kind}>", "exec")
    except (SyntaxError, ValueError) as exc:
        return "", [f"Leaf {kind} source did not parse and compile: {exc}"]

    if kind == "test":
        unwrapped = _unwrap_single_test_method(
            source,
            tree,
            required_reference=required_reference,
        )
        if unwrapped:
            source = unwrapped
            tree = ast.parse(source, filename="<project-edit-test>")

    definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    non_definitions = [node for node in tree.body if node not in definitions]
    if len(definitions) != 1 or non_definitions:
        return "", [f"Leaf {kind} source must contain exactly one function and no imports or extra statements."]
    function = definitions[0]
    expected_name = str(expected_symbol or "").rsplit(".", 1)[-1]
    if kind == "test":
        if not function.name.startswith("test_"):
            return "", ["Leaf test source must define one test_* method."]
    elif function.name != expected_name:
        return "", [f"Leaf {kind} source defined {function.name}, expected {expected_name}."]
    if kind == "define" and not ast.get_docstring(function):
        return "", [f"Leaf definition {expected_name} needs a useful docstring."]
    if any(isinstance(node, ast.Pass) for node in ast.walk(function)) or any(
        isinstance(node, ast.Constant) and node.value is Ellipsis for node in ast.walk(function)
    ):
        return "", [f"Leaf {kind} source contained a placeholder body."]
    if required_reference and not _ast_references_name(function, required_reference):
        return "", [f"Leaf {kind} source did not reference required symbol {required_reference}."]
    contract_errors = _validate_project_edit_leaf_objective_contract(
        function,
        kind=kind,
        objective=objective,
        required_reference=required_reference,
    )
    if contract_errors:
        return "", contract_errors
    return source, []


def _is_self_import(
    target_path: Path,
    module: str,
    level: int,
    *,
    project_root: str | None,
) -> bool:
    if level or not module:
        return False
    try:
        root = Path(project_root).resolve() if project_root else target_path.parent.resolve()
        relative = target_path.resolve().relative_to(root).with_suffix("")
    except (OSError, ValueError):
        return False
    current_module = ".".join(relative.parts)
    return module == current_module


def _ensure_python_from_import(
    source: str,
    *,
    module: str,
    symbol: str,
    filename: str,
) -> tuple[bool, str, str]:
    """Insert one validated from-import without rewriting existing imports."""

    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module):
        return False, source, f"Invalid import module for {filename}: {module or '(missing)'}"
    if not symbol.isidentifier():
        return False, source, f"Invalid imported symbol for {filename}: {symbol or '(missing)'}"
    if _is_self_import(Path(filename), module, 0, project_root=None):
        return True, source, ""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return False, source, f"Cannot ensure import; existing Python did not parse: {exc}"

    matching_imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module
    ]
    if any(alias.name == symbol for node in matching_imports for alias in node.names):
        return True, source, ""

    anchors: list[ast.AST] = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    if matching_imports:
        anchor = matching_imports[-1]
    elif anchors:
        anchor = anchors[-1]
    elif tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        anchor = tree.body[0]
    else:
        anchor = None

    lines = source.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[: int(getattr(anchor, "end_lineno", 0) or 0)]) if anchor else 0
    prefix = source[:offset]
    suffix = source[offset:]
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += "\n"
    statement = f"from {module} import {symbol}\n"
    if anchor and not isinstance(anchor, (ast.Import, ast.ImportFrom)):
        statement = "\n" + statement
    if suffix and not suffix.startswith(("\n", "\r")) and not statement.endswith(("\n", "\r")):
        statement += "\n"
    return True, prefix + statement + suffix, ""


def _resolve_model_changes(
    model_response: str,
    *,
    project_root: str | None = None,
    allowed_external_paths: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    from tech_connector.knowledge.search import parse_multi_file_changes, replace_content_resilient

    root = Path(project_root).resolve() if project_root else None

    def _normalize_candidate_path(raw_path: str) -> str:
        path_text = str(raw_path or "").strip().replace("\\", "/")
        if not path_text:
            return ""
        if root is None or not _is_forbidden_edit_path(path_text):
            return path_text
        path_obj = Path(path_text)
        if path_obj.is_absolute():
            parts = path_obj.parts
            for idx, part in enumerate(parts):
                if part.lower() == "unreal_tools":
                    return str(root.joinpath(*parts[idx:]))
            return str(root / path_obj.name)
        return path_text

    changes, errors, structured = _parse_structured_project_changes(
        model_response,
        project_root=project_root,
        allowed_external_paths=allowed_external_paths,
    )
    if not structured:
        changes = parse_multi_file_changes(model_response or "", project_root or "")
    states: dict[str, dict[str, Any]] = {}
    for change in changes:
        action = str(change.get("action") or "")
        path = _normalize_candidate_path(str(change.get("path") or ""))
        if not path:
            errors.append("Change is missing a path.")
            continue
        if _is_forbidden_edit_path(path):
            errors.append(_edit_error_for_forbidden_path(path))
            continue
        if not action:
            action = "modify"
        if action == "create":
            states[path] = {
                "action": "create",
                "path": path,
                "before": "",
                "after": _sanitize_python_candidate_text(change.get("new_content")),
            }
            continue
        p = Path(path)
        if not p.exists():
            if p.suffix.lower() == ".py":
                states[path] = {
                    "action": "create",
                    "path": path,
                    "before": "",
                    "after": _sanitize_python_candidate_text(change.get("new_content")),
                }
            else:
                errors.append(f"Cannot modify missing file: {path}; switch to create or provide existing target.")
            continue
        state = states.get(path)
        if state is None:
            before = p.read_text(encoding="utf-8", errors="replace")
            state = {"action": "modify", "path": path, "before": before, "after": before}
            states[path] = state
        current = str(state.get("after") or "")
        if action == "ensure_import":
            if p.suffix.lower() != ".py":
                errors.append(f"Cannot ensure a Python import in a non-Python file: {path}")
                continue
            module = str(change.get("target_symbol") or "").strip()
            symbol = str(change.get("new_content") or "").strip()
            matched, after, error = _ensure_python_from_import(
                current,
                module=module,
                symbol=symbol,
                filename=str(p),
            )
            if not matched:
                errors.append(error or f"Could not ensure import {module}.{symbol}: {path}")
                continue
            state["after"] = after
            continue
        if action in {"replace_text", "insert_before_text", "insert_after_text"}:
            anchor = str(change.get("target_symbol") or "")
            if not anchor:
                errors.append(f"{action} change is missing exact text anchor: {path}")
                continue
            occurrences = current.count(anchor)
            if occurrences != 1:
                errors.append(
                    f"{action} requires one exact anchor occurrence, found {occurrences}: {path}"
                )
                continue
            # Exact-text operations are language-neutral. Preserve leading and
            # trailing newlines because they are part of the requested splice;
            # Python snippet normalization would collapse C++/shader spacing.
            replacement = str(change.get("new_content") or "")
            if action == "insert_before_text":
                replacement = replacement + anchor
            elif action == "insert_after_text":
                replacement = anchor + replacement
            state["after"] = current.replace(anchor, replacement, 1)
            continue
        if action in {"replace_symbol", "insert_before_symbol", "insert_after_symbol"}:
            if p.suffix.lower() != ".py":
                errors.append(f"Cannot edit a Python symbol in a non-Python file: {path}")
                continue
            target_symbol = str(change.get("target_symbol") or "").strip()
            if not target_symbol:
                errors.append(f"{action} change is missing target_symbol: {path}")
                continue
            matched, after, error = _edit_python_symbol_source(
                current,
                target_symbol=target_symbol,
                replacement=_sanitize_python_candidate_text(change.get("new_content")),
                filename=str(p),
                operation=action,
            )
            if not matched:
                errors.append(error or f"Could not resolve symbol {target_symbol}: {path}")
                continue
            state["after"] = after
            continue
        if action != "modify":
            errors.append(f"Unsupported change action for {path}: {action}")
            continue
        matched, after = replace_content_resilient(
            current,
            str(change.get("original_content") or ""),
            _sanitize_python_candidate_text(change.get("new_content")),
        )
        if not matched:
            errors.append(f"Original block did not match: {path}")
            continue
        state["after"] = after
    return list(states.values()), errors
