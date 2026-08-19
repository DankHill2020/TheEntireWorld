"""Behavior-harness repair helpers for project-edit workflows."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from tech_connector.services.project_edit_agent_service import (
    apply_project_edit_generated_symbol_repair,
)

def _behavior_harness_production_targets(
    implementation_plan: dict[str, Any],
    errors: list[str],
) -> list[dict[str, str]]:
    """Map disposable behavior-ID test failures to approved production owners."""

    diagnostics = "\n".join(str(error) for error in errors)
    requirement_ids = {
        match.upper()
        for match in re.findall(
            r"\btest_[A-Za-z0-9_]*?(r[0-9]+)_(?:b|v)[0-9]+\b",
            diagnostics,
            flags=re.IGNORECASE,
        )
    }
    targets: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, dict) or str(chunk.get("kind") or "") == "module":
            continue
        owned_ids = {
            str(requirement.get("id") or "").upper()
            for requirement in chunk.get("requirements") or []
            if isinstance(requirement, dict)
        }
        if not requirement_ids.intersection(owned_ids):
            continue
        key = (
            str(chunk.get("path") or ""),
            str(chunk.get("owner") or ""),
        )
        if not all(key) or key in seen:
            continue
        seen.add(key)
        targets.append({"path": key[0], "symbol": key[1]})
    if not targets:
        approved_callable_owners = list({
            (
                str(chunk.get("path") or ""),
                str(chunk.get("owner") or ""),
            )
            for chunk in implementation_plan.get("chunks") or []
            if isinstance(chunk, dict)
            and str(chunk.get("kind") or "") in {"class", "function"}
            and str(chunk.get("path") or "")
            and str(chunk.get("owner") or "")
        })
        if len(approved_callable_owners) == 1:
            path, symbol = approved_callable_owners[0]
            targets.append({"path": path, "symbol": symbol})
    return targets


def _repair_dropped_partial_iterable_result(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Yield a proven non-empty partial accumulator before iterator termination."""

    diagnostics = "\n".join(str(error) for error in errors)
    if not re.search(
        r"Second list contains .* additional elements?"
        r"|First extra element",
        diagnostics,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        return generated_files, []

    updated_files: list[tuple[str, str, str]] = []
    repairs: list[str] = []
    for path, original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            updated_files.append((path, original, source))
            continue
        replacements: list[tuple[int, int, str, str]] = []
        for function_node in [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            function_changed = False
            for while_node in [
                node for node in ast.walk(function_node) if isinstance(node, ast.While)
            ]:
                empty_list_names = {
                    target.id
                    for statement in while_node.body
                    if isinstance(statement, (ast.Assign, ast.AnnAssign))
                    for target in (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                    if isinstance(target, ast.Name)
                    and isinstance(statement.value, ast.List)
                    and not statement.value.elts
                }
                for try_node in [
                    statement
                    for statement in while_node.body
                    if isinstance(statement, ast.Try)
                ]:
                    appended_names = {
                        call.func.value.id
                        for call in ast.walk(try_node)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "append"
                        and isinstance(call.func.value, ast.Name)
                    }
                    yielded_names = {
                        yielded.value.id
                        for yielded in ast.walk(try_node)
                        if isinstance(yielded, ast.Yield)
                        and isinstance(yielded.value, ast.Name)
                    }
                    accumulator_names = (
                        empty_list_names & appended_names & yielded_names
                    )
                    if len(accumulator_names) != 1:
                        continue
                    accumulator_name = next(iter(accumulator_names))
                    for handler in try_node.handlers:
                        if not (
                            isinstance(handler.type, ast.Name)
                            and handler.type.id == "StopIteration"
                        ):
                            continue
                        if any(
                            isinstance(node, ast.Yield)
                            and isinstance(node.value, ast.Name)
                            and node.value.id == accumulator_name
                            for node in ast.walk(handler)
                        ):
                            continue
                        break_index = next(
                            (
                                index
                                for index, statement in enumerate(handler.body)
                                if isinstance(statement, ast.Break)
                            ),
                            -1,
                        )
                        if break_index < 0:
                            continue
                        conditional_yield = ast.If(
                            test=ast.Name(
                                id=accumulator_name,
                                ctx=ast.Load(),
                            ),
                            body=[
                                ast.Expr(
                                    value=ast.Yield(
                                        value=ast.Name(
                                            id=accumulator_name,
                                            ctx=ast.Load(),
                                        )
                                    )
                                )
                            ],
                            orelse=[],
                        )
                        ast.copy_location(
                            conditional_yield,
                            handler.body[break_index],
                        )
                        handler.body.insert(break_index, conditional_yield)
                        function_changed = True
            if function_changed:
                ast.fix_missing_locations(function_node)
                replacements.append((
                    int(function_node.lineno) - 1,
                    int(function_node.end_lineno or function_node.lineno),
                    ast.unparse(function_node) + "\n",
                    function_node.name,
                ))
        if not replacements:
            updated_files.append((path, original, source))
            continue
        lines = source.splitlines(keepends=True)
        for start, end, replacement, symbol in sorted(
            replacements,
            reverse=True,
        ):
            lines[start:end] = [replacement]
            repairs.append(
                f"{Path(path).name}:{symbol} now emits its proven partial "
                "accumulator before iterator termination."
            )
        updated_files.append((path, original, "".join(lines)))
    return updated_files, repairs


def _runtime_deepest_frame_is_test(errors: list[str]) -> bool:
    """Return whether runtime exceptions originate in generated test bodies."""

    deepest_frames: list[tuple[str, str]] = []
    for error in errors:
        if "Disposable generated-patch validation failed:" not in str(error):
            continue
        for _test_name, block in re.findall(
            r"(?ms)^(?:ERROR|FAIL):\s+(test_[A-Za-z0-9_]+)[^\n]*\n"
            r"-+\n(.*?)(?=^={5,}\s*$|\Z)",
            str(error),
        ):
            frames = re.findall(
                r'File "([^"]+)", line \d+, in ([A-Za-z_][A-Za-z0-9_]*)',
                block,
            )
            if frames:
                deepest_frames.append(frames[-1])
    return bool(deepest_frames) and any(
        Path(path).name.startswith("test_") or callable_name.startswith("test_")
        for path, callable_name in deepest_frames
    )


def _repair_unrequested_exception_message_assertion(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], str]:
    """Replace invented exact exception text with the requested type proof."""

    if "AssertionError" not in "\n".join(str(error) for error in errors):
        return generated_files, ""
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for function in [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            changed = False
            for handler in [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.ExceptHandler)
                and isinstance(node.type, ast.Name)
                and isinstance(node.name, str)
            ]:
                exception_name = handler.type.id
                variable_name = handler.name
                retained: list[ast.stmt] = []
                for statement in handler.body:
                    compares_exact_message = (
                        isinstance(statement, ast.Assert)
                        and isinstance(statement.test, ast.Compare)
                        and any(
                            isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                            and node.func.id == "str"
                            and len(node.args) == 1
                            and isinstance(node.args[0], ast.Name)
                            and node.args[0].id == variable_name
                            for node in ast.walk(statement.test)
                        )
                        and any(
                            isinstance(node, ast.Constant)
                            and isinstance(node.value, str)
                            and node.value
                            and node.value not in request_prompt
                            for node in ast.walk(statement.test)
                        )
                    )
                    if not compares_exact_message:
                        retained.append(statement)
                        continue
                    retained.extend(ast.parse(
                        f"assert isinstance({variable_name}, {exception_name})"
                    ).body)
                    changed = True
                handler.body = retained
            if not changed:
                continue
            ast.fix_missing_locations(function)
            updated, splice_errors = apply_project_edit_generated_symbol_repair(
                generated_files,
                path=path,
                symbol=function.name,
                replacement_response=ast.unparse(function),
                forbidden_names=[],
            )
            if not splice_errors and updated != generated_files:
                return (
                    updated,
                    f"{Path(path).name}:{function.name} replaced an invented "
                    "exception-message literal with the caught exception type",
                )
    return generated_files, ""


def _repair_orphaned_result_expectations(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], str]:
    """Remove result assertions whose expected literal has no valid setup."""

    diagnostics = "\n".join(str(error) for error in errors)
    frames = re.findall(
        r'File "([^"]+)", line (\d+), in ([A-Za-z_][A-Za-z0-9_]*)',
        diagnostics,
    )
    if "AssertionError" not in diagnostics or not frames:
        return generated_files, ""
    failure_path, failure_line_text, function_name = frames[-1]
    if (
        function_name in {"run_self_test", "self_test"}
        or function_name.startswith("test_")
        or Path(failure_path).name.startswith("test_")
    ):
        return generated_files, ""
    failure_line = int(failure_line_text)
    for path, _original, source in generated_files:
        if Path(path).name.casefold() != Path(failure_path).name.casefold():
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        function = next(
            (
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == function_name
            ),
            None,
        )
        if function is None:
            continue
        failing_index = next(
            (
                index
                for index, statement in enumerate(function.body)
                if isinstance(statement, ast.Assert)
                and statement.lineno <= failure_line
                <= getattr(statement, "end_lineno", statement.lineno)
            ),
            None,
        )
        if failing_index is None:
            continue
        result_names = {
            node.id
            for node in ast.walk(function.body[failing_index])
            if isinstance(node, ast.Name)
        }
        result_assignment = next(
            (
                statement
                for statement in reversed(function.body[:failing_index])
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id in result_names
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and isinstance(statement.value.func.value, ast.Name)
            ),
            None,
        )
        if result_assignment is None:
            continue
        result_name = result_assignment.targets[0].id
        receiver_name = result_assignment.value.func.value.id
        assertion_group: list[ast.Assert] = []
        for statement in function.body[failing_index:]:
            if not isinstance(statement, ast.Assert) or not any(
                isinstance(node, ast.Name) and node.id == result_name
                for node in ast.walk(statement)
            ):
                break
            assertion_group.append(statement)
        expected_literals = {
            node.value
            for assertion in assertion_group
            for node in ast.walk(assertion)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, (str, bytes))
        }
        if not expected_literals:
            continue
        configured_literals: set[Any] = set()
        for statement in function.body[:failing_index]:
            for call in ast.walk(statement):
                if (
                    not isinstance(call, ast.Call)
                    or not isinstance(call.func, ast.Attribute)
                    or not isinstance(call.func.value, ast.Name)
                    or call.func.value.id != receiver_name
                    or not call.args
                    or not isinstance(call.args[0], ast.Constant)
                ):
                    continue
                numeric_arguments: list[int | float] = []
                for argument in call.args[1:]:
                    try:
                        literal_value = ast.literal_eval(argument)
                    except (TypeError, ValueError):
                        continue
                    if (
                        isinstance(literal_value, (int, float))
                        and not isinstance(literal_value, bool)
                    ):
                        numeric_arguments.append(literal_value)
                if numeric_arguments and any(
                    value < 0 for value in numeric_arguments
                ):
                    continue
                configured_literals.add(call.args[0].value)
        missing_literals = expected_literals - configured_literals
        if not missing_literals:
            continue
        group_ids = {id(statement) for statement in assertion_group}
        function.body = [
            statement
            for statement in function.body
            if id(statement) not in group_ids
        ]
        ast.fix_missing_locations(function)
        updated, splice_errors = apply_project_edit_generated_symbol_repair(
            generated_files,
            path=path,
            symbol=function.name,
            replacement_response=ast.unparse(function),
            forbidden_names=[],
        )
        if not splice_errors and updated != generated_files:
            return (
                updated,
                f"{Path(path).name}:{function.name} removed orphaned "
                f"{result_name} expectations for "
                + ", ".join(repr(value) for value in sorted(missing_literals)),
            )
    return generated_files, ""
