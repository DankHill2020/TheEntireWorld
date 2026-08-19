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
    _checkpoint_hash,
)

from tech_connector.services.project_edit_workflow_part_06 import (
    _EPHEMERAL_HOST_RUNTIME_MODULES,
    _ephemeral_behavior_bindings,
)


def _ephemeral_harness_call_graph_errors(
    harness_source: str,
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> list[str]:
    """Reject disposable fixtures that do not mirror production host boundaries."""

    try:
        harness_tree = ast.parse(
            harness_source,
            filename="<ephemeral_behavior_harness>",
        )
    except SyntaxError:
        return []

    def dotted_name(node: ast.AST) -> str:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    production_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    production_function_modules: dict[str, str] = {}
    connected_methods: set[str] = set()
    for _path, _original, production_source in generated_files:
        try:
            production_tree = ast.parse(production_source)
        except SyntaxError:
            continue
        for node in ast.walk(production_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                production_functions.setdefault(node.name, node)
                production_function_modules.setdefault(
                    node.name,
                    Path(_path).stem,
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and node.args
            ):
                connected_name = dotted_name(node.args[0])
                if connected_name.startswith("self."):
                    connected_methods.add(connected_name.split(".", 1)[1])

    host_roots = set(_EPHEMERAL_HOST_RUNTIME_MODULES)
    errors: list[str] = []
    requires_existing_file = bool(
        re.search(
            r"\b(?:require|requires|required|requiring)\b"
            r"[^.!?\n]{0,80}\bexisting\b[^.!?\n]{0,40}\bfile\b",
            request_prompt,
            flags=re.IGNORECASE,
        )
    )
    for test_node in (
        node
        for node in ast.walk(harness_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ):
        called_production = {
            node.func.id
            for node in ast.walk(test_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in production_functions
        }
        patched_connected_slots = sorted(
            slot_name
            for node in ast.walk(test_node)
            if isinstance(node, ast.Call)
            and dotted_name(node.func).endswith("patch.object")
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            for slot_name in [node.args[1].value]
            if slot_name in connected_methods
        )
        if patched_connected_slots:
            errors.append(
                f"{test_node.name}: do not patch construction-connected slots "
                "after the signal is wired; patch the imported backend callable "
                "and assert public widget/status behavior instead: "
                + ", ".join(patched_connected_slots)
            )
        if not called_production:
            continue
        patch_paths = {
            argument.value
            for node in ast.walk(test_node)
            if isinstance(node, ast.Call)
            and dotted_name(node.func).split(".")[-1] in {"patch", "object"}
            for argument in node.args[:1]
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
        }
        patch_paths.update(
            argument.value
            for decorator in test_node.decorator_list
            if isinstance(decorator, ast.Call)
            and dotted_name(decorator.func).split(".")[-1] in {"patch", "object"}
            for argument in decorator.args[:1]
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
        )
        for callable_name in sorted(called_production):
            production_node = production_functions[callable_name]
            direct_host_calls = {
                path
                for call in ast.walk(production_node)
                if isinstance(call, ast.Call)
                for path in [dotted_name(call.func)]
                if path.split(".", 1)[0] in host_roots
            }
            local_import_roots = {
                alias.asname or alias.name.split(".", 1)[0]
                for import_node in ast.walk(production_node)
                if isinstance(import_node, ast.Import)
                for alias in import_node.names
            }
            production_module = production_function_modules.get(
                callable_name,
                "",
            )
            for host_call in sorted(direct_host_calls):
                if host_call.split(".", 1)[0] not in local_import_roots:
                    continue
                overqualified_suffix = f"{production_module}.{host_call}"
                overqualified = sorted(
                    patch_path
                    for patch_path in patch_paths
                    if production_module
                    and patch_path.endswith(overqualified_suffix)
                )
                if overqualified:
                    errors.append(
                        f"{test_node.name}: function-local host imports must be "
                        f"patched at `{host_call}`, not through the production "
                        "module: " + ", ".join(overqualified)
                    )
            patched_subject_paths = sorted(
                patch_path
                for patch_path in patch_paths
                if patch_path.rsplit(".", 1)[-1] == callable_name
                and not any(
                    patch_path == host_call
                    or patch_path.endswith("." + host_call)
                    for host_call in direct_host_calls
                )
            )
            if patched_subject_paths:
                errors.append(
                    f"{test_node.name}: never patch the public callable under "
                    f"test `{callable_name}`; invoke production and patch only "
                    "its external dependencies: "
                    + ", ".join(patched_subject_paths)
                )
            missing_patches = sorted(
                path
                for path in direct_host_calls
                if not any(
                    patch_path == path
                    or patch_path.endswith("." + path)
                    for patch_path in patch_paths
                )
            )
            if missing_patches:
                errors.append(
                    f"{test_node.name}: patch every direct host boundary used by "
                    f"{callable_name}; missing exact paths: "
                    + ", ".join(missing_patches)
                )
            returned_host_paths: set[str] = set()
            assignments = {
                target.id: dotted_name(value.func)
                for value_node in ast.walk(production_node)
                if isinstance(value_node, ast.Assign)
                and len(value_node.targets) == 1
                and isinstance(value_node.targets[0], ast.Name)
                and isinstance(value_node.value, ast.Call)
                for target, value in [
                    (value_node.targets[0], value_node.value)
                ]
                if dotted_name(value.func).split(".", 1)[0] in host_roots
            }
            for return_node in ast.walk(production_node):
                if (
                    isinstance(return_node, ast.Return)
                    and isinstance(return_node.value, ast.Name)
                    and return_node.value.id in assignments
                ):
                    returned_host_paths.add(assignments[return_node.value.id])
            result_is_observed = (
                "success" in test_node.name.casefold()
                or any(
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == callable_name
                    for node in ast.walk(test_node)
                )
            )
            if returned_host_paths and result_is_observed and not any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "assertIs"
                for node in ast.walk(test_node)
            ):
                errors.append(
                    f"{test_node.name}: {callable_name} returns the object from "
                    + ", ".join(sorted(returned_host_paths))
                    + "; patch that exact call and assert result identity with "
                    "its configured return object."
                )
        directly_called_connected_slots = sorted({
            node.func.attr
            for node in ast.walk(test_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in connected_methods
        })
        if directly_called_connected_slots:
            errors.append(
                f"{test_node.name}: trigger construction-connected behavior "
                "through the public widget signal, not by directly calling slots: "
                + ", ".join(directly_called_connected_slots)
            )
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("assert")
            and any(isinstance(argument, ast.Lambda) for argument in node.args)
            for node in ast.walk(test_node)
        ):
            errors.append(
                f"{test_node.name}: do not compare callback lambda identity; "
                "inspect the dependency call, invoke the captured callback, and "
                "assert its public progress/status effect."
            )
        if (
            requires_existing_file
            and "success" in test_node.name.casefold()
            and not any(
                isinstance(node, ast.Call)
                and dotted_name(node.func).split(".")[-1]
                in {"NamedTemporaryFile", "TemporaryDirectory"}
                for node in ast.walk(test_node)
            )
        ):
            errors.append(
                f"{test_node.name}: success requires an existing input file; "
                "create it with a disposable tempfile fixture and pass that path."
            )
    return list(dict.fromkeys(errors))


def _repair_ephemeral_harness_call_graph(
    harness_source: str,
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
    project_root: str,
) -> tuple[str, list[str]]:
    """Mechanically align disposable host fixtures with production calls."""

    try:
        tree = ast.parse(
            harness_source,
            filename="<ephemeral_behavior_harness>",
        )
    except SyntaxError:
        return harness_source, []

    def dotted_name(node: ast.AST) -> str:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    def snake_case(value: str) -> str:
        value = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
        return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()

    production_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    production_function_modules: dict[str, str] = {}
    consumer_modules: dict[str, str] = {}
    connected_widgets: dict[str, str] = {}
    slot_backends: dict[str, tuple[str, str]] = {}
    for production_path, _original, production_source in generated_files:
        try:
            production_tree = ast.parse(production_source)
        except SyntaxError:
            continue
        try:
            module_name = ".".join(
                Path(production_path)
                .resolve()
                .relative_to(Path(project_root).resolve())
                .with_suffix("")
                .parts
            )
        except ValueError:
            module_name = Path(production_path).stem
        local_imported_names: set[str] = set()
        for import_node in production_tree.body:
            if isinstance(import_node, ast.ImportFrom):
                for alias in import_node.names:
                    local_name = alias.asname or alias.name
                    local_imported_names.add(local_name)
                    consumer_modules[local_name] = module_name
        for node in production_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                production_functions.setdefault(node.name, node)
                production_function_modules.setdefault(node.name, module_name)
        for node in ast.walk(production_tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and node.args
                and isinstance(node.args[0], ast.Attribute)
                and isinstance(node.args[0].value, ast.Name)
                and node.args[0].value.id == "self"
            ):
                continue
            signal_owner = node.func.value
            if (
                isinstance(signal_owner, ast.Attribute)
                and isinstance(signal_owner.value, ast.Attribute)
                and isinstance(signal_owner.value.value, ast.Name)
                and signal_owner.value.value.id == "self"
            ):
                connected_widgets[node.args[0].attr] = signal_owner.value.attr
        for method_node in ast.walk(production_tree):
            if not isinstance(
                method_node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            imported_calls = [
                call.func.id
                for call in ast.walk(method_node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id in local_imported_names
                and call.func.id[:1].islower()
            ]
            if imported_calls:
                slot_backends[method_node.name] = (
                    module_name,
                    imported_calls[0],
                )

    requires_existing_file = bool(
        re.search(
            r"\b(?:require|requires|required|requiring)\b"
            r"[^.!?\n]{0,80}\bexisting\b[^.!?\n]{0,40}\bfile\b",
            request_prompt,
            flags=re.IGNORECASE,
        )
    )
    needs_patch_import = False
    needs_magic_mock_import = False
    needs_tempfile_import = False
    fixes: list[str] = []
    for test_node in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ):
        called_production = {
            node.func.id
            for node in ast.walk(test_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in production_functions
        }
        if not called_production:
            called_production = set()
        dialog_instances = {
            target.id
            for assignment in ast.walk(test_node)
            if isinstance(assignment, ast.Assign)
            and len(assignment.targets) == 1
            and isinstance(assignment.targets[0], ast.Name)
            and isinstance(assignment.value, ast.Call)
            and isinstance(assignment.value.func, ast.Name)
            and assignment.value.func.id.endswith(("Dialog", "Window", "Widget"))
            for target in [assignment.targets[0]]
        }
        if dialog_instances:
            obsolete_fixture_names: set[str] = set()
            rewritten_slot_patch_body: list[ast.stmt] = []
            for statement in test_node.body:
                if not isinstance(statement, ast.With):
                    rewritten_slot_patch_body.append(statement)
                    continue
                slot_patch_item = next(
                    (
                        item
                        for item in statement.items
                        if isinstance(item.context_expr, ast.Call)
                        and dotted_name(
                            item.context_expr.func
                        ).endswith("patch.object")
                        and len(item.context_expr.args) >= 2
                        and isinstance(
                            item.context_expr.args[0],
                            ast.Name,
                        )
                        and item.context_expr.args[0].id in dialog_instances
                        and isinstance(
                            item.context_expr.args[1],
                            ast.Constant,
                        )
                        and isinstance(
                            item.context_expr.args[1].value,
                            str,
                        )
                        and item.context_expr.args[1].value
                        in connected_widgets
                    ),
                    None,
                )
                if slot_patch_item is None:
                    rewritten_slot_patch_body.append(statement)
                    continue
                slot_name = str(slot_patch_item.context_expr.args[1].value)
                backend_contract = slot_backends.get(slot_name)
                if backend_contract is None:
                    rewritten_slot_patch_body.append(statement)
                    continue
                consumer_module, backend_name = backend_contract
                backend_patch_path = f"{consumer_module}.{backend_name}"
                backend_mock_name = "mock_" + snake_case(backend_name)
                existing_decorator_paths = {
                    decorator.args[0].value
                    for decorator in test_node.decorator_list
                    if isinstance(decorator, ast.Call)
                    and dotted_name(decorator.func).split(".")[-1] == "patch"
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.args[0].value, str)
                }
                if backend_patch_path not in existing_decorator_paths:
                    test_node.decorator_list.append(
                        ast.Call(
                            func=ast.Name(id="patch", ctx=ast.Load()),
                            args=[ast.Constant(value=backend_patch_path)],
                            keywords=[],
                        )
                    )
                    test_node.args.args.insert(
                        1,
                        ast.arg(arg=backend_mock_name),
                    )
                    needs_patch_import = True
                optional_name = (
                    slot_patch_item.optional_vars.id
                    if isinstance(
                        slot_patch_item.optional_vars,
                        ast.Name,
                    )
                    else ""
                )
                if optional_name:
                    obsolete_fixture_names.add(optional_name)
                if "failure" in test_node.name.casefold():
                    rewritten_slot_patch_body.append(
                        ast.Assign(
                            targets=[
                                ast.Attribute(
                                    value=ast.Name(
                                        id=backend_mock_name,
                                        ctx=ast.Load(),
                                    ),
                                    attr="side_effect",
                                    ctx=ast.Store(),
                                )
                            ],
                            value=ast.Call(
                                func=ast.Name(
                                    id="ValueError",
                                    ctx=ast.Load(),
                                ),
                                args=[
                                    ast.Constant(value="forced test failure")
                                ],
                                keywords=[],
                            ),
                        )
                    )
                else:
                    rewritten_slot_patch_body.append(
                        ast.Assign(
                            targets=[
                                ast.Attribute(
                                    value=ast.Name(
                                        id=backend_mock_name,
                                        ctx=ast.Load(),
                                    ),
                                    attr="return_value",
                                    ctx=ast.Store(),
                                )
                            ],
                            value=ast.Call(
                                func=ast.Name(
                                    id="MagicMock",
                                    ctx=ast.Load(),
                                ),
                                args=[],
                                keywords=[],
                            ),
                        )
                    )
                    needs_magic_mock_import = True
                rewritten_slot_patch_body.extend(
                    inner_statement
                    for inner_statement in statement.body
                    if not optional_name
                    or not any(
                        isinstance(node, ast.Name)
                        and node.id == optional_name
                        for node in ast.walk(inner_statement)
                    )
                )
                fixes.append(
                    f"{test_node.name}: replaced connected-slot patch with "
                    f"consumer backend patch {backend_patch_path}"
                )
            test_node.body = rewritten_slot_patch_body
            lifted_exception_body: list[ast.stmt] = []
            for statement in test_node.body:
                if not isinstance(statement, ast.With):
                    lifted_exception_body.append(statement)
                    continue
                assert_raises_item = next(
                    (
                        item
                        for item in statement.items
                        if isinstance(item.context_expr, ast.Call)
                        and dotted_name(
                            item.context_expr.func
                        ).endswith("assertRaises")
                    ),
                    None,
                )
                if assert_raises_item is None:
                    lifted_exception_body.append(statement)
                    continue
                if isinstance(assert_raises_item.optional_vars, ast.Name):
                    obsolete_fixture_names.add(
                        assert_raises_item.optional_vars.id
                    )
                lifted_exception_body.extend(statement.body)
                fixes.append(
                    f"{test_node.name}: asserted caught UI failure through status"
                )
            test_node.body = [
                statement
                for statement in lifted_exception_body
                if not any(
                    isinstance(node, ast.Name)
                    and node.id in obsolete_fixture_names
                    for node in ast.walk(statement)
                )
            ]
            test_node.args.args = [
                argument
                for argument in test_node.args.args
                if argument.arg not in obsolete_fixture_names
            ]
            for decorator in test_node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and dotted_name(decorator.func).split(".")[-1] == "patch"
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.args[0].value, str)
                ):
                    continue
                patch_path = decorator.args[0].value
                imported_name = patch_path.rsplit(".", 1)[-1]
                consumer_module = consumer_modules.get(imported_name)
                if (
                    consumer_module
                    and not patch_path.startswith(consumer_module + ".")
                ):
                    decorator.args[0] = ast.Constant(
                        value=f"{consumer_module}.{imported_name}"
                    )
                    fixes.append(
                        f"{test_node.name}: patched {imported_name} at consumer "
                        f"lookup {consumer_module}"
                    )
            for call in ast.walk(test_node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in dialog_instances
                    and call.func.attr in connected_widgets
                ):
                    continue
                call.func = ast.Attribute(
                    value=ast.Attribute(
                        value=ast.Name(
                            id=call.func.value.id,
                            ctx=ast.Load(),
                        ),
                        attr=connected_widgets[call.func.attr],
                        ctx=ast.Load(),
                    ),
                    attr="click",
                    ctx=ast.Load(),
                )
                fixes.append(
                    f"{test_node.name}: triggered {call.func.value.attr}.click()"
                )
            if (
                ("success" in test_node.name.casefold()
                 or "failure" in test_node.name.casefold())
                and not any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"assertIn", "assertTrue", "assertEqual"}
                    and any(
                        isinstance(node, ast.Attribute)
                        and node.attr == "status_label"
                        for node in ast.walk(call)
                    )
                    for call in ast.walk(test_node)
                )
            ):
                dialog_name = sorted(dialog_instances)[0]
                expected_status = (
                    "fail"
                    if "failure" in test_node.name.casefold()
                    else "success"
                )
                test_node.body.append(
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr="assertIn",
                                ctx=ast.Load(),
                            ),
                            args=[
                                ast.Constant(value=expected_status),
                                ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Call(
                                            func=ast.Attribute(
                                                value=ast.Attribute(
                                                    value=ast.Name(
                                                        id=dialog_name,
                                                        ctx=ast.Load(),
                                                    ),
                                                    attr="status_label",
                                                    ctx=ast.Load(),
                                                ),
                                                attr="text",
                                                ctx=ast.Load(),
                                            ),
                                            args=[],
                                            keywords=[],
                                        ),
                                        attr="casefold",
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                ),
                            ],
                            keywords=[],
                        )
                    )
                )
                fixes.append(
                    f"{test_node.name}: asserted public {expected_status} status"
                )
        existing_patch_paths = {
            argument.value
            for decorator in test_node.decorator_list
            if isinstance(decorator, ast.Call)
            and dotted_name(decorator.func).split(".")[-1] == "patch"
            for argument in decorator.args[:1]
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
        }
        configured_statements: list[ast.stmt] = []
        prefix_statements: list[ast.stmt] = []
        fixture_names = {
            target.id
            for assignment in ast.walk(test_node)
            if isinstance(assignment, ast.Assign)
            for target in assignment.targets
            if isinstance(target, ast.Name)
        }
        returned_fixture_names: dict[str, str] = {}
        for callable_name in sorted(called_production):
            production_node = production_functions[callable_name]
            production_module = production_function_modules.get(
                callable_name,
                "",
            )
            local_import_roots = {
                alias.asname or alias.name.split(".", 1)[0]
                for import_node in ast.walk(production_node)
                if isinstance(import_node, ast.Import)
                for alias in import_node.names
            }
            local_import_roots.update(
                alias.asname or alias.name
                for import_node in ast.walk(production_node)
                if isinstance(import_node, ast.ImportFrom)
                for alias in import_node.names
            )
            host_assignments: dict[str, str] = {}
            direct_host_calls: set[str] = set()
            for production_call in ast.walk(production_node):
                if not isinstance(production_call, ast.Call):
                    continue
                path = dotted_name(production_call.func)
                if (
                    path
                    and path.split(".", 1)[0]
                    in _EPHEMERAL_HOST_RUNTIME_MODULES
                ):
                    direct_host_calls.add(path)
            for assignment in ast.walk(production_node):
                if (
                    isinstance(assignment, ast.Assign)
                    and len(assignment.targets) == 1
                    and isinstance(assignment.targets[0], ast.Name)
                    and isinstance(assignment.value, ast.Call)
                ):
                    path = dotted_name(assignment.value.func)
                    if (
                        path
                        and path.split(".", 1)[0]
                        in _EPHEMERAL_HOST_RUNTIME_MODULES
                    ):
                        host_assignments[path] = assignment.targets[0].id
            returned_host_path = ""
            returned_local_name = ""
            for return_node in ast.walk(production_node):
                if not (
                    isinstance(return_node, ast.Return)
                    and isinstance(return_node.value, ast.Name)
                ):
                    continue
                for path, local_name in host_assignments.items():
                    if local_name == return_node.value.id:
                        returned_host_path = path
                        returned_local_name = local_name
                        break
            for path in sorted(direct_host_calls):
                if path.split(".", 1)[0] in local_import_roots:
                    overqualified_target = (
                        f"{production_module}.{path}"
                        if production_module
                        else ""
                    )
                    for patch_call in ast.walk(test_node):
                        if not (
                            isinstance(patch_call, ast.Call)
                            and dotted_name(patch_call.func).split(".")[-1]
                            == "patch"
                            and patch_call.args
                            and isinstance(patch_call.args[0], ast.Constant)
                            and patch_call.args[0].value == overqualified_target
                        ):
                            continue
                        patch_call.args[0] = ast.Constant(value=path)
                        existing_patch_paths.discard(overqualified_target)
                        existing_patch_paths.add(path)
                        fixes.append(
                            f"{test_node.name}: corrected function-local host "
                            f"patch target to {path}"
                        )
                if any(
                    existing == path or existing.endswith("." + path)
                    for existing in existing_patch_paths
                ):
                    continue
                mock_argument_name = "mock_" + snake_case(
                    path.rsplit(".", 1)[-1]
                )
                if mock_argument_name in {
                    argument.arg for argument in test_node.args.args
                }:
                    argument_already_present = True
                else:
                    argument_already_present = False
                patch_target = (
                    f"{production_module}.{path}"
                    if production_module
                    and path.split(".", 1)[0] not in local_import_roots
                    else path
                )
                test_node.decorator_list.append(
                    ast.Call(
                        func=ast.Name(id="patch", ctx=ast.Load()),
                        args=[ast.Constant(value=patch_target)],
                        keywords=[],
                    )
                )
                if not argument_already_present:
                    test_node.args.args.insert(
                        1,
                        ast.arg(arg=mock_argument_name),
                    )
                existing_patch_paths.add(patch_target)
                needs_patch_import = True
                fixes.append(
                    f"{test_node.name}: patched exact host boundary "
                    f"{patch_target}"
                )
                assigned_local = host_assignments.get(path)
                if assigned_local:
                    fixture_name = "mock_" + snake_case(assigned_local)
                    if fixture_name not in fixture_names:
                        configured_statements.append(
                            ast.Assign(
                                targets=[
                                    ast.Name(
                                        id=fixture_name,
                                        ctx=ast.Store(),
                                    )
                                ],
                                value=ast.Call(
                                    func=ast.Name(
                                        id="MagicMock",
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                ),
                            )
                        )
                        fixture_names.add(fixture_name)
                        needs_magic_mock_import = True
                    configured_statements.append(
                        ast.Assign(
                            targets=[
                                ast.Attribute(
                                    value=ast.Name(
                                        id=mock_argument_name,
                                        ctx=ast.Load(),
                                    ),
                                    attr="return_value",
                                    ctx=ast.Store(),
                                )
                            ],
                            value=ast.Name(
                                id=fixture_name,
                                ctx=ast.Load(),
                            ),
                        )
                    )
                    if path == returned_host_path:
                        returned_fixture_names[callable_name] = fixture_name
            result_variables = {
                target.id
                for assignment in ast.walk(test_node)
                if isinstance(assignment, ast.Assign)
                and len(assignment.targets) == 1
                and isinstance(assignment.targets[0], ast.Name)
                and isinstance(assignment.value, ast.Call)
                and isinstance(assignment.value.func, ast.Name)
                and assignment.value.func.id == callable_name
                for target in [assignment.targets[0]]
            }
            returned_fixture = returned_fixture_names.get(callable_name)
            returned_object_methods = {
                call.func.attr
                for call in ast.walk(production_node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == returned_local_name
            }
            if returned_fixture and returned_object_methods:
                for assertion in ast.walk(test_node):
                    if not (
                        isinstance(assertion, ast.Call)
                        and isinstance(assertion.func, ast.Attribute)
                        and assertion.func.attr.startswith("assert_")
                        and isinstance(assertion.func.value, ast.Attribute)
                        and assertion.func.value.attr in returned_object_methods
                        and isinstance(
                            assertion.func.value.value,
                            ast.Name,
                        )
                    ):
                        continue
                    assertion.func.value.value = ast.Name(
                        id=returned_fixture,
                        ctx=ast.Load(),
                    )
                    fixes.append(
                        f"{test_node.name}: asserted "
                        f"{assertion.func.value.attr} on returned host mock"
                    )
            if returned_fixture and result_variables:
                for assertion in ast.walk(test_node):
                    if not (
                        isinstance(assertion, ast.Call)
                        and isinstance(assertion.func, ast.Attribute)
                        and assertion.func.attr in {"assertEqual", "assertIs"}
                        and len(assertion.args) >= 2
                        and isinstance(assertion.args[0], ast.Name)
                        and assertion.args[0].id in result_variables
                    ):
                        continue
                    assertion.func.attr = "assertIs"
                    assertion.args[1] = ast.Name(
                        id=returned_fixture,
                        ctx=ast.Load(),
                    )
                    fixes.append(
                        f"{test_node.name}: asserted returned host-object identity"
                    )
        if (
            requires_existing_file
            and "failure" not in test_node.name.casefold()
        ):
            temporary_name = "temporary_source_file"
            prefix_statements.append(
                ast.Assign(
                    targets=[
                        ast.Name(id=temporary_name, ctx=ast.Store())
                    ],
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="tempfile", ctx=ast.Load()),
                            attr="NamedTemporaryFile",
                            ctx=ast.Load(),
                        ),
                        args=[],
                        keywords=[
                            ast.keyword(
                                arg="suffix",
                                value=ast.Constant(value=".png"),
                            )
                        ],
                    ),
                ),
            )
            prefix_statements.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr="addCleanup",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Attribute(
                                value=ast.Name(
                                    id=temporary_name,
                                    ctx=ast.Load(),
                                ),
                                attr="close",
                                ctx=ast.Load(),
                            )
                        ],
                        keywords=[],
                    )
                ),
            )
            for call in ast.walk(test_node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id.endswith("Request")
                ):
                    continue
                for keyword in call.keywords:
                    if keyword.arg == "source_file":
                        keyword.value = ast.Attribute(
                            value=ast.Name(
                                id=temporary_name,
                                ctx=ast.Load(),
                            ),
                            attr="name",
                            ctx=ast.Load(),
                        )
                if call.args and isinstance(call.args[0], ast.Constant):
                    call.args[0] = ast.Attribute(
                        value=ast.Name(
                            id=temporary_name,
                            ctx=ast.Load(),
                        ),
                        attr="name",
                        ctx=ast.Load(),
                    )
            needs_tempfile_import = True
            fixes.append(
                f"{test_node.name}: created a real disposable input file"
            )
        if prefix_statements:
            prefix_index = (
                1
                if test_node.body
                and isinstance(test_node.body[0], ast.Expr)
                and isinstance(test_node.body[0].value, ast.Constant)
                and isinstance(test_node.body[0].value.value, str)
                else 0
            )
            test_node.body[prefix_index:prefix_index] = prefix_statements
        if configured_statements:
            first_call_index = next(
                (
                    index
                    for index, statement in enumerate(test_node.body)
                    if any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in called_production
                        for node in ast.walk(statement)
                    )
                ),
                len(test_node.body),
            )
            test_node.body[first_call_index:first_call_index] = (
                configured_statements
            )
        rewritten_body: list[ast.stmt] = []
        for statement in test_node.body:
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and statement.value.func.attr.startswith("assert_called")
                and isinstance(statement.value.func.value, ast.Name)
                and any(
                    isinstance(argument, ast.Lambda)
                    for argument in statement.value.args
                )
            ):
                rewritten_body.append(statement)
                continue
            mock_name = statement.value.func.value.id
            expected_arguments = [
                argument
                for argument in statement.value.args
                if not isinstance(argument, ast.Lambda)
            ]
            replacement_source = (
                f"{mock_name}.assert_called_once()\n"
                f"captured_call_args = {mock_name}.call_args.args\n"
            )
            replacement_nodes = ast.parse(replacement_source).body
            if expected_arguments:
                replacement_nodes.append(
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr="assertEqual",
                                ctx=ast.Load(),
                            ),
                            args=[
                                ast.Subscript(
                                    value=ast.Name(
                                        id="captured_call_args",
                                        ctx=ast.Load(),
                                    ),
                                    slice=ast.Constant(value=0),
                                    ctx=ast.Load(),
                                ),
                                expected_arguments[0],
                            ],
                            keywords=[],
                        )
                    )
                )
            replacement_nodes.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr="assertTrue",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Call(
                                func=ast.Name(id="callable", ctx=ast.Load()),
                                args=[
                                    ast.Subscript(
                                        value=ast.Name(
                                            id="captured_call_args",
                                            ctx=ast.Load(),
                                        ),
                                        slice=ast.Constant(value=1),
                                        ctx=ast.Load(),
                                    )
                                ],
                                keywords=[],
                            )
                        ],
                        keywords=[],
                    )
                )
            )
            rewritten_body.extend(replacement_nodes)
            fixes.append(
                f"{test_node.name}: captured callback instead of comparing lambda"
            )
        test_node.body = rewritten_body

    if not fixes:
        return harness_source, []
    import_from = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "unittest.mock"
        ),
        None,
    )
    required_mock_imports = {
        *({"patch"} if needs_patch_import else set()),
        *({"MagicMock"} if needs_magic_mock_import else set()),
    }
    if required_mock_imports:
        if import_from is None:
            tree.body.insert(
                0,
                ast.ImportFrom(
                    module="unittest.mock",
                    names=[
                        ast.alias(name=name)
                        for name in sorted(required_mock_imports)
                    ],
                    level=0,
                ),
            )
        else:
            existing_imports = {alias.name for alias in import_from.names}
            import_from.names.extend(
                ast.alias(name=name)
                for name in sorted(required_mock_imports)
                if name not in existing_imports
            )
    if needs_tempfile_import and not any(
        isinstance(node, ast.Import)
        and any(alias.name == "tempfile" for alias in node.names)
        for node in tree.body
    ):
        tree.body.insert(
            0,
            ast.Import(names=[ast.alias(name="tempfile")]),
        )
    ast.fix_missing_locations(tree)
    return ast.unparse(tree).rstrip() + "\n", fixes


def _build_ephemeral_harness_audit_stage(
    *,
    behavior_rows: list[dict[str, str]],
    generated_files: list[tuple[str, str, str]],
    harness_source: str,
    known_issues: list[str] | None = None,
) -> ProjectEditPromptStage:
    """Build a causal audit for disposable fixture expectations."""

    selected_test_names = {
        str(row.get("test_name") or "")
        for row in behavior_rows
        if str(row.get("test_name") or "")
    }
    failing_test_names = {
        match
        for issue in known_issues or []
        for match in re.findall(r"\btest_[A-Za-z0-9_]+\b", str(issue))
    }
    harness_test_names = failing_test_names or selected_test_names
    if harness_test_names:
        behavior_rows = [
            row
            for row in behavior_rows
            if str(row.get("test_name") or "") in harness_test_names
        ]
        try:
            harness_tree = ast.parse(
                harness_source,
                filename="<ephemeral_behavior_harness>",
            )
            for node in ast.walk(harness_tree):
                if isinstance(node, ast.ClassDef):
                    node.body = [
                        member
                        for member in node.body
                        if not (
                            isinstance(
                                member,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and member.name.startswith("test_")
                            and member.name not in harness_test_names
                        )
                    ]
            ast.fix_missing_locations(harness_tree)
            harness_source = ast.unparse(harness_tree).rstrip() + "\n"
        except SyntaxError:
            pass

    relevant_paths = {
        str(owner.get("path") or "").replace("\\", "/").casefold()
        for row in behavior_rows
        for owner in row.get("production_owners") or []
        if isinstance(owner, Mapping)
    }
    production = [
        {
            "path": Path(path).name,
            "source": source,
        }
        for path, _original, source in generated_files
        if not Path(path).name.startswith("test_")
        and (
            not relevant_paths
            or any(
                normalized_path.endswith(relevant_path)
                or relevant_path.endswith(normalized_path)
                for relevant_path in relevant_paths
                for normalized_path in [
                    str(path).replace("\\", "/").casefold()
                ]
            )
        )
    ]
    return ProjectEditPromptStage(
        key="ephemeral_behavior_harness_audit",
        label="Auditing disposable requirement-test fixtures",
        system_prompt=(
            "/no_think\n"
            "You audit disposable Python tests, not production code. Return JSON "
            "only. Reject a test when its own setup does not mathematically imply "
            "its expected value or exception. Compare every patch, configured "
            "return value, asserted receiver, and returned object identity against "
            "the supplied production call graph. Never propose weakening production. "
            "When validator-proven issues are supplied, repair every named failing "
            "test exactly once. Return only complete replacement methods for those "
            "tests; never return a complete module, omit a failing test, or return "
            "an unchanged method. A replacement name must exactly equal a test_name "
            "from Approved behavior checks. Never return `_run_as_script`, a main "
            "guard, imports, binding metadata, assignments, or helper functions as "
            "test-method repairs, even when those names appear in a traceback."
        ),
        user_prompt=(
            "Approved behavior checks:\n"
            + json.dumps(behavior_rows, ensure_ascii=True)
            + "\n\nProduction public implementation:\n"
            + json.dumps(production, ensure_ascii=True)
            + "\n\nDisposable harness:\n```python\n"
            + harness_source
            + "\n```"
            + (
                "\n\nValidator-proven fixture contradictions that each require "
                "one exact named test-method replacement:\n"
                + json.dumps(known_issues, ensure_ascii=True)
                if known_issues
                else ""
            )
            + """
Trace each test's fixture state in execution order. For clocks, TTLs, retries,
ordering, and state transitions, calculate the exact values at every assertion.
An expiration assertion is valid only when the configured clock is at or beyond
the stored insertion time plus duration. Distinguish a bad fixture expectation
from a production defect.

When production constructs an unavailable host object, a test that configures a
separate mock must patch that exact constructor to return the configured mock.
When production loads or creates an object and returns it, patch that exact call,
configure one explicit result object, and assert identity with that object. Never
assert a method on a mock owner that production does not call. If success requires
an existing input file, create a disposable real file; use a proven missing path
for rejection coverage. Preserve or add all patch decorators/context managers
needed by the complete replacement method.

Derive every expected collection from the production selection predicate. A
fixture record that does not satisfy an OR/AND/filter predicate must not appear in
the expected result. Never assume an arbitrary literal filesystem path exists:
create a disposable path with the required state or patch the exact filesystem
predicate used by production. Before asserting UI consumer output, explicitly set
every checkbox, combo, or other input state that controls filtering.

Respect asynchronous boundaries. Starting a QThread, QRunnable, task, or worker
does not prove that its work function has already run. A launcher test must assert
worker construction, signal wiring, and the asynchronous start call without
expecting the service result synchronously. Test the worker's run method separately
when the behavior contract requires the service invocation or emitted terminal
signals. Never make production synchronous merely to satisfy a disposable test.

Report only a direct contradiction where the fixture values compute to a
different expected public result than the assertion contains. Missing extra
coverage, missing mock call-count checks, missing private-state inspection, and
an assertion that could be made stronger are not fixture contradictions and must
not be reported. Never ask a test to access private state.

For each direct contradiction, return one complete raw replacement test method
whose function name exactly matches `test`. Preserve every unrelated assertion
and every existing patch decorator. A replacement may patch only an exact
qualified host API path present in the supplied production source; never
substitute a shorter, alternate, or guessed host API path.

Every replacement must remain callable under its decorators. Preserve all mock
parameters injected by retained `patch` decorators in the correct decorator
order. If a mock parameter is no longer needed, remove the corresponding patch
decorator or use a scoped context manager instead; never retain a decorator while
omitting its injected function parameter.
"""
            + (
                """
VALIDATOR-REPAIR OVERRIDE:
The supplied validator issues are already proven and are not optional semantic
suggestions. Repair every named test even when the issue is missing owner
execution, missing observable coverage, or an insufficient assertion rather
than a fixture contradiction. Each replacement must call every production
owner named by its bound behavior contract and directly assert every stated
observation. Preserve all already-valid behavior in the method. Do not return
`valid: true` while any supplied validator issue remains.

When a validator issue names an exact class method or function owner, invoke that
exact callable directly in the replacement test. Triggering a signal, clicking a
widget, or calling a downstream helper is not a substitute for executing the
named owner. Patch the owner's downstream dependency when isolation is needed,
then assert that dependency's exact call.
"""
                if known_issues
                else ""
            )
            + """
Return exactly:
{"valid": true_or_false, "issues": [{"test": "test_name", "reason": "exact issue", "replacement": "def test_name(self):\\n    ..."}]}
"""
        ),
        model_tier="local_code",
        num_ctx=6144,
        num_predict=-1,
        timeout=90,
        no_progress_seconds=30,
        prefer_coder=True,
        coder_preference="standard",
        response_format="json",
        metadata={
            "failing_test_names": sorted(failing_test_names),
            "behavior_rows": behavior_rows,
        },
    )


def _parse_ephemeral_harness_audit(
    response: str,
    *,
    accept_validator_repairs: bool = False,
) -> tuple[list[str], list[dict[str, str]]]:
    """Return concrete fixture issues and exact test-method repairs."""

    text = str(response or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        object_match = re.search(r"\{.*\}", text, re.DOTALL)
        if object_match:
            text = object_match.group(0)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ["Disposable harness semantic audit did not return valid JSON."], []
    if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
        return ["Disposable harness semantic audit omitted its issues list."], []
    issues = []
    repairs: list[dict[str, str]] = []
    for issue in payload["issues"]:
        if not isinstance(issue, dict):
            continue
        reason = str(issue.get("reason") or "").strip()
        if not reason:
            continue
        raw_test_name = str(issue.get("test") or "").strip()
        test_name = raw_test_name.rsplit(".", 1)[-1]
        replacement = str(issue.get("replacement") or "").strip()
        lower_reason = reason.casefold()
        if (
            re.search(
                r"(?:progress|callback)",
                replacement,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\bassert_(?:has_calls|called(?:_once)?_with)\b",
                replacement,
            )
        ):
            # Candidate-derived exact callback sequences are examples, not
            # authoritative requirement oracles. Contract-level progress checks
            # are normalized deterministically after the harness runs.
            continue
        if not accept_validator_repairs:
            if any(
                marker in lower_reason
                for marker in (
                    "could be stronger",
                    "mock is called",
                    "private state",
                    "._",
                )
            ):
                continue
            if not re.search(
                r"\b(?:incorrect|contradiction|should (?:be|return|raise)|"
                r"actual|computed|expires? at|wrong|unpatched|not patched|"
                r"different object|mock|constructor|return value|call graph)\b",
                reason,
                flags=re.IGNORECASE,
            ):
                continue
        issues.append(
            f"{test_name or '<unknown test>'}: {reason}"
        )
        if test_name and replacement:
            repairs.append({
                "test": test_name,
                "replacement": replacement,
            })
    return issues, repairs


def _ensure_ephemeral_behavior_bindings(
    response: str,
    behavior_ids: list[str],
    test_names: list[str] | None = None,
) -> str:
    """Inject deterministic behavior ownership metadata when code omitted it."""

    text = str(response or "")
    unfenced = re.sub(
        r"^\s*```(?:python)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    unfenced = re.sub(r"\s*```\s*$", "", unfenced).strip()
    existing_bindings, binding_errors = _ephemeral_behavior_bindings(
        unfenced
    )
    existing_behavior_ids = {
        behavior_id
        for owned_ids in existing_bindings.values()
        for behavior_id in owned_ids
    }
    if (
        not binding_errors
        and set(behavior_ids).issubset(existing_behavior_ids)
    ):
        return text
    text = re.sub(
        r"(?m)^[ \t]*__TECH_CONNECTOR_BEHAVIOR_BINDINGS__"
        r"[ \t]*(?::[^=\r\n]+)?=[^\r\n]*(?:\r?\n|$)",
        "",
        text,
    )
    names = [
        str(value) for value in (test_names or []) if str(value).strip()
    ]
    if len(names) != len(behavior_ids):
        discovered_names = list(dict.fromkeys(re.findall(
            r"\bdef\s+(test_[A-Za-z0-9_]+)\s*\(",
            text,
        )))
        if len(discovered_names) == 1 and behavior_ids:
            names = [
                discovered_names[0] for _behavior_id in behavior_ids
            ]
        else:
            names = discovered_names
    if len(names) != len(behavior_ids):
        return text
    bindings: dict[str, list[str]] = {}
    for test_name, behavior_id in zip(names, behavior_ids, strict=True):
        bindings.setdefault(test_name, []).append(behavior_id)
    binding_line = (
        "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = "
        + repr(bindings)
        + "\n"
    )
    fence = re.search(r"```(?:python)?[ \t]*\r?\n", text)
    if fence:
        return text[:fence.end()] + binding_line + text[fence.end():]
    return binding_line + text


def _apply_ephemeral_harness_repairs(
    source: str,
    repairs: list[dict[str, str]],
    *,
    generated_files: list[tuple[str, str, str]],
) -> tuple[str, list[str]]:
    """Apply independently audited test-method replacements."""

    try:
        tree = ast.parse(source, filename="<ephemeral_behavior_harness>")
    except SyntaxError as exc:
        return source, [f"Disposable harness did not parse for repair: {exc}."]
    errors: list[str] = []
    changed = False
    host_module_pattern = "|".join(
        re.escape(module)
        for module in sorted(_EPHEMERAL_HOST_RUNTIME_MODULES)
    )
    host_path_pattern = re.compile(
        rf"\b(?:{host_module_pattern})"
        r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
    )

    def canonicalize_host_paths(value: str) -> tuple[str, set[str]]:
        """Replace guessed host prefixes with unique indexed canonical paths."""

        try:
            from tech_connector.services.symbol_evidence_service import (
                resolve_runtime_api_record,
            )
        except Exception:
            return value, set()
        canonical_paths: set[str] = set()
        normalized = value
        for proposed_path in {
            match.group(0) for match in host_path_pattern.finditer(value)
        }:
            record = resolve_runtime_api_record(
                proposed_path,
                project_root=Path(__file__).resolve().parents[2],
                allow_unique_owner_suffix=True,
            )
            canonical = str(
                (record or {}).get("qualified_name") or ""
            ).strip()
            if not canonical:
                continue
            normalized = normalized.replace(proposed_path, canonical)
            canonical_paths.add(canonical)
        return normalized, canonical_paths

    for repair in repairs:
        test_name = str(repair.get("test") or "")
        replacement = str(repair.get("replacement") or "")
        replacement, verified_canonical_paths = canonicalize_host_paths(
            replacement
        )
        try:
            replacement_tree = ast.parse(replacement)
        except SyntaxError as exc:
            errors.append(f"{test_name}: replacement did not parse: {exc}.")
            continue
        replacement_nodes = [
            node
            for node in replacement_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if (
            len(replacement_tree.body) != 1
            or len(replacement_nodes) != 1
            or replacement_nodes[0].name != test_name
        ):
            errors.append(
                f"{test_name}: audit must return exactly one matching test method."
            )
            continue
        matches = [
            (class_node, index)
            for class_node in tree.body
            if isinstance(class_node, ast.ClassDef)
            for index, member in enumerate(class_node.body)
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name == test_name
        ]
        if len(matches) != 1:
            errors.append(
                f"{test_name}: expected one existing disposable test owner, found "
                f"{len(matches)}."
            )
            continue
        class_node, member_index = matches[0]
        existing_method = class_node.body[member_index]
        replacement_method = replacement_nodes[0]
        def is_mock_patch_decorator(decorator: ast.AST) -> bool:
            expression = (
                decorator.func
                if isinstance(decorator, ast.Call)
                else decorator
            )
            parts: list[str] = []
            while isinstance(expression, ast.Attribute):
                parts.append(expression.attr)
                expression = expression.value
            if isinstance(expression, ast.Name):
                parts.append(expression.id)
            dotted = ".".join(reversed(parts)).casefold()
            return dotted == "patch" or dotted.startswith("patch.")

        existing_decorators = {
            ast.dump(decorator, include_attributes=False): decorator
            for decorator in existing_method.decorator_list
            if not is_mock_patch_decorator(decorator)
        }
        replacement_decorator_keys = {
            ast.dump(decorator, include_attributes=False)
            for decorator in replacement_method.decorator_list
        }
        replacement_method.decorator_list = [
            *[
                decorator
                for key, decorator in existing_decorators.items()
                if key not in replacement_decorator_keys
            ],
            *replacement_method.decorator_list,
        ]
        allowed_host_paths = {
            match.group(0)
            for _path, _original, production_source in generated_files
            for match in host_path_pattern.finditer(production_source)
        }
        replacement_host_paths = {
            match.group(0)
            for match in host_path_pattern.finditer(replacement)
        }
        verified_host_paths = {
            match.group(0)
            for canonical_path in verified_canonical_paths
            for match in host_path_pattern.finditer(canonical_path)
        }
        invented_host_paths = sorted(
            replacement_host_paths
            - allowed_host_paths
            - verified_host_paths
        )
        if invented_host_paths:
            errors.append(
                f"{test_name}: replacement introduced host API paths absent "
                "from production: " + ", ".join(invented_host_paths) + "."
            )
            continue
        class_node.body[member_index] = replacement_method
        changed = True
    if errors and not changed:
        return source, errors
    ast.fix_missing_locations(tree)
    return ast.unparse(tree).rstrip() + "\n", errors


def _repair_ephemeral_indirect_owner_invocations(
    source: str,
    errors: list[str],
    *,
    generated_files: list[tuple[str, str, str]] | None = None,
) -> tuple[str, list[str]]:
    """Replace indirect disposable triggers with validator-required owner calls."""

    required_calls = re.findall(
        r"(test_[A-Za-z0-9_]+): `[^`]+` does not execute approved "
        r"production owner `([A-Za-z_][A-Za-z0-9_]*)"
        r"\.([A-Za-z_][A-Za-z0-9_]*)`",
        "\n".join(str(error) for error in errors),
    )
    if not required_calls:
        return source, []
    try:
        tree = ast.parse(source, filename="<ephemeral_behavior_harness>")
    except SyntaxError:
        return source, []
    repairs: list[str] = []
    indirect_triggers = {"click", "emit", "trigger", "activate"}
    production_methods: dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for path, _original, production_source in generated_files or []:
        try:
            production_tree = ast.parse(production_source, filename=path)
        except SyntaxError:
            continue
        for class_node in production_tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            for member in class_node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    production_methods[(class_node.name, member.name)] = member
    for test_name, class_name, owner_method in required_calls:
        test_node = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == test_name
            ),
            None,
        )
        if test_node is None:
            continue
        instance_names = {
            target.id
            for node in ast.walk(test_node)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            if isinstance(target, ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == class_name
        }
        if not instance_names:
            continue

        class IndirectTriggerRewriter(ast.NodeTransformer):
            def __init__(self) -> None:
                self.changed = False

            def visit_Expr(self, node: ast.Expr) -> ast.AST:
                self.generic_visit(node)
                call = node.value
                if (
                    not self.changed
                    and isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in indirect_triggers
                ):
                    cursor = call.func.value
                    while isinstance(cursor, ast.Attribute):
                        cursor = cursor.value
                    if (
                        isinstance(cursor, ast.Name)
                        and cursor.id in instance_names
                    ):
                        self.changed = True
                        return ast.copy_location(
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(
                                            id=cursor.id,
                                            ctx=ast.Load(),
                                        ),
                                        attr=owner_method,
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                )
                            ),
                            node,
                        )
                return node

        rewriter = IndirectTriggerRewriter()
        rewriter.visit(test_node)
        if rewriter.changed:
            repairs.append(
                f"{test_name}: replaced an indirect trigger with exact "
                f"approved owner {class_name}.{owner_method}."
            )
            continue
        production_method = production_methods.get((class_name, owner_method))
        if production_method is None:
            continue
        positional = production_method.args.posonlyargs + production_method.args.args
        if positional and positional[0].arg in {"self", "cls"}:
            positional = positional[1:]
        required_positional = max(
            0,
            len(positional) - len(production_method.args.defaults),
        )

        def fixture_value(argument: ast.arg) -> ast.expr:
            annotation = (
                ast.unparse(argument.annotation).casefold()
                if argument.annotation is not None
                else ""
            )
            name = argument.arg.casefold()
            if annotation in {"int", "builtins.int"}:
                return ast.Constant(value=1)
            if annotation in {"float", "builtins.float"}:
                return ast.Constant(value=1.0)
            if annotation in {"str", "builtins.str"}:
                return ast.Constant(value="status")
            if annotation in {"bool", "builtins.bool"}:
                return ast.Constant(value=True)
            if annotation in {"bytes", "builtins.bytes"}:
                return ast.Constant(value=b"")
            if any(
                token in annotation
                for token in ("list", "sequence", "iterable", "collection")
            ):
                return ast.List(elts=[], ctx=ast.Load())
            if "tuple" in annotation:
                return ast.Tuple(elts=[], ctx=ast.Load())
            if any(token in annotation for token in ("dict", "mapping")):
                return ast.Dict(keys=[], values=[])
            if "set" in annotation:
                return ast.Set(elts=[])
            if "path" in annotation or "path" in name:
                return ast.Constant(value="input")
            if any(
                token in name
                for token in ("current", "total", "count", "index", "step")
            ):
                return ast.Constant(value=1)
            if any(
                token in name
                for token in ("status", "message", "error", "text", "name")
            ):
                return ast.Constant(value="status")
            return ast.Call(
                func=ast.Name(id="MagicMock", ctx=ast.Load()),
                args=[],
                keywords=[],
            )

        required_args = [
            fixture_value(argument)
            for argument in positional[:required_positional]
        ]
        required_keywords = [
            ast.keyword(
                arg=argument.arg,
                value=fixture_value(argument),
            )
            for argument, default in zip(
                production_method.args.kwonlyargs,
                production_method.args.kw_defaults,
            )
            if default is None
        ]
        instance_name = sorted(instance_names)[0]
        owner_call = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id=instance_name, ctx=ast.Load()),
                    attr=owner_method,
                    ctx=ast.Load(),
                ),
                args=required_args,
                keywords=required_keywords,
            )
        )
        downstream_methods = [
            call.func.attr
            for call in ast.walk(production_method)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in {"self", "cls"}
            and call.func.attr != owner_method
        ]
        insertion_index = next(
            (
                index + 1
                for index, statement in enumerate(test_node.body)
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                and any(
                    isinstance(target, ast.Name)
                    and target.id == instance_name
                    for target in (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                )
            ),
            0,
        )
        if insertion_index == 0:
            constructor = production_methods.get((class_name, "__init__"))
            constructor_args: list[ast.expr] = []
            constructor_keywords: list[ast.keyword] = []
            if constructor is not None:
                constructor_positional = (
                    constructor.args.posonlyargs + constructor.args.args
                )
                if (
                    constructor_positional
                    and constructor_positional[0].arg in {"self", "cls"}
                ):
                    constructor_positional = constructor_positional[1:]
                constructor_required = max(
                    0,
                    len(constructor_positional) - len(constructor.args.defaults),
                )
                constructor_args = [
                    fixture_value(argument)
                    for argument in constructor_positional[:constructor_required]
                ]
                constructor_keywords = [
                    ast.keyword(
                        arg=argument.arg,
                        value=fixture_value(argument),
                    )
                    for argument, default in zip(
                        constructor.args.kwonlyargs,
                        constructor.args.kw_defaults,
                    )
                    if default is None
                ]
            test_node.body.insert(
                0,
                ast.Assign(
                    targets=[ast.Name(id=instance_name, ctx=ast.Store())],
                    value=ast.Call(
                        func=ast.Name(id=class_name, ctx=ast.Load()),
                        args=constructor_args,
                        keywords=constructor_keywords,
                    ),
                ),
            )
            insertion_index = 1
        if downstream_methods:
            dependency_name = downstream_methods[0]
            mock_name = f"mock_{dependency_name.lstrip('_')}"
            owner_proof: ast.stmt = ast.With(
                items=[
                    ast.withitem(
                        context_expr=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="patch", ctx=ast.Load()),
                                attr="object",
                                ctx=ast.Load(),
                            ),
                            args=[
                                ast.Name(id=instance_name, ctx=ast.Load()),
                                ast.Constant(value=dependency_name),
                            ],
                            keywords=[],
                        ),
                        optional_vars=ast.Name(
                            id=mock_name,
                            ctx=ast.Store(),
                        ),
                    )
                ],
                body=[
                    owner_call,
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(
                                    id=mock_name,
                                    ctx=ast.Load(),
                                ),
                                attr="assert_called_once_with",
                                ctx=ast.Load(),
                            ),
                            args=[],
                            keywords=[],
                        )
                    ),
                ],
            )
            if not any(
                isinstance(statement, ast.ImportFrom)
                and statement.module == "unittest.mock"
                and any(alias.name == "patch" for alias in statement.names)
                for statement in tree.body
            ):
                tree.body.insert(
                    0,
                    ast.ImportFrom(
                        module="unittest.mock",
                        names=[ast.alias(name="patch")],
                        level=0,
                    ),
                )
        else:
            owner_proof = owner_call
        if any(
            isinstance(node, ast.Name)
            and node.id == "MagicMock"
            for node in ast.walk(owner_proof)
        ) and not any(
            isinstance(statement, ast.ImportFrom)
            and statement.module == "unittest.mock"
            and any(alias.name == "MagicMock" for alias in statement.names)
            for statement in tree.body
        ):
            tree.body.insert(
                0,
                ast.ImportFrom(
                    module="unittest.mock",
                    names=[ast.alias(name="MagicMock")],
                    level=0,
                ),
            )
        test_node.body.insert(insertion_index, owner_proof)
        repairs.append(
            f"{test_name}: inserted exact approved owner call "
            f"{class_name}.{owner_method} with its derived dependency isolated."
        )
    if not repairs:
        return source, []
    ast.fix_missing_locations(tree)
    return ast.unparse(tree).rstrip() + "\n", repairs


def _semantic_requirement_ledger(
    requirement_ledger: list[dict[str, str]],
    *,
    generated_files: list[tuple[str, str, str]] | None = None,
) -> list[dict[str, str]]:
    """Return clauses whose behavior cannot be proven structurally."""

    semantic_markers = re.compile(
        r"\b(?:calls?|calling|connect(?:s|ed|ing|_[A-Za-z0-9_]+)?|"
        r"execut(?:e|es|ed|ing)|load(?:s|ed|ing)?|normaliz\w*|"
        r"report(?:s|ed|ing)?|"
        r"require\s+an?\s+existing|require\s+exactly|"
        r"return(?:s|ed|ing)?|sav(?:e|es|ed|ing)|set(?:s|ting)?|"
        r"stream(?:s|ed|ing)?|validat(?:e|es|ed|ing))\b",
        flags=re.IGNORECASE,
    )
    semantic_rows = [
        row
        for row in requirement_ledger
        if semantic_markers.search(
            str(
                row.get("text")
                or row.get("requirement")
                or row.get("description")
                or ""
            )
        )
    ]
    if not generated_files:
        return semantic_rows

    def direct_call_path(expression: ast.AST) -> str:
        parts: list[str] = []
        cursor = expression
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name) and parts:
            return ".".join([cursor.id, *reversed(parts)])
        return ""

    generated_call_paths: set[str] = set()
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        generated_call_paths.update(
            call_path.casefold()
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            for call_path in [direct_call_path(call.func)]
            if call_path
        )

    unresolved_rows: list[dict[str, str]] = []
    for row in semantic_rows:
        requirement_text = str(
            row.get("text")
            or row.get("requirement")
            or row.get("description")
            or ""
        )
        requested_paths = list(dict.fromkeys(re.findall(
            r"\b((?:unreal|maya(?:\.cmds)?|cmds|bpy|pyfbsdk|"
            r"PySide6|PySide2|PyQt6|PyQt5)"
            r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*\(",
            requirement_text,
        )))
        if not requested_paths:
            unresolved_rows.append(row)
            continue
        requested_actions = {
            path.rsplit(".", 1)[-1].casefold().split("_", 1)[0]
            for path in requested_paths
        }
        semantic_actions = {
            match.casefold()
            for match in re.findall(
                r"\b(call|connect|execute|load|normalize|report|return|"
                r"save|set|stream|validate)\w*\b",
                requirement_text,
                flags=re.IGNORECASE,
            )
        }
        allowed_actions = requested_actions | {"call", "execute"}
        all_calls_present = all(
            any(
                actual == expected.casefold()
                or actual.endswith(
                    "." + ".".join(expected.split(".")[-2:]).casefold()
                )
                for actual in generated_call_paths
            )
            for expected in requested_paths
        )
        if not all_calls_present or not semantic_actions <= allowed_actions:
            unresolved_rows.append(row)
    return unresolved_rows


def _production_evidence_candidate_is_admissible(
    candidate: Mapping[str, Any],
    requirement_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Return whether evidence may authorize a production implementation call."""

    name = str(candidate.get("name") or "")
    path = str(candidate.get("path") or "").replace("\\", "/")
    kind = str(candidate.get("kind") or "").casefold()
    provider = str(candidate.get("provider") or "").casefold()
    requirement_text = " ".join(
        str(row.get("text") or row.get("requirement") or "")
        for row in requirement_rows
    ).casefold()
    normalized_identity = f"{name} {path} {kind} {provider}".casefold()
    direct_unreal_request = bool(re.search(
        r"\bimport\s+unreal\b|\bunreal\.[A-Za-z_]",
        requirement_text,
    ))
    if direct_unreal_request:
        unreal_native = name.casefold().startswith("unreal.") or (
            "unreal_capability_graph" in provider
            and "unreal" in normalized_identity
        )
        unreal_internal = bool(re.search(
            r"\b(?:adapter|bridge|service)\b",
            requirement_text,
        )) and (
            name.casefold().startswith("tech_connector.bridges.unreal.")
            or name.casefold().startswith("tech_connector.services.unreal.")
        )
        if not (unreal_native or unreal_internal):
            return False
    prohibited_terms = {
        token.casefold()
        for pattern in (
            r"\bwithout\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\brather\s+than\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\binstead\s+of\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\bdo\s+not\s+([A-Za-z_][A-Za-z0-9_]*)",
            r"\bmust\s+not\s+([A-Za-z_][A-Za-z0-9_]*)",
        )
        for token in re.findall(
            pattern,
            requirement_text,
            flags=re.IGNORECASE,
        )
    }
    candidate_leaf_terms = {
        token.casefold()
        for token in re.findall(
            r"[A-Za-z][A-Za-z0-9]*",
            name.rsplit(".", 1)[-1].replace("_", " "),
        )
        if len(token) >= 3
    }
    if any(
        candidate_term == prohibited_term
        or (
            min(len(candidate_term), len(prohibited_term)) >= 5
            and candidate_term[:6] == prohibited_term[:6]
        )
        for candidate_term in candidate_leaf_terms
        for prohibited_term in prohibited_terms
    ):
        return False
    non_authorizing_markers = (
        "/tests/",
        "/test/",
        "/examples/",
        "/example/",
        "/benchmarks/",
        "/benchmark/",
        "/fixtures/",
        "/fixture/",
        ".tests.",
        ".test.",
        ".examples.",
        ".example.",
        "testcase",
    )
    if (
        kind in {"test", "test_method", "fixture", "example"}
        or name.rsplit(".", 1)[-1].startswith("test_")
        or any(marker in normalized_identity for marker in non_authorizing_markers)
    ):
        return False
    internal_only = bool(re.search(
        r"\b(?:internal|adapter|bridge)\b.*\b(?:capability|callable|api)\b"
        r"|\buse\s+(?:an?\s+)?existing\s+internal\b"
        r"|\brather\s+than\s+import(?:ing)?\b",
        requirement_text,
    ))
    if internal_only and (
        "/site-packages/" in path.casefold()
        or "/.venv/" in path.casefold()
        or provider in {
            "installed_package",
            "installed_package_stub",
            "official_public_api",
        }
    ):
        return False
    return True


def _requirement_owner_paths(
    implementation_plan: dict[str, Any],
    requirement_id: str,
) -> set[str]:
    """Return normalized generated-file owners for one approved requirement."""

    paths: set[str] = set()
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        owned_ids = {
            str(value)
            for value in chunk.get("requirement_ids") or []
            if str(value)
        }
        owned_ids.update(
            str(item.get("requirement_id") or "")
            for key in ("implementation_mechanics", "validation_cases")
            for item in chunk.get(key) or []
            if isinstance(item, dict)
        )
        if requirement_id not in owned_ids:
            continue
        path = str(chunk.get("path") or chunk.get("file") or "")
        if path:
            paths.add(path.replace("\\", "/").casefold())
    return paths


def _requirement_source_hash(
    requirement_id: str,
    *,
    implementation_plan: dict[str, Any],
    generated_files: list[tuple[str, str, str]],
) -> str:
    """Hash only source owned by a requirement, falling back to the package."""

    owner_paths = _requirement_owner_paths(
        implementation_plan,
        requirement_id,
    )
    selected = [
        [path, source]
        for path, _original, source in generated_files
        if not owner_paths
        or any(
            path.replace("\\", "/").casefold().endswith(owner_path)
            or Path(path).name.casefold() == Path(owner_path).name.casefold()
            for owner_path in owner_paths
        )
    ]
    if not selected:
        selected = [
            [path, source] for path, _original, source in generated_files
        ]
    return _checkpoint_hash({
        "semantic_proof_contract": "source-backed-semantic-proof-v2",
        "owned_source": selected,
    })


def _generated_files_for_requirements(
    requirement_rows: list[dict[str, str]],
    *,
    implementation_plan: dict[str, Any],
    generated_files: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Return the smallest proven file set owning the supplied requirements."""

    owner_paths: set[str] = set()
    for row in requirement_rows:
        requirement_id = str(
            row.get("id") or row.get("requirement_id") or ""
        )
        paths = _requirement_owner_paths(
            implementation_plan,
            requirement_id,
        )
        if not paths:
            return generated_files
        owner_paths.update(paths)
    selected = [
        item
        for item in generated_files
        if any(
            item[0].replace("\\", "/").casefold().endswith(owner_path)
            or Path(item[0]).name.casefold() == Path(owner_path).name.casefold()
            for owner_path in owner_paths
        )
    ]
    return selected or generated_files


def _clean_final_review_requirement_ids(
    response: str,
    requirement_ledger: list[dict[str, str]],
) -> set[str]:
    """Return requirement IDs with one grounded, fully met review row."""

    text = str(response or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        object_match = re.search(r"\{.*\}", text, re.DOTALL)
        if object_match:
            text = object_match.group(0)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    ledger = {
        str(row.get("id") or row.get("requirement_id") or ""): str(
            row.get("text")
            or row.get("requirement")
            or row.get("description")
            or ""
        )
        for row in requirement_ledger
    }
    issue_ids = {
        str(
            issue.get("requirement_id")
            or (next(iter(ledger)) if len(ledger) == 1 else "")
        )
        for issue in payload.get("issues") or []
        if isinstance(issue, dict)
    }
    rows_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("coverage") or []:
        if not isinstance(row, dict):
            continue
        requirement_id = str(row.get("requirement_id") or "")
        if requirement_id in ledger:
            rows_by_id.setdefault(requirement_id, []).append(row)
    clean: set[str] = set()
    for requirement_id, rows in rows_by_id.items():
        if len(rows) != 1 or requirement_id in issue_ids:
            continue
        checks = rows[0].get("checks") or rows[0].get("obligations")
        if not isinstance(checks, list) or not checks:
            continue
        if all(
            isinstance(check, dict)
            and str(check.get("verdict") or "").casefold() == "met"
            and len(str(check.get("evidence") or "").strip()) >= 8
            for check in checks
        ):
            clean.add(requirement_id)
    return clean


def _parse_final_requirement_review(
    response: str,
    *,
    requirement_ledger: list[dict[str, str]],
    generated_files: list[tuple[str, str, str]],
) -> list[str]:
    """Convert final-review JSON into focused, repairable validation evidence."""

    text = str(response or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        object_match = re.search(r"\{.*\}", text, re.DOTALL)
        if object_match:
            text = object_match.group(0)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return [
            "Final requirement review was not valid JSON; rerun it before "
            "declaring the package production-ready."
        ]
    raw_issues = payload.get("issues") if isinstance(payload, dict) else None
    if not isinstance(raw_issues, list):
        return ["Final requirement review omitted its required issues list."]
    ledger = {
        str(item.get("id") or item.get("requirement_id") or ""): str(
            item.get("text")
            or item.get("requirement")
            or item.get("description")
            or ""
        )
        for item in requirement_ledger
        if str(item.get("id") or item.get("requirement_id") or "")
    }
    raw_coverage = payload.get("coverage") if isinstance(payload, dict) else None
    coverage_owner_by_id = {
        str(row.get("requirement_id") or ""): str(row.get("owner") or "").strip()
        for row in raw_coverage or []
        if isinstance(row, dict)
        and str(row.get("requirement_id") or "") in ledger
        and str(row.get("owner") or "").strip()
    }
    issues: list[Any] = []
    for raw_issue in raw_issues:
        if not isinstance(raw_issue, dict):
            issues.append(raw_issue)
            continue
        issue = dict(raw_issue)
        requirement_id = str(issue.get("requirement_id") or "").strip()
        if not requirement_id and len(ledger) == 1:
            requirement_id = next(iter(ledger))
            issue["requirement_id"] = requirement_id
        if requirement_id and not str(issue.get("owner") or "").strip():
            coverage_owner = coverage_owner_by_id.get(requirement_id, "")
            if coverage_owner:
                issue["owner"] = coverage_owner
        issues.append(issue)
    generated_source = "\n".join(
        source for _path, _original, source in generated_files
    ).casefold()

    def matching_owner_sources(owner: str) -> list[tuple[str, str]]:
        """Resolve colon-path and dotted reviewer owners to generated source.

        :param owner: reviewer owner such as ``file.py:Class.method`` or a
            dotted ``package.module.Class.method`` name
        :return: pairs containing matching source and the local owner symbol
        """

        raw_owner = str(owner or "").strip()
        if not raw_owner:
            return []
        normalized_owner = raw_owner.replace("\\", "/")
        python_separator = normalized_owner.casefold().rfind(".py:")
        declared_path = ""
        declared_symbol = ""
        if python_separator >= 0:
            declared_path = normalized_owner[:python_separator + 3]
            declared_symbol = normalized_owner[python_separator + 4:]

        matches: list[tuple[str, str]] = []
        for path, _original, source in generated_files:
            normalized_path = str(path).replace("\\", "/")
            if declared_path:
                if not (
                    Path(normalized_path).name.casefold()
                    == Path(declared_path).name.casefold()
                    or normalized_path.casefold().endswith(
                        declared_path.casefold()
                    )
                ):
                    continue
                matches.append((source, declared_symbol))
                continue

            module_parts = Path(normalized_path).with_suffix("").parts
            module_candidates = [
                ".".join(module_parts[index:]).casefold()
                for index in range(len(module_parts))
                if module_parts[index]
                and module_parts[index] not in {"/", "\\"}
            ]
            owner_lower = raw_owner.casefold()
            matching_modules = [
                module
                for module in module_candidates
                if owner_lower == module or owner_lower.startswith(module + ".")
            ]
            if not matching_modules:
                continue
            module = max(matching_modules, key=len)
            symbol = raw_owner[len(module):].lstrip(".")
            matches.append((source, symbol))
        return matches

    def worker_wiring_is_already_proven(
        owner: str,
        requirement_text: str,
        evidence_text: str,
        repair_text: str,
    ) -> bool:
        claim = " ".join(
            (requirement_text, evidence_text, repair_text)
        ).casefold()
        if not (
            re.search(r"\b(?:background|thread|worker)\b", claim)
            and re.search(r"\b(?:connect|signal|start|off[- ]?ui)\b", claim)
        ):
            return False
        for source, owner_symbol in matching_owner_sources(owner):
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            class_name = owner_symbol.split(".", 1)[0]
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
            helper_names = {
                node.name
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and any(
                    (
                        isinstance(base, ast.Name)
                        and base.id in {"QThread", "QRunnable"}
                    )
                    or (
                        isinstance(base, ast.Attribute)
                        and base.attr in {"QThread", "QRunnable"}
                    )
                    for base in node.bases
                )
            }
            worker_attributes = {
                target.attr
                for assignment in ast.walk(class_node)
                if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                and isinstance(assignment.value, ast.Call)
                and (
                    (
                        isinstance(assignment.value.func, ast.Name)
                        and assignment.value.func.id in helper_names
                    )
                    or (
                        isinstance(assignment.value.func, ast.Attribute)
                        and assignment.value.func.attr in helper_names
                    )
                )
                for target in (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                if isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            }
            connected_signals = {
                call.func.value.attr.casefold()
                for call in ast.walk(class_node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "connect"
                and isinstance(call.func.value, ast.Attribute)
                and isinstance(call.func.value.value, ast.Attribute)
                and isinstance(call.func.value.value.value, ast.Name)
                and call.func.value.value.value.id == "self"
                and call.func.value.value.attr in worker_attributes
            }
            has_start = any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "start"
                and isinstance(call.func.value, ast.Attribute)
                and isinstance(call.func.value.value, ast.Name)
                and call.func.value.value.id == "self"
                and call.func.value.attr in worker_attributes
                for call in ast.walk(class_node)
            )
            requested_signals = {
                signal
                for signal in ("result", "error", "progress", "finished")
                if re.search(rf"\b{signal}\b", claim)
            }
            if (
                helper_names
                and worker_attributes
                and has_start
                and requested_signals.issubset(connected_signals)
            ):
                return True
        return False

    def explicit_result_contract_is_already_proven(
        owner: str,
        requirement_text: str,
    ) -> bool:
        """Return whether executable source disproves a result-contract issue.

        :param owner: Reviewer-supplied file and callable owner.
        :param requirement_text: Authoritative requirement clause.
        :return: True when the exact result behavior is structurally proven.
        """

        lowered_requirement = requirement_text.casefold()
        requires_resolved_path = "return a resolved path" in lowered_requirement
        requires_none_only = "only none as a missing result" in lowered_requirement
        requires_envelope = all(
            phrase in lowered_requirement
            for phrase in (
                "explicit 'ok' field",
                "exactly ok, value, and error keys",
                "defaulting missing value to none",
                "missing error to an empty string",
            )
        )
        if not (requires_resolved_path or requires_none_only or requires_envelope):
            return False
        for source, owner_symbol in matching_owner_sources(owner):
            callable_name = owner_symbol.rsplit(".", 1)[-1]
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            function = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == callable_name
                ),
                None,
            )
            if function is None:
                continue
            arguments = [*function.args.posonlyargs, *function.args.args]
            payload = next(
                (
                    argument.arg
                    for argument in arguments
                    if argument.arg not in {"self", "cls"}
                ),
                "",
            )
            if not payload:
                continue
            resolved_path_proven = not requires_resolved_path
            if requires_resolved_path:
                for returned in (
                    node for node in ast.walk(function) if isinstance(node, ast.Return)
                ):
                    if (
                        isinstance(returned.value, ast.Call)
                        and isinstance(returned.value.func, ast.Attribute)
                        and returned.value.func.attr == "resolve"
                    ):
                        resolved_path_proven = True
                        break
                    if not isinstance(returned.value, ast.Name):
                        continue
                    returned_name = returned.value.id
                    resolved_path_proven = any(
                        isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        and getattr(assignment, "lineno", 0)
                        < getattr(returned, "lineno", 0)
                        and any(
                            isinstance(target, ast.Name)
                            and target.id == returned_name
                            for target in (
                                assignment.targets
                                if isinstance(assignment, ast.Assign)
                                else [assignment.target]
                            )
                        )
                        and isinstance(assignment.value, ast.Call)
                        and isinstance(assignment.value.func, ast.Attribute)
                        and assignment.value.func.attr == "resolve"
                        for assignment in ast.walk(function)
                    )
                    if resolved_path_proven:
                        break
            none_only_proven = not requires_none_only or any(
                isinstance(branch.test, ast.Compare)
                and isinstance(branch.test.left, ast.Name)
                and branch.test.left.id == payload
                and len(branch.test.ops) == 1
                and isinstance(branch.test.ops[0], ast.Is)
                and len(branch.test.comparators) == 1
                and isinstance(branch.test.comparators[0], ast.Constant)
                and branch.test.comparators[0].value is None
                for branch in ast.walk(function)
                if isinstance(branch, ast.If)
            )
            envelope_proven = not requires_envelope
            for branch in (
                node for node in ast.walk(function) if isinstance(node, ast.If)
            ):
                if not requires_envelope:
                    break
                has_ok_guard = any(
                    isinstance(comparison, ast.Compare)
                    and isinstance(comparison.left, ast.Constant)
                    and comparison.left.value == "ok"
                    and any(isinstance(operation, ast.In) for operation in comparison.ops)
                    and any(
                        isinstance(comparator, ast.Name)
                        and comparator.id == payload
                        for comparator in comparison.comparators
                    )
                    for comparison in ast.walk(branch.test)
                )
                returned = next(
                    (
                        statement.value
                        for statement in branch.body
                        if isinstance(statement, ast.Return)
                        and isinstance(statement.value, ast.Dict)
                    ),
                    None,
                )
                if not has_ok_guard or returned is None:
                    continue
                has_mapping_guard = any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "isinstance"
                    and len(call.args) >= 2
                    and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == payload
                    for call in ast.walk(branch.test)
                )
                if not has_mapping_guard:
                    continue
                keyed_values = {
                    str(key.value): value
                    for key, value in zip(returned.keys, returned.values)
                    if isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                }
                if set(keyed_values) != {"ok", "value", "error"}:
                    continue

                def mapping_get_default(
                    expression: ast.AST,
                    key: str,
                    default: object,
                ) -> bool:
                    return bool(
                        isinstance(expression, ast.Call)
                        and isinstance(expression.func, ast.Attribute)
                        and isinstance(expression.func.value, ast.Name)
                        and expression.func.value.id == payload
                        and expression.func.attr == "get"
                        and expression.args
                        and isinstance(expression.args[0], ast.Constant)
                        and expression.args[0].value == key
                        and (
                            len(expression.args) == 1
                            and default is None
                            or len(expression.args) >= 2
                            and isinstance(expression.args[1], ast.Constant)
                            and expression.args[1].value == default
                        )
                    )

                if mapping_get_default(
                    keyed_values["value"], "value", None
                ) and mapping_get_default(
                    keyed_values["error"], "error", ""
                ):
                    envelope_proven = True
                    break
            if resolved_path_proven and none_only_proven and envelope_proven:
                return True
        return False

    def explicit_docstring_contract_is_already_proven(
        owner: str,
        requirement_text: str,
    ) -> bool:
        """Return whether source proves an explicit typed-docstring contract.

        :param owner: reviewer-supplied file and callable owner
        :param requirement_text: authoritative requirement clause
        :return: whether annotations and requested fields are present
        """

        lowered_requirement = requirement_text.casefold()
        if "docstring" not in lowered_requirement:
            return False
        for source, owner_symbol in matching_owner_sources(owner):
            callable_name = owner_symbol.rsplit(".", 1)[-1]
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            function = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == callable_name
                ),
                None,
            )
            if function is None:
                continue
            parameters = [
                argument
                for argument in [
                    *function.args.posonlyargs,
                    *function.args.args,
                    *function.args.kwonlyargs,
                ]
                if argument.arg not in {"self", "cls"}
            ]
            if "type hint" in lowered_requirement and (
                function.returns is None
                or any(argument.annotation is None for argument in parameters)
            ):
                continue
            docstring = ast.get_docstring(function, clean=False) or ""
            if not docstring.strip():
                continue
            if "restructuredtext fields" in lowered_requirement and not all(
                field in docstring
                for field in [
                    *(f":param {argument.arg}:" for argument in parameters),
                    ":return:",
                ]
            ):
                continue
            return True
        return False

    def explicit_command_registry_contract_is_already_proven(
        owner: str,
        requirement_text: str,
    ) -> bool:
        """Reject registry findings contradicted by the exact return expression.

        :param owner: reviewer-supplied file and callable owner
        :param requirement_text: authoritative requirement clause
        :return: whether the registry return contract is structurally proven
        """

        lowered_requirement = requirement_text.casefold()
        proves_handler = "return the handler" in lowered_requirement
        proves_listing = (
            "list_commands" in lowered_requirement
            and "sorted canonical names only" in lowered_requirement
        )
        proves_normalization = (
            "normalize names with strip and casefold" in lowered_requirement
        )
        if not (proves_handler or proves_listing or proves_normalization):
            return False
        for source, owner_symbol in matching_owner_sources(owner):
            callable_name = owner_symbol.rsplit(".", 1)[-1]
            if proves_handler and callable_name != "resolve":
                continue
            if proves_listing and callable_name != "list_commands":
                continue
            if proves_normalization and callable_name != "register":
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            function = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == callable_name
                ),
                None,
            )
            if function is None:
                continue
            if proves_normalization:
                class_name = owner_symbol.split(".", 1)[0]
                class_node = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.ClassDef)
                        and node.name == class_name
                    ),
                    None,
                )
                normalizer = next(
                    (
                        node
                        for node in class_node.body
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == "_normalize"
                    ),
                    None,
                ) if class_node is not None else None
                normalized_arguments = {
                    argument.id
                    for call in ast.walk(function)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "_normalize"
                    for argument in call.args
                    if isinstance(argument, ast.Name)
                }
                has_strip_casefold = bool(
                    normalizer is not None
                    and any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "casefold"
                        and isinstance(call.func.value, ast.Call)
                        and isinstance(call.func.value.func, ast.Attribute)
                        and call.func.value.func.attr == "strip"
                        for call in ast.walk(normalizer)
                    )
                )
                if has_strip_casefold and "name" in normalized_arguments:
                    return True
            returns = [
                node.value
                for node in ast.walk(function)
                if isinstance(node, ast.Return) and node.value is not None
            ]
            if proves_handler and any(
                isinstance(value, ast.Subscript)
                and isinstance(value.value, ast.Attribute)
                and isinstance(value.value.value, ast.Name)
                and value.value.value.id == "self"
                and value.value.attr in {"commands", "_commands"}
                for value in returns
            ):
                return True
            if proves_listing and any(
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "sorted"
                and value.args
                and (
                    isinstance(value.args[0], ast.Attribute)
                    and isinstance(value.args[0].value, ast.Name)
                    and value.args[0].value.id == "self"
                    and value.args[0].attr in {"commands", "_commands"}
                    or isinstance(value.args[0], ast.Call)
                    and isinstance(value.args[0].func, ast.Attribute)
                    and value.args[0].func.attr == "keys"
                    and isinstance(value.args[0].func.value, ast.Attribute)
                    and isinstance(value.args[0].func.value.value, ast.Name)
                    and value.args[0].func.value.value.id == "self"
                    and value.args[0].func.value.attr in {"commands", "_commands"}
                )
                for value in returns
            ):
                return True
        return False

    def explicit_asset_operation_contract_is_already_proven(
        owner: str,
        requirement_text: str,
    ) -> bool:
        """Prove explicit asset-pipeline clauses across their real owners.

        :param owner: reviewer-supplied operation owner
        :param requirement_text: authoritative operation requirement
        :return: whether generated source structurally proves the clause
        """

        lowered = requirement_text.casefold()
        sources = {
            Path(path).name: source
            for path, _original, source in generated_files
        }
        operation_source = sources.get("operations.py", "")
        planner_source = sources.get("planner.py", "")
        wrapper_source = sources.get("wrappers.py", "")
        executor_source = sources.get("executor.py", "")
        try:
            normalized_operation_source = ast.unparse(
                ast.parse(operation_source)
            ) if operation_source else ""
        except SyntaxError:
            normalized_operation_source = ""
        if "operations['asset.configure']" in lowered:
            return bool(normalized_operation_source) and all(
                token in normalized_operation_source
                for token in (
                    "connector.game_engine.wrappers.configure_asset",
                    "('asset_path', 'value')",
                    "{'save': True}",
                )
            )
        if "plan_asset_configuration must return a fresh request" in lowered:
            if not planner_source:
                return False
            try:
                tree = ast.parse(planner_source)
            except SyntaxError:
                return False
            function = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "plan_asset_configuration"
                ),
                None,
            )
            return bool(
                function is not None
                and "json.dumps" not in ast.unparse(function)
                and all(
                    repr(key) in ast.unparse(function)
                    for key in ("operation", "params", "asset_path", "value", "save")
                )
            )
        if "report all missing or unexpected parameter names" in lowered:
            return bool(normalized_operation_source) and all(
                token in normalized_operation_source
                for token in (
                    "missing = sorted",
                    "unexpected = sorted",
                    "raise TypeError",
                )
            )
        if "registered wrapper rather than a native host method" in lowered:
            return bool(executor_source) and all(
                token in executor_source
                for token in (
                    "build_operation_call",
                    "importlib.import_module",
                )
            ) and "host_api" not in executor_source
        if "json-serialize value exactly once" in lowered:
            return bool(wrapper_source) and bool(
                "isinstance(asset_path, str)" in wrapper_source
                and ".strip()" in wrapper_source
                and wrapper_source.count("json.dumps(value)") == 1
                and "bool(save)" in wrapper_source
                and "host_api.NativeLibrary.configure_asset" in wrapper_source
            )
        if "preserve native return values including falsey ones" in lowered:
            return bool(wrapper_source) and bool(
                re.search(
                    r"return\s+host_api\.NativeLibrary\.configure_asset\s*\(",
                    wrapper_source,
                )
            )
        return False

    errors: list[str] = []
    coverage = raw_coverage
    if not isinstance(coverage, list):
        errors.append(
            "Final requirement review omitted per-requirement coverage evidence."
        )
        coverage = []
    coverage_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in coverage:
        if not isinstance(row, dict):
            continue
        requirement_id = str(row.get("requirement_id") or "").strip()
        if requirement_id in ledger:
            coverage_by_id.setdefault(requirement_id, []).append(row)
    missing_coverage = sorted(set(ledger) - set(coverage_by_id))
    if missing_coverage:
        errors.append(
            "Final requirement review did not inspect requirement IDs: "
            + ", ".join(missing_coverage)
        )
    for requirement_id, rows in coverage_by_id.items():
        requirement_text = ledger[requirement_id]
        for row in rows:
            checks = row.get("checks") or row.get("obligations")
            if not isinstance(checks, list) or not checks:
                errors.append(
                    f"Final requirement review supplied no obligation evidence for "
                    f"{requirement_id}."
                )
                continue
            for check in checks:
                if not isinstance(check, dict):
                    errors.append(
                        f"Final requirement review supplied malformed obligation "
                        f"evidence for {requirement_id}."
                    )
                    continue
                verdict = str(check.get("verdict") or "").strip().lower()
                evidence_text = str(check.get("evidence") or "").strip()
                if (
                    verdict not in {"met", "unmet"}
                    or len(evidence_text) < 8
                ):
                    errors.append(
                        f"Final requirement review supplied ungrounded obligation "
                        f"evidence for {requirement_id}."
                    )
                if verdict == "unmet" and not any(
                    isinstance(issue, dict)
                    and str(issue.get("requirement_id") or "").strip()
                    == requirement_id
                    for issue in issues
                ):
                    errors.append(
                        f"Final requirement review marked {requirement_id} unmet "
                        "without a repairable issue."
                    )
                owner = str(
                    check.get("owner") or row.get("owner") or ""
                ).strip()
                result_contract_requirement = any(
                    phrase in requirement_text.casefold()
                    for phrase in (
                        "only none as a missing result",
                        "explicit 'ok' field",
                        "return a resolved path",
                    )
                )
                if (
                    verdict == "met"
                    and owner
                    and result_contract_requirement
                    and not explicit_result_contract_is_already_proven(
                        owner,
                        requirement_text,
                    )
                ):
                    errors.append(
                        f"Final requirement review [implementation] {owner}: unmet "
                        f"{requirement_id} '{requirement_text}'. Evidence: "
                        "deterministic source inspection could not prove the "
                        "declared result contract. Smallest repair: implement the "
                        "authoritative result branches exactly."
                    )
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        requirement_id = str(issue.get("requirement_id") or "").strip()
        authoritative_requirement = ledger.get(requirement_id, "")
        if not authoritative_requirement:
            continue
        owner = str(issue.get("owner") or "").strip()
        evidence_text = str(issue.get("evidence") or "").strip()
        repair = str(issue.get("repair") or "").strip()
        category = str(issue.get("category") or "implementation").strip()
        missing_observable = str(
            issue.get("missing_observable") or ""
        ).strip()
        if (
            not owner
            or not evidence_text
            or category not in {
                "implementation",
                "api",
                "wiring",
                "validation",
                "callback",
                "test_coverage",
            }
            or not missing_observable
            or missing_observable.casefold()
            not in authoritative_requirement.casefold()
        ):
            continue
        if (
            category == "test_coverage"
            and not re.search(
                r"\b(?:assert(?:ion|s|ed|ing)?|check(?:s|ed|ing)?|"
                r"proof|prove[sd]?|self[-_ ]?test|test(?:s|ed|ing)?|"
                r"validat(?:e|es|ed|ing|ion))\b",
                authoritative_requirement,
                flags=re.IGNORECASE,
            )
        ):
            continue
        owner_leaf = owner.rsplit(":", 1)[-1].rsplit(".", 1)[-1].strip()
        owner_leaf_lower = owner_leaf.casefold()
        authoritative_lower = authoritative_requirement.casefold()
        if (
            owner_leaf_lower not in {"<module>", "__init__", "__main__"}
            and owner_leaf_lower not in authoritative_lower
            and re.search(
                rf"\b{re.escape(owner_leaf_lower)}\b",
                generated_source,
            )
            is None
        ):
            continue
        issue_blob = "\n".join((evidence_text, repair))
        code_identifiers = {
            token.casefold()
            for token in re.findall(
                r"`([A-Za-z_][A-Za-z0-9_.]*)`"
                r"|\b([A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*)\b",
                issue_blob,
            )
            for token in token
            if token
        }
        if any(
            identifier not in authoritative_lower
            and re.search(
                rf"\b{re.escape(identifier)}\b",
                generated_source,
            )
            is None
            for identifier in code_identifiers
        ):
            continue
        if worker_wiring_is_already_proven(
            owner,
            authoritative_requirement,
            evidence_text,
            repair,
        ):
            continue
        if explicit_result_contract_is_already_proven(
            owner,
            authoritative_requirement,
        ):
            continue
        if explicit_docstring_contract_is_already_proven(
            owner,
            authoritative_requirement,
        ):
            continue
        if explicit_command_registry_contract_is_already_proven(
            owner,
            authoritative_requirement,
        ):
            continue
        if explicit_asset_operation_contract_is_already_proven(
            owner,
            authoritative_requirement,
        ):
            continue
        errors.append(
            f"Final requirement review [{category}] {owner}: unmet "
            f"{requirement_id} '{authoritative_requirement}'. "
            f"Evidence: {evidence_text}. Smallest repair: {repair}"
        )
    ready = bool(payload.get("ready")) if isinstance(payload, dict) else False
    if ready and errors:
        errors.append(
            "Final requirement review contradicted itself by marking a package "
            "with unmet requirements ready."
        )
    # Coverage and grounded issues are authoritative. A redundant false `ready`
    # flag cannot override complete met coverage with an empty issue list.
    return errors


def _focused_repair_quality_errors(
    errors: list[str],
) -> tuple[str, list[str]]:
    """Select one quality category per repair cycle without hiding failures."""

    def host_runtime_import_diagnostic(error: str) -> bool:
        lowered = str(error or "").lower()
        mentions_host = bool(
            re.search(r"\b(?:unreal|maya|cmds|bpy|pyfbsdk)\b", lowered)
        )
        import_shaped = any(
            marker in lowered
            for marker in (
                "host-module access",
                "host-local",
                "could not be resolved",
                "undefined name",
                "undefined names",
                "missing import",
                "new import",
            )
        )
        return mentions_host and import_shaped

    categories = (
        ("syntax", ("syntax", "did not parse", "parse and compile", "compile:")),
        (
            "imports",
            (
                "new import",
                "missing import",
                "could not be resolved",
                "undefined name",
                "undefined names",
                "unresolved",
                "does not expose",
            ),
        ),
        (
            "api",
            (
                "api call",
                "api path",
                "runtime api",
                "patch targets do not resolve",
                "requested runtime",
                "create_asset",
                "authoritative unreal call signature",
                "host runtime calls lack",
            ),
        ),
        (
            "construction_and_wiring",
            (
                ".connect(",
                "signal handler",
                "widget constructor",
                "not reachable from __init__",
                "not importing a qt-compatible symbol surface",
            ),
        ),
        (
            "dead_code",
            (
                "never read",
                "dead code",
                "unused",
                "not consumed",
            ),
        ),
        (
            "behavioral_coverage",
            (
                "behavioral proof",
                "test methods",
                "fixture variables",
                "stronger behavioral",
            ),
        ),
        (
            "runtime",
            (
                "disposable generated-patch validation failed",
                "traceback",
                "assertionerror",
            ),
        ),
    )
    for category, markers in categories:
        focused = [
            error
            for error in errors
            if any(marker in str(error).lower() for marker in markers)
            and not (
                category == "imports"
                and host_runtime_import_diagnostic(error)
            )
        ]
        if focused:
            if category == "imports":
                focused.extend(
                    error
                    for error in errors
                    if host_runtime_import_diagnostic(error)
                    and error not in focused
                )
            return category, focused
    host_diagnostics = [
        error for error in errors if host_runtime_import_diagnostic(error)
    ]
    if host_diagnostics:
        return "api", host_diagnostics
    return "other", list(errors)


def _describe_top_level_symbols(
    generated_files: list[tuple[str, str, str]],
) -> str:
    """Return a compact per-file symbol trace without exposing full source."""

    descriptions: list[str] = []
    for path, _original_source, source in generated_files:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            descriptions.append(f"{Path(path).name}=[syntax-error]")
            continue
        symbols = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        descriptions.append(f"{Path(path).name}=[{', '.join(symbols)}]")
    return "; ".join(descriptions)


def _source_defines_symbol(
    source: str,
    symbol: str,
    objective: str = "",
) -> bool:
    """Return whether source defines a compatible module-level declaration."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and re.search(
                    rf"(?<![.\w]){re.escape(symbol)}\s*\(\s*\)",
                    objective,
                ):
                    positional = [*node.args.posonlyargs, *node.args.args]
                    required_positional = max(
                        0,
                        len(positional) - len(node.args.defaults),
                    )
                    required_keyword_only = sum(
                        default is None for default in node.args.kw_defaults
                    )
                    if required_positional or required_keyword_only:
                        return False
                return True
        elif isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == symbol
                for target in node.targets
            ):
                return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol:
                return True
    return False


def _manifest_symbol_name(raw_symbol: Any) -> str:
    """Normalize a manifest signature or label to one valid Python identifier."""

    value = re.sub(
        r"^(?:(?:async\s+)?def|async|class)\s+",
        "",
        str(raw_symbol or "").strip(),
        flags=re.IGNORECASE,
    ).split("(", 1)[0].rsplit(".", 1)[-1].strip()
    match = re.match(r"[A-Za-z_]\w*", value)
    return match.group(0) if match else ""


def _requested_immutable_record_errors(source: str, prompt: str) -> list[str]:
    """Reject mutable implementations of explicitly immutable named records."""

    requested = set(
        re.findall(
            r"\bimmutable\s+([A-Z][A-Za-z0-9_]*)\s+"
            r"(?:record|value|data(?:\s+class)?|dataclass|class|type)\b",
            prompt,
            flags=re.IGNORECASE,
        )
    )
    if not requested:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    errors: list[str] = []
    for symbol in sorted(requested):
        assignment = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == symbol
                    for target in node.targets
                )
            ),
            None,
        )
        if assignment is not None and isinstance(assignment.value, ast.Call):
            if ast.unparse(assignment.value.func).endswith(("namedtuple", "NamedTuple")):
                continue
        class_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == symbol
            ),
            None,
        )
        if class_node is None:
            continue
        named_tuple_base = any(
            ast.unparse(base).endswith(("NamedTuple", "tuple"))
            for base in class_node.bases
        )
        frozen_dataclass = any(
            isinstance(decorator, ast.Call)
            and ast.unparse(decorator.func).endswith("dataclass")
            and any(
                keyword.arg == "frozen"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in decorator.keywords
            )
            for decorator in class_node.decorator_list
        )
        if not (named_tuple_base or frozen_dataclass):
            errors.append(
                f"Requested immutable record {symbol} must use a frozen dataclass "
                "or named tuple."
            )
            continue
        if not frozen_dataclass:
            continue
        mutable_fields = [
            statement.target.id
            for statement in class_node.body
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and re.match(
                    r"^(?:dict|list|set|MutableMapping|MutableSequence|MutableSet)\b",
                    ast.unparse(statement.annotation),
                )
            )
        ]
        if not mutable_fields:
            continue
        post_init = next(
            (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__post_init__"
            ),
            None,
        )
        post_init_source = ast.unparse(post_init) if post_init is not None else ""
        for field_name in mutable_fields:
            if (
                re.search(
                    rf"object\.__setattr__\s*\(\s*self\s*,\s*"
                    rf"['\"]{re.escape(field_name)}['\"]",
                    post_init_source,
                )
                and re.search(
                    r"\b(?:MappingProxyType|frozenset|tuple|freeze|immutable)\b",
                    post_init_source,
                    re.IGNORECASE,
                )
            ):
                continue
            errors.append(
                f"Requested immutable record {symbol} has mutable-typed field "
                f"{field_name}; recursively detach it at construction and expose "
                "an immutable nested representation."
            )
    return errors


def _requested_public_constructor_errors(
    source: str,
    prompt: str,
    expected_symbols: list[str] | None = None,
) -> list[str]:
    """Reject invented parameters on every generated public class owner."""

    requested_classes = set(re.findall(
        r"\b(?:define|create|add|implement)\s+(?:an?\s+)?"
        r"([A-Z][A-Za-z0-9_]*)\b",
        prompt,
        flags=re.IGNORECASE,
    ))
    requested_classes.update(re.findall(
        r"\b([A-Z][A-Za-z0-9_]*)\s+must\s+define\b",
        prompt,
        flags=re.IGNORECASE,
    ))
    requested_classes.update(
        _manifest_symbol_name(symbol)
        for symbol in expected_symbols or []
        if _manifest_symbol_name(symbol)
        and _manifest_symbol_name(symbol)[:1].isupper()
        and not _manifest_symbol_name(symbol).startswith("_")
    )
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if not requested_classes:
        requested_classes = {
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and not node.name.startswith("_")
        }

    errors: list[str] = []
    for class_node in (
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in requested_classes
    ):
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
        qt_owner = class_node.name.endswith(("Dialog", "Widget", "Window")) or any(
            ast.unparse(base).endswith(("Dialog", "Widget", "Window"))
            for base in class_node.bases
        )
        for argument in (
            *constructor.args.posonlyargs,
            *constructor.args.args,
            *constructor.args.kwonlyargs,
        ):
            parameter = argument.arg
            if parameter in {"self", "cls"}:
                continue
            if qt_owner and parameter in {"parent", "parent_widget"}:
                continue
            phrase_pattern = r"\b" + r"[\s_-]+".join(
                re.escape(part)
                for part in parameter.split("_")
                if part
            ) + r"\b"
            if re.search(phrase_pattern, prompt, flags=re.IGNORECASE):
                continue
            errors.append(
                f"{class_node.name}.__init__ invents public parameter "
                f"{parameter!r}; constructors may accept only request-owned or "
                "verified base-signature parameters."
            )
    return errors
