"""Validate generated declarations against approved implementation contracts."""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


_UI_ATTRIBUTE_SUFFIXES = (
    "_bar",
    "_btn",
    "_button",
    "_checkbox",
    "_combo",
    "_dial",
    "_editor",
    "_group",
    "_input",
    "_label",
    "_list",
    "_radio",
    "_slider",
    "_spinbox",
    "_stack",
    "_table",
    "_tabs",
    "_tree",
    "_view",
    "_widget",
)
_MODULE_CALLABLES = {
    name.casefold()
    for name in dir(builtins)
    if callable(getattr(builtins, name, None))
}
from tech_connector.services.implementation_plan_quality_contract import (
    APPROVED_PLAN_SCHEMA,
    APPROVED_PLAN_VALIDATOR_VERSION,
)

from tech_connector.services.implementation_plan_quality_service import (
    _structured_record_state_terms,
)


def validate_approved_declaration_contracts(
    implementation_plan: Mapping[str, Any],
    trees: Mapping[str, ast.Module],
    errors: list[str],
    requirement_text_by_id: Mapping[str, str],
) -> None:
    """
    Validates declaration ownership, UI wiring, and worker contracts.

    :param implementation_plan: Approved implementation plan.
    :param trees: Generated syntax trees keyed by resolved path.
    :param errors: Mutable validation error collection.
    :param requirement_text_by_id: Requirement text keyed by identifier.
    :return: None.
    """

    def approved_owner_node(
        tree: ast.Module,
        owner: str,
    ) -> ast.AST:
        if not owner or owner == "<module>":
            return tree
        owner_name = owner.rsplit(".", 1)[-1]
        return next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.name == owner_name
            ),
            tree,
        )

    def call_path(call: ast.Call) -> str:
        try:
            return ast.unparse(call.func)
        except (AttributeError, ValueError):
            return ""

    def expression_path(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except (AttributeError, ValueError):
            return ""

    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        tree = trees.get(path)
        declaration_contract = chunk.get("declaration_contract")
        if tree is None or not isinstance(declaration_contract, Mapping):
            continue
        owner = str(chunk.get("owner") or "<module>")
        owner_node = approved_owner_node(tree, owner)
        methods = {
            node.name: node
            for node in (
                owner_node.body
                if isinstance(owner_node, (ast.ClassDef, ast.Module))
                else [owner_node]
            )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        internal_mapping_keys: dict[str, set[str]] = {}
        tools_root = Path(__file__).resolve().parents[2]
        for import_node in (
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and str(node.module or "")
        ):
            imported_module = str(import_node.module or "")
            dependency_trees = [
                candidate_tree
                for candidate_path, candidate_tree in trees.items()
                if Path(candidate_path).stem
                == imported_module.rsplit(".", 1)[-1]
            ]
            module_path = tools_root.joinpath(
                *imported_module.split(".")
            ).with_suffix(".py")
            if module_path.is_file():
                try:
                    dependency_source = module_path.read_text(encoding="utf-8")
                    dependency_trees.append(
                        ast.parse(
                            dependency_source,
                            filename=str(module_path),
                        )
                    )
                except (OSError, UnicodeError, SyntaxError):
                    pass
            for dependency_tree in dependency_trees:
                for dependency_method in (
                    node
                    for node in ast.walk(dependency_tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    keys = {
                        str(key.value)
                        for dictionary in ast.walk(dependency_method)
                        if isinstance(dictionary, ast.Dict)
                        for key in dictionary.keys
                        if isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                    }
                    if keys:
                        internal_mapping_keys.setdefault(
                            dependency_method.name,
                            set(),
                        ).update(keys)
        if internal_mapping_keys:
            def validate_mapping_loop(
                method: ast.FunctionDef | ast.AsyncFunctionDef,
                result_name: str,
                proven_keys: set[str],
            ) -> None:
                for loop in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, (ast.For, ast.AsyncFor))
                    and isinstance(node.iter, ast.Name)
                    and node.iter.id == result_name
                    and isinstance(node.target, ast.Name)
                ):
                    item_name = loop.target.id
                    invalid_attributes = sorted({
                        f"{node.value.id}.{node.attr}"
                        for node in ast.walk(loop)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == item_name
                        and node.attr not in {
                            "clear",
                            "copy",
                            "get",
                            "items",
                            "keys",
                            "pop",
                            "popitem",
                            "setdefault",
                            "update",
                            "values",
                        }
                    })
                    invalid_keys = sorted({
                        str(node.slice.value)
                        for node in ast.walk(loop)
                        if isinstance(node, ast.Subscript)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == item_name
                        and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, str)
                        and str(node.slice.value) not in proven_keys
                    })
                    if invalid_attributes:
                        errors.append(
                            f"{path}:{owner}.{method.name}: internal dependency "
                            "returns mapping records; replace invented item "
                            "attributes with proven keys: "
                            + ", ".join(invalid_attributes)
                            + ". Proven keys: "
                            + ", ".join(sorted(proven_keys))
                            + "."
                        )
                    if invalid_keys:
                        errors.append(
                            f"{path}:{owner}.{method.name}: internal dependency "
                            "mapping does not prove key(s): "
                            + ", ".join(invalid_keys)
                            + ". Proven keys: "
                            + ", ".join(sorted(proven_keys))
                            + "."
                        )

            for method in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                result_schemas: dict[str, set[str]] = {}
                for assignment in ast.walk(method):
                    if not isinstance(
                        assignment,
                        (ast.Assign, ast.AnnAssign),
                    ) or not isinstance(assignment.value, ast.Call):
                        continue
                    terminal = call_path(assignment.value).rsplit(".", 1)[-1]
                    keys = internal_mapping_keys.get(terminal)
                    if not keys:
                        continue
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    ):
                        if isinstance(target, ast.Name):
                            result_schemas[target.id] = set(keys)
                for result_name, proven_keys in result_schemas.items():
                    validate_mapping_loop(method, result_name, proven_keys)

            for class_node in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, ast.ClassDef)
            ):
                methods_by_name = {
                    method.name: method
                    for method in class_node.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                worker_result_schemas: dict[str, set[str]] = {}
                for assignment in (
                    node
                    for method in methods_by_name.values()
                    for node in ast.walk(method)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    and isinstance(node.value, ast.Call)
                ):
                    operation_values = [
                        keyword.value
                        for keyword in assignment.value.keywords
                        if keyword.arg == "operation"
                    ]
                    if not operation_values:
                        continue
                    operation_name = expression_path(
                        operation_values[0]
                    ).rsplit(".", 1)[-1]
                    proven_keys = internal_mapping_keys.get(operation_name)
                    if not proven_keys:
                        continue
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    ):
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            worker_result_schemas[target.attr] = set(proven_keys)
                for call in (
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
                    and isinstance(node.args[0], ast.Attribute)
                    and isinstance(node.args[0].value, ast.Name)
                    and node.args[0].value.id == "self"
                ):
                    proven_keys = worker_result_schemas.get(
                        call.func.value.value.attr
                    )
                    handler = methods_by_name.get(call.args[0].attr)
                    if not proven_keys or handler is None:
                        continue
                    positional = [
                        *handler.args.posonlyargs,
                        *handler.args.args,
                    ]
                    if positional and positional[0].arg in {"self", "cls"}:
                        positional = positional[1:]
                    if positional:
                        validate_mapping_loop(
                            handler,
                            positional[0].arg,
                            proven_keys,
                        )
                        result_name = positional[0].arg
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
                            delegated = methods_by_name[
                                delegated_call.func.attr
                            ]
                            delegated_positional = [
                                *delegated.args.posonlyargs,
                                *delegated.args.args,
                            ]
                            if (
                                delegated_positional
                                and delegated_positional[0].arg
                                in {"self", "cls"}
                            ):
                                delegated_positional = delegated_positional[1:]
                            if not delegated_positional:
                                continue
                            delegated_name = delegated_positional[0].arg
                            consumes_collection = any(
                                isinstance(loop, (ast.For, ast.AsyncFor))
                                and isinstance(loop.iter, ast.Name)
                                and loop.iter.id == delegated_name
                                for loop in ast.walk(delegated)
                            )
                            if not consumes_collection:
                                continue
                            argument = delegated_call.args[0]
                            if (
                                isinstance(argument, ast.List)
                                and len(argument.elts) == 1
                                and isinstance(argument.elts[0], ast.Name)
                                and argument.elts[0].id == result_name
                            ):
                                errors.append(
                                    f"{path}:{owner}.{handler.name}: worker "
                                    "result is already a mapping-record "
                                    "collection; do not wrap it in another list "
                                    f"before `{delegated.name}`."
                                )
                            elif (
                                isinstance(argument, ast.Name)
                                and argument.id == result_name
                            ):
                                validate_mapping_loop(
                                    delegated,
                                    delegated_name,
                                    proven_keys,
                                )
        chunk_requirement_text = " ".join(
            (
                str(requirement.get("text") or requirement.get("requirement") or "")
                if isinstance(requirement, Mapping)
                else requirement_text_by_id.get(str(requirement), "")
            )
            for requirement in chunk.get("requirements") or []
        )
        selective_return_requested = bool(
            re.search(
                r"\breturn(?:s|ed|ing)?\b.+\b(?:for|matching|where|that are)\b"
                r".*\b(?:active|eligible|enabled|filtered|invalid|loaded|missing|"
                r"ready|selected|unloaded|valid)\b",
                chunk_requirement_text,
                flags=re.IGNORECASE,
            )
            and not re.search(
                r"\b(?:for|from)\s+(?:every|each|all)\s+selected\b",
                chunk_requirement_text,
                flags=re.IGNORECASE,
            )
        )
        if selective_return_requested:
            requested_record_states = set(
                _structured_record_state_terms(chunk_requirement_text)
            )
            for method in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                parent_by_id = {
                    id(child): parent
                    for parent in ast.walk(method)
                    for child in ast.iter_child_nodes(parent)
                }
                for loop in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, (ast.For, ast.AsyncFor))
                ):
                    loop_item_names = {
                        node.id
                        for node in ast.walk(loop.target)
                        if isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Store)
                    }
                    derived_predicate_names = {
                        target.id
                        for assignment in ast.walk(loop)
                        if isinstance(
                            assignment,
                            (ast.Assign, ast.AnnAssign),
                        )
                        and any(
                            isinstance(node, ast.Name)
                            and node.id in loop_item_names
                            for node in ast.walk(assignment.value)
                        )
                        for target in (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        if isinstance(target, ast.Name)
                    }
                    if "missing" in requested_record_states:
                        missing_assignments = [
                            assignment
                            for assignment in ast.walk(loop)
                            if isinstance(
                                assignment,
                                (ast.Assign, ast.AnnAssign),
                            )
                            and any(
                                isinstance(target, ast.Name)
                                and target.id == "missing"
                                for target in (
                                    assignment.targets
                                    if isinstance(assignment, ast.Assign)
                                    else [assignment.target]
                                )
                            )
                        ]
                        for assignment in missing_assignments:
                            value = assignment.value
                            blank_path_is_missing = not (
                                isinstance(value, ast.IfExp)
                                and isinstance(value.orelse, ast.Constant)
                                and value.orelse.value is False
                            )
                            has_existence_check = any(
                                isinstance(call, ast.Call)
                                and (
                                    (
                                        isinstance(call.func, ast.Attribute)
                                        and call.func.attr
                                        in {"exists", "is_file", "is_dir"}
                                    )
                                    or (
                                        isinstance(call.func, ast.Name)
                                        and call.func.id
                                        in {"exists", "isfile", "isdir"}
                                    )
                                )
                                for call in ast.walk(value)
                            )
                            if (
                                not blank_path_is_missing
                                or not has_existence_check
                            ):
                                errors.append(
                                    f"{path}:{owner}.{method.name}: path-backed "
                                    "`missing` state must treat a blank path as "
                                    "missing and use an explicit existence check."
                                )
                    for call in (
                        node
                        for node in ast.walk(loop)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"add", "append", "extend", "insert"}
                    ):
                        guarded_by_item_predicate = False
                        omitted_states: set[str] = set()
                        parent = parent_by_id.get(id(call))
                        while parent is not None and parent is not loop:
                            if isinstance(parent, ast.If):
                                predicate_names = {
                                    node.id
                                    for node in ast.walk(parent.test)
                                    if isinstance(node, ast.Name)
                                }
                                omitted_states = (
                                    requested_record_states - predicate_names
                                )
                                if (
                                    predicate_names & loop_item_names
                                    or (
                                        predicate_names
                                        & derived_predicate_names
                                        and not omitted_states
                                    )
                                    or (
                                        predicate_names
                                        & requested_record_states
                                        and not omitted_states
                                    )
                                ):
                                    guarded_by_item_predicate = True
                                    break
                            parent = parent_by_id.get(id(parent))
                        if not guarded_by_item_predicate:
                            if omitted_states:
                                errors.append(
                                    f"{path}:{owner}.{method.name}: selective "
                                    "return predicate omits requested state(s): "
                                    + ", ".join(sorted(omitted_states))
                                    + "."
                                )
                            else:
                                errors.append(
                                    f"{path}:{owner}.{method.name}: selective "
                                    "return requirement appends loop records "
                                    "without a per-record eligibility predicate."
                                )
                            break
        for helper in declaration_contract.get("helper_declarations") or []:
            if not isinstance(helper, Mapping):
                continue
            helper_owner = str(helper.get("owner") or "")
            helper_nodes = [
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and node.name == helper_owner
            ]
            if len(helper_nodes) != 1:
                errors.append(
                    f"{path}:{owner}: approved helper declaration "
                    f"`{helper_owner}` is missing from the target file."
                )
                continue
            helper_node = helper_nodes[0]
            helper_methods = {
                node.name
                for node in helper_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for required_method in helper.get("required_methods") or []:
                if str(required_method) not in helper_methods:
                    errors.append(
                        f"{path}:{helper_owner}: approved helper method "
                        f"`{required_method}` is missing."
                    )
            declared_helper_signals = {
                target.id: len(statement.value.args)
                for statement in helper_node.body
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                for target in (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                if isinstance(target, ast.Name)
                and isinstance(statement.value, ast.Call)
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
            }
            for signal_contract in helper.get("signals") or []:
                if not isinstance(signal_contract, Mapping):
                    continue
                signal_name = str(signal_contract.get("name") or "")
                expected_arity = len(signal_contract.get("arguments") or [])
                actual_arity = declared_helper_signals.get(signal_name)
                if actual_arity is None:
                    errors.append(
                        f"{path}:{helper_owner}: approved worker signal "
                        f"`{signal_name}` is not declared."
                    )
                elif actual_arity != expected_arity:
                    errors.append(
                        f"{path}:{helper_owner}: approved worker signal "
                        f"`{signal_name}` requires {expected_arity} payload "
                        f"argument(s), but its declaration has {actual_arity}."
                    )
                if signal_contract.get("emit_required"):
                    emitted = any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "emit"
                        and isinstance(call.func.value, ast.Attribute)
                        and isinstance(call.func.value.value, ast.Name)
                        and call.func.value.value.id == "self"
                        and call.func.value.attr == signal_name
                        for call in ast.walk(helper_node)
                    )
                    emitted = emitted or any(
                        isinstance(node, ast.Attribute)
                        and node.attr == "emit"
                        and isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id == "self"
                        and node.value.attr == signal_name
                        for node in ast.walk(helper_node)
                    )
                    if not emitted:
                        errors.append(
                            f"{path}:{helper_owner}: approved worker signal "
                            f"`{signal_name}` is declared but never emitted."
                        )
            inferred_progress_injection = any(
                isinstance(signal_contract, Mapping)
                and str(signal_contract.get("name") or "") == "progress"
                and bool(signal_contract.get("emit_required"))
                for signal_contract in helper.get("signals") or []
            )
            if (
                helper.get("inject_progress_callback_before_invoke")
                or inferred_progress_injection
            ):
                callback_parameter = str(
                    helper.get("progress_callback_parameter")
                    or "progress_callback"
                )
                callback_value = str(
                    helper.get("progress_callback_value")
                    or "self.progress.emit"
                )
                run_method = next(
                    (
                        node
                        for node in helper_node.body
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == "run"
                    ),
                    None,
                )
                operation_calls = [
                    node
                    for node in ast.walk(run_method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr == "operation"
                ] if run_method is not None else []
                injection_lines: list[int] = []
                for node in ast.walk(run_method) if run_method is not None else []:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = (
                            node.targets
                            if isinstance(node, ast.Assign)
                            else [node.target]
                        )
                        value = node.value
                        for target in targets:
                            if (
                                isinstance(target, ast.Subscript)
                                and isinstance(target.value, ast.Attribute)
                                and isinstance(target.value.value, ast.Name)
                                and target.value.value.id == "self"
                                and target.value.attr == "kwargs"
                                and isinstance(target.slice, ast.Constant)
                                and target.slice.value == callback_parameter
                                and isinstance(value, ast.Attribute)
                                and isinstance(value.value, ast.Attribute)
                                and isinstance(value.value.value, ast.Name)
                                and value.value.value.id == "self"
                                and f"self.{value.value.attr}.{value.attr}"
                                == callback_value
                            ):
                                injection_lines.append(
                                    int(getattr(node, "lineno", 0))
                                )
                    if isinstance(node, ast.Call) and node in operation_calls:
                        for keyword in node.keywords:
                            if (
                                keyword.arg == callback_parameter
                                and isinstance(keyword.value, ast.Attribute)
                                and isinstance(
                                    keyword.value.value,
                                    ast.Attribute,
                                )
                                and isinstance(
                                    keyword.value.value.value,
                                    ast.Name,
                                )
                                and keyword.value.value.value.id == "self"
                                and (
                                    f"self.{keyword.value.value.attr}."
                                    f"{keyword.value.attr}"
                                )
                                == callback_value
                            ):
                                injection_lines.append(
                                    int(getattr(node, "lineno", 0))
                                )
                first_operation_line = min(
                    (
                        int(getattr(node, "lineno", 0))
                        for node in operation_calls
                    ),
                    default=0,
                )
                if (
                    not injection_lines
                    or not first_operation_line
                    or min(injection_lines) > first_operation_line
                ):
                    errors.append(
                        f"{path}:{helper_owner}.run: approved worker operation "
                        f"must inject `{callback_parameter}={callback_value}` "
                        "before invoking the blocking operation."
                    )
        if isinstance(owner_node, ast.ClassDef):
            helper_owner_names = {
                str(helper.get("owner") or "")
                for helper in declaration_contract.get("helper_declarations") or []
                if isinstance(helper, Mapping)
                and str(helper.get("owner") or "")
            }
            for method in owner_node.body:
                if not isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                constructs_worker = any(
                    isinstance(call, ast.Call)
                    and (
                        (
                            isinstance(call.func, ast.Name)
                            and call.func.id in helper_owner_names
                        )
                        or (
                            isinstance(call.func, ast.Attribute)
                            and call.func.attr in helper_owner_names
                        )
                    )
                    for call in ast.walk(method)
                )
                if not constructs_worker:
                    continue
                worker_lambda_callbacks = {
                    str(keyword.arg)
                    for lambda_node in ast.walk(method)
                    if isinstance(lambda_node, ast.Lambda)
                    for call in ast.walk(lambda_node.body)
                    if isinstance(call, ast.Call)
                    for keyword in call.keywords
                    if keyword.arg and keyword.arg.endswith("callback")
                }
                direct_ui_callbacks = {
                    keyword.value.attr
                    for lambda_node in ast.walk(method)
                    if isinstance(lambda_node, ast.Lambda)
                    for call in ast.walk(lambda_node.body)
                    if isinstance(call, ast.Call)
                    for keyword in call.keywords
                    if keyword.arg
                    and keyword.arg.endswith("callback")
                    and isinstance(keyword.value, ast.Attribute)
                    and isinstance(keyword.value.value, ast.Name)
                    and keyword.value.value.id == "self"
                }
                local_ui_callback_names = {
                    nested.name
                    for nested in method.body
                    if isinstance(
                        nested,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and any(
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        for node in ast.walk(nested)
                    )
                }
                direct_ui_callbacks.update(
                    keyword.value.id
                    for lambda_node in ast.walk(method)
                    if isinstance(lambda_node, ast.Lambda)
                    for call in ast.walk(lambda_node.body)
                    if isinstance(call, ast.Call)
                    for keyword in call.keywords
                    if keyword.arg
                    and keyword.arg.endswith("callback")
                    and isinstance(keyword.value, ast.Name)
                    and keyword.value.id in local_ui_callback_names
                )
                direct_ui_callbacks.update(worker_lambda_callbacks)
                if direct_ui_callbacks:
                    errors.append(
                        f"{path}:{owner}.{method.name}: worker operation passes "
                        "dialog-bound callback(s) directly across the thread "
                        "boundary: "
                        + ", ".join(
                            f"self.{name}" for name in sorted(direct_ui_callbacks)
                        )
                        + ". Route worker progress through its approved signal."
                    )
        if isinstance(owner_node, ast.ClassDef):
            for method in owner_node.body:
                if not isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                local_signals = {
                    target.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    and isinstance(assignment.value, ast.Call)
                    and ast.unparse(assignment.value.func).rsplit(".", 1)[-1]
                    == "Signal"
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Name)
                }
                if local_signals:
                    errors.append(
                        f"{path}:{owner}.{method.name}: Qt Signal declaration(s) "
                        "must be class attributes on a QObject-derived owner, not "
                        "local method values: "
                        + ", ".join(sorted(local_signals))
                        + "."
                    )
        owner_calls = [
            call
            for call in ast.walk(owner_node)
            if isinstance(call, ast.Call)
        ]
        owner_call_paths = [call_path(call) for call in owner_calls]
        owner_call_terminals = {
            value.rsplit(".", 1)[-1] for value in owner_call_paths if value
        }
        owner_callable_reference_terminals = {
            node.attr
            for node in ast.walk(owner_node)
            if isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
        }
        if owner != "<module>":
            imported_bindings = {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            imported_bindings.update(
                alias.asname or alias.name.split(".", 1)[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            plan_chunks_by_id = {
                str(candidate_chunk.get("chunk_id") or ""): candidate_chunk
                for candidate_chunk in implementation_plan.get("chunks") or []
                if isinstance(candidate_chunk, Mapping)
                and str(candidate_chunk.get("chunk_id") or "")
            }
            for dependency_id in chunk.get("depends_on") or []:
                dependency_chunk = plan_chunks_by_id.get(
                    str(dependency_id), {}
                )
                dependency_owner = str(
                    dependency_chunk.get("owner") or ""
                )
                dependency_path = str(
                    Path(
                        str(dependency_chunk.get("path") or "")
                    ).resolve()
                )
                if (
                    not dependency_owner
                    or dependency_owner == "<module>"
                    or dependency_path == path
                ):
                    continue
                required_dependency_interfaces = [
                    item
                    for item in chunk.get(
                        "required_dependency_interfaces", []
                    )
                    if isinstance(item, Mapping)
                    and str(item.get("producer_chunk") or "")
                    == str(dependency_id)
                    and not bool(item.get("approval_required"))
                ]
                if not required_dependency_interfaces:
                    continue
                dependency_methods = {
                    match.group(1)
                    for item in required_dependency_interfaces
                    for match in [
                        re.search(
                            r"\bdef\s+([a-z_][A-Za-z0-9_]*)\s*\(",
                            str(item.get("signature") or ""),
                        )
                    ]
                    if match
                }
                dependency_referenced = any(
                    isinstance(node, ast.Name)
                    and node.id == dependency_owner
                    for node in ast.walk(owner_node)
                )
                if dependency_owner not in imported_bindings:
                    errors.append(
                        f"[owner:<module>] [repair-scope:module] "
                        f"{path}:<module>: "
                        "approved cross-file dependency "
                        f"`{dependency_owner}` required by `{owner}` is not "
                        "imported."
                    )
                elif not dependency_referenced:
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        f"approved cross-file dependency `{dependency_owner}` is "
                        "imported but never consumed as a type, value, constructor, "
                        "or explicitly approved callable."
                    )
                if dependency_methods and not (
                    dependency_methods
                    & (
                        owner_call_terminals
                        | owner_callable_reference_terminals
                    )
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        "approved cross-file dependency "
                        f"`{dependency_owner}` is not consumed through any "
                        "consumer-approved callable: "
                        + ", ".join(sorted(dependency_methods))
                        + "."
                    )
        required_calls = [
            item
            for item in declaration_contract.get("required_calls") or []
            if (
                isinstance(item, Mapping)
                and str(item.get("name") or "")
                and not (
                    not str(item.get("signature") or "")
                    and str(item.get("name") or "")
                    .rsplit(".", 1)[-1][:1]
                    .isupper()
                )
            )
        ]
        required_call_names = {
            str(item.get("name") or "") for item in required_calls
        }
        required_calls.extend(
            {
                "name": str(
                    item.get("qualified_name") or item.get("name") or ""
                ),
                "import_statement": str(item.get("import_statement") or ""),
            }
            for item in chunk.get("evidence") or []
            if isinstance(item, Mapping)
            and bool(item.get("selected_for_generation"))
            and str(item.get("signature") or "")
            and not str(
                item.get("qualified_name") or item.get("name") or ""
            ).rsplit(".", 1)[-1][:1].isupper()
            and str(item.get("qualified_name") or item.get("name") or "")
            not in required_call_names
        )
        def evidence_mapping_keys(
            required_name: str,
        ) -> set[str]:
            excerpts = [
                str(item.get("source_excerpt") or item.get("source") or "")
                for item in chunk.get("evidence") or []
                if isinstance(item, Mapping)
                and (
                    str(item.get("name") or "") == required_name
                    or str(item.get("qualified_name") or "") == required_name
                    or str(
                        item.get("qualified_name") or item.get("name") or ""
                    ).endswith("." + required_name)
                    or str(
                        item.get("qualified_name") or item.get("name") or ""
                    ).rsplit(".", 1)[-1]
                    == required_name.rsplit(".", 1)[-1]
                )
                and str(
                    item.get("source_excerpt") or item.get("source") or ""
                ).strip()
            ]
            if not excerpts:
                required_terminal = required_name.rsplit(".", 1)[-1]
                tools_root = Path(__file__).resolve().parents[2]
                for import_node in (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and str(node.module or "")
                ):
                    module_path = tools_root.joinpath(
                        *str(import_node.module).split(".")
                    ).with_suffix(".py")
                    if not module_path.is_file():
                        continue
                    try:
                        dependency_source = module_path.read_text(
                            encoding="utf-8"
                        )
                        dependency_tree = ast.parse(
                            dependency_source,
                            filename=str(module_path),
                        )
                    except (OSError, UnicodeError, SyntaxError):
                        continue
                    for method in (
                        node
                        for node in ast.walk(dependency_tree)
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == required_terminal
                    ):
                        excerpt = (
                            ast.get_source_segment(dependency_source, method)
                            or ast.unparse(method)
                        )
                        if excerpt:
                            excerpts.append(excerpt)
            keys: set[str] = set()
            pending = list(excerpts)
            visited: set[str] = set()
            while pending:
                raw_excerpt = pending.pop()
                raw_lines = str(raw_excerpt).splitlines()
                first_content = next(
                    (line for line in raw_lines if line.strip()),
                    "",
                )
                leading_indent = len(first_content) - len(
                    first_content.lstrip()
                )
                excerpt = "\n".join(
                    (
                        line[leading_indent:]
                        if leading_indent
                        and line.startswith(" " * leading_indent)
                        else line
                    )
                    for line in raw_lines
                ).strip()
                if not excerpt or excerpt in visited:
                    continue
                visited.add(excerpt)
                try:
                    excerpt_tree = ast.parse(excerpt)
                except SyntaxError:
                    try:
                        excerpt_tree = ast.parse(
                            "class _IndexedEvidence:\n" + excerpt
                        )
                    except SyntaxError:
                        continue
                for node in ast.walk(excerpt_tree):
                    if isinstance(node, ast.Dict):
                        keys.update(
                            str(key.value)
                            for key in node.keys
                            if isinstance(key, ast.Constant)
                            and isinstance(key.value, str)
                        )
                    elif (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and ("{" in node.value or "dict(" in node.value)
                    ):
                        pending.append(node.value)
            return keys

        def assigned_names(node: ast.AST) -> set[str]:
            return {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Store)
            }

        for required_call in required_calls:
            required_name = str(required_call.get("name") or "")
            required_terminal = required_name.rsplit(".", 1)[-1]
            mapping_keys = evidence_mapping_keys(required_name)
            if mapping_keys:
                for method in (
                    node
                    for node in ast.walk(owner_node)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    result_names = {
                        target.id
                        for assignment in ast.walk(method)
                        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        and isinstance(assignment.value, ast.Call)
                        and call_path(assignment.value).rsplit(".", 1)[-1]
                        == required_terminal
                        for target in (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        if isinstance(target, ast.Name)
                    }
                    if not result_names:
                        continue
                    item_names = {
                        item_name
                        for loop in ast.walk(method)
                        if isinstance(loop, (ast.For, ast.AsyncFor))
                        and isinstance(loop.iter, ast.Name)
                        and loop.iter.id in result_names
                        for item_name in assigned_names(loop.target)
                    }
                    invalid_attributes = sorted({
                        f"{node.value.id}.{node.attr}"
                        for node in ast.walk(method)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in item_names
                        and node.attr not in {
                            "clear",
                            "copy",
                            "get",
                            "items",
                            "keys",
                            "pop",
                            "popitem",
                            "setdefault",
                            "update",
                            "values",
                        }
                    })
                    invalid_keys = sorted({
                        str(node.slice.value)
                        for node in ast.walk(method)
                        if isinstance(node, ast.Subscript)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in item_names
                        and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, str)
                        and str(node.slice.value) not in mapping_keys
                    })
                    if invalid_attributes:
                        errors.append(
                            f"{path}:{owner}.{method.name}: verified dependency "
                            f"`{required_name}` returns mapping records; consume "
                            "their proven keys with subscription instead of invented "
                            "attributes: "
                            + ", ".join(invalid_attributes)
                            + "."
                        )
                    if invalid_keys:
                        errors.append(
                            f"{path}:{owner}.{method.name}: verified dependency "
                            f"`{required_name}` records do not prove requested key(s): "
                            + ", ".join(invalid_keys)
                            + ". Proven keys: "
                            + ", ".join(sorted(mapping_keys))
                            + "."
                        )
            verified_import = str(
                required_call.get("import_statement") or ""
            ).strip()
            if verified_import:
                try:
                    verified_import_node = ast.parse(
                        verified_import,
                        filename="<verified-import>",
                    ).body[0]
                except (SyntaxError, IndexError):
                    verified_import_node = None
                import_root = ""
                if isinstance(verified_import_node, ast.ImportFrom):
                    import_root = str(verified_import_node.module or "").split(
                        ".",
                        1,
                    )[0]
                elif isinstance(verified_import_node, ast.Import):
                    import_root = verified_import_node.names[0].name.split(
                        ".",
                        1,
                    )[0]
                if (
                    verified_import_node is not None
                    and import_root not in {
                        "bpy",
                        "maya",
                        "pyfbsdk",
                        "unreal",
                    }
                    and not any(
                        ast.dump(node, include_attributes=False)
                        == ast.dump(
                            verified_import_node,
                            include_attributes=False,
                        )
                        for node in tree.body
                        if isinstance(node, (ast.Import, ast.ImportFrom))
                    )
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        "verified internal dependency import must exist at module "
                        f"scope exactly as `{verified_import}`. Localizing the "
                        "import inside a callable changes the patch/runtime "
                        "binding and is not the approved import surface."
                    )
            matching_calls = [
                call
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1]
                == required_terminal
            ]
            if not matching_calls:
                errors.append(
                    f"{path}:{owner}: approved behavior requires verified call "
                    f"`{required_name}` with signature "
                    f"`{required_call.get('signature') or ''}`, but "
                    "the owning AST contains no invocation of that callable."
                )
                continue
            approved_error_semantics = bool(
                re.search(
                    r"\b(?:error|exception|fail(?:ure)?|reject|unavailable|"
                    r"fallback)\b",
                    " ".join(
                        str(requirement.get("text") or "")
                        for requirement in chunk.get("requirements") or []
                        if isinstance(requirement, Mapping)
                    ),
                    flags=re.IGNORECASE,
                )
            )
            if not approved_error_semantics:
                matching_call_ids = {id(call) for call in matching_calls}
                for method_name, method_node in methods.items():
                    if not any(
                        id(call) in matching_call_ids
                        for call in ast.walk(method_node)
                        if isinstance(call, ast.Call)
                    ):
                        continue
                    for try_node in (
                        node
                        for node in ast.walk(method_node)
                        if isinstance(node, ast.Try)
                    ):
                        for handler in try_node.handlers:
                            broad_handler = (
                                handler.type is None
                                or (
                                    isinstance(handler.type, ast.Name)
                                    and handler.type.id
                                    in {"BaseException", "Exception"}
                                )
                            )
                            if not broad_handler:
                                continue
                            fallback_return = any(
                                isinstance(node, ast.Return)
                                and node.value is not None
                                for statement in handler.body
                                for node in ast.walk(statement)
                            )
                            fallback_output = any(
                                isinstance(node, ast.Call)
                                and call_path(node).rsplit(".", 1)[-1]
                                in {"print", "showMessage", "warning"}
                                for statement in handler.body
                                for node in ast.walk(statement)
                            )
                            if fallback_return or fallback_output:
                                errors.append(
                                    f"[owner:{owner}] [repair-scope:class] "
                                    f"{path}:{owner}.{method_name}: verified "
                                    f"call `{required_name}` is wrapped in an "
                                    "unrequested catch-all error path that "
                                    "prints, displays, or returns fallback data. "
                                    "Preserve the approved dependency result and "
                                    "let unspecified failures propagate."
                                )
            signature = str(required_call.get("signature") or "")
            if signature and "(" in signature and ")" in signature:
                try:
                    signature_tree = ast.parse(
                        "def _verified"
                        + signature[signature.find("("):]
                        + ":\n    pass\n"
                    )
                    signature_args = signature_tree.body[0].args
                except SyntaxError:
                    signature_args = None
                if signature_args is not None:
                    positional_parameters = [
                        *signature_args.posonlyargs,
                        *signature_args.args,
                    ]
                    if (
                        positional_parameters
                        and positional_parameters[0].arg
                        in {"self", "cls"}
                    ):
                        positional_parameters = positional_parameters[1:]
                    maximum_positional = (
                        None
                        if signature_args.vararg is not None
                        else len(positional_parameters)
                    )
                    if maximum_positional is not None:
                        for call in matching_calls:
                            if len(call.args) > maximum_positional:
                                errors.append(
                                    f"{path}:{owner}: verified call "
                                    f"`{required_name}` receives "
                                    f"{len(call.args)} positional argument(s), "
                                    f"but its indexed signature permits at most "
                                    f"{maximum_positional}."
                                )
            parameter_types = {
                str(name): str(type_name)
                for name, type_name in (
                    required_call.get("parameter_types") or {}
                ).items()
                if str(name) and str(type_name)
            }
            if parameter_types:
                assigned_values: dict[str, ast.AST] = {}
                for assignment in ast.walk(owner_node):
                    if (
                        isinstance(assignment, ast.Assign)
                        and len(assignment.targets) == 1
                        and isinstance(assignment.targets[0], ast.Name)
                    ):
                        assigned_values[assignment.targets[0].id] = assignment.value
                    elif (
                        isinstance(assignment, ast.AnnAssign)
                        and isinstance(assignment.target, ast.Name)
                        and assignment.value is not None
                    ):
                        assigned_values[assignment.target.id] = assignment.value

                def inferred_value_kind(
                    value: ast.AST,
                    seen: set[str] | None = None,
                ) -> str:
                    if isinstance(value, ast.Constant):
                        return type(value.value).__name__
                    if isinstance(value, (ast.List, ast.ListComp)):
                        return "list"
                    if isinstance(value, (ast.Tuple, ast.GeneratorExp)):
                        return "tuple"
                    if isinstance(value, (ast.Dict, ast.DictComp)):
                        return "dict"
                    if isinstance(value, ast.Set):
                        return "set"
                    if isinstance(value, ast.Name):
                        visited = set(seen or ())
                        if value.id in visited or value.id not in assigned_values:
                            return ""
                        visited.add(value.id)
                        return inferred_value_kind(
                            assigned_values[value.id],
                            visited,
                        )
                    if isinstance(value, ast.Call):
                        terminal = call_path(value).rsplit(".", 1)[-1]
                        if terminal in {"text", "currentText"}:
                            return "str"
                        if terminal in {"split", "splitlines", "list"}:
                            return "list"
                        if terminal == "dict":
                            return "dict"
                        if terminal in {"int", "value"}:
                            return "int"
                        if terminal == "float":
                            return "float"
                        if terminal in {"bool", "isChecked"}:
                            return "bool"
                    return ""

                def resolved_assigned_value(
                    value: ast.AST,
                    seen: set[str] | None = None,
                ) -> ast.AST:
                    if not isinstance(value, ast.Name):
                        return value
                    visited = set(seen or ())
                    if value.id in visited or value.id not in assigned_values:
                        return value
                    visited.add(value.id)
                    return resolved_assigned_value(
                        assigned_values[value.id],
                        visited,
                    )

                def is_raw_singleton_text_collection(value: ast.AST) -> bool:
                    resolved = resolved_assigned_value(value)
                    if not isinstance(resolved, (ast.List, ast.Tuple)):
                        return False
                    if len(resolved.elts) != 1:
                        return False
                    element = resolved_assigned_value(resolved.elts[0])
                    return (
                        isinstance(element, ast.Call)
                        and call_path(element).rsplit(".", 1)[-1]
                        in {"text", "currentText"}
                    )

                parameter_order = [
                    parameter.arg
                    for parameter in (
                        [*signature_args.posonlyargs, *signature_args.args]
                        if signature_args is not None
                        else []
                    )
                    if parameter.arg not in {"self", "cls"}
                ]
                for call in matching_calls:
                    supplied = {
                        parameter_order[index]: argument
                        for index, argument in enumerate(call.args)
                        if index < len(parameter_order)
                    }
                    supplied.update({
                        str(keyword.arg): keyword.value
                        for keyword in call.keywords
                        if keyword.arg
                    })
                    for parameter_name, argument in supplied.items():
                        expected_type = parameter_types.get(
                            parameter_name, ""
                        ).casefold()
                        actual_kind = inferred_value_kind(argument)
                        expected_kind = next(
                            (
                                kind
                                for kind in (
                                    "list",
                                    "dict",
                                    "tuple",
                                    "set",
                                    "str",
                                    "bool",
                                    "int",
                                    "float",
                                )
                                if re.search(rf"\b{kind}\b", expected_type)
                            ),
                            "",
                        )
                        if (
                            expected_kind
                            and actual_kind
                            and actual_kind != expected_kind
                        ):
                            errors.append(
                                f"{path}:{owner}: verified call `{required_name}` "
                                f"passes `{parameter_name}` as `{actual_kind}`, but "
                                "authoritative API evidence requires "
                                f"`{parameter_types[parameter_name]}`."
                            )
                        optional_collection = bool(
                            re.search(
                                r"\b(?:list|tuple|set)\b",
                                expected_type,
                            )
                            and re.search(
                                r"\b(?:none|optional)\b",
                                expected_type,
                            )
                        )
                        if (
                            optional_collection
                            and is_raw_singleton_text_collection(argument)
                        ):
                            errors.append(
                                f"[owner:{owner}] [repair-scope:class] "
                                f"{path}:{owner}: verified optional collection "
                                f"parameter `{parameter_name}` for "
                                f"`{required_name}` wraps raw UI text as a "
                                "single element without normalizing an empty "
                                "value. Strip and parse the text, then pass a "
                                "typed collection only when values remain; "
                                "otherwise pass None."
                            )
        called_attribute_nodes = {
            id(call.func)
            for call in owner_calls
            if isinstance(call.func, ast.Attribute)
        }
        owner_access_terminals = {
            node.attr
            for node in ast.walk(owner_node)
            if isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and id(node) not in called_attribute_nodes
        }
        for required_access in (
            declaration_contract.get("required_accesses") or []
        ):
            if not isinstance(required_access, Mapping):
                continue
            required_name = str(required_access.get("name") or "")
            required_terminal = required_name.rsplit(".", 1)[-1]
            if required_terminal not in owner_access_terminals:
                errors.append(
                    f"{path}:{owner}: approved behavior requires property access "
                    f"`{required_name}`, but the owning AST contains no non-call "
                    "attribute read for that property."
                )
        required_call_order = [
            str(value)
            for value in declaration_contract.get("required_call_order") or []
            if str(value)
        ]
        if required_call_order:
            required_terminals = [
                value.rsplit(".", 1)[-1] for value in required_call_order
            ]
            callable_nodes = [
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            ordered_chain_found = False
            for callable_node in callable_nodes:
                terminal_sequence = [
                    call_path(call).rsplit(".", 1)[-1]
                    for call in sorted(
                        (
                            node
                            for node in ast.walk(callable_node)
                            if isinstance(node, ast.Call)
                        ),
                        key=lambda node: (
                            int(getattr(node, "lineno", 0)),
                            int(getattr(node, "col_offset", 0)),
                        ),
                    )
                    if call_path(call)
                ]
                cursor = 0
                for terminal in terminal_sequence:
                    if terminal == required_terminals[cursor]:
                        cursor += 1
                        if cursor == len(required_terminals):
                            ordered_chain_found = True
                            break
                if ordered_chain_found:
                    break
            if not ordered_chain_found:
                errors.append(
                    f"{path}:{owner}: no orchestration callable executes the "
                    "approved verified capability chain in order: "
                    + " -> ".join(required_call_order)
                    + "."
                )
        chunk_requirement_text = " ".join(
            str(requirement.get("text") or "")
            for requirement in chunk.get("requirements") or []
            if isinstance(requirement, Mapping)
        )
        direct_owner_callables = (
            [
                callable_node
                for callable_node in owner_node.body
                if isinstance(
                    callable_node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            ]
            if isinstance(owner_node, ast.ClassDef)
            else [owner_node]
            if isinstance(
                owner_node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
            else []
        )
        requested_finally_cleanup_verbs = {
            value.casefold()
            for value in re.findall(
                r"\b(cleanup|close|delete|destroy|dispose|release|remove|unlink)\w*\b",
                chunk_requirement_text,
                flags=re.IGNORECASE,
            )
        }
        explicit_finally_cleanup = bool(
            requested_finally_cleanup_verbs
            and re.search(r"\bfinally\b", chunk_requirement_text, re.IGNORECASE)
            and re.search(r"\balways\b", chunk_requirement_text, re.IGNORECASE)
        )
        if explicit_finally_cleanup:
            finally_call_terminals = {
                call_path(call).rsplit(".", 1)[-1].casefold()
                for callable_node in direct_owner_callables
                for try_node in ast.walk(callable_node)
                if isinstance(try_node, ast.Try) and try_node.finalbody
                for statement in try_node.finalbody
                for call in ast.walk(statement)
                if isinstance(call, ast.Call) and call_path(call)
            }
            cleanup_proven = any(
                any(
                    terminal == verb
                    or terminal.startswith(f"{verb}_")
                    or terminal.endswith(f"_{verb}")
                    for verb in requested_finally_cleanup_verbs
                )
                for terminal in finally_call_terminals
            )
            if not cleanup_proven:
                errors.append(
                    f"{path}:{owner}: requested always-on lifecycle cleanup "
                    "must execute the requested cleanup operation in a finally path."
                )
        if isinstance(owner_node, ast.ClassDef):
            referenced_private_names = {
                node.attr
                for node in ast.walk(owner_node)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"self", "cls"}
                and node.attr.startswith("_")
            }
            unreferenced_private_helpers = sorted(
                callable_node.name
                for callable_node in direct_owner_callables
                if callable_node.name.startswith("_")
                and not callable_node.name.startswith("__")
                and callable_node.name not in referenced_private_names
            )
            if unreferenced_private_helpers:
                errors.append(
                    f"{path}:{owner}: private helper callable(s) are never "
                    "referenced by production behavior and introduce dead code: "
                    + ", ".join(unreferenced_private_helpers)
                    + "."
                )
        progress_callback_owners = [
            callable_node
            for callable_node in direct_owner_callables
            if any(
                argument.arg == "progress_callback"
                for argument in (
                    *callable_node.args.posonlyargs,
                    *callable_node.args.args,
                    *callable_node.args.kwonlyargs,
                )
            )
        ]
        if progress_callback_owners and re.search(
            r"\bprogress_callback\b",
            chunk_requirement_text,
            flags=re.IGNORECASE,
        ):
            progress_error_owner = owner
            if (
                isinstance(owner_node, ast.ClassDef)
                and "." not in progress_error_owner
            ):
                progress_error_owner = (
                    f"{owner}.{progress_callback_owners[0].name}"
                )
            progress_calls = [
                call
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1] == "progress_callback"
            ]
            if len(progress_calls) < 2:
                errors.append(
                    f"{path}:{progress_error_owner}: requested progress updates "
                    "require at "
                    "least two observable callback invocations."
                )
            has_iterative_work = any(
                isinstance(
                    node,
                    (
                        ast.For,
                        ast.AsyncFor,
                        ast.ListComp,
                        ast.SetComp,
                        ast.DictComp,
                        ast.GeneratorExp,
                    ),
                )
                for callable_node in progress_callback_owners
                for node in ast.walk(callable_node)
            )
            fixed_progress_totals = [
                call.args[1]
                for call in progress_calls
                if len(call.args) >= 2
                and isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, int)
            ]
            if (
                has_iterative_work
                and len(fixed_progress_totals) == len(progress_calls)
                and progress_calls
            ):
                errors.append(
                    f"{path}:{progress_error_owner}: iterative work reports only "
                    "fixed progress totals; derive total_steps from the actual work "
                    "collection and emit monotonic progress as units complete."
                )
            operation_terminals = {
                str(item.get("name") or "").rsplit(".", 1)[-1]
                for item in required_calls
            }
            operation_lines = [
                int(getattr(call, "lineno", 0))
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1]
                in operation_terminals
            ]
            progress_lines = [
                int(getattr(call, "lineno", 0))
                for call in progress_calls
            ]
            if (
                operation_lines
                and progress_lines
                and min(progress_lines) >= max(operation_lines)
            ):
                progress_owner_names = [
                    callable_node.name
                    for callable_node in ast.walk(owner_node)
                    if isinstance(
                        callable_node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and any(
                        isinstance(call, ast.Call)
                        and call_path(call).rsplit(".", 1)[-1]
                        in operation_terminals
                        for call in ast.walk(callable_node)
                    )
                ]
                progress_owner = (
                    f"{owner}.{progress_owner_names[0]}"
                    if len(set(progress_owner_names)) == 1
                    else owner
                )
                errors.append(
                    f"{path}:{progress_owner}: all progress updates occur after the "
                    "approved work; progress must span the operation lifecycle."
                )
        if re.search(
            r"\btemporary\b.*\b(?:file|path|directory|artifact)\b",
            chunk_requirement_text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            persistent_temp_calls = []
            temporary_provider_calls = []
            for call in owner_calls:
                terminal = call_path(call).rsplit(".", 1)[-1]
                if terminal in {
                    "NamedTemporaryFile",
                    "TemporaryDirectory",
                    "mkdtemp",
                    "mkstemp",
                }:
                    temporary_provider_calls.append(call)
                if terminal in {"mkstemp", "mkdtemp"}:
                    persistent_temp_calls.append(call)
                    continue
                if terminal != "NamedTemporaryFile":
                    continue
                delete_keyword = next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == "delete"
                    ),
                    None,
                )
                if (
                    isinstance(delete_keyword, ast.Constant)
                    and delete_keyword.value is False
                ):
                    persistent_temp_calls.append(call)
            cleanup_terminals = {
                "cleanup",
                "remove",
                "rmdir",
                "rmtree",
                "unlink",
            }
            cleanup_calls = [
                call
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1]
                in cleanup_terminals
            ]
            finally_cleanup = any(
                call_path(call).rsplit(".", 1)[-1] in cleanup_terminals
                for try_node in ast.walk(owner_node)
                if isinstance(try_node, ast.Try) and try_node.finalbody
                for statement in try_node.finalbody
                for call in ast.walk(statement)
                if isinstance(call, ast.Call)
            )
            if not temporary_provider_calls:
                errors.append(
                    f"{path}:{owner}: requested temporary resources require "
                    "a temporary-file/directory provider rather than a fixed path."
                )
            if (
                persistent_temp_calls or cleanup_calls
            ) and not finally_cleanup:
                errors.append(
                    f"{path}:{owner}: persistent temporary resources require "
                    "cleanup in a finally path."
                )
        execution_constraints = (
            declaration_contract.get("execution_constraints")
            if isinstance(
                declaration_contract.get("execution_constraints"), Mapping
            )
            else {}
        )
        if execution_constraints.get("requires_off_ui_thread"):
            forbidden_ui_calls = {
                str(value)
                for value in execution_constraints.get(
                    "forbidden_ui_calls", []
                )
                if str(value)
            }
            forbidden_hits = sorted({
                value
                for value in owner_call_paths
                if value.rsplit(".", 1)[-1] in forbidden_ui_calls
            })
            if forbidden_hits:
                errors.append(
                    f"{path}:{owner}: off-UI-thread contract forbids blocking or "
                    "event-pumping calls in the UI owner: "
                    + ", ".join(forbidden_hits)
                    + "."
                )
            dispatch_terminals = {
                "start",
                "submit",
                "run_in_executor",
                "startThread",
            }
            has_background_dispatch = bool(
                owner_call_terminals & dispatch_terminals
            )
            if not has_background_dispatch:
                errors.append(
                    f"{path}:{owner}: off-UI-thread contract has no approved "
                    "background dispatch call such as a worker/thread start, "
                    "executor submit, or event-loop executor dispatch."
                )
            helper_names = {
                str(helper.get("owner") or "")
                for helper in declaration_contract.get(
                    "helper_declarations", []
                )
                if isinstance(helper, Mapping)
                and str(helper.get("owner") or "")
            }
            for method in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                local_workers = {
                    target.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    and isinstance(assignment.value, ast.Call)
                    and isinstance(assignment.value.func, ast.Name)
                    and assignment.value.func.id in helper_names
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Name)
                }
                started_workers = {
                    call.func.value.id
                    for call in ast.walk(method)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "start"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in local_workers
                }
                retained_workers = {
                    assignment.value.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    and isinstance(assignment.value, ast.Name)
                    and assignment.value.id in local_workers
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                }
                unretained_workers = sorted(
                    started_workers - retained_workers
                )
                if unretained_workers:
                    errors.append(
                        f"{path}:{owner}.{method.name}: started background worker "
                        "is held only by a local variable and may be destroyed before "
                        "completion; retain it on the owner until a completion or "
                        "failure handler releases it: "
                        + ", ".join(unretained_workers)
                        + "."
                    )
                nested_operations = {
                    node.name: node
                    for node in method.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                for constructor_call in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in helper_names
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in nested_operations
                ):
                    operation_node = nested_operations[
                        constructor_call.args[0].id
                    ]
                    operation_argument_names = {
                        argument.arg
                        for argument in [
                            *operation_node.args.posonlyargs,
                            *operation_node.args.args,
                            *operation_node.args.kwonlyargs,
                        ]
                    }
                    if "progress_callback" not in operation_argument_names:
                        errors.append(
                            f"{path}:{owner}.{method.name}: nested worker "
                            "operation must accept the injected "
                            "`progress_callback` parameter."
                        )
                    direct_dialog_callbacks = sorted({
                        keyword.value.attr
                        for call in ast.walk(operation_node)
                        if isinstance(call, ast.Call)
                        for keyword in call.keywords
                        if keyword.arg
                        and keyword.arg.endswith("progress_callback")
                        and isinstance(keyword.value, ast.Attribute)
                        and isinstance(keyword.value.value, ast.Name)
                        and keyword.value.value.id == "self"
                    })
                    if direct_dialog_callbacks:
                        errors.append(
                            f"{path}:{owner}.{method.name}: nested worker "
                            "operation bypasses its injected progress callback "
                            "with dialog method(s): "
                            + ", ".join(direct_dialog_callbacks)
                            + "."
                        )
                    operation_parameters = [
                        argument.arg
                        for argument in [
                            *operation_node.args.posonlyargs,
                            *operation_node.args.args,
                            *operation_node.args.kwonlyargs,
                        ]
                        if argument.arg != "self"
                        and not argument.arg.endswith("progress_callback")
                    ]
                    supplied_operation_args = constructor_call.args[1:]
                    if len(supplied_operation_args) > len(
                        operation_parameters
                    ):
                        errors.append(
                            f"{path}:{owner}.{method.name}: worker constructor "
                            "passes positional value(s) not accepted by its "
                            "bound operation after progress callback injection."
                        )
            connection_sources = [
                expression_path(call.func.value)
                for call in owner_calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr == "connect"
                and isinstance(call.func.value, ast.Attribute)
            ]
            owner_method_names = {
                method.name
                for method in owner_node.body
                if isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            unresolved_private_signal_targets = sorted({
                argument.attr
                for call in owner_calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr == "connect"
                for argument in call.args[:1]
                if isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "self"
                and argument.attr.startswith("_")
                and argument.attr not in owner_method_names
            })
            if unresolved_private_signal_targets:
                errors.append(
                    f"{path}:{owner}: signal connections reference undefined "
                    "private handler(s): "
                    + ", ".join(unresolved_private_signal_targets)
                    + "."
                )
            has_done_callback = "add_done_callback" in owner_call_terminals
            has_completion_path = has_done_callback or any(
                value.rsplit(".", 1)[-1].casefold()
                in {"complete", "completed", "finished", "result", "succeeded"}
                for value in connection_sources
            )
            has_error_path = has_done_callback or any(
                value.rsplit(".", 1)[-1].casefold()
                in {"error", "exception", "failed", "failure"}
                for value in connection_sources
            )
            worker_release_required = any(
                "retained worker" in str(step).casefold()
                and (
                    "finished signal" in str(step).casefold()
                    or "finished-signal" in str(step).casefold()
                    or "release" in str(step).casefold()
                    or "disposal" in str(step).casefold()
                )
                for task in chunk.get("method_tasks") or []
                if isinstance(task, Mapping)
                for step in task.get("implementation_mechanics") or []
            )
            if worker_release_required:
                retained_worker_attributes = {
                    target.attr
                    for assignment in ast.walk(owner_node)
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
                worker_assignment_methods: dict[str, ast.AST] = {}
                for method in (
                    node
                    for node in owner_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    for assignment in ast.walk(method):
                        if not isinstance(
                            assignment,
                            (ast.Assign, ast.AnnAssign),
                        ) or not isinstance(assignment.value, ast.Call):
                            continue
                        targets = (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        for target in targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and target.attr in retained_worker_attributes
                            ):
                                worker_assignment_methods[target.attr] = method
                for worker_name, method in worker_assignment_methods.items():
                    assignment_lines = [
                        int(getattr(node, "lineno", 0))
                        for node in ast.walk(method)
                        if isinstance(node, (ast.Assign, ast.AnnAssign))
                        and any(
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == worker_name
                            for target in (
                                node.targets
                                if isinstance(node, ast.Assign)
                                else [node.target]
                            )
                        )
                    ]
                    first_assignment_line = min(
                        assignment_lines,
                        default=10**9,
                    )
                    has_active_worker_guard = any(
                        isinstance(node, ast.If)
                        and int(getattr(node, "lineno", 0))
                        < first_assignment_line
                        and any(
                            isinstance(comparison, ast.Compare)
                            and isinstance(
                                comparison.left,
                                ast.Attribute,
                            )
                            and isinstance(
                                comparison.left.value,
                                ast.Name,
                            )
                            and comparison.left.value.id == "self"
                            and comparison.left.attr == worker_name
                            and any(
                                isinstance(operator, ast.IsNot)
                                for operator in comparison.ops
                            )
                            and any(
                                isinstance(comparator, ast.Constant)
                                and comparator.value is None
                                for comparator in comparison.comparators
                            )
                            for comparison in ast.walk(node.test)
                        )
                        and any(
                            isinstance(statement, (ast.Return, ast.Raise))
                            for statement in ast.walk(node)
                        )
                        for node in ast.walk(method)
                    )
                    disables_trigger = any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "setEnabled"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value is False
                        and int(getattr(node, "lineno", 0))
                        < first_assignment_line
                        for node in ast.walk(method)
                    )
                    if not has_active_worker_guard and not disables_trigger:
                        errors.append(
                            f"{path}:{owner}.{method.name}: background worker "
                            f"`self.{worker_name}` can be overwritten by a repeated "
                            "start; guard an active worker or disable the initiating "
                            "control until terminal cleanup."
                        )
                    has_finished_cleanup = any(
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr == "connect"
                        and isinstance(call.func.value, ast.Attribute)
                        and call.func.value.attr == "finished"
                        and isinstance(call.func.value.value, ast.Attribute)
                        and isinstance(call.func.value.value.value, ast.Name)
                        and call.func.value.value.value.id == "self"
                        and call.func.value.value.attr == worker_name
                        for call in owner_calls
                    )
                    if not has_finished_cleanup:
                        errors.append(
                            f"{path}:{owner}.{method.name}: retained worker "
                            f"`self.{worker_name}` must connect its `finished` signal "
                            "to owner-side cleanup so every terminal path releases "
                            "the worker."
                        )
                terminal_handlers: dict[str, set[str]] = {}
                result_handler_names: set[str] = set()
                for call in owner_calls:
                    if (
                        not isinstance(call.func, ast.Attribute)
                        or call.func.attr != "connect"
                        or not call.args
                        or not isinstance(call.func.value, ast.Attribute)
                        or not isinstance(
                            call.func.value.value,
                            ast.Attribute,
                        )
                        or not isinstance(
                            call.func.value.value.value,
                            ast.Name,
                        )
                        or call.func.value.value.value.id != "self"
                        or not isinstance(call.args[0], ast.Attribute)
                        or not isinstance(call.args[0].value, ast.Name)
                        or call.args[0].value.id != "self"
                    ):
                        continue
                    signal_name = call.func.value.attr.casefold()
                    if signal_name not in {
                        "complete",
                        "completed",
                        "error",
                        "exception",
                        "failed",
                        "failure",
                        "finished",
                        "result",
                        "succeeded",
                    }:
                        continue
                    worker_name = call.func.value.value.attr
                    terminal_handlers.setdefault(
                        call.args[0].attr,
                        set(),
                    ).add(worker_name)
                    if signal_name in {
                        "complete",
                        "completed",
                        "finished",
                        "result",
                        "succeeded",
                    }:
                        result_handler_names.add(call.args[0].attr)
                methods_by_name = {
                    method.name: method
                    for method in owner_node.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                result_filter_attributes = {
                    str(attribute.get("name") or "")
                    for attribute in declaration_contract.get(
                        "attributes",
                    ) or []
                    if isinstance(attribute, Mapping)
                    and re.fullmatch(
                        r"include_[A-Za-z_][A-Za-z0-9_]*_checkbox",
                        str(attribute.get("name") or ""),
                    )
                }
                for handler_name in result_handler_names:
                    handler = methods_by_name.get(handler_name)
                    if handler is None:
                        continue
                    read_attributes = {
                        node.attr
                        for node in ast.walk(handler)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                    }
                    missing_filters = sorted(
                        result_filter_attributes - read_attributes
                    )
                    for filter_name in missing_filters:
                        errors.append(
                            f"{path}:{owner}.{handler_name}: approved result "
                            f"filter `{filter_name}` must be read and applied "
                            "inside the result consumer."
                        )
            if (
                execution_constraints.get("requires_completion_path")
                and not has_completion_path
            ):
                errors.append(
                    f"{path}:{owner}: background execution has no connected "
                    "completion/result path back to the UI owner."
                )
            if (
                execution_constraints.get("requires_error_path")
                and not has_error_path
            ):
                errors.append(
                    f"{path}:{owner}: background execution has no connected "
                    "error/failure path back to the UI owner."
                )
            if execution_constraints.get("forbid_handler_loops"):
                connected_handler_names = {
                    argument.attr
                    for call in owner_calls
                    if isinstance(call.func, ast.Attribute)
                    and call.func.attr == "connect"
                    for argument in call.args[:1]
                    if isinstance(argument, ast.Attribute)
                    and isinstance(argument.value, ast.Name)
                    and argument.value.id == "self"
                }
                blocking_loop_calls = {
                    "join", "processEvents", "sleep", "wait",
                }
                looping_handlers = sorted({
                    node.name
                    for node in ast.walk(owner_node)
                    if isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                    and node.name in connected_handler_names
                    and any(
                        isinstance(loop, ast.While)
                        or (
                            isinstance(loop, (ast.For, ast.AsyncFor))
                            and any(
                                isinstance(call, ast.Call)
                                and call_path(call).rsplit(".", 1)[-1]
                                in blocking_loop_calls
                                for call in ast.walk(loop)
                            )
                        )
                        for loop in ast.walk(node)
                    )
                })
                if looping_handlers:
                    errors.append(
                        f"{path}:{owner}: off-UI-thread contract forbids loops "
                        "inside connected UI handlers: "
                        + ", ".join(looping_handlers)
                        + "."
                    )
            background_method_names = {
                argument.attr
                for call in owner_calls
                if isinstance(call.func, ast.Name)
                and call.func.id in helper_names
                and call.args
                for argument in call.args[:1]
                if isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "self"
            }
            widget_names = {
                str(attribute.get("name") or "")
                for attribute in declaration_contract.get("attributes") or []
                if isinstance(attribute, Mapping)
                and str(attribute.get("name") or "")
                and (
                    str(attribute.get("type") or "").startswith("Q")
                    or str(attribute.get("name") or "").endswith(
                        (
                            "_btn",
                            "_button",
                            "_input",
                            "_label",
                            "_bar",
                            "_widget",
                            "_combo",
                            "_spinbox",
                        )
                    )
                )
            }
            methods_by_name = {
                node.name: node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for method_name in sorted(background_method_names):
                background_method = methods_by_name.get(method_name)
                if background_method is None:
                    continue
                ui_mutations = sorted({
                    expression_path(call.func)
                    for call in ast.walk(background_method)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and expression_path(call.func).split(".")[:2]
                    in [["self", widget_name] for widget_name in widget_names]
                })
                if ui_mutations:
                    errors.append(
                        f"{path}:{owner}.{method_name}: background worker "
                        "operation mutates UI-owned widgets outside the UI "
                        "thread: "
                        + ", ".join(ui_mutations)
                        + ". Return data and update widgets only in connected "
                        "completion/error handlers."
                    )
                swallowing_handlers = [
                    handler
                    for try_node in ast.walk(background_method)
                    if isinstance(try_node, ast.Try)
                    for handler in try_node.handlers
                    if not any(
                        isinstance(child, ast.Raise)
                        for child in ast.walk(handler)
                    )
                ]
                if swallowing_handlers:
                    errors.append(
                        f"{path}:{owner}.{method_name}: background worker "
                        "operation catches an exception without re-raising it; "
                        "the worker error boundary must receive failures."
                    )
