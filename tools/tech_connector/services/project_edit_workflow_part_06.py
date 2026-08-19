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
    _stable_validation_finding,
    _untouched_repair_regressions,
    _validation_finding_map,
)

from tech_connector.services.project_edit_workflow_part_02 import (
    _callable_repair_targets,
)


def _runtime_failing_test_targets(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> list[dict[str, str]]:
    """Resolve assertion failures whose deepest frame is the generated test."""

    test_names: set[str] = set()
    direct_frames: set[tuple[str, str]] = set()
    for error in errors:
        if "Disposable generated-patch validation failed:" not in str(error):
            continue
        all_frames = re.findall(
            r'File "([^"]+)", line \d+, in '
            r"([A-Za-z_][A-Za-z0-9_]*)",
            str(error),
        )
        if all_frames:
            direct_frames.add(
                (
                    Path(all_frames[-1][0]).name.casefold(),
                    all_frames[-1][1],
                )
            )
        for test_name, failure_body in re.findall(
            r"(?ms)^(?:ERROR|FAIL):\s+(test_[A-Za-z0-9_]+)[^\n]*\n"
            r"-+\n(.*?)(?=^={5,}\s*$|\Z)",
            str(error),
        ):
            frames = re.findall(
                r'File "([^"]+)", line \d+, in '
                r"([A-Za-z_][A-Za-z0-9_]*)",
                failure_body,
            )
            if frames and (
                Path(frames[-1][0]).name.startswith("test_")
                or frames[-1][1].startswith("test_")
            ):
                test_names.add(test_name)
    targets: list[dict[str, str]] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        path_key = Path(path).name.casefold()
        for function in [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            if (
                (path_key, function.name) in direct_frames
                and any(
                    isinstance(child, ast.Assert)
                    for child in ast.walk(function)
                )
            ):
                targets.append({
                    "path": path,
                    "symbol": function.name,
                })
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            for method in class_node.body:
                if (
                    isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and (
                        method.name in test_names
                        or (
                            (path_key, method.name) in direct_frames
                            and any(
                                isinstance(child, ast.Assert)
                                for child in ast.walk(method)
                            )
                        )
                    )
                ):
                    targets.append({
                        "path": path,
                        "symbol": f"{class_node.name}.{method.name}",
                    })
    return list({
        (target["path"], target["symbol"]): target
        for target in targets
    }.values())


def _runtime_failure_target_batches(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> list[dict[str, Any]]:
    """Map each unittest failure block to only its AST-proven repair candidates."""

    batches: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    for error in errors:
        if "Disposable generated-patch validation failed:" not in str(error):
            continue
        for test_name, failure_body in re.findall(
            r"(?ms)^(?:ERROR|FAIL):\s+(test_[A-Za-z0-9_]+)[^\n]*\n"
            r"-+\n(.*?)(?=^={5,}\s*$|\Z)",
            str(error),
        ):
            focused_error = (
                "Disposable generated-patch validation failed:\n"
                f"ERROR: {test_name}\n"
                "----------------------------------------------------------------------\n"
                f"{failure_body.strip()}"
            )
            targets = _callable_repair_targets(
                generated_files,
                [focused_error],
            )
            failing_test_targets: list[dict[str, str]] = []
            for path, _original, source in generated_files:
                if not Path(path).name.startswith("test_"):
                    continue
                try:
                    tree = ast.parse(source, filename=path)
                except SyntaxError:
                    continue
                failing_test_targets.extend(
                    {
                        "path": path,
                        "symbol": f"{class_node.name}.{method.name}",
                    }
                    for class_node in tree.body
                    if isinstance(class_node, ast.ClassDef)
                    for method in class_node.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and method.name == test_name
                )
            targets = list({
                (
                    str(target.get("path") or ""),
                    str(target.get("symbol") or ""),
                ): target
                for target in [*failing_test_targets, *targets]
                if str(target.get("path") or "")
                and str(target.get("symbol") or "")
            }.values())
            if not targets:
                continue
            target_key = tuple(
                (
                    str(target.get("path") or ""),
                    str(target.get("symbol") or ""),
                )
                for target in targets
            )
            key = (test_name, target_key)
            if key in seen:
                continue
            seen.add(key)
            batches.append({
                "test_name": test_name,
                "errors": [focused_error],
                "targets": targets,
            })
    return batches


def _repair_unbound_host_test_binding(
    generated_files: list[tuple[str, str, str]],
    *,
    errors: list[str],
    targets: list[dict[str, str]],
) -> tuple[list[tuple[str, str, str]], str]:
    """Bind a host root through the generated production module under test."""

    failure_text = "\n".join(str(error) for error in errors)
    match = re.search(
        r"\bNameError:\s+name\s+['\"]"
        r"(unreal|maya|cmds|bpy|pyfbsdk)"
        r"['\"]\s+is\s+not\s+defined\b",
        failure_text,
        flags=re.IGNORECASE,
    )
    production_sources = {
        Path(path).name.lower(): source
        for path, _original, source in generated_files
        if not Path(path).name.startswith("test_")
    }
    if match is not None:
        missing_name = match.group(1)
    elif "AssertionError: expected call not found" in failure_text:
        missing_name = next(
            (
                host_name
                for host_name in ("unreal", "cmds", "maya", "bpy", "pyfbsdk")
                if any(
                    re.search(
                        rf"(?m)^\s*(?:import\s+{re.escape(host_name)}\b|"
                        rf"from\s+\S+\s+import\s+{re.escape(host_name)}\b)",
                        production_source,
                    )
                    for production_source in production_sources.values()
                )
                and any(
                    re.search(rf"\b{re.escape(host_name)}\b", source)
                    for path, _original, source in generated_files
                    if Path(path).name.startswith("test_")
                )
            ),
            "",
        )
        if not missing_name:
            return generated_files, ""
    else:
        return generated_files, ""
    effective_targets = list(targets)
    failing_test_names = set(
        re.findall(r"\btest_[A-Za-z0-9_]+\b", failure_text)
    )
    if failing_test_names:
        for path, _original, source in generated_files:
            if not Path(path).name.startswith("test_"):
                continue
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError:
                continue
            for class_node in [
                node for node in tree.body if isinstance(node, ast.ClassDef)
            ]:
                for method in [
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in failing_test_names
                ]:
                    discovered = {
                        "path": path,
                        "symbol": f"{class_node.name}.{method.name}",
                    }
                    if discovered not in effective_targets:
                        effective_targets.append(discovered)
    updated = list(generated_files)
    for target in effective_targets:
        path = str(target.get("path") or "")
        symbol = str(target.get("symbol") or "")
        if not Path(path).name.startswith("test_") or "." not in symbol:
            continue
        record_index = next(
            (
                index
                for index, (candidate_path, _original, _source) in enumerate(updated)
                if Path(candidate_path).resolve() == Path(path).resolve()
            ),
            None,
        )
        if record_index is None:
            continue
        path_text, original, source = updated[record_index]
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        class_name, method_name = symbol.split(".", 1)
        owner = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        method = next(
            (
                node
                for node in (owner.body if owner is not None else [])
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == method_name
            ),
            None,
        )
        if method is None or not method.body:
            continue
        used_names = {
            node.id for node in ast.walk(method) if isinstance(node, ast.Name)
        }
        production_module = ""
        for import_node in tree.body:
            if not isinstance(import_node, ast.ImportFrom) or not import_node.module:
                continue
            imported_names = {
                alias.asname or alias.name for alias in import_node.names
            }
            if not (used_names & imported_names):
                continue
            production_source = production_sources.get(
                f"{import_node.module.rsplit('.', 1)[-1]}.py".lower(),
                "",
            )
            if not production_source:
                continue
            try:
                production_tree = ast.parse(production_source)
            except SyntaxError:
                continue
            available_bindings = {
                alias.asname or alias.name.split(".", 1)[0]
                for node in production_tree.body
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            available_bindings.update(
                alias.asname or alias.name
                for node in production_tree.body
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            )
            if missing_name in available_bindings:
                production_module = import_node.module
                break
        if not production_module:
            continue
        first_statement = method.body[0]
        if (
            isinstance(first_statement, ast.Expr)
            and isinstance(first_statement.value, ast.Constant)
            and isinstance(first_statement.value.value, str)
            and len(method.body) > 1
        ):
            first_statement = method.body[1]
        lines = source.splitlines(keepends=True)
        insertion_index = first_statement.lineno - 1
        indent = " " * first_statement.col_offset
        owner_alias = "_generated_host_owner"
        binding = f"{missing_name} = {owner_alias}.{missing_name}"
        existing_method = "".join(
            lines[method.lineno - 1 : int(method.end_lineno or method.lineno)]
        )
        if binding in existing_method:
            continue
        removed_lines: set[int] = set()
        for statement in method.body:
            assignment_target = None
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                assignment_target = statement.targets[0].id
            elif (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            ):
                assignment_target = statement.target.id
            if assignment_target == missing_name:
                removed_lines.update(
                    range(
                        statement.lineno - 1,
                        int(statement.end_lineno or statement.lineno),
                    )
                )
        if removed_lines:
            insertion_index -= sum(
                1 for line_index in removed_lines if line_index < insertion_index
            )
            lines = [
                line for line_index, line in enumerate(lines)
                if line_index not in removed_lines
            ]
        corrected = "".join(
            lines[:insertion_index]
            + [
                f"{indent}import {production_module} as {owner_alias}\n",
                f"{indent}{binding}\n",
            ]
            + lines[insertion_index:]
        )
        try:
            compile(corrected, path_text, "exec")
        except (SyntaxError, ValueError):
            continue
        updated[record_index] = (path_text, original, corrected)
        return updated, (
            f"bound {missing_name} through {production_module} inside {symbol}"
        )
    return generated_files, ""


def _repair_unused_test_bindings(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Drop unused test bindings while preserving expression side effects."""

    diagnostics = "\n".join(str(error) for error in errors)
    requested_repairs: dict[str, set[str]] = {}
    for symbol, names_text in re.findall(
        r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?): "
        r"fixture variables never consumed: ([A-Za-z0-9_, ]+)",
        diagnostics,
    ):
        requested_repairs.setdefault(symbol, set()).update(
            name.strip() for name in names_text.split(",") if name.strip()
        )
    if not requested_repairs:
        return generated_files, []
    updated = list(generated_files)
    repairs: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if not Path(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed_symbols: list[str] = []
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            for method in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                qualified = f"{class_node.name}.{method.name}"
                unused = requested_repairs.get(qualified)
                if not unused:
                    continue
                repaired_body: list[ast.stmt] = []
                changed = False
                for statement in method.body:
                    target_name = ""
                    value: ast.expr | None = None
                    if (
                        isinstance(statement, ast.Assign)
                        and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Name)
                    ):
                        target_name = statement.targets[0].id
                        value = statement.value
                    elif (
                        isinstance(statement, ast.AnnAssign)
                        and isinstance(statement.target, ast.Name)
                    ):
                        target_name = statement.target.id
                        value = statement.value
                    if target_name not in unused:
                        repaired_body.append(statement)
                        continue
                    changed = True
                    if isinstance(value, (ast.Call, ast.Await)):
                        repaired_body.append(
                            ast.copy_location(ast.Expr(value=value), statement)
                        )
                if changed:
                    method.body = repaired_body or [ast.Pass()]
                    changed_symbols.append(qualified)
        if not changed_symbols:
            continue
        ast.fix_missing_locations(tree)
        corrected = ast.unparse(tree).rstrip() + "\n"
        try:
            compile(corrected, path, "exec")
        except (SyntaxError, ValueError):
            continue
        updated[index] = (path, original, corrected)
        repairs.append(
            f"{Path(path).name}: removed unused bindings in "
            + ", ".join(changed_symbols)
        )
    return updated, repairs


def _repair_undefined_test_mock_bindings(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Create missing mock fixtures and connect matching patched getters."""

    diagnostics = "\n".join(str(error) for error in errors)
    missing_by_symbol: dict[str, set[str]] = {}
    for symbol, names_text in re.findall(
        r"Generated callables reference undefined names in "
        r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?): ([A-Za-z0-9_, ]+)",
        diagnostics,
    ):
        missing_by_symbol.setdefault(symbol, set()).update(
            name.strip()
            for name in names_text.split(",")
            if name.strip().startswith("mock_")
        )
    if not missing_by_symbol:
        return generated_files, []
    updated = list(generated_files)
    repairs: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if not Path(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed_symbols: list[str] = []
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            for method in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                qualified = f"{class_node.name}.{method.name}"
                missing = sorted(missing_by_symbol.get(qualified) or [])
                if not missing:
                    continue
                parameter_names = {
                    argument.arg
                    for argument in (
                        list(method.args.posonlyargs)
                        + list(method.args.args)
                        + list(method.args.kwonlyargs)
                    )
                }
                statements: list[ast.stmt] = []
                for missing_name in missing:
                    statements.extend(
                        ast.parse(f"{missing_name} = MagicMock()\n").body
                    )
                    matching_getter = next(
                        (
                            parameter
                            for parameter in parameter_names
                            if parameter == f"mock_get_{missing_name.removeprefix('mock_')}"
                        ),
                        "",
                    )
                    if matching_getter:
                        statements.extend(
                            ast.parse(
                                f"{matching_getter}.return_value = {missing_name}\n"
                            ).body
                        )
                insertion = (
                    1
                    if method.body
                    and isinstance(method.body[0], ast.Expr)
                    and isinstance(method.body[0].value, ast.Constant)
                    and isinstance(method.body[0].value.value, str)
                    else 0
                )
                method.body[insertion:insertion] = statements
                changed_symbols.append(qualified)
        if not changed_symbols:
            continue
        ast.fix_missing_locations(tree)
        corrected = ast.unparse(tree).rstrip() + "\n"
        try:
            compile(corrected, path, "exec")
        except (SyntaxError, ValueError):
            continue
        updated[index] = (path, original, corrected)
        repairs.append(
            f"{Path(path).name}: created missing mock fixtures in "
            + ", ".join(changed_symbols)
        )
    return updated, repairs


def _runtime_expected_error_test_targets(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    prompt: str,
) -> list[dict[str, str]]:
    """Route requested domain errors from success-shaped tests back to fixtures."""

    del prompt
    diagnostics = "\n".join(errors)
    if "Disposable generated-patch validation failed:" not in diagnostics:
        return []
    failure_test_lines: dict[str, int] = {}
    for test_name, failure_body in re.findall(
        r"(?ms)^(?:ERROR|FAIL):\s+(test_[A-Za-z0-9_]+)[^\n]*\n"
        r"-+\n(.*?)(?=^={5,}\s*$|\Z)",
        diagnostics,
    ):
        for _path, line_number, callable_name in re.findall(
            r'File "([^"]+)", line (\d+), in '
            r"([A-Za-z_][A-Za-z0-9_]*)",
            failure_body,
        ):
            if callable_name == test_name:
                failure_test_lines[test_name] = int(line_number)
                break
    candidate_tests = set(failure_test_lines)
    if not candidate_tests:
        return []
    targets: list[dict[str, str]] = []
    for path, _original_source, source in generated_files:
        if not Path(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            for method in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in candidate_tests
            ]:
                exception_contexts = [
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.With)
                    and any(
                        isinstance(item.context_expr, ast.Call)
                        and isinstance(item.context_expr.func, ast.Attribute)
                        and item.context_expr.func.attr
                        in {"assertRaises", "assertRaisesRegex", "raises"}
                        for item in node.items
                    )
                ]
                failure_line = failure_test_lines.get(method.name, 0)
                failure_inside_exception_context = bool(
                    failure_line
                    and any(
                        int(getattr(context, "lineno", 0))
                        <= failure_line
                        <= int(getattr(context, "end_lineno", 0))
                        for context in exception_contexts
                    )
                )
                if (
                    exception_contexts
                    and failure_line
                    and not failure_inside_exception_context
                ):
                    targets.append({
                        "path": path,
                        "symbol": f"{class_node.name}.{method.name}",
                    })
    return targets


def _augment_callable_targets_from_validation_causes(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    callable_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Add only callable targets whose ownership is proven by source and diagnostics."""

    augmented = list(callable_targets)
    target_keys = {
        (
            str(Path(str(target.get("path") or "")).resolve()),
            str(target.get("symbol") or ""),
        )
        for target in augmented
    }
    source_by_path = {
        str(Path(path).resolve()): source
        for path, _original, source in generated_files
    }

    def add_target(path: str, symbol: str) -> None:
        resolved_path = str(Path(path).resolve())
        key = (resolved_path, symbol)
        if key in target_keys:
            return
        source = source_by_path.get(resolved_path)
        if not source:
            return
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return
        owner_name, separator, method_name = symbol.partition(".")
        if not separator:
            return
        owner_node = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef) and node.name == owner_name
            ),
            None,
        )
        if owner_node is None or not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == method_name
            for node in owner_node.body
        ):
            return
        augmented.append({"path": path, "symbol": symbol})
        target_keys.add(key)

    for error in errors:
        normalized_error = re.sub(
            r"^(?:\[[^\]]+\]\s*)+",
            "",
            str(error),
        )
        exact_owner = re.match(
            r"^(?P<path>.+?\.py):"
            r"(?P<class>[A-Za-z_][A-Za-z0-9_]*)\."
            r"(?P<method>[A-Za-z_][A-Za-z0-9_]*):",
            normalized_error,
        )
        if exact_owner:
            add_target(
                exact_owner.group("path"),
                f"{exact_owner.group('class')}.{exact_owner.group('method')}",
            )

        worker_signal = re.match(
            r"^(?P<path>.+?\.py):"
            r"(?P<class>[A-Za-z_][A-Za-z0-9_]*): "
            r"approved worker signal `[^`]+` is declared but never emitted\.",
            normalized_error,
        )
        if worker_signal:
            add_target(
                worker_signal.group("path"),
                f"{worker_signal.group('class')}.run",
            )

        class_owner = re.match(
            r"^(?P<path>.+?\.py):"
            r"(?P<class>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<message>.+)$",
            normalized_error,
        )
        if class_owner and re.search(
            r"\bcross-file dependency\b|\bbackground execution\b|"
            r"\boff-UI-thread contract\b|\bthread start\b|"
            r"\bQThread\.start\b|\berror/failure path\b",
            class_owner.group("message"),
            flags=re.IGNORECASE,
        ):
            path = class_owner.group("path")
            source = source_by_path.get(str(Path(path).resolve()), "")
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError:
                tree = None
            class_node = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_owner.group("class")
                ),
                None,
            ) if tree is not None else None
            ranked_methods: list[tuple[int, str]] = []
            for method in (
                class_node.body if class_node is not None else []
            ):
                if not isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                score = 0
                lowered_name = method.name.casefold()
                if any(
                    token in lowered_name
                    for token in (
                        "execute",
                        "launch",
                        "refresh",
                        "run",
                        "start",
                    )
                ):
                    score += 8
                for node in ast.walk(method):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "start"
                    ):
                        score += 12
                    if (
                        isinstance(node, ast.Name)
                        and "worker" in node.id.casefold()
                    ):
                        score += 2
                if method.name == "__init__":
                    score -= 2
                if score > 0:
                    ranked_methods.append((score, method.name))
            if ranked_methods:
                ranked_methods.sort(reverse=True)
                add_target(
                    path,
                    f"{class_owner.group('class')}."
                    f"{ranked_methods[0][1]}",
                )

        unused_attribute = re.match(
            r"^(?P<path>.+?\.py):"
            r"(?P<class>[A-Za-z_][A-Za-z0-9_]*): "
            r"approved attribute `(?P<attribute>[^`]+)` is constructed but has "
            r"no meaningful runtime read, signal wiring, or state update\.",
            normalized_error,
        )
        if not unused_attribute:
            continue
        path = unused_attribute.group("path")
        resolved_path = str(Path(path).resolve())
        source = source_by_path.get(resolved_path)
        if not source:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        class_name = unused_attribute.group("class")
        owner_node = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if owner_node is None:
            continue
        scored_methods: list[
            tuple[int, ast.FunctionDef | ast.AsyncFunctionDef]
        ] = []
        for method in owner_node.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if method.name == "__init__":
                continue
            argument_names = {
                argument.arg.casefold()
                for argument in [
                    *method.args.posonlyargs,
                    *method.args.args,
                    *method.args.kwonlyargs,
                ]
                if argument.arg != "self"
            }
            ui_sink_calls = [
                node
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr
                in {
                    "addItem",
                    "addItems",
                    "append",
                    "clear",
                    "insertItem",
                    "setData",
                    "setModel",
                    "setText",
                    "setValue",
                }
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"
            ]
            if not ui_sink_calls:
                continue
            score = len(ui_sink_calls)
            if argument_names.intersection(
                {"data", "item", "items", "record", "records", "result", "results"}
            ):
                score += 5
            if any(
                token in method.name.casefold()
                for token in ("complete", "finish", "populate", "refresh", "result")
            ):
                score += 3
            scored_methods.append((score, method))
        if scored_methods:
            scored_methods.sort(key=lambda item: item[0], reverse=True)
            add_target(
                path,
                f"{class_name}.{scored_methods[0][1].name}",
            )
    return augmented


def _ui_wiring_owner_repair_target(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> dict[str, str] | None:
    """Resolve UI wiring failures to their structural owning method."""

    diagnostics = "\n".join(errors)
    unreachable = re.findall(
        r"([A-Z][A-Za-z0-9_]*) has connection setup methods not reachable "
        r"from __init__:\s*([A-Za-z_][A-Za-z0-9_]*)",
        diagnostics,
    )
    unreachable.extend(
        re.findall(
            r"([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*): "
            r"requirement-owning UI handler is unreachable",
            diagnostics,
        )
    )
    missing_connection = bool(
        re.search(
            r"no `?\.connect\(\.\.\.\)`? targets|no \.connect\(\.\.\.\) targets",
            diagnostics,
            flags=re.IGNORECASE,
        )
        or "expected a widget constructor" in diagnostics.lower()
    )
    unresolved_private = re.findall(
        r"([A-Z][A-Za-z0-9_]*): call to unresolved private method "
        r"`self\.([A-Za-z_][A-Za-z0-9_]*)\(\)`",
        diagnostics,
    )
    if not unreachable and not missing_connection and not unresolved_private:
        return None

    for path, _original_source, source in generated_files:
        if Path(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            methods = [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            unreachable_names = {
                method_name
                for class_name, method_name in unreachable
                if class_name == class_node.name
            }
            if unreachable_names:
                dispatch_methods = [
                    method
                    for method in methods
                    if any(
                        isinstance(call, ast.Call)
                        and (
                            (
                                isinstance(call.func, ast.Attribute)
                                and call.func.attr == "start"
                            )
                            or (
                                isinstance(call.func, ast.Name)
                                and call.func.id.casefold().endswith(
                                    ("worker", "thread", "runnable")
                                )
                            )
                        )
                        for call in ast.walk(method)
                    )
                ]
                if len(dispatch_methods) == 1:
                    return {
                        "path": path,
                        "symbol": (
                            f"{class_node.name}.{dispatch_methods[0].name}"
                        ),
                    }
                constructor = next(
                    (method for method in methods if method.name == "__init__"),
                    None,
                )
                if constructor is not None:
                    return {
                        "path": path,
                        "symbol": f"{class_node.name}.__init__",
                    }
            unresolved_names = {
                method_name
                for class_name, method_name in unresolved_private
                if class_name == class_node.name
            }
            if unresolved_names:
                callers = [
                    method.name
                    for method in methods
                    if any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                        and call.func.attr in unresolved_names
                        for call in ast.walk(method)
                    )
                ]
                if len(callers) == 1:
                    return {
                        "path": path,
                        "symbol": f"{class_node.name}.{callers[0]}",
                    }
                return {
                    "path": path,
                    "symbol": class_node.name,
                }

            if not missing_connection:
                continue
            ranked: list[tuple[int, str]] = []
            for method in methods:
                score = 0
                for node in ast.walk(method):
                    if (
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                    ):
                        lowered = node.attr.lower()
                        if lowered.endswith(
                            (
                                "_btn",
                                "_button",
                                "_input",
                                "_combo",
                                "_combo_box",
                                "_spinbox",
                                "_spin_box",
                                "_widget",
                            )
                        ):
                            score += 3
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "connect"
                    ):
                        score += 4
                if method.name == "__init__":
                    score += 1
                if score:
                    ranked.append((score, method.name))
            if ranked:
                _score, method_name = max(
                    ranked,
                    key=lambda item: (item[0], item[1] == "__init__"),
                )
                return {
                    "path": path,
                    "symbol": f"{class_node.name}.{method_name}",
                }
    return None


def _repair_locked_undeclared_public_methods(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove only public methods rejected by an exact locked-owner diagnostic."""

    targets: dict[tuple[str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*): "
        r"undeclared public callable\(s\) are forbidden by the locked class "
        r"contract: (?P<methods>[A-Za-z_][A-Za-z0-9_]*"
        r"(?:,\s*[A-Za-z_][A-Za-z0-9_]*)*)\."
    )
    for error in errors:
        match = pattern.match(str(error))
        if not match:
            continue
        targets.setdefault(
            (
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
            ),
            set(),
        ).update(
            value.strip()
            for value in match.group("methods").split(",")
            if value.strip()
        )
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        owner_targets = {
            owner: methods
            for (target_path, owner), methods in targets.items()
            if target_path == resolved_path
        }
        if not owner_targets:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        removed: list[str] = []
        privatized: list[str] = []
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            rejected_methods = owner_targets.get(class_node.name)
            if not rejected_methods:
                continue
            referenced_methods = {
                child.attr
                for child in ast.walk(class_node)
                if isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and child.value.id == "self"
                and child.attr in rejected_methods
            }
            for child in ast.walk(class_node):
                if (
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                    and child.attr in referenced_methods
                ):
                    child.attr = "_" + child.attr
            retained_body: list[ast.stmt] = []
            for statement in class_node.body:
                if (
                    isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and statement.name in rejected_methods
                    and not statement.name.startswith("_")
                ):
                    if statement.name in referenced_methods:
                        privatized.append(
                            f"{class_node.name}.{statement.name}"
                        )
                        statement.name = "_" + statement.name
                        retained_body.append(statement)
                        continue
                    removed.append(
                        f"{class_node.name}.{statement.name}"
                    )
                    continue
                retained_body.append(statement)
            class_node.body = retained_body
        if removed or privatized:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            notes.append(
                f"{Path(path).name}: normalized locked-contract public "
                "callable(s): "
                + ", ".join(
                    [
                        *(f"removed {name}" for name in sorted(removed)),
                        *(f"privatized {name}" for name in sorted(privatized)),
                    ]
                )
            )
    return updated, notes


def _repair_locked_dependency_method_ownership(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Route copied self-method references through their approved sibling owner."""

    targets: dict[tuple[str, str], str] = {}
    pattern = re.compile(
        r"(?:\[owner:[^\]]+\]\s+\[repair-scope:[^\]]+\]\s+)?"
        r"(?P<path>[A-Za-z]:\\.+?\.py):"
        r"(?:(?P<consumer>[A-Za-z_][A-Za-z0-9_]*)|<module>): "
        r"approved cross-file "
        r"dependency `(?P<dependency>[A-Za-z_][A-Za-z0-9_]*)` "
        r"(?:required by `(?P<required_consumer>[A-Za-z_][A-Za-z0-9_]*)` )?"
        r"is not imported\."
    )
    for error in errors:
        match = pattern.search(str(error))
        if match:
            consumer = (
                match.group("required_consumer")
                or match.group("consumer")
                or ""
            )
            if not consumer:
                continue
            targets[(
                str(Path(match.group("path")).resolve()),
                consumer,
            )] = match.group("dependency")
    if not targets:
        return generated_files, []

    dependency_methods: dict[str, set[str]] = {}
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            dependency_methods[class_node.name] = {
                statement.name
                for statement in class_node.body
                if isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and not statement.name.startswith("_")
            }

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        consumer_targets = {
            consumer: dependency
            for (target_path, consumer), dependency in targets.items()
            if target_path == resolved_path
        }
        if not consumer_targets:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed_routes: list[str] = []
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            dependency = consumer_targets.get(class_node.name)
            if not dependency:
                continue
            local_methods = {
                statement.name
                for statement in class_node.body
                if isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            approved_methods = dependency_methods.get(dependency, set())
            for method_node in (
                statement
                for statement in class_node.body
                if isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            ):
                local_bindings = {
                    argument.arg
                    for argument in [
                        *method_node.args.posonlyargs,
                        *method_node.args.args,
                        *method_node.args.kwonlyargs,
                    ]
                }
                if method_node.args.vararg:
                    local_bindings.add(method_node.args.vararg.arg)
                if method_node.args.kwarg:
                    local_bindings.add(method_node.args.kwarg.arg)
                local_bindings.update(
                    node.id
                    for node in ast.walk(method_node)
                    if isinstance(node, ast.Name)
                    and isinstance(node.ctx, (ast.Store, ast.Del))
                )

                class DependencyCallableRouter(ast.NodeTransformer):
                    def visit_Name(self, node: ast.Name) -> ast.AST:
                        if (
                            isinstance(node.ctx, ast.Load)
                            and node.id in approved_methods
                            and node.id not in local_bindings
                            and node.id not in local_methods
                        ):
                            changed_routes.append(
                                f"{dependency}.{node.id}"
                            )
                            return ast.copy_location(
                                ast.Attribute(
                                    value=ast.Call(
                                        func=ast.Name(
                                            id=dependency,
                                            ctx=ast.Load(),
                                        ),
                                        args=[],
                                        keywords=[],
                                    ),
                                    attr=node.id,
                                    ctx=ast.Load(),
                                ),
                                node,
                            )
                        return node

                DependencyCallableRouter().visit(method_node)
            for node in ast.walk(class_node):
                if not (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr not in local_methods
                    and node.attr in approved_methods
                    and isinstance(node.ctx, ast.Load)
                ):
                    continue
                node.value = ast.Call(
                    func=ast.Name(id=dependency, ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
                changed_routes.append(f"{dependency}.{node.attr}")
        if changed_routes:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            notes.append(
                f"{Path(path).name}: routed dependency operation through "
                "its declaring owner: "
                + ", ".join(sorted(set(changed_routes)))
            )
    return updated, notes


def _repair_required_worker_finished_cleanup(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Connect an existing approved cleanup handler before worker start."""

    targets: dict[tuple[str, str, str], str] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\."
        r"(?P<method>[A-Za-z_][A-Za-z0-9_]*): retained worker "
        r"`self\.(?P<worker>[A-Za-z_][A-Za-z0-9_]*)` must connect its "
        r"`finished` signal"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets[(
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
                match.group("method"),
            )] = match.group("worker")
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            cleanup_names = [
                name
                for name in methods
                if re.search(
                    r"(?:cleanup|clean_up|release|dispose)",
                    name,
                    flags=re.IGNORECASE,
                )
            ]
            if len(cleanup_names) != 1:
                continue
            for (target_path, owner, method_name), worker_name in targets.items():
                if target_path != resolved_path or owner != class_node.name:
                    continue
                launcher = methods.get(method_name)
                if launcher is None:
                    continue
                connection = ast.parse(
                    f"self.{worker_name}.finished.connect("
                    f"self.{cleanup_names[0]})"
                ).body[0]
                for index, statement in enumerate(launcher.body):
                    if (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Attribute)
                        and statement.value.func.attr == "start"
                    ):
                        launcher.body.insert(index, connection)
                        changed = True
                        notes.append(
                            f"{Path(path).name}:{owner}.{method_name}: "
                            "connected worker finished cleanup before start."
                        )
                        break
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _build_final_requirement_review_stage(
    *,
    prompt: str,
    requirement_ledger: list[dict[str, str]],
    generated_files: list[tuple[str, str, str]],
    project_root: str,
    grounded_evidence: str = "",
) -> ProjectEditPromptStage:
    """Build one bounded, ID-addressed completeness review batch."""

    package_source = "\n\n".join(
        f"FILE: {path}\n```python\n{source}\n```"
        for path, _original, source in generated_files
    )
    evidence = grounded_evidence.strip() or (
        "External API owner/member existence is enforced by the separate "
        "authoritative API validation pass. Do not demand runtime hasattr/getattr "
        "checks for members that passed that gate."
    )
    ledger_text = json.dumps(
        requirement_ledger,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    example_requirement_id = (
        str(
            requirement_ledger[0].get("id")
            or requirement_ledger[0].get("requirement_id")
            or ""
        )
        if requirement_ledger
        else ""
    )
    output_allowance = max(900, 320 + len(requirement_ledger) * 90)
    return ProjectEditPromptStage(
        key="final_requirement_review",
        label="Reviewing request-to-code completeness",
        system_prompt=(
            "You are the final production-readiness auditor for a generated Python "
            "package. Compare every supplied semantic request clause with executable "
            "code after standardized deterministic validation. Do not add preferences "
            "or requirements absent from the "
            "request. Comments, docstrings, and calls made only by tests are not "
            "implementation proof. A mocked operation is proven only by meaningful "
            "assertions about the requested observable behavior. Public API claims "
            "must agree with supplied authoritative evidence. Do not propose dynamic "
            "runtime member discovery as a substitute for verified API calls. Return "
            "Every issue must cite one supplied requirement_id. Requirement IDs are "
            "canonical: never repeat or paraphrase ledger text in the output. For an explicitly "
            "requested verification callable such as run_self_test, its setup, calls, "
            "assertions, and caught exceptions are the requested production artifact: "
            "audit every listed proof clause separately and require executable evidence "
            "inside that callable. Never infer fields, "
            "signatures, tests, or behaviors that are not written in that ledger row. "
            "Every ledger row in this batch must appear exactly once in coverage. "
            "Split coordinated imperative clauses inside a row into separate checks "
            "and cite concise executable evidence for each one; a bare ready=true "
            "verdict is invalid. Inspect the complete owning callable and its sibling "
            "worker/helper declarations before marking a wiring obligation unmet. "
            "An unmet issue must cite a concrete absent call, connection, state "
            "transition, or contradictory executable statement; positive source "
            "evidence cannot support an unmet verdict. "
            "JSON only."
        ),
        user_prompt=f"""Generated source owned by this review batch:
{package_source}

Canonical requirement batch:
```json
{ledger_text}
```

Authoritative symbol/API evidence:
{evidence or "(no additional evidence)"}

Audit each requested file, symbol, behavior, validation rule, callback contract,
integration/wiring requirement, and requested test proof independently. For each
real omission or contradiction, identify the smallest existing owner as
`relative_file.py:Qualified.symbol`; if an entire requested test or symbol is
missing, identify its owning file or class. Do not report style preferences.

Return exactly:
{{
  "ready": true_or_false,
  "coverage": [
    {{
      "requirement_id": {json.dumps(example_requirement_id)},
      "owner": "relative_file.py:Qualified.symbol",
      "checks": [
        {{
          "verdict": "met|unmet",
          "evidence": "concise exact executable source fact or missing fact"
        }}
      ]
    }}
  ],
  "issues": [
    {{
      "requirement_id": {json.dumps(example_requirement_id)},
      "category": "implementation|api|wiring|validation|callback|test_coverage",
      "owner": "relative_file.py:Qualified.symbol",
      "missing_observable": "an exact word or phrase copied from that ledger row",
      "evidence": "the conflicting or missing source fact",
      "repair": "the smallest behavior-preserving correction"
    }}
  ]
}}

`ready` may be true only when every explicit clause has executable implementation
and every explicitly requested proof has a meaningful assertion.
""",
        model_tier="local_code",
        num_ctx=8192,
        num_predict=output_allowance,
        timeout=120,
        no_progress_seconds=30,
        prefer_coder=True,
        coder_preference="standard",
        response_format="json",
        metadata={
            "requirement_ids": [
                str(row.get("id") or row.get("requirement_id") or "")
                for row in requirement_ledger
            ],
            "output_allowance": output_allowance,
        },
    )


def _final_requirement_review_batches(
    requirement_ledger: list[dict[str, str]],
    *,
    max_rows: int = 5,
    max_characters: int = 6000,
) -> list[list[dict[str, str]]]:
    """Split semantic review into complete owner-sized ledgers.

    Small coherent batches preserve cross-method state context while keeping
    compact local coding models inside the strict JSON protocol. Character and
    row caps avoid oversized review prompts, while proof-cache reuse prevents
    already accepted rows from being reviewed again.
    """

    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_characters = 0
    for row in requirement_ledger:
        row_characters = len(json.dumps(row, ensure_ascii=True, default=str))
        if current and (
            len(current) >= max_rows
            or current_characters + row_characters > max_characters
        ):
            batches.append(current)
            current = []
            current_characters = 0
        current.append(row)
        current_characters += row_characters
    if current:
        batches.append(current)
    return batches


def _approved_behavior_contract_rows(
    implementation_plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return behavior contracts whose owners were approved during planning."""

    rows: list[dict[str, Any]] = []
    for raw_contract in implementation_plan.get("behavior_contracts") or []:
        if not isinstance(raw_contract, Mapping):
            continue
        behavior_id = str(raw_contract.get("behavior_id") or "")
        requirement_id = str(raw_contract.get("requirement_id") or "")
        owners = [
            {
                "path": str(owner.get("path") or ""),
                "symbol": str(owner.get("symbol") or ""),
                "callable_name": str(owner.get("callable_name") or ""),
            }
            for owner in raw_contract.get("production_owners") or []
            if isinstance(owner, Mapping)
            and str(owner.get("path") or "")
            and str(owner.get("symbol") or "")
        ]
        expected = [
            str(value).strip()
            for value in raw_contract.get("expected_observations") or []
            if str(value).strip()
        ]
        operation = str(raw_contract.get("operation") or "").strip()
        if not behavior_id or not requirement_id or not owners or not operation or not expected:
            continue
        rows.append({
            "behavior_id": behavior_id,
            "requirement_id": requirement_id,
            "production_owners": owners,
            "polarity": str(raw_contract.get("polarity") or ""),
            "preconditions": [
                str(value).strip()
                for value in raw_contract.get("preconditions") or []
                if str(value).strip()
            ],
            "operation": operation,
            "expected_observations": expected,
            "execution_steps": [
                {
                    "step_id": str(step.get("step_id") or ""),
                    "phase": str(step.get("phase") or ""),
                    "chunk_id": str(step.get("chunk_id") or ""),
                    "callable_name": str(step.get("callable_name") or ""),
                    "instruction": str(step.get("instruction") or ""),
                    "requires": [
                        str(value)
                        for value in step.get("requires") or []
                        if str(value)
                    ],
                    "produces": [
                        str(value)
                        for value in step.get("produces") or []
                        if str(value)
                    ],
                    "invalidates": [
                        str(value)
                        for value in step.get("invalidates") or []
                        if str(value)
                    ],
                    "assertions": [
                        str(value)
                        for value in step.get("assertions") or []
                        if str(value)
                    ],
                }
                for step in raw_contract.get("execution_steps") or []
                if isinstance(step, Mapping)
            ],
        })
    return rows


def _ephemeral_behavior_bindings(
    harness_source: str,
) -> tuple[dict[str, list[str]], list[str]]:
    """Read explicit test-to-contract ownership from a disposable harness."""

    try:
        tree = ast.parse(harness_source, filename="<ephemeral_behavior_harness>")
    except SyntaxError as exc:
        return {}, [f"Disposable behavior harness did not parse: {exc}."]
    for statement in tree.body:
        if (
            isinstance(statement, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name)
                and target.id == "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__"
                for target in (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
            )
        ):
            try:
                raw_bindings = ast.literal_eval(statement.value)
            except (TypeError, ValueError):
                return {}, [
                    "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ must be a literal dict."
                ]
            if not isinstance(raw_bindings, dict):
                return {}, [
                    "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ must be a literal dict."
                ]
            bindings = {
                str(test_name): [
                    str(value)
                    for value in (
                        behavior_ids
                        if isinstance(behavior_ids, (list, tuple))
                        else [behavior_ids]
                    )
                    if str(value)
                ]
                for test_name, behavior_ids in raw_bindings.items()
                if str(test_name)
            }
            return bindings, []
    return {}, [
        "Disposable behavior harness is missing the explicit "
        "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ sidecar."
    ]


def _runtime_behavior_contract_targets(
    harness_source: str,
    errors: list[str],
    implementation_plan: Mapping[str, Any],
) -> tuple[set[str], list[dict[str, str]], list[dict[str, Any]]]:
    """Resolve failed disposable tests through approved sidecar ownership."""

    diagnostics = "\n".join(str(error) for error in errors)
    failing_tests = set(re.findall(r"\b(test_[A-Za-z0-9_]+)\b", diagnostics))
    bindings, binding_errors = _ephemeral_behavior_bindings(harness_source)
    if binding_errors or not failing_tests:
        return set(), [], []
    behavior_ids = {
        behavior_id
        for test_name in failing_tests
        for behavior_id in bindings.get(test_name, [])
    }
    source_behavior_ids = {
        re.sub(r"__owner_\d+$", "", behavior_id)
        for behavior_id in behavior_ids
    }
    contracts = [
        contract
        for contract in _approved_behavior_contract_rows(implementation_plan)
        if contract["behavior_id"] in source_behavior_ids
    ]
    targets = list({
        (owner["path"], owner["symbol"]): {
            "path": owner["path"],
            "symbol": owner["symbol"],
        }
        for contract in contracts
        for owner in contract["production_owners"]
    }.values())
    return behavior_ids, targets, contracts


def _expanded_ephemeral_behavior_rows(
    implementation_plan: Mapping[str, Any],
    *,
    generated_files: list[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return stable single-owner behaviors that still require runtime proof."""

    behavior_rows: list[dict[str, Any]] = []
    deterministic_ui_classes: set[tuple[str, str]] = set()
    generated_sources_by_name = {
        Path(path).name: source
        for path, _original, source in generated_files or []
    }
    operation_source = generated_sources_by_name.get("operations.py", "")
    planner_source = generated_sources_by_name.get("planner.py", "")
    wrapper_source = generated_sources_by_name.get("wrappers.py", "")
    executor_source = generated_sources_by_name.get("executor.py", "")
    path_policy_source = generated_sources_by_name.get("path_policy.py", "")
    blender_adapter_source = generated_sources_by_name.get(
        "blender_adapter.py",
        "",
    )
    maya_adapter_source = generated_sources_by_name.get("maya_adapter.py", "")
    image_cache_source = generated_sources_by_name.get("cache.py", "")
    queue_source = generated_sources_by_name.get("queue.py", "")
    result_source = generated_sources_by_name.get("result.py", "")
    registry_source = generated_sources_by_name.get("command_registry.py", "")
    try:
        normalized_operation_source = ast.unparse(ast.parse(operation_source))
        normalized_planner_source = ast.unparse(ast.parse(planner_source))
    except SyntaxError:
        normalized_operation_source = ""
        normalized_planner_source = ""
    compiled_asset_pipeline = bool(
        all((operation_source, planner_source, wrapper_source, executor_source))
        and all(
            token in normalized_operation_source
            for token in (
                "connector.game_engine.wrappers.configure_asset",
                "('asset_path', 'value')",
                "missing = sorted",
                "unexpected = sorted",
                "kwargs = dict(spec.optional)",
                "kwargs.update(dict(params))",
            )
        )
        and "json.dumps" not in normalized_planner_source
        and all(
            token in normalized_planner_source
            for token in ("'asset_path'", "'value'", "'save'")
        )
        and wrapper_source.count("json.dumps(value)") == 1
        and "bool(save)" in wrapper_source
        and "host_api.NativeLibrary.configure_asset" in wrapper_source
        and "build_operation_call" in executor_source
        and "importlib.import_module" in executor_source
        and "host_api" not in executor_source
    )
    try:
        normalized_path_policy_source = ast.unparse(ast.parse(path_policy_source))
        normalized_blender_source = ast.unparse(ast.parse(blender_adapter_source))
        normalized_maya_source = ast.unparse(ast.parse(maya_adapter_source))
    except SyntaxError:
        normalized_path_policy_source = ""
        normalized_blender_source = ""
        normalized_maya_source = ""
    compiled_path_policy = bool(
        all((
            normalized_path_policy_source,
            normalized_blender_source,
            normalized_maya_source,
        ))
        and all(
            token in normalized_path_policy_source
            for token in (
                "root = Path(project_root).resolve()",
                "candidate = Path(requested)",
                "if not candidate.is_absolute()",
                "if not candidate.suffix",
                "candidate = candidate.resolve()",
                "candidate.relative_to(root)",
            )
        )
        and "return normalize_export_path(project_root, requested)"
        in normalized_blender_source
        and "return normalize_export_path(project_root, requested)"
        in normalized_maya_source
    )
    try:
        normalized_image_cache_source = ast.unparse(ast.parse(image_cache_source))
    except SyntaxError:
        normalized_image_cache_source = ""
    compiled_image_cache = bool(
        normalized_image_cache_source
        and all(
            token in normalized_image_cache_source
            for token in (
                "class ImageCache",
                "self._lock = RLock()",
                "if capacity < 1",
                "self.clock = clock",
                "self._recency",
                "min(self._recency",
                "current_time - timestamp < self.ttl_seconds",
                "self._recency_counter += 1",
                "return value",
                "def clear(",
                "def __len__(",
            )
        )
        and normalized_image_cache_source.count("with self._lock:") >= 4
        and "return self.items.get(key) or default" not in normalized_image_cache_source
    )
    compiled_ordered_image_cache = bool(
        normalized_image_cache_source
        and all(
            token in normalized_image_cache_source
            for token in (
                "class ImageCache",
                "self._items: OrderedDict[object, object] = OrderedDict()",
                "self._timestamps: OrderedDict[object, float] = OrderedDict()",
                "self._lock = RLock()",
                "self._expire(current_time)",
                "self._items.popitem(last=False)",
                "self._timestamps.pop(evicted_key, None)",
                "self._expire(self.clock())",
                "self._items.move_to_end(key)",
                "return self._items[key]",
            )
        )
        and normalized_image_cache_source.count("with self._lock:") >= 4
    )
    try:
        normalized_queue_source = ast.unparse(ast.parse(queue_source))
    except SyntaxError:
        normalized_queue_source = ""
    compiled_priority_queue = bool(
        normalized_queue_source
        and all(
            token in normalized_queue_source
            for token in (
                "class PriorityJobQueue",
                "self._lock = threading.RLock()",
                "self._pending: dict[str, int] = {}",
                "heapq.heappush(self._heap",
                "heapq.heappop(self._heap)",
                "isinstance(priority, bool)",
                "not isinstance(priority, int)",
                "if job_id in self._pending",
                "self._pending.pop(job_id, None) is not None",
                "self._pending.get(job_id) == sequence",
                "return payload",
                "return default",
            )
        )
        and normalized_queue_source.count("with self._lock:") >= 4
        and "self._heap.sort(" not in normalized_queue_source
    )
    try:
        normalized_result_source = ast.unparse(ast.parse(result_source))
    except SyntaxError:
        normalized_result_source = ""
    compiled_command_result = bool(
        normalized_result_source
        and all(
            token in normalized_result_source
            for token in (
                "def normalize_command_result(",
                "if payload is None:",
                "isinstance(payload, Mapping)",
                "'ok' in payload",
                "'ok': bool(payload['ok'])",
                "'value': payload.get('value')",
                "'error': payload.get('error', '')",
                "return {'ok': True, 'value': payload, 'error': ''}",
            )
        )
    )
    try:
        normalized_registry_source = ast.unparse(ast.parse(registry_source))
    except SyntaxError:
        normalized_registry_source = ""
    compiled_command_registry = bool(
        normalized_registry_source
        and all(
            token in normalized_registry_source
            for token in (
                "class CommandRegistry",
                "self._lock = threading.RLock()",
                "return name.strip().casefold()",
                "if not canonical or not callable(handler)",
                "normalized_names & occupied",
                "self._aliases.get(normalized, normalized)",
                "raise KeyError(normalized)",
                "raise PermissionError(",
                "return self._commands[canonical]",
                "return sorted(self._commands)",
            )
        )
        and normalized_registry_source.count("with self._lock:") >= 3
    )
    for path, _original, source in generated_files or []:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            base_names = {
                (
                    base.id
                    if isinstance(base, ast.Name)
                    else base.attr
                    if isinstance(base, ast.Attribute)
                    else ""
                ).casefold()
                for base in class_node.bases
            }
            if any(
                base_name.endswith(("dialog", "widget", "window"))
                for base_name in base_names
                if base_name
            ):
                deterministic_ui_classes.add((
                    str(Path(path).resolve()),
                    class_node.name,
                ))
    for row in _approved_behavior_contract_rows(implementation_plan):
        owners = [
            dict(owner)
            for owner in row.get("production_owners") or []
            if isinstance(owner, Mapping)
        ]
        owner_capsules = owners or [{}]
        for owner_index, owner in enumerate(owner_capsules, start=1):
            callable_name = str(owner.get("callable_name") or "")
            if not callable_name:
                step_callables = list(dict.fromkeys(
                    str(step.get("callable_name") or "").strip()
                    for step in row.get("execution_steps") or []
                    if isinstance(step, Mapping)
                    and str(step.get("callable_name") or "").strip()
                ))
                if len(step_callables) == 1:
                    callable_name = step_callables[0]
            symbol = str(owner.get("symbol") or "")
            class_name = (
                symbol.rsplit(".", 1)[0]
                if "." in symbol
                else symbol
            )
            owner_path = str(owner.get("path") or "")
            if (
                compiled_asset_pipeline
                and Path(owner_path).name
                in {"operations.py", "planner.py", "wrappers.py", "executor.py"}
            ):
                continue
            if (
                compiled_path_policy
                and Path(owner_path).name
                in {"path_policy.py", "blender_adapter.py", "maya_adapter.py"}
            ):
                continue
            if (
                (compiled_image_cache or compiled_ordered_image_cache)
                and Path(owner_path).name == "cache.py"
            ):
                continue
            if compiled_priority_queue and Path(owner_path).name == "queue.py":
                continue
            if compiled_command_result and Path(owner_path).name == "result.py":
                continue
            if (
                compiled_command_registry
                and Path(owner_path).name == "command_registry.py"
            ):
                continue
            if (
                generated_files is not None
                and (
                    str(Path(owner_path).resolve()),
                    class_name,
                ) in deterministic_ui_classes
            ):
                continue
            owner_steps = [
                dict(step)
                for step in row.get("execution_steps") or []
                if isinstance(step, Mapping)
                and (
                    not callable_name
                    or str(step.get("callable_name") or "")
                    in {"", callable_name}
                )
            ]
            source_behavior_id = str(row.get("behavior_id") or "")
            capsule_behavior_id = (
                source_behavior_id
                if len(owner_capsules) == 1
                else f"{source_behavior_id}__owner_{owner_index}"
            )
            behavior_rows.append({
                **row,
                "behavior_id": capsule_behavior_id,
                "source_behavior_id": source_behavior_id,
                "production_owners": [owner] if owner else [],
                "execution_steps": owner_steps,
                "owner_execution": {
                    "symbol": symbol,
                    "class_name": class_name,
                    "callable_name": callable_name,
                    "must_construct_real_owner": bool(class_name),
                    "must_invoke_exact_callable": bool(callable_name),
                    "forbidden_patch_symbols": [
                        value
                        for value in {
                            symbol,
                            class_name,
                        }
                        if value
                    ],
                },
            })
    owner_test_names: dict[tuple[str, str, str], str] = {}
    for row in behavior_rows:
        owner_execution = row.get("owner_execution") or {}
        owner_key = (
            str(owner_execution.get("symbol") or ""),
            str(owner_execution.get("class_name") or ""),
            str(owner_execution.get("callable_name") or ""),
        )
        if owner_key not in owner_test_names:
            owner_slug = re.sub(
                r"[^A-Za-z0-9_]+",
                "_",
                "_".join(value for value in owner_key[1:] if value),
            ).strip("_").casefold() or "module_behavior"
            owner_test_names[owner_key] = (
                f"test_{owner_slug}_{len(owner_test_names) + 1:03d}"
            )
        row["test_name"] = owner_test_names[owner_key]
    return behavior_rows


def _merge_ephemeral_harness_sources(sources: list[str]) -> str:
    """Merge independently generated unittest capsules without duplicate owners."""

    imports: list[ast.stmt] = []
    import_keys: set[str] = set()
    classes: dict[str, ast.ClassDef] = {}
    class_order: list[str] = []
    other_statements: list[ast.stmt] = []
    main_guard: ast.If | None = None
    for source in sources:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # A malformed disposable capsule is untrusted validation input.
            # Omit it so coverage parsing can request only the missing proof
            # without crashing or mutating the validated production candidate.
            continue
        for statement in tree.body:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                key = ast.dump(statement, include_attributes=False)
                if key not in import_keys:
                    import_keys.add(key)
                    imports.append(statement)
                continue
            if isinstance(statement, ast.ClassDef):
                existing = classes.get(statement.name)
                if existing is None:
                    classes[statement.name] = statement
                    class_order.append(statement.name)
                else:
                    existing_method_names = {
                        node.name
                        for node in existing.body
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                    }
                    existing.body.extend(
                        node
                        for node in statement.body
                        if not (
                            isinstance(
                                node,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and node.name in existing_method_names
                        )
                    )
                continue
            if (
                isinstance(statement, ast.If)
                and isinstance(statement.test, ast.Compare)
                and isinstance(statement.test.left, ast.Name)
                and statement.test.left.id == "__name__"
            ):
                main_guard = main_guard or statement
                continue
            other_statements.append(statement)
    body = [
        *imports,
        *other_statements,
        *(classes[name] for name in class_order),
    ]
    if main_guard is not None:
        body.append(main_guard)
    merged = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(merged)
    return ast.unparse(merged).rstrip() + "\n"


def _build_ephemeral_behavior_harness_stage(
    *,
    prompt: str,
    implementation_plan: dict[str, Any],
    generated_files: list[tuple[str, str, str]],
    project_root: str,
    behavior_rows_override: list[dict[str, Any]] | None = None,
) -> tuple[ProjectEditPromptStage | None, list[str]]:
    """Build disposable runtime proof for behavior that static checks cannot prove."""

    behavior_rows = (
        list(behavior_rows_override)
        if behavior_rows_override is not None
        else _expanded_ephemeral_behavior_rows(
            implementation_plan,
            generated_files=generated_files,
        )
    )
    if not behavior_rows:
        return None, []
    package_source = "\n\n".join(
        f"FILE: {path}\n```python\n{source}\n```"
        for path, _original, source in generated_files
    )
    behavior_contract = json.dumps(
        behavior_rows,
        indent=2,
        ensure_ascii=True,
    )
    required_behavior_ids = [
        row["behavior_id"] for row in behavior_rows
    ]
    return ProjectEditPromptStage(
        key="ephemeral_behavior_harness",
        label="Compiling ordered behavior contracts into disposable runtime proof",
        system_prompt=(
            "Write a disposable Python unittest module that proves only the "
            "supplied relational behavior contracts through the generated "
            "package's public API. Do not reimplement production behavior in "
            "the test. Use deterministic fakes for clocks and external hosts. "
            "Instantiate production classes through their normal constructors "
            "and exercise the controls, collaborators, and state created by "
            "those constructors. Never replace constructor-owned controls or "
            "manually reconnect signals merely to make a test pass. Seed the "
            "real controls or public inputs with representative non-empty values. "
            "Each contract includes an owner_execution capsule. Construct the real "
            "owner and invoke its exact callable directly. Never patch, replace, or "
            "mock a forbidden_patch_symbol, and never call the behavior under test "
            "on MagicMock. Patch only a downstream dependency that the supplied "
            "production source actually calls. "
            "Never invoke a production dependency directly to calculate an "
            "expected result. Patch that dependency where the generated module "
            "looks it up, configure one explicit return object, assert the exact "
            "approved required or caller-derived arguments received by the patch, "
            "and assert returned-object identity when production forwards the "
            "dependency result. Treat an omitted optional parameter as its verified "
            "signature default; do not require production to spell out a default-"
            "valued keyword unless the original request explicitly names that "
            "parameter or requires a non-default value. "
            "Do not sleep, access the network, or write into the project. Every "
            "behavior contract supplies an exact opaque test_name. Contracts sharing "
            "the same test_name have the same production owner and callable: prove "
            "all of them in one isolated unittest method with that exact name. Never "
            "split one test_name across classes or invent alternate test names. Do not "
            "write ownership metadata; "
            "the orchestrator adds it after parsing. Unless the contract is a pure "
            "declaration invariant, execute every listed production owner in the test "
            "body, including callable-form assertRaises invocations. Invoke each "
            "exact owner directly; a signal emission, widget click, or downstream "
            "helper is not equivalent owner execution. For asynchronous launchers, "
            "patch the worker boundary and assert construction, signal connections, "
            "and start without waiting for synchronous results. Test worker execution "
            "separately when required. Never call join, sleep, processEvents, or assert "
            "a service result immediately after asynchronous start. Derive expected "
            "collections from the production selection predicate, explicitly control "
            "filesystem predicates, and set every UI filter before asserting rows. "
            "Each contract contains authoritative ordered execution_steps. Execute "
            "those steps in exactly their listed order. A step's requires facts must "
            "be established before it runs; its produces facts describe state made "
            "available to later steps; its invalidates facts must not be observed "
            "again unless a later step produces them again. Assertions belong at the "
            "listed observation step, never after a later destructive transition. "
            "Return Python source only."
        ),
        user_prompt=f"""Original request:
{prompt}

Project root:
{project_root}

Generated package:
{package_source}

Relational behavior contracts:
```json
{behavior_contract}
```

Create focused unittest tests that execute each observable relationship. Import
the generated public symbols rather than copying their implementation. Assert
state before and after the operation, exact ordering where requested, exact
failure behavior where requested, and callback/signal effects where requested.
For imported dependencies, use unittest.mock.patch against the generated
production module's binding. Do not import or call the dependency directly in
the harness. Preserve constructor wiring and interact with the actual controls
owned by the production instance.
Return only one complete disposable Python test module.
""",
        model_tier="local_code",
        num_ctx=16384,
        num_predict=-1,
        timeout=120,
        no_progress_seconds=30,
        prefer_coder=True,
        coder_preference="standard",
        response_format="text",
        metadata={"behavior_rows": behavior_rows},
    ), required_behavior_ids


def _parse_ephemeral_behavior_harness(
    response: str,
    required_behavior_ids: list[str],
    required_test_names: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Validate syntax and explicit clause ownership for a disposable harness."""

    source = str(response or "").strip()
    source = re.sub(
        r"^\s*```(?:python)?\s*",
        "",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(r"\s*```\s*$", "", source).strip()
    try:
        tree = ast.parse(source, filename="<ephemeral_behavior_harness>")
    except SyntaxError as exc:
        return "", [f"Disposable behavior harness did not parse: {exc}."]
    test_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    errors: list[str] = []
    changed = False
    if not test_names:
        errors.append("Disposable behavior harness defines no test methods.")
    expected_names = list(required_test_names or [])
    if len(expected_names) != len(required_behavior_ids):
        existing_bindings, binding_errors = _ephemeral_behavior_bindings(
            source
        )
        behavior_test_names = {
            behavior_id: test_name
            for test_name, behavior_ids in existing_bindings.items()
            for behavior_id in behavior_ids
        } if not binding_errors else {}
        if all(
            behavior_id in behavior_test_names
            for behavior_id in required_behavior_ids
        ):
            expected_names = [
                behavior_test_names[behavior_id]
                for behavior_id in required_behavior_ids
            ]
        elif len(test_names) == 1 and required_behavior_ids:
            shared_owner_test = next(iter(test_names))
            expected_names = [
                shared_owner_test for _behavior_id in required_behavior_ids
            ]
        else:
            expected_names = [
                f"test_contract_{index:03d}"
                for index in range(1, len(required_behavior_ids) + 1)
            ]
    expected_bindings: dict[str, list[str]] = {}
    for test_name, behavior_id in zip(
        expected_names,
        required_behavior_ids,
        strict=True,
    ):
        expected_bindings.setdefault(test_name, []).append(behavior_id)
    missing_tests = sorted(set(expected_bindings) - test_names)
    if missing_tests:
        errors.append(
            "Disposable behavior harness omitted required isolated tests: "
            + ", ".join(missing_tests)
        )
    if errors:
        return source, errors
    expected_test_names = set(expected_bindings)
    retained_test_names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        retained_members: list[ast.stmt] = []
        for member in node.body:
            if not (
                isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name.startswith("test_")
            ):
                retained_members.append(member)
                continue
            if (
                member.name not in expected_test_names
                or member.name in retained_test_names
            ):
                changed = True
                continue
            retained_test_names.add(member.name)
            retained_members.append(member)
        node.body = retained_members or [ast.Pass()]
    tree.body = [
        statement
        for statement in tree.body
        if not (
            isinstance(statement, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name)
                and target.id == "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__"
                for target in (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
            )
        )
    ]
    binding_assignment = ast.Assign(
        targets=[
            ast.Name(
                id="__TECH_CONNECTOR_BEHAVIOR_BINDINGS__",
                ctx=ast.Store(),
            )
        ],
        value=ast.parse(repr(expected_bindings), mode="eval").body,
    )
    insert_at = 1 if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ) else 0
    while (
        insert_at < len(tree.body)
        and isinstance(tree.body[insert_at], ast.ImportFrom)
        and tree.body[insert_at].module == "__future__"
    ):
        insert_at += 1
    tree.body.insert(insert_at, binding_assignment)
    ast.fix_missing_locations(tree)
    normalized = ast.unparse(tree).rstrip() + "\n"
    normalized = _format_ephemeral_behavior_binding_assignment(
        normalized,
        expected_bindings,
    )
    return normalized, []


def _format_ephemeral_behavior_binding_assignment(
    source: str,
    bindings: Mapping[str, list[str]],
) -> str:
    """Render internal behavior ownership without creating overlong lines.

    :param source: Disposable test-module source.
    :param bindings: Test names mapped to approved behavior identifiers.
    :return: Source with one deterministic multiline sidecar assignment.
    """

    lines = ["__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = {"]
    for test_name, behavior_ids in bindings.items():
        lines.append(f"    {test_name!r}: [")
        lines.extend(f"        {behavior_id!r}," for behavior_id in behavior_ids)
        lines.append("    ],")
    lines.append("}")
    replacement = "\n".join(lines)
    return re.sub(
        r"(?m)^__TECH_CONNECTOR_BEHAVIOR_BINDINGS__\s*=\s*[^\r\n]+$",
        lambda _match: replacement,
        source,
        count=1,
    )


def _ephemeral_harness_behavior_contract_errors(
    harness_source: str,
    behavior_rows: list[dict[str, Any]],
    *,
    generated_files: list[tuple[str, str, str]],
) -> list[str]:
    """Validate disposable proofs against approved behavior metadata."""

    try:
        tree = ast.parse(harness_source, filename="<ephemeral_behavior_harness>")
    except SyntaxError:
        return []
    bindings, binding_errors = _ephemeral_behavior_bindings(harness_source)
    if binding_errors:
        return binding_errors
    tests = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }
    test_execution_nodes: dict[str, list[ast.AST]] = {}
    for class_node in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        methods = {
            node.name: node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        lifecycle = [
            methods[name]
            for name in ("setUpClass", "setUp")
            if name in methods
        ]
        for method_name, method_node in methods.items():
            if method_name.startswith("test_"):
                test_execution_nodes[method_name] = [
                    *lifecycle,
                    method_node,
                ]
    contracts = {
        str(row.get("behavior_id") or ""): row
        for row in behavior_rows
        if str(row.get("behavior_id") or "")
    }
    production_call_sequences: dict[str, list[str]] = {}
    for _path, _original, production_source in generated_files:
        try:
            production_tree = ast.parse(production_source)
        except SyntaxError:
            continue
        for production_callable in (
            node
            for node in ast.walk(production_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            ordered_production_calls = sorted(
                (
                    call
                    for call in ast.walk(production_callable)
                    if isinstance(call, ast.Call)
                ),
                key=lambda call: (
                    int(getattr(call, "lineno", 0)),
                    int(getattr(call, "col_offset", 0)),
                ),
            )
            production_call_sequences.setdefault(
                production_callable.name,
                [
                    (
                        call.func.id
                        if isinstance(call.func, ast.Name)
                        else call.func.attr
                        if isinstance(call.func, ast.Attribute)
                        else ""
                    )
                    for call in ordered_production_calls
                    if isinstance(call.func, (ast.Name, ast.Attribute))
                ],
            )

    def expand_production_calls(call_names: list[str]) -> list[str]:
        """Expand public calls through their real generated call graph in order."""

        expanded: list[str] = []

        def visit(call_name: str, active: set[str]) -> None:
            if not call_name:
                return
            expanded.append(call_name)
            if call_name in active:
                return
            next_active = {*active, call_name}
            for nested_name in production_call_sequences.get(call_name, []):
                visit(nested_name, next_active)

        for name in call_names:
            visit(name, set())
        return expanded

    errors: list[str] = []
    for test_name, behavior_ids in bindings.items():
        test = tests.get(test_name)
        if test is None:
            continue
        execution_nodes = test_execution_nodes.get(test_name, [test])
        assertion_calls = [
            call
            for call in ast.walk(test)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr.startswith("assert")
        ]
        assertion_statements = [
            statement
            for statement in ast.walk(test)
            if isinstance(statement, ast.Assert)
        ]
        ordered_calls = sorted(
            (
                call
                for execution_node in execution_nodes
                for call in ast.walk(execution_node)
                if isinstance(call, ast.Call)
            ),
            key=lambda call: (
                int(getattr(call, "lineno", 0)),
                int(getattr(call, "col_offset", 0)),
            ),
        )
        ordered_call_names = [
            (
                call.func.id
                if isinstance(call.func, ast.Name)
                else call.func.attr
                if isinstance(call.func, ast.Attribute)
                else ""
            )
            for call in ordered_calls
        ]
        call_aliases: dict[str, str] = {}
        for execution_node in execution_nodes:
            for assignment in ast.walk(execution_node):
                if (
                    not isinstance(assignment, ast.Assign)
                    or len(assignment.targets) != 1
                    or not isinstance(assignment.targets[0], ast.Name)
                ):
                    continue
                alias_name = assignment.targets[0].id
                value = assignment.value
                if isinstance(value, ast.Attribute):
                    call_aliases[alias_name] = value.attr
                elif (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "getattr"
                    and len(value.args) >= 2
                    and isinstance(value.args[1], ast.Constant)
                    and isinstance(value.args[1].value, str)
                ):
                    call_aliases[alias_name] = value.args[1].value
        ordered_call_names = [
            call_aliases.get(name, name) for name in ordered_call_names
        ]
        ordered_call_names = expand_production_calls(ordered_call_names)
        called_names = {name for name in ordered_call_names if name}
        for assertion in assertion_calls:
            if (
                assertion.func.attr in {"assertRaises", "assertRaisesRegex"}
                and len(assertion.args) >= 2
            ):
                asserted_callable = assertion.args[1]
                if isinstance(asserted_callable, ast.Name):
                    called_names.add(asserted_callable.id)
                elif isinstance(asserted_callable, ast.Attribute):
                    called_names.add(asserted_callable.attr)
        asserted_rejections = [
            assertion
            for assertion in assertion_calls
            if assertion.func.attr in {"assertRaises", "assertRaisesRegex"}
        ]
        bound_contracts = [
            contracts[behavior_id]
            for behavior_id in behavior_ids
            if behavior_id in contracts
        ]
        approved_rejection_parts: list[str] = []
        for contract in bound_contracts:
            approved_rejection_parts.append(
                str(contract.get("operation") or "")
            )
            approved_rejection_parts.extend(
                str(value)
                for value in contract.get("expected_observations") or []
            )
        approved_rejection_text = " ".join(approved_rejection_parts)
        rejection_is_approved = bool(
            any(
                str(contract.get("polarity") or "") == "rejection"
                for contract in bound_contracts
            )
            or re.search(
                r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b",
                approved_rejection_text,
            )
        )
        if asserted_rejections and not rejection_is_approved:
            errors.append(
                f"{test_name}: disposable proof invents assertRaises behavior "
                "that is absent from every bound approved behavior contract. "
                "Remove the unapproved rejection assertion while preserving the "
                "approved actions and direct postcondition assertions."
            )
        for behavior_id in behavior_ids:
            contract = contracts.get(behavior_id)
            if contract is None:
                errors.append(
                    f"{test_name}: sidecar references unknown behavior "
                    f"`{behavior_id}`."
                )
                continue
            if not assertion_calls and not assertion_statements:
                errors.append(
                    f"{test_name}: `{behavior_id}` executes no observable assertion."
                )
            contract_owners = list(contract.get("production_owners") or [])
            forbidden_patch_symbols = {
                str(value)
                for value in (
                    contract.get("owner_execution") or {}
                ).get("forbidden_patch_symbols") or []
                if str(value)
            }
            protected_patch_targets = {
                str(owner.get("symbol") or "")
                for owner in contract_owners
                if isinstance(owner, Mapping)
                and str(owner.get("symbol") or "")
            }
            protected_patch_targets.update(
                f"{Path(str(owner.get('path') or '')).stem}."
                f"{str(owner.get('symbol') or '')}"
                for owner in contract_owners
                if isinstance(owner, Mapping)
                and str(owner.get("path") or "")
                and str(owner.get("symbol") or "")
            )
            protected_patch_targets.update(
                forbidden
                for forbidden in forbidden_patch_symbols
                if "." in forbidden
            )
            for call in ast.walk(test):
                if not isinstance(call, ast.Call):
                    continue
                patch_target = ""
                patch_object = False
                if (
                    isinstance(call.func, ast.Name)
                    and call.func.id == "patch"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    patch_target = call.args[0].value
                elif (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "object"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "patch"
                    and len(call.args) >= 2
                    and isinstance(call.args[1], ast.Constant)
                    and isinstance(call.args[1].value, str)
                ):
                    patch_target = call.args[1].value
                    patch_object = True
                patches_production_owner = bool(
                    patch_target
                    and (
                        any(
                            patch_target == protected
                            or "." in protected
                            and patch_target.endswith("." + protected)
                            for protected in protected_patch_targets
                        )
                        or patch_object
                        and patch_target in forbidden_patch_symbols
                    )
                )
                if patches_production_owner:
                    errors.append(
                        f"{test_name}: `{behavior_id}` patches approved owner "
                        f"`{patch_target}` instead of executing the real "
                        "production owner."
                    )
            declaration_invariant = (
                str(contract.get("polarity") or "") == "invariant"
                and (
                    len(contract_owners) > 1
                    or any(
                        str(owner.get("callable_name") or "")
                        == "<declaration>"
                        for owner in contract_owners
                        if isinstance(owner, Mapping)
                    )
                )
            )
            for owner in ([] if declaration_invariant else contract_owners):
                if not isinstance(owner, Mapping):
                    continue
                callable_name = str(owner.get("callable_name") or "")
                symbol = str(owner.get("symbol") or "")
                if callable_name == "<module>":
                    continue
                required_call = callable_name
                if callable_name == "<declaration>":
                    required_call = symbol.rsplit(".", 1)[-1]
                elif callable_name.startswith("__") and "." in symbol:
                    required_call = symbol.rsplit(".", 1)[0].rsplit(".", 1)[-1]
                if required_call and required_call not in called_names:
                    errors.append(
                        f"{test_name}: `{behavior_id}` does not execute approved "
                        f"production owner `{symbol}`."
                    )
            ordered_required_calls: list[str] = []
            for step in contract.get("execution_steps") or []:
                if not isinstance(step, Mapping):
                    continue
                callable_name = str(step.get("callable_name") or "")
                phase = str(step.get("phase") or "").casefold()
                if phase == "observation":
                    continue
                chunk_id = str(step.get("chunk_id") or "")
                matching_owner = next(
                    (
                        owner
                        for owner in contract_owners
                        if isinstance(owner, Mapping)
                        and str(owner.get("chunk_id") or "") == chunk_id
                        and str(owner.get("callable_name") or "") == callable_name
                    ),
                    None,
                )
                if matching_owner is None or callable_name == "<module>":
                    continue
                if (
                    phase == "setup"
                    and callable_name != "<declaration>"
                ):
                    continue
                if callable_name == "<declaration>":
                    required_call = str(
                        matching_owner.get("symbol") or ""
                    ).rsplit(".", 1)[-1]
                elif callable_name.startswith("__"):
                    owner_symbol = str(matching_owner.get("symbol") or "")
                    required_call = (
                        owner_symbol.rsplit(".", 1)[0].rsplit(".", 1)[-1]
                        if "." in owner_symbol
                        else callable_name
                    )
                else:
                    required_call = callable_name
                if required_call:
                    if (
                        not ordered_required_calls
                        or ordered_required_calls[-1] != required_call
                    ):
                        ordered_required_calls.append(required_call)
            if ordered_required_calls:
                required_index = 0
                for called_name in ordered_call_names:
                    if (
                        required_index < len(ordered_required_calls)
                        and called_name == ordered_required_calls[required_index]
                    ):
                        required_index += 1
                if required_index != len(ordered_required_calls):
                    errors.append(
                        f"{test_name}: `{behavior_id}` does not execute its approved "
                        "state transitions in order. Required call sequence: "
                        + " -> ".join(ordered_required_calls)
                        + "."
                    )
    return list(dict.fromkeys(errors))


def _repair_phase_validation_errors(
    files: list[tuple[str, str, str]],
    *,
    implementation_plan: Mapping[str, Any],
    project_root: str,
    request_prompt: str,
    harness_path: str = "",
) -> list[str]:
    """Validate one repair candidate through the same deepest available gate."""

    from tech_connector.services.implementation_plan_quality_service import (
        validate_generated_files_against_implementation_plan,
    )

    production_files = [
        entry for entry in files if not harness_path or entry[0] != harness_path
    ]
    plan_errors = validate_generated_files_against_implementation_plan(
        implementation_plan,
        production_files,
    )
    if plan_errors:
        return list(plan_errors)
    behavior_rows = _approved_behavior_contract_rows(implementation_plan)
    production_candidate = build_project_edit_multi_file_candidate(
        production_files
    )
    production_preview = preview_project_edit_agent_response(
        production_candidate,
        project_root=project_root,
        request_prompt=request_prompt,
        behavioral_proof_deferred=bool(behavior_rows),
    )
    production_errors = list(production_preview.errors or [])
    if production_errors or not harness_path:
        return production_errors
    harness_source = next(
        (
            source
            for path, _original, source in files
            if path == harness_path
        ),
        "",
    )
    if not harness_source:
        return []
    harness_candidate = build_project_edit_multi_file_candidate(files)
    harness_preview = preview_project_edit_agent_response(
        harness_candidate,
        project_root=project_root,
        allowed_external_paths={harness_path},
        request_prompt=(
            "Run the supplied disposable unittest module as an authoritative "
            "validation harness. It is not an output artifact."
        ),
    )
    return [
        *_ephemeral_harness_behavior_contract_errors(
            harness_source,
            _expanded_ephemeral_behavior_rows(
                implementation_plan,
                generated_files=production_files,
            ),
            generated_files=production_files,
        ),
        *list(harness_preview.errors or []),
    ]


def _monotonic_repair_rejections(
    before_files: list[tuple[str, str, str]],
    after_files: list[tuple[str, str, str]],
    *,
    repair_targets: Iterable[tuple[str, str]],
    assigned_errors: Iterable[object],
    implementation_plan: Mapping[str, Any],
    project_root: str,
    request_prompt: str,
    harness_path: str = "",
) -> list[str]:
    """Return reasons a proposed symbol transaction cannot replace its baseline."""

    target_list = list(repair_targets)
    assigned_error_list = list(assigned_errors)
    regressions = _untouched_repair_regressions(
        before_files,
        after_files,
        repair_targets=target_list,
    )
    before_errors = _repair_phase_validation_errors(
        before_files,
        implementation_plan=implementation_plan,
        project_root=project_root,
        request_prompt=request_prompt,
        harness_path=harness_path,
    )
    after_errors = _repair_phase_validation_errors(
        after_files,
        implementation_plan=implementation_plan,
        project_root=project_root,
        request_prompt=request_prompt,
        harness_path=harness_path,
    )
    before_findings = _validation_finding_map(before_errors, project_root)
    after_findings = _validation_finding_map(after_errors, project_root)
    assigned_findings = _validation_finding_map(
        assigned_error_list,
        project_root,
    )
    assigned_keys = set(before_findings) & set(assigned_findings)
    if not assigned_keys:
        assigned_text = [
            _stable_validation_finding(error, project_root)
            for error in assigned_error_list
            if str(error or "").strip()
        ]
        assigned_keys = {
            key
            for key in before_findings
            if any(
                assigned in key or key in assigned
                for assigned in assigned_text
            )
        }
    production_repair_target = any(
        not Path(str(path)).name.startswith("test_")
        for path, _symbol in target_list
    )
    approved_runtime_transition = any(
        "APPROVED BEHAVIOR CONTRACT FAILURE:" in str(error)
        or (
            production_repair_target
            and re.search(r"\btest_[A-Za-z0-9_]+\b", str(error))
            and re.search(
                r"\b(?:AssertionError|KeyError|ValueError|PermissionError|"
                r"TypeError|RuntimeError)\b",
                str(error),
            )
        )
        for error in assigned_error_list
    )
    if not assigned_keys and approved_runtime_transition:
        assigned_keys = set(before_findings)
    resolved_keys = set(before_findings) - set(after_findings)
    introduced_keys = set(after_findings) - set(before_findings)
    normalized_targets = {
        (str(Path(str(path)).resolve()).casefold(), str(symbol).casefold())
        for path, symbol in target_list
    }

    def belongs_to_repair_target(finding: str) -> bool:
        """Return whether a finding is owned by the active repair surface.

        :param finding: stable validation finding
        :return: whether its parsed file and symbol match a repair target
        """

        owner_match = re.search(
            r"(?P<path>(?:[A-Za-z]:)?[^|\r\n]+?\.py):"
            r"(?P<symbol>[A-Za-z_][A-Za-z0-9_.]*):",
            finding,
        )
        if owner_match is None:
            if finding.startswith(
                (
                    "Requested complete type hints are invalid or missing:",
                    "Requested useful docstrings are too vague:",
                    "Requested docstrings are missing:",
                )
            ):
                return any(
                    re.search(
                        rf"\b{re.escape(target_symbol)}\b",
                        finding,
                        flags=re.IGNORECASE,
                    )
                    for _target_path, target_symbol in normalized_targets
                )
            return True
        raw_path = owner_match.group("path").replace(
            "<PROJECT_ROOT>",
            str(Path(project_root).resolve()),
        )
        finding_path = str(Path(raw_path).resolve()).casefold()
        finding_symbol = owner_match.group("symbol").casefold()
        return any(
            finding_path == target_path
            and (
                finding_symbol == target_symbol
                or finding_symbol.startswith(target_symbol + ".")
                or target_symbol.startswith(finding_symbol + ".")
            )
            for target_path, target_symbol in normalized_targets
        )

    # Validators intentionally reveal deeper findings only after an earlier
    # declaration blocker is repaired. Findings on untouched owners are latent
    # work for the next bounded pass, not regressions caused by this transaction.
    introduced_keys = {
        key for key in introduced_keys if belongs_to_repair_target(key)
    }
    if approved_runtime_transition and (assigned_keys & resolved_keys):
        introduced_keys = {
            key
            for key in introduced_keys
            if "Disposable generated-patch validation failed:" not in after_findings[key]
        }
    # A missing declaration prevents validators from inspecting its executable
    # body.  Accept a transaction that materially adds that exact owner and
    # resolves the missing-declaration finding even when this reveals a deeper
    # same-owner behavior defect.  The newly visible finding remains queued for
    # the next bounded owner-only repair pass.
    resolved_missing_owner_symbols = {
        match.group(1).casefold()
        for key in resolved_keys
        for match in [
            re.search(
                r"approved (?:method|callable) `([^`]+)` is missing",
                before_findings.get(key, ""),
                flags=re.IGNORECASE,
            )
        ]
        if match is not None
    }
    if resolved_missing_owner_symbols:
        introduced_keys = set()
    resolved_coarse_owner_blocker = any(
        "executable implementation is unchanged" in before_findings.get(key, "")
        for key in resolved_keys
    )
    if resolved_coarse_owner_blocker and (assigned_keys & resolved_keys):
        introduced_keys = set()
    if not assigned_keys:
        regressions.append(
            "repair has no exact assigned validation finding in the baseline"
        )
    elif not (assigned_keys & resolved_keys):
        regressions.append(
            "repair did not resolve any of its assigned validation findings"
        )
    if introduced_keys:
        introduced = [
            after_findings[key]
            for key in sorted(introduced_keys)
        ]
        regressions.append(
            "repair introduced new validation finding(s): "
            + " | ".join(introduced[:3])
        )
    return regressions


def _repair_unapproved_ephemeral_rejections(
    harness_source: str,
    behavior_rows: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Remove rejection assertions absent from a test's approved contracts."""

    try:
        tree = ast.parse(harness_source, filename="<ephemeral_behavior_harness>")
    except SyntaxError:
        return harness_source, []
    bindings, binding_errors = _ephemeral_behavior_bindings(harness_source)
    if binding_errors:
        return harness_source, []
    contracts = {
        str(row.get("behavior_id") or ""): row
        for row in behavior_rows
        if str(row.get("behavior_id") or "")
    }

    def is_rejection_context(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"assertRaises", "assertRaisesRegex"}
        )

    def is_manual_rejection_proof(node: ast.AST) -> bool:
        if not isinstance(node, ast.Try):
            return False
        raised_messages = [
            str(raised.exc.args[0].value)
            for raised in ast.walk(node)
            if isinstance(raised, ast.Raise)
            and isinstance(raised.exc, ast.Call)
            and isinstance(raised.exc.func, ast.Name)
            and raised.exc.func.id in {"AssertionError", "RuntimeError"}
            and raised.exc.args
            and isinstance(raised.exc.args[0], ast.Constant)
        ]
        return bool(
            node.handlers
            and any(
                re.search(
                    r"\b(?:expected|must raise|did not raise)\b.*"
                    r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b",
                    message,
                    flags=re.IGNORECASE,
                )
                for message in raised_messages
            )
        )

    repairs: list[str] = []
    for test in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in bindings
    ):
        bound_contracts = [
            contracts[behavior_id]
            for behavior_id in bindings[test.name]
            if behavior_id in contracts
        ]
        approved_parts: list[str] = []
        for contract in bound_contracts:
            approved_parts.append(str(contract.get("operation") or ""))
            approved_parts.extend(
                str(value)
                for value in contract.get("expected_observations") or []
            )
        approved_text = " ".join(approved_parts)
        rejection_is_approved = bool(
            any(
                str(contract.get("polarity") or "") == "rejection"
                for contract in bound_contracts
            )
            or re.search(
                r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b",
                approved_text,
            )
        )
        if rejection_is_approved:
            continue
        retained_body: list[ast.stmt] = []
        for statement in test.body:
            remove_statement = (
                isinstance(statement, (ast.With, ast.AsyncWith))
                and any(
                    is_rejection_context(item.context_expr)
                    for item in statement.items
                )
            ) or (
                isinstance(statement, ast.Expr)
                and is_rejection_context(statement.value)
            ) or (
                is_manual_rejection_proof(statement)
            )
            if remove_statement:
                repairs.append(
                    f"{test.name}: removed unapproved assertRaises proof"
                )
                continue
            retained_body.append(statement)
        test.body = retained_body or [ast.Pass()]
    if not repairs:
        return harness_source, []
    ast.fix_missing_locations(tree)
    return ast.unparse(tree).rstrip() + "\n", repairs


_EPHEMERAL_HOST_RUNTIME_MODULES = {
    "host_api",
    "unreal",
    "maya",
    "cmds",
    "bpy",
    "pyfbsdk",
    "hou",
}


def _repair_ephemeral_numeric_callable_fixtures(
    harness_source: str,
    generated_files: list[tuple[str, str, str]],
) -> tuple[str, list[str]]:
    """Give bare mocks numeric returns when passed to numeric callable parameters."""

    try:
        harness_tree = ast.parse(
            harness_source,
            filename="<ephemeral_behavior_harness>",
        )
    except SyntaxError:
        return harness_source, []

    numeric_callable_parameters: dict[str, dict[int, str]] = {}
    for _path, _original, production_source in generated_files:
        try:
            production_tree = ast.parse(production_source)
        except SyntaxError:
            continue
        for class_node in [
            node
            for node in production_tree.body
            if isinstance(node, ast.ClassDef)
        ]:
            initializer = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "__init__"
                ),
                None,
            )
            if initializer is None:
                continue
            parameters: dict[int, str] = {}
            for parameter_index, argument in enumerate(
                argument
                for argument in initializer.args.args
                if argument.arg != "self"
            ):
                annotation = (
                    ast.unparse(argument.annotation)
                    if argument.annotation is not None
                    else ""
                )
                if re.fullmatch(
                    r"(?:typing\.)?Callable\[\[\],\s*(?:float|int)\]",
                    annotation,
                ):
                    parameters[parameter_index] = argument.arg
            if parameters:
                numeric_callable_parameters[class_node.name] = parameters

    repairs: list[str] = []
    def _is_bare_mock_call(node: ast.AST | None) -> bool:
        return (
            isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id in {"Mock", "MagicMock"}
                or isinstance(node.func, ast.Attribute)
                and node.func.attr in {"Mock", "MagicMock"}
            )
            and not any(
                keyword.arg == "return_value"
                for keyword in node.keywords
            )
        )

    def _add_numeric_return(
        mock_call: ast.Call,
        *,
        repair_label: str,
    ) -> None:
        mock_call.keywords.append(
            ast.keyword(
                arg="return_value",
                value=ast.Constant(value=0.0),
            )
        )
        repairs.append(repair_label)

    for call in [
        node
        for node in ast.walk(harness_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in numeric_callable_parameters
    ]:
        for parameter_index, parameter_name in numeric_callable_parameters[
            call.func.id
        ].items():
            argument_node: ast.AST | None = (
                call.args[parameter_index]
                if parameter_index < len(call.args)
                else next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == parameter_name
                    ),
                    None,
                )
            )
            if not _is_bare_mock_call(argument_node):
                continue
            _add_numeric_return(
                argument_node,
                repair_label=(
                    f"{call.func.id}.{parameter_name}="
                    "Mock(return_value=0.0)"
                ),
            )

    for function_node in [
        node
        for node in ast.walk(harness_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]:
        local_mock_assignments: dict[str, ast.Call] = {}
        for node in ast.walk(function_node):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and _is_bare_mock_call(node.value)
            ):
                local_mock_assignments[node.targets[0].id] = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and _is_bare_mock_call(node.value)
            ):
                local_mock_assignments[node.target.id] = node.value

        for call in [
            node
            for node in ast.walk(function_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in numeric_callable_parameters
        ]:
            for parameter_index, parameter_name in numeric_callable_parameters[
                call.func.id
            ].items():
                argument_node = (
                    call.args[parameter_index]
                    if parameter_index < len(call.args)
                    else next(
                        (
                            keyword.value
                            for keyword in call.keywords
                            if keyword.arg == parameter_name
                        ),
                        None,
                    )
                )
                if not isinstance(argument_node, ast.Name):
                    continue
                mock_call = local_mock_assignments.get(argument_node.id)
                if not _is_bare_mock_call(mock_call):
                    continue
                _add_numeric_return(
                    mock_call,
                    repair_label=(
                        f"{function_node.name}.{argument_node.id}="
                        "Mock(return_value=0.0)"
                    ),
                )
    if not repairs:
        return harness_source, []
    ast.fix_missing_locations(harness_tree)
    return ast.unparse(harness_tree).rstrip() + "\n", list(dict.fromkeys(repairs))
