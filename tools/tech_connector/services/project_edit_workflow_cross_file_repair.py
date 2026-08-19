"""Cross-file import and verified Qt worker repair helpers."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def _repair_missing_cross_file_imports(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Import and consume an approved generated sibling dependency atomically."""

    targets: dict[str, dict[str, set[str]]] = {}
    pattern = re.compile(
        r"(?:\[owner:[^\]]+\]\s+\[repair-scope:[^\]]+\]\s+)?"
        r"(?P<path>[A-Za-z]:\\.+?\.py):(?:<module>|"
        r"(?P<consumer>[A-Za-z_][A-Za-z0-9_]*)): "
        r"approved cross-file dependency `(?P<owner>[A-Za-z_][A-Za-z0-9_]*)` "
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
            targets.setdefault(
                str(Path(match.group("path")).resolve()), {}
            ).setdefault(match.group("owner"), set()).add(consumer)
    if not targets:
        return generated_files, []

    owner_paths: dict[str, Path] = {}
    owner_methods: dict[str, set[str]] = {}
    default_constructible_owners: set[str] = set()
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                owner_paths.setdefault(node.name, Path(path).resolve())
            if not isinstance(node, ast.ClassDef):
                continue
            owner_methods[node.name] = {
                statement.name
                for statement in node.body
                if isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and not statement.name.startswith("_")
            }
            initializer = next(
                (
                    statement
                    for statement in node.body
                    if isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and statement.name == "__init__"
                ),
                None,
            )
            if initializer is None:
                default_constructible_owners.add(node.name)
                continue
            positional = [
                *initializer.args.posonlyargs,
                *initializer.args.args,
            ][1:]
            required_positional_count = max(
                0,
                len(positional) - len(initializer.args.defaults),
            )
            required_keyword_only = any(
                default is None
                for default in initializer.args.kw_defaults
            )
            if not required_positional_count and not required_keyword_only:
                default_constructible_owners.add(node.name)

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        dependencies = targets.get(resolved_path, {})
        if not dependencies:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        existing_names = {
            alias.asname or alias.name.rsplit(".", 1)[-1]
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        inserted: list[str] = []
        routed: list[str] = []
        for dependency, consumers in sorted(dependencies.items()):
            dependency_path = owner_paths.get(dependency)
            if (
                dependency_path is None
                or dependency_path == Path(path).resolve()
            ):
                continue
            if dependency not in existing_names:
                target_parent = Path(path).resolve().parent
                dependency_parent = dependency_path.parent
                if dependency_parent == target_parent:
                    package_name = target_parent.name
                    module_name = f"{package_name}.{dependency_path.stem}"
                else:
                    module_name = dependency_path.stem
                tree.body.insert(
                    0,
                    ast.ImportFrom(
                        module=module_name,
                        names=[ast.alias(name=dependency)],
                        level=0,
                    ),
                )
                existing_names.add(dependency)
                inserted.append(f"{module_name}.{dependency}")
            if dependency not in default_constructible_owners:
                continue
            approved_methods = owner_methods.get(dependency, set())
            for class_node in (
                node for node in tree.body if isinstance(node, ast.ClassDef)
            ):
                if class_node.name not in consumers:
                    continue
                local_methods = {
                    statement.name
                    for statement in class_node.body
                    if isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
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
                    routed.append(f"{dependency}.{node.attr}")
        if inserted or routed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            notes.append(
                f"{Path(path).name}: atomically resolved approved generated "
                "dependency surface: "
                + ", ".join(inserted + sorted(set(routed)))
                + "."
            )
    return updated, notes


def _repair_unreferenced_private_helpers(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove only validator-proven unreachable private class callables."""

    targets: dict[tuple[str, str], set[str]] = {}
    cleanup_required_owners: set[tuple[str, str]] = set()
    requirement_owned_methods: dict[tuple[str, str], set[str]] = {}
    cleanup_requirement_pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\."
        r"[A-Za-z_][A-Za-z0-9_]*: retained worker "
        r"`self\.[A-Za-z_][A-Za-z0-9_]*` must connect its `finished` signal"
    )
    for error in errors:
        cleanup_match = cleanup_requirement_pattern.match(str(error))
        if cleanup_match:
            cleanup_required_owners.add((
                str(Path(cleanup_match.group("path")).resolve()),
                cleanup_match.group("owner"),
            ))
        owned_match = re.match(
            r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*)\."
            r"(?P<method>_[A-Za-z_][A-Za-z0-9_]*): "
            r"requirement-owning UI handler is unreachable",
            str(error),
        )
        if owned_match:
            requirement_owned_methods.setdefault(
                (
                    str(Path(owned_match.group("path")).resolve()),
                    owned_match.group("owner"),
                ),
                set(),
            ).add(owned_match.group("method"))
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*): "
        r"private helper callable\(s\) are never referenced by production "
        r"behavior and introduce dead code: (?P<methods>[^.]+)\."
    )
    for error in errors:
        match = pattern.search(str(error))
        if not match:
            continue
        methods = {
            value.strip()
            for value in match.group("methods").split(",")
            if value.strip().startswith("_")
            and not value.strip().startswith("__")
        }
        if methods:
            targets[(
                str(Path(match.group("path")).resolve()),
                match.group("owner"),
            )] = methods
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
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            candidate_names = owner_targets.get(class_node.name, set())
            if not candidate_names:
                continue
            candidate_names = candidate_names - requirement_owned_methods.get(
                (resolved_path, class_node.name),
                set(),
            )
            if (resolved_path, class_node.name) in cleanup_required_owners:
                candidate_names = {
                    name
                    for name in candidate_names
                    if not any(
                        token in name.casefold()
                        for token in (
                            "cleanup",
                            "clean_up",
                            "release",
                            "dispose",
                        )
                    )
                }
            if not candidate_names:
                continue
            retained_nodes = [
                node
                for node in class_node.body
                if not (
                    isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name in candidate_names
                )
            ]
            referenced_names = {
                reference.attr
                for node in retained_nodes
                for reference in ast.walk(node)
                if isinstance(reference, ast.Attribute)
                and isinstance(reference.value, ast.Name)
                and reference.value.id == "self"
            }
            safe_to_remove = candidate_names - referenced_names
            if not safe_to_remove:
                continue
            class_node.body = [
                node
                for node in class_node.body
                if not (
                    isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name in safe_to_remove
                )
            ]
            removed.extend(
                f"{class_node.name}.{name}"
                for name in sorted(safe_to_remove)
            )
        if removed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            notes.append(
                f"{Path(path).name}: removed validator-proven unreachable "
                "private callable(s): " + ", ".join(removed)
            )
    return updated, notes


def _repair_verified_qt_worker_integration(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Wire an existing Qt worker to one source-proven blocking operation."""

    if not any(
        "background execution has no connected completion/result path" in str(error)
        or "background execution has no connected error/failure path" in str(error)
        for error in errors
    ):
        return generated_files, []

    parsed_files: list[tuple[int, str, str, str, ast.Module]] = []
    for index, (path, original, source) in enumerate(generated_files):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        parsed_files.append((index, path, original, source, tree))

    operation_candidates: list[tuple[str, str, str]] = []
    for _index, path, _original, _source, tree in parsed_files:
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
            constructor_required = 0
            if constructor is not None:
                constructor_parameters = [
                    *constructor.args.posonlyargs,
                    *constructor.args.args,
                ][1:]
                constructor_required = max(
                    0,
                    len(constructor_parameters) - len(constructor.args.defaults),
                )
            if constructor_required:
                continue
            for method in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name != "__init__"
            ]:
                parameter_names = {
                    argument.arg
                    for argument in [
                        *method.args.posonlyargs,
                        *method.args.args,
                        *method.args.kwonlyargs,
                    ]
                }
                if "progress_callback" in parameter_names:
                    operation_candidates.append(
                        (path, class_node.name, method.name)
                    )
    if len(operation_candidates) != 1:
        return generated_files, []
    operation_path, service_name, operation_name = operation_candidates[0]

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, path, original, source, tree in parsed_files:
        worker_classes: list[tuple[ast.ClassDef, list[str]]] = []
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            base_names = {
                ast.unparse(base).rsplit(".", 1)[-1]
                for base in class_node.bases
            }
            if "QThread" not in base_names:
                continue
            signal_names = [
                target.id
                for statement in class_node.body
                if isinstance(statement, ast.Assign)
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
                for target in statement.targets
                if isinstance(target, ast.Name)
            ]
            if signal_names:
                worker_classes.append((class_node, signal_names))
        if len(worker_classes) != 1:
            continue
        worker_class, signal_names = worker_classes[0]

        dialog_candidates: list[
            tuple[
                ast.ClassDef,
                ast.FunctionDef | ast.AsyncFunctionDef,
                ast.Call,
                str,
            ]
        ] = []
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for method in methods.values():
                worker_assignment = next(
                    (
                        node
                        for node in ast.walk(method)
                        if isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Attribute)
                        and isinstance(node.targets[0].value, ast.Name)
                        and node.targets[0].value.id == "self"
                        and isinstance(node.value, ast.Call)
                        and (
                            (
                                isinstance(node.value.func, ast.Name)
                                and node.value.func.id == worker_class.name
                            )
                            or (
                                isinstance(node.value.func, ast.Attribute)
                                and node.value.func.attr == worker_class.name
                            )
                        )
                    ),
                    None,
                )
                if worker_assignment is None:
                    continue
                if not any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "start"
                    for node in ast.walk(method)
                ):
                    continue
                dialog_candidates.append(
                    (
                        class_node,
                        method,
                        worker_assignment.value,
                        worker_assignment.targets[0].attr,
                    )
                )
        if len(dialog_candidates) != 1:
            continue
        dialog_class, launcher, worker_call, worker_attribute = (
            dialog_candidates[0]
        )
        method_names = {
            node.name
            for node in dialog_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        handler_by_signal: dict[str, str] = {}
        for signal_name in signal_names:
            matching_handlers = sorted(
                name
                for name in method_names
                if re.search(
                    rf"(?:^|_){re.escape(signal_name.casefold())}(?:_|$)",
                    name.casefold(),
                )
            )
            if len(matching_handlers) == 1:
                handler_by_signal[signal_name] = matching_handlers[0]
        if not {"result", "error", "progress"} <= set(handler_by_signal):
            continue

        retained_docstring: list[ast.stmt] = []
        if (
            launcher.body
            and isinstance(launcher.body[0], ast.Expr)
            and isinstance(launcher.body[0].value, ast.Constant)
            and isinstance(launcher.body[0].value.value, str)
        ):
            retained_docstring.append(launcher.body[0])
        service_local = "_service"
        worker_reference = ast.Attribute(
            value=ast.Name(id="self", ctx=ast.Load()),
            attr=worker_attribute,
            ctx=ast.Load(),
        )
        preserved_worker_args = list(worker_call.args[1:])
        preserved_worker_keywords = [
            keyword
            for keyword in worker_call.keywords
            if keyword.arg != "progress_callback"
        ]
        launcher.body = [
            *retained_docstring,
            ast.Assign(
                targets=[ast.Name(id=service_local, ctx=ast.Store())],
                value=ast.Call(
                    func=ast.Name(id=service_name, ctx=ast.Load()),
                    args=[],
                    keywords=[],
                ),
            ),
            ast.Assign(
                targets=[
                    ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=worker_attribute,
                        ctx=ast.Store(),
                    )
                ],
                value=ast.Call(
                    func=ast.Name(id=worker_class.name, ctx=ast.Load()),
                    args=[
                        ast.Attribute(
                            value=ast.Name(id=service_local, ctx=ast.Load()),
                            attr=operation_name,
                            ctx=ast.Load(),
                        ),
                        *preserved_worker_args,
                    ],
                    keywords=preserved_worker_keywords,
                ),
            ),
            *[
                ast.Expr(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Attribute(
                                value=worker_reference,
                                attr=signal_name,
                                ctx=ast.Load(),
                            ),
                            attr="connect",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=handler_by_signal[signal_name],
                                ctx=ast.Load(),
                            )
                        ],
                        keywords=[],
                    )
                )
                for signal_name in ("result", "error", "progress")
            ],
            ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=worker_reference,
                        attr="start",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                )
            ),
        ]

        imported_names = {
            alias.asname or alias.name.rsplit(".", 1)[-1]
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        if service_name not in imported_names:
            target_parent = Path(path).resolve().parent
            source_path = Path(operation_path).resolve()
            module_name = (
                f"{target_parent.name}.{source_path.stem}"
                if source_path.parent == target_parent
                else source_path.stem
            )
            tree.body.insert(
                0,
                ast.ImportFrom(
                    module=module_name,
                    names=[ast.alias(name=service_name)],
                    level=0,
                ),
            )
        ast.fix_missing_locations(tree)
        updated[file_index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
        notes.append(
            f"{Path(path).name}:{dialog_class.name}.{launcher.name}: "
            "wired the verified worker, generated service operation, and "
            "declared result/error/progress signals."
        )
    return updated, notes


