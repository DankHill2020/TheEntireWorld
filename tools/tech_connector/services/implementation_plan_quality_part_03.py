"""Dependency-ordered implementation-plan quality functions."""
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


def _verification_proof_gaps(
    node: ast.AST,
    clauses: list[str],
) -> list[str]:
    source = ast.unparse(node).casefold()
    calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
    assertions = [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Assert)
        or (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr.startswith("assert")
        )
    ]
    prefix_snapshots: set[str] = set()
    for statement in ast.walk(node):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        value = statement.value
        is_prefix_snapshot = (
            isinstance(value, ast.Attribute)
            and value.attr == "prefixes"
        ) or (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "tuple"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Attribute)
            and value.args[0].attr == "prefixes"
        )
        if not is_prefix_snapshot:
            continue
        for target in (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        ):
            if isinstance(target, ast.Name):
                prefix_snapshots.add(target.id)
    assertion_text = "\n".join(ast.unparse(item) for item in assertions)
    has_snapshot_assertion = any(
        re.search(rf"\b{re.escape(name)}\b", assertion_text)
        for name in prefix_snapshots
    )
    has_mutation_call = any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr
        in {"add", "append", "clear", "delete", "discard", "pop", "remove", "update"}
        for call in calls
    )
    mapping_assignments = [
        (target.id, statement.lineno)
        for statement in ast.walk(node)
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        and isinstance(statement.value, (ast.Dict, ast.Call))
        for target in (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        if isinstance(target, ast.Name)
    ]
    defensively_exercised = False
    for variable, assigned_line in mapping_assignments:
        passed_line = min(
            (
                call.lineno
                for call in calls
                if call.lineno > assigned_line
                if any(
                    isinstance(argument, ast.Name)
                    and argument.id == variable
                    for argument in call.args
                )
            ),
            default=0,
        )
        mutated_after_pass = any(
            getattr(child, "lineno", 0) > passed_line > assigned_line
            and (
                (
                        isinstance(child, ast.Subscript)
                        and isinstance(child.ctx, (ast.Store, ast.Del))
                    and isinstance(child.value, ast.Name)
                    and child.value.id == variable
                )
                or (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == variable
                    and child.func.attr
                    in {"append", "clear", "pop", "remove", "setdefault", "update"}
                )
            )
            for child in ast.walk(node)
        )
        if passed_line and mutated_after_pass and assertions:
            defensively_exercised = True
            break
    exception_names = {
        ast.unparse(child.type).rsplit(".", 1)[-1]
        for child in ast.walk(node)
        if isinstance(child, ast.ExceptHandler) and child.type is not None
    }
    exception_names.update(
        ast.unparse(argument).rsplit(".", 1)[-1]
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr in {"assertRaises", "assertRaisesRegex"}
        for argument in call.args[:1]
    )
    resolve_calls = [
        ast.dump(call, include_attributes=False)
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "resolve"
    ]
    repeated_resolve = any(
        resolve_calls.count(call_dump) > 1
        for call_dump in set(resolve_calls)
    )
    observable_calls = [
        ast.dump(call, include_attributes=False)
        for call in calls
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr.startswith("assert")
        )
    ]
    repeated_observable_call = any(
        observable_calls.count(call_dump) > 1
        for call_dump in set(observable_calls)
    )
    overlapping_literal_routes = any(
        any(
            left != right and (left.startswith(right) or right.startswith(left))
            for left in keys
            for right in keys
        )
        for call in calls
        for argument in call.args[:1]
        if isinstance(argument, ast.Dict)
        for keys in [[
            key.value
            for key in argument.keys
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
        ]]
    )
    remove_assertions = [
        item
        for item in assertions
        if ".remove(" in ast.unparse(item)
    ]
    has_false_remove_proof = any(
        isinstance(item, ast.Assert)
        and isinstance(item.test, ast.UnaryOp)
        and isinstance(item.test.op, ast.Not)
        or (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "assertFalse"
        )
        for item in remove_assertions
    )
    exact_checks = {
        "defensive copying": defensively_exercised,
        "validation": "ValueError" in exception_names,
        "replacement ordering": (
            bool(prefix_snapshots)
            and has_snapshot_assertion
            and ".add(" in source
        ),
        "longest-prefix selection": (
            overlapping_literal_routes and bool(resolve_calls) and bool(assertions)
        ),
        "tie stability": (
            bool(prefix_snapshots)
            and has_snapshot_assertion
            and ".add(" in source
        ),
        "missing-route rejection": "KeyError" in exception_names,
        "immutable detached prefixes": (
            bool(prefix_snapshots)
            and has_snapshot_assertion
            and has_mutation_call
        ),
        "remove results": (
            len(remove_assertions) >= 2 and has_false_remove_proof
        ),
        "clear behavior": ".clear(" in source and "()" in assertion_text,
        "repeatable resolution without state mutation": (
            repeated_resolve
            and bool(prefix_snapshots)
            and has_snapshot_assertion
        ),
    }
    gaps: list[str] = []
    for clause in clauses:
        normalized_clause = clause.casefold()
        if (
            re.search(
                r"\b(?:repeat(?:able|ed|ability)?|same\s+input|"
                r"without\s+(?:shared\s+)?state|stateless)\b",
                normalized_clause,
            )
            and not (repeated_observable_call and bool(assertions))
        ):
            gaps.append(clause)
            continue
        if (
            normalized_clause in exact_checks
            and not exact_checks[normalized_clause]
        ):
            gaps.append(clause)
    return gaps


def _final_value_guard_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Find guards that validate a value before a reducing return transform."""

    gaps: list[str] = []
    for index, statement in enumerate(node.body):
        if not isinstance(statement, ast.If):
            continue
        guarded_name = ""
        if (
            isinstance(statement.test, ast.UnaryOp)
            and isinstance(statement.test.op, ast.Not)
            and isinstance(statement.test.operand, ast.Name)
        ):
            guarded_name = statement.test.operand.id
        if not guarded_name or not any(
            isinstance(child, ast.Raise) for child in ast.walk(statement)
        ):
            continue
        for later in node.body[index + 1:]:
            if not isinstance(later, ast.Return):
                continue
            value = later.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr in {"strip", "lstrip", "rstrip"}
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == guarded_name
            ):
                continue
            gaps.append(
                f"`{guarded_name}` is validated before the final "
                f"`{value.func.attr}()` transformation. Assign the transformed "
                "value first, validate that exact final value, and return it."
            )
    return gaps


def _regex_requirement_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    requirement_text: str,
) -> list[str]:
    """Validate regex shape only when the approved requirement defines it."""

    normalized_requirement = requirement_text.casefold()
    if not (
        "non-alphanumeric" in normalized_requirement
        and re.search(r"\b(?:each|every)\s+run\b", normalized_requirement)
    ):
        return []
    gaps: list[str] = []
    for call in ast.walk(node):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "sub"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        ):
            continue
        pattern = call.args[0].value
        negated_class = re.search(r"\[\^([^\]]*)\]", pattern)
        preserved = negated_class.group(1) if negated_class else ""
        if (
            r"\W" in pattern
            or r"\w" in preserved
            or r"\s" in preserved
            or "_" in preserved
        ):
            gaps.append(
                f"regex pattern {pattern!r} preserves whitespace or underscore, "
                "which are non-alphanumeric under the approved requirement"
            )
        if re.search(
            r"(?:\[\^[^\]]+\]|\\W)(?:\+|\{1(?:,\d*)?\})",
            pattern,
        ) is None:
            gaps.append(
                f"regex pattern {pattern!r} does not consume a complete run in "
                "one substitution"
            )
    return gaps


def _boundary_trim_requirement_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    requirement_text: str,
) -> list[str]:
    """Require an explicitly requested delimiter trim after normalization."""

    normalized_requirement = requirement_text.casefold()
    if not re.search(
        r"\bremov(?:e|es|ing)\s+leading\s+and\s+trailing\s+hyphens?\b",
        normalized_requirement,
    ):
        return []
    substitution_lines = [
        int(call.lineno)
        for call in ast.walk(node)
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "sub"
        )
    ]
    trim_lines = [
        int(call.lineno)
        for call in ast.walk(node)
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "strip"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "-"
        )
    ]
    if not trim_lines:
        return [
            "the callable never applies `.strip('-')` to remove the requested "
            "leading and trailing hyphens"
        ]
    if substitution_lines and max(trim_lines) < min(substitution_lines):
        return [
            "hyphen trimming occurs before normalization can introduce boundary "
            "hyphens; trim the normalized result instead"
        ]
    return []


def _discarded_pure_transform_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Reject ignored return values from known immutable Python transforms."""

    string_names = {
        argument.arg
        for argument in (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        )
        if (
            isinstance(argument.annotation, ast.Name)
            and argument.annotation.id == "str"
        )
        or (
            isinstance(argument.annotation, ast.Constant)
            and argument.annotation.value == "str"
        )
    }
    immutable_string_methods = {
        "capitalize",
        "casefold",
        "center",
        "expandtabs",
        "format",
        "format_map",
        "join",
        "lower",
        "lstrip",
        "removeprefix",
        "removesuffix",
        "replace",
        "rjust",
        "rstrip",
        "strip",
        "swapcase",
        "title",
        "translate",
        "upper",
        "zfill",
    }
    gaps: list[str] = []
    for statement in ast.walk(node):
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
        ):
            continue
        call = statement.value
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in string_names
            and call.func.attr in immutable_string_methods
        ):
            gaps.append(
                f"result of immutable string transform "
                f"`{ast.unparse(call)}` is discarded"
            )
            continue
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "re"
            and call.func.attr in {"sub", "subn"}
        ):
            gaps.append(
                f"result of pure regular-expression transform "
                f"`{ast.unparse(call)}` is discarded"
            )
    return gaps
