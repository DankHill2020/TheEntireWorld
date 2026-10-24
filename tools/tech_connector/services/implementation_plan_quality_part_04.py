"""Dependency-ordered implementation-plan quality functions."""
from __future__ import annotations

import ast
import builtins
import copy
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

from tech_connector.services.implementation_plan_quality_part_02 import (
    _call_names,
    _definition_nodes,
    _method_map,
)

from tech_connector.services.implementation_plan_quality_part_03 import (
    _boundary_trim_requirement_gaps,
    _discarded_pure_transform_gaps,
    _final_value_guard_gaps,
    _regex_requirement_gaps,
    _verification_proof_gaps,
)


def _explicit_serialization_contract_gaps(
    implementation_plan: Mapping[str, Any],
    trees: Mapping[str, ast.Module],
) -> list[str]:
    """Catch direct contradictions of approved JSON and falsey-value contracts."""

    requirements_by_path: dict[str, list[str]] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or not chunk.get("path"):
            continue
        path = str(Path(str(chunk["path"])).resolve())
        requirements_by_path.setdefault(path, []).extend(
            str(row.get("text") or row.get("requirement") or "")
            if isinstance(row, Mapping)
            else str(row)
            for row in chunk.get("requirements") or []
        )

    errors: list[str] = []
    for path, tree in trees.items():
        requirements = " ".join(requirements_by_path.get(path) or [])
        if not requirements:
            continue
        preserves_falsey = bool(re.search(
            r"\b(?:preserv\w*|accept\w*|allow\w*|support\w*)"
            r"[^.;]{0,70}\b(?:falsey|falsy)\b",
            requirements,
            flags=re.IGNORECASE,
        ))
        falsey_names = {
            match.group(1).removesuffix("s").casefold()
            for match in re.finditer(
                r"\b(?:falsey|falsy)\s+(?:hashable\s+)?([A-Za-z_]\w*)",
                requirements,
                flags=re.IGNORECASE,
            )
        } if preserves_falsey else set()
        canonical_json = bool(
            re.search(r"\bcanonical\b[^.;]{0,100}\bJSON\b", requirements, re.I)
            and re.search(r"\bcompact\s+separators\b", requirements, re.I)
        )
        both_paths_validate = bool(re.search(
            r"\bboth\s+(?:paths|directions)\s+must\s+validate\b",
            requirements,
            re.I,
        ))
        strict_integer_version = bool(re.search(
            r"\bversion\b[^.;]{0,90}\binteger\s+(?:other\s+than|excluding)\s+bool\b",
            requirements,
            re.I,
        ))
        positive_version = bool(re.search(
            r"\bversion\b[^.;]{0,90}\bat\s+least\s+1\b",
            requirements,
            re.I,
        ))
        local_validators = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith(("validate_", "_validate_"))
            and any(isinstance(child, ast.Raise) for child in ast.walk(node))
        }
        functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append((node.name, node))
            elif isinstance(node, ast.ClassDef):
                functions.extend(
                    (f"{node.name}.{member.name}", member)
                    for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        for owner, function in functions:
            calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
            dumps_json = any(
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "json"
                and call.func.attr == "dumps"
                for call in calls
            )
            loads_json = any(
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "json"
                and call.func.attr == "loads"
                for call in calls
            )
            calls_local_validator = any(
                isinstance(call.func, ast.Name)
                and call.func.id in local_validators
                for call in calls
            )
            def raises_for_field(field: str) -> bool:
                return any(
                    any(isinstance(child, ast.Raise) for statement in guard.body for child in ast.walk(statement))
                    and any(
                        isinstance(child, ast.Name) and child.id == field
                        or isinstance(child, ast.Attribute) and child.attr == field
                        or isinstance(child, ast.Constant) and child.value == field
                        for child in ast.walk(guard.test)
                    )
                    for guard in ast.walk(function)
                    if isinstance(guard, ast.If)
                )
            if both_paths_validate and dumps_json and not calls_local_validator and not (
                raises_for_field("version") and raises_for_field("kind")
            ):
                errors.append(
                    f"{path}:{owner}: approved validation on both JSON paths "
                    "requires explicit rejection guards for version and kind "
                    "values before json.dumps; an unrelated input/key guard "
                    "does not validate those fields."
                )
            if both_paths_validate and loads_json and not calls_local_validator and not (
                raises_for_field("version") and raises_for_field("kind")
            ):
                errors.append(
                    f"{path}:{owner}: approved validation on both JSON paths "
                    "requires explicit rejection guards for version and kind "
                    "values after json.loads and before returning the decoded "
                    "object; constructing the object alone does not validate "
                    "those fields."
                )
            if (loads_json or dumps_json) and not calls_local_validator and (strict_integer_version or positive_version):
                executable = ast.unparse(ast.Module(body=[
                    statement for statement in function.body
                    if not (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Constant)
                        and isinstance(statement.value.value, str)
                    )
                ], type_ignores=[]))
                if re.search(r"\bversion\b", executable):
                    version_ref = (
                        r"(?:[A-Za-z_]\w*\.)?version"
                        r"|[A-Za-z_]\w*\[\s*['\"]version['\"]\s*\]"
                    )
                    version_ref = f"(?:{version_ref})"
                    if strict_integer_version and not (
                        re.search(rf"\btype\(\s*{version_ref}\s*\)\s+is(?:\s+not)?\s+int\b", executable)
                        or re.search(rf"\bisinstance\(\s*{version_ref}\s*,\s*bool\)", executable)
                    ):
                        errors.append(
                            f"{path}:{owner}: approved integer version excludes bool; "
                            "isinstance(value, int) alone accepts True and False."
                        )
                    if positive_version and not re.search(
                        rf"\b{version_ref}\s*(?:<\s*1|<=\s*0|>=\s*1|>\s*0)\b",
                        executable,
                    ):
                        errors.append(
                            f"{path}:{owner}: approved version must be at least 1; "
                            "the JSON path has no numeric lower-bound check."
                        )
            if falsey_names:
                for guard in (node for node in ast.walk(function) if isinstance(node, ast.If)):
                    rejects = any(
                        isinstance(child, ast.Raise)
                        for statement in guard.body
                        for child in ast.walk(statement)
                    )
                    if not rejects:
                        continue
                    tested_name = ""
                    if isinstance(guard.test, ast.UnaryOp) and isinstance(guard.test.op, ast.Not):
                        if isinstance(guard.test.operand, ast.Name):
                            tested_name = guard.test.operand.id
                    elif isinstance(guard.test, ast.Compare) and len(guard.test.ops) == 1:
                        if isinstance(guard.test.ops[0], (ast.Is, ast.Eq)):
                            pair = [guard.test.left, *guard.test.comparators]
                            if any(isinstance(value, ast.Constant) and value.value is None for value in pair):
                                tested_name = next(
                                    (value.id for value in pair if isinstance(value, ast.Name)), ""
                                )
                    if tested_name.casefold() in falsey_names:
                        errors.append(
                            f"{path}:{owner}: approved falsey {tested_name} values "
                            "must remain valid; a truthiness/None raising guard "
                            "conflates a present falsey value with a missing one. "
                            "Check key presence separately."
                        )
                        break
            if canonical_json:
                for call in (
                    node for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "json"
                    and node.func.attr == "dumps"
                ):
                    keywords = {item.arg: item.value for item in call.keywords if item.arg}
                    sorted_keys = isinstance(keywords.get("sort_keys"), ast.Constant) and keywords["sort_keys"].value is True
                    separators = keywords.get("separators")
                    compact = (
                        isinstance(separators, ast.Tuple)
                        and len(separators.elts) == 2
                        and all(isinstance(item, ast.Constant) for item in separators.elts)
                        and [item.value for item in separators.elts] == [",", ":"]
                    )
                    if not sorted_keys or not compact:
                        errors.append(
                            f"{path}:{owner}: approved canonical JSON bytes require "
                            "json.dumps with sort_keys=True and compact "
                            "separators=(',', ':')."
                        )
                        break
    return errors


def _explicit_tuple_dict_result_gaps(
    implementation_plan: Mapping[str, Any],
    trees: Mapping[str, ast.Module],
) -> list[str]:
    """Catch a proven name-only flow into an approved dict-row result."""

    chunks = [
        chunk for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
    ]
    function_chunks: dict[str, list[Mapping[str, Any]]] = {}
    for chunk in chunks:
        if str(chunk.get("kind") or "") == "function":
            function_chunks.setdefault(str(chunk.get("owner") or ""), []).append(chunk)
    name_result_owners = {
        owner
        for owner, matches in function_chunks.items()
        if owner and len(matches) == 1
        and any(
            re.search(
                r"\breturn\s+(?:a\s+)?tuple\s+of\b[^.;]*\bnames\b",
                str(row.get("text") or ""),
                re.I,
            )
            for row in matches[0].get("requirements") or []
            if isinstance(row, Mapping)
        )
    }
    def dict_result_keys(owner: str) -> set[str]:
        """Read an exact dict-row key contract from one approved owner."""

        matches = function_chunks.get(owner) or []
        if len(matches) != 1:
            return set()
        for row in matches[0].get("requirements") or []:
            if not isinstance(row, Mapping):
                continue
            contract = re.search(
                r"\breturn\s+a\s+tuple\s+of\s+dicts?\s+with\s+exactly\s+"
                r"(.+?)\s+keys\b",
                str(row.get("text") or ""),
                re.I,
            )
            if contract:
                return {
                    key for key in re.findall(r"[A-Za-z_]\w*", contract.group(1))
                    if key != "and"
                }
        return set()

    dict_result_owners = {
        owner: dict_result_keys(owner)
        for owner in function_chunks
        if dict_result_keys(owner)
    }
    gaps: list[str] = []
    for chunk in chunks:
        if str(chunk.get("kind") or "") != "function":
            continue
        if not any(
            re.search(
                r"\breturn\s+a\s+tuple\s+of\s+dicts?\s+with\s+exactly\b",
                str(row.get("text") or ""),
                re.I,
            )
            for row in chunk.get("requirements") or []
            if isinstance(row, Mapping)
        ):
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        tree = trees.get(path)
        owner = str(chunk.get("owner") or "")
        expected_dict_keys = dict_result_owners.get(owner, set())
        if tree is None or not owner:
            continue
        function = next(
            (node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == owner),
            None,
        )
        if function is None:
            continue
        class OwnerReturns(ast.NodeVisitor):
            """Visit returns in this owner, excluding nested callable bodies."""

            def __init__(self) -> None:
                self.values: list[ast.expr | None] = []
                self.assignments: list[ast.Assign | ast.AnnAssign] = []
                self.loops: list[ast.For | ast.AsyncFor] = []
                self.calls: list[ast.Call] = []

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node is function:
                    self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                if node is function:
                    self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                return

            def visit_Return(self, node: ast.Return) -> None:
                self.values.append(node.value)

            def visit_Assign(self, node: ast.Assign) -> None:
                self.assignments.append(node)
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                self.calls.append(node)
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                self.assignments.append(node)
                self.generic_visit(node)

            def visit_For(self, node: ast.For) -> None:
                self.loops.append(node)
                self.generic_visit(node)

            def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
                self.loops.append(node)
                self.generic_visit(node)

        owner_returns = OwnerReturns()
        owner_returns.visit(function)
        returned_collectors: set[str] = set()
        for value in owner_returns.values:
            if isinstance(value, ast.Name):
                returned_collectors.add(value.id)
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "tuple"
                and len(value.args) == 1
                and isinstance(value.args[0], ast.Name)
            ):
                returned_collectors.add(value.args[0].id)
        if expected_dict_keys:
            for call in owner_returns.calls:
                if not (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in returned_collectors
                    and call.func.attr == "append"
                    and len(call.args) == 1
                    and isinstance(call.args[0], ast.Dict)
                ):
                    continue
                keys = call.args[0].keys
                if not all(
                    isinstance(key, ast.Constant) and isinstance(key.value, str)
                    for key in keys
                ):
                    continue
                actual_keys = {key.value for key in keys}
                if actual_keys != expected_dict_keys or len(keys) != len(expected_dict_keys):
                    gaps.append(
                        f"{path}:{owner}: appended dict-row keys "
                        f"{sorted(actual_keys)} differ from approved exact keys "
                        f"{sorted(expected_dict_keys)}."
                    )
                    break
        assignment_counts: dict[str, int] = {}
        for assignment in owner_returns.assignments:
            for target in (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            ):
                if isinstance(target, ast.Name):
                    assignment_counts[target.id] = (
                        assignment_counts.get(target.id, 0) + 1
                    )
        scalar_helper_results = {
            target.id: assignment.value.func.id
            for assignment in owner_returns.assignments
            if isinstance(assignment.value, ast.Call)
            and isinstance(assignment.value.func, ast.Name)
            and assignment.value.func.id in name_result_owners
            for target in (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            if isinstance(target, ast.Name)
            and assignment_counts.get(target.id) == 1
        }
        requirement_text = " ".join(
            str(row.get("text") or "")
            for row in chunk.get("requirements") or []
            if isinstance(row, Mapping)
        )
        path_name_fields = set(re.findall(r"<([A-Za-z_]\w*)>", requirement_text))
        parameters = {
            argument.arg
            for argument in (*function.args.posonlyargs, *function.args.args,
                             *function.args.kwonlyargs)
        }
        raw_entry_vars: set[str] = set()
        for assignment in owner_returns.assignments:
            value = assignment.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "next"
                and value.args
                and isinstance(value.args[0], ast.GeneratorExp)
            ):
                continue
            generator = value.args[0]
            if not (
                isinstance(generator.elt, ast.Name)
                and len(generator.generators) == 1
                and isinstance(generator.generators[0].target, ast.Name)
                and generator.elt.id == generator.generators[0].target.id
                and isinstance(generator.generators[0].iter, ast.Name)
                and generator.generators[0].iter.id in parameters
            ):
                continue
            for target in (
                assignment.targets if isinstance(assignment, ast.Assign)
                else [assignment.target]
            ):
                if isinstance(target, ast.Name) and assignment_counts.get(target.id) == 1:
                    raw_entry_vars.add(target.id)
        for loop in owner_returns.loops:
            if not isinstance(loop.target, ast.Name):
                continue
            raw_input_loop = (
                isinstance(loop.iter, ast.Name)
                and loop.iter.id in parameters
                and bool(scalar_helper_results)
            )
            helper_name = (
                loop.iter.func.id
                if isinstance(loop.iter, ast.Call)
                and isinstance(loop.iter.func, ast.Name)
                and loop.iter.func.id in name_result_owners
                else ""
            )
            if (
                not helper_name
                and isinstance(loop.iter, ast.Name)
                and loop.iter.id in scalar_helper_results
            ):
                helper_name = scalar_helper_results[loop.iter.id]
            if not helper_name and not raw_input_loop:
                continue
            if path_name_fields and (raw_entry_vars or raw_input_loop):
                for statement in loop.body:
                    for child in ast.walk(statement):
                        if not isinstance(child, ast.Dict):
                            continue
                        for key, value in zip(child.keys, child.values):
                            if (
                                isinstance(key, ast.Constant)
                                and isinstance(key.value, str)
                                and key.value in path_name_fields
                                and isinstance(value, ast.Name)
                                and (
                                    value.id in raw_entry_vars
                                    or (raw_input_loop and value.id == loop.target.id)
                                )
                            ):
                                selected_name = (
                                    loop.target.id if helper_name else
                                    next(iter(scalar_helper_results))
                                )
                                gaps.append(
                                    f"{path}:{owner}: a selection helper returns name strings, "
                                    f"but dict field {key.value!r} stores raw input entry "
                                    f"{value.id}; use a name from {selected_name} "
                                    "for the row and derived output path."
                                )
                                break
            if not helper_name:
                continue
            if any(
                isinstance(child, ast.Subscript)
                and isinstance(child.value, ast.Name)
                and child.value.id == loop.target.id
                and isinstance(child.slice, ast.Constant)
                and isinstance(child.slice.value, str)
                for statement in loop.body
                for child in ast.walk(statement)
            ):
                gaps.append(
                    f"{path}:{owner}: {helper_name} returns name strings, but "
                    f"{loop.target.id} is indexed as a mapping inside the result "
                    "loop; use the scalar name directly when constructing dict rows."
                )
                break
        for value in owner_returns.values:
            if value is None:
                continue
            operand: ast.expr = value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "tuple"
            ):
                if len(value.args) != 1 or value.keywords:
                    continue
                operand = value.args[0]
            helper_name = ""
            source_description = ""
            if isinstance(operand, ast.Call) and isinstance(operand.func, ast.Name):
                helper_name = operand.func.id
                source_description = f"returning {helper_name}(...) directly"
            elif isinstance(operand, ast.Name):
                helper_calls = [
                    assignment.value
                    for assignment in owner_returns.assignments
                    if isinstance(assignment.value, ast.Call)
                    and any(
                        isinstance(target, ast.Name) and target.id == operand.id
                        for target in (
                            assignment.targets if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                    )
                ]
                if len(helper_calls) == 1 and isinstance(helper_calls[0].func, ast.Name):
                    helper_name = helper_calls[0].func.id
                    source_description = (
                        f"return tuple({operand.id})" if operand is not value
                        else f"return {operand.id}"
                    )
            if helper_name in name_result_owners:
                gaps.append(
                    f"{path}:{owner}: approved tuple-of-dicts result is not built; "
                    f"{source_description} forwards name-only output from "
                    f"{helper_name} without constructing dict rows."
                )
                break
            helper_dict_keys = dict_result_owners.get(helper_name, set())
            if (
                helper_name != owner
                and helper_dict_keys
                and expected_dict_keys
                and helper_dict_keys != expected_dict_keys
            ):
                gaps.append(
                    f"{path}:{owner}: approved dict-row keys "
                    f"{sorted(expected_dict_keys)} differ from forwarded "
                    f"{helper_name} rows {sorted(helper_dict_keys)}; build "
                    "the requested result rows instead of returning the "
                    "helper output directly."
                )
                break
    return gaps


def _explicit_boundary_contract_gaps(
    implementation_plan: Mapping[str, Any],
    trees: Mapping[str, ast.Module],
) -> list[str]:
    """Catch direct empty-selection and blank-path contradictions in owner code."""

    gaps: list[str] = []
    none_all_helpers = {
        str(chunk.get("owner") or "")
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and chunk.get("kind") == "function"
        and re.search(
            r"(?:selected_names\s*=\s*none|none selection)\s+"
            r"(?:exports?|includes?|returns?)\s+all",
            " ".join(
                str(row.get("text") or row.get("requirement") or "")
                if isinstance(row, Mapping) else str(row)
                for row in chunk.get("requirements") or []
            ).casefold(),
        )
    }
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or chunk.get("kind") != "function":
            continue
        owner = str(chunk.get("owner") or "")
        path = str(Path(str(chunk.get("path") or "")).resolve())
        tree = trees.get(path)
        if tree is None or not owner:
            continue
        function = next(
            (node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == owner),
            None,
        )
        if function is None:
            continue
        requirements = " ".join(
            str(row.get("text") or row.get("requirement") or "")
            if isinstance(row, Mapping) else str(row)
            for row in chunk.get("requirements") or []
        ).casefold()
        parameters = {
            arg.arg for arg in [
                *function.args.posonlyargs, *function.args.args,
                *function.args.kwonlyargs,
            ]
        }
        forwards_to_default_all_helper = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in none_all_helpers - {owner}
            and any(
                isinstance(read, ast.Name)
                and isinstance(read.ctx, ast.Load)
                and read.id == "selected_names"
                for argument in [*call.args, *(keyword.value for keyword in call.keywords)]
                for read in ast.walk(argument)
            )
            for call in ast.walk(function)
        )
        if (
            "selected_names" in parameters
            and (
                forwards_to_default_all_helper
                or (
                    re.search(
                        r"(?:selected_names\s*=\s*none|none selection)\s+"
                        r"(?:exports?|includes?|returns?)\s+all", requirements,
                    )
                    and re.search(
                        r"(?:explicit\s+)?empty selection\s+"
                        r"(?:exports?\s+nothing|returns?\s+(?:an\s+)?empty)",
                        requirements,
                    )
                )
            )
        ):
            for statement in function.body:
                if not (
                    isinstance(statement, ast.If)
                    and isinstance(statement.test, ast.Compare)
                    and isinstance(statement.test.left, ast.Name)
                    and statement.test.left.id == "selected_names"
                    and any(isinstance(op, ast.Is) for op in statement.test.ops)
                    and any(isinstance(value, ast.Constant) and value.value is None
                            for value in statement.test.comparators)
                    and len(statement.body) == 1
                    and isinstance(statement.body[0], ast.Assign)
                    and len(statement.body[0].targets) == 1
                    and isinstance(statement.body[0].targets[0], ast.Name)
                    and statement.body[0].targets[0].id == "selected_names"
                    and (
                        isinstance(statement.body[0].value, (ast.List, ast.Set, ast.Tuple))
                        and not statement.body[0].value.elts
                        or isinstance(statement.body[0].value, ast.Call)
                        and isinstance(statement.body[0].value.func, ast.Name)
                        and statement.body[0].value.func.id in {"list", "set", "tuple"}
                        and not statement.body[0].value.args
                        and not statement.body[0].value.keywords
                    )
                ):
                    continue
                gaps.append(
                    f"{path}:{owner}: selected_names=None is collapsed to "
                    "an explicit empty selection, but the approved contract "
                    "requires None to include all and [] to include none. "
                    "Preserve a distinct all-mode sentinel through filtering."
                )
                break
        if (
            "selected_names" in parameters
            and re.search(r"\b(?:empty selection|selected names?|selected_names)\b", requirements)
        ):
            parents = {
                id(child): node
                for node in ast.walk(function)
                for child in ast.iter_child_nodes(node)
            }
            selection_reads = [
                node for node in ast.walk(function)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id == "selected_names"
            ]
            default_checks_only = not selection_reads or all(
                isinstance(parents.get(id(node)), ast.Compare)
                and any(
                    isinstance(value, ast.Constant) and value.value is None
                    for value in parents[id(node)].comparators
                )
                for node in selection_reads
            )
            if default_checks_only:
                gaps.append(
                    f"{path}:{owner}: selected_names is only checked for its "
                    "default or never read; the approved explicit selection "
                    "cannot affect the result. Use requested names to filter "
                    "enabled names in project order and reject unknown or "
                    "disabled names where required."
                )
            # Validation of requested names is not enough: the final ordered
            # collector must also be filtered. A frequent local-model failure
            # validates a requested set, then appends every enabled item in a
            # later loop and returns that unfiltered collector.
            selection_derived = {"selected_names"}
            assignments = [
                node for node in ast.walk(function)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
            ]
            for _ in range(len(assignments)):
                changed = False
                for assignment in assignments:
                    value = assignment.value
                    if value is None or not any(
                        isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Load)
                        and node.id in selection_derived
                        for node in ast.walk(value)
                    ):
                        continue
                    targets = (
                        assignment.targets if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in selection_derived:
                            selection_derived.add(target.id)
                            changed = True
                if not changed:
                    break
            returned_collectors = {
                value.args[0].id
                for node in function.body
                if isinstance(node, ast.Return)
                for value in [node.value]
                if isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in {"tuple", "list"}
                and len(value.args) == 1
                and isinstance(value.args[0], ast.Name)
            }
            for selection_if in (
                node for node in ast.walk(function)
                if isinstance(node, ast.If)
            ):
                appends_result = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in returned_collectors
                    for statement in selection_if.body
                    for node in ast.walk(statement)
                )
                inverted_membership = any(
                    isinstance(node, ast.Compare)
                    and any(isinstance(op, ast.NotIn) for op in node.ops)
                    and any(
                        isinstance(comparator, ast.Name)
                        and comparator.id in selection_derived
                        for comparator in node.comparators
                    )
                    for node in ast.walk(selection_if.test)
                )
                if appends_result and inverted_membership:
                    gaps.append(
                        f"{path}:{owner}: inverted explicit selection filter "
                        "appends a name when it is not in requested names. "
                        "For a nonempty requested set, append matching enabled "
                        "names in project order; None includes all and an "
                        "explicit empty selection includes none."
                    )
                    break
            for loop in (
                node for node in function.body
                if isinstance(node, (ast.For, ast.AsyncFor))
            ):
                appended = {
                    node.func.value.id
                    for node in ast.walk(loop)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                }
                if not appended.intersection(returned_collectors):
                    continue
                if any(
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id in selection_derived
                    for node in ast.walk(loop)
                ):
                    continue
                later = function.body[function.body.index(loop) + 1:]
                if any(
                    isinstance(node, (ast.Assign, ast.AnnAssign))
                    and any(
                        isinstance(target, ast.Name)
                        and target.id in returned_collectors
                        for target in (
                            node.targets if isinstance(node, ast.Assign)
                            else [node.target]
                        )
                    )
                    and node.value is not None
                    and any(
                        isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Load)
                        and child.id in selection_derived
                        for child in ast.walk(node.value)
                    )
                    for statement in later
                    for node in ast.walk(statement)
                ):
                    continue
                gaps.append(
                    f"{path}:{owner}: explicit selected_names is validated "
                    "but does not filter the returned collection. Filter each "
                    "appended enabled item against the requested names, while "
                    "preserving project order; an empty selection returns ()."
                )
                break
        if (
            "selected_names" in parameters
            and re.search(
                r"\bempty selection\b[^.;]*\b(?:nothing|empty)\b",
                requirements,
            )
        ):
            derived = {"selected_names"}
            assignments = [
                node for node in ast.walk(function)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
            ]
            for _ in range(len(assignments)):
                changed = False
                for assignment in assignments:
                    value = assignment.value
                    if value is None or not any(
                        isinstance(node, ast.Name) and node.id in derived
                        for node in ast.walk(value)
                    ):
                        continue
                    targets = (
                        assignment.targets if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in derived:
                            derived.add(target.id)
                            changed = True
                if not changed:
                    break
            returns_empty_before_raise = any(
                isinstance(node, ast.If)
                and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)
                and isinstance(node.test.operand, ast.Name)
                and node.test.operand.id in derived
                and any(
                    isinstance(child, ast.Return)
                    and isinstance(child.value, (ast.Tuple, ast.List, ast.Set))
                    and not child.value.elts
                    for statement in node.body
                    for child in ast.walk(statement)
                )
                for node in ast.walk(function)
            )
            raises_on_empty_filtered_result = any(
                isinstance(node, ast.If)
                and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)
                and isinstance(node.test.operand, ast.Name)
                and node.test.operand.id in derived
                and any(isinstance(child, ast.Raise)
                        for statement in node.body
                        for child in ast.walk(statement))
                for node in ast.walk(function)
            )
            if raises_on_empty_filtered_result and not returns_empty_before_raise:
                gaps.append(
                    f"{path}:{owner}: explicit empty selected_names must return "
                    "an empty result, but a selection-derived empty value raises. "
                    "After normalizing selected_names to a set, return () only "
                    "when that set is empty. For a nonempty set, reject keys "
                    "absent from enabled names with ValueError, then filter in "
                    "project order. Never turn unknown/disabled selection into ()."
                )
        if (
            "selected_names" in parameters
            and re.search(
                r"\bunknown or disabled (?:selected names?|selections?)\b"
                r"[^.;]*\b(?:raises?|with)\s+valueerror\b",
                requirements,
            )
        ):
            selection_derived = {"selected_names"}
            for _ in range(len(function.body)):
                changed = False
                for assignment in (
                    node for node in ast.walk(function)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    and node.value is not None
                    and any(
                        isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Load)
                        and child.id in selection_derived
                        for child in ast.walk(node.value)
                    )
                ):
                    targets = (
                        assignment.targets if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in selection_derived:
                            selection_derived.add(target.id)
                            changed = True
                if not changed:
                    break
            parent_nodes = {
                id(child): node
                for node in ast.walk(function)
                for child in ast.iter_child_nodes(node)
            }
            has_selection_rejection = False
            for rejection in (
                node for node in ast.walk(function)
                if isinstance(node, ast.Raise)
            ):
                ancestor = parent_nodes.get(id(rejection))
                while ancestor is not None and ancestor is not function:
                    if (
                        isinstance(ancestor, ast.If)
                        and any(
                            isinstance(read, ast.Name)
                            and read.id in selection_derived
                            for read in ast.walk(ancestor.test)
                        )
                    ):
                        has_selection_rejection = True
                        break
                    ancestor = parent_nodes.get(id(ancestor))
                if has_selection_rejection:
                    break
            if not has_selection_rejection:
                gaps.append(
                    f"{path}:{owner}: approved unknown or disabled "
                    "selected_names must raise ValueError; no rejection is "
                    "guarded by the requested selection. "
                    "Compare nonempty requested keys with enabled keys before "
                    "filtering and reject any missing key."
                )
        if (
            re.search(r"reject blank names?", requirements)
            and "backslash" in requirements
            and "valueerror" in requirements
        ):
            for guard in (
                node for node in ast.walk(function)
                if isinstance(node, ast.If)
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Continue)
            ):
                literals = {
                    node.value for node in ast.walk(guard.test)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                }
                if {"/", "\\"} <= literals:
                    gaps.append(
                        f"{path}:{owner}: unsafe or blank names are silently "
                        "skipped; the approved contract requires ValueError."
                    )
                    break
        for field in sorted(set(re.findall(
            r"\bblank\s+([a-z_]\w*)\b", requirements,
        )) & parameters):
            path_conversions = [
                node for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and (
                    isinstance(node.func, ast.Name) and node.func.id == "Path"
                    or isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "pathlib"
                    and node.func.attr == "Path"
                )
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == field
            ]
            def stringified_field_strip(node: ast.AST) -> bool:
                """Recognize str(field).strip(), which also accepts Path inputs."""

                return (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "strip"
                    and isinstance(node.func.value, ast.Call)
                    and isinstance(node.func.value.func, ast.Name)
                    and node.func.value.func.id == "str"
                    and len(node.func.value.args) == 1
                    and isinstance(node.func.value.args[0], ast.Name)
                    and node.func.value.args[0].id == field
                )

            def stringified_blank_test(node: ast.AST) -> bool:
                """Accept a blank check alone or as one disjunctive rejection."""

                return (
                    isinstance(node, ast.UnaryOp)
                    and isinstance(node.op, ast.Not)
                    and stringified_field_strip(node.operand)
                ) or (
                    isinstance(node, ast.BoolOp)
                    and isinstance(node.op, ast.Or)
                    and any(stringified_blank_test(value) for value in node.values)
                )

            stringified_guard = any(
                isinstance(node, ast.If)
                and stringified_blank_test(node.test)
                and any(
                    isinstance(child, ast.Raise)
                    for statement in node.body for child in ast.walk(statement)
                )
                and any(node.lineno < conversion.lineno for conversion in path_conversions)
                for node in ast.walk(function)
            )
            strips_field = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "strip"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == field
                for node in ast.walk(function)
            )
            if path_conversions and not strips_field and not stringified_guard:
                gaps.append(
                    f"{path}:{owner}: approved blank `{field}` rejection is "
                    f"missing before Path({field}); use `isinstance({field}, str) "
                    f"and not {field}.strip()` so whitespace-only strings raise "
                    "ValueError."
                )
            elif path_conversions and (strips_field or stringified_guard) and re.search(
                rf"\b{re.escape(field)}\b[^.;]{{0,90}}\b(?:str|pathlib\.Path|Path)\b",
                requirements,
                re.I,
            ):
                guarded_strip = any(
                    isinstance(node, ast.If)
                    and any(
                        isinstance(part, ast.Call)
                        and isinstance(part.func, ast.Name)
                        and part.func.id == "isinstance"
                        and len(part.args) >= 2
                        and isinstance(part.args[0], ast.Name)
                        and part.args[0].id == field
                        and isinstance(part.args[1], ast.Name)
                        and part.args[1].id == "str"
                        for part in ast.walk(node.test)
                    )
                    and any(
                        isinstance(part, ast.Call)
                        and isinstance(part.func, ast.Attribute)
                        and part.func.attr == "strip"
                        and isinstance(part.func.value, ast.Name)
                        and part.func.value.id == field
                        for part in ast.walk(node.test)
                    )
                    for node in ast.walk(function)
                )
                if not guarded_strip and not stringified_guard:
                    gaps.append(
                        f"{path}:{owner}: `{field}.strip()` is unguarded even "
                        "though pathlib.Path is an approved input. Restrict the "
                        f"blank-string check to `isinstance({field}, str) and "
                        f"not {field}.strip()`; Path inputs must remain valid."
                    )
    return gaps


def _explicit_function_completion_gaps(
    implementation_plan: Mapping[str, Any],
    trees: Mapping[str, ast.Module],
) -> list[str]:
    """Reject missing outer returns and explicitly required sibling calls."""

    callable_names = {
        node.name
        for tree in trees.values()
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    gaps: list[str] = []
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or chunk.get("kind") != "function":
            continue
        owner = str(chunk.get("owner") or "")
        path = str(Path(str(chunk.get("path") or "")).resolve())
        tree = trees.get(path)
        if tree is None or not owner:
            continue
        function = next(
            (node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == owner),
            None,
        )
        if function is None:
            continue
        requirements = " ".join(
            str(row.get("text") or row.get("requirement") or "")
            if isinstance(row, Mapping) else str(row)
            for row in chunk.get("requirements") or []
        )
        if re.search(r"\breturns? a tuple\b", requirements, re.IGNORECASE):
            class OuterReturns(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.values: list[ast.expr | None] = []

                def visit_Return(self, node: ast.Return) -> None:
                    self.values.append(node.value)

                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    return

                def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                    return

                def visit_ClassDef(self, node: ast.ClassDef) -> None:
                    return

            returns = OuterReturns()
            for statement in function.body:
                returns.visit(statement)
            if not any(
                value is not None
                and not (isinstance(value, ast.Constant) and value.value is None)
                for value in returns.values
            ):
                gaps.append(
                    f"{path}:{owner}: approved tuple result has no value-return "
                    "in the public owner; a nested helper return or yield is not "
                    "the callable's result."
                )
        required_calls = {
            name for name in re.findall(
                r"\busing\s+([A-Za-z_]\w*)\b", requirements, re.IGNORECASE,
            )
            if name in callable_names and name != owner
        }
        for dependency in sorted(required_calls):
            aliases = {dependency}
            for statement in [*tree.body, *ast.walk(function)]:
                if isinstance(statement, ast.ImportFrom):
                    aliases.update(
                        alias.asname or alias.name
                        for alias in statement.names if alias.name == dependency
                    )
            nested = {
                child.name: child
                for child in ast.walk(function)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child is not function
            }

            class CallsOutsideNestedDefinitions(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.calls: list[ast.Call] = []
                    self.loaded_names: set[str] = set()

                def visit_Call(self, call: ast.Call) -> None:
                    self.calls.append(call)
                    self.generic_visit(call)

                def visit_Name(self, name: ast.Name) -> None:
                    if isinstance(name.ctx, ast.Load):
                        self.loaded_names.add(name.id)

                def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
                    return

                def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
                    return

                def visit_ClassDef(self, child: ast.ClassDef) -> None:
                    return

            reachable_calls: list[ast.Call] = []
            pending = [function]
            visited: set[int] = set()
            while pending:
                current = pending.pop()
                if id(current) in visited:
                    continue
                visited.add(id(current))
                visitor = CallsOutsideNestedDefinitions()
                for statement in current.body:
                    visitor.visit(statement)
                reachable_calls.extend(visitor.calls)
                # A callback may be passed to another callable rather than
                # invoked syntactically here. Follow loaded helper names to
                # avoid rejecting that valid delegation shape.
                pending.extend(
                    nested[name]
                    for name in visitor.loaded_names & nested.keys()
                )
            if not any(
                isinstance(call.func, ast.Name) and call.func.id in aliases
                or isinstance(call.func, ast.Attribute)
                and call.func.attr == dependency
                for call in reachable_calls
            ):
                gaps.append(
                    f"{path}:{owner}: approved `using {dependency}` dependency "
                    "is never called by the public owner or its nested helpers."
                )
    return gaps


def validate_generated_files_against_implementation_plan(
    implementation_plan: Mapping[str, Any],
    generated_files: list[tuple[str, str, str]],
) -> list[str]:
    """Validate approved declaration and mechanic contracts against generated AST."""

    source_by_path = {
        str(Path(path).resolve()): source
        for path, _original, source in generated_files
    }
    original_by_path = {
        str(Path(path).resolve()): original
        for path, original, _source in generated_files
    }
    trees: dict[str, ast.Module] = {}
    errors: list[str] = []
    for path, source in source_by_path.items():
        try:
            trees[path] = ast.parse(source, filename=path)
        except SyntaxError as exc:
            errors.append(f"{path}: approved-plan AST validation failed: {exc}")
    errors.extend(_explicit_serialization_contract_gaps(implementation_plan, trees))
    errors.extend(_explicit_tuple_dict_result_gaps(implementation_plan, trees))
    errors.extend(_explicit_boundary_contract_gaps(implementation_plan, trees))
    errors.extend(_explicit_function_completion_gaps(implementation_plan, trees))

    def executable_owner_fingerprint(
        tree: ast.Module,
        owner: str,
        kind: str,
    ) -> str:
        """Return a documentation- and annotation-neutral owner fingerprint.

        :param tree: Parsed module tree.
        :param owner: Approved top-level owner name.
        :param kind: Approved owner kind.
        :return: Stable executable AST fingerprint or an empty string.
        """

        node = next(
            (
                candidate
                for candidate in tree.body
                if getattr(candidate, "name", None) == owner
                and (
                    kind == "class" and isinstance(candidate, ast.ClassDef)
                    or kind == "function"
                    and isinstance(
                        candidate,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                )
            ),
            None,
        )
        if node is None:
            return ""

        class StripPresentation(ast.NodeTransformer):
            """Remove non-executable callable presentation metadata."""

            @staticmethod
            def _body(statements: list[ast.stmt]) -> list[ast.stmt]:
                if (
                    statements
                    and isinstance(statements[0], ast.Expr)
                    and isinstance(statements[0].value, ast.Constant)
                    and isinstance(statements[0].value.value, str)
                ):
                    return statements[1:]
                return statements

            def _callable(self, candidate: ast.AST) -> ast.AST:
                candidate.body = self._body(candidate.body)
                candidate.decorator_list = []
                candidate.returns = None
                for argument in (
                    *candidate.args.posonlyargs,
                    *candidate.args.args,
                    *candidate.args.kwonlyargs,
                ):
                    argument.annotation = None
                if candidate.args.vararg is not None:
                    candidate.args.vararg.annotation = None
                if candidate.args.kwarg is not None:
                    candidate.args.kwarg.annotation = None
                return self.generic_visit(candidate)

            def visit_FunctionDef(self, candidate: ast.FunctionDef) -> ast.AST:
                return self._callable(candidate)

            def visit_AsyncFunctionDef(
                self,
                candidate: ast.AsyncFunctionDef,
            ) -> ast.AST:
                return self._callable(candidate)

            def visit_ClassDef(self, candidate: ast.ClassDef) -> ast.AST:
                candidate.body = self._body(candidate.body)
                candidate.decorator_list = []
                return self.generic_visit(candidate)

        normalized = StripPresentation().visit(copy.deepcopy(node))
        ast.fix_missing_locations(normalized)
        return ast.dump(normalized, include_attributes=False)

    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        contract = chunk.get("declaration_contract") or {}
        if not isinstance(contract, Mapping):
            continue
        kind = str(chunk.get("kind") or contract.get("kind") or "")
        owner = str(chunk.get("owner") or contract.get("owner") or "")
        if kind not in {"class", "function"} or not owner:
            continue
        if (
            kind == "class"
            and not list(contract.get("required_methods") or [])
            and not list(chunk.get("method_tasks") or [])
        ):
            # Passive data models can satisfy preservation requirements without
            # executable AST changes; behavior-first routing applies to callable
            # owners and classes with an explicit operation surface.
            continue
        behavior_requirements = [
            requirement
            for requirement in chunk.get("requirements") or []
            if isinstance(requirement, Mapping)
            and str(requirement.get("semantic_role") or "") == "behavior"
        ]
        if not behavior_requirements:
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        original_source = original_by_path.get(path, "")
        generated_tree = trees.get(path)
        if not original_source.strip() or generated_tree is None:
            continue
        try:
            original_tree = ast.parse(original_source, filename=path)
        except SyntaxError:
            continue
        before = executable_owner_fingerprint(original_tree, owner, kind)
        after = executable_owner_fingerprint(generated_tree, owner, kind)
        if before and before == after:
            errors.append(
                f"{path}:{owner}: executable implementation is unchanged from "
                "the original despite approved behavior requirements."
            )
    approved_requirement_text = " ".join(
        str(requirement.get("text") or "")
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for requirement in chunk.get("requirements") or []
        if isinstance(requirement, Mapping)
    )
    requirement_text_by_id = {
        str(requirement.get("id") or requirement.get("requirement_id") or ""): str(
            requirement.get("text") or requirement.get("requirement") or ""
        )
        for requirement in (
            implementation_plan.get("requirements")
            or implementation_plan.get("requirement_ledger")
            or []
        )
        if isinstance(requirement, Mapping)
    }
    module_entry_paths = {
        str(Path(str(chunk.get("path") or "")).resolve())
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and isinstance(chunk.get("declaration_contract"), Mapping)
        and bool(
            chunk.get("declaration_contract", {}).get(
                "module_entry_point_required"
            )
        )
    }
    for path, tree in trees.items():
        module_bindings = {
            alias.asname or alias.name.split(".", 1)[0]
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        module_bindings.update(
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        )
        module_bindings.update(
            node.name
            for node in tree.body
            if isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            )
        )
        builtin_names = set(dir(builtins))

        def call_root(call: ast.Call) -> str:
            current: ast.AST = call.func
            while isinstance(current, ast.Attribute):
                current = current.value
            return current.id if isinstance(current, ast.Name) else ""

        parent_by_node = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for callable_node in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            ancestor = parent_by_node.get(callable_node)
            nested_callable = False
            while ancestor is not None:
                if isinstance(
                    ancestor,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
                ):
                    nested_callable = True
                    break
                ancestor = parent_by_node.get(ancestor)
            if nested_callable:
                continue
            local_names = {
                argument.arg
                for argument in (
                    *callable_node.args.posonlyargs,
                    *callable_node.args.args,
                    *callable_node.args.kwonlyargs,
                )
            }
            local_names.update(
                node.id
                for node in ast.walk(callable_node)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, (ast.Store, ast.Param))
            )
            local_names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for node in ast.walk(callable_node)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            local_names.update(
                alias.asname or alias.name
                for node in ast.walk(callable_node)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            )
            local_names.update(
                argument.arg
                for node in ast.walk(callable_node)
                if isinstance(node, ast.Lambda)
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
            )
            local_names.update(
                node.name
                for node in ast.walk(callable_node)
                if node is not callable_node
                and isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
            )
            def nested_arguments_for(call: ast.Call) -> set[str]:
                """Include only parameters of scopes enclosing this call."""

                names: set[str] = set()
                ancestor = parent_by_node.get(call)
                while ancestor is not None and ancestor is not callable_node:
                    if isinstance(
                        ancestor,
                        (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
                    ):
                        arguments = ancestor.args
                        names.update(
                            argument.arg
                            for argument in (
                                *arguments.posonlyargs,
                                *arguments.args,
                                *arguments.kwonlyargs,
                            )
                        )
                        if arguments.vararg is not None:
                            names.add(arguments.vararg.arg)
                        if arguments.kwarg is not None:
                            names.add(arguments.kwarg.arg)
                    ancestor = parent_by_node.get(ancestor)
                return names

            unresolved_roots = sorted({
                root
                for call in ast.walk(callable_node)
                if isinstance(call, ast.Call)
                for root in [call_root(call)]
                if root
                and root not in local_names
                and root not in nested_arguments_for(call)
                and root not in module_bindings
                and root not in builtin_names
            })
            if unresolved_roots:
                errors.append(
                    f"{path}:{callable_node.name}: callable roots are neither "
                    "imported nor defined in scope: "
                    + ", ".join(unresolved_roots)
                )

        if path in module_entry_paths:
            main_guards = [
                node
                for node in tree.body
                if isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
                and any(
                    isinstance(comparator, ast.Constant)
                    and comparator.value == "__main__"
                    for comparator in node.test.comparators
                )
            ]
            if len(main_guards) != 1:
                errors.append(
                    f"{path}: approved module entry point requires exactly one "
                    f"guarded __main__ block; found {len(main_guards)}."
                )

        class_nodes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        signal_arity_by_class: dict[str, dict[str, int]] = {}
        for class_name, class_node in class_nodes.items():
            signal_arity_by_class[class_name] = {
                target.id: len(statement.value.args)
                for statement in class_node.body
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
        for class_name, class_node in class_nodes.items():
            signal_arities = signal_arity_by_class.get(class_name, {})
            for call in (
                node
                for node in ast.walk(class_node)
                if isinstance(node, ast.Call)
            ):
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "emit"
                    and isinstance(call.func.value, ast.Attribute)
                    and isinstance(call.func.value.value, ast.Name)
                    and call.func.value.value.id == "self"
                    and call.func.value.attr in signal_arities
                    and len(call.args)
                    != signal_arities[call.func.value.attr]
                ):
                    errors.append(
                        f"{path}:{class_name}: signal "
                        f"`{call.func.value.attr}` declares "
                        f"{signal_arities[call.func.value.attr]} argument(s) but "
                        f"emit supplies {len(call.args)}."
                    )
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for method in methods.values():
                worker_types = {
                    target.id: assignment.value.func.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, ast.Assign)
                    and isinstance(assignment.value, ast.Call)
                    and isinstance(assignment.value.func, ast.Name)
                    for target in assignment.targets
                    if isinstance(target, ast.Name)
                    and assignment.value.func.id in signal_arity_by_class
                }
                for call in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id in worker_types
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Attribute)
                    and isinstance(node.args[0].value, ast.Name)
                    and node.args[0].value.id == "self"
                ):
                    worker_name = call.func.value.value.id
                    signal_name = call.func.value.attr
                    handler_name = call.args[0].attr
                    handler = methods.get(handler_name)
                    if handler is None:
                        continue
                    signal_arity = signal_arity_by_class[
                        worker_types[worker_name]
                    ].get(signal_name)
                    if signal_arity is None:
                        continue
                    positional = [
                        *handler.args.posonlyargs,
                        *handler.args.args,
                    ]
                    if positional and positional[0].arg in {"self", "cls"}:
                        positional = positional[1:]
                    required_handler_args = max(
                        0, len(positional) - len(handler.args.defaults)
                    )
                    if signal_arity < required_handler_args:
                        errors.append(
                            f"{path}:{class_name}.{method.name}: signal "
                            f"`{worker_types[worker_name]}.{signal_name}` emits "
                            f"{signal_arity} argument(s), but connected handler "
                            f"`{handler_name}` requires "
                            f"{required_handler_args}."
                        )
    forbidden_imports_by_path: dict[str, set[str]] = {}
    dependency_constraints_by_path: dict[str, list[str]] = {}
    global_dependency_policy = (
        implementation_plan.get("dependency_policy")
        if isinstance(implementation_plan.get("dependency_policy"), Mapping)
        else {}
    )
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        declaration_contract = chunk.get("declaration_contract")
        chunk_policy = (
            declaration_contract.get("dependency_policy")
            if isinstance(declaration_contract, Mapping)
            and isinstance(
                declaration_contract.get("dependency_policy"), Mapping
            )
            else global_dependency_policy
        )
        forbidden_imports_by_path.setdefault(path, set()).update(
            str(module).casefold()
            for module in chunk_policy.get("forbidden_imports") or []
            if str(module).strip()
        )
        dependency_constraints_by_path.setdefault(path, []).extend(
            str(clause)
            for clause in chunk_policy.get("constraints") or []
            if str(clause).strip()
        )

    from tech_connector.services.implementation_plan_declaration_validation_service import (
        validate_approved_declaration_contracts,
    )

    validate_approved_declaration_contracts(
        implementation_plan,
        trees,
        errors,
        requirement_text_by_id,
    )
    for path, tree in trees.items():
        forbidden_imports = forbidden_imports_by_path.get(path, set())
        if forbidden_imports:
            imported_paths: set[str] = set()
            for import_node in ast.walk(tree):
                if isinstance(import_node, ast.Import):
                    imported_paths.update(
                        alias.name.casefold() for alias in import_node.names
                    )
                elif (
                    isinstance(import_node, ast.ImportFrom)
                    and import_node.level == 0
                    and import_node.module
                ):
                    module = import_node.module.casefold()
                    imported_paths.add(module)
                    imported_paths.update(
                        f"{module}.{alias.name.casefold()}"
                        for alias in import_node.names
                    )
            violations = sorted({
                imported
                for imported in imported_paths
                if any(
                    imported == forbidden
                    or imported.startswith(forbidden + ".")
                    for forbidden in forbidden_imports
                )
            })
            if violations:
                constraint_text = " ".join(dict.fromkeys(
                    dependency_constraints_by_path.get(path, [])
                ))
                errors.append(
                    f"{path}:<module>: explicit request dependency policy "
                    "forbids direct imports "
                    + ", ".join(violations)
                    + (
                        f"; governing request constraint: {constraint_text}"
                        if constraint_text else ""
                    )
                    + ". Use only the approved dependency owner or transport."
                )
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.split(".", 1)[0]
                in getattr(sys, "stdlib_module_names", set())
            ):
                continue
            try:
                imported_module = importlib.import_module(node.module)
            except (ImportError, ModuleNotFoundError) as exc:
                errors.append(
                    f"{path}:<module>: standard-library module "
                    f"{node.module!r} could not be imported: {exc}"
                )
                continue
            for alias in node.names:
                public_exports = getattr(imported_module, "__all__", None)
                is_public_attribute = (
                    hasattr(imported_module, alias.name)
                    and (
                        public_exports is None
                        or alias.name in public_exports
                    )
                )
                if alias.name == "*" or is_public_attribute:
                    continue
                try:
                    child_spec = importlib.util.find_spec(
                        f"{node.module}.{alias.name}"
                    )
                except (ImportError, ModuleNotFoundError, ValueError):
                    child_spec = None
                if child_spec is None:
                    errors.append(
                        f"{path}:<module>: standard-library module "
                        f"{node.module!r} does not expose imported symbol "
                        f"{alias.name!r}; replace the invented import with a "
                        "verified public declaration or remove its usages."
                    )
    docstring_requirement_texts = [
        str(requirement.get("text") or "")
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for requirement in chunk.get("requirements") or []
        if isinstance(requirement, Mapping)
        if "docstring" in str(requirement.get("text") or "").casefold()
    ]
    requires_complete_docstrings = True
    requires_explicit_return_fields = any(
        re.search(
            r":returns?\b|\breturns?\s+fields?\b",
            text,
            flags=re.IGNORECASE,
        )
        for text in docstring_requirement_texts
    )
    if requires_complete_docstrings:
        generic_docstring_pattern = re.compile(
            r"\bpreserving validated inputs, state transitions, and failure "
            r"behavior\b|\bafter validating construction inputs\b|"
            r"\bcontaining the validated inputs for this operation\b|"
            r"\bsupplied to this operation\b|"
            r"\bused by (?:the )?operation\b|"
            r"\bcoordinate .+ through .+ operations\b|"
            r"\bthe calculated [a-z_ ]+ value\b|"
            r"\bproduced after the operation completes successfully\b",
            flags=re.IGNORECASE,
        )

        def docstring_issues(name: str, node: ast.AST) -> list[str]:
            docstring = str(ast.get_docstring(node) or "").strip()
            issues: list[str] = []
            if isinstance(node, ast.ClassDef):
                fields = [
                    statement.target.id
                    for statement in node.body
                    if isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                ]
                for field in fields:
                    if not re.search(
                        rf":param\s+(?:[^:\s]+\s+)?{re.escape(field)}\s*:",
                        docstring,
                    ):
                        issues.append(f"is missing :param {field}:")
                return issues
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return issues
            parameters = [
                argument.arg
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
                if argument.arg not in {"self", "cls"}
            ]
            for parameter in parameters:
                if not re.search(
                    rf":param\s+(?:[^:\s]+\s+)?{re.escape(parameter)}\s*:",
                    docstring,
                ):
                    issues.append(f"is missing :param {parameter}:")
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
            if (
                (returns_value or requires_explicit_return_fields)
                and not re.search(r":returns?\s*:", docstring)
            ):
                issues.append("is missing :return:")
            return issues

        for path, tree in trees.items():
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    for issue in docstring_issues(node.name, node):
                        errors.append(
                            f"{path}:{node.name}: Requested useful docstrings are "
                            f"too vague: {node.name} {issue}"
                        )
                    for method in node.body:
                        if not (
                            isinstance(
                                method,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and (
                                not (
                                    method.name.startswith("__")
                                    and method.name.endswith("__")
                                )
                                or method.name == "__init__"
                            )
                        ):
                            continue
                        qualified = f"{node.name}.{method.name}"
                        for issue in docstring_issues(qualified, method):
                            errors.append(
                                f"{path}:{qualified}: Requested useful docstrings "
                                f"are too vague: {qualified} {issue}"
                            )
                elif isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and not node.name.startswith("_"):
                    for issue in docstring_issues(node.name, node):
                        errors.append(
                            f"{path}:{node.name}: Requested useful docstrings are "
                            f"too vague: {node.name} {issue}"
                        )
    for path, tree in trees.items():
        for function in [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            class LocalUsageVisitor(ast.NodeVisitor):
                def __init__(self, root: ast.AST) -> None:
                    self.root = root
                    self.loads: set[str] = set()
                    self.assignments: list[ast.AST] = []

                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    if node is self.root:
                        self.generic_visit(node)

                def visit_AsyncFunctionDef(
                    self,
                    node: ast.AsyncFunctionDef,
                ) -> None:
                    if node is self.root:
                        self.generic_visit(node)

                def visit_Name(self, node: ast.Name) -> None:
                    if isinstance(node.ctx, ast.Load):
                        self.loads.add(node.id)

                def visit_Assign(self, node: ast.Assign) -> None:
                    if any(
                        isinstance(target, ast.Name)
                        for target in node.targets
                    ):
                        self.assignments.append(node)
                    self.generic_visit(node)

                def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                    if isinstance(node.target, ast.Name):
                        self.assignments.append(node)
                    self.generic_visit(node)

            usage = LocalUsageVisitor(function)
            usage.visit(function)
            for assignment in usage.assignments:
                targets = (
                    [
                        target.id
                        for target in assignment.targets
                        if isinstance(target, ast.Name)
                    ]
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target.id]
                )
                unused = [
                    name
                    for name in targets
                    if name not in usage.loads and not name.startswith("_")
                ]
                if unused:
                    errors.append(
                        f"{path}:{function.name}: unused local assignment(s) "
                        f"introduce dead code: {', '.join(unused)}."
                    )
            linear_assignments: dict[str, list[tuple[int, ast.AST]]] = {}
            for statement_index, statement in enumerate(function.body):
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                ):
                    linear_assignments.setdefault(
                        statement.targets[0].id,
                        [],
                    ).append((statement_index, statement))
                elif (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.value is not None
                ):
                    linear_assignments.setdefault(
                        statement.target.id,
                        [],
                    ).append((statement_index, statement))
            for name, assignments in linear_assignments.items():
                for assignment_index in range(len(assignments) - 1):
                    statement_index, assignment = assignments[assignment_index]
                    next_statement_index, next_assignment = assignments[
                        assignment_index + 1
                    ]
                    used_before_overwrite = any(
                        isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Load)
                        and node.id == name
                        for statement in function.body[
                            statement_index + 1:next_statement_index
                        ]
                        for node in ast.walk(statement)
                    )
                    used_by_next_assignment = any(
                        isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Load)
                        and child.id == name
                        for child in ast.walk(
                            getattr(next_assignment, "value", None)
                        )
                    )
                    if (
                        not used_before_overwrite
                        and not used_by_next_assignment
                        and isinstance(
                            getattr(assignment, "value", None),
                            ast.Call,
                        )
                    ):
                        errors.append(
                            f"{path}:{function.name}: result assigned to {name} "
                            "is overwritten before use; preserve the call side "
                            "effect but discard its unused result."
                        )
            if (
                function.name.startswith("test_")
                or "self_test" in function.name.casefold()
            ):
                for try_node in [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Try)
                ]:
                    catches_asserted_exception = any(
                        handler.type is not None
                        and any(
                            isinstance(child, ast.Assert)
                            for child in ast.walk(handler)
                        )
                        for handler in try_node.handlers
                    )
                    if (
                        catches_asserted_exception
                        and not try_node.orelse
                        and any(
                            isinstance(child, ast.Call)
                            for statement in try_node.body
                            for child in ast.walk(statement)
                        )
                    ):
                        errors.append(
                            f"{path}:{function.name}: exception proof can pass "
                            "silently when the operation does not raise; add an "
                            "explicit failure path for the no-exception branch."
                        )
    for path, tree in trees.items():
        type_variable_declarations = {
            target.id: statement.value
            for statement in tree.body
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            for target in (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            if isinstance(target, ast.Name)
            and isinstance(getattr(statement, "value", None), ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "TypeVar"
        }
        type_variables = set(type_variable_declarations)
        unrestricted_type_variables = {
            name
            for name, declaration in type_variable_declarations.items()
            if len(declaration.args) <= 1
            and not any(
                keyword.arg in {"bound", "constraints"}
                for keyword in declaration.keywords
            )
        }
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            class_docstring = str(ast.get_docstring(class_node) or "")
            class_text = ast.unparse(class_node)
            uses_synchronization = any(
                isinstance(node, (ast.With, ast.AsyncWith))
                and any(
                    any(
                        token in ast.unparse(item.context_expr).casefold()
                        for token in ("lock", "mutex", "semaphore", "condition")
                    )
                    for item in node.items
                )
                for node in ast.walk(class_node)
            ) or any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"acquire", "release"}
                for node in ast.walk(class_node)
            )
            if (
                re.search(r"\bthread[- ]safe\b", class_docstring, re.IGNORECASE)
                and not uses_synchronization
            ):
                errors.append(
                    f"{path}:{class_node.name}: documentation claims thread-safe "
                    "behavior without a proven synchronization boundary."
                )
            if re.search(r"\batomic\b", class_docstring, re.IGNORECASE) and not (
                uses_synchronization
                or ".replace(" in class_text
                or "os.replace(" in class_text
                or any(
                    token in class_text.casefold()
                    for token in ("transaction", "compare_and_swap")
                )
            ):
                errors.append(
                    f"{path}:{class_node.name}: documentation claims atomic "
                    "behavior without a proven lock, transaction, or atomic "
                    "replacement boundary."
                )
            used_type_variables = {
                node.id
                for node in ast.walk(class_node)
                if isinstance(node, ast.Name) and node.id in type_variables
            }
            generic_type_variables = {
                node.id
                for base in class_node.bases
                if isinstance(base, ast.Subscript)
                and isinstance(base.value, ast.Name)
                and base.value.id == "Generic"
                for node in ast.walk(base.slice)
                if isinstance(node, ast.Name)
            }
            missing_generic_owners = sorted(
                used_type_variables - generic_type_variables
            )
            if missing_generic_owners:
                errors.append(
                    f"{path}:{class_node.name}: class annotations use type "
                    f"variable(s) {', '.join(missing_generic_owners)} without "
                    "declaring their Generic ownership."
                )
            unrestricted_key_usages: set[tuple[str, str]] = set()
            for function in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                generic_parameters = {
                    argument.arg: argument.annotation.id
                    for argument in (
                        *function.args.posonlyargs,
                        *function.args.args,
                        *function.args.kwonlyargs,
                    )
                    if isinstance(argument.annotation, ast.Name)
                    and argument.annotation.id in unrestricted_type_variables
                }
                for subscript in [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "self"
                    and isinstance(node.slice, ast.Name)
                    and node.slice.id in generic_parameters
                    and isinstance(node.ctx, (ast.Store, ast.Del))
                ]:
                    unrestricted_key_usages.add(
                        (
                            subscript.slice.id,
                            generic_parameters[subscript.slice.id],
                        )
                    )
            if unrestricted_key_usages:
                errors.append(
                    f"{path}:{class_node.name}: unrestricted generic value(s) "
                    + ", ".join(
                        f"{parameter}:{type_variable}"
                        for parameter, type_variable
                        in sorted(unrestricted_key_usages)
                    )
                    + " are used as mapping keys; use an order-preserving entry "
                    "sequence or explicitly constrain the TypeVar to Hashable."
                )

            parent_by_id = {
                id(child): parent
                for parent in ast.walk(class_node)
                for child in ast.iter_child_nodes(parent)
            }
            initializer = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "__init__"
                ),
                None,
            )
            accumulating_attributes = {
                target.attr
                for assignment in (
                    ast.walk(initializer) if initializer is not None else []
                )
                if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                for target in (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                if isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(
                    assignment.value,
                    (ast.List, ast.Dict, ast.Set),
                )
                and not (
                    getattr(assignment.value, "elts", None)
                    or getattr(assignment.value, "keys", None)
                )
            }
            for attribute_name in sorted(accumulating_attributes):
                has_growth = False
                has_reset = False
                length_reads = 0
                meaningful_reads = 0
                for attribute in [
                    node
                    for node in ast.walk(class_node)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr == attribute_name
                ]:
                    parent = parent_by_id.get(id(attribute))
                    grandparent = parent_by_id.get(id(parent)) if parent else None
                    if (
                        isinstance(parent, ast.Attribute)
                        and parent.value is attribute
                        and isinstance(grandparent, ast.Call)
                        and grandparent.func is parent
                    ):
                        if parent.attr in {"append", "add", "extend", "insert"}:
                            has_growth = True
                            continue
                        if parent.attr in {"clear"}:
                            has_reset = True
                            continue
                        if parent.attr in {"discard", "pop", "remove"}:
                            continue
                    if (
                        isinstance(parent, ast.Call)
                        and isinstance(parent.func, ast.Name)
                        and parent.func.id == "len"
                    ):
                        length_reads += 1
                        continue
                    if isinstance(attribute.ctx, ast.Load):
                        meaningful_reads += 1
                if (
                    has_growth
                    and length_reads
                    and not has_reset
                    and not meaningful_reads
                ):
                    errors.append(
                        f"{path}:{class_node.name}: self.{attribute_name} is an "
                        "unbounded write-only accumulator consumed only through "
                        "len(); use an explicit counter or expose/reset the "
                        "collection according to the contract."
                    )

            for function in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                for conditional in [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.If) and node.orelse
                ]:
                    if conditional.body and conditional.orelse:
                        body_tail = ast.dump(
                            conditional.body[-1],
                            include_attributes=False,
                        )
                        else_tail = ast.dump(
                            conditional.orelse[-1],
                            include_attributes=False,
                        )
                        if body_tail == else_tail:
                            errors.append(
                                f"{path}:{class_node.name}.{function.name}: "
                                "conditional branches duplicate the same trailing "
                                "statement; factor it once after the branch."
                            )
                    if conditional.body and isinstance(
                        conditional.body[-1],
                        (ast.Return, ast.Raise),
                    ):
                        errors.append(
                            f"{path}:{class_node.name}.{function.name}: uses an "
                            "unnecessary else branch after a terminating return or "
                            "raise."
                        )

    entrypoint_paths = {
        str(Path(str(chunk.get("path") or "")).resolve())
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and (
            bool(
                (chunk.get("declaration_contract") or {}).get(
                    "module_entry_point_required"
                )
            )
            or any(
                re.search(
                    r"\bif\s+__name__\b|\bruns?\s+standalone\b"
                    r"|\bstandalone\b[^.!?\n]{0,60}\bentry\s+point\b"
                    r"|\brunnable\s+(?:main\s+)?example\b|\b__main__\b",
                    str(requirement.get("text") or ""),
                    flags=re.IGNORECASE,
                )
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, Mapping)
            )
        )
    }
    class_methods_by_path: dict[str, set[str]] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or str(chunk.get("kind") or "") != "class":
            continue
        resolved_path = str(Path(str(chunk.get("path") or "")).resolve())
        class_methods_by_path.setdefault(resolved_path, set()).update(
            str(value)
            for value in (
                chunk.get("declaration_contract") or {}
            ).get("required_methods") or []
            if str(value) and not str(value).startswith("__")
        )
    for path, tree in trees.items():
        has_main_guard = any(
            isinstance(node, ast.If)
            and "__name__" in ast.unparse(node.test)
            and "__main__" in ast.unparse(node.test)
            for node in tree.body
        )
        if (
            has_main_guard
            and path not in entrypoint_paths
            and not Path(path).name.startswith("test_")
        ):
            errors.append(
                f"{path}:<module>: unrequested standalone entry point is present."
            )
        if (
            path in entrypoint_paths
            and not has_main_guard
            and not Path(path).name.startswith("test_")
        ):
            errors.append(
                f"{path}:<module>: approved runnable entry point is missing."
            )
        duplicate_method_functions = sorted(
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in class_methods_by_path.get(path, set())
        )
        if duplicate_method_functions:
            errors.append(
                f"{path}:<module>: class-owned methods were duplicated as "
                "top-level functions: " + ", ".join(duplicate_method_functions)
            )
        if not Path(path).name.startswith("test_"):
            for node in tree.body:
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                ) and node.name.startswith("test_"):
                    errors.append(
                        f"{path}:<module>: test declaration `{node.name}` is "
                        "unrequested in a production module."
                    )

    approved_surfaces: dict[str, set[str]] = {}
    approved_member_types: dict[str, dict[str, str]] = {}
    approved_constructor_types: dict[str, str] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or str(chunk.get("kind") or "") != "class":
            continue
        contract = chunk.get("declaration_contract") or {}
        allowed = {
            match.group(1)
            for signature in contract.get("callable_signatures") or []
            for match in [
                re.search(
                    r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                    str(signature),
                )
            ]
            if match
        }
        allowed.update(
            str(value) for value in contract.get("required_methods") or []
        )
        allowed.update(
            str(item.get("name") or "")
            for item in contract.get("attributes") or []
            if isinstance(item, Mapping)
        )
        allowed.update(
            str(item.get("name") or "")
            if isinstance(item, Mapping)
            else str(item)
            for item in contract.get("properties") or []
        )
        approved_surfaces[str(chunk.get("owner") or "")] = {
            value for value in allowed if value
        }
        approved_member_types[str(chunk.get("owner") or "")] = {
            str(item.get("name") or ""): str(
                item.get("return_type")
                or item.get("type")
                or item.get("annotation")
                or ""
            )
            for item in contract.get("properties") or []
            if isinstance(item, Mapping)
            and str(item.get("name") or "")
        }

    # The declaration contract can omit a property's return type even though the
    # generated declaration contains it. Overlay generated annotations so
    # verification code can be checked against the code it will actually run.
    for tree in trees.values():
        for class_node in [
            item for item in tree.body if isinstance(item, ast.ClassDef)
        ]:
            if class_node.name not in approved_surfaces:
                continue
            for member in class_node.body:
                if not isinstance(
                    member,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                if member.name == "__init__":
                    constructor_arguments = [
                        argument
                        for argument in (
                            *member.args.posonlyargs,
                            *member.args.args,
                        )
                        if argument.arg not in {"self", "cls"}
                    ]
                    if (
                        constructor_arguments
                        and constructor_arguments[0].annotation is not None
                    ):
                        approved_constructor_types[class_node.name] = (
                            ast.unparse(constructor_arguments[0].annotation)
                        )
                if not any(
                    (
                        isinstance(decorator, ast.Name)
                        and decorator.id == "property"
                    )
                    or (
                        isinstance(decorator, ast.Attribute)
                        and decorator.attr == "property"
                    )
                    for decorator in member.decorator_list
                ):
                    continue
                if member.returns is not None:
                    approved_member_types.setdefault(
                        class_node.name,
                        {},
                    )[member.name] = ast.unparse(member.returns)

    builtin_verification_types = {
        value.__name__: value
        for value in (
            bool,
            bytes,
            bytearray,
            complex,
            dict,
            float,
            frozenset,
            int,
            list,
            memoryview,
            range,
            set,
            str,
            tuple,
        )
    }

    def verification_owner_for(
        path: str,
        tree: ast.Module,
        lineno: int,
        verification_ranges: list[tuple[str, int, int]],
        is_test_module: bool,
    ) -> str:
        verification_owner = next(
            (
                owner
                for owner, start, end in verification_ranges
                if start <= lineno <= end
            ),
            "",
        )
        if not is_test_module:
            return verification_owner
        if verification_owner:
            return verification_owner
        for item in ast.walk(tree):
            if not isinstance(
                item,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            if int(item.lineno) <= lineno <= int(
                item.end_lineno or item.lineno
            ):
                return item.name
        return "<module>"

    verification_owners_by_path: dict[str, list[tuple[str, int, int]]] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or not any(
            isinstance(requirement, Mapping)
            and str(requirement.get("semantic_role") or "") == "verification"
            for requirement in chunk.get("requirements") or []
        ):
            continue
        verification_path = str(
            Path(str(chunk.get("path") or "")).resolve()
        )
        verification_tree = trees.get(verification_path)
        if verification_tree is None:
            continue
        verification_node = _definition_nodes(verification_tree).get(
            str(chunk.get("owner") or "")
        )
        if isinstance(
            verification_node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            verification_owners_by_path.setdefault(
                verification_path,
                [],
            ).append((
                verification_node.name,
                int(verification_node.lineno),
                int(verification_node.end_lineno or verification_node.lineno),
            ))

    for path, tree in trees.items():
        is_test_module = Path(path).name.startswith("test_")
        verification_ranges = verification_owners_by_path.get(path, [])
        if not is_test_module and not verification_ranges:
            continue
        instance_types: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in approved_surfaces
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    instance_types[target.id] = value.func.id
                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    instance_types[f"self.{target.attr}"] = value.func.id
        for call in [
            node for node in ast.walk(tree) if isinstance(node, ast.Call)
        ]:
            if not (
                isinstance(call.func, ast.Name)
                and call.func.id in approved_constructor_types
                and call.args
                and isinstance(call.args[0], ast.Attribute)
            ):
                continue
            argument = call.args[0]
            argument_receiver = ""
            if isinstance(argument.value, ast.Name):
                argument_receiver = argument.value.id
            elif (
                isinstance(argument.value, ast.Attribute)
                and isinstance(argument.value.value, ast.Name)
                and argument.value.value.id == "self"
            ):
                argument_receiver = f"self.{argument.value.attr}"
            argument_class = instance_types.get(argument_receiver)
            argument_annotation = approved_member_types.get(
                argument_class or "",
                {},
            ).get(argument.attr, "")
            actual_root_match = re.match(
                r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
                r"([A-Za-z_][A-Za-z0-9_]*)",
                argument_annotation.strip(),
            )
            expected_annotation = approved_constructor_types[call.func.id]
            expected_root_match = re.match(
                r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
                r"([A-Za-z_][A-Za-z0-9_]*)",
                expected_annotation.strip(),
            )
            actual_root = (
                actual_root_match.group(1).casefold()
                if actual_root_match is not None
                else ""
            )
            expected_root = (
                expected_root_match.group(1).casefold()
                if expected_root_match is not None
                else ""
            )
            actual_type = builtin_verification_types.get(actual_root)
            expected_type = builtin_verification_types.get(expected_root)
            compatible = True
            if actual_type is not None and expected_type is not None:
                compatible = issubclass(actual_type, expected_type)
            elif (
                actual_type is not None
                and expected_root in {"mapping", "mutablemapping"}
            ):
                compatible = all(
                    member in dir(actual_type)
                    for member in ("items", "keys", "values")
                )
            if compatible:
                continue
            test_owner = verification_owner_for(
                path,
                tree,
                int(call.lineno),
                verification_ranges,
                is_test_module,
            )
            if not is_test_module and not test_owner:
                continue
            errors.append(
                f"{path}:{test_owner}: verification call "
                f"`{ast.unparse(call)}` passes `{argument_class}.{argument.attr}` "
                f"with generated type `{argument_annotation}` to "
                f"`{call.func.id}` constructor parameter "
                f"`{expected_annotation}`. Repair only this verification callable "
                "with a type-compatible public value; do not broaden or rewrite "
                "the valid production constructor."
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            receiver = ""
            if isinstance(node.value, ast.Name):
                receiver = node.value.id
            elif (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
            ):
                receiver = f"self.{node.value.attr}"
            class_name = instance_types.get(receiver)
            if (
                class_name
                and node.attr not in approved_surfaces[class_name]
                and not node.attr.startswith("__")
            ):
                verification_owner = next(
                    (
                        owner
                        for owner, start, end in verification_ranges
                        if start <= int(node.lineno) <= end
                    ),
                    "",
                )
                if not is_test_module and not verification_owner:
                    continue
                test_owner = "<module>"
                if verification_owner:
                    test_owner = verification_owner
                else:
                    for class_node in [
                        item for item in tree.body if isinstance(item, ast.ClassDef)
                    ]:
                        for method_node in [
                            item
                            for item in class_node.body
                            if isinstance(
                                item,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                        ]:
                            if (
                                int(method_node.lineno) <= int(node.lineno)
                                <= int(method_node.end_lineno or method_node.lineno)
                            ):
                                test_owner = (
                                    f"{class_node.name}.{method_node.name}"
                                )
                errors.append(
                    f"{path}:{test_owner}: verification code accesses unapproved `{class_name}."
                    f"{node.attr}`; use only the approved public contract. Trigger UI "
                    "behavior through approved widget attributes (for example, a "
                    "button's click() method), and assert state only through approved "
                    "dependency query methods; never call dialog slots directly or "
                    "inspect production storage. The exact approved surface for "
                    f"`{class_name}` is: "
                    + ", ".join(sorted(approved_surfaces[class_name]))
                    + "."
                )
                continue

            # Validate chained members through an approved property's concrete
            # built-in return type. For example, if `items` is annotated as a
            # tuple, verification code may use tuple members but cannot invent a
            # list-only member. This is derived from annotations and Python's
            # actual runtime surface rather than from request-specific names.
            if not isinstance(node.value, ast.Attribute):
                continue
            property_access = node.value
            property_receiver = ""
            if isinstance(property_access.value, ast.Name):
                property_receiver = property_access.value.id
            elif (
                isinstance(property_access.value, ast.Attribute)
                and isinstance(property_access.value.value, ast.Name)
                and property_access.value.value.id == "self"
            ):
                property_receiver = f"self.{property_access.value.attr}"
            property_class = instance_types.get(property_receiver)
            property_annotation = approved_member_types.get(
                property_class or "",
                {},
            ).get(property_access.attr, "")
            annotation_root_match = re.match(
                r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
                r"([A-Za-z_][A-Za-z0-9_]*)",
                property_annotation.strip(),
            )
            annotation_root = (
                annotation_root_match.group(1)
                if annotation_root_match is not None
                else ""
            )
            runtime_type = builtin_verification_types.get(
                annotation_root.casefold()
            )
            if runtime_type is None or node.attr in dir(runtime_type):
                continue
            test_owner = verification_owner_for(
                path,
                tree,
                int(node.lineno),
                verification_ranges,
                is_test_module,
            )
            if not is_test_module and not test_owner:
                continue
            errors.append(
                f"{path}:{test_owner}: verification expression "
                f"`{ast.unparse(node)}` accesses invalid member `{node.attr}` "
                f"on `{property_class}.{property_access.attr}`, whose generated "
                f"return annotation resolves to built-in `{runtime_type.__name__}`. "
                "Repair only this verification callable and use a member supported "
                "by the resolved runtime type; do not change the valid production "
                "declaration."
            )

    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        owner = str(chunk.get("owner") or "")
        kind = str(chunk.get("kind") or "")
        contract = chunk.get("declaration_contract") or {}
        tree = trees.get(path)
        if tree is None:
            continue
        definitions = _definition_nodes(tree)
        if owner == "<module>":
            owner_node: ast.AST = tree
        else:
            owner_node = definitions.get(owner)  # type: ignore[assignment]
            if owner_node is None:
                errors.append(
                    f"{path}:{owner}: approved declaration is missing."
                )
                continue
        verification_clauses = [
            match.group(1).strip().rstrip(".")
            for validation_case in chunk.get("validation_cases") or []
            if isinstance(validation_case, Mapping)
            for check in validation_case.get("checks") or []
            for match in [
                re.search(
                    r"exact observable clause:\s*(.+)$",
                    str(check),
                    flags=re.IGNORECASE,
                )
            ]
            if match is not None
        ]
        if (
            verification_clauses
            and isinstance(owner_node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            missing_proofs = _verification_proof_gaps(
                owner_node,
                verification_clauses,
            )
            if missing_proofs:
                errors.append(
                    f"{path}:{owner}: requested verification callable does not "
                    "independently prove clause(s): "
                    + ", ".join(missing_proofs)
                    + ". Repair only this callable with explicit setup, action, "
                    "assertion, and exception evidence for every listed clause."
                )
        if isinstance(owner_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for discarded_gap in _discarded_pure_transform_gaps(owner_node):
                errors.append(
                    f"{path}:{owner}: discarded pure transform introduces dead "
                    f"behavior: {discarded_gap}. Assign and consume the returned "
                    "value inside this callable."
                )
            for guard_gap in _final_value_guard_gaps(owner_node):
                errors.append(
                    f"{path}:{owner}: final-result validation order is unsafe: "
                    f"{guard_gap} Repair only this callable."
                )
            owned_requirement_text = " ".join(
                str(requirement.get("text") or "")
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, Mapping)
            )
            for regex_gap in _regex_requirement_gaps(
                owner_node,
                owned_requirement_text,
            ):
                errors.append(
                    f"{path}:{owner}: approved regex behavior is not implemented: "
                    f"{regex_gap}. Repair only this callable."
                )
            for trim_gap in _boundary_trim_requirement_gaps(
                owner_node,
                owned_requirement_text,
            ):
                errors.append(
                    f"{path}:{owner}: approved boundary normalization is not "
                    f"implemented: {trim_gap}. Repair only this callable."
                )
            merge_contract = owned_requirement_text.casefold()
            if (
                "mapping patch" in merge_contract
                and "non-mapping" in merge_contract
                and "deletes that key" in merge_contract
                and "fully detached" in merge_contract
                and len(owner_node.args.args) >= 2
            ):
                document_name = owner_node.args.args[0].arg
                patch_name = owner_node.args.args[1].arg
                source_text = ast.unparse(owner_node)
                initializes_mapping_for_scalar = bool(re.search(
                    rf"deepcopy\({re.escape(document_name)}\)\s+if\s+"
                    rf"isinstance\({re.escape(document_name)},\s*[^)]+\)\s+else\s+\{{\}}",
                    source_text,
                )) or bool(re.search(
                    rf"if\s+isinstance\({re.escape(document_name)},\s*[^)]+\):"
                    rf"[\s\S]*?=\s*deepcopy\({re.escape(document_name)}\)"
                    rf"[\s\S]*?else:[\s\S]*?=\s*\{{\}}",
                    source_text,
                ))
                if not initializes_mapping_for_scalar:
                    for conditional in (
                        node
                        for node in ast.walk(owner_node)
                        if isinstance(node, ast.If)
                    ):
                        tested_document_mapping = (
                            isinstance(conditional.test, ast.Call)
                            and isinstance(conditional.test.func, ast.Name)
                            and conditional.test.func.id == "isinstance"
                            and conditional.test.args
                            and isinstance(conditional.test.args[0], ast.Name)
                            and conditional.test.args[0].id == document_name
                        )
                        if not tested_document_mapping:
                            continue
                        true_assignments = {
                            target.id
                            for statement in conditional.body
                            if isinstance(statement, ast.Assign)
                            for target in statement.targets
                            if isinstance(target, ast.Name)
                            and isinstance(statement.value, ast.Call)
                            and isinstance(statement.value.func, ast.Name)
                            and statement.value.func.id == "deepcopy"
                        }
                        false_assignments = {
                            target.id
                            for statement in conditional.orelse
                            if isinstance(statement, ast.Assign)
                            for target in statement.targets
                            if isinstance(target, ast.Name)
                            and isinstance(statement.value, ast.Dict)
                            and not statement.value.keys
                        }
                        if true_assignments & false_assignments:
                            initializes_mapping_for_scalar = True
                            break
                mapping_result_reads = any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "get"
                    and isinstance(call.func.value, ast.Name)
                    for call in ast.walk(owner_node)
                ) or any(
                    isinstance(node, ast.Subscript)
                    for node in ast.walk(owner_node)
                )
                if mapping_result_reads and not initializes_mapping_for_scalar:
                    errors.append(
                        f"{path}:{owner}: mapping patches over non-mapping documents "
                        "must start from a new empty mapping before any `.get` or key "
                        "access; deep-copy the document only when it is a mapping."
                    )
                unsafe_deletes = any(
                    isinstance(node, ast.Delete)
                    and any(isinstance(target, ast.Subscript) for target in node.targets)
                    for node in ast.walk(owner_node)
                )
                if unsafe_deletes:
                    errors.append(
                        f"{path}:{owner}: a None member must delete only an existing "
                        "key; use a missing-safe removal such as `pop(key, None)`."
                    )
                returns_patch_alias = any(
                    isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == patch_name
                    for node in ast.walk(owner_node)
                )
                if returns_patch_alias:
                    errors.append(
                        f"{path}:{owner}: non-mapping replacement returns the input "
                        "patch by reference; return a deep copy to satisfy the fully "
                        "detached result contract."
                    )
                patch_member_value_names = {
                    node.target.elts[1].id
                    for node in ast.walk(owner_node)
                    if isinstance(node, ast.For)
                    and isinstance(node.target, (ast.Tuple, ast.List))
                    and len(node.target.elts) >= 2
                    and isinstance(node.target.elts[1], ast.Name)
                    and isinstance(node.iter, ast.Call)
                    and isinstance(node.iter.func, ast.Attribute)
                    and node.iter.func.attr == "items"
                    and isinstance(node.iter.func.value, ast.Name)
                    and node.iter.func.value.id == patch_name
                }
                aliases_patch_member = any(
                    isinstance(node, (ast.Assign, ast.AnnAssign))
                    and isinstance(node.value, ast.Name)
                    and node.value.id in patch_member_value_names
                    and any(
                        isinstance(target, ast.Subscript)
                        for target in (
                            node.targets
                            if isinstance(node, ast.Assign)
                            else [node.target]
                        )
                    )
                    for node in ast.walk(owner_node)
                )
                if aliases_patch_member:
                    errors.append(
                        f"{path}:{owner}: mapping member replacement stores an "
                        "input patch value by reference; deep-copy direct member "
                        "values so nested mutable data is detached."
                    )
        if kind == "class" and isinstance(owner_node, ast.ClassDef):
            bases = {
                ast.unparse(base).rsplit(".", 1)[-1]
                for base in owner_node.bases
            }
            required_base = str(contract.get("base") or "")
            if required_base and required_base.rsplit(".", 1)[-1] not in bases:
                errors.append(
                    f"{path}:{owner}: approved base `{required_base}` is missing."
                )
            if required_base:
                required_base_name = required_base.rsplit(".", 1)[-1]
                module_bindings = {
                    node.name
                    for node in tree.body
                    if isinstance(
                        node,
                        (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                module_bindings.update(
                    alias.asname or alias.name.split(".", 1)[0]
                    for node in tree.body
                    if isinstance(node, ast.Import)
                    for alias in node.names
                )
                module_bindings.update(
                    alias.asname or alias.name
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names
                )
                if (
                    required_base_name not in {
                        "BaseException", "Exception", "object",
                    }
                    and required_base_name not in module_bindings
                ):
                    errors.append(
                        f"{path}:{owner}: approved base `{required_base_name}` "
                        "is referenced but neither imported nor defined."
                    )
            if required_base:
                unapproved_bases = sorted(
                    base
                    for base in bases
                    if base != required_base.rsplit(".", 1)[-1]
                )
                if unapproved_bases:
                    errors.append(
                        f"{path}:{owner}: unapproved base classes are present: "
                        + ", ".join(unapproved_bases)
                        + f". The approved base is `{required_base}`."
                    )
                required_base_name = required_base.rsplit(".", 1)[-1]
                base_excerpt = next(
                    (
                        str(item.get("source_excerpt") or "")
                        for item in chunk.get("evidence") or []
                        if isinstance(item, Mapping)
                        and str(item.get("name") or "").rsplit(".", 1)[-1]
                        == required_base_name
                        and str(item.get("source_excerpt") or "").strip()
                    ),
                    "",
                )
                required_constructor_parameters: list[str] = []
                if base_excerpt:
                    try:
                        base_tree = ast.parse(base_excerpt)
                    except SyntaxError:
                        base_tree = None
                    base_class = next(
                        (
                            node
                            for node in (base_tree.body if base_tree else [])
                            if isinstance(node, ast.ClassDef)
                            and node.name == required_base_name
                        ),
                        None,
                    )
                    base_init = next(
                        (
                            node
                            for node in (base_class.body if base_class else [])
                            if isinstance(
                                node,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and node.name == "__init__"
                        ),
                        None,
                    )
                    if base_init is not None:
                        positional = [
                            *base_init.args.posonlyargs,
                            *base_init.args.args,
                        ]
                        if positional and positional[0].arg in {"self", "cls"}:
                            positional = positional[1:]
                        required_count = max(
                            0,
                            len(positional) - len(base_init.args.defaults),
                        )
                        required_constructor_parameters = [
                            argument.arg
                            for argument in positional[:required_count]
                        ]
                if required_constructor_parameters:
                    class_init = _method_map(owner_node).get("__init__")
                    super_init_call = next(
                        (
                            call
                            for call in ast.walk(class_init)
                            if isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "__init__"
                            and isinstance(call.func.value, ast.Call)
                            and isinstance(call.func.value.func, ast.Name)
                            and call.func.value.func.id == "super"
                        ),
                        None,
                    ) if class_init is not None else None
                    supplied_keywords = {
                        str(keyword.arg)
                        for keyword in (super_init_call.keywords if super_init_call else [])
                        if keyword.arg
                    }
                    supplied_required = len(
                        super_init_call.args if super_init_call else []
                    ) + sum(
                        parameter in supplied_keywords
                        for parameter in required_constructor_parameters
                    )
                    if supplied_required < len(required_constructor_parameters):
                        errors.append(
                            f"{path}:{owner}.__init__: verified base "
                            f"`{required_base_name}` requires constructor values "
                            "for "
                            + ", ".join(required_constructor_parameters)
                            + "; the generated super().__init__ call does not "
                            "supply them."
                        )
            decorators = {
                ast.unparse(
                    decorator.func
                    if isinstance(decorator, ast.Call)
                    else decorator
                ).rsplit(".", 1)[-1]
                for decorator in owner_node.decorator_list
            }
            for decorator in contract.get("decorators") or []:
                if str(decorator).rsplit(".", 1)[-1] not in decorators:
                    errors.append(
                        f"{path}:{owner}: approved decorator `@{decorator}` is missing."
                    )
            methods = _method_map(owner_node)
            initializer = methods.get("__init__")
            if initializer is not None:
                owned_requirement_text = " ".join(
                    str(requirement.get("text") or "")
                    for requirement in chunk.get("requirements") or []
                    if isinstance(requirement, Mapping)
                )
                constructor_parameters = {
                    argument.arg
                    for argument in (
                        *initializer.args.posonlyargs,
                        *initializer.args.args,
                        *initializer.args.kwonlyargs,
                    )
                    if argument.arg not in {"self", "cls"}
                }
                initialized_instance_attributes = {
                    node.attr
                    for node in ast.walk(initializer)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and isinstance(node.ctx, ast.Store)
                }
                initialized_class_attributes = {
                    target.id
                    for statement in owner_node.body
                    if isinstance(statement, (ast.Assign, ast.AnnAssign))
                    for target in (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                    if isinstance(target, ast.Name)
                }
                directly_read_public_attributes = {
                    node.attr
                    for method_name, method in methods.items()
                    if not method_name.startswith("_")
                    for node in ast.walk(method)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and isinstance(node.ctx, ast.Load)
                }
                missing_constructor_state = sorted(
                    constructor_parameters
                    & directly_read_public_attributes
                    - initialized_instance_attributes
                    - initialized_class_attributes
                )
                for attribute_name in missing_constructor_state:
                    errors.append(
                        f"{path}:{owner}.__init__: constructor argument "
                        f"`{attribute_name}` is read as `self.{attribute_name}` by "
                        "public behavior but is never initialized on the instance."
                    )
                initializer_source = ast.unparse(initializer)
                for parameter_name in sorted(constructor_parameters):
                    non_bool_integer_required = bool(
                        re.search(
                            rf"\b{re.escape(parameter_name)}\b[^.;]*\bnon[- ]bool\b[^.;]*\binteger\b",
                            owned_requirement_text,
                            flags=re.IGNORECASE,
                        )
                    )
                    exact_integer_check = bool(
                        re.search(
                            rf"\btype\s*\(\s*{re.escape(parameter_name)}\s*\)\s*"
                            r"(?:is(?:\s+not)?|==|!=)\s*int\b",
                            initializer_source,
                        )
                    )
                    explicit_bool_rejection = bool(
                        re.search(
                            rf"\bisinstance\s*\(\s*{re.escape(parameter_name)}\s*,\s*bool\s*\)",
                            initializer_source,
                        )
                    )
                    if (
                        non_bool_integer_required
                        and not exact_integer_check
                        and not explicit_bool_rejection
                    ):
                        errors.append(
                            f"{path}:{owner}.__init__: constructor argument "
                            f"`{parameter_name}` requires a non-bool integer, but "
                            "the validation allows bool through Python's int subclass."
                        )
            owned_requirement_rows = [
                str(requirement.get("text") or "")
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, Mapping)
            ]
            requirement_text_by_method: dict[str, list[str]] = {
                name: [] for name in methods if not name.startswith("_")
            }
            active_requirement_methods: set[str] = set()
            for requirement_text in owned_requirement_rows:
                explicitly_named_methods = {
                    name
                    for name in requirement_text_by_method
                    if re.search(
                        rf"\b{re.escape(name)}\s*\(",
                        requirement_text,
                    )
                }
                if explicitly_named_methods:
                    active_requirement_methods = explicitly_named_methods
                for name in active_requirement_methods:
                    requirement_text_by_method[name].append(requirement_text)
            for method_name, method in methods.items():
                if method_name.startswith("_"):
                    continue
                method_requirement_text = " ".join(
                    requirement_text_by_method.get(method_name) or []
                )
                if not method_requirement_text:
                    continue
                if not re.search(
                    r"raises?\s+[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)?\b"
                    r"[^.;]*without\s+(?:changing|mutating|modifying)\s+(?:the\s+)?state",
                    method_requirement_text,
                    flags=re.IGNORECASE,
                ):
                    continue

                def mutates_instance_state(statement: ast.stmt) -> bool:
                    """Return whether a statement directly mutates self-owned state."""

                    for node in ast.walk(statement):
                        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
                            targets = (
                                list(node.targets)
                                if isinstance(node, ast.Assign)
                                else list(node.targets)
                                if isinstance(node, ast.Delete)
                                else [node.target]
                            )
                            if any(
                                isinstance(child, ast.Attribute)
                                and isinstance(child.value, ast.Name)
                                and child.value.id == "self"
                                or isinstance(child, ast.Subscript)
                                and isinstance(child.value, ast.Attribute)
                                and isinstance(child.value.value, ast.Name)
                                and child.value.value.id == "self"
                                for target in targets
                                for child in ast.walk(target)
                            ):
                                return True
                    return False

                statement_blocks = [method.body]
                statement_blocks.extend(
                    node.body
                    for node in ast.walk(method)
                    if isinstance(node, (ast.With, ast.AsyncWith))
                )
                has_state_mutation = any(
                    mutates_instance_state(statement)
                    for statements in statement_blocks
                    for statement in statements
                )
                has_raising_guard = False
                unsafe_guard = False
                for statements in statement_blocks:
                    for index, statement in enumerate(statements):
                        if not (
                            isinstance(statement, ast.If)
                            and any(isinstance(node, ast.Raise) for node in ast.walk(statement))
                        ):
                            continue
                        has_raising_guard = True
                        if any(mutates_instance_state(item) for item in statements[:index]):
                            unsafe_guard = True
                            break
                    if unsafe_guard:
                        break
                unsafe_guard = unsafe_guard or (
                    has_state_mutation and not has_raising_guard
                )
                if unsafe_guard:
                    errors.append(
                        f"{path}:{owner}.{method_name}: approved rejection must "
                        "leave state unchanged, but instance state is mutated before "
                        "a valid raising guard. Validate the rejection before mutation."
                    )
                if re.search(
                    r"once\s+([A-Za-z_][A-Za-z0-9_]*)\s+is\s+reached,?\s+"
                    r"another\s+[^.;]*raises?",
                    method_requirement_text,
                    flags=re.IGNORECASE,
                ):
                    next_count_names = {
                        target.id
                        for assignment in ast.walk(method)
                        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        for target in (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        if isinstance(target, ast.Name)
                        and isinstance(assignment.value, ast.BinOp)
                        and isinstance(assignment.value.op, ast.Add)
                        and isinstance(assignment.value.right, ast.Constant)
                        and assignment.value.right.value == 1
                    }
                    premature_guards = [
                        node
                        for node in ast.walk(method)
                        if isinstance(node, ast.Compare)
                        and len(node.ops) == 1
                        and isinstance(node.ops[0], ast.GtE)
                        and isinstance(node.left, ast.Name)
                        and node.left.id in next_count_names
                        and len(node.comparators) == 1
                        and isinstance(node.comparators[0], ast.Attribute)
                        and isinstance(node.comparators[0].value, ast.Name)
                        and node.comparators[0].value.id == "self"
                    ]
                    if premature_guards:
                        errors.append(
                            f"{path}:{owner}.{method_name}: limit guard is off by "
                            "one; the call that reaches the approved limit must "
                            "succeed and only the following call may raise."
                        )
            for method_name in contract.get("required_methods") or []:
                if str(method_name) not in methods:
                    errors.append(
                        f"{path}:{owner}: approved method `{method_name}` is missing."
                    )
            for property_name in contract.get("properties") or []:
                property_method = methods.get(str(property_name))
                property_decorators = {
                    ast.unparse(decorator).rsplit(".", 1)[-1]
                    for decorator in (
                        property_method.decorator_list
                        if property_method is not None
                        else []
                    )
                }
                if property_method is None:
                    continue
                if "property" not in property_decorators:
                    errors.append(
                        f"{path}:{owner}.{property_name}: approved property "
                        "must be implemented with `@property`."
                    )
            approved_fields = {
                str(field.get("name") or ""): str(field.get("type") or "")
                for field in contract.get("fields") or []
                if isinstance(field, Mapping) and str(field.get("name") or "")
            }
            actual_fields = {
                node.target.id: ast.unparse(node.annotation)
                for node in owner_node.body
                if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
            }
            for field_name, field_type in approved_fields.items():
                if field_name not in actual_fields:
                    errors.append(
                        f"{path}:{owner}: approved typed field `{field_name}: "
                        f"{field_type}` is missing."
                    )
            frozen_dataclass = any(
                isinstance(decorator, ast.Call)
                and ast.unparse(decorator.func).rsplit(".", 1)[-1] == "dataclass"
                and any(
                    keyword.arg == "frozen"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in decorator.keywords
                )
                for decorator in owner_node.decorator_list
            )
            if bool(contract.get("immutable")) and not frozen_dataclass:
                errors.append(
                    f"{path}:{owner}: immutable dataclass must use "
                    "`@dataclass(frozen=True)`."
                )
            if frozen_dataclass and any(
                isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                and any(
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                    and isinstance(child.ctx, ast.Store)
                    for child in ast.walk(node)
                )
                for method in methods.values()
                for node in ast.walk(method)
            ):
                errors.append(
                    f"{path}:{owner}: frozen dataclass mutates `self` directly."
                )
            if bool(contract.get("public_surface_locked")):
                approved_public_methods = {
                    str(method_name)
                    for method_name in contract.get("required_methods") or []
                    if str(method_name)
                    and not str(method_name).startswith("_")
                }
                approved_public_methods.update(
                    match.group(1)
                    for signature in contract.get("callable_signatures") or []
                    for match in [
                        re.match(
                            r"(?:async\s+)?def\s+"
                            r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                            str(signature).strip(),
                        )
                    ]
                    if match and not match.group(1).startswith("_")
                )
                approved_public_methods.add("__init__")
                undeclared_public_methods = sorted(
                    method_name
                    for method_name in methods
                    if not method_name.startswith("_")
                    and method_name not in approved_public_methods
                )
                if undeclared_public_methods:
                    errors.append(
                        f"{path}:{owner}: undeclared public callable(s) are "
                        "forbidden by the locked class contract: "
                        + ", ".join(undeclared_public_methods)
                        + ". Dependency callables must be invoked through their "
                        "declaring owner, not copied onto the consumer."
                    )
            reachable_methods = {"__init__"} if "__init__" in methods else set()
            pending_reachable = list(reachable_methods)
            while pending_reachable:
                method_name = pending_reachable.pop()
                method_node = methods.get(method_name)
                if method_node is None:
                    continue
                for call in ast.walk(method_node):
                    connected_handler = (
                        call.args[0].attr
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "connect"
                            and call.args
                            and isinstance(call.args[0], ast.Attribute)
                            and isinstance(call.args[0].value, ast.Name)
                            and call.args[0].value.id == "self"
                            and call.args[0].attr in methods
                        )
                        else ""
                    )
                    if (
                        connected_handler
                        and connected_handler not in reachable_methods
                    ):
                        reachable_methods.add(connected_handler)
                        pending_reachable.append(connected_handler)
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                        and call.func.attr in methods
                        and call.func.attr not in reachable_methods
                    ):
                        reachable_methods.add(call.func.attr)
                        pending_reachable.append(call.func.attr)
            is_ui_owner = bool(
                owner.endswith(
                    ("Dialog", "Window", "Widget", "Panel", "Dock")
                )
                or any(
                    token in str(contract.get("base") or "")
                    for token in ("Dialog", "Window", "Widget", "Qt")
                )
            )
            required_behavior_handlers = {
                str(task.get("name") or "")
                for task in chunk.get("method_tasks") or []
                if isinstance(task, Mapping)
                and str(task.get("name") or "") not in {"", "__init__"}
                and bool(task.get("requirement_ids"))
            } if is_ui_owner else set()
            for handler_name in sorted(
                required_behavior_handlers - reachable_methods
            ):
                errors.append(
                    f"{path}:{owner}.{handler_name}: requirement-owning UI "
                    "handler is unreachable; connect it from construction or "
                    "call it through a constructor-reachable method."
                )
            unresolved_private_calls = {
                call.func.attr
                for method in methods.values()
                for call in ast.walk(method)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
                and call.func.attr.startswith("_")
                and call.func.attr not in methods
            }
            for method_name in sorted(unresolved_private_calls):
                errors.append(
                    f"{path}:{owner}: call to unresolved private method "
                    f"`self.{method_name}()`."
                )
            for task in chunk.get("method_tasks") or []:
                if not isinstance(task, Mapping):
                    continue
                method_name = str(task.get("name") or "")
                method_node = methods.get(method_name)
                task_contract = " ".join(
                    str(value)
                    for value in [
                        *task.get("implementation_mechanics", []),
                        *task.get("validation_cases", []),
                    ]
                )
                if (
                    method_node is not None
                    and re.search(
                        r"\b(?:visible|observable)\s+(?:error|failure)\s+path\b"
                        r"|\bsurface\s+(?:errors?|failures?)\b",
                        task_contract,
                        flags=re.IGNORECASE,
                    )
                    and not any(
                        isinstance(node, ast.Try)
                        and bool(node.handlers)
                        for node in ast.walk(method_node)
                    )
                ):
                    errors.append(
                        f"{path}:{owner}.{method_name}: approved visible error "
                        "path has no executable exception handler."
                    )
            reachable_nodes = [
                methods[name]
                for name in reachable_methods
                if name in methods
            ]
            attached_widget_attributes = {
                argument.attr
                for call in ast.walk(owner_node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in {
                    "addWidget",
                    "insertWidget",
                    "setCentralWidget",
                    "setWidget",
                }
                for argument in call.args[:1]
                if isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "self"
            }
            owner_has_layout = any(
                isinstance(call, ast.Call)
                and (
                    (
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr in {
                            "setLayout",
                            "setCentralWidget",
                            "setWidget",
                        }
                    )
                    or (
                        ast.unparse(call.func).rsplit(".", 1)[-1].startswith("Q")
                        and ast.unparse(call.func).rsplit(".", 1)[-1].endswith(
                            "Layout"
                        )
                        and bool(call.args)
                    )
                )
                for call in ast.walk(owner_node)
            )
            for attribute in contract.get("attributes") or []:
                if not isinstance(attribute, Mapping):
                    continue
                attribute_name = str(attribute.get("name") or "")
                expected_type = str(attribute.get("type") or "").rsplit(".", 1)[-1]
                if not attribute_name:
                    continue
                for method_name, method_node in methods.items():
                    if method_name == "__init__":
                        continue
                    misplaced_construction = any(
                        isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        and any(
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == attribute_name
                            for target in (
                                assignment.targets
                                if isinstance(assignment, ast.Assign)
                                else [assignment.target]
                            )
                        )
                        and isinstance(assignment.value, ast.Call)
                        for assignment in ast.walk(method_node)
                    )
                    if misplaced_construction:
                        errors.append(
                            f"{path}:{owner}.{method_name}: approved UI attribute "
                            f"`{attribute_name}` is reconstructed outside "
                            "`__init__`; consume the existing widget instead."
                        )
                constructed = False
                for method_node in reachable_nodes:
                    for assignment in ast.walk(method_node):
                        value: ast.AST | None = None
                        targets: list[ast.AST] = []
                        if isinstance(assignment, ast.Assign):
                            value = assignment.value
                            targets = list(assignment.targets)
                        elif isinstance(assignment, ast.AnnAssign):
                            value = assignment.value
                            targets = [assignment.target]
                        if value is None or not any(
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == attribute_name
                            for target in targets
                        ):
                            continue
                        if not expected_type:
                            constructed = True
                            break
                        if isinstance(value, ast.Call) and (
                            (
                                expected_type == "QWidget"
                                and ast.unparse(value.func).rsplit(
                                    ".", 1
                                )[-1].startswith("Q")
                            )
                            or (
                                ast.unparse(value.func).rsplit(".", 1)[-1]
                                == expected_type
                            )
                        ):
                            constructed = True
                            break
                    if constructed:
                        break
                if bool(attribute.get("construction_required")) and not constructed:
                    errors.append(
                        f"{path}:{owner}: approved attribute `{attribute_name}` "
                        + (
                            f"must be constructed as `{expected_type}` "
                            if expected_type
                            else "must be initialized "
                        )
                        + "from `__init__` or a constructor-reachable helper."
                    )
                meaningful_widget_members = {
                    "QCheckBox": {
                        "checkState", "clicked", "isChecked", "stateChanged",
                        "toggled",
                    },
                    "QComboBox": {
                        "activated", "currentData", "currentIndex",
                        "currentIndexChanged", "currentText",
                        "currentTextChanged",
                    },
                    "QLabel": {"clear", "setPixmap", "setText", "text"},
                    "QLineEdit": {
                        "clear", "editingFinished", "setText", "text",
                        "textChanged",
                    },
                    "QListWidget": {
                        "addItem", "addItems", "clear", "currentItem",
                        "itemSelectionChanged", "selectedItems",
                    },
                    "QProgressBar": {
                        "reset", "setMaximum", "setMinimum", "setRange",
                        "setValue", "value", "valueChanged",
                    },
                    "QPushButton": {"click", "clicked", "setEnabled"},
                    "QSpinBox": {
                        "setRange", "setValue", "value", "valueChanged",
                    },
                    "QTextEdit": {
                        "append", "clear", "setPlainText", "textChanged",
                        "toPlainText",
                    },
                }
                attribute_use_members = {
                    candidate.attr
                    for candidate in ast.walk(owner_node)
                    if isinstance(candidate, ast.Attribute)
                    and expression_path(candidate).startswith(
                        f"self.{attribute_name}."
                    )
                }
                meaningful_runtime_use = bool(
                    attribute_use_members
                    & meaningful_widget_members.get(expected_type, set())
                )
                if not expected_type.startswith("Q"):
                    meaningful_runtime_use = any(
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        and node.attr == attribute_name
                        and isinstance(node.ctx, ast.Load)
                        for method in _method_map(owner_node).values()
                        if method.name != "__init__"
                        for node in ast.walk(method)
                    )
                if (
                    bool(attribute.get("runtime_use_required"))
                    and not meaningful_runtime_use
                ):
                    errors.append(
                        f"{path}:{owner}: approved attribute `{attribute_name}` "
                        "is constructed but has no meaningful runtime read, signal "
                        "wiring, or state update."
                    )
                if (
                    bool(attribute.get("construction_required"))
                    and expected_type.startswith("Q")
                    and expected_type not in {
                        "QAction",
                        "QButtonGroup",
                        "QLayout",
                        "QMenu",
                        "QShortcut",
                        "QTimer",
                    }
                    and (
                        attribute_name not in attached_widget_attributes
                        or not owner_has_layout
                    )
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        f"approved UI control `{attribute_name}` is constructed "
                        "but not attached to a constructor-reachable layout or "
                        "container, so the user cannot interact with it."
                    )
                selection_semantics = bool(
                    expected_type == "QComboBox"
                    and re.search(
                        r"\b(?:select|selection|choice|choose|mode|category)\b",
                        attribute_name.replace("_", " "),
                        flags=re.IGNORECASE,
                    )
                )
                if selection_semantics and not any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "currentData",
                        "currentIndex",
                        "currentText",
                    }
                    and isinstance(call.func.value, ast.Attribute)
                    and isinstance(call.func.value.value, ast.Name)
                    and call.func.value.value.id == "self"
                    and call.func.value.attr == attribute_name
                    for call in ast.walk(owner_node)
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        f"selection control `{attribute_name}` never reads its "
                        "current selection through currentText(), currentData(), "
                        "or currentIndex()."
                    )
            for signature in contract.get("callable_signatures") or []:
                match = re.match(
                    r"def\s+([A-Za-z_][A-Za-z0-9_]*)\((.*)\)",
                    str(signature),
                )
                if not match:
                    continue
                method = methods.get(match.group(1))
                if method is None:
                    if (
                        match.group(1) == "__init__"
                        and "dataclass" in decorators
                    ):
                        continue
                    if (
                        match.group(1) == "__init__"
                        and re.fullmatch(
                            r"def\s+__init__\(\s*self\s*\)",
                            str(signature).strip(),
                        )
                    ):
                        continue
                    errors.append(
                        f"{path}:{owner}: approved callable `{match.group(1)}` is missing."
                    )
                    continue
                try:
                    signature_tree = ast.parse(
                        str(signature).rstrip() + ":\n    pass",
                        filename="<approved-signature>",
                    )
                    signature_node = signature_tree.body[0]
                    if not isinstance(
                        signature_node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    ):
                        raise SyntaxError("approved signature is not callable")
                    expected_parameters = [
                        argument.arg
                        for argument in [
                            *signature_node.args.posonlyargs,
                            *signature_node.args.args,
                            *signature_node.args.kwonlyargs,
                        ]
                    ]
                except SyntaxError:
                    expected_parameters = [
                        value.split(":", 1)[0].split("=", 1)[0].strip()
                        for value in match.group(2).split(",")
                        if value.strip()
                    ]
                actual_parameters = [
                    argument.arg
                    for argument in [
                        *method.args.posonlyargs,
                        *method.args.args,
                        *method.args.kwonlyargs,
                    ]
                ]
                requirement_text = " ".join(
                    str(requirement.get("text") or "")
                    for requirement in chunk.get("requirements") or []
                    if isinstance(requirement, Mapping)
                )
                parameter_names_are_explicit = bool(
                    re.search(
                        rf"(?<![A-Za-z0-9_.]){re.escape(method.name)}\s*"
                        r"\([^)]*\)",
                        requirement_text,
                    )
                )
                if method.name == "__len__":
                    expected_parameters = ["self"]
                    parameter_names_are_explicit = True
                parameter_contract_failed = (
                    expected_parameters
                    != actual_parameters[:len(expected_parameters)]
                    if parameter_names_are_explicit
                    else len(actual_parameters) < len(expected_parameters)
                )
                if parameter_contract_failed:
                    errors.append(
                        f"{path}:{owner}.{method.name}: "
                        + (
                            "explicitly requested parameters "
                            f"{expected_parameters} do not match "
                            f"{actual_parameters}."
                            if parameter_names_are_explicit
                            else "inferred interface requires at least "
                            f"{len(expected_parameters)} parameters but found "
                            f"{len(actual_parameters)}."
                        )
                    )
                expected_return_match = re.search(
                    r"\)\s*->\s*(.+)$", str(signature)
                )
                if expected_return_match:
                    actual_return = (
                        ast.unparse(method.returns)
                        if method.returns is not None
                        else ""
                    )
                    expected_return = expected_return_match.group(1)
                    if (
                        "tuple" in expected_return.casefold()
                        and "..." in expected_return
                        and (
                            "tuple" not in actual_return.casefold()
                            or "..." not in actual_return
                        )
                    ):
                        errors.append(
                            f"{path}:{owner}.{method.name}: approved variable-length "
                            f"tuple return `{expected_return}` does not match "
                            f"`{actual_return or '<missing>'}`."
                        )
            owner_call_names = {
                call_name.rsplit(".", 1)[-1]
                for call_name in _call_names(owner_node)
            }
            owner_callable_names = owner_call_names | {
                node.attr
                for node in ast.walk(owner_node)
                if isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
            }
            journal_requirement_text = " ".join(
                str(requirement.get("text") or "")
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, Mapping)
            )
            if (
                "monotonically increasing" in journal_requirement_text.casefold()
                and "retain only the newest" in journal_requirement_text.casefold()
                and "without reusing sequence" in journal_requirement_text.casefold()
                and {"append", "since", "clear"}.issubset(methods)
            ):
                append_method = methods["append"]
                since_method = methods["since"]
                if "useful type hints" in journal_requirement_text.casefold():
                    append_return = (
                        ast.unparse(append_method.returns)
                        if append_method.returns is not None else ""
                    )
                    if append_return in {"", "object", "Any"}:
                        errors.append(
                            f"{path}:{owner}.append: requested useful type hints "
                            "must declare the integer sequence result as int."
                        )
                    sequence_argument = next(
                        (argument for argument in since_method.args.args
                         if argument.arg == "sequence"),
                        None,
                    )
                    sequence_hint = (
                        ast.unparse(sequence_argument.annotation)
                        if sequence_argument is not None
                        and sequence_argument.annotation is not None else ""
                    )
                    since_return = (
                        ast.unparse(since_method.returns)
                        if since_method.returns is not None else ""
                    )
                    if sequence_hint in {"", "object", "Any"} or since_return in {
                        "", "object", "Any"
                    }:
                        errors.append(
                            f"{path}:{owner}.since: requested useful type hints "
                            "must declare sequence: int and a tuple return type."
                        )
                persistent_sequence_attributes = {
                    node.attr
                    for node in ast.walk(append_method)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and isinstance(node.ctx, ast.Store)
                    and any(
                        token in node.attr.casefold()
                        for token in ("sequence", "serial", "counter", "next")
                    )
                }
                def event_tuple_expression(node: ast.AST) -> bool:
                    if isinstance(node, (ast.Tuple, ast.List)):
                        return len(node.elts) >= 3
                    return (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in {"deepcopy", "copy"}
                        and len(node.args) == 1
                        and event_tuple_expression(node.args[0])
                    )

                event_tuple_aliases = {
                    target.id
                    for node in ast.walk(append_method)
                    if isinstance(node, ast.Assign)
                    and event_tuple_expression(node.value)
                    for target in node.targets
                    if isinstance(target, ast.Name)
                }
                stores_sequence_in_events = any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"append", "appendleft", "insert"}
                    and any(
                        event_tuple_expression(argument)
                        or (
                            isinstance(argument, ast.Name)
                            and argument.id in event_tuple_aliases
                        )
                        for argument in call.args
                    )
                    for call in ast.walk(append_method)
                )
                returned_sequence_from_retention = any(
                    isinstance(node, ast.Return)
                    and any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "len"
                        for call in ast.walk(node)
                    )
                    for node in ast.walk(append_method)
                )
                derives_sequence_from_retention = (
                    returned_sequence_from_retention
                    or any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "enumerate"
                    for call in ast.walk(since_method)
                    )
                )
                append_parents = {
                    child: parent
                    for parent in ast.walk(append_method)
                    for child in ast.iter_child_nodes(parent)
                }

                def unconditional_statement(node: ast.AST) -> bool:
                    """Exclude updates nested in retention or filter branches."""

                    parent = append_parents.get(node)
                    while parent is not None and parent is not append_method:
                        if isinstance(parent, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try)):
                            return False
                        parent = append_parents.get(parent)
                    return parent is append_method

                def counter_attribute(node: ast.AST) -> bool:
                    return (
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        and node.attr in persistent_sequence_attributes
                    )

                def increment_expression(node: ast.AST) -> bool:
                    return (
                        isinstance(node, ast.BinOp)
                        and isinstance(node.op, ast.Add)
                        and counter_attribute(node.left)
                        and isinstance(node.right, ast.Constant)
                        and type(node.right.value) is int
                        and node.right.value == 1
                    )

                unconditional_aliases = {
                    target.id: node.lineno
                    for node in ast.walk(append_method)
                    if isinstance(node, ast.Assign)
                    and unconditional_statement(node)
                    and increment_expression(node.value)
                    for target in node.targets
                    if isinstance(target, ast.Name)
                }

                def unconditional_counter_increment(node: ast.AST) -> bool:
                    """Recognize direct and one-step local-alias counter updates."""

                    if not unconditional_statement(node):
                        return False
                    if isinstance(node, ast.AugAssign):
                        return (
                            counter_attribute(node.target)
                            and isinstance(node.op, ast.Add)
                            and isinstance(node.value, ast.Constant)
                            and type(node.value.value) is int
                            and node.value.value == 1
                        )
                    if not isinstance(node, ast.Assign) or not any(
                        counter_attribute(target) for target in node.targets
                    ):
                        return False
                    if increment_expression(node.value):
                        return True
                    return (
                        isinstance(node.value, ast.Name)
                        and unconditional_aliases.get(node.value.id, node.lineno) < node.lineno
                    )

                advances_every_append = any(
                    unconditional_counter_increment(node)
                    for node in ast.walk(append_method)
                )
                cursor_parameter_names = {
                    argument.arg
                    for argument in (
                        *since_method.args.posonlyargs,
                        *since_method.args.args,
                    )
                    if argument.arg not in {"self", "cls"}
                }
                slices_retention_by_cursor = any(
                    isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "self"
                    and isinstance(node.slice, ast.Slice)
                    and any(
                        isinstance(value, ast.Name)
                        and value.id in cursor_parameter_names
                        for value in ast.walk(node.slice)
                    )
                    for node in ast.walk(since_method)
                )
                if (
                    not persistent_sequence_attributes
                    or not stores_sequence_in_events
                    or derives_sequence_from_retention
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        "monotonic event identity is incorrectly coupled to the "
                        "bounded retention container. Keep a persistent sequence "
                        "counter, store each sequence with its event, and have append, "
                        "since, eviction, and clear share that representation."
                    )
                elif not advances_every_append:
                    errors.append(
                        f"{path}:{owner}.append: the persistent sequence counter "
                        "must advance by one on every append, outside retention "
                        "and topic-filter branches."
                    )
                elif slices_retention_by_cursor:
                    errors.append(
                        f"{path}:{owner}.since: cursor sequence is an event ID, "
                        "not a retained-list offset. Iterate retained events and "
                        "filter by stored ID > sequence instead of slicing the list."
                    )
                clear_method = methods["clear"]
                clears_sequence_counter = any(
                    isinstance(node, (ast.Assign, ast.AnnAssign))
                    and any(
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr in persistent_sequence_attributes
                        for target in (
                            node.targets
                            if isinstance(node, ast.Assign)
                            else [node.target]
                        )
                    )
                    for node in ast.walk(clear_method)
                )
                if clears_sequence_counter:
                    errors.append(
                        f"{path}:{owner}.clear: clear must preserve the monotonic "
                        "sequence counter so later event identifiers are never reused."
                    )
                returns_mutable_snapshot = any(
                    isinstance(node, ast.Return)
                    and isinstance(node.value, (ast.List, ast.ListComp))
                    for node in ast.walk(since_method)
                ) or any(
                    isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Name)
                    and any(
                        isinstance(binding, ast.Assign)
                        and any(
                            isinstance(target, ast.Name)
                            and target.id == node.value.id
                            for target in binding.targets
                        )
                        and isinstance(binding.value, ast.List)
                        for binding in ast.walk(since_method)
                    )
                    for node in ast.walk(since_method)
                )
                if returns_mutable_snapshot:
                    errors.append(
                        f"{path}:{owner}.since: approved immutable snapshot must "
                        "return a tuple, not a list-backed result."
                    )
                if "deep cop" in journal_requirement_text.casefold():
                    def calls_deepcopy(method: ast.AST) -> bool:
                        return any(
                            isinstance(node, ast.Call)
                            and (
                                isinstance(node.func, ast.Name)
                                and node.func.id == "deepcopy"
                                or isinstance(node.func, ast.Attribute)
                                and node.func.attr == "deepcopy"
                            )
                            for node in ast.walk(method)
                        )

                    if not calls_deepcopy(append_method):
                        errors.append(
                            f"{path}:{owner}.append: approved deep-copy boundary "
                            "must copy the mutable payload before retention."
                        )
                    if not calls_deepcopy(since_method):
                        errors.append(
                            f"{path}:{owner}.since: approved deep-copy snapshot "
                            "must detach retained payloads before returning them."
                        )
            for interface in chunk.get(
                "required_dependency_interfaces",
            ) or []:
                if not isinstance(interface, Mapping):
                    continue
                interface_match = re.search(
                    r"\bdef\s+([a-z_][A-Za-z0-9_]*)\s*\(",
                    str(interface.get("signature") or ""),
                )
                if (
                    interface_match
                    and interface_match.group(1) not in owner_callable_names
                ):
                    errors.append(
                        f"{path}:{owner}: approved dependency callable "
                        f"`{interface_match.group(1)}` is not consumed by the "
                        "consumer implementation."
                    )
            if bool(contract.get("type_hints_required")):
                annotated_fields = {
                    node.target.id
                    for node in owner_node.body
                    if isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.annotation is not None
                }
                if "dataclass" in decorators and not annotated_fields:
                    errors.append(
                        f"{path}:{owner}: typed dataclass has no annotated fields."
                    )
                for method_name in contract.get("required_methods") or []:
                    method = methods.get(str(method_name))
                    if method is None:
                        continue
                    public_args = [
                        argument
                        for argument in [
                            *method.args.posonlyargs,
                            *method.args.args,
                            *method.args.kwonlyargs,
                        ]
                        if argument.arg not in {"self", "cls"}
                    ]
                    if (
                        any(argument.annotation is None for argument in public_args)
                        or method.returns is None
                    ):
                        errors.append(
                            f"{path}:{owner}.{method_name}: typed public method "
                            "requires parameter and return annotations."
                        )

        mechanics = " ".join(
            str(step)
            for item in chunk.get("implementation_mechanics") or []
            if isinstance(item, Mapping)
            for step in item.get("steps") or []
        ).casefold()
        owner_source = ast.unparse(owner_node)
        owner_source_lower = owner_source.casefold()
        owned_requirement_text = " ".join(
            str(requirement.get("text") or "")
            for requirement in chunk.get("requirements") or []
            if isinstance(requirement, Mapping)
        )
        if isinstance(owner_node, ast.ClassDef):
            ordered_methods = _method_map(owner_node)
            if (
                "duplicate canonical names or aliases" in owned_requirement_text.casefold()
                and "permissionerror" in owned_requirement_text.casefold()
                and "sorted canonical names only" in owned_requirement_text.casefold()
            ):
                register_method = ordered_methods.get("register")
                resolve_method = ordered_methods.get("resolve")
                list_method = ordered_methods.get("list_commands")
                registry_issues: list[str] = []
                register_source = (
                    ast.unparse(register_method) if register_method is not None else ""
                )
                resolve_source = (
                    ast.unparse(resolve_method) if resolve_method is not None else ""
                )
                list_source = (
                    ast.unparse(list_method) if list_method is not None else ""
                )
                normalization_helpers = {
                    name
                    for name, method in ordered_methods.items()
                    if ".strip()" in ast.unparse(method)
                    and ".casefold()" in ast.unparse(method)
                }

                def uses_normalization_helper(node: ast.AST | None) -> bool:
                    if node is None:
                        return False
                    return any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id in {"self", "cls"}
                        and call.func.attr in normalization_helpers
                        for call in ast.walk(node)
                    )

                register_normalized = bool(
                    (
                        ".strip()" in register_source
                        and ".casefold()" in register_source
                    )
                    or uses_normalization_helper(register_method)
                )
                if not (
                    register_normalized
                    and "callable(" in register_source
                    and "ValueError" in register_source
                ):
                    registry_issues.append(
                        "register lacks complete normalized input validation"
                    )
                register_loaded_names = {
                    node.id
                    for node in ast.walk(register_method)
                    if isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                } if register_method is not None else set()
                if "capabilities" not in register_loaded_names:
                    registry_issues.append(
                        "register does not persist required capabilities"
                    )
                resolve_normalized = bool(
                    (
                        ".strip()" in resolve_source
                        and ".casefold()" in resolve_source
                    )
                    or uses_normalization_helper(resolve_method)
                )
                explicit_or_implicit_key_error = bool(
                    "KeyError" in resolve_source
                    or (
                        resolve_method is not None
                        and any(
                            isinstance(node, ast.Subscript)
                            and isinstance(node.ctx, ast.Load)
                            for node in ast.walk(resolve_method)
                        )
                    )
                )
                if not (
                    resolve_normalized
                    and explicit_or_implicit_key_error
                    and "PermissionError" in resolve_source
                    and "available_capabilities" in resolve_source
                ):
                    registry_issues.append(
                        "resolve lacks normalized alias, unknown-name, or capability handling"
                    )
                if "sorted(" not in list_source:
                    registry_issues.append(
                        "list_commands does not return sorted canonical names"
                    )
                if registry_issues:
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        "approved command-registry invariant is incomplete: "
                        + "; ".join(registry_issues)
                    )
            if (
                "expire entries lazily" in owned_requirement_text.casefold()
                and "ttl_seconds" in owned_requirement_text
            ):
                get_method = ordered_methods.get("get")
                put_method = ordered_methods.get("put")
                len_method = ordered_methods.get("__len__")

                def stored_subscript_attributes(node: ast.AST | None) -> set[str]:
                    if node is None:
                        return set()
                    return {
                        target.value.attr
                        for child in ast.walk(node)
                        for target in (
                            child.targets
                            if isinstance(child, ast.Assign)
                            else [child.target]
                            if isinstance(child, (ast.AnnAssign, ast.AugAssign))
                            else []
                        )
                        if isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and isinstance(target.value.value, ast.Name)
                        and target.value.value.id == "self"
                    }

                def removes_owned_entry(node: ast.AST | None) -> bool:
                    if node is None:
                        return False
                    return any(
                        (
                            isinstance(child, ast.Delete)
                            and any(
                                isinstance(target, ast.Subscript)
                                and isinstance(target.value, ast.Attribute)
                                and isinstance(target.value.value, ast.Name)
                                and target.value.value.id == "self"
                                for target in child.targets
                            )
                        )
                        or (
                            isinstance(child, ast.Call)
                            and isinstance(child.func, ast.Attribute)
                            and child.func.attr in {"pop", "popitem", "clear"}
                            and isinstance(child.func.value, ast.Attribute)
                            and isinstance(child.func.value.value, ast.Name)
                            and child.func.value.value.id == "self"
                        )
                        for child in ast.walk(node)
                    )

                get_stores = stored_subscript_attributes(get_method)
                put_stores = stored_subscript_attributes(put_method)
                ttl_expression_attributes = {
                    child.attr
                    for expression in (
                        node
                        for node in (
                            ast.walk(get_method) if get_method is not None else []
                        )
                        if isinstance(node, (ast.BinOp, ast.Compare))
                    )
                    for child in ast.walk(expression)
                    if isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                }
                get_calls = _call_names(get_method) if get_method is not None else set()
                refreshes_recency = bool(
                    get_stores
                    or any(
                        name.endswith(("move_to_end", "touch", "refresh_recency"))
                        for name in get_calls
                    )
                )
                if get_method is not None and not refreshes_recency:
                    errors.append(
                        f"{path}:{owner}.get: approved successful-get recency "
                        "refresh is missing."
                    )
                if (
                    get_method is not None
                    and get_stores
                    and get_stores & put_stores & ttl_expression_attributes
                ):
                    errors.append(
                        f"{path}:{owner}.get: recency refresh overwrites the "
                        "insertion timestamp used for TTL expiry."
                    )
                delegates_expiry_cleanup = any(
                    name.endswith(("._expire", ".expire", "_expire"))
                    for name in get_calls
                )
                if (
                    get_method is not None
                    and not removes_owned_entry(get_method)
                    and not delegates_expiry_cleanup
                ):
                    errors.append(
                        f"{path}:{owner}.get: approved lazy expiry removal is "
                        "missing."
                    )
                if (
                    get_method is not None
                    and "self.clock" not in ast.unparse(get_method)
                ):
                    errors.append(
                        f"{path}:{owner}.get: approved injected clock is not used."
                    )
                if len_method is not None:
                    len_source = ast.unparse(len_method)
                    len_calls = _call_names(len_method)
                    cleans_expired_length = bool(
                        removes_owned_entry(len_method)
                        or "self.clock" in len_source
                        or any(name.startswith("self._") for name in len_calls)
                    )
                    if not cleans_expired_length:
                        errors.append(
                            f"{path}:{owner}.__len__: approved live-entry expiry "
                            "cleanup is missing."
                        )
            for property_name in (
                chunk.get("declaration_contract", {}).get("properties") or []
            ):
                property_method = ordered_methods.get(str(property_name))
                property_requirement = next(
                    (
                        str(requirement.get("text") or "")
                        for requirement in chunk.get("requirements") or []
                        if isinstance(requirement, Mapping)
                        and re.search(
                            rf"\b{re.escape(str(property_name))}\b",
                            str(requirement.get("text") or ""),
                        )
                    ),
                    "",
                )
                if (
                    property_method is not None
                    and re.search(
                        r"\binsertion\s+order\b",
                        property_requirement,
                        flags=re.IGNORECASE,
                    )
                    and any(
                        isinstance(call.func, ast.Name)
                        and call.func.id == "sorted"
                        for call in ast.walk(property_method)
                        if isinstance(call, ast.Call)
                    )
                ):
                    errors.append(
                        f"{path}:{owner}.{property_name}: approved insertion-order "
                        "property sorts its result instead of preserving the "
                        "owner's insertion sequence."
                    )
            if re.search(
                r"\binsertion\s+order\b",
                owned_requirement_text,
                flags=re.IGNORECASE,
            ):
                for property_name in (
                    chunk.get("declaration_contract", {}).get("properties") or []
                ):
                    property_method = ordered_methods.get(str(property_name))
                    if property_method is not None and any(
                        isinstance(call.func, ast.Name)
                        and call.func.id == "sorted"
                        for call in ast.walk(property_method)
                        if isinstance(call, ast.Call)
                    ):
                        error = (
                            f"{path}:{owner}.{property_name}: approved "
                            "insertion-order property sorts its result instead "
                            "of preserving the owner's insertion sequence."
                        )
                        if error not in errors:
                            errors.append(error)
            for requirement in chunk.get("requirements") or []:
                if not isinstance(requirement, Mapping):
                    continue
                requirement_text = str(requirement.get("text") or "")
                replacement_match = re.search(
                    r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
                    r"[^.!?\n]{0,180}\bpreserv(?:e|es|ed|ing)\b"
                    r"[^.!?\n]{0,100}\boriginal\s+insertion\s+position\b",
                    requirement_text,
                    flags=re.IGNORECASE,
                )
                replacement_method = (
                    ordered_methods.get(replacement_match.group(1))
                    if replacement_match
                    else None
                )
                if replacement_method is not None and any(
                    isinstance(node, ast.Delete)
                    or (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"pop", "popitem"}
                    )
                    for node in ast.walk(replacement_method)
                ):
                    errors.append(
                        f"{path}:{owner}.{replacement_match.group(1)}: approved "
                        "replacement-position contract deletes or pops mapping "
                        "entries. Replace an existing key in place and preserve "
                        "all unrelated entries."
                    )
                if replacement_method is not None:
                    method_parameters = [
                        argument.arg
                        for argument in (
                            *replacement_method.args.posonlyargs,
                            *replacement_method.args.args,
                        )
                        if argument.arg not in {"self", "cls"}
                    ]
                    requested_key = (
                        method_parameters[0] if method_parameters else ""
                    )
                    wrong_assignment_keys = {
                        ast.unparse(target.slice)
                        for assignment in ast.walk(replacement_method)
                        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        for target in (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        if isinstance(target, ast.Subscript)
                        and isinstance(target.ctx, ast.Store)
                        and ast.unparse(target.slice) != requested_key
                    }
                    if wrong_assignment_keys:
                        errors.append(
                            f"{path}:{owner}.{replacement_match.group(1)}: "
                            "approved replacement-position contract assigns "
                            "through a different key expression ("
                            + ", ".join(sorted(wrong_assignment_keys))
                            + f") instead of the requested `{requested_key}` key."
                        )
        forbids_sleeping = bool(re.search(
            r"\bwithout\s+sleep(?:ing)?\b|\bdo\s+not\s+sleep\b"
            r"|\bnever\s+sleep\b|\bmutable\s+fake\s+clock\b",
            owned_requirement_text,
            flags=re.IGNORECASE,
        ))
        if forbids_sleeping:
            sleeping_calls = [
                ast.unparse(call.func)
                for call in ast.walk(owner_node)
                if isinstance(call, ast.Call)
                and (
                    isinstance(call.func, ast.Name)
                    and call.func.id == "sleep"
                    or isinstance(call.func, ast.Attribute)
                    and call.func.attr == "sleep"
                )
            ]
            if sleeping_calls:
                errors.append(
                    f"{path}:{owner}: approved deterministic timing contract "
                    "forbids sleeping; advance the injected or fake clock instead."
                )
        if (
            "monotonic-clock deadline" in mechanics
            or "time.monotonic()" in mechanics
            or "injected monotonic" in mechanics
        ):
            file_source_lower = source_by_path.get(path, "").casefold()
            if "monotonic" not in file_source_lower:
                errors.append(
                    f"{path}:{owner}: approved monotonic TTL deadline is not implemented."
                )
            if isinstance(owner_node, ast.ClassDef):
                methods = _method_map(owner_node)
                initializer = methods.get("__init__")
                injected_clock_attrs: set[str] = set()
                if initializer is not None:
                    callable_parameters = {
                        argument.arg
                        for argument in (
                            *initializer.args.posonlyargs,
                            *initializer.args.args,
                            *initializer.args.kwonlyargs,
                        )
                        if argument.arg not in {"self", "cls"}
                    }
                    for assignment in ast.walk(initializer):
                        if not isinstance(assignment, ast.Assign):
                            continue
                        if not isinstance(assignment.value, ast.Name):
                            continue
                        if assignment.value.id not in callable_parameters:
                            continue
                        for target in assignment.targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and any(
                                    token in target.attr.casefold()
                                    for token in ("clock", "time_source", "monotonic")
                                )
                            ):
                                injected_clock_attrs.add(target.attr)
                injected_clock_required = (
                    "injected monotonic" in mechanics
                    or "stored injected" in mechanics
                )
                if injected_clock_required and re.search(
                    r"\btime\.(?:monotonic|time)\s*\(",
                    owner_source,
                ):
                    errors.append(
                        f"{path}:{owner}: injected clock is bypassed by a direct "
                        "host-clock call."
                    )
                helper_methods = {
                    name: method
                    for name, method in methods.items()
                    if name.startswith("_") and name != "__init__"
                }
                for method_name in ("put", "get", "keys"):
                    method = methods.get(method_name)
                    if method is None:
                        continue
                    method_text = ast.unparse(method).casefold()
                    called_helpers = [
                        helper_methods[call_name.rsplit(".", 1)[-1]]
                        for call_name in _call_names(method)
                        if call_name.rsplit(".", 1)[-1] in helper_methods
                    ]
                    helper_text = " ".join(
                        ast.unparse(helper).casefold()
                        for helper in called_helpers
                    )
                    combined_method_text = f"{method_text} {helper_text}"
                    expiry_markers = (
                        marker in combined_method_text
                        for marker in ("monotonic", "expire", "purge", "deadline")
                    )
                    if not any(expiry_markers):
                        errors.append(
                            f"{path}:{owner}.{method_name}: approved TTL expiry "
                            "path is missing."
                        )
                    if injected_clock_required and injected_clock_attrs and not any(
                        f"self.{attribute}" in combined_method_text
                        for attribute in injected_clock_attrs
                    ):
                        errors.append(
                            f"{path}:{owner}.{method_name}: expiry logic does not use "
                            "the stored injected clock."
                        )
                    call_names = _call_names(method)
                    if (
                        method_name == "put"
                        and "insertion order" in mechanics
                        and any(
                            call_name.rsplit(".", 1)[-1] in methods
                            and any(
                                marker in call_name.casefold()
                                for marker in ("remove", "delete", "discard")
                            )
                            for call_name in call_names
                        )
                        and any(
                            call_name.endswith(".append")
                            for call_name in call_names
                        )
                    ):
                        errors.append(
                            f"{path}:{owner}.{method_name}: updating an existing "
                            "key removes and appends it, which changes insertion "
                            "order. Replace the stored value and expiration in place "
                            "for existing keys, and append to the ordering collection "
                            "only when the key is new."
                        )
                    removes_expired = (
                        ".pop(" in combined_method_text
                        or "del " in combined_method_text
                        or any(
                            any(
                                marker in call_name.casefold()
                                for marker in (
                                    "cleanup",
                                    "purge",
                                    "evict",
                                    "expire",
                                    "remove",
                                )
                            )
                            for call_name in call_names
                            if call_name.rsplit(".", 1)[-1] in methods
                        )
                    )
                    if method_name in {"get", "keys"} and not removes_expired:
                        if method_name == "get":
                            errors.append(
                                f"{path}:{owner}.{method_name}: an expired requested "
                                "key is not lazily removed. Remove that key through an "
                                "already-declared removal method, or delete it directly "
                                "from every synchronized backing collection, then return "
                                "the missing-value result; do not call an undeclared "
                                "cleanup helper."
                            )
                        else:
                            errors.append(
                                f"{path}:{owner}.{method_name}: expired keys are filtered "
                                "but not lazily removed. Iterate over a stable snapshot, "
                                "remove every expired key from all synchronized backing "
                                "collections through declared behavior, and yield only "
                                "live keys in their original order."
                            )
                    if method_name == "keys":
                        for loop in [
                            node
                            for node in ast.walk(method)
                            if isinstance(node, (ast.For, ast.AsyncFor))
                            and isinstance(node.iter, ast.Attribute)
                            and isinstance(node.iter.value, ast.Name)
                            and node.iter.value.id == "self"
                        ]:
                            iterated_attribute = loop.iter.attr
                            mutates_iterated_attribute = any(
                                isinstance(node, ast.Call)
                                and isinstance(node.func, ast.Attribute)
                                and node.func.attr in {"remove", "pop", "clear"}
                                and isinstance(node.func.value, ast.Attribute)
                                and isinstance(node.func.value.value, ast.Name)
                                and node.func.value.value.id == "self"
                                and node.func.value.attr == iterated_attribute
                                for node in ast.walk(loop)
                            )
                            if mutates_iterated_attribute:
                                errors.append(
                                    f"{path}:{owner}.{method_name}: mutates the "
                                    f"insertion-order collection self."
                                    f"{iterated_attribute} while iterating it; iterate "
                                    "over a stable snapshot before removing expired "
                                    "entries."
                                )
        if "synchronization primitive" in mechanics and isinstance(
            owner_node, ast.ClassDef
        ):
            methods = _method_map(owner_node)
            if not any(
                isinstance(node, (ast.With, ast.AsyncWith))
                for method in methods.values()
                for node in ast.walk(method)
            ):
                errors.append(
                    f"{path}:{owner}: approved synchronization boundary is missing."
                )
            locking_methods = {
                name
                for name, method in methods.items()
                if any(
                    isinstance(node, (ast.With, ast.AsyncWith))
                    for node in ast.walk(method)
                )
            }
            owner_calls = {
                method_name: {
                    call_name.split(".", 1)[1]
                    for call_name in _call_names(method)
                    if call_name.startswith("self.")
                    and "." not in call_name[len("self."):]
                }
                for method_name, method in methods.items()
            }
            uses_reentrant_lock = "rlock" in owner_source_lower
            for method_name in locking_methods:
                nested_lock_calls = (
                    owner_calls.get(method_name, set()) & locking_methods
                )
                if nested_lock_calls and not uses_reentrant_lock:
                    errors.append(
                        f"{path}:{owner}.{method_name}: calls lock-owning method(s) "
                        f"{sorted(nested_lock_calls)} while holding a non-reentrant lock."
                    )
        if "1000 millisecond interval" in mechanics:
            if "1000" not in owner_source or not any(
                name.endswith((".start", ".setInterval"))
                for name in _call_names(owner_node)
            ):
                errors.append(
                    f"{path}:{owner}: approved 1000ms timer is not configured."
                )
        if "dependency clear operation first" in mechanics and isinstance(
            owner_node, ast.ClassDef
        ):
            ordered_calls = [
                name
                for method in _method_map(owner_node).values()
                for name in _call_names(method)
            ]
            clear_index = next(
                (index for index, name in enumerate(ordered_calls) if name.endswith(".clear")),
                -1,
            )
            refresh_index = next(
                (
                    index
                    for index, name in enumerate(ordered_calls)
                    if name == "self.refresh"
                ),
                -1,
            )
            if clear_index < 0 or refresh_index <= clear_index:
                errors.append(
                    f"{path}:{owner}: approved clear-then-refresh call order is missing."
                )
        if "qapplication entry point" in mechanics:
            has_guard = any(
                isinstance(node, ast.If)
                and "__name__" in ast.unparse(node.test)
                and "__main__" in ast.unparse(node.test)
                for node in tree.body
            )
            if not has_guard or ".show" not in ast.unparse(tree):
                errors.append(
                    f"{path}:<module>: approved QApplication entry point is missing."
                )
        if (
            str(chunk.get("kind") or "") == "module"
            and "mutable fake injected clock/time source" in mechanics
        ):
            module_source = source_by_path.get(path, "")
            has_sleep = bool(
                re.search(r"\b(?:time\.)?sleep\s*\(", module_source)
            )
            has_host_clock = bool(
                re.search(r"\btime\.(?:monotonic|time)\s*\(", module_source)
            )
            if has_sleep or has_host_clock:
                entry_symbol = "<module>"
                try:
                    module_tree = ast.parse(module_source, filename=path)
                except SyntaxError:
                    module_tree = None
                if module_tree is not None:
                    for statement in module_tree.body:
                        if not isinstance(statement, ast.If):
                            continue
                        if "__main__" not in ast.unparse(statement.test):
                            continue
                        called_names = [
                            node.func.id
                            for node in ast.walk(statement)
                            if isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                        ]
                        if len(called_names) == 1:
                            entry_symbol = called_names[0]
                            break
            if has_sleep:
                errors.append(
                    f"{path}:{entry_symbol}: runnable example sleeps to demonstrate a "
                    "time-dependent state change. Repair the owned entry callable by "
                    "advancing its mutable local fake-time state synchronously; do not "
                    "sleep."
                )
            if has_host_clock:
                errors.append(
                    f"{path}:{entry_symbol}: runnable example reads a direct host clock "
                    "instead of its injected fake time source. Repair the owned entry "
                    "callable by storing time in a built-in mutable local container and "
                    "injecting a nested callable that reads only that container; advance "
                    "the container directly, do not introduce a local class, and do not "
                    "import or read a host clock."
                )
    return list(dict.fromkeys(errors))
