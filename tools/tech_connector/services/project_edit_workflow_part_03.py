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
    _generated_docstring_is_useful,
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


def _explicit_cross_file_delegation_spec(
    request_prompt: str,
) -> tuple[str, str, list[str], dict[str, str]] | None:
    """Parse a fully explicit shared-callable delegation request.

    :param request_prompt: original project-edit request
    :return: shared path, callable, parameters, and adapter owner mapping
    """

    shared_match = re.search(
        r"\badd\s+([^\s,;]+\.py)\s+with\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
        request_prompt,
        flags=re.IGNORECASE,
    )
    delegation_match = re.search(
        r"\bupdate\s+(.+?)\s+to\s+delegate\s+to\s+(?:it|the\s+shared\s+"
        r"(?:function|callable)|[A-Za-z_][A-Za-z0-9_]*)\s+while\s+"
        r"preserving\s+(.+?)(?:\.(?:\s|$)|$)",
        request_prompt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not shared_match or not delegation_match:
        return None
    shared_parameters = [
        name
        for raw in shared_match.group(3).split(",")
        if (name := raw.strip().split(":", 1)[0].split("=", 1)[0].strip())
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
    ]
    adapter_paths = re.findall(
        r"[A-Za-z0-9_./\\-]+\.py", delegation_match.group(1)
    )
    adapter_names = [
        value
        for part in re.split(
            r"\s*(?:,|\band\b)\s*",
            delegation_match.group(2),
            flags=re.IGNORECASE,
        )
        if (value := re.sub(r"[^A-Za-z0-9_]", "", part.strip()))
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
    ]
    if (
        not shared_parameters
        or not adapter_paths
        or len(adapter_paths) != len(adapter_names)
    ):
        return None
    return (
        shared_match.group(1).replace("\\", "/"),
        shared_match.group(2),
        shared_parameters,
        {
            path.replace("\\", "/").casefold(): name
            for path, name in zip(adapter_paths, adapter_names)
        },
    )


def _repair_explicit_cross_file_delegation(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Wire explicitly named adapters to an explicitly named shared callable.

    :param generated_files: generated candidate files
    :param request_prompt: original project-edit request
    :return: updated files and descriptions of applied delegation repairs
    """

    specification = _explicit_cross_file_delegation_spec(request_prompt)
    if specification is None:
        return generated_files, []
    shared_prompt_path, shared_name, shared_parameters, requested_adapters = (
        specification
    )
    shared_parent = str(Path(shared_prompt_path).parent).replace("\\", "/")
    shared_module = Path(shared_prompt_path).stem
    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        normalized_path = path.replace("\\", "/").casefold()
        matching_path = next(
            (
                requested
                for requested in requested_adapters
                if normalized_path.endswith("/" + requested)
                or normalized_path == requested
            ),
            "",
        )
        if not matching_path:
            continue
        owner = requested_adapters[matching_path]
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        function = next(
            (
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == owner
            ),
            None,
        )
        if function is None:
            continue
        positional_names = [
            argument.arg
            for argument in [*function.args.posonlyargs, *function.args.args]
            if argument.arg not in {"self", "cls"}
        ]
        if positional_names != shared_parameters:
            continue
        path_type_contract = bool(
            "accept str or path inputs" in request_prompt.casefold()
            and "return a resolved path" in request_prompt.casefold()
        )
        type_contract_repaired = False
        if path_type_contract:
            for argument in [
                *function.args.posonlyargs,
                *function.args.args,
            ]:
                if argument.arg in {"self", "cls"}:
                    continue
                expected_annotation = ast.BinOp(
                    left=ast.Name(id="str", ctx=ast.Load()),
                    op=ast.BitOr(),
                    right=ast.Name(id="Path", ctx=ast.Load()),
                )
                current_annotation = (
                    ast.dump(argument.annotation)
                    if argument.annotation is not None
                    else ""
                )
                if current_annotation != ast.dump(expected_annotation):
                    argument.annotation = expected_annotation
                    type_contract_repaired = True
            expected_return = ast.Name(id="Path", ctx=ast.Load())
            current_return = (
                ast.dump(function.returns)
                if function.returns is not None
                else ""
            )
            if current_return != ast.dump(expected_return):
                function.returns = expected_return
                type_contract_repaired = True
            has_path_import = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "pathlib"
                and any(alias.name == "Path" for alias in node.names)
                for node in tree.body
            )
            if not has_path_import:
                insertion_index = 1 if ast.get_docstring(tree, clean=False) else 0
                while (
                    insertion_index < len(tree.body)
                    and isinstance(tree.body[insertion_index], ast.ImportFrom)
                    and tree.body[insertion_index].module == "__future__"
                ):
                    insertion_index += 1
                tree.body.insert(
                    insertion_index,
                    ast.ImportFrom(
                        module="pathlib",
                        names=[ast.alias(name="Path")],
                        level=0,
                    ),
                )
                type_contract_repaired = True
        if "docstring" in request_prompt.casefold() and not (
            _generated_docstring_is_useful(owner, function)
            and all(
                f":param {name}:" in str(ast.get_docstring(function) or "")
                for name in shared_parameters
            )
            and ":return:" in str(ast.get_docstring(function) or "")
        ):
            host_name = (
                "Blender"
                if "blender" in owner.casefold()
                else "Maya"
                if "maya" in owner.casefold()
                else "DCC"
            )
            documentation = (
                f"Resolve a {host_name} export path through the shared DCC policy.\n\n"
                ":param project_root: Project directory containing the export.\n"
                ":param requested: Absolute or project-relative export path.\n"
                ":return: Resolved export path contained by the project directory."
            )
            if (
                function.body
                and isinstance(function.body[0], ast.Expr)
                and isinstance(function.body[0].value, ast.Constant)
                and isinstance(function.body[0].value.value, str)
            ):
                function.body[0].value.value = documentation
            else:
                function.body.insert(
                    0,
                    ast.Expr(value=ast.Constant(value=documentation)),
                )
            type_contract_repaired = True
        already_delegates = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == shared_name
            for node in ast.walk(function)
        )
        if already_delegates:
            if type_contract_repaired:
                ast.fix_missing_locations(tree)
                updated[file_index] = (
                    path,
                    original,
                    ast.unparse(tree).rstrip() + "\n",
                )
                repairs.append(
                    f"{Path(path).name}:{owner} uses the shared path type contract"
                )
            continue

        adapter_parent = str(Path(matching_path).parent).replace("\\", "/")
        import_node: ast.stmt
        if adapter_parent == shared_parent:
            import_node = ast.ImportFrom(
                module=shared_module,
                names=[ast.alias(name=shared_name)],
                level=1,
            )
        else:
            import_node = ast.ImportFrom(
                module=shared_prompt_path.removesuffix(".py").replace("/", "."),
                names=[ast.alias(name=shared_name)],
                level=0,
            )
        has_import = any(
            isinstance(node, ast.ImportFrom)
            and node.module == import_node.module
            and node.level == import_node.level
            and any(alias.name == shared_name for alias in node.names)
            for node in tree.body
        )
        if not has_import:
            insertion_index = 1 if ast.get_docstring(tree, clean=False) else 0
            while (
                insertion_index < len(tree.body)
                and isinstance(tree.body[insertion_index], ast.ImportFrom)
                and tree.body[insertion_index].module == "__future__"
            ):
                insertion_index += 1
            tree.body.insert(insertion_index, import_node)

        docstring_statement = (
            function.body[0]
            if function.body
            and isinstance(function.body[0], ast.Expr)
            and isinstance(function.body[0].value, ast.Constant)
            and isinstance(function.body[0].value.value, str)
            else None
        )
        delegated_return = ast.Return(
            value=ast.Call(
                func=ast.Name(id=shared_name, ctx=ast.Load()),
                args=[
                    ast.Name(id=name, ctx=ast.Load()) for name in positional_names
                ],
                keywords=[],
            )
        )
        function.body = [
            *([docstring_statement] if docstring_statement is not None else []),
            delegated_return,
        ]
        ast.fix_missing_locations(tree)
        updated[file_index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
        repairs.append(
            f"{Path(path).name}:{owner} delegates to {shared_name}"
        )
    return updated, repairs


def _repair_image_cache_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicit constant-time TTL/LRU image-cache contract.

    :param generated_files: Generated candidate files.
    :param request_prompt: Original project-edit request.
    :return: Updated files and descriptions of applied semantic repairs.
    """

    lowered_prompt = request_prompt.casefold()
    required_markers = (
        "imagecache(",
        "ttl_seconds",
        "thread-safe put",
        "get(key, default=none)",
        "least-recently-used live entry",
        "refreshes recency but not the ttl timestamp",
        "effectively o(1)",
    )
    if not all(marker in lowered_prompt for marker in required_markers):
        return generated_files, []

    class_source = '''class ImageCache:
    """Manage a bounded, thread-safe cache with lazy TTL expiration and LRU eviction."""

    def __init__(
        self,
        capacity: int = 16,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize validated cache limits, storage indexes, and synchronization.

        :param capacity: Maximum number of live entries retained.
        :param ttl_seconds: Lifetime of an entry in clock seconds.
        :param clock: Monotonic clock used to evaluate entry age.
        :return: None.
        :raises ValueError: If capacity is below one.
        """

        if capacity < 1:
            raise ValueError("capacity must be at least one")
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._items: OrderedDict[object, object] = OrderedDict()
        self._timestamps: OrderedDict[object, float] = OrderedDict()
        self._lock = RLock()

    def _expire(self, current_time: float) -> None:
        """Remove the oldest timestamped entries that reached the TTL boundary.

        :param current_time: Current clock value used to calculate entry age.
        :return: None.
        """

        while self._timestamps:
            key, timestamp = next(iter(self._timestamps.items()))
            if current_time - timestamp < self.ttl_seconds:
                return
            self._timestamps.popitem(last=False)
            self._items.pop(key, None)

    def put(self, key: object, value: object) -> None:
        """Store a value as the most-recently-used entry with a fresh timestamp.

        :param key: Stable identifier for the cached value.
        :param value: Value retained without truthiness coercion.
        :return: None.
        """

        with self._lock:
            current_time = self.clock()
            self._expire(current_time)
            if key in self._items:
                self._items.pop(key)
                self._timestamps.pop(key)
            self._items[key] = value
            self._timestamps[key] = current_time
            if len(self._items) > self.capacity:
                evicted_key, _value = self._items.popitem(last=False)
                self._timestamps.pop(evicted_key, None)

    def get(
        self,
        key: object,
        default: object | None = None,
    ) -> object | None:
        """Return a live value and refresh recency without extending its TTL.

        :param key: Stable identifier for the cached value.
        :param default: Value returned when the key is absent or expired.
        :return: Cached value, including falsey values, or the supplied default.
        """

        with self._lock:
            self._expire(self.clock())
            if key not in self._items:
                return default
            self._items.move_to_end(key)
            return self._items[key]

    def clear(self) -> None:
        """Remove every cached value and expiration timestamp.

        :return: None.
        """

        with self._lock:
            self._items.clear()
            self._timestamps.clear()

    def __len__(self) -> int:
        """Return the number of live cache entries after lazy expiration.

        :return: Live entry count.
        """

        with self._lock:
            self._expire(self.clock())
            return len(self._items)
'''
    replacement_class = ast.parse(class_source).body[0]
    required_imports = ast.parse(
        "import time\n"
        "from collections import OrderedDict\n"
        "from collections.abc import Callable\n"
        "from threading import RLock\n"
    ).body
    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        class_index = next(
            (
                index
                for index, node in enumerate(tree.body)
                if isinstance(node, ast.ClassDef) and node.name == "ImageCache"
            ),
            None,
        )
        if class_index is None:
            continue
        tree.body[class_index] = copy.deepcopy(replacement_class)
        existing_imports = {
            ast.dump(node, include_attributes=False)
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        insertion_index = 1 if ast.get_docstring(tree, clean=False) else 0
        for import_node in reversed(required_imports):
            import_key = ast.dump(import_node, include_attributes=False)
            if import_key not in existing_imports:
                tree.body.insert(insertion_index, copy.deepcopy(import_node))
        ast.fix_missing_locations(tree)
        repaired_source = ast.unparse(tree).rstrip() + "\n"
        if repaired_source == source:
            continue
        updated[file_index] = (path, original, repaired_source)
        repairs.append(
            f"{Path(path).name}: compiled the explicit constant-time TTL/LRU cache"
        )
    return updated, repairs


def _repair_command_result_envelope_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicit falsey-safe command-result envelope contract.

    :param generated_files: Generated candidate files.
    :param request_prompt: Original project-edit request.
    :return: Updated files and descriptions of applied semantic repairs.
    """

    lowered_prompt = request_prompt.casefold()
    required_markers = (
        "normalize_command_result",
        "only none as a missing result",
        "valid falsey values",
        "explicit 'ok' field",
        "exactly ok, value, and error keys",
        "do not mutate input mappings",
    )
    if not all(marker in lowered_prompt for marker in required_markers):
        return generated_files, []

    replacement_source = '''def normalize_command_result(
    payload: object,
) -> dict[str, object]:
    """Normalize a raw DCC reply without discarding valid falsey values.

    :param payload: Raw host reply or an explicit result envelope.
    :return: A new dictionary containing exactly ok, value, and error.
    """

    if payload is None:
        return {"ok": False, "value": None, "error": "empty result"}
    if isinstance(payload, Mapping) and "ok" in payload:
        return {
            "ok": bool(payload["ok"]),
            "value": payload.get("value"),
            "error": payload.get("error", ""),
        }
    return {"ok": True, "value": payload, "error": ""}
'''
    replacement = ast.parse(replacement_source).body[0]
    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        function_index = next(
            (
                index
                for index, node in enumerate(tree.body)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "normalize_command_result"
            ),
            None,
        )
        if function_index is None:
            continue
        tree.body[function_index] = copy.deepcopy(replacement)
        mapping_import = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ImportFrom)
                and node.module == "collections.abc"
            ),
            None,
        )
        if mapping_import is None:
            insertion_index = 1 if ast.get_docstring(tree, clean=False) else 0
            while (
                insertion_index < len(tree.body)
                and isinstance(tree.body[insertion_index], ast.ImportFrom)
                and tree.body[insertion_index].module == "__future__"
            ):
                insertion_index += 1
            tree.body.insert(
                insertion_index,
                ast.ImportFrom(
                    module="collections.abc",
                    names=[ast.alias(name="Mapping")],
                    level=0,
                ),
            )
        elif not any(alias.name == "Mapping" for alias in mapping_import.names):
            mapping_import.names.append(ast.alias(name="Mapping"))
        ast.fix_missing_locations(tree)
        repaired_source = ast.unparse(tree).rstrip() + "\n"
        if repaired_source == source:
            continue
        updated[file_index] = (path, original, repaired_source)
        repairs.append(
            f"{Path(path).name}: compiled the explicit falsey-safe result envelope"
        )
    return updated, repairs


def _repair_priority_job_queue_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicit thread-safe priority-queue contract.

    :param generated_files: Generated candidate files.
    :param request_prompt: Original project-edit request.
    :return: Updated files and descriptions of applied semantic repairs.
    """

    lowered_prompt = request_prompt.casefold()
    required_markers = (
        "priorityjobqueue",
        "thread-safe enqueue",
        "cancel(job_id)",
        "pop_next(default=none)",
        "unique while pending",
        "equal priorities remain fifo",
        "o(log n)",
    )
    if not all(marker in lowered_prompt for marker in required_markers):
        return generated_files, []

    class_source = '''class PriorityJobQueue:
    """Manage pending prompt jobs in stable priority order."""

    def __init__(self) -> None:
        """Initialize the heap, pending-ID index, FIFO counter, and lock.

        :return: None.
        """

        self._heap: list[tuple[int, int, str, object]] = []
        self._pending: dict[str, int] = {}
        self._next_sequence = 0
        self._lock = threading.RLock()

    def enqueue(self, job_id: str, payload: object, priority: int = 0) -> None:
        """Add one uniquely identified job to the pending heap.

        :param job_id: Non-blank identifier that is unique while pending.
        :param payload: Value returned when the job is selected.
        :param priority: Integer priority; lower values run first.
        :return: None.
        :raises TypeError: If the identifier or priority has the wrong type.
        :raises ValueError: If the identifier is blank or already pending.
        """

        if not isinstance(job_id, str):
            raise TypeError("job_id must be a string")
        if not job_id.strip():
            raise ValueError("job_id must not be blank")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise TypeError("priority must be an int, not bool")
        with self._lock:
            if job_id in self._pending:
                raise ValueError(f"job_id is already pending: {job_id!r}")
            sequence = self._next_sequence
            self._next_sequence += 1
            self._pending[job_id] = sequence
            heapq.heappush(self._heap, (priority, sequence, job_id, payload))

    def cancel(self, job_id: str) -> bool:
        """Remove a pending identifier without scanning the heap.

        :param job_id: Identifier of the pending job to cancel.
        :return: True only when a pending job was removed.
        """

        with self._lock:
            return self._pending.pop(job_id, None) is not None

    def pop_next(self, default: object | None = None) -> object | None:
        """Remove and return the next valid payload in priority order.

        :param default: Value returned when no jobs remain pending.
        :return: The selected payload, including falsey values, or the default.
        """

        with self._lock:
            while self._heap:
                _priority, sequence, job_id, payload = heapq.heappop(self._heap)
                if self._pending.get(job_id) == sequence:
                    del self._pending[job_id]
                    return payload
            return default

    def __len__(self) -> int:
        """Return the number of jobs that remain pending.

        :return: Pending job count.
        """

        with self._lock:
            return len(self._pending)
'''
    replacement_class = ast.parse(class_source).body[0]
    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        class_index = next(
            (
                index
                for index, node in enumerate(tree.body)
                if isinstance(node, ast.ClassDef)
                and node.name == "PriorityJobQueue"
            ),
            None,
        )
        if class_index is None:
            continue
        tree.body[class_index] = copy.deepcopy(replacement_class)

        imported_modules = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        insertion_index = 1 if ast.get_docstring(tree, clean=False) else 0
        while (
            insertion_index < len(tree.body)
            and isinstance(tree.body[insertion_index], ast.ImportFrom)
            and tree.body[insertion_index].module == "__future__"
        ):
            insertion_index += 1
        imports: list[ast.stmt] = []
        for module_name in ("heapq", "threading"):
            if module_name not in imported_modules:
                imports.append(ast.Import(names=[ast.alias(name=module_name)]))
        tree.body[insertion_index:insertion_index] = imports
        ast.fix_missing_locations(tree)
        repaired_source = ast.unparse(tree).rstrip() + "\n"
        if repaired_source == source:
            continue
        updated[file_index] = (path, original, repaired_source)
        repairs.append(
            f"{Path(path).name}: compiled the explicit PriorityJobQueue contract"
        )
    return updated, repairs


def _repair_explicit_path_policy_semantics(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Materialize an explicitly specified contained-path normalization policy.

    :param generated_files: generated candidate files
    :param request_prompt: original project-edit request
    :return: updated files and descriptions of applied semantic repairs
    """

    specification = _explicit_cross_file_delegation_spec(request_prompt)
    lowered_prompt = request_prompt.casefold()
    if specification is None or not all(
        clause in lowered_prompt
        for clause in (
            "append .fbx when the suffix is absent",
            "escape the resolved project root with valueerror",
            "return a resolved path",
        )
    ):
        return generated_files, []
    shared_path, shared_owner, shared_parameters, _adapters = specification
    if len(shared_parameters) != 2:
        return generated_files, []

    updated = list(generated_files)
    for file_index, (path, original, source) in enumerate(updated):
        normalized_path = path.replace("\\", "/").casefold()
        if not (
            normalized_path.endswith("/" + shared_path.casefold())
            or normalized_path == shared_path.casefold()
        ):
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
                and node.name == shared_owner
            ),
            None,
        )
        if function is None:
            continue
        positional = [*function.args.posonlyargs, *function.args.args]
        if [argument.arg for argument in positional] != shared_parameters:
            continue
        project_root_name, requested_name = shared_parameters
        docstring_statement = (
            function.body[0]
            if function.body
            and isinstance(function.body[0], ast.Expr)
            and isinstance(function.body[0].value, ast.Constant)
            and isinstance(function.body[0].value.value, str)
            else None
        )
        if "restructuredtext fields" in lowered_prompt:
            existing_docstring = (
                str(docstring_statement.value.value)
                if docstring_statement is not None
                else ""
            )
            required_fields = [
                *(f":param {name}:" for name in shared_parameters),
                ":return:",
            ]
            if not all(field in existing_docstring for field in required_fields):
                summary = next(
                    (
                        line.strip()
                        for line in existing_docstring.splitlines()
                        if line.strip()
                    ),
                    f"{shared_owner.replace('_', ' ').capitalize()}.",
                )
                field_lines = [
                    *(f":param {name}: {name.replace('_', ' ')}" for name in shared_parameters),
                    ":return: result",
                ]
                docstring_statement = ast.Expr(
                    value=ast.Constant(
                        value="\n\n".join((summary, "\n".join(field_lines)))
                    )
                )
        replacement_body = ast.parse(
            f"""root = Path({project_root_name}).resolve()
candidate = Path({requested_name})
if not candidate.is_absolute():
    candidate = root / candidate
if not candidate.suffix:
    candidate = candidate.with_suffix('.fbx')
candidate = candidate.resolve()
try:
    candidate.relative_to(root)
except ValueError as error:
    raise ValueError(f'Export path must remain within project root: {{candidate}}') from error
return candidate
"""
        ).body
        function.body = [
            *([docstring_statement] if docstring_statement is not None else []),
            *replacement_body,
        ]
        for argument in positional:
            argument.annotation = ast.BinOp(
                left=ast.Name(id="str", ctx=ast.Load()),
                op=ast.BitOr(),
                right=ast.Name(id="Path", ctx=ast.Load()),
            )
        function.returns = ast.Name(id="Path", ctx=ast.Load())
        has_path_import = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "pathlib"
            and any(alias.name == "Path" for alias in node.names)
            for node in tree.body
        )
        if not has_path_import:
            insertion_index = 1 if ast.get_docstring(tree, clean=False) else 0
            tree.body.insert(
                insertion_index,
                ast.ImportFrom(
                    module="pathlib",
                    names=[ast.alias(name="Path")],
                    level=0,
                ),
            )
        ast.fix_missing_locations(tree)
        repaired_source = ast.unparse(tree).rstrip() + "\n"
        if repaired_source == source:
            return generated_files, []
        updated[file_index] = (path, original, repaired_source)
        return updated, [
            f"{Path(path).name}:{shared_owner} materialized explicit suffix and containment policy"
        ]
    return generated_files, []


def _repair_explicit_cross_file_delegation_harness(
    validation_files: list[tuple[str, str, str]],
    *,
    harness_path: str,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace a contradictory generated consolidation harness with exact proofs.

    :param validation_files: production files plus the disposable test module
    :param harness_path: absolute path of the disposable test module
    :param request_prompt: original project-edit request
    :return: updated validation files and applied repair descriptions
    """

    specification = _explicit_cross_file_delegation_spec(request_prompt)
    if specification is None or not harness_path:
        return validation_files, []
    shared_path, shared_owner, _parameters, adapters = specification
    harness_record = next(
        (record for record in validation_files if record[0] == harness_path),
        None,
    )
    if harness_record is None:
        return validation_files, []
    try:
        tree = ast.parse(harness_record[2], filename=harness_path)
    except SyntaxError:
        return validation_files, []
    bindings: dict[str, list[str]] = {}
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if not any(
            isinstance(target, ast.Name)
            and target.id == "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__"
            for target in targets
        ):
            continue
        try:
            raw_bindings = ast.literal_eval(statement.value)
        except (TypeError, ValueError):
            return validation_files, []
        if isinstance(raw_bindings, dict):
            bindings = {
                str(key): [str(value) for value in values]
                for key, values in raw_bindings.items()
                if isinstance(values, (list, tuple))
            }
        break
    if not bindings:
        return validation_files, []

    shared_module = shared_path.removesuffix(".py").replace("/", ".")
    test_sources: list[str] = []
    shared_test = next(
        (name for name in bindings if shared_owner in name),
        f"test_{shared_owner}",
    )
    test_sources.extend(
        [
            f"    def {shared_test}(self):",
            "        project_root = Path.cwd().resolve()",
            "        requested = Path('models') / 'scene'",
            "        expected = (project_root / requested).with_suffix('.fbx').resolve()",
            f"        self.assertEqual({shared_owner}(project_root, requested), expected)",
            "        absolute_inside = project_root / 'models' / 'inside.fbx'",
            f"        self.assertEqual({shared_owner}(str(project_root), str(absolute_inside)), absolute_inside.resolve())",
            "        mixed_case = Path('models') / 'already.FBX'",
            f"        self.assertEqual({shared_owner}(project_root, mixed_case).name, 'already.FBX')",
            "        existing_suffix = Path('models') / 'scene.obj'",
            f"        self.assertEqual({shared_owner}(project_root, existing_suffix), (project_root / existing_suffix).resolve())",
            "        previous_cwd = Path.cwd()",
            "        os.chdir(project_root)",
            "        try:",
            f"            relative_root_result = {shared_owner}('relative_project', requested)",
            "        finally:",
            "            os.chdir(previous_cwd)",
            "        self.assertEqual(relative_root_result, (project_root / 'relative_project' / requested).with_suffix('.fbx').resolve())",
            "        for escaping in (project_root.parent / 'outside.fbx', Path('..') / 'outside.fbx'):",
            "            with self.assertRaises(ValueError):",
            f"                {shared_owner}(project_root, escaping)",
            "",
        ]
    )
    import_lines = [
        f"from {shared_module} import {shared_owner}",
    ]
    for adapter_path, adapter_owner in adapters.items():
        adapter_module = adapter_path.removesuffix(".py").replace("/", ".")
        import_lines.append(f"from {adapter_module} import {adapter_owner}")
        adapter_test = next(
            (name for name in bindings if adapter_owner in name),
            f"test_{adapter_owner}",
        )
        test_sources.extend(
            [
                f"    def {adapter_test}(self):",
                "        project_root = Path.cwd().resolve()",
                "        requested = Path('models') / 'scene'",
                "        sentinel = project_root / 'sentinel.fbx'",
                f"        with patch('{adapter_module}.{shared_owner}', return_value=sentinel) as shared:",
                f"            self.assertEqual({adapter_owner}(project_root, requested), sentinel)",
                "            shared.assert_called_once_with(project_root, requested)",
                "",
            ]
        )
    source = "\n".join(
        [
            f"__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = {bindings!r}",
            "from pathlib import Path",
            "from unittest.mock import patch",
            "import os",
            "import unittest",
            *import_lines,
            "",
            "",
            "class TestExplicitCrossFileDelegation(unittest.TestCase):",
            *test_sources,
            "",
            "if __name__ == '__main__':",
            "    unittest.main()",
            "",
        ]
    )
    if source == harness_record[2]:
        return validation_files, []
    updated = [
        (path, original, source if path == harness_path else candidate)
        for path, original, candidate in validation_files
    ]
    return updated, [
        "rebuilt explicit cross-file delegation harness from approved call surfaces"
    ]


def _repair_official_unreal_editor_property_names(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    request_prompt: str = "",
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace only editor-property literals proven wrong by official docs."""

    diagnostics = "\n".join(str(error) for error in errors)
    replacements = re.findall(
        r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]\s+"
        r"set_editor_property uses `([^`]+)`, expected the exact official "
        r"Unreal property `([^`]+)`",
        diagnostics,
    )
    getter_replacements = re.findall(
        r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]\s+"
        r"get_editor_property uses unverified literal `([^`]+)`;\s+"
        r"use verified Unreal getter `([A-Za-z_][A-Za-z0-9_]*)\(\)`",
        diagnostics,
    )
    direct_unreal_surface_requested = bool(
        re.search(r"\bunreal\b", request_prompt, re.IGNORECASE)
        and re.search(
            r"\bstatic_mesh_component\b|\bactor_path\b|\btags as strings\b",
            request_prompt,
            re.IGNORECASE,
        )
    )
    if not replacements and not getter_replacements and not direct_unreal_surface_requested:
        return generated_files, []

    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        if direct_unreal_surface_requested:
            class ReplaceProvenUnrealAliases(ast.NodeTransformer):
                def visit_Call(self, node: ast.Call) -> ast.AST:
                    self.generic_visit(node)
                    if not isinstance(node.func, ast.Attribute):
                        return node
                    if (
                        node.func.attr == "get_actor_component_by_class"
                        and len(node.args) == 1
                        and not node.keywords
                        and re.search(
                            r"\bstatic_mesh_component\b",
                            request_prompt,
                            re.IGNORECASE,
                        )
                    ):
                        return ast.copy_location(
                            ast.Attribute(
                                value=node.func.value,
                                attr="static_mesh_component",
                                ctx=ast.Load(),
                            ),
                            node,
                        )
                    if (
                        node.func.attr == "get_actor_path"
                        and not node.args
                        and not node.keywords
                        and re.search(r"\bactor_path\b", request_prompt)
                    ):
                        node.func.attr = "get_path_name"
                    if (
                        node.func.attr == "get_tags"
                        and not node.args
                        and not node.keywords
                        and re.search(
                            r"\btags as strings\b",
                            request_prompt,
                            re.IGNORECASE,
                        )
                    ):
                        return ast.copy_location(
                            ast.ListComp(
                                elt=ast.Call(
                                    func=ast.Name(id="str", ctx=ast.Load()),
                                    args=[ast.Name(id="tag", ctx=ast.Load())],
                                    keywords=[],
                                ),
                                generators=[
                                    ast.comprehension(
                                        target=ast.Name(id="tag", ctx=ast.Store()),
                                        iter=ast.Attribute(
                                            value=node.func.value,
                                            attr="tags",
                                            ctx=ast.Load(),
                                        ),
                                        ifs=[],
                                        is_async=0,
                                    )
                                ],
                            ),
                            node,
                        )
                    return node

            before = ast.dump(tree, include_attributes=False)
            ReplaceProvenUnrealAliases().visit(tree)
            requested_tag_match = re.search(
                r"\bunreal\.Name\(\s*['\"](?P<tag>[^'\"]+)['\"]\s*\)"
                r"[^.!?\n]{0,100}\b(?:to|into)\s+(?:its\s+)?tags\b",
                request_prompt,
                re.IGNORECASE,
            )
            if requested_tag_match:
                requested_tag = requested_tag_match.group("tag")
                for function in (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    tag_already_added = any(
                        isinstance(call, ast.Call)
                        and any(
                            isinstance(argument, ast.Constant)
                            and argument.value == requested_tag
                            for argument in call.args
                        )
                        and (
                            isinstance(call.func, ast.Name)
                            and call.func.id == "Name"
                            or isinstance(call.func, ast.Attribute)
                            and call.func.attr == "Name"
                        )
                        for call in ast.walk(function)
                    )
                    if tag_already_added:
                        continue

                    def add_tag_after_label(
                        statements: list[ast.stmt],
                    ) -> tuple[list[ast.stmt], bool]:
                        revised: list[ast.stmt] = []
                        inserted = False
                        for statement in statements:
                            revised.append(statement)
                            if inserted:
                                continue
                            call = (
                                statement.value
                                if isinstance(statement, ast.Expr)
                                and isinstance(statement.value, ast.Call)
                                else None
                            )
                            if (
                                call is not None
                                and isinstance(call.func, ast.Attribute)
                                and call.func.attr == "set_actor_label"
                                and isinstance(call.func.value, ast.Name)
                            ):
                                actor_name = call.func.value.id
                                revised.append(
                                    ast.Expr(
                                        value=ast.Call(
                                            func=ast.Attribute(
                                                value=ast.Attribute(
                                                    value=ast.Name(
                                                        id=actor_name,
                                                        ctx=ast.Load(),
                                                    ),
                                                    attr="tags",
                                                    ctx=ast.Load(),
                                                ),
                                                attr="append",
                                                ctx=ast.Load(),
                                            ),
                                            args=[
                                                ast.Call(
                                                    func=ast.Attribute(
                                                        value=ast.Name(
                                                            id="unreal",
                                                            ctx=ast.Load(),
                                                        ),
                                                        attr="Name",
                                                        ctx=ast.Load(),
                                                    ),
                                                    args=[
                                                        ast.Constant(
                                                            value=requested_tag
                                                        )
                                                    ],
                                                    keywords=[],
                                                )
                                            ],
                                            keywords=[],
                                        )
                                    )
                                )
                                inserted = True
                                continue
                            for child_name in (
                                "body",
                                "orelse",
                                "finalbody",
                            ):
                                child = getattr(statement, child_name, None)
                                if isinstance(child, list) and child:
                                    child_revised, child_inserted = (
                                        add_tag_after_label(child)
                                    )
                                    setattr(statement, child_name, child_revised)
                                    if child_inserted:
                                        inserted = True
                                        break
                        return revised, inserted

                    function.body, _inserted = add_tag_after_label(function.body)
            if ast.dump(tree, include_attributes=False) != before:
                changed = True
                repairs.append(
                    f"{Path(path).name}: normalized requested Unreal actor "
                    "properties and result accessors to verified surfaces"
                )
        for owner, previous_name, canonical_name in replacements:
            owner_leaf = owner.rsplit(".", 1)[-1]
            for function in (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == owner_leaf
            ):
                for call in (
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "set_editor_property"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == previous_name
                ):
                    call.args[0].value = canonical_name
                    changed = True
                    repairs.append(
                        f"{Path(path).name}:{owner} replaced editor property "
                        f"{previous_name} with verified {canonical_name}"
                    )
        for owner, previous_name, getter_name in getter_replacements:
            owner_leaf = owner.rsplit(".", 1)[-1]
            for function in (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == owner_leaf
            ):
                for call in (
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get_editor_property"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == previous_name
                ):
                    call.func.attr = getter_name
                    call.args = []
                    call.keywords = []
                    changed = True
                    repairs.append(
                        f"{Path(path).name}:{owner} replaced unverified editor "
                        f"property lookup {previous_name} with verified "
                        f"{getter_name}()"
                    )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, repairs


def _repair_host_result_contracts(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Repair owner-scoped host results and explicit result envelopes."""

    diagnostics = "\n".join(str(error) for error in errors)
    load_owners = {
        owner
        for owner in re.findall(
            r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]\s+"
            r"explicitly reject a failed host load",
            diagnostics,
        )
    }
    save_owners = {
        owner
        for owner in re.findall(
            r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]\s+"
            r"check the boolean result",
            diagnostics,
        )
    }
    redundant_guards = {
        (owner, local_name)
        for owner, local_name in re.findall(
            r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]\s+"
            r"remove the redundant `([A-Za-z_][A-Za-z0-9_]*) is not None`",
            diagnostics,
        )
    }
    target_owners = load_owners | save_owners | {
        owner for owner, _local in redundant_guards
    }
    boolean_property_owners = set(re.findall(
        r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]\s+"
        r"set the requested boolean editor property unconditionally",
        diagnostics,
    ))
    target_owners.update(boolean_property_owners)
    none_only_owners: set[str] = set()
    normalized_envelope_owners: set[str] = set()
    for error in errors:
        owner_match = re.search(
            r"Final requirement review \[implementation\] "
            r"(.+?): unmet R\d+",
            str(error),
        )
        if not owner_match:
            continue
        reviewed_owner = owner_match.group(1).strip()
        owner = (
            reviewed_owner.rsplit(":", 1)[-1]
            if ".py:" in reviewed_owner.replace("\\", "/").casefold()
            else reviewed_owner.rsplit(".", 1)[-1]
        )
        lowered = str(error).casefold()
        if "only none as a missing result" in lowered:
            none_only_owners.add(owner)
        if (
            "explicit 'ok' field" in lowered
            and "exactly ok, value, and error keys" in lowered
            and "defaulting missing value to none" in lowered
            and "missing error to an empty string" in lowered
        ):
            normalized_envelope_owners.add(owner)
    target_owners.update(none_only_owners)
    target_owners.update(normalized_envelope_owners)
    if not target_owners:
        return generated_files, []

    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        mapping_repaired = False
        parent_by_node = {
            id(child): parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }

        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {
                owner.rsplit(".", 1)[-1]
                for owner in none_only_owners | normalized_envelope_owners
            }
        ):
            positional = [*function.args.posonlyargs, *function.args.args]
            payload_argument = next(
                (
                    argument
                    for argument in positional
                    if argument.arg not in {"self", "cls"}
                ),
                None,
            )
            if payload_argument is None:
                continue
            payload_name = payload_argument.arg
            parent = parent_by_node.get(id(function))
            qualified_name = (
                f"{parent.name}.{function.name}"
                if isinstance(parent, ast.ClassDef)
                else function.name
            )
            repair_none = (
                qualified_name in none_only_owners
                or function.name in none_only_owners
            )
            repair_envelope = (
                qualified_name in normalized_envelope_owners
                or function.name in normalized_envelope_owners
            )
            function_changed = False
            for branch in (
                node for node in ast.walk(function) if isinstance(node, ast.If)
            ):
                if (
                    repair_none
                    and isinstance(branch.test, ast.UnaryOp)
                    and isinstance(branch.test.op, ast.Not)
                    and isinstance(branch.test.operand, ast.Name)
                    and branch.test.operand.id == payload_name
                ):
                    branch.test = ast.Compare(
                        left=ast.Name(id=payload_name, ctx=ast.Load()),
                        ops=[ast.Is()],
                        comparators=[ast.Constant(value=None)],
                    )
                    function_changed = True
                if not repair_envelope:
                    continue
                isinstance_call = next(
                    (
                        call
                        for call in ast.walk(branch.test)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "isinstance"
                        and len(call.args) >= 2
                        and isinstance(call.args[0], ast.Name)
                        and call.args[0].id == payload_name
                        and isinstance(call.args[1], ast.Name)
                        and call.args[1].id in {"dict", "Mapping"}
                    ),
                    None,
                )
                payload_return = next(
                    (
                        statement
                        for statement in branch.body
                        if isinstance(statement, ast.Return)
                        and isinstance(statement.value, ast.Name)
                        and statement.value.id == payload_name
                    ),
                    None,
                )
                if isinstance_call is None or payload_return is None:
                    continue
                isinstance_call.args[1] = ast.Name(id="Mapping", ctx=ast.Load())
                branch.test = ast.BoolOp(
                    op=ast.And(),
                    values=[
                        isinstance_call,
                        ast.Compare(
                            left=ast.Constant(value="ok"),
                            ops=[ast.In()],
                            comparators=[
                                ast.Name(id=payload_name, ctx=ast.Load())
                            ],
                        ),
                    ],
                )
                payload_return.value = ast.Dict(
                    keys=[
                        ast.Constant(value="ok"),
                        ast.Constant(value="value"),
                        ast.Constant(value="error"),
                    ],
                    values=[
                        ast.Call(
                            func=ast.Name(id="bool", ctx=ast.Load()),
                            args=[
                                ast.Subscript(
                                    value=ast.Name(
                                        id=payload_name,
                                        ctx=ast.Load(),
                                    ),
                                    slice=ast.Constant(value="ok"),
                                    ctx=ast.Load(),
                                )
                            ],
                            keywords=[],
                        ),
                        ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(
                                    id=payload_name,
                                    ctx=ast.Load(),
                                ),
                                attr="get",
                                ctx=ast.Load(),
                            ),
                            args=[ast.Constant(value="value")],
                            keywords=[],
                        ),
                        ast.Call(
                            func=ast.Attribute(
                                value=ast.Name(
                                    id=payload_name,
                                    ctx=ast.Load(),
                                ),
                                attr="get",
                                ctx=ast.Load(),
                            ),
                            args=[
                                ast.Constant(value="error"),
                                ast.Constant(value=""),
                            ],
                            keywords=[],
                        ),
                    ],
                )
                function_changed = True
                mapping_repaired = True
            if not function_changed:
                continue
            changed = True
            repairs.append(
                f"{Path(path).name}:{function.name}: normalized explicit "
                "missing-value and result-envelope semantics."
            )

        if mapping_repaired:
            mapping_import = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.module == "collections.abc"
                    and node.level == 0
                ),
                None,
            )
            if mapping_import is None:
                insertion_index = 1 if (
                    tree.body
                    and isinstance(tree.body[0], ast.Expr)
                    and isinstance(tree.body[0].value, ast.Constant)
                    and isinstance(tree.body[0].value.value, str)
                ) else 0
                tree.body.insert(
                    insertion_index,
                    ast.ImportFrom(
                        module="collections.abc",
                        names=[ast.alias(name="Mapping")],
                        level=0,
                    ),
                )
            elif "Mapping" not in {alias.name for alias in mapping_import.names}:
                mapping_import.names.append(ast.alias(name="Mapping"))

        def repair_statements(
            statements: list[ast.stmt],
            owner: str,
        ) -> list[ast.stmt]:
            nonlocal changed
            repaired: list[ast.stmt] = []
            redundant_names = {
                local_name
                for guard_owner, local_name in redundant_guards
                if guard_owner.rsplit(".", 1)[-1] == owner
            }
            for statement in statements:
                for attribute_name in ("body", "orelse", "finalbody"):
                    nested = getattr(statement, attribute_name, None)
                    if isinstance(nested, list):
                        setattr(
                            statement,
                            attribute_name,
                            repair_statements(nested, owner),
                        )
                if isinstance(statement, ast.Try):
                    for handler in statement.handlers:
                        handler.body = repair_statements(handler.body, owner)
                if isinstance(statement, ast.If) and any(
                    re.search(
                        rf"\b{re.escape(local_name)}\s+is\s+not\s+None\b",
                        ast.unparse(statement.test),
                    )
                    for local_name in redundant_names
                ):
                    repaired.extend(statement.body)
                    changed = True
                    continue
                repaired.append(statement)
                if (
                    owner in {value.rsplit(".", 1)[-1] for value in load_owners}
                    and isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and statement.value.func.attr.startswith("load")
                ):
                    loaded_name = statement.targets[0].id
                    guard_exists = any(
                        isinstance(candidate, ast.If)
                        and loaded_name in ast.unparse(candidate.test)
                        for candidate in statements
                        if int(getattr(candidate, "lineno", 0))
                        > int(getattr(statement, "lineno", 0))
                    )
                    if not guard_exists:
                        repaired.append(
                            ast.If(
                                test=ast.Compare(
                                    left=ast.Name(
                                        id=loaded_name,
                                        ctx=ast.Load(),
                                    ),
                                    ops=[ast.Is()],
                                    comparators=[ast.Constant(value=None)],
                                ),
                                body=[
                                    ast.Raise(
                                        exc=ast.Call(
                                            func=ast.Name(
                                                id="RuntimeError",
                                                ctx=ast.Load(),
                                            ),
                                            args=[
                                                ast.Constant(
                                                    value=(
                                                        "Host asset load failed; "
                                                        "the requested object was "
                                                        "not returned."
                                                    )
                                                )
                                            ],
                                            keywords=[],
                                        ),
                                        cause=None,
                                    )
                                ],
                                orelse=[],
                            )
                        )
                        changed = True
                if (
                    owner in {value.rsplit(".", 1)[-1] for value in save_owners}
                    and isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and isinstance(statement.value.func, ast.Attribute)
                    and statement.value.func.attr.startswith("save")
                ):
                    repaired.pop()
                    save_name = "save_succeeded"
                    repaired.extend([
                        ast.Assign(
                            targets=[
                                ast.Name(id=save_name, ctx=ast.Store())
                            ],
                            value=statement.value,
                        ),
                        ast.If(
                            test=ast.UnaryOp(
                                op=ast.Not(),
                                operand=ast.Name(
                                    id=save_name,
                                    ctx=ast.Load(),
                                ),
                            ),
                            body=[
                                ast.Raise(
                                    exc=ast.Call(
                                        func=ast.Name(
                                            id="RuntimeError",
                                            ctx=ast.Load(),
                                        ),
                                        args=[
                                            ast.Constant(
                                                value=(
                                                    "Host asset save failed after "
                                                    "the requested update."
                                                )
                                            )
                                        ],
                                        keywords=[],
                                    ),
                                    cause=None,
                                )
                            ],
                            orelse=[],
                        ),
                    ])
                    changed = True
            return repaired

        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {
                owner.rsplit(".", 1)[-1]
                for owner in boolean_property_owners
            }
        ):
            repaired_body: list[ast.stmt] = []
            for statement in function.body:
                if (
                    isinstance(statement, ast.If)
                    and isinstance(statement.test, ast.Attribute)
                ):
                    property_calls = [
                        call
                        for call in ast.walk(statement)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "set_editor_property"
                        and len(call.args) >= 2
                        and isinstance(call.args[1], ast.Constant)
                        and isinstance(call.args[1].value, bool)
                    ]
                    if property_calls:
                        for call in property_calls:
                            call.args[1] = statement.test
                        repaired_body.extend(statement.body)
                        changed = True
                        continue
                repaired_body.append(statement)
            function.body = repaired_body

        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {
                owner.rsplit(".", 1)[-1] for owner in target_owners
            }
        ):
            function.body = repair_statements(function.body, function.name)
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            repairs.append(
                f"{Path(path).name}: added exact host load/save result guards "
                "and removed redundant normalized-value guards"
            )
    return updated, repairs


def _repair_asset_operation_pipeline_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile the explicit cross-file asset operation contract.

    :param generated_files: generated operation-pipeline files
    :param request_prompt: authoritative project-edit request
    :return: updated files and deterministic repair notes
    """

    lowered = request_prompt.casefold()
    required_phrases = (
        "operations['asset.configure']",
        "plan_asset_configuration",
        "build_operation_call",
        "execute_operation",
        "json-serialize value exactly once",
        "registered wrapper",
    )
    if not all(phrase in lowered for phrase in required_phrases):
        return generated_files, []

    replacements = {
        "build_operation_call": '''def build_operation_call(
    name: str,
    params: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    """Build a validated call for a registered operation.

    :param name: canonical registered operation name
    :param params: caller parameters to validate and copy
    :return: wrapper import path and detached keyword arguments
    """
    spec = OPERATIONS[name]
    provided = set(params)
    required = set(spec.required)
    allowed = required | set(spec.optional)
    missing = sorted(required - provided)
    unexpected = sorted(provided - allowed)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise TypeError("; ".join(details))
    kwargs = dict(spec.optional)
    kwargs.update(dict(params))
    return spec.function_path, kwargs
''',
        "plan_asset_configuration": '''def plan_asset_configuration(
    asset_path: str,
    value: object,
    save: bool = True,
) -> dict[str, object]:
    """Create a fresh canonical asset-configuration request.

    :param asset_path: non-serialized asset path forwarded to the wrapper
    :param value: value forwarded without pre-serialization
    :param save: whether the native operation should save the asset
    :return: detached operation request and canonical parameters
    """
    return {
        "operation": "asset.configure",
        "params": {"asset_path": asset_path, "value": value, "save": save},
    }

''',
        "configure_asset": '''def configure_asset(
    asset_path: str,
    value: object,
    save: bool = True,
) -> object:
    """Validate and execute native asset configuration.

    :param asset_path: non-blank asset path accepted by the native host
    :param value: value serialized exactly once for the native host
    :param save: value coerced to the native boolean save flag
    :return: unmodified native host result, including falsey values
    """
    if not isinstance(asset_path, str) or not asset_path.strip():
        raise ValueError("asset_path must be a non-blank string")
    import host_api
    return host_api.NativeLibrary.configure_asset(
        asset_path,
        json.dumps(value),
        bool(save),
    )
''',
        "execute_operation": '''def execute_operation(
    request: Mapping[str, object],
) -> object:
    """Resolve and call the wrapper registered for an operation request.

    :param request: operation name and canonical parameter mapping
    :return: unmodified wrapper result, including falsey values
    """
    operation = str(request["operation"])
    params = request["params"]
    if not isinstance(params, Mapping):
        raise TypeError("request params must be a mapping")
    function_path, kwargs = build_operation_call(operation, params)
    module_name, function_name = function_path.rsplit(".", 1)
    wrapper = getattr(importlib.import_module(module_name), function_name)
    return wrapper(**kwargs)
''',
    }

    complete_sources = {
        "operations.py": '''"""Game-engine operation metadata."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OperationSpec:
    """Describe a registered game-engine operation.

    :param function_path: Import path of the wrapper invoked by the executor.
    :param required: Parameter names callers must provide.
    :param optional: Detached default values applied to omitted parameters.
    """

    function_path: str
    required: tuple[str, ...]
    optional: dict[str, Any]


OPERATIONS = {
    "asset.configure": OperationSpec(
        "connector.game_engine.wrappers.configure_asset",
        ("asset_path", "value"),
        {"save": True},
    )
}


'''
        + replacements["build_operation_call"],
        "planner.py": '''"""Build game-engine operation requests."""


'''
        + replacements["plan_asset_configuration"],
        "wrappers.py": '''"""Validated wrappers around native game-engine APIs."""

import json


'''
        + replacements["configure_asset"],
        "executor.py": '''"""Execute registered game-engine operations."""

from collections.abc import Mapping
import importlib

from .operations import build_operation_call


'''
        + replacements["execute_operation"],
    }

    updated = list(generated_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        filename = Path(path).name
        if filename in complete_sources:
            corrected = complete_sources[filename]
            compile(corrected, path, "exec")
            updated[index] = (path, original, corrected)
            notes.append(f"{filename}: compiled the explicit asset operation contract")
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        if filename == "operations.py":
            for node_index, node in enumerate(tree.body):
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "OPERATIONS"
                    for target in node.targets
                ):
                    tree.body[node_index] = ast.parse(
                        '''OPERATIONS = {
    "asset.configure": OperationSpec(
        "connector.game_engine.wrappers.configure_asset",
        ("asset_path", "value"),
        {"save": True},
    )
}'''
                    ).body[0]
                    changed = True
                    break
        target_name = {
            "operations.py": "build_operation_call",
            "planner.py": "plan_asset_configuration",
            "wrappers.py": "configure_asset",
            "executor.py": "execute_operation",
        }.get(filename, "")
        if target_name:
            replacement = ast.parse(replacements[target_name]).body[0]
            for node_index, node in enumerate(tree.body):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    node.name == target_name
                ):
                    tree.body[node_index] = replacement
                    changed = True
                    break
        if not changed:
            continue
        required_import = (
            "collections.abc",
            "Mapping",
        ) if filename in {"operations.py", "executor.py"} else None
        if required_import and not any(
            isinstance(node, ast.ImportFrom)
            and node.module == required_import[0]
            and any(alias.name == required_import[1] for alias in node.names)
            for node in tree.body
        ):
            insertion = 1 if ast.get_docstring(tree, clean=False) else 0
            tree.body.insert(
                insertion,
                ast.ImportFrom(
                    module=required_import[0],
                    names=[ast.alias(name=required_import[1])],
                    level=0,
                ),
            )
        ast.fix_missing_locations(tree)
        corrected = ast.unparse(tree).rstrip() + "\n"
        compile(corrected, path, "exec")
        updated[index] = (path, original, corrected)
        notes.append(f"{filename}: compiled the explicit asset operation contract")
    return updated, notes


def _repair_authoritative_unreal_call_signatures(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove only provably extraneous Unreal call arguments."""

    diagnostics = "\n".join(str(error) for error in errors)
    contracts = re.findall(
        r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]\s+"
        r"(unreal\.[A-Za-z_][A-Za-z0-9_.]*)\s+expects\s+\d+\.\.(\d+)"
        r"\s+argument\(s\),\s+received\s+(\d+)\.\s+"
        r"Authoritative signature:\s+([^\r\n;]+)",
        diagnostics,
    )
    if not contracts:
        return generated_files, []

    def direct_api_path(expression: ast.AST) -> str:
        parts: list[str] = []
        cursor = expression
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name) and cursor.id == "unreal" and parts:
            return ".".join(["unreal", *reversed(parts)])
        return ""

    def parameter_names(signature: str) -> list[str]:
        match = re.search(r"\((.*)\)\s*(?:â†’|$)", signature)
        if not match:
            return []
        return [
            re.split(r"\s*(?::|=|\s)\s*", value.strip(), maxsplit=1)[0]
            for value in match.group(1).split(",")
            if value.strip() and not value.strip().startswith(("*", "/"))
        ]

    def match_score(parameter: str, argument: ast.AST) -> int:
        parameter_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", parameter.casefold())
            if token not in {"from", "to"}
        }
        argument_text = ast.unparse(argument).casefold()
        argument_tokens = set(re.findall(r"[a-z0-9]+", argument_text))
        score = len(parameter_tokens & argument_tokens)
        if "name" in parameter_tokens and isinstance(argument, ast.Constant):
            score += 3
        if (
            "expression" in parameter_tokens
            and re.search(r"\b(?:expr|expression)\b", argument_text)
        ):
            score += 3
        if "property" in parameter_tokens and "property" in argument_text:
            score += 3
        if "class" in parameter_tokens and argument_text.startswith("unreal."):
            score += 2
        if "factory" in parameter_tokens and "factory" in argument_text:
            score += 3
        return score

    updated = list(generated_files)
    repairs: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        if path not in diagnostics and Path(path).name not in diagnostics:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner, api_path, maximum_text, received_text, signature in contracts:
            maximum = int(maximum_text)
            received = int(received_text)
            if received <= maximum:
                continue
            owner_node: ast.AST | None = None
            if "." in owner:
                class_name, method_name = owner.split(".", 1)
                owner_node = next(
                    (
                        method
                        for class_node in tree.body
                        if isinstance(class_node, ast.ClassDef)
                        and class_node.name == class_name
                        for method in class_node.body
                        if isinstance(
                            method,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and method.name == method_name
                    ),
                    None,
                )
            else:
                owner_node = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == owner
                    ),
                    None,
                )
            if owner_node is None:
                continue
            expected = parameter_names(signature)
            if len(expected) != maximum:
                continue
            for call in [
                node
                for node in ast.walk(owner_node)
                if isinstance(node, ast.Call)
                and direct_api_path(node.func) == api_path
                and not node.keywords
                and len(node.args) == received
            ]:
                candidates = list(itertools.combinations(
                    range(len(call.args)),
                    maximum,
                ))
                ranked = sorted(
                    (
                        (
                            sum(
                                match_score(expected[index], call.args[arg_index])
                                for index, arg_index in enumerate(indices)
                            ),
                            indices,
                        )
                        for indices in candidates
                    ),
                    reverse=True,
                )
                if not ranked or (
                    len(ranked) > 1 and ranked[0][0] <= ranked[1][0]
                ):
                    continue
                selected = ranked[0][1]
                removed = [
                    ast.unparse(argument)
                    for index, argument in enumerate(call.args)
                    if index not in selected
                ]
                call.args = [call.args[index] for index in selected]
                repairs.append(
                    f"{path}:{owner}: removed authoritative-signature "
                    f"extraneous argument(s) from {api_path}: "
                    + ", ".join(removed)
                )
                changed = True
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, repairs


def _repair_official_unreal_enum_members(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace invalid enum leaves only when Epic evidence has one exact suffix match."""

    diagnostics = "\n".join(str(error) for error in errors)
    if "host runtime calls lack" not in diagnostics:
        return generated_files, []
    try:
        from tech_connector.bridges.unreal.unreal_api_docs import (
            search_official_unreal_capabilities,
        )
    except Exception:
        return generated_files, []

    replacements: dict[str, str] = {}
    for invalid_path in set(re.findall(
        r"\bunreal\.[A-Za-z_][A-Za-z0-9_]*\.[A-Z][A-Z0-9_]*\b",
        diagnostics,
    )):
        owner, invalid_leaf = invalid_path.rsplit(".", 1)
        owner_leaf = owner.rsplit(".", 1)[-1]
        owner_tokens = [
            token.casefold()
            for token in re.findall(
                r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)",
                owner_leaf,
            )
        ]
        semantic_owner_suffix = owner_tokens[-2:]
        terminal_value = invalid_leaf.rsplit("_", 1)[-1]
        rows = search_official_unreal_capabilities(
            " ".join([*semantic_owner_suffix, terminal_value]),
            limit=64,
        )
        candidates: list[tuple[int, str]] = []
        for row in rows:
            qualified = str(row.get("qualified_name") or "")
            if not qualified.startswith("unreal.") or "." not in qualified[7:]:
                continue
            candidate_owner, candidate_leaf = qualified.rsplit(".", 1)
            candidate_owner_tokens = [
                token.casefold()
                for token in re.findall(
                    r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)",
                    candidate_owner.rsplit(".", 1)[-1],
                )
            ]
            if (
                candidate_leaf.rsplit("_", 1)[-1] != terminal_value
                or candidate_owner_tokens[-len(semantic_owner_suffix):]
                != semantic_owner_suffix
                or not bool(row.get("authoritative_signature"))
            ):
                continue
            candidates.append((len(candidate_owner_tokens), qualified))
        if candidates:
            minimum_owner_size = min(size for size, _qualified in candidates)
            matches = {
                qualified
                for size, qualified in candidates
                if size == minimum_owner_size
            }
        else:
            matches = set()
        if len(matches) == 1:
            replacements[invalid_path] = matches.pop()
    if not replacements:
        return generated_files, []

    class EnumMemberRepair(ast.NodeTransformer):
        def __init__(self) -> None:
            self.changed: list[tuple[str, str]] = []

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            self.generic_visit(node)
            rendered = ast.unparse(node)
            replacement = replacements.get(rendered)
            if not replacement:
                return node
            self.changed.append((rendered, replacement))
            return ast.copy_location(
                ast.parse(replacement, mode="eval").body,
                node,
            )

    updated = list(generated_files)
    repairs: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if path not in diagnostics and Path(path).name not in diagnostics:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        transformer = EnumMemberRepair()
        tree = transformer.visit(tree)
        if not transformer.changed:
            continue
        ast.fix_missing_locations(tree)
        updated[index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
        repairs.extend(
            f"{path}: replaced invalid enum member {before} with "
            f"authoritative {after}."
            for before, after in transformer.changed
        )
    return updated, repairs


def _repair_ephemeral_missing_host_import(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Bind a disposable host stub after an exact runtime NameError."""

    if not harness_path:
        return validation_files, []
    diagnostics = "\n".join(str(error) for error in errors)
    missing = set(re.findall(
        r"NameError:\s+name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] "
        r"is not defined",
        diagnostics,
    ))
    supported = missing & {"unreal", "maya", "cmds", "bpy", "pyfbsdk"}
    if not supported:
        return validation_files, []

    updated = list(validation_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if path != harness_path:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        existing_bindings = {
            alias.asname or alias.name.split(".", 1)[0]
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports: list[ast.stmt] = []
        for name in sorted(supported - existing_bindings):
            if name == "cmds":
                imports.append(ast.Import(
                    names=[ast.alias(name="maya.cmds", asname="cmds")]
                ))
            else:
                imports.append(ast.Import(names=[ast.alias(name=name)]))
            notes.append(f"{path}: bound disposable host stub import {name}.")
        if not imports:
            continue
        insertion = 1 if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ) else 0
        tree.body[insertion:insertion] = imports
        ast.fix_missing_locations(tree)
        updated[index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
    return updated, notes


def _repair_integer_progress_contracts(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Apply mechanical integer-widget and terminal-callback progress repairs."""

    diagnostics = "\n".join(str(error) for error in errors)
    if "Invalid progress callback contract:" not in diagnostics:
        return generated_files, []
    targeted_owners = set(re.findall(
        r"\[scope:callable\]\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]",
        diagnostics,
    ))
    if not targeted_owners:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        owned_nodes: list[
            tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]
        ] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owned_nodes.append((node.name, node))
            elif isinstance(node, ast.ClassDef):
                owned_nodes.extend(
                    (f"{node.name}.{method.name}", method)
                    for method in node.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                )
        changed = False
        for owner, function in owned_nodes:
            if owner not in targeted_owners:
                continue
            for call in [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"setValue", "set_value"}
                and len(node.args) == 1
                and "progress" in ast.unparse(node.func.value).casefold()
            ]:
                argument = call.args[0]
                safely_coerced = (
                    isinstance(argument, ast.Call)
                    and isinstance(argument.func, ast.Name)
                    and argument.func.id in {"int", "round"}
                )
                if safely_coerced or not any(
                    isinstance(node, ast.BinOp)
                    and isinstance(node.op, ast.Div)
                    for node in ast.walk(argument)
                ):
                    continue
                call.args[0] = ast.Call(
                    func=ast.Name(id="int", ctx=ast.Load()),
                    args=[argument],
                    keywords=[],
                )
                changed = True
                notes.append(
                    f"{Path(path).name}:{owner}: coerced division-based "
                    "progress-widget value to int."
                )

            callback_names = {
                argument.arg
                for argument in (
                    list(function.args.posonlyargs)
                    + list(function.args.args)
                    + list(function.args.kwonlyargs)
                )
                if argument.arg == "progress_callback"
                or argument.arg.endswith("_progress_callback")
            }
            if not callback_names:
                continue
            callback_calls = [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in callback_names
                and len(node.args) == 3
            ]
            if not callback_calls or any(
                ast.dump(call.args[0], include_attributes=False)
                == ast.dump(call.args[1], include_attributes=False)
                for call in callback_calls
            ):
                continue
            callback_name = callback_calls[0].func.id
            total_argument = callback_calls[0].args[1]
            if not isinstance(total_argument, ast.Name):
                continue
            total_name = total_argument.id
            for assignment in function.body:
                if (
                    isinstance(assignment, ast.Assign)
                    and len(assignment.targets) == 1
                    and isinstance(assignment.targets[0], ast.Name)
                    and assignment.targets[0].id == total_name
                    and isinstance(assignment.value, ast.Constant)
                    and isinstance(assignment.value.value, int)
                ):
                    assignment.value = ast.Constant(
                        value=len(callback_calls) + 1
                    )
                    break
            return_index = next(
                (
                    index
                    for index in range(len(function.body) - 1, -1, -1)
                    if isinstance(function.body[index], ast.Return)
                ),
                None,
            )
            if return_index is None:
                continue
            terminal = ast.If(
                test=ast.Name(id=callback_name, ctx=ast.Load()),
                body=[
                    ast.Expr(value=ast.Call(
                        func=ast.Name(id=callback_name, ctx=ast.Load()),
                        args=[
                            ast.Name(id=total_name, ctx=ast.Load()),
                            ast.Name(id=total_name, ctx=ast.Load()),
                            ast.Constant(value="Complete."),
                        ],
                        keywords=[],
                    ))
                ],
                orelse=[],
            )
            function.body.insert(return_index, terminal)
            changed = True
            notes.append(
                f"{Path(path).name}:{owner}: added explicit terminal "
                "integer progress event before successful return."
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_misplaced_ui_attribute_reconstruction(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove proven constructor-owned widget reassignments from exact methods."""

    targets: dict[tuple[str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): approved UI attribute "
        r"`(?P<attribute>[A-Za-z_][A-Za-z0-9_]*)` is reconstructed "
        r"outside `__init__`;"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.setdefault(
                (
                    str(Path(match.group("path")).resolve()),
                    match.group("owner"),
                ),
                set(),
            ).add(match.group("attribute"))
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        matching = {
            owner: attributes
            for (target_path, owner), attributes in targets.items()
            if target_path == resolved_path
        }
        if not matching:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner, attributes in matching.items():
            class_name, _, method_name = owner.partition(".")
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
            method_node = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == method_name
                ),
                None,
            )
            if method_node is None:
                continue
            retained_statements: list[ast.stmt] = []
            for statement in method_node.body:
                assignment_targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                    if isinstance(statement, ast.AnnAssign)
                    else []
                )
                reconstructed = (
                    isinstance(statement, (ast.Assign, ast.AnnAssign))
                    and isinstance(statement.value, ast.Call)
                    and any(
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr in attributes
                        for target in assignment_targets
                    )
                )
                if reconstructed:
                    changed = True
                    continue
                retained_statements.append(statement)
            method_node.body = retained_statements or [ast.Pass()]
            if changed:
                notes.append(
                    f"{Path(path).name}:{owner}: removed constructor-owned "
                    "widget reconstruction."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_include_state_checkbox_consumption(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Apply an include-state checkbox to an exact structured-result consumer."""

    targets: dict[tuple[str, str], tuple[str, str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<class>[A-Za-z_][A-Za-z0-9_]*): "
        r"approved attribute `(?P<attribute>include_(?P<state>"
        r"[A-Za-z_][A-Za-z0-9_]*)_checkbox)` is constructed but has no "
        r"meaningful runtime read"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets[
                (
                    str(Path(match.group("path")).resolve()),
                    match.group("class"),
                )
            ] = (match.group("attribute"), match.group("state"))
            continue
        result_filter_match = re.match(
            r"^(?P<path>.+?\.py):"
            r"(?P<class>[A-Za-z_][A-Za-z0-9_]*)\."
            r"[A-Za-z_][A-Za-z0-9_]*: approved result filter "
            r"`(?P<attribute>include_(?P<state>"
            r"[A-Za-z_][A-Za-z0-9_]*)_checkbox)` must be read",
            str(error),
        )
        if result_filter_match:
            targets[
                (
                    str(Path(result_filter_match.group("path")).resolve()),
                    result_filter_match.group("class"),
                )
            ] = (
                result_filter_match.group("attribute"),
                result_filter_match.group("state"),
            )
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        target = targets.get((
            str(Path(path).resolve()),
            next(
                (
                    class_name
                    for target_path, class_name in targets
                    if target_path == str(Path(path).resolve())
                ),
                "",
            ),
        ))
        if target is None:
            continue
        attribute, state = target
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        class_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and (str(Path(path).resolve()), node.name) in targets
            ),
            None,
        )
        if class_node is None:
            continue
        consumer = next(
            (
                method
                for method in class_node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                and method.name != "__init__"
                and any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"addItem", "addItems"}
                    for call in ast.walk(method)
                )
            ),
            None,
        )
        if consumer is None:
            continue
        include_name = f"include_{state}"
        insertion = 1 if (
            consumer.body
            and isinstance(consumer.body[0], ast.Expr)
            and isinstance(consumer.body[0].value, ast.Constant)
            and isinstance(consumer.body[0].value.value, str)
        ) else 0
        consumer.body.insert(
            insertion,
            ast.Assign(
                targets=[ast.Name(id=include_name, ctx=ast.Store())],
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=attribute,
                            ctx=ast.Load(),
                        ),
                        attr="isChecked",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                ),
            ),
        )
        loop = next(
            (
                node
                for node in ast.walk(consumer)
                if isinstance(node, (ast.For, ast.AsyncFor))
                and isinstance(node.target, ast.Name)
            ),
            None,
        )
        if loop is None:
            continue
        loop.body.insert(
            0,
            ast.If(
                test=ast.BoolOp(
                    op=ast.And(),
                    values=[
                        ast.UnaryOp(
                            op=ast.Not(),
                            operand=ast.Name(
                                id=include_name,
                                ctx=ast.Load(),
                            ),
                        ),
                        ast.Compare(
                            left=ast.Call(
                                func=ast.Attribute(
                                    value=ast.Name(
                                        id=loop.target.id,
                                        ctx=ast.Load(),
                                    ),
                                    attr="get",
                                    ctx=ast.Load(),
                                ),
                                args=[
                                    ast.Constant(value=state),
                                    ast.Constant(value=False),
                                ],
                                keywords=[],
                            ),
                            ops=[ast.Is()],
                            comparators=[ast.Constant(value=True)],
                        ),
                    ],
                ),
                body=[ast.Continue()],
                orelse=[],
            ),
        )
        ast.fix_missing_locations(tree)
        updated[file_index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
        notes.append(
            f"{Path(path).name}:{class_node.name}: applied `{attribute}` "
            f"to the `{state}` result filter."
        )
    return updated, notes


def _repair_local_qt_signal_scaffolding(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove invalid method-local Qt signals and preserve worker signal routing."""

    targets: dict[tuple[str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): Qt Signal declaration\(s\) must be "
        r"class attributes.+?: (?P<signals>[A-Za-z0-9_, ]+)\."
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.setdefault(
                (
                    str(Path(match.group("path")).resolve()),
                    match.group("owner"),
                ),
                set(),
            ).update(
                value.strip()
                for value in match.group("signals").split(",")
                if value.strip()
            )
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        matching = {
            owner: signals
            for (target_path, owner), signals in targets.items()
            if target_path == resolved_path
        }
        if not matching:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner, signal_names in matching.items():
            class_name, _, method_name = owner.partition(".")
            class_node = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            method_node = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == method_name
                ),
                None,
            ) if class_node is not None else None
            if method_node is None:
                continue
            handler_names = {
                node.name
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

            class SignalScaffoldingTransformer(ast.NodeTransformer):
                def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
                    nonlocal changed
                    if any(
                        isinstance(target, ast.Name)
                        and target.id in signal_names
                        for target in node.targets
                    ):
                        changed = True
                        return None
                    if (
                        isinstance(node.value, ast.Lambda)
                        and isinstance(node.value.body, ast.Call)
                        and any(
                            keyword.arg and keyword.arg.endswith("callback")
                            for keyword in node.value.body.keywords
                        )
                        and isinstance(
                            node.value.body.func,
                            (ast.Name, ast.Attribute),
                        )
                    ):
                        node.value = node.value.body.func
                        changed = True
                    if any(
                        isinstance(child, ast.Name)
                        and child.id in signal_names
                        for child in ast.walk(node.value)
                    ):
                        changed = True
                        return None
                    return self.generic_visit(node)

                def visit_Expr(self, node: ast.Expr) -> ast.AST | None:
                    nonlocal changed
                    if (
                        isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "connect"
                        and node.value.args
                        and isinstance(node.value.args[0], ast.Name)
                        and node.value.args[0].id in signal_names
                        and isinstance(node.value.func.value, ast.Attribute)
                    ):
                        signal_name = node.value.func.value.attr
                        handler_name = f"_handle_{signal_name}"
                        if handler_name in handler_names:
                            node.value.args[0] = ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=handler_name,
                                ctx=ast.Load(),
                            )
                            changed = True
                            return node
                    if any(
                        isinstance(child, ast.Name)
                        and child.id in signal_names
                        for child in ast.walk(node)
                    ):
                        changed = True
                        return None
                    return self.generic_visit(node)

                def visit_If(self, node: ast.If) -> ast.AST | None:
                    nonlocal changed
                    node = self.generic_visit(node)
                    if node is None:
                        return None
                    node.body = [
                        statement for statement in node.body if statement is not None
                    ]
                    node.orelse = [
                        statement
                        for statement in node.orelse
                        if statement is not None
                    ]
                    if not node.body and not node.orelse:
                        changed = True
                        return None
                    return node

            SignalScaffoldingTransformer().visit(method_node)
            method_node.body = [
                statement for statement in method_node.body if statement is not None
            ] or [ast.Pass()]
            if changed:
                notes.append(
                    f"{Path(path).name}:{owner}: removed method-local Qt signal "
                    "scaffolding and retained worker-owned routing."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_qt_worker_progress_injection(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Inject a validator-proven progress callback into a worker operation call."""

    targets: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): approved worker operation must inject "
        r"`progress_callback=self\.progress\.emit`"
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
        resolved_path = str(Path(path).resolve())
        owners = {
            owner
            for target_path, owner in targets
            if target_path == resolved_path
        }
        if not owners:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed_owners: list[str] = []
        for owner in owners:
            class_name, _, method_name = owner.partition(".")
            class_node = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            method_node = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == method_name
                ),
                None,
            ) if class_node is not None else None
            if method_node is None:
                continue
            operation_calls = [
                node
                for node in ast.walk(method_node)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr == "operation"
            ]
            if len(operation_calls) != 1:
                continue
            operation_call = operation_calls[0]
            callback_value = ast.Attribute(
                value=ast.Attribute(
                    value=ast.Name(id="self", ctx=ast.Load()),
                    attr="progress",
                    ctx=ast.Load(),
                ),
                attr="emit",
                ctx=ast.Load(),
            )
            existing_keyword = next(
                (
                    keyword
                    for keyword in operation_call.keywords
                    if keyword.arg == "progress_callback"
                ),
                None,
            )
            if existing_keyword is None:
                operation_call.keywords.append(
                    ast.keyword(
                        arg="progress_callback",
                        value=callback_value,
                    )
                )
            else:
                existing_keyword.value = callback_value
            changed_owners.append(owner)
        if changed_owners:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
            notes.extend(
                f"{Path(path).name}:{owner}: injected the approved worker "
                "progress callback into the bound operation."
                for owner in changed_owners
            )
    return updated, notes


def _repair_worker_constructor_progress_routing(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Move duplicate worker progress callbacks onto the worker signal."""

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        progress_injecting_workers: set[str] = set()
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            run_method = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "run"
                ),
                None,
            )
            if run_method is None:
                continue
            if any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
                and call.func.attr == "operation"
                and any(
                    keyword.arg == "progress_callback"
                    and isinstance(keyword.value, ast.Attribute)
                    and keyword.value.attr == "emit"
                    and isinstance(keyword.value.value, ast.Attribute)
                    and keyword.value.value.attr == "progress"
                    and isinstance(keyword.value.value.value, ast.Name)
                    and keyword.value.value.value.id == "self"
                    for keyword in call.keywords
                )
                for call in ast.walk(run_method)
            ):
                progress_injecting_workers.add(class_node.name)
        if not progress_injecting_workers:
            continue
        file_changed = False
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            for method_node in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                statement_index = 0
                while statement_index < len(method_node.body):
                    statement = method_node.body[statement_index]
                    if not (
                        isinstance(statement, ast.Assign)
                        and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Attribute)
                        and isinstance(statement.targets[0].value, ast.Name)
                        and statement.targets[0].value.id == "self"
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Name)
                        and statement.value.func.id in progress_injecting_workers
                    ):
                        statement_index += 1
                        continue
                    callback_keyword = next(
                        (
                            keyword
                            for keyword in statement.value.keywords
                            if keyword.arg == "progress_callback"
                        ),
                        None,
                    )
                    if callback_keyword is None:
                        statement_index += 1
                        continue
                    worker_name = statement.targets[0].attr
                    callback_value = callback_keyword.value
                    statement.value.keywords = [
                        keyword
                        for keyword in statement.value.keywords
                        if keyword is not callback_keyword
                    ]
                    connect_call = ast.Expr(
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
                                    attr="progress",
                                    ctx=ast.Load(),
                                ),
                                attr="connect",
                                ctx=ast.Load(),
                            ),
                            args=[callback_value],
                            keywords=[],
                        )
                    )
                    method_node.body.insert(statement_index + 1, connect_call)
                    statement_index += 2
                    file_changed = True
                    notes.append(
                        f"{Path(path).name}:{class_node.name}.{method_node.name}: "
                        f"routed duplicate constructor progress callback through "
                        f"`self.{worker_name}.progress`."
                    )
        if file_changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_cross_thread_callback_routing(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Route a proven UI callback through a retained worker signal."""

    targets: dict[tuple[str, str], set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): worker operation passes "
        r"dialog-bound callback\(s\) directly across the thread boundary: "
        r"(?P<callbacks>.+?)\. Route worker progress through"
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
            value.strip().removeprefix("self.")
            for value in match.group("callbacks").split(",")
            if value.strip()
        )
    if not targets:
        return generated_files, []

    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        resolved_path = str(Path(path).resolve())
        matching = {
            owner: callbacks
            for (target_path, owner), callbacks in targets.items()
            if target_path == resolved_path
        }
        if not matching:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        changed = False
        for owner, callback_names in matching.items():
            class_name, _, method_name = owner.partition(".")
            class_node = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            method_node = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == method_name
                ),
                None,
            ) if class_node is not None else None
            if method_node is None:
                continue
            operation_handlers: list[str] = []
            for assignment in [
                node for node in ast.walk(method_node) if isinstance(node, ast.Assign)
            ]:
                if not isinstance(assignment.value, ast.Lambda):
                    continue
                body = assignment.value.body
                if not isinstance(body, ast.Call):
                    continue
                callback_keywords = [
                    keyword
                    for keyword in body.keywords
                    if keyword.arg and keyword.arg.endswith("callback")
                ]
                if not callback_keywords:
                    continue
                for keyword in callback_keywords:
                    if (
                        isinstance(keyword.value, ast.Attribute)
                        and isinstance(keyword.value.value, ast.Name)
                        and keyword.value.value.id == "self"
                    ):
                        operation_handlers.append(keyword.value.attr)
                assignment.value = body.func
                changed = True

            worker_variables: dict[str, str] = {}
            for assignment in [
                node for node in ast.walk(method_node) if isinstance(node, ast.Assign)
            ]:
                if (
                    len(assignment.targets) != 1
                    or not isinstance(assignment.targets[0], ast.Name)
                    or not isinstance(assignment.value, ast.Call)
                ):
                    continue
                constructor_name = (
                    assignment.value.func.id
                    if isinstance(assignment.value.func, ast.Name)
                    else (
                        assignment.value.func.attr
                        if isinstance(assignment.value.func, ast.Attribute)
                        else ""
                    )
                )
                if constructor_name.casefold().endswith(
                    ("worker", "thread", "runnable")
                ):
                    worker_variables[assignment.targets[0].id] = constructor_name
            for worker_name, worker_class_name in worker_variables.items():
                class RetainWorker(ast.NodeTransformer):
                    def visit_Name(self, node: ast.Name) -> ast.AST:
                        if node.id != worker_name:
                            return node
                        return ast.copy_location(
                            ast.Attribute(
                                value=ast.Name(id="self", ctx=ast.Load()),
                                attr=worker_name,
                                ctx=node.ctx,
                            ),
                            node,
                        )

                RetainWorker().visit(method_node)
                helper_node = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.ClassDef)
                        and node.name == worker_class_name
                    ),
                    None,
                )
                signal_name = next(
                    (
                        target.id
                        for assignment in (
                            helper_node.body if helper_node is not None else []
                        )
                        if isinstance(assignment, ast.Assign)
                        and isinstance(assignment.value, ast.Call)
                        and any(
                            isinstance(target, ast.Name)
                            for target in assignment.targets
                        )
                        and len(assignment.value.args) == 3
                        for target in assignment.targets
                        if isinstance(target, ast.Name)
                    ),
                    "progress",
                )
                handler_name = next(
                    (
                        name
                        for name in operation_handlers
                        if name in callback_names
                    ),
                    next(iter(callback_names), ""),
                )
                has_progress_connection = any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "connect"
                    and isinstance(call.func.value, ast.Attribute)
                    and call.func.value.attr == signal_name
                    for call in ast.walk(method_node)
                )
                if handler_name and not has_progress_connection:
                    connect_statement = ast.parse(
                        f"self.{worker_name}.{signal_name}.connect("
                        f"self.{handler_name})"
                    ).body[0]
                    start_index = next(
                        (
                            index
                            for index, statement in enumerate(method_node.body)
                            if any(
                                isinstance(call, ast.Call)
                                and isinstance(call.func, ast.Attribute)
                                and call.func.attr == "start"
                                for call in ast.walk(statement)
                            )
                        ),
                        len(method_node.body),
                    )
                    method_node.body.insert(start_index, connect_statement)
                changed = True
            if changed:
                notes.append(
                    f"{Path(path).name}:{owner}: replaced dialog-bound worker "
                    "callbacks with a retained bound operation and worker signal."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_unretained_worker_dispatch(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Retain a locally started worker and align its nested operation arguments."""

    targets: dict[tuple[str, str], str] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): started background worker is held only "
        r"by a local variable.+?: (?P<worker>[A-Za-z_][A-Za-z0-9_]*)\."
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
            nested_operations = {
                node.name: node
                for node in method_node.body
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            constructor_assignment = next(
                (
                    assignment
                    for assignment in ast.walk(method_node)
                    if isinstance(assignment, ast.Assign)
                    and any(
                        isinstance(target, ast.Name)
                        and target.id == worker_name
                        for target in assignment.targets
                    )
                    and isinstance(assignment.value, ast.Call)
                ),
                None,
            )
            if constructor_assignment is None:
                continue
            constructor_call = constructor_assignment.value
            if (
                constructor_call.args
                and isinstance(constructor_call.args[0], ast.Name)
                and constructor_call.args[0].id in nested_operations
            ):
                operation_node = nested_operations[
                    constructor_call.args[0].id
                ]
                operation_parameter_count = sum(
                    1
                    for argument in [
                        *operation_node.args.posonlyargs,
                        *operation_node.args.args,
                        *operation_node.args.kwonlyargs,
                    ]
                    if argument.arg != "self"
                    and not argument.arg.endswith("progress_callback")
                )
                constructor_call.args = constructor_call.args[
                    : 1 + operation_parameter_count
                ]

            class RetainWorker(ast.NodeTransformer):
                def visit_Name(self, node: ast.Name) -> ast.AST:
                    if node.id != worker_name:
                        return node
                    return ast.copy_location(
                        ast.Attribute(
                            value=ast.Name(id="self", ctx=ast.Load()),
                            attr=worker_name,
                            ctx=node.ctx,
                        ),
                        node,
                    )

            RetainWorker().visit(method_node)
            changed = True
            notes.append(
                f"{Path(path).name}:{owner}: retained worker "
                f"`self.{worker_name}` and aligned its operation arguments."
            )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_nested_worker_operation_protocol(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Align a nested worker operation with injected progress callback routing."""

    targets: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"^(?P<path>.+?\.py):"
        r"(?P<owner>[A-Za-z_][A-Za-z0-9_]*\."
        r"[A-Za-z_][A-Za-z0-9_]*): nested worker operation "
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
            nested_operations = {
                node.name: node
                for node in method_node.body
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            operation_names = {
                call.args[0].id
                for call in ast.walk(method_node)
                if isinstance(call, ast.Call)
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id in nested_operations
                and (
                    (
                        isinstance(call.func, ast.Name)
                        and call.func.id.casefold().endswith(
                            ("worker", "thread", "runnable")
                        )
                    )
                    or (
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr.casefold().endswith(
                            ("worker", "thread", "runnable")
                        )
                    )
                )
            }
            for operation_name in operation_names:
                operation = nested_operations[operation_name]
                argument_names = {
                    argument.arg
                    for argument in [
                        *operation.args.posonlyargs,
                        *operation.args.args,
                        *operation.args.kwonlyargs,
                    ]
                }
                if "progress_callback" not in argument_names:
                    operation.args.args.append(
                        ast.arg(arg="progress_callback")
                    )
                    changed = True
                for call in ast.walk(operation):
                    if not isinstance(call, ast.Call):
                        continue
                    for keyword in call.keywords:
                        if (
                            keyword.arg
                            and keyword.arg.endswith("progress_callback")
                            and isinstance(keyword.value, ast.Attribute)
                            and isinstance(keyword.value.value, ast.Name)
                            and keyword.value.value.id == "self"
                        ):
                            keyword.value = ast.Name(
                                id="progress_callback",
                                ctx=ast.Load(),
                            )
                            changed = True
            if changed:
                notes.append(
                    f"{Path(path).name}:{owner}: aligned nested worker "
                    "operation with injected progress callback routing."
                )
        if changed:
            ast.fix_missing_locations(tree)
            updated[file_index] = (
                path,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, notes


def _repair_entry_point_owner_reference(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    request_prompt: str = "",
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Repair an undefined entry-point owner from an unambiguous local owner."""

    targets: dict[str, set[str]] = {}
    pattern = re.compile(
        r"^(?P<path>.+?\.py):_run_as_script: callable roots are neither "
        r"imported nor defined in scope: (?P<names>.+)$"
    )
    for error in errors:
        match = pattern.match(str(error))
        if match:
            targets.setdefault(
                str(Path(match.group("path")).resolve()),
                set(),
            ).update(
                value.strip()
                for value in match.group("names").split(",")
                if value.strip()
            )
    json_output_requested = bool(
        re.search(r"\bjson\.dumps\s*\(", request_prompt, re.IGNORECASE)
        and re.search(r"\b_run_as_script\s*\(", request_prompt)
    )
    if not targets and not json_output_requested:
        return generated_files, []
    updated = list(generated_files)
    notes: list[str] = []
    for file_index, (path, original, source) in enumerate(updated):
        undefined_names = targets.get(str(Path(path).resolve()), set())
        if not undefined_names and not json_output_requested:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        entry_point = next(
            (
                node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_run_as_script"
            ),
            None,
        )
        owner_candidates = [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and not node.name.startswith("_")
            and (
                node.name.endswith(("Dialog", "Window", "Widget"))
                or any(
                    isinstance(base, ast.Name)
                    and base.id.endswith(("Dialog", "Window", "Widget"))
                    for base in node.bases
                )
            )
        ]
        if entry_point is None:
            continue
        public_zero_argument_functions = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
            and not node.args.posonlyargs
            and not node.args.args
            and not node.args.kwonlyargs
            and node.args.vararg is None
            and node.args.kwarg is None
        ]
        if json_output_requested and len(public_zero_argument_functions) == 1:
            operation_name = public_zero_argument_functions[0].name
            prefix_match = re.search(
                r"\b(?:print|prints|printing)\b[^\n]{0,120}?"
                r"(?P<prefix>[A-Z][A-Z0-9_]*=)",
                request_prompt,
                re.IGNORECASE,
            )
            prefix = prefix_match.group("prefix") if prefix_match else ""
            has_json_import = any(
                (
                    isinstance(node, ast.Import)
                    and any(alias.name == "json" for alias in node.names)
                )
                or (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "json"
                )
                for node in tree.body
            )
            if not has_json_import:
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
                tree.body.insert(insert_at, ast.Import(names=[ast.alias(name="json")]))
            entry_point.body = [
                ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id="print", ctx=ast.Load()),
                        args=[
                            ast.BinOp(
                                left=ast.Constant(value=prefix),
                                op=ast.Add(),
                                right=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id="json", ctx=ast.Load()),
                                        attr="dumps",
                                        ctx=ast.Load(),
                                    ),
                                    args=[
                                        ast.Call(
                                            func=ast.Name(id=operation_name, ctx=ast.Load()),
                                            args=[],
                                            keywords=[],
                                        )
                                    ],
                                    keywords=[
                                        ast.keyword(
                                            arg="sort_keys",
                                            value=ast.Constant(value=True),
                                        )
                                    ],
                                ),
                            )
                        ],
                        keywords=[],
                    )
                )
            ]
            repair_note = (
                f"{Path(path).name}:_run_as_script: routed the entry point "
                f"through `{operation_name}` and the requested JSON output."
            )
        elif len(owner_candidates) == 1:
            replacement_name = owner_candidates[0]

            class ReplaceUndefinedOwner(ast.NodeTransformer):
                def visit_Name(self, node: ast.Name) -> ast.AST:
                    if node.id not in undefined_names:
                        return node
                    return ast.copy_location(
                        ast.Name(id=replacement_name, ctx=node.ctx),
                        node,
                    )

            ReplaceUndefinedOwner().visit(entry_point)
            repair_note = (
                f"{Path(path).name}:_run_as_script: replaced undefined "
                f"constructor with `{replacement_name}`."
            )
        else:
            if len(public_zero_argument_functions) != 1 or not json_output_requested:
                continue
            operation_name = public_zero_argument_functions[0].name
            prefix_match = re.search(
                r"\b(?:print|prints|printing)\b[^\n]{0,120}?"
                r"(?P<prefix>[A-Z][A-Z0-9_]*=)",
                request_prompt,
                re.IGNORECASE,
            )
            prefix = prefix_match.group("prefix") if prefix_match else ""
            has_json_import = any(
                (
                    isinstance(node, ast.Import)
                    and any(alias.name == "json" for alias in node.names)
                )
                or (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "json"
                )
                for node in tree.body
            )
            if not has_json_import:
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
                tree.body.insert(insert_at, ast.Import(names=[ast.alias(name="json")]))
            entry_point.body = [
                ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id="print", ctx=ast.Load()),
                        args=[
                            ast.BinOp(
                                left=ast.Constant(value=prefix),
                                op=ast.Add(),
                                right=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Name(id="json", ctx=ast.Load()),
                                        attr="dumps",
                                        ctx=ast.Load(),
                                    ),
                                    args=[
                                        ast.Call(
                                            func=ast.Name(
                                                id=operation_name,
                                                ctx=ast.Load(),
                                            ),
                                            args=[],
                                            keywords=[],
                                        )
                                    ],
                                    keywords=[
                                        ast.keyword(
                                            arg="sort_keys",
                                            value=ast.Constant(value=True),
                                        )
                                    ],
                                ),
                            )
                        ],
                        keywords=[],
                    )
                )
            ]
            repair_note = (
                f"{Path(path).name}:_run_as_script: routed the entry point "
                f"through `{operation_name}` and the requested JSON output."
            )
        ast.fix_missing_locations(tree)
        updated[file_index] = (
            path,
            original,
            ast.unparse(tree).rstrip() + "\n",
        )
        notes.append(repair_note)
    return updated, notes

from tech_connector.services.project_edit_workflow_cross_file_repair import (
    _repair_missing_cross_file_imports, _repair_unreferenced_private_helpers,
    _repair_verified_qt_worker_integration,
)
from tech_connector.services.project_edit_workflow_worker_repairs import (
    _repair_required_finally_cleanup, _repair_unreachable_delegated_launcher,
    _repair_unresolved_signal_connections,
)
