"""Worker lifecycle and UI dispatch repairs for project-edit synthesis."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def _repair_required_finally_cleanup(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """
        Wraps proven spawned-resource work in requested finally cleanup.
    :param generated_files: generated path, original source, and candidate source rows
    :param errors: validation errors describing required cleanup
    :return: updated generated files and repair notes
    """
    targets: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*): "
        r"requested always-on lifecycle cleanup must execute"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.add((str(Path(match.group("path")).resolve()), match.group("owner")))
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        owners = {
            owner for target_path, owner in targets
            if target_path == str(Path(path).resolve())
        }
        if not owners:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for function in tree.body:
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if function.name not in owners:
                continue
            spawn_index = -1
            resource_name = ""
            subsystem_name = ""
            for statement_index, statement in enumerate(function.body):
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                value = statement.value
                targets_to_check = (
                    statement.targets if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
                    continue
                if value.func.attr != "spawn_actor_from_class":
                    continue
                target = next(
                    (item for item in targets_to_check if isinstance(item, ast.Name)),
                    None,
                )
                if target is None or not isinstance(value.func.value, ast.Name):
                    continue
                spawn_index = statement_index
                resource_name = target.id
                subsystem_name = value.func.value.id
                break
            if spawn_index < 0 or not resource_name or not subsystem_name:
                continue
            trailing = function.body[spawn_index + 1:]
            if not trailing or any(isinstance(node, ast.Try) and node.finalbody for node in trailing):
                continue
            cleanup_call = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id=subsystem_name, ctx=ast.Load()),
                        attr="destroy_actor",
                        ctx=ast.Load(),
                    ),
                    args=[ast.Name(id=resource_name, ctx=ast.Load())],
                    keywords=[],
                )
            )
            cleanup_guard = ast.If(
                test=ast.Name(id=resource_name, ctx=ast.Load()),
                body=[cleanup_call],
                orelse=[],
            )
            function.body = [
                *function.body[:spawn_index + 1],
                ast.Try(body=trailing, handlers=[], orelse=[], finalbody=[cleanup_guard]),
            ]
            changed = True
            notes.append(
                f"{Path(path).name}:{function.name}: wrapped post-spawn work "
                f"in finally cleanup for `{resource_name}`."
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[index] = (path, original, ast.unparse(tree).rstrip() + "\n")
    return updated, notes


def _repair_unreachable_delegated_launcher(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """
        Delegates a connected UI action handler to its worker launcher.
    :param generated_files: generated path, original source, and candidate source rows
    :param errors: validation errors describing unreachable launchers
    :return: updated generated files and repair notes
    """
    targets: dict[tuple[str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<class>[A-Za-z_][A-Za-z0-9_]*)\."
        r"(?P<method>[A-Za-z_][A-Za-z0-9_]*): requirement-owning UI "
        r"handler is unreachable"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.setdefault(
                (
                    str(Path(match.group("path")).resolve()),
                    match.group("class"),
                ),
                set(),
            ).add(match.group("method"))
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        matching = {
            class_name: methods
            for (target_path, class_name), methods in targets.items()
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
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name in matching
        ]:
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            connected_handlers: set[str] = set()
            for node in ast.walk(class_node):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.args
                    and isinstance(node.args[0], ast.Attribute)
                    and isinstance(node.args[0].value, ast.Name)
                    and node.args[0].value.id == "self"
                ):
                    continue
                signal_owner = node.func.value.value
                signal_owner_name = (
                    signal_owner.attr
                    if isinstance(signal_owner, ast.Attribute)
                    and isinstance(signal_owner.value, ast.Name)
                    and signal_owner.value.id == "self"
                    else ""
                )
                signal_name = node.func.value.attr.casefold()
                if (
                    any(
                        token in signal_owner_name.casefold()
                        for token in ("worker", "thread", "task")
                    )
                    or signal_name
                    in {
                        "completed",
                        "error",
                        "failed",
                        "finished",
                        "progress",
                        "result",
                        "succeeded",
                    }
                ):
                    continue
                connected_handlers.add(node.args[0].attr)

            connected_action_handlers: list[
                ast.FunctionDef | ast.AsyncFunctionDef
            ] = []
            for handler_name in connected_handlers:
                handler = methods.get(handler_name)
                if handler is not None:
                    connected_action_handlers.append(handler)
            if len(connected_action_handlers) != 1:
                continue
            action_handler = connected_action_handlers[0]
            compatible_launchers: list[str] = []
            for launcher_name in sorted(matching[class_node.name]):
                launcher = methods.get(launcher_name)
                if launcher is None or launcher is action_handler:
                    continue
                role_name = launcher_name.casefold()
                if any(
                    token in role_name
                    for token in (
                        "cleanup",
                        "clean_up",
                        "dispose",
                        "error",
                        "finish",
                        "progress",
                        "release",
                        "result",
                    )
                ):
                    continue
                launches_background_work = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"start", "submit", "run_in_executor"}
                    for node in ast.walk(launcher)
                )
                if launches_background_work:
                    compatible_launchers.append(launcher_name)
            if len(compatible_launchers) != 1:
                continue
            launcher_name = compatible_launchers[0]
            retained_docstring: list[ast.stmt] = []
            if (
                action_handler.body
                and isinstance(action_handler.body[0], ast.Expr)
                and isinstance(action_handler.body[0].value, ast.Constant)
                and isinstance(action_handler.body[0].value.value, str)
            ):
                retained_docstring.append(action_handler.body[0])
            action_handler.body = retained_docstring + [
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=launcher_name,
                            ctx=ast.Load(),
                        ),
                        args=[],
                        keywords=[],
                    )
                )
            ]
            changed = True
            notes.append(
                f"{Path(path).name}:{class_node.name}."
                f"{action_handler.name}: delegated to requirement-owning "
                f"background launcher `{launcher_name}`."
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_unresolved_signal_connections(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """
        Removes signal connections whose private handlers are undeclared.
    :param generated_files: generated path, original source, and candidate source rows
    :param errors: validation errors describing undefined handlers
    :return: updated generated files and repair notes
    """
    targets: dict[tuple[str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<class>[A-Za-z_][A-Za-z0-9_]*): "
        r"signal connections reference undefined private handler\(s\): "
        r"(?P<handlers>.+?)\."
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.setdefault(
                (
                    str(Path(match.group("path")).resolve()),
                    match.group("class"),
                ),
                set(),
            ).update(
                value.strip()
                for value in match.group("handlers").split(",")
                if value.strip()
            )
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        matching = {
            class_name: handlers
            for (target_path, class_name), handlers in targets.items()
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
            node for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name in matching
        ]:
            invalid_handlers = matching[class_node.name]
            for method in class_node.body:
                if not isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                retained_statements: list[ast.stmt] = []
                for statement in method.body:
                    invalid_connection = (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Attribute)
                        and statement.value.func.attr == "connect"
                        and statement.value.args
                        and isinstance(statement.value.args[0], ast.Attribute)
                        and isinstance(statement.value.args[0].value, ast.Name)
                        and statement.value.args[0].value.id == "self"
                        and statement.value.args[0].attr in invalid_handlers
                    )
                    if invalid_connection:
                        changed = True
                        continue
                    retained_statements.append(statement)
                method.body = retained_statements or [ast.Pass()]
            if changed:
                notes.append(
                    f"{Path(path).name}:{class_node.name}: removed signal "
                    "connections to undefined private handlers."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes
