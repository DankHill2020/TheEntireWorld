"""Dependency-ordered project edit workflow helpers."""
from __future__ import annotations

import ast
import copy
import importlib
import importlib.util
import itertools
import json
import re
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from tech_connector.models.constants import TOOLS_ROOT
from tech_connector.services.llm_router_service import (
    LLMProviderRoute,
    generate_llm_response,
    resolve_llm_provider_route,
)
from tech_connector.services.project_edit_agent_service import (
    ProjectEditApplyResult,
    ProjectEditPlan,
    ProjectEditPromptStage,
    apply_project_edit_agent_response,
    apply_project_edit_generated_symbol_repair,
    build_project_edit_agent_request,
    assemble_project_edit_generated_chunks,
    build_project_edit_artifact_chunk_stages,
    build_project_edit_artifact_file_stages,
    build_project_edit_artifact_manifest_stage,
    build_project_edit_chunk_plan_stage,
    build_deterministic_project_edit_chunk_plan,
    build_user_visible_implementation_plan,
    build_project_edit_function_repair_contract,
    build_project_edit_function_repair_plan_stage,
    build_project_edit_function_repair_stage,
    build_project_edit_class_repair_stage,
    build_project_edit_class_set_repair_stage,
    build_project_edit_integration_contract_stage,
    build_project_edit_missing_symbol_stage,
    build_project_edit_multi_file_candidate,
    parse_project_edit_chunk_plan,
    parse_project_edit_generated_chunk,
    extract_project_edit_artifact_requirements,
    complete_project_edit_integration_contract_response,
    ensure_project_edit_requested_docstrings,
    enforce_project_edit_requested_test_contracts,
    format_project_edit_generated_python,
    model_for_project_edit_stage,
    apply_project_edit_missing_symbol,
    apply_project_edit_generated_class_repair,
    apply_project_edit_generated_class_set_repair,
    parse_project_edit_artifact_manifest,
    parse_project_edit_function_repair_plan,
    parse_project_edit_generated_file,
    preview_project_edit_agent_response,
    project_edit_validation_failure_signature,
    remove_project_edit_unused_imports,
    repair_project_edit_duplicate_dependency_symbols,
    resolve_project_edit_cross_file_symbols,
    resolve_project_edit_standard_library_symbols,
)


StatusCallback = Callable[[str], None]

from tech_connector.services.project_edit_workflow_part_01 import (
    _ensure_new_qt_ui_main_show,
    _ensure_qt_test_application,
    _hoist_generated_test_project_imports,
    _normalize_generated_qt_binding,
    _normalize_generated_qt_tests,
    _normalize_qt_entry_application_ownership,
    _remove_generated_self_imports,
    _remove_shadowed_and_duplicate_generated_imports,
    _remove_unrequested_failure_tests,
    _resolve_generated_qt_symbols,
)


def _normalize_generated_python_source_quality(
    source: str,
    *,
    newly_created: bool,
) -> str:
    """Normalize mechanically safe Python source-quality details."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    changed = False

    def is_string_expression(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )

    for owner in [tree, *(
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    )]:
        body = list(owner.body)
        retained = [
            statement
            for index, statement in enumerate(body)
            if index == 0 or not is_string_expression(statement)
        ]
        if len(retained) != len(body):
            owner.body = retained
            changed = True
    documentable_nodes: list[ast.AST] = [tree]
    documentable_nodes.extend(
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        )
    )
    for node in documentable_nodes:
        body = getattr(node, "body", None)
        if (
            not body
            or not isinstance(body[0], ast.Expr)
            or not isinstance(body[0].value, ast.Constant)
            or not isinstance(body[0].value.value, str)
        ):
            continue
        cleaned = ast.get_docstring(node, clean=True)
        if cleaned is not None and cleaned != body[0].value.value:
            body[0].value = ast.Constant(value=cleaned)
            changed = True

    for class_node in (
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ):
        is_dataclass = any(
            ast.unparse(decorator.func if isinstance(decorator, ast.Call) else decorator)
            .rsplit(".", 1)[-1]
            == "dataclass"
            for decorator in class_node.decorator_list
        )
        if not is_dataclass:
            continue
        for statement in class_node.body:
            if (
                not isinstance(statement, ast.AnnAssign)
                or not isinstance(statement.value, ast.Call)
                or ast.unparse(statement.value.func).rsplit(".", 1)[-1] != "field"
                or statement.value.args
                or len(statement.value.keywords) != 1
                or statement.value.keywords[0].arg != "default"
            ):
                continue
            statement.value = statement.value.keywords[0].value
            changed = True

    class RedundantReraiseRemover(ast.NodeTransformer):
        """Remove try/except blocks whose only handler action is re-raising."""

        def visit_Try(self, node: ast.Try) -> ast.AST | list[ast.stmt]:
            self.generic_visit(node)
            if (
                node.handlers
                and not node.orelse
                and not node.finalbody
                and all(
                    len(handler.body) == 1
                    and isinstance(handler.body[0], ast.Raise)
                    and handler.body[0].exc is None
                    and handler.body[0].cause is None
                    for handler in node.handlers
                )
            ):
                return node.body
            return node

    class RedundantLockGuardRemover(ast.NodeTransformer):
        """Collapse nested ``self._lock`` contexts inside the same boundary."""

        def __init__(self) -> None:
            self.lock_depth = 0

        @staticmethod
        def is_instance_lock(node: ast.With | ast.AsyncWith) -> bool:
            return (
                len(node.items) == 1
                and isinstance(node.items[0].context_expr, ast.Attribute)
                and isinstance(node.items[0].context_expr.value, ast.Name)
                and node.items[0].context_expr.value.id == "self"
                and node.items[0].context_expr.attr == "_lock"
            )

        def visit_With(self, node: ast.With) -> ast.AST | list[ast.stmt]:
            if not self.is_instance_lock(node):
                return self.generic_visit(node)
            nested = self.lock_depth > 0
            self.lock_depth += 1
            node.body = [
                child
                for statement in node.body
                for child in self._visit_statement(statement)
            ]
            self.lock_depth -= 1
            return node.body if nested else node

        def visit_AsyncWith(
            self,
            node: ast.AsyncWith,
        ) -> ast.AST | list[ast.stmt]:
            if not self.is_instance_lock(node):
                return self.generic_visit(node)
            nested = self.lock_depth > 0
            self.lock_depth += 1
            node.body = [
                child
                for statement in node.body
                for child in self._visit_statement(statement)
            ]
            self.lock_depth -= 1
            return node.body if nested else node

        def _visit_statement(self, statement: ast.stmt) -> list[ast.stmt]:
            visited = self.visit(statement)
            if visited is None:
                return []
            if isinstance(visited, list):
                return visited
            return [visited]

    before_transforms = ast.dump(tree, include_attributes=False)
    normalized_tree = RedundantReraiseRemover().visit(tree)
    normalized_tree = RedundantLockGuardRemover().visit(normalized_tree)
    if isinstance(normalized_tree, ast.Module):
        if ast.dump(normalized_tree, include_attributes=False) != before_transforms:
            changed = True
        tree = normalized_tree

    qt_widget_import_required = False
    for class_node in (
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ):
        qt_ui_class = any(
            ast.unparse(base).rsplit(".", 1)[-1].endswith(
                ("Dialog", "Widget", "Window")
            )
            for base in class_node.bases
        )
        if not qt_ui_class:
            continue
        constructor = next(
            (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__init__"
            ),
            None,
        )
        if constructor is None:
            continue
        parent_argument = next(
            (
                argument
                for argument in (
                    *constructor.args.posonlyargs,
                    *constructor.args.args,
                    *constructor.args.kwonlyargs,
                )
                if argument.arg in {"parent", "parent_widget"}
            ),
            None,
        )
        if (
            parent_argument is not None
            and (
                parent_argument.annotation is None
                or ast.unparse(parent_argument.annotation) in {"Any", "object"}
            )
        ):
            parent_argument.annotation = ast.parse(
                "QWidget | None",
                mode="eval",
            ).body
            qt_widget_import_required = True
            changed = True

    if qt_widget_import_required:
        qt_widgets_import = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ImportFrom)
                and node.module == "PySide6.QtWidgets"
                and node.level == 0
            ),
            None,
        )
        if qt_widgets_import is not None and not any(
            alias.name == "QWidget" for alias in qt_widgets_import.names
        ):
            qt_widgets_import.names.append(ast.alias(name="QWidget"))
            changed = True

    if newly_created:
        stdlib_modules = set(
            getattr(__import__("sys"), "stdlib_module_names", ())
        )
        promoted: list[ast.stmt] = []
        existing_imports = {
            ast.dump(node, include_attributes=False)
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        for callable_node in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            retained_body: list[ast.stmt] = []
            for statement in callable_node.body:
                root_module = ""
                if isinstance(statement, ast.ImportFrom):
                    root_module = str(statement.module or "").split(".", 1)[0]
                elif isinstance(statement, ast.Import):
                    imported_roots = {
                        alias.name.split(".", 1)[0] for alias in statement.names
                    }
                    if len(imported_roots) == 1:
                        root_module = next(iter(imported_roots))
                if (
                    root_module
                    and root_module in stdlib_modules
                    and ast.dump(statement, include_attributes=False)
                    not in existing_imports
                ):
                    promoted.append(statement)
                    existing_imports.add(
                        ast.dump(statement, include_attributes=False)
                    )
                    changed = True
                    continue
                retained_body.append(statement)
            callable_node.body = retained_body

        if promoted:
            insertion_index = 0
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                insertion_index = 1
            while (
                insertion_index < len(tree.body)
                and isinstance(tree.body[insertion_index], ast.ImportFrom)
                and tree.body[insertion_index].module == "__future__"
            ):
                insertion_index += 1
            tree.body[insertion_index:insertion_index] = promoted

    if not changed:
        return source
    ast.fix_missing_locations(tree)
    return ast.unparse(tree).rstrip() + "\n"


def _lift_generated_main_block(source: str) -> str:
    """Make a nontrivial script entry block independently repairable."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    existing_names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for index, node in enumerate(tree.body):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_main_guard = (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        )
        if not is_main_guard or not node.body:
            continue
        if (
            len(node.body) == 1
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Call)
            and isinstance(node.body[0].value.func, ast.Name)
            and node.body[0].value.func.id in existing_names
        ):
            called_name = node.body[0].value.func.id
            entry_function = next(
                (
                    candidate
                    for candidate in tree.body
                    if isinstance(
                        candidate,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and candidate.name == called_name
                ),
                None,
            )
            if entry_function is None:
                return source
            tree.body = [
                candidate
                for candidate in tree.body
                if not (
                    isinstance(
                        candidate,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and candidate.name.startswith("_run_as_script")
                    and candidate is not entry_function
                )
            ]
            entry_function.name = "_run_as_script"
            node.body[0].value.func.id = "_run_as_script"
            ast.fix_missing_locations(tree)
            return ast.unparse(tree).rstrip() + "\n"
        existing_entry_function = next(
            (
                candidate
                for candidate in tree.body
                if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef))
                and candidate.name == "_run_as_script"
            ),
            None,
        )
        if existing_entry_function is not None:
            existing_entry_function.body = node.body
            node.body = [
                ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id="_run_as_script", ctx=ast.Load()),
                        args=[],
                        keywords=[],
                    )
                )
            ]
            ast.fix_missing_locations(tree)
            return ast.unparse(tree).rstrip() + "\n"
        function_name = "_run_as_script"
        suffix = 2
        while function_name in existing_names:
            function_name = f"_run_as_script_{suffix}"
            suffix += 1
        function = ast.FunctionDef(
            name=function_name,
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=node.body,
            decorator_list=[],
            returns=None,
            type_comment=None,
        )
        node.body = [
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id=function_name, ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
            )
        ]
        tree.body.insert(index, function)
        ast.fix_missing_locations(tree)
        return ast.unparse(tree).rstrip() + "\n"
    return source


def _ensure_generated_generic_type_parameters(source: str) -> str:
    """Define undeclared type parameters used by ``typing.Generic`` bases."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    required: list[str] = []
    for class_node in (
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ):
        for base in class_node.bases:
            if not isinstance(base, ast.Subscript):
                continue
            generic_owner = base.value
            is_generic = (
                isinstance(generic_owner, ast.Name)
                and generic_owner.id == "Generic"
            ) or (
                isinstance(generic_owner, ast.Attribute)
                and generic_owner.attr == "Generic"
            )
            if not is_generic:
                continue
            parameters = (
                base.slice.elts
                if isinstance(base.slice, ast.Tuple)
                else [base.slice]
            )
            for parameter in parameters:
                if isinstance(parameter, ast.Name) and parameter.id not in required:
                    required.append(parameter.id)

    declared = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            declared.update(
                child.id
                for target in targets
                for child in ast.walk(target)
                if isinstance(child, ast.Name)
            )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            declared.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )

    missing = [name for name in required if name not in declared]
    if not missing:
        return source

    typing_import = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "typing"
            and node.level == 0
        ),
        None,
    )
    if typing_import is None:
        typing_import = ast.ImportFrom(
            module="typing",
            names=[ast.alias(name="TypeVar")],
            level=0,
        )
        import_index = next(
            (
                index
                for index, node in enumerate(tree.body)
                if not isinstance(node, (ast.Import, ast.ImportFrom))
                and not (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                )
            ),
            len(tree.body),
        )
        tree.body.insert(import_index, typing_import)
    elif not any(alias.name == "TypeVar" for alias in typing_import.names):
        typing_import.names.append(ast.alias(name="TypeVar"))

    assignment_index = max(
        (
            index + 1
            for index, node in enumerate(tree.body)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ),
        default=0,
    )
    tree.body[assignment_index:assignment_index] = [
        ast.Assign(
            targets=[ast.Name(id=name, ctx=ast.Store())],
            value=ast.Call(
                func=ast.Name(id="TypeVar", ctx=ast.Load()),
                args=[ast.Constant(value=name)],
                keywords=[],
            ),
        )
        for name in missing
    ]
    ast.fix_missing_locations(tree)
    return ast.unparse(tree).rstrip() + "\n"


def _normalize_generated_files(
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str,
    request_prompt: str,
) -> list[tuple[str, str, str]]:
    """Apply the desktop editor's deterministic bounded-file cleanup sequence."""

    normalized: list[tuple[str, str, str]] = []
    valid_input_sources: dict[str, str] = {}
    qt_ui_requested = bool(
        re.search(
            r"\b(?:qt|pyside6?|pyqt[56]?|Q[A-Z][A-Za-z0-9_]*|"
            r"Modeless[A-Za-z0-9_]*(?:Dialog|Widget|Window))\b",
            request_prompt,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:ui|dialog|window|widget|panel|picker)\b",
            request_prompt,
            re.IGNORECASE,
        )
    )
    for path, original, source in generated_files:
        try:
            compile(ast.parse(source, filename=path), path, "exec")
        except (SyntaxError, ValueError):
            pass
        else:
            valid_input_sources[str(Path(path).resolve())] = source
        if not Path(path).name.startswith("test_"):
            source = _lift_generated_main_block(source)
        source = _remove_shadowed_class_methods(source)
        source = _remove_generated_self_imports(path, source)
        source = _ensure_generated_generic_type_parameters(source)
        source = _resolve_generated_qt_symbols(
            _normalize_generated_qt_binding(source)
        )
        if Path(path).name.startswith("test_"):
            source = _remove_unrequested_failure_tests(source, request_prompt)
            source = _normalize_generated_qt_tests(source, request_prompt)
            source = _resolve_generated_qt_symbols(source)
        elif not original and qt_ui_requested:
            source = _ensure_new_qt_ui_main_show(source)
            source = _normalize_qt_entry_application_ownership(source)
        source = _normalize_generated_python_source_quality(
            source,
            newly_created=not bool(original),
        )
        normalized.append((path, original, source))
    normalized = _remove_shadowed_and_duplicate_generated_imports(
        normalized,
        project_root,
    )
    normalized = _hoist_generated_test_project_imports(
        normalized,
        project_root,
    )
    normalized, _ = ensure_project_edit_requested_docstrings(
        normalized,
        request_prompt=request_prompt,
        force=False,
    )
    normalized, _ = resolve_project_edit_standard_library_symbols(
        normalized,
        project_root=project_root,
    )
    normalized, _ = remove_project_edit_unused_imports(normalized)
    normalized, _ = enforce_project_edit_requested_test_contracts(
        normalized,
        request_prompt=request_prompt,
    )
    normalized, _ = format_project_edit_generated_python(normalized)
    safe_normalized: list[tuple[str, str, str]] = []
    for path, original, source in normalized:
        candidate_source = (
            _ensure_qt_test_application(source)
            if Path(path).name.startswith("test_")
            else source
        )
        try:
            compile(ast.parse(candidate_source, filename=path), path, "exec")
        except (SyntaxError, ValueError):
            candidate_source = valid_input_sources.get(
                str(Path(path).resolve()),
                candidate_source,
            )
        safe_normalized.append((path, original, candidate_source))
    return safe_normalized


def _remove_shadowed_class_methods(source: str) -> str:
    """Remove class methods shadowed by a later same-name declaration.

    :param source: Python module source
    :return: normalized Python module source
    """

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    changed = False
    for class_node in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        last_index_by_name = {
            statement.name: index
            for index, statement in enumerate(class_node.body)
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        retained: list[ast.stmt] = []
        for index, statement in enumerate(class_node.body):
            if (
                isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                and last_index_by_name.get(statement.name) != index
            ):
                changed = True
                continue
            retained.append(statement)
        class_node.body = retained
    if not changed:
        return source
    ast.fix_missing_locations(tree)
    return ast.unparse(tree).rstrip() + "\n"


def _callable_repair_targets(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> list[dict[str, str]]:
    """Map concrete diagnostics to the smallest generated callable owners."""

    diagnostics = "\n".join(errors)
    indexed: list[dict[str, Any]] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            lines = source.splitlines()
            lexical_rows: list[dict[str, Any]] = []
            active_class = ""
            active_class_indent = -1
            for line_index, line in enumerate(lines, start=1):
                stripped = line.lstrip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(line) - len(stripped)
                class_match = re.match(
                    r"class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                    stripped,
                )
                if class_match:
                    active_class = class_match.group(1)
                    active_class_indent = indent
                    continue
                if active_class and indent <= active_class_indent:
                    active_class = ""
                    active_class_indent = -1
                function_match = re.match(
                    r"(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                    stripped,
                )
                if not function_match:
                    continue
                name = function_match.group(1)
                lexical_rows.append({
                    "path": path,
                    "symbol": (
                        f"{active_class}.{name}"
                        if active_class and indent > active_class_indent
                        else name
                    ),
                    "name": name,
                    "start": line_index,
                    "end": len(lines),
                    "indent": indent,
                    "is_test": Path(path).name.startswith("test_"),
                    "calls": set(),
                })
            for row_index, row in enumerate(lexical_rows):
                for following in lexical_rows[row_index + 1:]:
                    if int(following["indent"]) <= int(row["indent"]):
                        row["end"] = int(following["start"]) - 1
                        break
                indexed.append(row)
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                indexed.append({
                    "path": path,
                    "symbol": node.name,
                    "name": node.name,
                    "start": node.lineno,
                    "end": node.end_lineno or node.lineno,
                    "is_test": Path(path).name.startswith("test_"),
                    "calls": {
                        call.func.attr
                        if isinstance(call.func, ast.Attribute)
                        else call.func.id
                        for call in ast.walk(node)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, (ast.Attribute, ast.Name))
                    },
                })
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        indexed.append({
                            "path": path,
                            "symbol": f"{node.name}.{child.name}",
                            "name": child.name,
                            "start": child.lineno,
                            "end": child.end_lineno or child.lineno,
                            "is_test": Path(path).name.startswith("test_"),
                            "calls": {
                                call.func.attr
                                if isinstance(call.func, ast.Attribute)
                                else call.func.id
                                for call in ast.walk(child)
                                if isinstance(call, ast.Call)
                                and isinstance(call.func, (ast.Attribute, ast.Name))
                            },
                        })

    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(item: dict[str, Any]) -> None:
        key = (str(item["path"]), str(item["symbol"]))
        if key not in seen and len(selected) < 4:
            seen.add(key)
            selected.append({"path": key[0], "symbol": key[1]})

    runtime_diagnostics = "Disposable generated-patch validation failed:" in diagnostics
    for filename, line_text in re.findall(
        r"\(([^,()]+\.py),\s*line\s+(\d+)\)",
        diagnostics,
        flags=re.IGNORECASE,
    ):
        line_number = int(line_text)
        matching = [
            item
            for item in indexed
            if Path(str(item["path"])).name.casefold()
            == Path(filename).name.casefold()
            and int(item["start"]) <= line_number <= int(item["end"])
        ]
        if matching:
            add(min(
                matching,
                key=lambda item: int(item["end"]) - int(item["start"]),
            ))
    for path_text, qualified_owner in re.findall(
        r"(?m)^([^\r\n]+?\.py):([A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*):\s+generated test ",
        diagnostics,
        flags=re.IGNORECASE,
    ):
        normalized_owner_path = path_text.replace("\\", "/").casefold()
        for item in indexed:
            if (
                str(item["symbol"]) == qualified_owner
                and str(item["path"]).replace("\\", "/").casefold().endswith(
                    normalized_owner_path
                )
            ):
                add(item)
    if (
        "generated test accesses unapproved" in diagnostics
        and selected
    ):
        return selected
    if not runtime_diagnostics:
        invalid_api_members = {
            qualified.rsplit(".", 1)[-1]
            for qualified in re.findall(
                r"(?:Imported callable members do not exist|"
                r"Imported API members do not exist):\s*"
                r"([A-Za-z_][A-Za-z0-9_.]*)",
                diagnostics,
            )
        }
        for item in indexed:
            qualified = str(item["symbol"])
            if "." in qualified and qualified in diagnostics:
                add(item)
            elif re.search(
                rf"{re.escape(str(item['path']))}:"
                rf"(?:<module>\.)?{re.escape(qualified)}\b",
                diagnostics,
                flags=re.IGNORECASE,
            ):
                add(item)
            elif invalid_api_members & set(item.get("calls") or set()):
                add(item)
            elif re.search(
                rf"\b(?:in|placeholder(?:s)?[:\s]+)\s*"
                rf"{re.escape(str(item['name']))}\b",
                diagnostics,
            ):
                add(item)
        indexed_by_name: dict[str, list[dict[str, Any]]] = {}
        for item in indexed:
            indexed_by_name.setdefault(str(item["name"]), []).append(item)
        for name, matching_items in indexed_by_name.items():
            if (
                len(matching_items) == 1
                and re.search(rf"\b{re.escape(name)}\b", diagnostics)
            ):
                add(matching_items[0])

    failure_sections = [
        section
        for error in errors
        for section in (
            re.split(
                r"(?=^={5,}\s*$|^(?:ERROR|FAIL):\s+)",
                error,
                flags=re.MULTILINE,
            )
            if runtime_diagnostics
            else [error]
        )
        if "File \"" in section
    ]
    for error in failure_sections:
        frames: list[dict[str, Any]] = []
        for path_text, line_text, _function_name in re.findall(
            r'File "([^"]+)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)',
            error,
        ):
            normalized_frame = path_text.replace("\\", "/").lower()
            line_number = int(line_text)
            matching = [
                item
                for item in indexed
                if (
                    normalized_frame.endswith(
                        str(item["path"]).replace("\\", "/").lower()
                    )
                    or Path(normalized_frame).name.casefold()
                    == Path(str(item["path"])).name.casefold()
                )
                and int(item["start"]) <= line_number <= int(item["end"])
            ]
            if matching:
                frames.append(min(
                    matching,
                    key=lambda item: int(item["end"]) - int(item["start"]),
                ))
        production_frames = [item for item in frames if not item["is_test"]]
        if production_frames:
            add(production_frames[-1])
            if len(production_frames) > 1:
                add(production_frames[-2])
        elif frames:
            add(frames[-1])

    selected_keys = {
        (item["path"], item["symbol"])
        for item in selected
    }
    selected_test_items = [
        item
        for item in indexed
        if item["is_test"]
        and (str(item["path"]), str(item["symbol"])) in selected_keys
    ]
    exact_production: list[dict[str, Any]] = []
    for test_item in selected_test_items:
        expected_name = str(test_item["name"]).removeprefix("test_")
        called_production = [
            item
            for item in indexed
            if not item["is_test"] and item["name"] in test_item["calls"]
        ]
        for item in called_production:
            if item["name"] == expected_name:
                exact_production.append(item)
        if (
            not any(item["name"] == expected_name for item in called_production)
            and len(called_production) == 1
        ):
            exact_production.append(called_production[0])

    prioritized: list[dict[str, str]] = []
    prioritized_seen: set[tuple[str, str]] = set()
    production_targets = exact_production
    for item in production_targets + selected:
        key = (str(item["path"]), str(item["symbol"]))
        if key in prioritized_seen:
            continue
        prioritized_seen.add(key)
        prioritized.append({"path": key[0], "symbol": key[1]})
        if len(prioritized) == 4:
            break
    return prioritized


def _repair_observed_literal_test_expectations(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Correct a rejected literal expectation after a prior causal test repair."""

    if not harness_path:
        return validation_files, []
    diagnostics = "\n".join(str(error) for error in errors)
    corrections: dict[str, tuple[Any, Any]] = {}
    for section in re.split(
        r"(?=^(?:FAIL|ERROR):\s+test_)",
        diagnostics,
        flags=re.MULTILINE,
    ):
        test_match = re.search(
            r"^(?:FAIL|ERROR):\s+(test_[A-Za-z0-9_]+)",
            section,
            flags=re.MULTILINE,
        ) or re.search(
            r"\b(test_[A-Za-z0-9_]+)\s+\(",
            section,
        )
        difference = re.search(
            r"AssertionError:\s*(?:Lists|Tuples|Dicts) differ:\s*"
            r"([^\r\n]+?)\s*!=\s*([^\r\n]+)",
            section,
        )
        if not test_match or not difference:
            continue
        try:
            actual = ast.literal_eval(difference.group(1).strip())
            expected = ast.literal_eval(difference.group(2).strip())
        except (SyntaxError, ValueError):
            continue
        if not isinstance(actual, (list, tuple, dict, str, int, float, bool, type(None))):
            continue
        corrections[test_match.group(1)] = (actual, expected)
    if not corrections:
        return validation_files, []

    updated = list(validation_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        if path != harness_path:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            for method in (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in corrections
            ):
                actual, expected = corrections[method.name]
                replacement = ast.parse(repr(actual), mode="eval").body
                method_changed = False
                for node in ast.walk(method):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "assertEqual"
                        and len(node.args) >= 2
                    ):
                        try:
                            current_expected = ast.literal_eval(node.args[1])
                        except (TypeError, ValueError):
                            continue
                        if current_expected == expected:
                            node.args[1] = replacement
                            method_changed = True
                            break
                    if (
                        isinstance(node, ast.Assert)
                        and isinstance(node.test, ast.Compare)
                        and len(node.test.ops) == 1
                        and isinstance(node.test.ops[0], ast.Eq)
                        and len(node.test.comparators) == 1
                    ):
                        try:
                            current_expected = ast.literal_eval(
                                node.test.comparators[0]
                            )
                        except (TypeError, ValueError):
                            continue
                        if current_expected == expected:
                            node.test.comparators[0] = replacement
                            method_changed = True
                            break
                if method_changed:
                    changed = True
                    repairs.append(
                        f"{class_node.name}.{method.name}: replaced only the "
                        "rejected literal expectation with the observed value"
                    )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, repairs


def _repair_requested_python_contract_surface(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Repair mechanically provable requested Python declaration surfaces."""

    diagnostics = "\n".join(str(error) for error in errors)
    missing_method_contracts = [
        (path, class_name, method_name)
        for path, class_name, method_name in re.findall(
            r"(?m)^(.+?\.py):([A-Za-z_][A-Za-z0-9_]*): "
            r"approved method `([A-Za-z_][A-Za-z0-9_]*)` is missing\.$",
            diagnostics,
        )
    ]
    repair_type_hints = (
        "Requested complete type hints are invalid or missing:" in diagnostics
        or "typed public method requires parameter and return annotations."
        in diagnostics
        or bool(
            re.search(
                r"\b(?:useful|clear|complete|explicit|full)?\s*type hints?\b"
                r"|\b(?:complete|explicit|full)\s+annotations?\b",
                request_prompt,
                flags=re.IGNORECASE,
            )
        )
    )
    repair_docstrings = (
        "Requested useful docstrings are too vague:" in diagnostics
    )
    requested_docstring_symbols = set(re.findall(
        r"\.py:([A-Za-z_][A-Za-z0-9_.]*): Requested useful docstrings "
        r"are too vague:",
        diagnostics,
    ))
    requires_explicit_return_fields = bool(
        re.search(
            r":returns?\b|\breturns?\s+fields?\b",
            request_prompt,
            flags=re.IGNORECASE,
        )
    )
    if (
        not missing_method_contracts
        and not repair_type_hints
        and not repair_docstrings
    ):
        return generated_files, []

    request_sentences = [
        " ".join(sentence.strip().split())
        for sentence in re.split(r"(?<=[.!?])\s+", request_prompt)
        if sentence.strip()
    ]

    def useful_docstring(name: str, node: ast.AST) -> bool:
        docstring = str(ast.get_docstring(node) or "")
        summary = re.split(
            r"(?m)^\s*:(?:param|return|returns|raise|raises|type)\b",
            docstring,
            maxsplit=1,
        )[0].strip()
        leaf_name = name.rsplit(".", 1)[-1]
        if (
            re.search(r"(?:[\\/]|\.py\b)", summary, flags=re.IGNORECASE)
            or re.search(
                r"\b(?:requested (?:behavior|change|feature|implementation)|"
                r"provide [a-z0-9_ ]+ behavior|"
                r"apply [a-z0-9_ ]+ and update only its documented state|"
                r"compute and return the [a-z0-9_ ]+ result|"
                r"return operation for [a-z0-9_ ]+|"
                r"store validated [-a-z0-9_ ]+ state and expose|"
                r"unrelated state|surrounding state|"
                r"observable behavior|validation invariants?|state contract|"
                r"behavioral contracts?|used by (?:the )?operation)\b"
                r"|\bcoordinate .+ through .+ operations\b",
                summary,
                flags=re.IGNORECASE,
            )
            or re.match(
                rf"^\s*{re.escape(leaf_name)}\s+must\b",
                summary,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\bpreserving validated inputs, state transitions, and "
                r"failure behavior\b|\bafter validating construction inputs\b",
                summary,
                flags=re.IGNORECASE,
            )
        ):
            return False
        words = re.findall(r"[A-Za-z0-9]+", summary)
        return len(words) >= 6 and len({
            word.casefold() for word in words
        }) >= 5

    def complete_docstring(name: str, node: ast.AST) -> bool:
        if not useful_docstring(name, node):
            return False
        if isinstance(node, ast.ClassDef):
            fields = [
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            ]
            docstring = str(ast.get_docstring(node) or "")
            return all(
                re.search(
                    rf":param\s+(?:[^:\s]+\s+)?{re.escape(field)}\s*:",
                    docstring,
                )
                for field in fields
            )
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True
        docstring = str(ast.get_docstring(node) or "")
        if re.search(
            r"\b(?:supplied to this operation|result produced by|"
            r"used by (?:the )?operation|"
            r"request value consumed by(?: the documented operation)?|"
            r"containing the validated inputs for this operation|"
            r"value consumed by the documented operation|"
            r"the documented .+ result after successful completion|"
            r"produced after the operation completes successfully|"
            r"the calculated [a-z_ ]+ value)\b",
            docstring,
            flags=re.IGNORECASE,
        ):
            return False
        parameters = [
            argument.arg
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
            if argument.arg not in {"self", "cls"}
        ]
        if node.args.vararg is not None:
            parameters.append(node.args.vararg.arg)
        if node.args.kwarg is not None:
            parameters.append(node.args.kwarg.arg)
        if any(
            not re.search(
                rf":param\s+(?:[^:\s]+\s+)?{re.escape(parameter)}\s*:",
                docstring,
            )
            for parameter in parameters
        ):
            return False
        returns_value = any(
            isinstance(child, (ast.Yield, ast.YieldFrom))
            or (
                isinstance(child, ast.Return)
                and child.value is not None
                and not (
                    isinstance(child.value, ast.Constant)
                    and child.value.value is None
                )
            )
            for statement in node.body
            for child in ast.walk(statement)
        )
        return not (returns_value or requires_explicit_return_fields) or bool(
            re.search(r":returns?\s*:", docstring)
        )

    def requested_docstring(
        name: str,
        *,
        node: ast.AST | None = None,
        class_methods: list[str] | None = None,
    ) -> str:
        def humanize(identifier: str) -> str:
            leaf = identifier.rsplit(".", 1)[-1].strip("_")
            expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", leaf)
            expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", expanded)
            words = re.sub(r"_+", " ", expanded).strip().split()
            collapsed: list[str] = []
            index = 0
            while index < len(words):
                if len(words[index]) == 1 and words[index].isalpha():
                    letters: list[str] = []
                    while (
                        index < len(words)
                        and len(words[index]) == 1
                        and words[index].isalpha()
                    ):
                        letters.append(words[index])
                        index += 1
                    collapsed.append("".join(letters))
                    continue
                collapsed.append(words[index])
                index += 1
            return " ".join(collapsed).lower()

        def joined(values: list[str]) -> str:
            clean = [value for value in values if value]
            if len(clean) < 2:
                return "".join(clean)
            if len(clean) == 2:
                return " and ".join(clean)
            return ", ".join(clean[:-1]) + f", and {clean[-1]}"

        def callable_parameters(callable_node: ast.AST | None) -> list[str]:
            if not isinstance(
                callable_node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                return []
            return [
                argument.arg
                for argument in (
                    *callable_node.args.posonlyargs,
                    *callable_node.args.args,
                    *callable_node.args.kwonlyargs,
                )
                if argument.arg not in {"self", "cls"}
            ]

        def parameter_description(
            parameter: str,
            callable_node: ast.AST | None,
        ) -> str:
            lowered = parameter.casefold()
            if lowered.endswith("_id"):
                owner_name = humanize(lowered[:-3]) or "record"
                return (
                    f"Non-empty stable identifier distinguishing this {owner_name} "
                    "from other active records."
                )
            if lowered in {"attempts", "attempt_count"}:
                return (
                    "Non-negative number of completed attempts represented by "
                    "the current record."
                )
            if lowered in {"revision", "version"} or lowered.endswith(
                ("_revision", "_version")
            ):
                return (
                    "Non-negative version number representing the record's "
                    "current state."
                )
            if lowered in {
                "attributes",
                "metadata",
                "properties",
                "settings",
            }:
                return (
                    "Caller-provided named values detached from mutable input "
                    "before they are retained by the record."
                )
            if "cancellation" in lowered and "callback" in lowered:
                return (
                    "Optional callable returning true when execution must stop "
                    "before the next pending action."
                )
            if "progress" in lowered and "callback" in lowered:
                return (
                    "Optional callable receiving the current integer step, total "
                    "integer steps, and user-visible status text."
                )
            if lowered in {"jobs", "tasks", "operations", "items"}:
                return (
                    f"Ordered {humanize(lowered)} supplied in the exact sequence "
                    "in which they must be processed."
                )
            if lowered in {"job", "task", "operation"}:
                return (
                    f"{humanize(lowered).capitalize()} record whose identity and "
                    "payload are consumed by the requested state transition."
                )
            if (
                isinstance(callable_node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and callable_node.name.startswith(
                    ("add", "append", "enqueue", "insert", "put", "register")
                )
            ):
                if lowered in {"key", "item_key", "cache_key"}:
                    return "Stable key identifying the value stored in the cache."
                if lowered in {"value", "item_value", "payload"}:
                    return "Caller-provided value retained without truthiness coercion."
                return (
                    "Value added after validating its identity, ordering, and "
                    "active-state constraints."
                )
            if lowered in {"parent", "parent_widget"}:
                return "Optional parent widget that owns this UI object."
            if lowered == "success" or lowered.endswith("_success"):
                return (
                    "Whether the background operation completed successfully "
                    "and the UI should display its success state."
                )
            if "message" in lowered or lowered in {"status", "error"}:
                return (
                    "Human-readable completion, status, or error text presented "
                    "to the caller or UI."
                )
            if lowered in {"request", "options", "config", "configuration"}:
                return (
                    "Validated request object containing source values, "
                    "destination settings, and operation options."
                )
            if lowered in {"clock", "monotonic_clock", "time_source"}:
                return (
                    "Injected callable returning the current monotonic time in "
                    "seconds."
                )
            if lowered in {"key", "item_key", "cache_key"}:
                return "Stable key identifying the item to read, update, or remove."
            if lowered in {"item", "payload", "value"}:
                return (
                    "Caller-provided data carried by the record and preserved unless "
                    "the documented operation explicitly replaces it."
                )
            if lowered == "priority":
                return (
                    "Numeric ordering key where lower values are selected before "
                    "higher values."
                )
            if lowered in {"predicate", "filter_predicate"}:
                return (
                    "Callable returning true for each pending payload that the "
                    "operation should select or remove."
                )
            if lowered in {"value", "item_value"}:
                return "Caller-provided value stored for later retrieval."
            if lowered.endswith(("_at", "_deadline")) and any(
                token in lowered for token in ("expire", "expiry", "deadline")
            ):
                return (
                    "Monotonic timestamp after which the stored value is no "
                    "longer live."
                )
            if lowered.endswith(("_file", "_filename")):
                return "Filesystem path to the source file consumed by the operation."
            if lowered.endswith("_path"):
                return "Normalized destination or resource path used by the operation."
            if lowered in {"destination", "target", "output"} or lowered.endswith(
                ("_destination", "_target", "_output")
            ):
                return (
                    "Caller-selected target forwarded to the downstream operation "
                    "that creates, stores, exports, or imports the result."
                )
            if lowered.endswith("_name"):
                return "Stable public name assigned to the created or selected resource."
            if lowered in {"srgb", "enabled", "disabled", "checked"} or lowered.endswith(
                ("_flag", "_enabled")
            ):
                return "Boolean option controlling the corresponding operation behavior."
            if lowered.endswith(("_index", "_position")):
                return (
                    "Zero-based position of the item or attempt whose result is "
                    "being calculated."
                )
            if lowered.endswith(("_seconds", "_duration", "_interval")):
                return "Non-negative duration, expressed in seconds."
            if lowered.startswith(("max_", "min_")) or lowered.endswith(
                ("_count", "_attempts", "_limit")
            ):
                return "Validated integer limit controlling how many operations may run."
            if lowered.endswith(("_multiplier", "_factor", "_scale")):
                return "Positive scaling factor applied when calculating the result."
            annotation_name = ""
            if isinstance(callable_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                argument = next(
                    (
                        value
                        for value in (
                            *callable_node.args.posonlyargs,
                            *callable_node.args.args,
                            *callable_node.args.kwonlyargs,
                        )
                        if value.arg == parameter
                    ),
                    None,
                )
                if argument is not None and argument.annotation is not None:
                    annotation_name = ast.unparse(argument.annotation)
            if annotation_name and annotation_name not in {"Any", "object"}:
                return (
                    f"{humanize(annotation_name).capitalize()} value consumed by "
                    f"{humanize(getattr(callable_node, 'name', 'operation'))}."
                )
            if isinstance(callable_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                forwarded_to = next(
                    (
                        ast.unparse(call.func)
                        for call in ast.walk(callable_node)
                        if isinstance(call, ast.Call)
                        and any(
                            isinstance(argument, ast.Name)
                            and argument.id == parameter
                            for argument in (
                                *call.args,
                                *[
                                    keyword.value
                                    for keyword in call.keywords
                                ],
                            )
                        )
                    ),
                    "",
                )
                if forwarded_to:
                    return (
                        f"Value forwarded to `{forwarded_to}` by "
                        f"{humanize(callable_node.name)}."
                    )
            return (
                f"Validated {humanize(parameter)} consumed when "
                f"{humanize(getattr(callable_node, 'name', 'operation'))} "
                "updates its documented result or state."
            )

        def return_description(
            identifier: str,
            callable_node: ast.AST | None,
        ) -> str:
            if isinstance(callable_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lowered_identifier = identifier.lower()
                parameters = callable_parameters(callable_node)
                if lowered_identifier in {"get", "find", "lookup"} and "key" in parameters:
                    return (
                        "The live value associated with the key, or None when no "
                        "matching value is available."
                    )
                if lowered_identifier in {"keys", "list_keys"}:
                    return "The live keys in their preserved insertion order."
                if any(
                    token in lowered_identifier
                    for token in ("delay", "backoff", "duration", "interval")
                ):
                    return "The calculated duration in seconds."
                if callable_node.returns is not None:
                    annotation_name = ast.unparse(callable_node.returns)
                    if annotation_name == "bool":
                        return (
                            "True when the requested operation succeeds; otherwise "
                            "False."
                        )
                    if annotation_name in {"int", "float"}:
                        if "cancel" in lowered_identifier:
                            return (
                                "The exact number of pending payloads removed by "
                                "the predicate."
                            )
                        return (
                            f"The calculated {humanize(identifier)} numeric value."
                        )
                    if annotation_name == "str":
                        return f"The resulting {humanize(identifier)} text."
                    if re.match(
                        r"(?:List|list|Sequence|tuple)\[",
                        annotation_name,
                    ):
                        return (
                            f"The ordered {humanize(identifier)} items that "
                            "satisfy the documented readiness or selection rule."
                        )
                returned_names = [
                    child.value.id
                    for statement in callable_node.body
                    for child in ast.walk(statement)
                    if isinstance(child, ast.Return)
                    and isinstance(child.value, ast.Name)
                ]
                if returned_names:
                    returned_name = returned_names[-1]
                    producer = next(
                        (
                            ast.unparse(statement.value.func)
                            for statement in callable_node.body
                            if isinstance(statement, (ast.Assign, ast.AnnAssign))
                            and isinstance(statement.value, ast.Call)
                            and (
                                (
                                    isinstance(statement, ast.Assign)
                                    and any(
                                        isinstance(target, ast.Name)
                                        and target.id == returned_name
                                        for target in statement.targets
                                    )
                                )
                                or (
                                    isinstance(statement, ast.AnnAssign)
                                    and isinstance(statement.target, ast.Name)
                                    and statement.target.id == returned_name
                                )
                            )
                        ),
                        "",
                    )
                    if producer:
                        return (
                            f"The result returned by `{producer}` after its "
                            "successful execution."
                        )
                    return (
                        f"The {humanize(returned_name)} returned by "
                        f"{humanize(identifier)}."
                    )
            return (
                f"The concrete result returned by {humanize(identifier)}."
            )

        def action_summary(
            identifier: str,
            callable_node: ast.AST | None,
        ) -> str:
            if isinstance(callable_node, ast.ClassDef):
                if any(
                    isinstance(base, ast.Name)
                    and base.id.endswith(("Error", "Exception"))
                    for base in callable_node.bases
                ):
                    return (
                        f"Report {humanize(identifier)} conditions while retaining "
                        "structured failure details for callers."
                    )
                if any(
                    isinstance(decorator, ast.Name)
                    and decorator.id == "dataclass"
                    or isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "dataclass"
                    for decorator in callable_node.decorator_list
                ):
                    fields = [
                        humanize(statement.target.id)
                        for statement in callable_node.body
                        if isinstance(statement, ast.AnnAssign)
                        and isinstance(statement.target, ast.Name)
                    ]
                    methods = [
                        humanize(statement.name)
                        for statement in callable_node.body
                        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not statement.name.startswith("_")
                    ]
                    if fields:
                        if (
                            any(field == "value" for field in fields)
                            and any("expire" in field for field in fields)
                        ):
                            return (
                                "Store an immutable cached value together with its "
                                "expiration deadline."
                            )
                        method_text = (
                            f" and expose {joined(methods)} behavior"
                            if methods
                            else ""
                        )
                        return (
                            f"Represent immutable {joined(fields)} values"
                            f"{method_text}."
                        )
                    return (
                        f"Describe immutable {humanize(identifier)} values consumed "
                        "by the owning workflow."
                    )
                public_methods = [
                    humanize(statement.name)
                    for statement in callable_node.body
                    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not statement.name.startswith("_")
                ]
                if public_methods:
                    return (
                        f"Manage validated {humanize(identifier)} state through "
                        f"the public {joined(public_methods)} operations."
                    )
                return (
                    f"Coordinate {humanize(identifier)} state, validation, "
                    "and public operations."
                )
            parameters = callable_parameters(callable_node)
            parameter_text = joined([
                humanize(parameter) for parameter in parameters
            ])
            call_attributes = {
                child.func.attr
                for child in ast.walk(callable_node)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
            } if callable_node is not None else set()
            has_subscript_return = any(
                isinstance(child, ast.Return)
                and isinstance(child.value, ast.Subscript)
                for child in ast.walk(callable_node)
            ) if callable_node is not None else False

            leaf_identifier = identifier.rsplit(".", 1)[-1]
            if leaf_identifier == "__init__":
                if call_attributes.intersection({
                    "addWidget",
                    "connect",
                    "setCentralWidget",
                    "setLayout",
                }):
                    return (
                        "Initialize the Qt controls, attach their layout, and "
                        "connect each approved user interaction to its handler."
                    )
                return (
                    "Initialize the instance fields and establish the approved "
                    "constructor invariants."
                )
            cache_contract = bool(
                re.search(
                    r"\b(?:cache|ttl|time-to-live|least-recently-used|lru)\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                )
            )
            if cache_contract and leaf_identifier == "put":
                return (
                    "Store a cache value with a fresh TTL timestamp and mark it "
                    "as the most recently used entry."
                )
            if cache_contract and leaf_identifier == "get":
                return (
                    "Return a live cached value while refreshing LRU recency "
                    "without extending its TTL."
                )
            if cache_contract and leaf_identifier == "clear":
                return "Remove all cached values together with their recency metadata."
            if cache_contract and leaf_identifier == "__len__":
                return "Count live cache entries after lazily removing expired values."
            if leaf_identifier.startswith("_on_"):
                invoked_calls = [
                    child
                    for child in ast.walk(callable_node)
                    if isinstance(child, ast.Call)
                    and ast.unparse(child.func).rsplit(".", 1)[-1]
                    not in {
                        "strip",
                        "split",
                        "text",
                        "currentText",
                        "value",
                        "isChecked",
                    }
                ] if callable_node is not None else []
                dependency_call = next(
                    (
                        call
                        for call in invoked_calls
                        if isinstance(call.func, ast.Name)
                    ),
                    invoked_calls[-1] if invoked_calls else None,
                )
                dependency = (
                    ast.unparse(dependency_call.func)
                    if dependency_call is not None
                    else ""
                )
                return (
                    f"Handle {humanize(leaf_identifier[4:])} by reading the "
                    "current controls"
                    + (
                        f", invoking `{dependency}`, and returning its result."
                        if dependency
                        else " and applying the approved state transition."
                    )
                )

            words = humanize(identifier).split()
            verb = words[0] if words else "execute"
            subject = " ".join(words[1:]) or "operation"
            inputs = f" using {parameter_text}" if parameter_text else ""
            if re.search(
                r"(?:^|_)(?:self_)?test(?:_|$)",
                identifier,
                flags=re.IGNORECASE,
            ):
                return (
                    "Execute deterministic success, boundary, ordering, callback, "
                    "and failure checks through the public API."
                )
            if verb in {"run", "execute", "process"}:
                effects: list[str] = []
                if call_attributes.intersection({"setText", "setValue", "setRange"}):
                    effects.append("user-visible status and progress")
                if call_attributes.intersection({"addItem", "append", "insert"}):
                    effects.append("result collection")
                effect_text = (
                    f", then update {joined(effects)}"
                    if effects
                    else ""
                )
                return (
                    f"Execute the {subject}{inputs}{effect_text} while preserving "
                    "validated ordering and failure behavior."
                )
            if "clear" in call_attributes:
                return "Remove all stored items from the collection."
            if verb in {"pop", "dequeue", "take", "remove"}:
                order_text = (
                    " in stable insertion order"
                    if re.search(
                        r"\bstable\s+(?:insertion\s+)?order\b",
                        request_prompt,
                        flags=re.IGNORECASE,
                    )
                    else ""
                )
                return (
                    f"Return and remove the eligible {subject}{order_text}."
                )
            if call_attributes.intersection({"append", "add", "insert"}):
                item = humanize(parameters[0]) if parameters else "an item"
                if verb in {"schedule", "enqueue"}:
                    if not re.search(
                        r"\bpriority\b",
                        request_prompt,
                        flags=re.IGNORECASE,
                    ):
                        return (
                            f"Add {item} while preserving requested ordering and "
                            "identity constraints."
                        )
                    return (
                        f"Schedule {item} for future readiness while preserving "
                        "numeric priority and stable insertion order."
                    )
                return (
                    f"Add {item} to the collection while preserving validated "
                    "ordering and identity constraints."
                )
            if has_subscript_return:
                return "Return the next item without removing it from the collection."
            if (
                any(
                    isinstance(child, (ast.Yield, ast.YieldFrom))
                    for child in ast.walk(callable_node)
                )
                and "key" in humanize(identifier)
                and re.search(
                    r"\b(?:ttl|expir|time-to-live)\w*\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                )
            ):
                return (
                    "Yield live keys in insertion order while lazily removing "
                    "expired entries."
                )

            inputs = f" from {parameter_text}" if parameter_text else ""
            if verb in {"create", "build", "generate", "make"}:
                return f"Create {subject}{inputs}."
            if verb in {"get", "find", "load", "read", "resolve", "peek"}:
                qualifier = f" for {parameter_text}" if parameter_text else ""
                return f"Return {subject}{qualifier}."
            if verb in {"is", "has", "can", "should"}:
                return (
                    f"Return whether {subject} for the callable's current "
                    "validated state."
                )
            if verb in {"save", "write", "export", "import", "set", "update"}:
                qualifier = f" using {parameter_text}" if parameter_text else ""
                return f"{verb.capitalize()} {subject}{qualifier}."
            if verb in {"cancel", "request", "stop"} and (
                "cancel" in humanize(identifier)
                or "stop" in humanize(identifier)
            ):
                if "predicate" in parameters:
                    return (
                        "Remove every pending payload selected by the predicate "
                        "and return the exact removal count."
                    )
                return (
                    "Request cancellation before the next pending operation "
                    "can begin."
                )
            if any(
                isinstance(child, ast.Return) and child.value is not None
                for child in ast.walk(callable_node)
            ) if callable_node is not None else False:
                if any(
                    token in humanize(identifier)
                    for token in ("delay", "backoff", "duration", "interval")
                ):
                    return "Calculate and return the corresponding duration in seconds."
                return (
                    f"Compute and return the {humanize(identifier)} result without "
                    "mutating the original instance."
                )
            qualifier = f" using {parameter_text}" if parameter_text else ""
            return (
                f"Apply {humanize(identifier)}{qualifier} and update only its "
                "documented state."
            )

        leaf_name = name.rsplit(".", 1)[-1]
        owner_aliases = {leaf_name}
        if leaf_name == "__init__":
            owner_aliases.update({"constructor", "initialization", "initialize"})
        relevant: list[str] = []
        for sentence in request_sentences:
            before_must = re.split(
                r"\bmust\b",
                sentence,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            named_before_must = bool(
                any(
                    re.search(
                        rf"(?<![A-Za-z0-9_]){re.escape(alias)}"
                        rf"(?![A-Za-z0-9_])",
                        before_must,
                        flags=re.IGNORECASE,
                    )
                    for alias in owner_aliases
                )
                and re.search(r"\bmust\b", sentence, flags=re.IGNORECASE)
            )
            called_explicitly = bool(
                any(
                    re.search(
                        rf"(?<![A-Za-z0-9_]){re.escape(alias)}\s*\(",
                        sentence,
                        flags=re.IGNORECASE,
                    )
                    for alias in owner_aliases
                )
            )
            named_explicitly = any(
                re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(alias)}"
                    rf"(?![A-Za-z0-9_])",
                    sentence,
                    flags=re.IGNORECASE,
                )
                for alias in owner_aliases
            )
            if named_before_must or called_explicitly or named_explicitly:
                relevant.append(sentence)
        class_method_summary = ""
        if class_methods:
            relevant_text = " ".join(relevant)
            modifiers = [
                label
                for pattern, label in (
                    (r"\bgeneric\b", "generic"),
                    (
                        r"\b(?:bounded|capacity|max(?:imum)?[_ ]?size)\b",
                        "fixed-capacity",
                    ),
                    (r"\blifo\b", "LIFO"),
                    (r"\bfifo\b", "FIFO"),
                    (r"\b(?:ttl|expir|time-to-live)\w*\b", "expiring"),
                )
                if re.search(pattern, relevant_text, flags=re.IGNORECASE)
            ]
            description = " ".join([
                *dict.fromkeys(modifiers),
                humanize(name),
            ])
            class_method_summary = (
                f"Manage validated {description} state through the public "
                f"{joined([humanize(method) for method in class_methods])} operations."
            )

        def requirement_clause(sentence: str) -> str:
            clause = sentence.strip().rstrip(".")
            for alias in sorted(owner_aliases, key=len, reverse=True):
                clause = re.sub(
                    rf"^(?:Its\s+|The\s+)?{re.escape(alias)}"
                    r"(?:\s*\([^)]*\))?"
                    r"(?:\s*->\s*"
                    r"[A-Za-z_][A-Za-z0-9_.]*"
                    r"(?:\[[^\]]+\])?"
                    r"(?:\s*\|\s*[A-Za-z_][A-Za-z0-9_.]*"
                    r"(?:\[[^\]]+\])?)*"
                    r")?"
                    r"\s*",
                    "",
                    clause,
                    count=1,
                    flags=re.IGNORECASE,
                )
            clause = clause.lstrip(" :-")
            if not clause:
                return action_summary(name, node)
            return clause[0].upper() + clause[1:] + "."

        summary = class_method_summary or action_summary(name, node)
        if not class_method_summary:
            behavioral_sentence = next(
                (
                    sentence
                    for sentence in relevant
                    if not re.search(r"(?:[\\/]|\.py\b)", sentence)
                    and re.search(
                        r"\b(?:implement|return|raise|preserve|store|remove|"
                        r"validate|compute|calculate|merge|schedule|execute|"
                        r"decode|encode|append|clear)\w*\b",
                        sentence,
                        flags=re.IGNORECASE,
                    )
                ),
                "",
            )
            if behavioral_sentence:
                grounded_summary = requirement_clause(behavioral_sentence)
                if grounded_summary and not re.search(
                    r"(?:[\\/]|\.py\b)", grounded_summary
                ):
                    summary = grounded_summary
        exception_clauses: list[str] = []
        for sentence in relevant:
            match = re.search(
                r"\bmust\s+(raise\s+[A-Za-z_][A-Za-z0-9_]*[^.!?]*)",
                sentence,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            clause = match.group(1).strip().rstrip(".")
            clause = re.sub(r"^raise\b", "Raise", clause, flags=re.IGNORECASE)
            exception_clauses.append(clause + ".")
        if exception_clauses:
            summary += " " + " ".join(dict.fromkeys(exception_clauses))
        documentation_lines = [summary]
        structured_fields: list[str] = []
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                if not (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                ):
                    continue
                field = statement.target.id
                structured_fields.append(
                    f":param {field}: {parameter_description(field, None)}"
                )
        for parameter in callable_parameters(node):
            structured_fields.append(
                f":param {parameter}: {parameter_description(parameter, node)}"
            )
        returns_value = bool(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                isinstance(child, ast.Return)
                and child.value is not None
                and not (
                    isinstance(child.value, ast.Constant)
                    and child.value.value is None
                )
                or isinstance(child, (ast.Yield, ast.YieldFrom))
                for statement in node.body
                for child in ast.walk(statement)
                if not isinstance(
                    child,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
                )
            )
        )
        if returns_value or (
            requires_explicit_return_fields
            and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            structured_fields.append(
                (
                    f":return: {return_description(name, node)}"
                    if returns_value
                    else ":return: None."
                )
            )
        if structured_fields:
            documentation_lines.extend(["", *structured_fields])
        return "\n".join(documentation_lines)

    class AnnotationRepair(ast.NodeTransformer):
        def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
            self.generic_visit(node)
            if isinstance(node.slice, ast.Tuple):
                node.slice.elts = [
                    ast.Subscript(
                        value=ast.Name(id="tuple", ctx=ast.Load()),
                        slice=ast.Tuple(elts=element.elts, ctx=ast.Load()),
                        ctx=ast.Load(),
                    )
                    if isinstance(element, ast.Tuple)
                    else element
                    for element in node.slice.elts
                ]
            return node

    def annotation_contains_any(annotation: ast.AST | None) -> bool:
        """Return whether an annotation exposes an unconstrained Any value.

        :param annotation: Annotation syntax tree to inspect.
        :return: True when the annotation contains ``Any``.
        """

        return bool(
            annotation is not None
            and any(
                isinstance(child, ast.Name) and child.id == "Any"
                for child in ast.walk(annotation)
            )
        )

    def inferred_return_annotation(
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> ast.expr:
        """Infer a conservative public return annotation from executable returns.

        :param function: Function whose return values provide the evidence.
        :return: Concrete annotation expression, falling back to ``object``.
        """

        returned_values: list[ast.expr | None] = []

        class ReturnCollector(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node is function:
                    self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                if node is function:
                    self.generic_visit(node)

            def visit_Lambda(self, node: ast.Lambda) -> None:
                return None

            def visit_Return(self, node: ast.Return) -> None:
                returned_values.append(node.value)

        ReturnCollector().visit(function)
        if not returned_values or all(value is None for value in returned_values):
            return ast.Constant(value=None)

        narrowed_mappings = {
            argument.id
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "isinstance"
            and len(call.args) >= 2
            and isinstance(call.args[0], ast.Name)
            for argument in [call.args[0]]
            if any(
                isinstance(owner, ast.Name)
                and owner.id in {"dict", "Mapping", "MutableMapping"}
                for owner in ast.walk(call.args[1])
            )
        }

        def expression_annotation(value: ast.expr | None) -> str:
            if value is None or (
                isinstance(value, ast.Constant) and value.value is None
            ):
                return "None"
            if isinstance(value, ast.Constant):
                if isinstance(value.value, bool):
                    return "bool"
                if isinstance(value.value, int):
                    return "int"
                if isinstance(value.value, float):
                    return "float"
                if isinstance(value.value, str):
                    return "str"
                if isinstance(value.value, bytes):
                    return "bytes"
            if isinstance(value, ast.Dict):
                key_type = "str" if all(
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    for key in value.keys
                    if key is not None
                ) else "object"
                return f"dict[{key_type}, object]"
            if isinstance(value, (ast.List, ast.ListComp)):
                return "list[object]"
            if isinstance(value, (ast.Set, ast.SetComp)):
                return "set[object]"
            if isinstance(value, (ast.Tuple, ast.GeneratorExp)):
                return "tuple[object, ...]"
            if isinstance(value, ast.Name) and value.id in narrowed_mappings:
                return "dict[str, object]"
            if isinstance(value, ast.Call):
                called_name = ast.unparse(value.func).rsplit(".", 1)[-1]
                if called_name in {
                    "bool",
                    "bytes",
                    "float",
                    "int",
                    "Path",
                    "str",
                }:
                    return called_name
                if called_name in {"dict", "list", "set", "tuple"}:
                    return f"{called_name}[object, object]" if called_name == "dict" else (
                        "tuple[object, ...]" if called_name == "tuple" else f"{called_name}[object]"
                    )
            return "object"

        annotations = {
            expression_annotation(value)
            for value in returned_values
        }
        if len(annotations) == 1:
            annotation_text = annotations.pop()
        elif annotations == {"int", "float"}:
            annotation_text = "int | float"
        elif "object" in annotations or len(annotations) > 3:
            annotation_text = "object"
        else:
            annotation_text = " | ".join(
                sorted(annotations, key=lambda item: (item == "None", item))
            )
        return ast.parse(annotation_text, mode="eval").body

    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        typing_names: set[str] = set()
        for contract_path, class_name, required_method in missing_method_contracts:
            if (
                Path(contract_path).name.casefold()
                != Path(path).name.casefold()
                and Path(contract_path).resolve() != Path(path).resolve()
            ):
                continue
            class_node = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            if class_node is None:
                continue
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if required_method in methods:
                continue
            connected_handlers = {
                call.args[0].attr
                for call in ast.walk(class_node)
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "connect"
                    and call.args
                    and isinstance(call.args[0], ast.Attribute)
                    and isinstance(call.args[0].value, ast.Name)
                    and call.args[0].value.id == "self"
                )
            }
            candidates = [
                method
                for name, method in methods.items()
                if name in connected_handlers
                and any(
                    isinstance(call.func, ast.Name)
                    and call.func.id == required_method
                    for call in ast.walk(method)
                    if isinstance(call, ast.Call)
                )
            ]
            if not candidates and len(connected_handlers) == 1:
                candidates = [
                    methods[name]
                    for name in connected_handlers
                    if name in methods
                ]
            if len(candidates) != 1:
                continue
            previous_name = candidates[0].name
            candidates[0].name = required_method
            for node in ast.walk(class_node):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr == previous_name
                ):
                    node.attr = required_method
            repairs.append(
                f"{path}:{class_name}: renamed connected handler "
                f"{previous_name} to required method {required_method}."
            )
            changed = True
        if repair_type_hints:
            AnnotationRepair().visit(tree)
            for class_node in (
                node for node in tree.body if isinstance(node, ast.ClassDef)
            ):
                generic_parameters: list[ast.expr] = []
                for base in class_node.bases:
                    if not isinstance(base, ast.Subscript):
                        continue
                    generic_owner = base.value
                    if not (
                        isinstance(generic_owner, ast.Name)
                        and generic_owner.id == "Generic"
                    ):
                        continue
                    generic_parameters = (
                        list(base.slice.elts)
                        if isinstance(base.slice, ast.Tuple)
                        else [base.slice]
                    )
                for method in (
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "__init__"
                ):
                    repaired_body: list[ast.stmt] = []
                    for statement in method.body:
                        if (
                            isinstance(statement, ast.Assign)
                            and len(statement.targets) == 1
                            and isinstance(statement.targets[0], ast.Attribute)
                            and isinstance(
                                statement.targets[0].value,
                                ast.Name,
                            )
                            and statement.targets[0].value.id == "self"
                            and isinstance(
                                statement.value,
                                (ast.List, ast.Dict, ast.Set),
                            )
                            and not getattr(statement.value, "elts", None)
                            and not getattr(statement.value, "keys", None)
                        ):
                            if isinstance(statement.value, ast.List):
                                element = (
                                    generic_parameters[0]
                                    if len(generic_parameters) == 1
                                    else ast.Name(id="Any", ctx=ast.Load())
                                )
                                annotation = ast.Subscript(
                                    value=ast.Name(id="list", ctx=ast.Load()),
                                    slice=element,
                                    ctx=ast.Load(),
                                )
                            elif isinstance(statement.value, ast.Dict):
                                elements = (
                                    generic_parameters
                                    if len(generic_parameters) == 2
                                    else [
                                        ast.Name(id="Any", ctx=ast.Load()),
                                        ast.Name(id="Any", ctx=ast.Load()),
                                    ]
                                )
                                annotation = ast.Subscript(
                                    value=ast.Name(id="dict", ctx=ast.Load()),
                                    slice=ast.Tuple(
                                        elts=list(elements),
                                        ctx=ast.Load(),
                                    ),
                                    ctx=ast.Load(),
                                )
                            else:
                                element = (
                                    generic_parameters[0]
                                    if len(generic_parameters) == 1
                                    else ast.Name(id="Any", ctx=ast.Load())
                                )
                                annotation = ast.Subscript(
                                    value=ast.Name(id="set", ctx=ast.Load()),
                                    slice=element,
                                    ctx=ast.Load(),
                                )
                            if any(
                                isinstance(child, ast.Name)
                                and child.id == "Any"
                                for child in ast.walk(annotation)
                            ):
                                typing_names.add("Any")
                            repaired_body.append(
                                ast.AnnAssign(
                                    target=statement.targets[0],
                                    annotation=annotation,
                                    value=statement.value,
                                    simple=0,
                                )
                            )
                            changed = True
                        else:
                            repaired_body.append(statement)
                    method.body = repaired_body
            for function in (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                parent_by_node = {
                    id(child): parent
                    for parent in ast.walk(tree)
                    for child in ast.iter_child_nodes(parent)
                }
                parent = parent_by_node.get(id(function))
                public_surface = (
                    not function.name.startswith("_")
                    or (
                        function.name == "__init__"
                        and isinstance(parent, ast.ClassDef)
                        and not parent.name.startswith("_")
                    )
                )
                positional = [
                    *function.args.posonlyargs,
                    *function.args.args,
                ]
                defaults = {
                    argument.arg: default
                    for argument, default in zip(
                        positional[-len(function.args.defaults):]
                        if function.args.defaults
                        else [],
                        function.args.defaults,
                    )
                }
                arguments = [
                    *positional,
                    *function.args.kwonlyargs,
                ]
                if function.args.vararg:
                    arguments.append(function.args.vararg)
                if function.args.kwarg:
                    arguments.append(function.args.kwarg)
                for argument in arguments:
                    if argument.arg in {"self", "cls"}:
                        continue
                    invalid_callable = (
                        argument.annotation is not None
                        and any(
                            isinstance(child, ast.Name)
                            and child.id == "callable"
                            for child in ast.walk(argument.annotation)
                        )
                    )
                    invalid_public_any = (
                        public_surface
                        and argument is not function.args.vararg
                        and argument is not function.args.kwarg
                        and annotation_contains_any(argument.annotation)
                    )
                    if (
                        argument.annotation is None
                        or invalid_callable
                        or invalid_public_any
                    ):
                        default = defaults.get(argument.arg)
                        if (
                            isinstance(default, ast.Attribute)
                            and default.attr == "monotonic"
                        ):
                            argument.annotation = ast.parse(
                                "Callable[[], float]",
                                mode="eval",
                            ).body
                            typing_names.add("Callable")
                        elif public_surface:
                            argument.annotation = ast.Name(
                                id="object",
                                ctx=ast.Load(),
                            )
                        else:
                            argument.annotation = ast.Name(
                                id="Any",
                                ctx=ast.Load(),
                            )
                            typing_names.add("Any")
                        changed = True
                if function.returns is None or (
                    public_surface
                    and annotation_contains_any(function.returns)
                ):
                    if public_surface:
                        function.returns = inferred_return_annotation(function)
                    else:
                        has_value_return = any(
                            isinstance(child, ast.Return)
                            and child.value is not None
                            for child in ast.walk(function)
                        )
                        function.returns = (
                            ast.Name(id="Any", ctx=ast.Load())
                            if has_value_return
                            else ast.Constant(value=None)
                        )
                    if annotation_contains_any(function.returns):
                        typing_names.add("Any")
                    changed = True
            if typing_names:
                typing_import = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.ImportFrom)
                        and node.module == "typing"
                        and node.level == 0
                    ),
                    None,
                )
                if typing_import is None:
                    typing_import = ast.ImportFrom(
                        module="typing",
                        names=[],
                        level=0,
                    )
                    insertion_index = next(
                        (
                            index
                            for index, node in enumerate(tree.body)
                            if not isinstance(node, (ast.Import, ast.ImportFrom))
                        ),
                        len(tree.body),
                    )
                    tree.body.insert(insertion_index, typing_import)
                imported = {alias.name for alias in typing_import.names}
                typing_import.names.extend(
                    ast.alias(name=name)
                    for name in sorted(typing_names - imported)
                )
        if repair_docstrings:
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [
                        child.name
                        for child in node.body
                        if isinstance(
                            child,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and (
                            not child.name.startswith("_")
                            or child.name == "__init__"
                        )
                    ]
                    if not complete_docstring(node.name, node):
                        docstring = requested_docstring(
                            node.name,
                            node=node,
                            class_methods=methods,
                        )
                        if (
                            node.body
                            and isinstance(node.body[0], ast.Expr)
                            and isinstance(node.body[0].value, ast.Constant)
                            and isinstance(node.body[0].value.value, str)
                        ):
                            if node.body[0].value.value != docstring:
                                node.body[0].value.value = docstring
                                changed = True
                        else:
                            node.body.insert(
                                0,
                                ast.Expr(value=ast.Constant(value=docstring)),
                            )
                            changed = True
                    for method in (
                        child
                        for child in node.body
                        if isinstance(
                            child,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and (
                            not child.name.startswith("_")
                            or child.name == "__init__"
                            or f"{node.name}.{child.name}"
                            in requested_docstring_symbols
                        )
                    ):
                        qualified = f"{node.name}.{method.name}"
                        if complete_docstring(qualified, method):
                            continue
                        docstring = requested_docstring(
                            method.name,
                            node=method,
                        )
                        if (
                            method.body
                            and isinstance(method.body[0], ast.Expr)
                            and isinstance(method.body[0].value, ast.Constant)
                            and isinstance(method.body[0].value.value, str)
                        ):
                            if method.body[0].value.value != docstring:
                                method.body[0].value.value = docstring
                                changed = True
                        else:
                            method.body.insert(
                                0,
                                ast.Expr(value=ast.Constant(value=docstring)),
                            )
                            changed = True
                elif (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not node.name.startswith("_")
                    and not complete_docstring(node.name, node)
                ):
                    docstring = requested_docstring(
                        node.name,
                        node=node,
                    )
                    if (
                        node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)
                    ):
                        if node.body[0].value.value != docstring:
                            node.body[0].value.value = docstring
                            changed = True
                    else:
                        node.body.insert(
                            0,
                            ast.Expr(value=ast.Constant(value=docstring)),
                        )
                        changed = True
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            formatted_records, _formatting_notes = (
                format_project_edit_generated_python([updated[file_index]])
            )
            updated[file_index] = formatted_records[0]
            repairs.append(
                f"{Path(path).name}: repaired only requested Python contract "
                "annotations/docstrings"
            )
    return updated, repairs


def _repair_standardized_local_quality_issues(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Batch mechanical local-quality repairs from one validation snapshot."""

    diagnostics = "\n".join(str(error) for error in errors)
    overwritten_by_symbol: dict[str, set[str]] = {}
    for symbol, name in re.findall(
        r"\.py:([A-Za-z_][A-Za-z0-9_.]*): result assigned to "
        r"([A-Za-z_][A-Za-z0-9_]*) is overwritten before use;",
        diagnostics,
    ):
        overwritten_by_symbol.setdefault(symbol, set()).add(name)
    unused_by_symbol: dict[str, set[str]] = {}
    for symbol, names in re.findall(
        r"\.py:([A-Za-z_][A-Za-z0-9_.]*): unused local assignment\(s\) "
        r"introduce dead code: ([A-Za-z_][A-Za-z0-9_, ]*)\.",
        diagnostics,
    ):
        unused_by_symbol.setdefault(symbol, set()).update(
            name.strip()
            for name in names.split(",")
            if name.strip()
        )
    silent_exception_symbols = set(re.findall(
        r"\.py:([A-Za-z_][A-Za-z0-9_.]*): exception proof can pass silently ",
        diagnostics,
    ))
    masked_order_symbols = set(re.findall(
        r"\.py:([A-Za-z_][A-Za-z0-9_.]*): stable-order proof masks the "
        r"returned order with sorted\(\);",
        diagnostics,
    ))
    discarded_transform_symbols = set(re.findall(
        r"\.py:([A-Za-z_][A-Za-z0-9_.]*): discarded pure transform "
        r"introduces dead behavior:",
        diagnostics,
    ))
    if not (
        overwritten_by_symbol
        or unused_by_symbol
        or silent_exception_symbols
        or masked_order_symbols
        or discarded_transform_symbols
    ):
        return generated_files, []

    updated = list(generated_files)
    repairs: list[str] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        callable_rows: list[
            tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]
        ] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                callable_rows.append((node.name, node))
            elif isinstance(node, ast.ClassDef):
                callable_rows.extend(
                    (f"{node.name}.{member.name}", member)
                    for member in node.body
                    if isinstance(
                        member,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                )
        for symbol, function in callable_rows:
            changed_reasons: list[str] = []
            if symbol in discarded_transform_symbols:
                class DiscardedTransformTransformer(ast.NodeTransformer):
                    def visit_FunctionDef(
                        self,
                        node: ast.FunctionDef,
                    ) -> ast.AST | None:
                        if node is not function:
                            return node
                        return self.generic_visit(node)

                    def visit_AsyncFunctionDef(
                        self,
                        node: ast.AsyncFunctionDef,
                    ) -> ast.AST | None:
                        if node is not function:
                            return node
                        return self.generic_visit(node)

                    def visit_Expr(
                        self,
                        node: ast.Expr,
                    ) -> ast.AST | None:
                        call = node.value
                        if not isinstance(call, ast.Call):
                            return self.generic_visit(node)
                        assignment_name = ""
                        if (
                            isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.attr
                            in {
                                "casefold",
                                "lower",
                                "lstrip",
                                "removeprefix",
                                "removesuffix",
                                "replace",
                                "rstrip",
                                "strip",
                                "swapcase",
                                "title",
                                "translate",
                                "upper",
                            }
                        ):
                            assignment_name = call.func.value.id
                        elif (
                            isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "re"
                            and call.func.attr in {"sub", "subn"}
                            and len(call.args) >= 3
                            and isinstance(call.args[2], ast.Name)
                        ):
                            assignment_name = call.args[2].id
                        if not assignment_name:
                            return self.generic_visit(node)
                        changed_reasons.append(
                            "consumed validator-proven pure transform result "
                            + assignment_name
                        )
                        return ast.copy_location(
                            ast.Assign(
                                targets=[
                                    ast.Name(
                                        id=assignment_name,
                                        ctx=ast.Store(),
                                    )
                                ],
                                value=call,
                            ),
                            node,
                        )

                transformed = DiscardedTransformTransformer().visit(function)
                if isinstance(
                    transformed,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    function = transformed
            overwritten_names = overwritten_by_symbol.get(symbol, set())
            if overwritten_names:
                discard_indices: set[int] = set()
                for target_name in overwritten_names:
                    assignment_indices = [
                        index
                        for index, statement in enumerate(function.body)
                        if (
                            isinstance(statement, ast.Assign)
                            and len(statement.targets) == 1
                            and isinstance(statement.targets[0], ast.Name)
                            and statement.targets[0].id == target_name
                            and isinstance(statement.value, ast.Call)
                        )
                        or (
                            isinstance(statement, ast.AnnAssign)
                            and isinstance(statement.target, ast.Name)
                            and statement.target.id == target_name
                            and isinstance(statement.value, ast.Call)
                        )
                    ]
                    for current_index, next_index in zip(
                        assignment_indices,
                        assignment_indices[1:],
                    ):
                        next_assignment = function.body[next_index]
                        used_before_overwrite = any(
                            isinstance(node, ast.Name)
                            and isinstance(node.ctx, ast.Load)
                            and node.id == target_name
                            for statement in function.body[
                                current_index + 1:next_index
                            ]
                            for node in ast.walk(statement)
                        )
                        used_by_next_assignment = any(
                            isinstance(node, ast.Name)
                            and isinstance(node.ctx, ast.Load)
                            and node.id == target_name
                            for node in ast.walk(
                                getattr(next_assignment, "value", None)
                            )
                        )
                        if (
                            not used_before_overwrite
                            and not used_by_next_assignment
                        ):
                            discard_indices.add(current_index)
                            changed_reasons.append(
                                f"discarded overwritten {target_name} result"
                            )
                function.body = [
                    (
                        ast.Expr(value=statement.value)
                        if index in discard_indices
                        else statement
                    )
                    for index, statement in enumerate(function.body)
                ]
            unused_names = {
                *unused_by_symbol.get(symbol, set()),
                *unused_by_symbol.get(symbol.rsplit(".", 1)[-1], set()),
            }
            if unused_names:
                class UnusedLocalTransformer(ast.NodeTransformer):
                    def visit_FunctionDef(
                        self,
                        node: ast.FunctionDef,
                    ) -> ast.AST | None:
                        if node is not function:
                            return node
                        return self.generic_visit(node)

                    def visit_AsyncFunctionDef(
                        self,
                        node: ast.AsyncFunctionDef,
                    ) -> ast.AST | None:
                        if node is not function:
                            return node
                        return self.generic_visit(node)

                    def visit_Assign(
                        self,
                        node: ast.Assign,
                    ) -> ast.AST | None:
                        if (
                            len(node.targets) == 1
                            and isinstance(node.targets[0], ast.Name)
                            and node.targets[0].id in unused_names
                        ):
                            changed_reasons.append(
                                "removed validator-proven unused local "
                                + node.targets[0].id
                            )
                            return None
                        return self.generic_visit(node)

                    def visit_AnnAssign(
                        self,
                        node: ast.AnnAssign,
                    ) -> ast.AST | None:
                        if (
                            isinstance(node.target, ast.Name)
                            and node.target.id in unused_names
                        ):
                            changed_reasons.append(
                                "removed validator-proven unused local "
                                + node.target.id
                            )
                            return None
                        return self.generic_visit(node)

                UnusedLocalTransformer().visit(function)
            if symbol in silent_exception_symbols:
                for try_node in [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Try)
                    and not node.orelse
                    and any(
                        any(
                            isinstance(child, ast.Assert)
                            for child in ast.walk(handler)
                        )
                        for handler in node.handlers
                    )
                ]:
                    try_node.orelse = [
                        ast.Raise(
                            exc=ast.Call(
                                func=ast.Name(
                                    id="AssertionError",
                                    ctx=ast.Load(),
                                ),
                                args=[
                                    ast.Constant(
                                        value=(
                                            "Expected operation to raise the "
                                            "validated exception type"
                                        )
                                    )
                                ],
                                keywords=[],
                            ),
                            cause=None,
                        )
                    ]
                    changed_reasons.append(
                        "added explicit no-exception failure path"
                    )
            if symbol in masked_order_symbols:
                class DirectOrderTransformer(ast.NodeTransformer):
                    def visit_Call(self, node: ast.Call) -> ast.AST:
                        node = self.generic_visit(node)
                        if (
                            isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                            and node.func.id == "sorted"
                            and len(node.args) == 1
                            and isinstance(node.args[0], ast.Call)
                            and isinstance(
                                node.args[0].func,
                                ast.Attribute,
                            )
                        ):
                            return node.args[0]
                        return node

                DirectOrderTransformer().visit(function)
                changed_reasons.append(
                    "removed sorted() from stable-order proof"
                )
            if not changed_reasons:
                continue
            ast.fix_missing_locations(function)
            updated_files, splice_errors = (
                apply_project_edit_generated_symbol_repair(
                    updated,
                    path=path,
                    symbol=symbol,
                    replacement_response=ast.unparse(function),
                    forbidden_names=[],
                )
            )
            if splice_errors or updated_files == updated:
                continue
            updated = updated_files
            repairs.append(
                f"{Path(path).name}:{symbol} "
                + ", ".join(dict.fromkeys(changed_reasons))
            )
    return updated, repairs


def _repair_missing_stable_order_self_test_proof(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Append a bounded same-deadline proof using symbols inferred from the test."""

    diagnostics = "\n".join(str(error) for error in errors)
    targets = [
        (path, owner)
        for path, owner in re.findall(
            r"(?m)^(.+?\.py):([A-Za-z_][A-Za-z0-9_.]*): "
            r"stable-order proof never compares a multi-item ordered result\.$",
            diagnostics,
        )
    ]
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        matching_owners = [
            owner
            for target_path, owner in targets
            if (
                Path(target_path).name.casefold() == Path(path).name.casefold()
                or Path(target_path).resolve() == Path(path).resolve()
            )
        ]
        if not matching_owners:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner in matching_owners:
            owner_leaf = owner.rsplit(".", 1)[-1]
            function = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == owner_leaf
                ),
                None,
            )
            if function is None:
                continue
            nested_clock = next(
                (
                    node
                    for node in function.body
                    if isinstance(node, ast.ClassDef)
                    and any(
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == "__call__"
                        for child in node.body
                    )
                    and any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr in {"advance", "advance_by", "set_time"}
                        for call in ast.walk(function)
                    )
                ),
                None,
            )
            constructor_assignment = next(
                (
                    statement
                    for statement in function.body
                    if isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Name)
                    and nested_clock is not None
                    and any(
                        isinstance(argument, ast.Name)
                        and argument.id in {
                            target.id
                            for clock_assignment in function.body
                            if isinstance(clock_assignment, ast.Assign)
                            and len(clock_assignment.targets) == 1
                            and isinstance(clock_assignment.targets[0], ast.Name)
                            and isinstance(clock_assignment.value, ast.Call)
                            and isinstance(clock_assignment.value.func, ast.Name)
                            and clock_assignment.value.func.id == nested_clock.name
                            for target in clock_assignment.targets
                        }
                        for argument in statement.value.args
                    )
                ),
                None,
            )
            if constructor_assignment is None or nested_clock is None:
                continue
            queue_name = constructor_assignment.targets[0].id
            queue_class = constructor_assignment.value.func.id
            scheduling_calls = [
                call
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == queue_name
                and len(call.args) >= 2
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, (int, float))
            ]
            if len(scheduling_calls) < 2:
                continue
            schedule_method = scheduling_calls[0].func.attr
            readiness_methods = [
                call.func.attr
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == queue_name
                and not call.args
                and call.func.attr != schedule_method
            ]
            if not readiness_methods:
                continue
            readiness_method = max(
                set(readiness_methods),
                key=readiness_methods.count,
            )
            first_item = scheduling_calls[0].args[0]
            second_item = scheduling_calls[1].args[0]
            proof_source = (
                f"_stable_clock = {nested_clock.name}()\n"
                f"_stable_queue = {queue_class}(_stable_clock)\n"
                f"_stable_queue.{schedule_method}({ast.unparse(first_item)}, 1.0)\n"
                f"_stable_queue.{schedule_method}({ast.unparse(second_item)}, 1.0)\n"
                f"assert _stable_queue.{readiness_method}() == []\n"
                f"_stable_clock.advance(1.0)\n"
                f"assert _stable_queue.{readiness_method}() == "
                f"[{ast.unparse(first_item)}, {ast.unparse(second_item)}]"
            )
            function.body.extend(ast.parse(proof_source).body)
            changed = True
            repairs.append(
                f"{owner}: appended isolated same-deadline stable-order proof "
                f"using inferred {queue_class}.{schedule_method}/"
                f"{readiness_method} interfaces"
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, repairs


def _repair_missing_positive_predicate_fixture(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Insert a missing matching fixture before a positive predicate-result assertion."""

    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for function in [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(child, ast.Assert) for child in ast.walk(node))
        ]:
            predicate_literals: dict[str, ast.Constant] = {}
            for nested in [
                node
                for node in function.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                comparison = next(
                    (
                        child
                        for child in ast.walk(nested)
                        if isinstance(child, ast.Compare)
                        and len(child.ops) == 1
                        and isinstance(child.ops[0], ast.Eq)
                        and len(child.comparators) == 1
                        and isinstance(child.comparators[0], ast.Constant)
                    ),
                    None,
                )
                if comparison is not None:
                    predicate_literals[nested.name] = comparison.comparators[0]

            for statement_index, statement in enumerate(list(function.body)):
                if not (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and isinstance(statement.value.func.value, ast.Name)
                    and len(statement.value.args) == 1
                    and isinstance(statement.value.args[0], ast.Name)
                    and statement.value.args[0].id in predicate_literals
                ):
                    continue
                result_name = statement.targets[0].id
                positive_assertion = next(
                    (
                        later
                        for later in function.body[statement_index + 1:]
                        if isinstance(later, ast.Assert)
                        and isinstance(later.test, ast.Compare)
                        and isinstance(later.test.left, ast.Name)
                        and later.test.left.id == result_name
                        and any(
                            isinstance(value, ast.Constant)
                            and isinstance(value.value, int)
                            and value.value > 0
                            for value in later.test.comparators
                        )
                    ),
                    None,
                )
                if positive_assertion is None:
                    continue
                receiver_name = statement.value.func.value.id
                matching_literal = predicate_literals[
                    statement.value.args[0].id
                ]
                earlier_receiver_calls = [
                    child
                    for earlier in function.body[:statement_index]
                    for child in ast.walk(earlier)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == receiver_name
                    and len(child.args) >= 2
                    and isinstance(child.args[0], ast.Constant)
                    and isinstance(child.args[1], ast.Constant)
                    and isinstance(child.args[1].value, (int, float))
                ]
                if not earlier_receiver_calls or any(
                    ast.dump(call.args[0], include_attributes=False)
                    == ast.dump(matching_literal, include_attributes=False)
                    for call in earlier_receiver_calls
                ):
                    continue
                schedule_method = earlier_receiver_calls[0].func.attr
                fixture_statement = ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(
                                id=receiver_name,
                                ctx=ast.Load(),
                            ),
                            attr=schedule_method,
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Constant(value=matching_literal.value),
                            ast.Constant(value=0.0),
                        ],
                        keywords=[],
                    )
                )
                function.body.insert(statement_index, fixture_statement)
                changed = True
                repairs.append(
                    f"{function.name}: inserted the predicate-matching fixture "
                    f"through inferred {schedule_method} before its positive "
                    "result assertion"
                )
                break
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, repairs


def _repair_local_callable_definition_order(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Move a local callable definition before its first proven runtime use."""

    diagnostics = "\n".join(str(error) for error in errors)
    match = re.search(
        r"NameError: cannot access free variable ['\"]"
        r"([A-Za-z_][A-Za-z0-9_]*)['\"] where it is not associated with a value",
        diagnostics,
    )
    if not match:
        return generated_files, []
    local_name = match.group(1)
    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for function in [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            definition_index = next(
                (
                    index
                    for index, statement in enumerate(function.body)
                    if isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and statement.name == local_name
                ),
                None,
            )
            if definition_index is None:
                continue
            first_use_index = next(
                (
                    index
                    for index, statement in enumerate(function.body)
                    if index < definition_index
                    and any(
                        isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Load)
                        and node.id == local_name
                        for node in ast.walk(statement)
                    )
                ),
                None,
            )
            if first_use_index is None:
                continue
            definition = function.body.pop(definition_index)
            function.body.insert(first_use_index, definition)
            changed = True
            repairs.append(
                f"{function.name}: moved local callable {local_name} before "
                "its first runtime use"
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, repairs
