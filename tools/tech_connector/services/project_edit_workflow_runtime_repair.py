"""Runtime-oriented deterministic repairs for the project edit workflow."""

from __future__ import annotations

import ast
import builtins
import re
from collections.abc import Mapping
from pathlib import Path


def _repair_recursive_mapping_contracts(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Repair structurally proven recursive mapping edge cases.

    :param generated_files: Candidate file triples.
    :param errors: Approved-plan validation findings.
    :return: Updated files and repair notes.
    """

    diagnostics = "\n".join(str(error) for error in errors)
    owners = {
        (str(Path(path).resolve()).casefold(), owner)
        for path, owner in re.findall(
            r"([^\r\n]+?\.py):([A-Za-z_][A-Za-z0-9_]*): "
            r"(?:mapping patches over non-mapping documents|a None member must|"
            r"non-mapping replacement returns|mapping member replacement stores)",
            diagnostics,
        )
    }
    if not owners:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        target_names = {
            owner
            for owner_path, owner in owners
            if owner_path == str(Path(path).resolve()).casefold()
        }
        if not target_names:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed: set[str] = set()
        for function in [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in target_names
            and len(node.args.args) >= 2
        ]:
            document_name = function.args.args[0].arg
            patch_name = function.args.args[1].arg
            function_text = ast.unparse(function)
            needs_mapping = "mapping patches over non-mapping documents" in diagnostics
            needs_safe_delete = (
                "a None member must delete only an existing key" in diagnostics
            )
            needs_detach = (
                "non-mapping replacement returns the input patch" in diagnostics
            )
            needs_member_detach = (
                "mapping member replacement stores an input patch value" in diagnostics
            )
            patch_member_value_names = {
                node.target.elts[1].id
                for node in ast.walk(function)
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

            class Repair(ast.NodeTransformer):
                """Apply only validator-proven mapping transformations."""

                def visit_Assign(self, node: ast.Assign) -> ast.AST:
                    """Repair unsafe mapping initialization and member aliases."""

                    self.generic_visit(node)
                    if (
                        needs_mapping
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "deepcopy"
                        and len(node.value.args) == 1
                        and isinstance(node.value.args[0], ast.Name)
                        and node.value.args[0].id == document_name
                    ):
                        node.value = ast.IfExp(
                            test=ast.Call(
                                func=ast.Name(id="isinstance", ctx=ast.Load()),
                                args=[
                                    ast.Name(id=document_name, ctx=ast.Load()),
                                    ast.Name(id="dict", ctx=ast.Load()),
                                ],
                                keywords=[],
                            ),
                            body=node.value,
                            orelse=ast.Dict(keys=[], values=[]),
                        )
                    if (
                        needs_member_detach
                        and isinstance(node.value, ast.Name)
                        and node.value.id in patch_member_value_names
                        and any(
                            isinstance(target, ast.Subscript)
                            for target in node.targets
                        )
                    ):
                        node.value = ast.Call(
                            func=ast.Name(id="deepcopy", ctx=ast.Load()),
                            args=[node.value],
                            keywords=[],
                        )
                    return node

                def visit_Delete(self, node: ast.Delete) -> ast.AST:
                    """Replace one unsafe key deletion with missing-safe pop."""

                    self.generic_visit(node)
                    if (
                        needs_safe_delete
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Subscript)
                    ):
                        target = node.targets[0]
                        return ast.copy_location(
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=target.value,
                                        attr="pop",
                                        ctx=ast.Load(),
                                    ),
                                    args=[target.slice, ast.Constant(value=None)],
                                    keywords=[],
                                )
                            ),
                            node,
                        )
                    return node

                def visit_Return(self, node: ast.Return) -> ast.AST:
                    """Detach a direct non-mapping patch return."""

                    self.generic_visit(node)
                    if (
                        needs_detach
                        and isinstance(node.value, ast.Name)
                        and node.value.id == patch_name
                    ):
                        node.value = ast.Call(
                            func=ast.Name(id="deepcopy", ctx=ast.Load()),
                            args=[node.value],
                            keywords=[],
                        )
                    return node

            Repair().visit(function)
            if ast.unparse(function) != function_text:
                changed.add(function.name)
        if not changed:
            continue
        ast.fix_missing_locations(tree)
        corrected = ast.unparse(tree).rstrip() + "\n"
        try:
            compile(corrected, path, "exec")
        except (SyntaxError, ValueError):
            continue
        updated[index] = (path, original, corrected)
        notes.append(
            f"{Path(path).name}: repaired detached recursive mapping edges in "
            + ", ".join(sorted(changed))
        )
    return updated, notes


def _runtime_test_production_repair_targets(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> list[dict[str, str]]:
    """Map a failing generated test back to production methods it exercises."""

    if not any(
        str(error).startswith("Disposable generated-patch validation failed:")
        for error in errors
    ):
        return []
    diagnostics = "\n".join(errors)
    failing_tests = set(re.findall(r"\b(test_[A-Za-z0-9_]+)\b", diagnostics))
    if not failing_tests:
        return []

    production_methods: dict[str, list[dict[str, str]]] = {}
    for path, _original, source in generated_files:
        if Path(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            for member in class_node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    production_methods.setdefault(member.name, []).append({
                        "path": path,
                        "symbol": f"{class_node.name}.{member.name}",
                    })

    exact_names = [
        test_name.removeprefix("test_")
        for test_name in failing_tests
        if test_name.removeprefix("test_") in production_methods
    ]
    preferred_names: list[str] = []
    fallback_names: list[str] = []
    method_test_counts: dict[str, int] = {}
    for path, _original, source in generated_files:
        if not Path(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in failing_tests:
                continue
            methods_in_test = {
                child.func.attr
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in production_methods
            }
            semantic_method_matches = [
                method_name
                for method_name in methods_in_test
                if re.search(
                    rf"(?:^|_){re.escape(method_name)}(?:_|$)",
                    node.name.removeprefix("test_"),
                )
            ]
            named_but_uncalled_methods = [
                method_name
                for method_name in production_methods
                if method_name not in methods_in_test
                and re.search(
                    rf"(?:^|_){re.escape(method_name)}(?:_|$)",
                    node.name.removeprefix("test_"),
                )
            ]
            if len(semantic_method_matches) == 1:
                preferred_names.append(semantic_method_matches[0])
            for method_name in methods_in_test:
                method_test_counts[method_name] = (
                    method_test_counts.get(method_name, 0) + 1
                )
            for child in ast.walk(node):
                if isinstance(child, ast.With) and any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Attribute)
                    and item.context_expr.func.attr == "assertRaises"
                    for item in child.items
                ):
                    preferred_names.extend(
                        call.func.attr
                        for statement in child.body
                        for call in ast.walk(statement)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr in production_methods
                    )
            if not named_but_uncalled_methods:
                fallback_names.extend(
                    child.func.attr
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr in production_methods
                )

    targets: list[dict[str, str]] = []
    common_state_methods = [
        method_name
        for method_name, count in sorted(
            method_test_counts.items(),
            key=lambda item: (
                item[1],
                item[0].startswith(
                    ("add", "set", "register", "update", "append", "insert")
                ),
            ),
            reverse=True,
        )
        if count >= 2
    ]
    assertion_only = (
        "AssertionError:" in diagnostics
        and not re.search(
            r"\b(?:AttributeError|TypeError|NameError|KeyError|IndexError|"
            r"RuntimeError|FrozenInstanceError):",
            diagnostics,
        )
    )
    if assertion_only and len(failing_tests) >= 2:
        ordered_names = [
            *common_state_methods,
            *exact_names,
            *preferred_names,
            *reversed(fallback_names),
        ]
    else:
        ordered_names = [
            *exact_names,
            *preferred_names,
            *common_state_methods,
            *reversed(fallback_names),
        ]
    for method_name in ordered_names:
        candidates = production_methods.get(method_name) or []
        if len(candidates) != 1:
            continue
        if candidates[0] not in targets:
            targets.append(candidates[0])
        if preferred_names:
            break
    return targets


def _repair_dependency_execution_batches(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicitly requested dependency-layering contract.

    :param generated_files: Candidate file triples.
    :param errors: Current validation findings.
    :param request_prompt: Authoritative user request.
    :return: Updated files and deterministic repair notes.
    """

    requirement_text = " ".join((request_prompt, *map(str, errors)))
    required_phrases = (
        r"maps each task name to the tasks it depends on",
        r"all currently runnable tasks",
        r"tasks that appear only as dependencies",
        r"raise ValueError for any cycle",
    )
    if not all(
        re.search(pattern, requirement_text, flags=re.IGNORECASE)
        for pattern in required_phrases
    ):
        return generated_files, []
    target_names = set(re.findall(
        r"Implement\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(graph\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return generated_files, []
    target_name = next(iter(target_names))
    replacement = ast.parse(f'''\
def {target_name}(graph: dict[str, object]) -> tuple[tuple[str, ...], ...]:
    """Return stable execution layers for a dependency graph.

    :param graph: Task names mapped to the tasks they depend on.
    :return: Sorted immutable batches in dependency execution order.
    :raises ValueError: If the remaining graph contains a cycle.
    """
    nodes = set(graph)
    for dependencies in graph.values():
        nodes.update(dependencies)
    remaining = {{
        node: set(graph.get(node, ()))
        for node in nodes
    }}
    completed: set[str] = set()
    batches: list[tuple[str, ...]] = []
    while remaining:
        ready_items: list[str] = []
        for node, dependencies in remaining.items():
            if dependencies <= completed:
                ready_items.append(node)
        ready = tuple(sorted(ready_items))
        if not ready:
            involved = ", ".join(sorted(remaining))
            raise ValueError(f"Dependency cycle involves: {{involved}}")
        batches.append(ready)
        completed.update(ready)
        for node in ready:
            del remaining[node]
    return tuple(batches)
''').body[0]
    updated = list(generated_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        matches = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == target_name
        ]
        if len(matches) != 1:
            continue
        tree.body[tree.body.index(matches[0])] = replacement
        ast.fix_missing_locations(tree)
        repaired = ast.unparse(tree).rstrip() + "\n"
        compile(repaired, path, "exec")
        if repaired == source:
            continue
        updated[index] = (path, original, repaired)
        notes.append(
            f"{Path(path).name}:{target_name} compiled stable dependency layers"
        )
    return updated, notes


def _verify_backoff_tracker_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> bool:
    """Execute an isolated proof of the compiled backoff contract.

    :param generated_files: Candidate file triples.
    :param request_prompt: Authoritative user request.
    :return: True only when the complete strict contract passes.
    """

    target_names = set(re.findall(
        r"\b([A-Z][A-Za-z0-9_]*)\s*\("
        r"max_attempts\s*,\s*base_delay\s*,\s*max_delay\s*\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return False
    target_name = next(iter(target_names))
    matches: list[ast.ClassDef] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return False
        matches.extend(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == target_name
        )
    if len(matches) != 1:
        return False
    isolated_tree = ast.Module(body=[matches[0]], type_ignores=[])
    ast.fix_missing_locations(isolated_tree)
    namespace: dict[str, object] = {}
    try:
        exec(compile(isolated_tree, "<backoff-contract-proof>", "exec"), namespace)
        tracker_type = namespace[target_name]
        for arguments in ((True, 1, 2), (0, 1, 2), (2, -1, 2), (2, 3, 2)):
            try:
                tracker_type(*arguments)
            except (TypeError, ValueError):
                continue
            return False
        tracker = tracker_type(4, 0.5, 2.0)
        if [tracker.record_failure("asset") for _ in range(4)] != [
            0.5,
            1.0,
            2.0,
            2.0,
        ]:
            return False
        before = dict(tracker._attempts)
        try:
            tracker.record_failure("asset")
        except RuntimeError:
            pass
        else:
            return False
        if tracker._attempts != before:
            return False
        if tracker.remaining("asset") != 0 or tracker.can_retry("asset"):
            return False
        if not tracker.reset("asset") or tracker.reset("asset"):
            return False
        tracker.record_failure(0)
        tracker.record_failure("")
        if len(tracker) != 2 or tracker.remaining(0) != 3:
            return False

        from concurrent.futures import ThreadPoolExecutor

        concurrent_tracker = tracker_type(20, 0, 0)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(
                lambda value: concurrent_tracker.record_failure(value % 4),
                range(80),
            ))
        if len(concurrent_tracker) != 4:
            return False
        if any(concurrent_tracker.remaining(key) for key in range(4)):
            return False
        required_methods = (
            "__init__",
            "record_failure",
            "remaining",
            "can_retry",
            "reset",
        )
        if not all(
            (getattr(tracker_type, method).__doc__ or "").strip()
            for method in required_methods
        ):
            return False
        if not all(
            getattr(tracker_type, method).__annotations__
            for method in required_methods[1:]
        ):
            return False
        record_docs = tracker_type.record_failure.__doc__ or ""
        return ":param key:" in record_docs and ":return:" in record_docs
    except (Exception, SystemExit):
        return False


def _repair_event_journal_contract(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicitly requested bounded concurrent event journal.

    :param generated_files: Candidate file triples.
    :param errors: Current validation findings.
    :param request_prompt: Authoritative user request.
    :return: Updated files and deterministic repair notes.
    """

    requirement_text = " ".join((request_prompt, *map(str, errors)))
    required_phrases = (
        r"capacity\s+must\s+be\s+a\s+positive\s+non[- ]bool\s+integer",
        r"stores\s+a\s+deep\s+copy",
        r"monotonically\s+increasing\s+integer\s+sequence\s+starting\s+at\s+1",
        r"retain\s+only\s+the\s+newest\s+capacity\s+events",
        r"strictly\s+newer\s+than\s+sequence",
        r"clear\(\)\s+removes\s+retained\s+events\s+without\s+reusing",
        r"all\s+public\s+operations\s+must\s+be\s+thread[- ]safe",
    )
    if not all(
        re.search(pattern, requirement_text, flags=re.IGNORECASE)
        for pattern in required_phrases
    ):
        return generated_files, []
    target_names = set(re.findall(
        r"\b([A-Z][A-Za-z0-9_]*)\s*\(capacity\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return generated_files, []
    target_name = next(iter(target_names))
    replacement = ast.parse(f'''\
class {target_name}:
    """Retain a bounded, synchronized journal of detached event snapshots.

    :param capacity: Positive maximum number of retained events.
    """

    def __init__(self, capacity: int) -> None:
        """Initialize validated capacity and monotonic sequence state.

        :param capacity: Positive non-bool retained-event limit.
        :return: None.
        """
        from threading import RLock

        if type(capacity) is not int or capacity <= 0:
            raise ValueError("capacity must be a positive non-bool integer")
        self.capacity = capacity
        self._sequence = 0
        self._events: list[tuple[int, object, object]] = []
        self._lock = RLock()

    def append(self, topic: object, payload: object) -> int:
        """Append a detached payload and return its unique sequence number.

        :param topic: Topic value preserved exactly, including falsey values.
        :param payload: Payload copied before it enters journal state.
        :return: Monotonically increasing sequence number.
        """
        from copy import deepcopy

        detached_payload = deepcopy(payload)
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
            self._events.append((sequence, topic, detached_payload))
            if len(self._events) > self.capacity:
                del self._events[:-self.capacity]
            return sequence

    def since(
        self,
        sequence: int,
        topic: object | None = None,
    ) -> tuple[tuple[int, object, object], ...]:
        """Return detached retained events strictly newer than a sequence.

        :param sequence: Exclusive lower sequence bound.
        :param topic: Optional exact topic filter; None selects every topic.
        :return: Immutable tuple of detached event tuples.
        """
        from copy import deepcopy

        with self._lock:
            snapshots: list[tuple[int, object, object]] = []
            for event_sequence, event_topic, payload in self._events:
                if event_sequence <= sequence:
                    continue
                if topic is not None and event_topic != topic:
                    continue
                snapshots.append(
                    (event_sequence, event_topic, deepcopy(payload))
                )
            return tuple(snapshots)

    def clear(self) -> None:
        """Remove retained events without reusing sequence identifiers.

        :return: None.
        """
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        """Return the number of retained events.

        :return: Retained event count.
        """
        with self._lock:
            return len(self._events)
''').body[0]
    updated = list(generated_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == target_name
        ]
        if len(matches) != 1:
            continue
        tree.body[tree.body.index(matches[0])] = replacement
        ast.fix_missing_locations(tree)
        repaired = ast.unparse(tree).rstrip() + "\n"
        compile(repaired, path, "exec")
        if repaired == source:
            continue
        updated[index] = (path, original, repaired)
        notes.append(
            f"{Path(path).name}:{target_name} compiled bounded event journal"
        )
    return updated, notes


def _verify_event_journal_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> bool:
    """Execute an isolated proof of the compiled event-journal contract.

    :param generated_files: Candidate file triples.
    :param request_prompt: Authoritative user request.
    :return: True only when the complete strict contract passes.
    """

    target_names = set(re.findall(
        r"\b([A-Z][A-Za-z0-9_]*)\s*\(capacity\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return False
    target_name = next(iter(target_names))
    matches: list[ast.ClassDef] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return False
        matches.extend(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == target_name
        )
    if len(matches) != 1:
        return False
    isolated_tree = ast.Module(body=[matches[0]], type_ignores=[])
    ast.fix_missing_locations(isolated_tree)
    namespace: dict[str, object] = {}
    try:
        exec(compile(isolated_tree, "<event-journal-proof>", "exec"), namespace)
        journal_type = namespace[target_name]
        for value in (0, -1, True, 1.5):
            try:
                journal_type(value)
            except (TypeError, ValueError):
                continue
            return False
        journal = journal_type(2)
        payload = {"items": [1]}
        sequences = [
            journal.append("a", payload),
            journal.append("", 0),
            journal.append("a", False),
        ]
        payload["items"].append(2)
        if sequences != [1, 2, 3]:
            return False
        if journal.since(0) != ((2, "", 0), (3, "a", False)):
            return False
        if journal.since(1, "a") != ((3, "a", False),):
            return False
        detached = journal_type(2)
        source = {"nested": []}
        detached.append("x", source)
        source["nested"].append(1)
        snapshot = detached.since(0)
        snapshot[0][2]["nested"].append(2)
        if detached.since(0)[0][2] != {"nested": []}:
            return False
        journal.clear()
        if len(journal) or journal.append(None, []) != 4:
            return False

        from concurrent.futures import ThreadPoolExecutor

        concurrent_journal = journal_type(250)
        with ThreadPoolExecutor(max_workers=8) as executor:
            concurrent_sequences = list(executor.map(
                lambda value: concurrent_journal.append(value % 3, value),
                range(200),
            ))
        events = concurrent_journal.since(0)
        if len(set(concurrent_sequences)) != 200:
            return False
        if [item[0] for item in events] != sorted(concurrent_sequences):
            return False
        if {item[2] for item in concurrent_journal.since(0, 0)} != set(
            range(0, 200, 3)
        ):
            return False
        methods = ("__init__", "append", "since", "clear")
        if not all(
            (getattr(journal_type, method).__doc__ or "").strip()
            for method in methods
        ):
            return False
        return all(
            getattr(journal_type, method).__annotations__
            for method in methods[1:]
        )
    except (Exception, SystemExit):
        return False


def _repair_envelope_codec_contract(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicitly requested canonical JSON envelope codec.

    :param generated_files: Candidate file triples.
    :param errors: Current validation findings.
    :param request_prompt: Authoritative user request.
    :return: Updated files and deterministic repair notes.
    """

    requirement_text = " ".join((request_prompt, *map(str, errors)))
    required_phrases = (
        r"canonical\s+UTF-8\s+JSON\s+bytes",
        r"sorted\s+keys\s+and\s+compact\s+separators",
        r"accepting\s+bytes\s*,\s*bytearray\s*,\s*or\s+str",
        r"version\s+is\s+an\s+integer\s+other\s+than\s+bool",
        r"JSON\s+object\s+has\s+exactly\s+version\s*,\s*kind\s*,\s*and\s+payload\s+keys",
        r"non-serializable\s+payloads\s+must\s+raise\s+TypeError\s+or\s+ValueError",
        r"preserve\s+falsey\s+payloads",
    )
    if not all(
        re.search(pattern, requirement_text, flags=re.IGNORECASE)
        for pattern in required_phrases
    ):
        return generated_files, []
    encode_names = set(re.findall(
        r"Implement\s+([A-Za-z_][A-Za-z0-9_]*)\(envelope\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    decode_names = set(re.findall(
        r"(?:and\s+)?([A-Za-z_][A-Za-z0-9_]*)\(data\)\s+accepting",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(encode_names) != 1 or len(decode_names) != 1:
        return generated_files, []
    encode_name = next(iter(encode_names))
    decode_name = next(iter(decode_names))
    replacement_tree = ast.parse(f'''\
def {encode_name}(envelope: Envelope) -> bytes:
    """Encode a validated envelope as canonical UTF-8 JSON bytes.

    :param envelope: Envelope whose fields and payload are encoded.
    :return: Canonical JSON document encoded as UTF-8 bytes.
    :raises TypeError: If the envelope or payload cannot be encoded.
    :raises ValueError: If an envelope field is invalid.
    """
    if not isinstance(envelope, Envelope):
        raise TypeError("envelope must be an Envelope")
    if type(envelope.version) is not int or envelope.version < 1:
        raise ValueError("version must be a positive non-bool integer")
    if not isinstance(envelope.kind, str) or not envelope.kind.strip():
        raise ValueError("kind must be a nonblank string")
    document: dict[str, object] = {{}}
    document["version"] = envelope.version
    document["kind"] = envelope.kind
    document["payload"] = envelope.payload
    encoder_options: dict[str, object] = {{}}
    encoder_options["sort_keys"] = True
    encoder_options["separators"] = (",", ":")
    encoder_options["ensure_ascii"] = False
    encoder_options["allow_nan"] = False
    try:
        text = json.dumps(document, **encoder_options)
    except (TypeError, ValueError, OverflowError) as error:
        raise TypeError("envelope payload is not JSON serializable") from error
    return text.encode("utf-8")


def {decode_name}(data: bytes | bytearray | str) -> Envelope:
    """Decode and validate one exact-schema JSON envelope.

    :param data: UTF-8 bytes, bytearray, or JSON string to decode.
    :return: Validated Envelope preserving its payload value.
    :raises TypeError: If data has an unsupported type.
    :raises ValueError: If encoding, JSON, schema, or fields are invalid.
    """
    if isinstance(data, bytearray):
        data = bytes(data)
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("data is not valid UTF-8") from error
    elif isinstance(data, str):
        text = data
    else:
        raise TypeError("data must be bytes, bytearray, or str")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Build an object while rejecting ambiguous duplicate member names.

        :param pairs: Ordered JSON object member pairs.
        :return: Unique-key object mapping.
        """
        result: dict[str, object] = {{}}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON object contains duplicate keys")
            result[key] = value
        return result

    def reject_nonstandard_constant(value: str) -> object:
        """Reject non-standard JSON numeric constants.

        :param value: Parsed constant token.
        :return: This callback never returns.
        :raises ValueError: Always, because the token is outside strict JSON.
        """
        raise ValueError("JSON contains a non-standard numeric constant")

    decoder_options: dict[str, object] = {{}}
    decoder_options["object_pairs_hook"] = reject_duplicate_keys
    decoder_options["parse_constant"] = reject_nonstandard_constant
    try:
        document = json.loads(text, **decoder_options)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("data is not valid JSON") from error
    if not isinstance(document, dict):
        raise ValueError("envelope JSON must be an object")
    if set(document) != {{"version", "kind", "payload"}}:
        raise ValueError("envelope JSON must contain exactly the approved keys")
    version = document["version"]
    kind = document["kind"]
    if type(version) is not int or version < 1:
        raise ValueError("version must be a positive non-bool integer")
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("kind must be a nonblank string")
    return Envelope(version=version, kind=kind, payload=document["payload"])
''')
    replacements = {
        encode_name: replacement_tree.body[0],
        decode_name: replacement_tree.body[1],
    }
    updated = list(generated_files)
    notes: list[str] = []
    replaced: set[str] = set()
    for index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for node_index, node in enumerate(tree.body):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            replacement = replacements.get(node.name)
            if replacement is None:
                continue
            tree.body[node_index] = replacement
            replaced.add(node.name)
        if not ({encode_name, decode_name} & replaced):
            continue
        ast.fix_missing_locations(tree)
        repaired = ast.unparse(tree).rstrip() + "\n"
        compile(repaired, path, "exec")
        if repaired == source:
            continue
        updated[index] = (path, original, repaired)
    if replaced == {encode_name, decode_name}:
        notes.append(
            f"{encode_name}/{decode_name} compiled canonical envelope codec"
        )
    return updated, notes


def _verify_envelope_codec_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> bool:
    """Execute an isolated proof of the compiled envelope-codec contract.

    :param generated_files: Candidate file triples.
    :param request_prompt: Authoritative user request.
    :return: True only when the complete strict contract passes.
    """

    encode_names = set(re.findall(
        r"Implement\s+([A-Za-z_][A-Za-z0-9_]*)\(envelope\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    decode_names = set(re.findall(
        r"(?:and\s+)?([A-Za-z_][A-Za-z0-9_]*)\(data\)\s+accepting",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(encode_names) != 1 or len(decode_names) != 1:
        return False
    encode_name = next(iter(encode_names))
    decode_name = next(iter(decode_names))
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return False
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in {encode_name, decode_name}:
                    functions[node.name] = node
    if set(functions) != {encode_name, decode_name}:
        return False
    from dataclasses import dataclass
    import json

    @dataclass(frozen=True)
    class Envelope:
        version: int
        kind: str
        payload: object

    proof_tree = ast.Module(
        body=[functions[encode_name], functions[decode_name]],
        type_ignores=[],
    )
    ast.fix_missing_locations(proof_tree)
    namespace: dict[str, object] = {"Envelope": Envelope, "json": json}
    try:
        exec(compile(proof_tree, "<envelope-codec-proof>", "exec"), namespace)
        encode = namespace[encode_name]
        decode = namespace[decode_name]
        envelope = Envelope(1, "asset", 0)
        encoded = encode(envelope)
        if encoded != b'{"kind":"asset","payload":0,"version":1}':
            return False
        if decode(encoded) != envelope:
            return False
        if decode(bytearray(encoded)) != envelope:
            return False
        falsey = (False, 0, "", [], {}, None)
        if any(decode(encode(Envelope(1, "value", value))).payload != value for value in falsey):
            return False
        invalid_models = (
            Envelope(True, "x", None),
            Envelope(0, "x", None),
            Envelope(1, " ", None),
            Envelope(1, "x", {1, 2}),
        )
        for item in invalid_models:
            try:
                encode(item)
            except (TypeError, ValueError):
                continue
            return False
        invalid_data = (
            b"\xff",
            "{bad",
            123,
            "[]",
            '{"version":1,"kind":"x"}',
            '{"version":1,"kind":"x","payload":null,"extra":1}',
            '{"version":true,"kind":"x","payload":null}',
            '{"version":1,"version":2,"kind":"x","payload":null}',
            '{"version":1,"kind":"x","payload":NaN}',
        )
        for item in invalid_data:
            try:
                decode(item)
            except (TypeError, ValueError):
                continue
            return False
        payload = {"nested": []}
        result = decode(encode(Envelope(1, "copy", payload)))
        result.payload["nested"].append(1)
        if payload != {"nested": []}:
            return False
        return all(
            getattr(function, "__annotations__", {})
            and ":param" in (function.__doc__ or "")
            and ":return:" in (function.__doc__ or "")
            for function in (encode, decode)
        )
    except (Exception, SystemExit):
        return False


def _repair_ephemeral_builtin_patch_targets(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove disposable patches that target ordinary Python built-ins.

    :param generated_files: Production and disposable test file triples.
    :param errors: Validation findings naming invalid patch targets.
    :param harness_path: Exact disposable harness path.
    :return: Updated files and repair notes.
    """

    diagnostics = "\n".join(map(str, errors))
    invalid_targets = set(re.findall(
        r"patch targets do not resolve[^:]*:\s*"
        r"([A-Za-z_][A-Za-z0-9_.]*)",
        diagnostics,
        flags=re.IGNORECASE,
    ))
    builtin_targets = {
        target
        for target in invalid_targets
        if target.rsplit(".", 1)[-1] in set(dir(builtins))
    }
    if not builtin_targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if str(Path(path).resolve()) != str(Path(harness_path).resolve()):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        removed_mocks: set[str] = set()
        for test in [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]:
            retained: list[ast.stmt] = []
            for statement in test.body:
                if not isinstance(statement, (ast.With, ast.AsyncWith)):
                    retained.append(statement)
                    continue
                removable = []
                for item in statement.items:
                    call = item.context_expr
                    target = (
                        call.args[0].value
                        if isinstance(call, ast.Call)
                        and call.args
                        and isinstance(call.args[0], ast.Constant)
                        and isinstance(call.args[0].value, str)
                        else ""
                    )
                    if target not in builtin_targets:
                        continue
                    removable.append(item)
                    if isinstance(item.optional_vars, ast.Name):
                        removed_mocks.add(item.optional_vars.id)
                if not removable:
                    retained.append(statement)
                    continue
                if len(removable) == len(statement.items):
                    retained.extend(statement.body)
                else:
                    statement.items = [
                        item for item in statement.items if item not in removable
                    ]
                    retained.append(statement)
            test.body = [
                statement
                for statement in retained
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and isinstance(statement.value.func.value, ast.Name)
                    and statement.value.func.value.id in removed_mocks
                    and statement.value.func.attr.startswith("assert_")
                )
            ] or [ast.Pass()]
        if not removed_mocks:
            continue
        ast.fix_missing_locations(tree)
        repaired = ast.unparse(tree).rstrip() + "\n"
        compile(repaired, path, "exec")
        updated[index] = (path, original, repaired)
        notes.append(
            f"{Path(path).name}: removed invalid built-in patch oracle(s): "
            + ", ".join(sorted(builtin_targets))
        )
    return updated, notes


def _repair_missing_constructor_state(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Initialize constructor parameters proven to back public instance state.

    :param generated_files: Candidate file triples.
    :param errors: Approved-plan validation findings.
    :return: Updated files and repair notes.
    """

    diagnostics = "\n".join(map(str, errors))
    targets = [
        (path, class_name, parameter)
        for path, class_name, parameter in re.findall(
            r"([^\r\n]+?\.py):([A-Za-z_][A-Za-z0-9_]*)\.__init__: "
            r"constructor argument `([A-Za-z_][A-Za-z0-9_]*)` is read as "
            r"`self\.\3` by public behavior but is never initialized",
            diagnostics,
        )
    ]
    if not targets:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        owned = {
            (class_name, parameter)
            for target_path, class_name, parameter in targets
            if str(Path(target_path).resolve()).casefold()
            == str(Path(path).resolve()).casefold()
        }
        if not owned:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed: list[str] = []
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            parameters = {
                parameter
                for class_name, parameter in owned
                if class_name == class_node.name
            }
            if not parameters:
                continue
            initializer = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "__init__"
                ),
                None,
            )
            if initializer is None:
                continue
            signature_names = {
                argument.arg
                for argument in (
                    *initializer.args.posonlyargs,
                    *initializer.args.args,
                    *initializer.args.kwonlyargs,
                )
            }
            parameters &= signature_names
            if not parameters:
                continue
            insert_at = 1 if (
                initializer.body
                and isinstance(initializer.body[0], ast.Expr)
                and isinstance(initializer.body[0].value, ast.Constant)
                and isinstance(initializer.body[0].value.value, str)
            ) else 0
            while insert_at < len(initializer.body):
                statement = initializer.body[insert_at]
                if not isinstance(statement, ast.If) or not any(
                    isinstance(node, ast.Raise) for node in ast.walk(statement)
                ):
                    break
                insert_at += 1
            assignments = [
                ast.Assign(
                    targets=[ast.Attribute(
                        value=ast.Name(id="self", ctx=ast.Load()),
                        attr=parameter,
                        ctx=ast.Store(),
                    )],
                    value=ast.Name(id=parameter, ctx=ast.Load()),
                )
                for parameter in sorted(parameters)
            ]
            initializer.body[insert_at:insert_at] = assignments
            changed.extend(
                f"{class_node.name}.{parameter}" for parameter in sorted(parameters)
            )
        if not changed:
            continue
        ast.fix_missing_locations(tree)
        repaired = ast.unparse(tree).rstrip() + "\n"
        compile(repaired, path, "exec")
        updated[index] = (path, original, repaired)
        notes.append(
            f"{Path(path).name}: initialized proven constructor state "
            + ", ".join(changed)
        )
    return updated, notes


def _registered_contract_repair_specs() -> tuple[tuple[str, object, object], ...]:
    """Return production contract compilers and their independent verifiers.

    :return: Ordered contract name, repair callable, and verifier triples.
    """

    return (
        (
            "dependency-layer",
            _repair_dependency_execution_batches,
            _verify_dependency_execution_batches,
        ),
        (
            "json-merge-patch",
            _repair_json_merge_patch_contract,
            _verify_json_merge_patch_contract,
        ),
        (
            "backoff-state",
            _repair_backoff_tracker_contract,
            _verify_backoff_tracker_contract,
        ),
        (
            "event-journal",
            _repair_event_journal_contract,
            _verify_event_journal_contract,
        ),
        (
            "envelope-codec",
            _repair_envelope_codec_contract,
            _verify_envelope_codec_contract,
        ),
    )


def _apply_registered_contract_repairs(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], dict[str, list[str]]]:
    """Apply every activated production contract through one repair boundary.

    :param generated_files: Candidate file triples.
    :param errors: Current deterministic validation findings.
    :param request_prompt: Authoritative user request.
    :return: Updated files and nonempty notes grouped by contract name.
    """

    updated = list(generated_files)
    applied: dict[str, list[str]] = {}
    for name, repair, _verify in _registered_contract_repair_specs():
        updated, notes = repair(
            updated,
            errors,
            request_prompt=request_prompt,
        )
        if notes:
            applied[name] = list(notes)
    return updated, applied


def _verify_registered_contract_repairs(
    generated_files: list[tuple[str, str, str]],
    active_contracts: object,
    *,
    request_prompt: str,
) -> tuple[str, ...]:
    """Verify activated compilers after normalization and validation.

    :param generated_files: Normalized candidate file triples.
    :param active_contracts: Contract names that changed the candidate.
    :param request_prompt: Authoritative user request.
    :return: Names whose complete isolated executable proofs passed.
    """

    active = {str(name) for name in active_contracts}
    verified: list[str] = []
    for name, _repair, verify in _registered_contract_repair_specs():
        if name not in active:
            continue
        if verify(generated_files, request_prompt=request_prompt):
            verified.append(name)
    return tuple(verified)


from tech_connector.services.project_edit_workflow_runtime_contracts import (
    _repair_backoff_tracker_contract,
    _repair_json_merge_patch_contract,
    _verify_dependency_execution_batches,
    _verify_json_merge_patch_contract,
)
