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


def _repair_qt_result_consumer_contract(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Apply one checkbox filter while presenting real worker result records."""

    targets: dict[tuple[str, str, str], str] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<class>[A-Za-z_][A-Za-z0-9_]*)\."
        r"(?P<method>[A-Za-z_][A-Za-z0-9_]*): approved result filter "
        r"`(?P<checkbox>[A-Za-z_][A-Za-z0-9_]*)` must be read and applied "
        r"inside the result consumer\."
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets[
                (
                    str(Path(match.group("path")).resolve()),
                    match.group("class"),
                    match.group("method"),
                )
            ] = match.group("checkbox")
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        matching = {
            (class_name, method_name): checkbox
            for (target_path, class_name, method_name), checkbox in targets.items()
            if target_path == str(Path(path).resolve())
        }
        if not matching:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
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
            widget_types: dict[str, str] = {}
            for assignment in [
                node
                for node in ast.walk(constructor)
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Attribute)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "self"
                and isinstance(node.value, ast.Call)
            ]:
                if isinstance(assignment.value.func, ast.Name):
                    widget_types[assignment.targets[0].attr] = (
                        assignment.value.func.id
                    )
                elif isinstance(assignment.value.func, ast.Attribute):
                    widget_types[assignment.targets[0].attr] = (
                        assignment.value.func.attr
                    )
            list_widgets = [
                name
                for name, widget_type in widget_types.items()
                if widget_type == "QListWidget"
            ]
            status_widgets = [
                name
                for name, widget_type in widget_types.items()
                if widget_type == "QLabel"
            ]
            if len(list_widgets) != 1:
                continue
            for method in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                checkbox_name = matching.get((class_node.name, method.name))
                if (
                    not checkbox_name
                    or widget_types.get(checkbox_name) != "QCheckBox"
                ):
                    continue
                positional = [
                    *method.args.posonlyargs,
                    *method.args.args,
                ]
                if len(positional) < 2:
                    continue
                result_name = positional[1].arg
                state_name = re.sub(
                    r"_checkbox$",
                    "",
                    re.sub(r"^include_", "", checkbox_name),
                )
                include_local = f"include_{state_name}"
                record_local = "record"
                label_local = "display_value"
                retained_docstring: list[ast.stmt] = []
                if (
                    method.body
                    and isinstance(method.body[0], ast.Expr)
                    and isinstance(method.body[0].value, ast.Constant)
                    and isinstance(method.body[0].value.value, str)
                ):
                    retained_docstring.append(method.body[0])
                statements: list[ast.stmt] = [
                    *retained_docstring,
                    ast.Assign(
                        targets=[
                            ast.Name(id=include_local, ctx=ast.Store())
                        ],
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=checkbox_name,
                                    ctx=ast.Load(),
                                ),
                                attr="isChecked",
                                ctx=ast.Load(),
                            ),
                            args=[],
                            keywords=[],
                        ),
                    ),
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=list_widgets[0],
                                    ctx=ast.Load(),
                                ),
                                attr="clear",
                                ctx=ast.Load(),
                            ),
                            args=[],
                            keywords=[],
                        )
                    ),
                    ast.For(
                        target=ast.Name(id=record_local, ctx=ast.Store()),
                        iter=ast.Name(id=result_name, ctx=ast.Load()),
                        body=[
                            ast.If(
                                test=ast.BoolOp(
                                    op=ast.And(),
                                    values=[
                                        ast.UnaryOp(
                                            op=ast.Not(),
                                            operand=ast.Name(
                                                id=include_local,
                                                ctx=ast.Load(),
                                            ),
                                        ),
                                        ast.Call(
                                            func=ast.Attribute(
                                                value=ast.Name(
                                                    id=record_local,
                                                    ctx=ast.Load(),
                                                ),
                                                attr="get",
                                                ctx=ast.Load(),
                                            ),
                                            args=[
                                                ast.Constant(value=state_name),
                                                ast.Constant(value=False),
                                            ],
                                            keywords=[],
                                        ),
                                    ],
                                ),
                                body=[ast.Continue()],
                                orelse=[],
                            ),
                            ast.Assign(
                                targets=[
                                    ast.Name(id=label_local, ctx=ast.Store())
                                ],
                                value=ast.BoolOp(
                                    op=ast.Or(),
                                    values=[
                                        ast.Call(
                                            func=ast.Attribute(
                                                value=ast.Name(
                                                    id=record_local,
                                                    ctx=ast.Load(),
                                                ),
                                                attr="get",
                                                ctx=ast.Load(),
                                            ),
                                            args=[ast.Constant(value="path")],
                                            keywords=[],
                                        ),
                                        ast.Call(
                                            func=ast.Attribute(
                                                value=ast.Name(
                                                    id=record_local,
                                                    ctx=ast.Load(),
                                                ),
                                                attr="get",
                                                ctx=ast.Load(),
                                            ),
                                            args=[ast.Constant(value="node")],
                                            keywords=[],
                                        ),
                                        ast.Call(
                                            func=ast.Name(
                                                id="str",
                                                ctx=ast.Load(),
                                            ),
                                            args=[
                                                ast.Name(
                                                    id=record_local,
                                                    ctx=ast.Load(),
                                                )
                                            ],
                                            keywords=[],
                                        ),
                                    ],
                                ),
                            ),
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Attribute(
                                            value=ast.Name(
                                                id="self",
                                                ctx=ast.Load(),
                                            ),
                                            attr=list_widgets[0],
                                            ctx=ast.Load(),
                                        ),
                                        attr="addItem",
                                        ctx=ast.Load(),
                                    ),
                                    args=[
                                        ast.Call(
                                            func=ast.Name(
                                                id="str",
                                                ctx=ast.Load(),
                                            ),
                                            args=[
                                                ast.Name(
                                                    id=label_local,
                                                    ctx=ast.Load(),
                                                )
                                            ],
                                            keywords=[],
                                        )
                                    ],
                                    keywords=[],
                                )
                            ),
                        ],
                        orelse=[],
                    ),
                    ast.If(
                        test=ast.Compare(
                            left=ast.Call(
                                func=ast.Name(id="getattr", ctx=ast.Load()),
                                args=[
                                    ast.Name(id="self", ctx=ast.Load()),
                                    ast.Constant(value="worker"),
                                    ast.Constant(value=None),
                                ],
                                keywords=[],
                            ),
                            ops=[ast.IsNot()],
                            comparators=[ast.Constant(value=None)],
                        ),
                        body=[
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Attribute(
                                            value=ast.Name(
                                                id="self",
                                                ctx=ast.Load(),
                                            ),
                                            attr="worker",
                                            ctx=ast.Load(),
                                        ),
                                        attr="deleteLater",
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                )
                            ),
                            ast.Assign(
                                targets=[
                                    ast.Attribute(
                                        value=ast.Name(
                                            id="self",
                                            ctx=ast.Load(),
                                        ),
                                        attr="worker",
                                        ctx=ast.Store(),
                                    )
                                ],
                                value=ast.Constant(value=None),
                            ),
                        ],
                        orelse=[],
                    ),
                ]
                if len(status_widgets) == 1:
                    statements.append(
                        ast.Expr(
                            value=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Attribute(
                                        value=ast.Name(
                                            id="self",
                                            ctx=ast.Load(),
                                        ),
                                        attr=status_widgets[0],
                                        ctx=ast.Load(),
                                    ),
                                    attr="setText",
                                    ctx=ast.Load(),
                                ),
                                args=[ast.Constant(value="Audit complete")],
                                keywords=[],
                            )
                        )
                    )
                method.body = statements
                changed = True
                notes.append(
                    f"{Path(path).name}:{class_node.name}.{method.name}: "
                    f"applied `{checkbox_name}` while presenting real records "
                    f"in `{list_widgets[0]}`."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_mapping_record_attribute_access(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace invented record attributes with validator-proven mapping keys."""

    targets: dict[tuple[str, str, str], set[tuple[str, str]]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\."
        r"(?P<method>[A-Za-z_][A-Za-z0-9_]*): internal dependency returns "
        r"mapping records; replace invented item attributes with proven keys: "
        r"(?P<attributes>.+?)\. Proven keys: (?P<keys>.+?)\.$"
    )
    for error in errors:
        match = pattern.match(str(error))
        if not match:
            continue
        proven_keys = {
            value.strip()
            for value in match.group("keys").split(",")
            if value.strip()
        }
        replacements = {
            (item_name, key)
            for value in match.group("attributes").split(",")
            for item_name, separator, key in [value.strip().partition(".")]
            if separator and item_name and key in proven_keys
        }
        if replacements:
            targets[(
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
                match.group("method"),
            )] = replacements
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        matching = {
            (owner, method): replacements
            for (target_path, owner, method), replacements in targets.items()
            if target_path == resolved_path
        }
        if not matching:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for class_node in (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        ):
            for method in (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (class_node.name, node.name) in matching
            ):
                replacements = matching[(class_node.name, method.name)]
                for attribute in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Load)
                    and isinstance(node.value, ast.Name)
                    and (node.value.id, node.attr) in replacements
                ):
                    replacement = ast.Subscript(
                        value=ast.Name(
                            id=attribute.value.id,
                            ctx=ast.Load(),
                        ),
                        slice=ast.Constant(value=attribute.attr),
                        ctx=ast.Load(),
                    )
                    for parent in ast.walk(method):
                        for field, value in ast.iter_fields(parent):
                            if value is attribute:
                                setattr(parent, field, replacement)
                            elif isinstance(value, list):
                                for index, item in enumerate(value):
                                    if item is attribute:
                                        value[index] = replacement
                    changed = True
                if changed:
                    notes.append(
                        f"{Path(path).name}:{class_node.name}.{method.name}: "
                        "replaced invented record attributes with proven mapping "
                        "key access."
                    )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_omitted_selective_states(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Extend an existing record-selection guard with omitted requested states."""

    targets: dict[tuple[str, str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<class>[A-Za-z_][A-Za-z0-9_]*)\."
        r"(?P<method>[A-Za-z_][A-Za-z0-9_]*): selective return predicate "
        r"omits requested state\(s\): (?P<states>.+?)\.?$"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.setdefault(
                (
                    str(Path(match.group("path")).resolve()),
                    match.group("class"),
                    match.group("method"),
                ),
                set(),
            ).update(
                state.strip().rstrip(".")
                for state in match.group("states").split(",")
                if state.strip()
            )
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        matching = {
            (class_name, method_name): states
            for (target_path, class_name, method_name), states in targets.items()
            if target_path == str(Path(path).resolve())
        }
        if not matching:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            for method in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                states = matching.get((class_node.name, method.name))
                if not states:
                    continue
                for guard in [
                    node for node in ast.walk(method) if isinstance(node, ast.If)
                ]:
                    if not any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "append"
                        for node in ast.walk(ast.Module(body=guard.body, type_ignores=[]))
                    ):
                        continue
                    existing_names = {
                        node.id
                        for node in ast.walk(guard.test)
                        if isinstance(node, ast.Name)
                    }
                    omitted = sorted(states - existing_names)
                    if not omitted:
                        continue
                    guard.test = ast.BoolOp(
                        op=ast.Or(),
                        values=[
                            guard.test,
                            *[
                                ast.Name(id=state, ctx=ast.Load())
                                for state in omitted
                            ],
                        ],
                    )
                    changed = True
                    notes.append(
                        f"{Path(path).name}:{class_node.name}.{method.name}: "
                        "extended record-selection guard with "
                        + ", ".join(omitted)
                        + "."
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


def _repair_selective_record_append(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Guard an unconditional record append with its proven state predicates."""

    targets: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): selective return "
        r"(?:requirement appends|predicate omits) "
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.add((
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
            ))
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        owners = {
            owner
            for target_path, owner in targets
            if target_path == str(Path(path).resolve())
        }
        if not owners:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner in owners:
            class_name, _, method_name = owner.partition(".")
            class_node = next(
                (
                    node for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            method_node = next(
                (
                    node for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == method_name
                ),
                None,
            ) if class_node is not None else None
            if method_node is None:
                continue
            for loop in [
                node for node in ast.walk(method_node)
                if isinstance(node, (ast.For, ast.AsyncFor))
            ]:
                predicate_names = [
                    target.id
                    for assignment in loop.body
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Name)
                    and isinstance(
                        assignment.value,
                        (ast.BoolOp, ast.Compare, ast.UnaryOp),
                    )
                ]
                if not predicate_names:
                    continue
                def state_test() -> ast.expr:
                    return (
                        ast.Name(
                            id=predicate_names[0],
                            ctx=ast.Load(),
                        )
                        if len(predicate_names) == 1
                        else ast.BoolOp(
                            op=ast.Or(),
                            values=[
                                ast.Name(id=name, ctx=ast.Load())
                                for name in predicate_names
                            ],
                        )
                    )
                for index, statement in enumerate(list(loop.body)):
                    if (
                        isinstance(statement, ast.If)
                        and len(statement.body) == 1
                        and isinstance(statement.body[0], ast.Continue)
                    ):
                        statement.test = ast.UnaryOp(
                            op=ast.Not(),
                            operand=state_test(),
                        )
                        changed = True
                        continue
                    append_call = next(
                        (
                            call for call in ast.walk(statement)
                            if isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "append"
                        ),
                        None,
                    )
                    if append_call is None:
                        continue
                    if isinstance(statement, ast.If):
                        statement.test = state_test()
                    else:
                        loop.body[index] = ast.If(
                            test=state_test(),
                            body=[statement],
                            orelse=[],
                        )
                    changed = True
                    break
            if changed:
                notes.append(
                    f"{Path(path).name}:{owner}: guarded record append with "
                    "the existing derived state predicates."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_initial_progress_boundary(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Repair deterministic integer progress lifecycle boundaries."""

    targets: dict[tuple[str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): "
        r"(?P<reason>all progress updates occur after |requested progress "
        r"updates require at least two observable callback invocations)"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.setdefault((
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
            ), set()).add(match.group("reason").strip())
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        owners = {
            owner: reasons
            for (target_path, owner), reasons in targets.items()
            if target_path == str(Path(path).resolve())
        }
        if not owners:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner, reasons in owners.items():
            class_name, _, method_name = owner.partition(".")
            class_node = next(
                (
                    node for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            method_node = next(
                (
                    node for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == method_name
                ),
                None,
            ) if class_node is not None else None
            if method_node is None:
                continue
            callback_name = next(
                (
                    argument.arg
                    for argument in [
                        *method_node.args.posonlyargs,
                        *method_node.args.args,
                        *method_node.args.kwonlyargs,
                    ]
                    if argument.arg.endswith("progress_callback")
                ),
                "",
            )
            if not callback_name:
                continue
            insertion_index = 1 if (
                method_node.body
                and isinstance(method_node.body[0], ast.Expr)
                and isinstance(method_node.body[0].value, ast.Constant)
                and isinstance(method_node.body[0].value.value, str)
            ) else 0
            total_assignment_index = next(
                (
                    index
                    for index, statement in enumerate(method_node.body)
                    if isinstance(statement, (ast.Assign, ast.AnnAssign))
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Name)
                    and statement.value.func.id == "len"
                    and any(
                        isinstance(target, ast.Name)
                        and target.id.casefold()
                        in {
                            "count",
                            "item_count",
                            "total",
                            "total_count",
                            "total_items",
                            "total_steps",
                        }
                        for target in (
                            statement.targets
                            if isinstance(statement, ast.Assign)
                            else [statement.target]
                        )
                    )
                ),
                None,
            )
            if total_assignment_index is None:
                continue
            total_statement = method_node.body[total_assignment_index]
            total_name = next(
                target.id
                for target in (
                    total_statement.targets
                    if isinstance(total_statement, ast.Assign)
                    else [total_statement.target]
                )
                if isinstance(target, ast.Name)
            )
            initial_progress = ast.parse(
                f"if {callback_name}:\n"
                f"    {callback_name}(0, 0, 'Starting operation')"
            ).body[0]
            method_node.body.insert(insertion_index, initial_progress)
            needs_full_lifecycle = any(
                reason.startswith("requested progress updates require")
                for reason in reasons
            )
            if needs_full_lifecycle:
                completion_progress = ast.parse(
                    f"if {callback_name}:\n"
                    f"    {callback_name}({total_name}, {total_name}, "
                    "'Operation complete')"
                ).body[0]
                return_indexes = [
                    statement_index
                    for statement_index, statement in enumerate(method_node.body)
                    if isinstance(statement, ast.Return)
                ]
                if return_indexes:
                    for return_index in reversed(return_indexes):
                        method_node.body.insert(
                            return_index,
                            copy.deepcopy(completion_progress),
                        )
                else:
                    method_node.body.append(completion_progress)
            changed = True
            notes.append(
                f"{Path(path).name}:{owner}: added an integer progress event "
                + (
                    "at the normal start and completion boundaries."
                    if needs_full_lifecycle
                    else "before the approved blocking operation."
                )
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_missing_path_state(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Make a validator-proven blank resource path count as missing."""

    targets: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): path-backed `missing` state must "
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.add((
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
            ))
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        owners = {
            owner
            for target_path, owner in targets
            if target_path == str(Path(path).resolve())
        }
        if not owners:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner in owners:
            class_name, _, method_name = owner.partition(".")
            class_node = next(
                (
                    node for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            method_node = next(
                (
                    node for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == method_name
                ),
                None,
            ) if class_node is not None else None
            if method_node is None:
                continue
            for assignment in ast.walk(method_node):
                if not isinstance(
                    assignment,
                    (ast.Assign, ast.AnnAssign),
                ):
                    continue
                targets_for_assignment = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                if not any(
                    isinstance(target, ast.Name)
                    and target.id == "missing"
                    for target in targets_for_assignment
                ):
                    continue
                if (
                    isinstance(assignment.value, ast.IfExp)
                    and isinstance(
                        assignment.value.orelse,
                        ast.Constant,
                    )
                    and assignment.value.orelse.value is False
                ):
                    assignment.value.orelse = ast.Constant(value=True)
                    changed = True
            if changed:
                notes.append(
                    f"{Path(path).name}:{owner}: normalized blank path "
                    "handling for the approved missing-state predicate."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_worker_terminal_release(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Release an owner-retained worker in an exact terminal handler."""

    targets: dict[tuple[str, str], str] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): terminal handler must release "
        r"retained worker `self\.(?P<worker>[A-Za-z_][A-Za-z0-9_]*)`"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets[(
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
            )] = match.group("worker")
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        matching = {
            owner: worker
            for (target_path, owner), worker in targets.items()
            if target_path == str(Path(path).resolve())
        }
        if not matching:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner, worker_name in matching.items():
            class_name, _, method_name = owner.partition(".")
            class_node = next(
                (
                    node for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            method_node = next(
                (
                    node for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == method_name
                ),
                None,
            ) if class_node is not None else None
            if method_node is None:
                continue
            retained_body = [
                statement
                for statement in method_node.body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and isinstance(statement.value.func.value, ast.Name)
                    and statement.value.func.value.id == "self"
                    and any(
                        token in statement.value.func.attr.casefold()
                        for token in ("cleanup", "clean_up", "release", "dispose")
                    )
                )
                and not any(
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr == worker_name
                    for node in ast.walk(statement)
                )
            ]
            method_node.body = [
                *retained_body,
                *ast.parse(
                    f"worker_to_release = self.{worker_name}\n"
                    f"self.{worker_name} = None\n"
                    "if worker_to_release is not None:\n"
                    "    worker_to_release.deleteLater()"
                ).body,
            ]
            changed = True
            notes.append(
                f"{Path(path).name}:{owner}: released retained worker "
                f"`self.{worker_name}` through one capture-clear-dispose sequence."
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_unreachable_qt_handler_routing(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Connect an exact approved UI handler to its owned worker signal."""

    targets: dict[tuple[str, str], str] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<class>[A-Za-z_][A-Za-z0-9_]*)\."
        r"(?P<method>_[A-Za-z_][A-Za-z0-9_]*): "
        r"requirement-owning UI handler is unreachable"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets[(
                str(Path(match.group("path")).resolve()),
                match.group("class"),
            )] = match.group("method")
            continue
        dead_helpers = re.match(
            r"^(?P<path>.+?\.py):"
            r"(?P<class>[A-Za-z_][A-Za-z0-9_]*): "
            r"private helper callable\(s\) are never referenced by production "
            r"behavior and introduce dead code: "
            r"(?P<methods>_[A-Za-z_][A-Za-z0-9_]*"
            r"(?:,\s*_[A-Za-z_][A-Za-z0-9_]*)*)\.",
            str(error),
        )
        if dead_helpers:
            method_names = [
                value.strip()
                for value in dead_helpers.group("methods").split(",")
                if value.strip()
            ]
            signal_handlers = [
                method_name
                for method_name in method_names
                if any(
                    role in method_name.casefold()
                    for role in ("progress", "error", "result", "complete")
                )
            ]
            if signal_handlers:
                targets[(
                    str(Path(dead_helpers.group("path")).resolve()),
                    dead_helpers.group("class"),
                )] = signal_handlers[0]
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        class_targets = {
            class_name: method_name
            for (target_path, class_name), method_name in targets.items()
            if target_path == resolved_path
        }
        if not class_targets:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        file_changed = False
        for class_node in [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name in class_targets
        ]:
            handler_name = class_targets[class_node.name]
            signal_name = (
                "progress"
                if "progress" in handler_name
                else "error"
                if "error" in handler_name
                else "result"
                if any(
                    token in handler_name
                    for token in ("result", "complete", "update")
                )
                else ""
            )
            if not signal_name:
                continue
            methods = [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if not any(method.name == handler_name for method in methods):
                continue
            repaired = False
            for method in methods:
                for call in [
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and node.args
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == signal_name
                    and isinstance(node.func.value.value, ast.Attribute)
                    and isinstance(node.func.value.value.value, ast.Name)
                    and node.func.value.value.value.id == "self"
                ]:
                    desired_handler = ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=handler_name,
                        ctx=ast.Load(),
                    )
                    if ast.dump(
                        call.args[0],
                        include_attributes=False,
                    ) != ast.dump(
                        desired_handler,
                        include_attributes=False,
                    ):
                        call.args[0] = desired_handler
                        repaired = True
                    break
                if repaired:
                    break
            if repaired:
                file_changed = True
                notes.append(
                    f"{Path(path).name}:{class_node.name}.{handler_name}: "
                    f"connected exact approved handler to retained worker "
                    f"`{signal_name}` signal."
                )
        if file_changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_inferred_collection_type_hints(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace generic annotations when executable collection shape is proven."""

    updated = list(generated_files)
    notes: list[str] = []

    def generic(annotation: ast.AST | None) -> bool:
        return annotation is None or (
            isinstance(annotation, ast.Name)
            and annotation.id in {"Any", "object"}
        )

    mapping_list_annotation = ast.parse(
        "value: list[dict[str, str]]"
    ).body[0].annotation
    callable_annotation = ast.parse(
        "value: Callable[..., object]"
    ).body[0].annotation

    def returns_mapping_list(
        function: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        mapping_record_names = {
            target.id
            for assignment in ast.walk(function)
            if isinstance(assignment, (ast.Assign, ast.AnnAssign))
            and isinstance(assignment.value, ast.Dict)
            and bool(assignment.value.keys)
            and all(
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                for key in assignment.value.keys
            )
            for target in (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            if isinstance(target, ast.Name)
        }
        mapping_list_names = {
            call.func.value.id
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "append"
            and isinstance(call.func.value, ast.Name)
            and call.args
            and (
                (
                    isinstance(call.args[0], ast.Dict)
                    and bool(call.args[0].keys)
                    and all(
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        for key in call.args[0].keys
                    )
                )
                or (
                    isinstance(call.args[0], ast.Name)
                    and call.args[0].id in mapping_record_names
                )
            )
        }
        return any(
            isinstance(return_node, ast.Return)
            and return_node.value is not None
            and any(
                isinstance(name, ast.Name)
                and name.id in mapping_list_names
                for name in ast.walk(return_node.value)
            )
            for return_node in ast.walk(function)
        )

    mapping_list_producers: set[tuple[str, str]] = set()
    for path, _original, source in generated_files:
        try:
            producer_tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for class_node in (
            node for node in producer_tree.body if isinstance(node, ast.ClassDef)
        ):
            for method in (
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                if returns_mapping_list(method):
                    mapping_list_producers.add(
                        (class_node.name, method.name)
                    )

    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        needs_callable_import = False

        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            if returns_mapping_list(function) and generic(function.returns):
                function.returns = copy.deepcopy(mapping_list_annotation)
                changed = True

            positional = [
                *function.args.posonlyargs,
                *function.args.args,
            ]
            parameter_by_name = {
                argument.arg: argument
                for argument in (
                    *positional,
                    *function.args.kwonlyargs,
                )
                if argument.arg not in {"self", "cls"}
            }
            for loop in (
                node
                for node in ast.walk(function)
                if isinstance(node, (ast.For, ast.AsyncFor))
                and isinstance(node.iter, ast.Name)
                and node.iter.id in parameter_by_name
                and isinstance(node.target, ast.Name)
            ):
                item_name = loop.target.id
                uses_mapping_keys = any(
                    isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == item_name
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)
                    for node in ast.walk(loop)
                )
                argument = parameter_by_name[loop.iter.id]
                if uses_mapping_keys and generic(argument.annotation):
                    argument.annotation = copy.deepcopy(
                        mapping_list_annotation
                    )
                    changed = True

        for class_node in (
            node
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
        ):
            constructor = next(
                (
                    method
                    for method in class_node.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and method.name == "__init__"
                ),
                None,
            )
            if constructor is None:
                continue
            operation_argument = next(
                (
                    argument
                    for argument in (
                        *constructor.args.posonlyargs,
                        *constructor.args.args,
                        *constructor.args.kwonlyargs,
                    )
                    if argument.arg == "operation"
                ),
                None,
            )
            if (
                operation_argument is not None
                and generic(operation_argument.annotation)
            ):
                operation_argument.annotation = copy.deepcopy(
                    callable_annotation
                )
                needs_callable_import = True
                changed = True

        worker_class_names = {
            class_node.name
            for class_node in tree.body
            if isinstance(class_node, ast.ClassDef)
            and any(
                (
                    isinstance(base, ast.Name)
                    and base.id in {"QThread", "QRunnable"}
                )
                or (
                    isinstance(base, ast.Attribute)
                    and base.attr in {"QThread", "QRunnable"}
                )
                for base in class_node.bases
            )
        }
        producer_method_counts: dict[str, int] = {}
        for _producer_owner, producer_method in mapping_list_producers:
            producer_method_counts[producer_method] = (
                producer_method_counts.get(producer_method, 0) + 1
            )

        for class_node in (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name not in worker_class_names
        ):
            methods_by_name = {
                method.name: method
                for method in class_node.body
                if isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            mapping_worker_names: set[str] = set()
            for assignment in (
                node
                for method in methods_by_name.values()
                for node in ast.walk(method)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in worker_class_names
            ):
                operation_values = [
                    keyword.value
                    for keyword in assignment.value.keywords
                    if keyword.arg == "operation"
                ]
                if not operation_values and assignment.value.args:
                    operation_values = [assignment.value.args[0]]
                if not operation_values:
                    continue
                operation = operation_values[0]
                if not isinstance(operation, ast.Attribute):
                    continue
                producer_method = operation.attr
                producer_owner = ""
                if (
                    isinstance(operation.value, ast.Call)
                    and isinstance(operation.value.func, ast.Name)
                ):
                    producer_owner = operation.value.func.id
                elif isinstance(operation.value, ast.Name):
                    producer_owner = operation.value.id
                producer_is_proven = (
                    (producer_owner, producer_method)
                    in mapping_list_producers
                    or (
                        not producer_owner
                        and producer_method_counts.get(producer_method) == 1
                    )
                )
                if not producer_is_proven:
                    continue
                targets = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                mapping_worker_names.update(
                    target.attr
                    for target in targets
                    if isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                )

            for connection in (
                node
                for method in methods_by_name.values()
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and len(node.args) == 1
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr
                in {"complete", "completed", "result", "succeeded"}
                and isinstance(node.func.value.value, ast.Attribute)
                and isinstance(node.func.value.value.value, ast.Name)
                and node.func.value.value.value.id == "self"
                and node.func.value.value.attr in mapping_worker_names
                and isinstance(node.args[0], ast.Attribute)
                and isinstance(node.args[0].value, ast.Name)
                and node.args[0].value.id == "self"
            ):
                handler = methods_by_name.get(connection.args[0].attr)
                if handler is None:
                    continue
                handler_parameters = [
                    *handler.args.posonlyargs,
                    *handler.args.args,
                ]
                if (
                    handler_parameters
                    and handler_parameters[0].arg in {"self", "cls"}
                ):
                    handler_parameters = handler_parameters[1:]
                if not handler_parameters:
                    continue
                result_parameter = handler_parameters[0]
                if (
                    result_parameter.annotation is None
                    or ast.dump(
                        result_parameter.annotation,
                        include_attributes=False,
                    )
                    != ast.dump(
                        mapping_list_annotation,
                        include_attributes=False,
                    )
                ):
                    result_parameter.annotation = copy.deepcopy(
                        mapping_list_annotation
                    )
                    changed = True
                for delegated_call in (
                    node
                    for node in ast.walk(handler)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr in methods_by_name
                    and node.args
                ):
                    delegated_method = methods_by_name[node.func.attr]
                    delegated_parameters = [
                        *delegated_method.args.posonlyargs,
                        *delegated_method.args.args,
                    ]
                    if (
                        delegated_parameters
                        and delegated_parameters[0].arg in {"self", "cls"}
                    ):
                        delegated_parameters = delegated_parameters[1:]
                    if not delegated_parameters:
                        continue
                    delegated_parameter = delegated_parameters[0]
                    consumes_collection = any(
                        isinstance(loop, (ast.For, ast.AsyncFor))
                        and isinstance(loop.iter, ast.Name)
                        and loop.iter.id == delegated_parameter.arg
                        for loop in ast.walk(delegated_method)
                    )
                    if not consumes_collection:
                        continue
                    argument = delegated_call.args[0]
                    if (
                        isinstance(argument, ast.List)
                        and len(argument.elts) == 1
                        and isinstance(argument.elts[0], ast.Name)
                        and argument.elts[0].id == result_parameter.arg
                    ):
                        delegated_call.args[0] = ast.copy_location(
                            ast.Name(
                                id=result_parameter.arg,
                                ctx=ast.Load(),
                            ),
                            argument,
                        )
                        changed = True
                    if (
                        delegated_parameter.annotation is None
                        or ast.dump(
                            delegated_parameter.annotation,
                            include_attributes=False,
                        )
                        != ast.dump(
                            mapping_list_annotation,
                            include_attributes=False,
                        )
                    ):
                        delegated_parameter.annotation = copy.deepcopy(
                            mapping_list_annotation
                        )
                        changed = True

        if needs_callable_import:
            typing_import = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.module == "typing"
                ),
                None,
            )
            if typing_import is None:
                tree.body.insert(
                    0,
                    ast.ImportFrom(
                        module="typing",
                        names=[ast.alias(name="Callable")],
                        level=0,
                    ),
                )
            elif "Callable" not in {
                alias.asname or alias.name
                for alias in typing_import.names
            }:
                typing_import.names.append(ast.alias(name="Callable"))

        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            notes.append(
                f"{Path(path).name}: replaced generic callable and mapping "
                "collection annotations with executable-shape types."
            )
    return updated, notes


def _repair_qt_worker_lifecycle_ownership(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Centralize button-triggered worker lifecycle wiring in one start method."""

    updated = list(generated_files)
    notes: list[str] = []

    def worker_assignment(
        statement: ast.stmt,
        worker_classes: set[str],
    ) -> tuple[str, ast.Call] | None:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Attribute)
            and isinstance(statement.targets[0].value, ast.Name)
            and statement.targets[0].value.id == "self"
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id in worker_classes
        ):
            return None
        return statement.targets[0].attr, statement.value

    def signal_connection(
        statement: ast.stmt,
        worker_name: str,
    ) -> tuple[str, ast.AST] | None:
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and statement.value.func.attr == "connect"
            and statement.value.args
            and isinstance(statement.value.func.value, ast.Attribute)
            and isinstance(statement.value.func.value.value, ast.Attribute)
            and isinstance(
                statement.value.func.value.value.value,
                ast.Name,
            )
            and statement.value.func.value.value.value.id == "self"
            and statement.value.func.value.value.attr == worker_name
        ):
            return None
        return (
            statement.value.func.value.attr,
            statement.value.args[0],
        )

    def direct_self_call(statement: ast.stmt) -> str:
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and isinstance(statement.value.func.value, ast.Name)
            and statement.value.func.value.id == "self"
        ):
            return ""
        return statement.value.func.attr

    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        worker_signals: dict[str, list[str]] = {}
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            if not any(
                isinstance(base, ast.Name)
                and base.id in {"QThread", "QRunnable"}
                for base in class_node.bases
            ):
                continue
            worker_signals[class_node.name] = [
                target.id
                for statement in class_node.body
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                for target in statement.targets
                if isinstance(statement.value, ast.Call)
                and (
                    (
                        isinstance(statement.value.func, ast.Name)
                        and statement.value.func.id == "Signal"
                    )
                    or (
                        isinstance(statement.value.func, ast.Attribute)
                        and statement.value.func.attr == "Signal"
                    )
                )
            ]
        if not worker_signals:
            continue
        worker_classes = set(worker_signals)
        file_changed = False
        for class_node in [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name not in worker_classes
        ]:
            class_before = ast.dump(
                class_node,
                include_attributes=False,
            )
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            constructor = methods.get("__init__")
            if constructor is None:
                continue
            assignments: list[
                tuple[ast.FunctionDef | ast.AsyncFunctionDef, str, ast.Call]
            ] = []
            for method in methods.values():
                for statement in method.body:
                    assignment = worker_assignment(statement, worker_classes)
                    if assignment:
                        assignments.append((
                            method,
                            assignment[0],
                            assignment[1],
                        ))
            if not assignments:
                continue
            start_candidates = [
                item
                for item in assignments
                if item[0].name != "__init__"
                and (
                    "start" in item[0].name
                    or "run" in item[0].name
                    or "worker" in item[0].name
                    or "background" in item[0].name
                )
            ]
            if not start_candidates:
                start_candidates = [
                    item for item in assignments if item[0].name != "__init__"
                ]
            if not start_candidates:
                continue
            start_method, worker_name, constructor_call = start_candidates[0]
            worker_aliases = {
                assigned_worker
                for _method, assigned_worker, _constructor in assignments
                if assigned_worker.lstrip("_") == worker_name.lstrip("_")
            }
            worker_aliases.add(worker_name)
            for reference in ast.walk(class_node):
                if (
                    isinstance(reference, ast.Attribute)
                    and isinstance(reference.value, ast.Name)
                    and reference.value.id == "self"
                    and reference.attr in worker_aliases
                ):
                    reference.attr = worker_name
            signal_handlers: dict[str, ast.AST] = {}
            for method in methods.values():
                for statement in method.body:
                    connection = signal_connection(statement, worker_name)
                    if connection:
                        signal_handlers.setdefault(
                            connection[0],
                            connection[1],
                        )
            signal_handlers = {
                signal_name: handler
                for signal_name, handler in signal_handlers.items()
                if not (
                    isinstance(handler, ast.Attribute)
                    and isinstance(handler.value, ast.Name)
                    and handler.value.id == "self"
                    and handler.attr not in methods
                )
            }
            if (
                "progress" not in signal_handlers
                and "progress" in worker_signals.get(
                    constructor_call.func.id
                    if isinstance(constructor_call.func, ast.Name)
                    else "",
                    [],
                )
            ):
                progress_handler = next(
                    (
                        method
                        for method in methods.values()
                        if "progress" in method.name.casefold()
                        and method is not start_method
                        and len(
                            [
                                *method.args.posonlyargs,
                                *method.args.args,
                                *method.args.kwonlyargs,
                            ]
                        )
                        >= 4
                        and any(
                            isinstance(reference, ast.Attribute)
                            and isinstance(reference.value, ast.Name)
                            and reference.value.id == "self"
                            and (
                                "progress" in reference.attr.casefold()
                                or "status" in reference.attr.casefold()
                            )
                            for reference in ast.walk(method)
                        )
                    ),
                    None,
                )
                if progress_handler is not None:
                    signal_handlers["progress"] = ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=progress_handler.name,
                        ctx=ast.Load(),
                    )
            signal_names = worker_signals.get(
                constructor_call.func.id
                if isinstance(constructor_call.func, ast.Name)
                else "",
                [],
            )
            constructor_call = copy.deepcopy(constructor_call)
            constructor_call.keywords = [
                keyword
                for keyword in constructor_call.keywords
                if keyword.arg != "progress_callback"
            ]
            retained_start_body: list[ast.stmt] = []
            if (
                start_method.body
                and isinstance(start_method.body[0], ast.Expr)
                and isinstance(start_method.body[0].value, ast.Constant)
                and isinstance(start_method.body[0].value.value, str)
            ):
                retained_start_body.append(start_method.body[0])
            original_assignment_index = next(
                (
                    index
                    for index, statement in enumerate(start_method.body)
                    if (
                        (assignment := worker_assignment(
                            statement,
                            worker_classes,
                        ))
                        and assignment[0] == worker_name
                    )
                ),
                len(start_method.body),
            )
            constructor_dependency_names = {
                node.id
                for node in ast.walk(constructor_call)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id not in worker_classes
            }
            for statement in start_method.body[:original_assignment_index]:
                if statement in retained_start_body:
                    continue
                bound_names = {
                    target.id
                    for node in ast.walk(statement)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    for target in (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                    )
                    if isinstance(target, ast.Name)
                }
                if bound_names & constructor_dependency_names:
                    retained_start_body.append(copy.deepcopy(statement))
                    continue
                if not isinstance(statement, ast.If):
                    continue
                references_retained_worker = any(
                    isinstance(reference, ast.Attribute)
                    and isinstance(reference.value, ast.Name)
                    and reference.value.id == "self"
                    and reference.attr == worker_name
                    for reference in ast.walk(statement.test)
                )
                exits_before_replacement = any(
                    isinstance(child, (ast.Return, ast.Raise))
                    for child in ast.walk(statement)
                )
                if references_retained_worker and exits_before_replacement:
                    retained_start_body.append(copy.deepcopy(statement))
            def is_retained_worker_guard(statement: ast.stmt) -> bool:
                return (
                    isinstance(statement, ast.If)
                    and any(
                        isinstance(reference, ast.Attribute)
                        and isinstance(reference.value, ast.Name)
                        and reference.value.id == "self"
                        and reference.attr == worker_name
                        for reference in ast.walk(statement.test)
                    )
                    and any(
                        isinstance(child, (ast.Return, ast.Raise))
                        for child in ast.walk(statement)
                    )
                )

            has_retained_worker_guard = any(
                is_retained_worker_guard(statement)
                for statement in retained_start_body
            )
            if has_retained_worker_guard:
                retained_start_body = [
                    statement
                    for statement in retained_start_body
                    if not is_retained_worker_guard(statement)
                ]
            retained_start_body.append(
                ast.If(
                    test=ast.Compare(
                        left=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=worker_name,
                            ctx=ast.Load(),
                        ),
                        ops=[ast.IsNot()],
                        comparators=[ast.Constant(value=None)],
                    ),
                    body=[ast.Return(value=None)],
                    orelse=[],
                )
            )
            retained_start_body.append(
                ast.Assign(
                    targets=[
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=worker_name,
                            ctx=ast.Store(),
                        )
                    ],
                    value=constructor_call,
                )
            )
            routed_signal_names = list(dict.fromkeys([
                *signal_names,
                *signal_handlers,
            ]))
            for signal_name in routed_signal_names:
                handler = signal_handlers.get(signal_name)
                if handler is None:
                    continue
                retained_start_body.append(
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Attribute(
                                    value=ast.Attribute(
                                        value=ast.Name(
                                            id="self",
                                            ctx=ast.Load(),
                                        ),
                                        attr=worker_name,
                                        ctx=ast.Load(),
                                    ),
                                    attr=signal_name,
                                    ctx=ast.Load(),
                                ),
                                attr="connect",
                                ctx=ast.Load(),
                            ),
                            args=[copy.deepcopy(handler)],
                            keywords=[],
                        )
                    )
                )
            finished_handler = signal_handlers.get("finished")
            if (
                isinstance(finished_handler, ast.Attribute)
                and isinstance(finished_handler.value, ast.Name)
                and finished_handler.value.id == "self"
                and finished_handler.attr in methods
            ):
                cleanup_method = methods[finished_handler.attr]
                cleanup_docstring = (
                    [cleanup_method.body[0]]
                    if (
                        cleanup_method.body
                        and isinstance(cleanup_method.body[0], ast.Expr)
                        and isinstance(
                            cleanup_method.body[0].value,
                            ast.Constant,
                        )
                        and isinstance(
                            cleanup_method.body[0].value.value,
                            str,
                        )
                    )
                    else []
                )
                self_argument = (
                    cleanup_method.args.args[0]
                    if cleanup_method.args.args
                    else ast.arg(arg="self")
                )
                cleanup_method.args = ast.arguments(
                    posonlyargs=[],
                    args=[self_argument],
                    vararg=None,
                    kwonlyargs=[],
                    kw_defaults=[],
                    kwarg=None,
                    defaults=[],
                )
                cleanup_method.returns = ast.Constant(value=None)
                cleanup_method.body = [
                    *cleanup_docstring,
                    ast.Assign(
                        targets=[
                            ast.Name(
                                id="worker_to_release",
                                ctx=ast.Store(),
                            )
                        ],
                        value=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=worker_name,
                            ctx=ast.Load(),
                        ),
                    ),
                    ast.Assign(
                        targets=[
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=worker_name,
                                ctx=ast.Store(),
                            )
                        ],
                        value=ast.Constant(value=None),
                    ),
                    ast.If(
                        test=ast.Compare(
                            left=ast.Name(
                                id="worker_to_release",
                                ctx=ast.Load(),
                            ),
                            ops=[ast.IsNot()],
                            comparators=[ast.Constant(value=None)],
                        ),
                        body=[
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(
                                            id="worker_to_release",
                                            ctx=ast.Load(),
                                        ),
                                        attr="deleteLater",
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                )
                            )
                        ],
                        orelse=[],
                    ),
                ]
                for signal_name, handler in signal_handlers.items():
                    if (
                        signal_name == "finished"
                        or not isinstance(handler, ast.Attribute)
                        or not isinstance(handler.value, ast.Name)
                        or handler.value.id != "self"
                    ):
                        continue
                    terminal_method = methods.get(handler.attr)
                    if terminal_method is None:
                        continue
                    terminal_method.body = [
                        statement
                        for statement in terminal_method.body
                        if not (
                            isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Call)
                            and isinstance(statement.value.func, ast.Attribute)
                            and isinstance(
                                statement.value.func.value,
                                ast.Name,
                            )
                            and statement.value.func.value.id == "self"
                            and statement.value.func.attr
                            == finished_handler.attr
                        )
                        and not any(
                            isinstance(node, ast.Attribute)
                            and isinstance(node.value, ast.Name)
                            and node.value.id == "self"
                            and node.attr == worker_name
                            for node in ast.walk(statement)
                        )
                    ]
            retained_start_body.append(
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=worker_name,
                                ctx=ast.Load(),
                            ),
                            attr="start",
                            ctx=ast.Load(),
                        ),
                        args=[],
                        keywords=[],
                    )
                )
            )
            start_method.body = retained_start_body

            connect_helper = methods.get("_connect_ui_handlers")
            control_connection_statements = [
                statement
                for statement in constructor.body
                if (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and statement.value.func.attr == "connect"
                    and signal_connection(statement, worker_name) is None
                )
            ]
            control_connections = [
                copy.deepcopy(statement)
                for statement in control_connection_statements
            ]
            constructor.body = [
                statement
                for statement in constructor.body
                if (
                    worker_assignment(statement, worker_classes) is None
                    and not (
                        isinstance(statement, ast.Assign)
                        and len(statement.targets) == 1
                        and isinstance(
                            statement.targets[0],
                            ast.Attribute,
                        )
                        and isinstance(
                            statement.targets[0].value,
                            ast.Name,
                        )
                        and statement.targets[0].value.id == "self"
                        and statement.targets[0].attr == worker_name
                    )
                    and signal_connection(statement, worker_name) is None
                    and not (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Attribute)
                        and isinstance(
                            statement.value.func.value,
                            ast.Attribute,
                        )
                        and isinstance(
                            statement.value.func.value.value,
                            ast.Name,
                        )
                        and statement.value.func.value.value.id == "self"
                        and statement.value.func.value.attr == worker_name
                        and statement.value.func.attr == "start"
                    )
                    and direct_self_call(statement) != start_method.name
                    and (
                        connect_helper is None
                        or statement not in control_connection_statements
                    )
                )
            ]
            if connect_helper is not None and control_connections:
                helper_body = [
                    connect_helper.body[0]
                ] if (
                    connect_helper.body
                    and isinstance(connect_helper.body[0], ast.Expr)
                    and isinstance(
                        connect_helper.body[0].value,
                        ast.Constant,
                    )
                    and isinstance(
                        connect_helper.body[0].value.value,
                        str,
                    )
                ) else []
                helper_body.extend(control_connections)
                connect_helper.body = helper_body
            constructor.body.append(
                ast.Assign(
                    targets=[
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=worker_name,
                            ctx=ast.Store(),
                        )
                    ],
                    value=ast.Constant(value=None),
                )
            )
            if connect_helper is not None and not any(
                direct_self_call(statement) == connect_helper.name
                for statement in constructor.body
            ):
                constructor.body.append(
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=connect_helper.name,
                                ctx=ast.Load(),
                            ),
                            args=[],
                            keywords=[],
                        )
                    )
                )
            if ast.dump(
                class_node,
                include_attributes=False,
            ) != class_before:
                file_changed = True
                notes.append(
                    f"{Path(path).name}:{class_node.name}: centralized retained "
                    f"worker construction, signal routing, and start ownership in "
                    f"`{start_method.name}`."
                )
        if file_changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _dedupe_constructor_signal_connections(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove repeated signal wiring along each constructor execution path."""

    updated = list(generated_files)
    notes: list[str] = []

    def connection_key(statement: ast.stmt) -> str:
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and statement.value.func.attr == "connect"
            and statement.value.args
        ):
            return ""
        return "|".join((
            ast.dump(statement.value.func.value, include_attributes=False),
            ast.dump(statement.value.args[0], include_attributes=False),
        ))

    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        file_changed = False
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            constructor = methods.get("__init__")
            if constructor is None:
                continue
            seen_connections: set[str] = set()
            visited_methods: set[str] = set()

            def process_method(method_name: str) -> None:
                nonlocal file_changed
                if method_name in visited_methods:
                    return
                visited_methods.add(method_name)
                method = methods.get(method_name)
                if method is None:
                    return
                retained: list[ast.stmt] = []
                for statement in method.body:
                    if (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Attribute)
                        and isinstance(statement.value.func.value, ast.Name)
                        and statement.value.func.value.id == "self"
                        and statement.value.func.attr in methods
                    ):
                        process_method(statement.value.func.attr)
                    key = connection_key(statement)
                    if key and key in seen_connections:
                        file_changed = True
                        notes.append(
                            f"{Path(path).name}:{class_node.name}."
                            f"{method_name}: removed duplicate constructor-path "
                            "signal connection."
                        )
                        continue
                    if key:
                        seen_connections.add(key)
                    retained.append(statement)
                method.body = retained

            process_method("__init__")
        if file_changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_ephemeral_progress_recorders(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace a placeholder nested progress callback with observable proof."""

    diagnostics = "\n".join(str(error) for error in errors)
    if (
        not harness_path
        or "Generated test methods are placeholders:" not in diagnostics
    ):
        return validation_files, []
    failing_tests = set(re.findall(
        r"\b(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
        r"(test_[A-Za-z0-9_]+)\b",
        diagnostics,
    ))
    updated = list(validation_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if path != harness_path:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            for method in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in failing_tests
            ]:
                for statement_index, statement in enumerate(method.body):
                    if not isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    ):
                        continue
                    parameters = [
                        argument.arg
                        for argument in statement.args.args
                        if argument.arg not in {"self", "cls"}
                    ]
                    if (
                        len(parameters) != 3
                        or not all(
                            isinstance(item, ast.Pass)
                            for item in statement.body
                        )
                        or not re.search(
                            r"(?:progress|callback)",
                            statement.name,
                            flags=re.IGNORECASE,
                        )
                    ):
                        continue
                    recorder_name = "_progress_events"
                    method.body.insert(
                        statement_index,
                        ast.Assign(
                            targets=[
                                ast.Name(id=recorder_name, ctx=ast.Store())
                            ],
                            value=ast.List(elts=[], ctx=ast.Load()),
                        ),
                    )
                    statement.body = [
                        ast.Expr(value=ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(
                                    id=recorder_name,
                                    ctx=ast.Load(),
                                ),
                                attr="append",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Tuple(
                                elts=[
                                    ast.Name(id=name, ctx=ast.Load())
                                    for name in parameters
                                ],
                                ctx=ast.Load(),
                            )],
                            keywords=[],
                        ))
                    ]
                    method.body.extend(ast.parse(
                        "self.assertTrue(_progress_events)\n"
                        "self.assertTrue(all(\n"
                        "    isinstance(current, int)\n"
                        "    and isinstance(total, int)\n"
                        "    and isinstance(status, str)\n"
                        "    for current, total, status in _progress_events\n"
                        "))\n"
                    ).body)
                    notes.append(
                        f"{path}:{class_node.name}.{method.name}: replaced "
                        "placeholder progress callback with event assertions."
                    )
                    changed = True
                    break
        if changed:
            ast.fix_missing_locations(tree)
            updated[index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_ephemeral_host_and_status_assertions(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Repair invalid host-mock type checks and unspecified exact UI wording."""

    if not harness_path:
        return validation_files, []
    diagnostics = "\n".join(str(error) for error in errors)
    repair_host_type = (
        "TypeError: isinstance() arg 2 must be a type" in diagnostics
    )
    repair_success_text = bool(re.search(
        r"AssertionError:.*(?:success|created)",
        diagnostics,
        flags=re.IGNORECASE | re.DOTALL,
    ))
    if not repair_host_type and not repair_success_text:
        return validation_files, []

    host_modules = {"unreal", "maya", "cmds", "bpy", "pyfbsdk"}

    def root_name(node: ast.AST) -> str:
        cursor = node
        while isinstance(cursor, ast.Attribute):
            cursor = cursor.value
        return cursor.id if isinstance(cursor, ast.Name) else ""

    class HarnessAssertionRepair(ast.NodeTransformer):
        def __init__(self) -> None:
            self.host_type_repairs = 0
            self.status_repairs = 0
            self.return_value_targets: list[ast.Attribute] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
            previous_targets = self.return_value_targets
            self.return_value_targets = [
                target
                for assignment in ast.walk(node)
                if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                for target in (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                if isinstance(target, ast.Attribute)
                and target.attr == "return_value"
            ]
            node = self.generic_visit(node)
            self.return_value_targets = previous_targets
            return node

        def visit_Expr(self, node: ast.Expr) -> ast.AST | list[ast.stmt]:
            node = self.generic_visit(node)
            if not isinstance(node.value, ast.Call):
                return node
            call = node.value
            if (
                repair_host_type
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "assertIsInstance"
                and len(call.args) == 2
                and root_name(call.args[1]) in host_modules
            ):
                ranked_targets = sorted(
                    self.return_value_targets,
                    key=lambda target: (
                        any(
                            marker in ast.unparse(target).casefold()
                            for marker in (
                                ".create",
                                ".build",
                                ".export",
                                ".import",
                                ".load",
                                ".make",
                            )
                        ),
                        ast.unparse(target).count("."),
                    ),
                    reverse=True,
                )
                if not ranked_targets:
                    return node
                self.host_type_repairs += 1
                expected = copy.deepcopy(ranked_targets[0])
                expected.ctx = ast.Load()
                return ast.copy_location(
                    ast.Expr(value=ast.Call(
                        func=ast.Attribute(
                            value=call.func.value,
                            attr="assertIs",
                            ctx=ast.Load(),
                        ),
                        args=[call.args[0], expected],
                        keywords=[],
                    )),
                    node,
                )
            if (
                repair_success_text
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in {"assertEqual", "assertMultiLineEqual"}
                and len(call.args) >= 2
                and isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, str)
                and re.search(
                    r"(?:success|created)",
                    call.args[1].value,
                    flags=re.IGNORECASE,
                )
            ):
                actual = call.args[0]
                self.status_repairs += 1
                return [
                    ast.copy_location(
                        ast.Expr(value=ast.Call(
                            func=ast.Attribute(
                                value=call.func.value,
                                attr="assertTrue",
                                ctx=ast.Load(),
                            ),
                            args=[copy.deepcopy(actual)],
                            keywords=[],
                        )),
                        node,
                    ),
                    ast.copy_location(
                        ast.Expr(value=ast.Call(
                            func=ast.Attribute(
                                value=call.func.value,
                                attr="assertIn",
                                ctx=ast.Load(),
                            ),
                            args=[
                                ast.Constant(value="success"),
                                ast.Call(
                                    func=ast.Attribute(
                                        value=copy.deepcopy(actual),
                                        attr="casefold",
                                        ctx=ast.Load(),
                                    ),
                                    args=[],
                                    keywords=[],
                                ),
                            ],
                            keywords=[],
                        )),
                        node,
                    ),
                ]
            return node

    updated = list(validation_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if path != harness_path:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        transformer = HarnessAssertionRepair()
        tree = transformer.visit(tree)
        if not transformer.host_type_repairs and not transformer.status_repairs:
            continue
        ast.fix_missing_locations(tree)
        updated[index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
        if transformer.host_type_repairs:
            notes.append(
                f"{path}: replaced invalid host-mock isinstance proof with "
                "configured return-object identity proof."
            )
        if transformer.status_repairs:
            notes.append(
                f"{path}: replaced unspecified exact success wording with "
                "non-empty semantic success proof."
            )
    return updated, notes


def _repair_ephemeral_unused_fixture_assignments(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove disposable fixture assignments proven unused by validation."""

    if not harness_path:
        return validation_files, []
    diagnostics = "\n".join(str(error) for error in errors)
    unused_names = {
        name
        for group in re.findall(
            r"fixture variables never consumed:\s*"
            r"([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)",
            diagnostics,
        )
        for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", group)
    }
    if not unused_names:
        return validation_files, []

    updated = list(validation_files)
    notes: list[str] = []

    class UnusedFixtureBindingRepair(ast.NodeTransformer):
        """Remove named bindings while retaining evaluated call side effects."""

        def __init__(self, removable_names: set[str]) -> None:
            self.removable_names = removable_names
            self.removed: set[str] = set()

        def visit_With(self, node: ast.With) -> ast.stmt:
            node = self.generic_visit(node)
            removable_patch_bindings = {
                item.optional_vars.id
                for item in node.items
                if isinstance(item.optional_vars, ast.Name)
                and item.optional_vars.id in self.removable_names
                and isinstance(item.context_expr, ast.Call)
                and (
                    (
                        isinstance(item.context_expr.func, ast.Name)
                        and item.context_expr.func.id == "patch"
                    )
                    or (
                        isinstance(item.context_expr.func, ast.Attribute)
                        and isinstance(item.context_expr.func.value, ast.Name)
                        and item.context_expr.func.value.id == "patch"
                        and item.context_expr.func.attr == "object"
                    )
                )
            }
            if removable_patch_bindings:
                self.removed.update(removable_patch_bindings)
                return ast.copy_location(
                    ast.If(
                        test=ast.Constant(value=True),
                        body=node.body or [ast.Pass()],
                        orelse=[],
                    ),
                    node,
                )
            return node

        def visit_Assign(self, node: ast.Assign) -> ast.stmt | None:
            node = self.generic_visit(node)
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if (
                assigned_names
                and assigned_names <= self.removable_names
                and len(assigned_names) == len(node.targets)
            ):
                self.removed.update(assigned_names)
                if isinstance(node.value, (ast.Call, ast.Await)):
                    return ast.copy_location(
                        ast.Expr(value=node.value),
                        node,
                    )
                return None
            return node

        def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.stmt | None:
            node = self.generic_visit(node)
            if (
                isinstance(node.target, ast.Name)
                and node.target.id in self.removable_names
            ):
                self.removed.add(node.target.id)
                if isinstance(node.value, (ast.Call, ast.Await)):
                    return ast.copy_location(
                        ast.Expr(value=node.value),
                        node,
                    )
                return None
            return node

    for index, (path, original, source) in enumerate(updated):
        if path != harness_path:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        removed: set[str] = set()
        for function in [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]:
            loaded_names = {
                node.id
                for node in ast.walk(function)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
            }
            removable = unused_names - loaded_names
            if not removable:
                continue
            transformer = UnusedFixtureBindingRepair(removable)
            function.body = [
                transformed
                for statement in function.body
                for transformed in [transformer.visit(statement)]
                if transformed is not None
            ]
            removed.update(transformer.removed)
            if not function.body:
                function.body = [ast.Pass()]
        if not removed:
            continue
        ast.fix_missing_locations(tree)
        updated[index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
        notes.append(
            f"{path}: removed validator-proven unused disposable fixture "
            f"assignment(s): {', '.join(sorted(removed))}."
        )
    return updated, notes


def _repair_ephemeral_mocked_production_methods(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove disposable patches that replace the production method under test.

    :param validation_files: validation file records
    :param errors: deterministic harness-quality findings
    :param harness_path: disposable harness path
    :return: updated records and repair notes
    """

    if not harness_path:
        return validation_files, []
    mocked_methods = {
        method
        for group in re.findall(
            r"mocks production method under test:\s*"
            r"([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)",
            "\n".join(str(error) for error in errors),
        )
        for method in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", group)
    }
    if not mocked_methods:
        return validation_files, []

    class MockedOwnerRepair(ast.NodeTransformer):
        """Replace matching patch contexts with their unmocked executable body."""

        def __init__(self) -> None:
            self.removed: set[str] = set()

        def visit_With(self, node: ast.With) -> ast.stmt:
            matching: list[tuple[str, str]] = []
            for item in node.items:
                call = item.context_expr
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "patch"
                    and call.func.attr == "object"
                    and len(call.args) >= 2
                    and isinstance(call.args[1], ast.Constant)
                    and str(call.args[1].value) in mocked_methods
                ):
                    continue
                binding = (
                    item.optional_vars.id
                    if isinstance(item.optional_vars, ast.Name)
                    else ""
                )
                matching.append((str(call.args[1].value), binding))
            if not matching:
                return self.generic_visit(node)
            bindings = {binding for _method, binding in matching if binding}
            retained = [
                statement
                for statement in node.body
                if not any(
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id in bindings
                    for child in ast.walk(statement)
                )
            ]
            self.removed.update(method for method, _binding in matching)
            return ast.copy_location(
                ast.If(
                    test=ast.Constant(value=True),
                    body=[self.visit(statement) for statement in retained]
                    or [ast.Pass()],
                    orelse=[],
                ),
                node,
            )

    updated = list(validation_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if path != harness_path:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        transformer = MockedOwnerRepair()
        tree = transformer.visit(tree)
        if not transformer.removed:
            continue
        ast.fix_missing_locations(tree)
        corrected = ast.unparse(tree).rstrip() + "\n"
        compile(corrected, path, "exec")
        updated[index] = (path, original, corrected)
        notes.append(
            f"{path}: removed disposable patching of production method(s) "
            "under test: " + ", ".join(sorted(transformer.removed))
        )
    return updated, notes
