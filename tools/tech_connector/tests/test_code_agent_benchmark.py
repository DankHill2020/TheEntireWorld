"""Tests for the deterministic code-agent comparison harness."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import sys

import pytest

from tech_connector.benchmarks.code_agent.cases import benchmark_cases
from tech_connector.benchmarks.code_agent.models import AgentRun
from tech_connector.benchmarks.code_agent.reporting import aggregate_runs
from tech_connector.benchmarks.code_agent.runners import (
    _codex_command,
    _codex_infrastructure_errors,
    _run_streamed_process,
)
from tech_connector.benchmarks.code_agent.scoring import (
    materialize_case,
    score_attempt,
    snapshot_workspace,
)
from tech_connector.benchmarks.code_agent.tech_worker import _safe_change_path
from tech_connector.services.project_edit_agent_service import (
    _incomplete_generated_type_hints,
    apply_project_edit_generated_class_set_repair,
    assemble_project_edit_generated_chunks,
    build_deterministic_project_edit_chunk_plan,
    build_user_visible_implementation_plan,
    extract_project_edit_artifact_requirements,
    format_project_edit_generated_python,
    resolve_project_edit_standard_library_symbols,
)
from tech_connector.services.implementation_plan_quality_service import (
    _mechanics,
    _observable_actions,
    _required_method_names,
    enrich_implementation_plan,
    validate_generated_files_against_implementation_plan,
    validate_implementation_plan_completeness,
)
from tech_connector.services.implementation_plan_declaration_validation_service import (
    validate_approved_declaration_contracts,
)
from tech_connector.services.implementation_plan_quality_contract import (
    APPROVED_PLAN_SCHEMA,
    APPROVED_PLAN_VALIDATOR_VERSION,
)
from tech_connector.services.project_edit_workflow_service import (
    _enrich_manifest_with_explicit_declarations,
    _fallback_requested_file_manifest,
    _final_requirement_review_batches,
    _parse_final_requirement_review,
    _repair_asset_operation_pipeline_contract,
    _repair_command_result_envelope_contract,
    _repair_explicit_cross_file_delegation,
    _repair_explicit_cross_file_delegation_harness,
    _repair_explicit_path_policy_semantics,
    _repair_priority_job_queue_contract,
    _repair_host_result_contracts,
    _repair_image_cache_contract,
    _repair_requested_python_contract_surface,
    _semantic_requirement_ledger,
)
from tech_connector.services.project_edit_workflow_runner_attempt_synthesize import (
    _review_finding_requires_disposable_test_repair,
)
from tech_connector.services.project_edit_workflow_part_06 import (
    _expanded_ephemeral_behavior_rows,
)
from tech_connector.services.project_edit_workflow_runner_attempt_finalize import (
    _bounded_repair_model_sequence,
)
from tech_connector.services.project_edit_workflow_runner_attempt_prepare import (
    _validation_cycle_fingerprint,
)
from tech_connector.services.project_edit_workflow_runtime_repair import (
    _repair_dependency_execution_batches,
    _repair_ephemeral_builtin_patch_targets,
    _repair_json_merge_patch_contract,
    _repair_missing_constructor_state,
    _verify_backoff_tracker_contract,
    _verify_dependency_execution_batches,
    _verify_json_merge_patch_contract,
)
from tech_connector.services.project_edit_workflow_runner_planning import (
    _is_project_edit_quality_requirement,
)
from tech_connector.services.project_edit_workflow_part_05 import (
    _repair_ephemeral_cache_contract_tests,
    _repair_missing_synchronization_boundaries,
    _repair_shared_ttl_recency_index,
    _repair_unnecessary_terminating_else_branches,
)
from tech_connector.services.project_edit_workflow_part_04 import (
    _repair_ephemeral_mocked_production_methods,
    _repair_ephemeral_unused_fixture_assignments,
)
from tech_connector.services.project_edit_workflow_part_02 import (
    _normalize_generated_files,
    _normalize_generated_python_source_quality,
    _remove_shadowed_class_methods,
)
from tech_connector.services.project_edit_workflow_part_06 import (
    _repair_locked_undeclared_public_methods,
)
from tech_connector.services.project_edit_workflow_part_07 import (
    _repair_ephemeral_indirect_owner_invocations,
)
from tech_connector.services.project_edit_workflow_part_11 import (
    _repair_explicit_command_registry_contract,
    _repair_ephemeral_command_registry_contract_tests,
    _repair_ephemeral_mock_call_reference,
    _repair_shared_command_registry,
)


def _completed_run(case_id: str) -> AgentRun:
    """Build a minimal successful adapter record.

    :param case_id: Benchmark case identifier.
    :return: Successful run fixture.
    """

    return AgentRun(
        agent="fixture",
        model="deterministic",
        case_id=case_id,
        repetition=1,
        status="ok",
        wall_seconds=1.0,
        exit_code=0,
)


def test_owner_chunk_assembly_ignores_displaced_module_docstring() -> None:
    """Accept a declaration capsule without retaining its stray string literal."""

    files, errors = assemble_project_edit_generated_chunks([
        (
            "connector/dcc/path_policy.py",
            "normalize_export_path",
            '"""Path policy helper."""\n\n'
            "from pathlib import Path\n\n"
            "def normalize_export_path(project_root, requested):\n"
            "    return Path(project_root) / requested\n",
        ),
    ])

    assert errors == []
    assert len(files) == 1
    assert '"""Path policy helper."""' not in files[0][2]
    assert "def normalize_export_path" in files[0][2]


def test_plan_validator_accepts_nested_callable_roots() -> None:
    """Treat function-local helpers as valid lexical-scope bindings."""

    plan = {
        "chunks": [
            {
                "chunk_id": "D1_1",
                "path": "pipeline/dependencies.py",
                "owner": "execution_batches",
                "kind": "function",
                "requirements": [
                    {
                        "id": "R1",
                        "text": "Compute dependency batches.",
                    }
                ],
            }
        ],
        "requirement_coverage": {"R1": ["D1_1"]},
    }
    source = """\
def execution_batches(graph):
    def visit(node):
        return graph[node]

    return tuple(visit(node) for node in graph)
"""

    errors = validate_generated_files_against_implementation_plan(
        plan,
        [("pipeline/dependencies.py", "", source)],
    )

    assert not any(
        "callable roots are neither imported nor defined" in error
        for error in errors
    )


def test_dependency_batch_contract_compiles_stable_layers() -> None:
    """Compile the full approved graph contract after weak model synthesis."""

    prompt = (
        "Implement execution_batches(graph), where graph maps each task name to "
        "the tasks it depends on. Return batches with all currently runnable tasks. "
        "Include tasks that appear only as dependencies and raise ValueError for any cycle."
    )
    source = "def execution_batches(graph):\n    return tuple((name,) for name in graph)\n"

    repaired, notes = _repair_dependency_execution_batches(
        [("pipeline/dependencies.py", source, source)],
        ["execution_batches remains behaviorally incomplete"],
        request_prompt=prompt,
    )

    assert notes == [
        "dependencies.py:execution_batches compiled stable dependency layers"
    ]
    namespace: dict[str, object] = {}
    exec(repaired[0][2], namespace)
    function = namespace["execution_batches"]
    graph = {
        "build": {"compile", "assets"},
        "compile": {"parse"},
        "assets": {"parse"},
        "parse": set(),
    }
    snapshot = {key: set(value) for key, value in graph.items()}
    assert function(graph) == (("parse",), ("assets", "compile"), ("build",))
    assert function({"package": ["compile"]}) == (("compile",), ("package",))
    assert function({"z": set(), "a": set()}) == (("a", "z"),)
    assert function({}) == ()
    assert graph == snapshot
    with pytest.raises(ValueError, match="a.*b"):
        function({"a": {"b"}, "b": {"a"}, "ready": set()})


def test_dependency_batch_compiler_requires_complete_explicit_contract() -> None:
    """Do not rewrite unrelated functions that merely mention dependencies."""

    source = "def execution_batches(graph):\n    return tuple(graph)\n"
    repaired, notes = _repair_dependency_execution_batches(
        [("pipeline/dependencies.py", source, source)],
        [],
        request_prompt="Sort dependency names for display.",
    )

    assert repaired[0][2] == source
    assert notes == []


def test_dependency_batch_compiler_has_isolated_executable_proof() -> None:
    """Prove stable complete layers, non-mutation, and cycle reporting."""

    prompt = (
        "Implement execution_batches(graph), where graph maps each task name to the "
        "tasks it depends on. Return all currently runnable tasks. Include tasks that "
        "appear only as dependencies and raise ValueError for any cycle."
    )
    source = "def execution_batches(graph):\n    return ()\n"
    repaired, _ = _repair_dependency_execution_batches(
        [("pipeline/dependencies.py", source, source)],
        [],
        request_prompt=prompt,
    )
    assert _verify_dependency_execution_batches(repaired, request_prompt=prompt)
    broken = repaired[0][2].replace(
        "tuple(sorted(ready_items))",
        "tuple(reversed(sorted(ready_items)))",
    )
    assert not _verify_dependency_execution_batches(
        [(repaired[0][0], repaired[0][1], broken)],
        request_prompt=prompt,
    )


def test_json_merge_patch_compiler_and_proof_cover_detachment() -> None:
    """Compile complete recursive semantics and prove both inputs stay detached."""

    prompt = """\
Implement merge_patch(document, patch): a non-mapping patch replaces the document; a
mapping patch recursively merges into a mapping document or an empty mapping when the
document is not a mapping; a None mapping value deletes that key. Return a detached result:
neither inputs nor nested mutable values may be shared. Never mutate either input.
"""
    source = "def merge_patch(document, patch):\n    return document\n"
    repaired, notes = _repair_json_merge_patch_contract(
        [("data/merge_patch.py", source, source)],
        [],
        request_prompt=prompt,
    )
    assert notes
    assert _verify_json_merge_patch_contract(repaired, request_prompt=prompt)
    broken = repaired[0][2].replace(
        "result = deepcopy(dict(document))",
        "result = dict(document)",
    )
    assert not _verify_json_merge_patch_contract(
        [(repaired[0][0], repaired[0][1], broken)],
        request_prompt=prompt,
    )


def test_json_merge_patch_compiler_requires_complete_contract() -> None:
    """Do not rewrite an incidental mapping update request."""

    source = "def merge_patch(document, patch):\n    return document\n"
    repaired, notes = _repair_json_merge_patch_contract(
        [("data/merge_patch.py", source, source)],
        [],
        request_prompt="Update a mapping with merge_patch(document, patch).",
    )
    assert repaired[0][2] == source
    assert notes == []


def test_builtin_patch_oracle_is_removed_from_disposable_harness() -> None:
    """Do not forbid a correct implementation from calling Python built-ins."""

    harness_path = "test_requirement_contract.py"
    source = """\
from unittest.mock import patch

def test_batches():
    with patch("pipeline.dependencies.set") as mock_set:
        result = execution_batches({"a": set()})
    assert result == (("a",),)
    mock_set.assert_not_called()
"""
    repaired, notes = _repair_ephemeral_builtin_patch_targets(
        [(harness_path, "", source)],
        [
            "test_batches: patch targets do not resolve to real generated or "
            "installed API symbols: pipeline.dependencies.set"
        ],
        harness_path=harness_path,
    )

    assert notes == [
        "test_requirement_contract.py: removed invalid built-in patch oracle(s): "
        "pipeline.dependencies.set"
    ]
    assert "patch(\"pipeline.dependencies.set\")" not in repaired[0][2]
    assert "mock_set.assert_not_called" not in repaired[0][2]
    assert "result = execution_batches" in repaired[0][2]
    assert "assert result ==" in repaired[0][2]
    ast.parse(repaired[0][2])


def test_missing_constructor_state_is_initialized_after_validation() -> None:
    """Install a constructor field only when public use proves it is required."""

    path = "network/backoff.py"
    source = """\
class BackoffTracker:
    def __init__(self, max_delay):
        if max_delay < 0:
            raise ValueError("max_delay")
        self.values = {}

    def delay(self):
        return self.max_delay
"""
    repaired, notes = _repair_missing_constructor_state(
        [(path, source, source)],
        [
            f"{path}:BackoffTracker.__init__: constructor argument `max_delay` "
            "is read as `self.max_delay` by public behavior but is never "
            "initialized on the instance."
        ],
    )

    assert notes == [
        "backoff.py: initialized proven constructor state BackoffTracker.max_delay"
    ]
    tree = ast.parse(repaired[0][2])
    initializer = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    assert "self.max_delay = max_delay" in ast.unparse(initializer)
    assert ast.unparse(initializer).index("raise ValueError") < ast.unparse(
        initializer
    ).index("self.max_delay = max_delay")


def test_class_set_repair_installs_imports_before_closure_validation(
    tmp_path: Path,
) -> None:
    """Allow a repaired class to use imports returned in its owner envelope."""

    target = tmp_path / "registry.py"
    original = "class Registry:\n    pass\n"
    repaired = """from threading import Lock

class Registry:
    def __init__(self):
        self._lock = Lock()

    def register(self, capabilities=()):
        with self._lock:
            return tuple(capabilities)
"""

    files, errors = apply_project_edit_generated_class_set_repair(
        [(str(target), original, original)],
        class_targets=[(str(target), "Registry")],
        replacement_response=repaired,
    )

    assert errors == []
    assert "from threading import Lock" in files[0][2]
    assert "self._lock = Lock()" in files[0][2]


def test_standard_library_repair_resolves_thread_locks(tmp_path: Path) -> None:
    """Supply deterministic imports for common synchronization primitives."""

    target = tmp_path / "cache.py"
    source = "class Cache:\n    def __init__(self):\n        self._lock = Lock()\n"

    files, fixes = resolve_project_edit_standard_library_symbols(
        [(str(target), source, source)]
    )

    assert fixes
    assert "from threading import Lock" in files[0][2]


def test_standard_library_repair_preserves_bound_parameter_names(
    tmp_path: Path,
) -> None:
    """Do not reinterpret a parameter named patch as unittest.mock.patch."""

    target = tmp_path / "merge_patch.py"
    source = '''"""Merge documents."""\n\n\ndef merge(document, patch):\n    return patch.items()\n'''

    files, fixes = resolve_project_edit_standard_library_symbols(
        [(str(target), source, source)]
    )

    assert fixes == []
    assert "unittest.mock" not in files[0][2]
    assert files[0][2].startswith('"""Merge documents."""')


def test_standard_library_repair_adds_collection_and_copy_symbols(
    tmp_path: Path,
) -> None:
    """Install common algorithm imports after the module docstring."""

    target = tmp_path / "algorithm.py"
    source = '''"""Run an algorithm."""\n\n\ndef run(values):\n    queue = deque(values)\n    grouped = defaultdict(list)\n    return deepcopy((queue, grouped))\n'''

    files, fixes = resolve_project_edit_standard_library_symbols(
        [(str(target), source, source)]
    )

    repaired = files[0][2]
    assert fixes
    assert repaired.startswith('"""Run an algorithm."""')
    assert "from collections import defaultdict" in repaired
    assert "from collections import deque" in repaired
    assert "from copy import deepcopy" in repaired
    compile(repaired, str(target), "exec")


def test_required_methods_ignore_prose_groups_and_builtin_expressions() -> None:
    """Recognize class protocols without hallucinating prose or builtins."""

    prompt = (
        "EventJournal.since(sequence) returns a tuple of (sequence, topic, payload) "
        "tuples. len(journal) reports retained count. clear() removes events. "
        "Use min(limit, base * 2) when calculating delays."
    )

    methods = _required_method_names("EventJournal", "class", prompt)

    assert methods == ["since", "clear", "__len__"]
    assert "of" not in methods
    assert "len" not in methods
    assert "min" not in methods


def test_missing_synchronization_repair_guards_instance_methods(
    tmp_path: Path,
) -> None:
    """Install one reentrant class boundary for approved thread safety."""

    target = tmp_path / "registry.py"
    source = """class Registry:
    def __init__(self):
        self.items = {}

    def register(self, name, value):
        self.items[name] = value

    def resolve(self, name):
        return self.items[name]
"""
    errors = [
        f"{target}:Registry: approved synchronization boundary is missing."
    ]

    files, fixes = _repair_missing_synchronization_boundaries(
        [(str(target), source, source)], errors
    )

    assert fixes
    repaired = files[0][2]
    assert "from threading import RLock" in repaired
    assert "self._lock = RLock()" in repaired
    assert repaired.count("with self._lock:") == 2


def test_missing_synchronization_repair_is_idempotent_for_threading_rlock(
    tmp_path: Path,
) -> None:
    """Leave an existing coherent synchronization boundary unchanged."""

    target = tmp_path / "registry.py"
    source = '''"""Runtime command registry."""

import threading


class Registry:
    def __init__(self):
        self._lock = threading.RLock()
        self.items = {}

    def register(self, name, value):
        with self._lock:
            self.items[name] = value
'''
    errors = [
        f"{target}:Registry: approved synchronization boundary is missing."
    ]

    files, fixes = _repair_missing_synchronization_boundaries(
        [(str(target), source, source)], errors
    )

    assert fixes == []
    assert files[0][2] == source
    assert source.count("RLock()") == 1


def test_missing_synchronization_repair_preserves_existing_critical_region(
    tmp_path: Path,
) -> None:
    """Do not wrap setup work around an already protected mutation region."""

    target = tmp_path / "registry.py"
    source = '''import threading


class Registry:
    def __init__(self):
        self._lock = threading.RLock()
        self.items = {}

    def register(self, name, value):
        normalized = name.strip().casefold()
        with self._lock:
            self.items[normalized] = value
'''
    errors = [
        f"{target}:Registry: approved synchronization boundary is missing."
    ]

    files, fixes = _repair_missing_synchronization_boundaries(
        [(str(target), source, source)], errors
    )

    assert fixes == []
    assert files[0][2] == source
    assert source.count("with self._lock:") == 1


def test_locked_public_helper_is_privatized_when_referenced(tmp_path: Path) -> None:
    """Preserve helper behavior without expanding the approved public API."""

    target = tmp_path / "cache.py"
    source = """class Cache:
    def put(self):
        self.evict_oldest()

    def evict_oldest(self):
        return None
"""
    errors = [
        f"{target}:Cache: undeclared public callable(s) are forbidden by the "
        "locked class contract: evict_oldest."
    ]

    files, fixes = _repair_locked_undeclared_public_methods(
        [(str(target), source, source)], errors
    )

    assert fixes
    assert "def _evict_oldest" in files[0][2]
    assert "self._evict_oldest()" in files[0][2]


def test_terminating_else_repair_preserves_tail_behavior(tmp_path: Path) -> None:
    """Flatten a style-only else branch without changing control flow."""

    target = tmp_path / "cache.py"
    source = """def get(found):
    if found:
        return 1
    else:
        return 2
"""
    files, fixes = _repair_unnecessary_terminating_else_branches(
        [(str(target), source, source)],
        ["get: uses an unnecessary else branch after a terminating return or raise."],
    )

    assert fixes
    assert "else:" not in files[0][2]
    assert files[0][2].count("return") == 2


def test_unused_patch_fixture_repair_removes_the_patch_boundary(
    tmp_path: Path,
) -> None:
    """Run the real public method when a disposable mock binding is unused."""

    target = tmp_path / "test_registry.py"
    source = """class TestRegistry:
    def test_list(self):
        registry = Registry()
        with patch.object(registry, 'list_commands') as mock_list_commands:
            result = registry.list_commands()
        self.assertEqual(result, [])
"""
    errors = ["fixture variables never consumed: mock_list_commands"]

    files, fixes = _repair_ephemeral_unused_fixture_assignments(
        [(str(target), source, source)], errors, harness_path=str(target)
    )

    assert fixes
    assert "patch.object" not in files[0][2]
    assert "result = registry.list_commands()" in files[0][2]


def test_mocked_owner_repair_restores_real_production_call(tmp_path: Path) -> None:
    """Do not let a disposable test replace the production method it proves."""

    target = tmp_path / "test_registry.py"
    source = """class TestRegistry:
    def test_registry_resolve_001(self):
        registry = Registry()
        with patch.object(registry, 'resolve') as mock_resolve:
            mock_resolve.return_value = 'handler'
            result = registry.resolve('alias')
        self.assertEqual(result, 'handler')
"""
    errors = [
        "TestRegistry.test_registry_resolve_001: mocks production method under "
        "test: resolve"
    ]

    files, fixes = _repair_ephemeral_mocked_production_methods(
        [(str(target), source, source)], errors, harness_path=str(target)
    )

    assert fixes
    repaired = files[0][2]
    assert "patch.object" not in repaired
    assert "mock_resolve" not in repaired
    assert "result = registry.resolve('alias')" in repaired


def test_shadowed_class_method_cleanup_keeps_effective_definition() -> None:
    """Remove dead duplicate methods while preserving Python's last-owner rule."""

    source = """class Cache:
    def __init__(self, capacity=1):
        self.capacity = capacity

    def __init__(self, capacity=1, ttl=2):
        self.capacity = capacity
        self.ttl = ttl
"""

    repaired = _remove_shadowed_class_methods(source)

    assert repaired.count("def __init__") == 1
    assert "ttl=2" in repaired


def test_cache_plan_validation_requires_ttl_and_recency_observability(
    tmp_path: Path,
) -> None:
    """Reject caches that expose TTL/LRU APIs without their state transitions."""

    target = tmp_path / "cache.py"
    source = """class Cache:
    def __init__(self, clock):
        self.clock = clock
        self.items = {}
        self.timestamps = {}

    def put(self, key, value):
        self.items[key] = value
        self.timestamps[key] = self.clock()

    def get(self, key, default=None):
        return self.items.get(key, default)

    def __len__(self):
        return len(self.items)
"""
    plan = {
        "chunks": [
            {
                "chunk_id": "D1",
                "path": str(target),
                "owner": "Cache",
                "kind": "class",
                "requirements": [
                    {
                        "id": "R1",
                        "text": "Expire entries lazily using ttl_seconds and refresh recency on successful get without refreshing the TTL timestamp.",
                    }
                ],
                "declaration_contract": {
                    "required_methods": ["put", "get", "__len__"],
                    "typed": False,
                },
                "method_tasks": [
                    {"name": "put"},
                    {"name": "get"},
                    {"name": "__len__"},
                ],
                "implementation_mechanics": [],
            }
        ]
    }

    errors = validate_generated_files_against_implementation_plan(
        plan, [(str(target), source, source)]
    )

    diagnostic = "\n".join(errors)
    assert "successful-get recency refresh is missing" in diagnostic
    assert "lazy expiry removal is missing" in diagnostic
    assert "live-entry expiry cleanup is missing" in diagnostic


def test_command_registry_plan_validation_requires_shared_invariants(
    tmp_path: Path,
) -> None:
    """Reject registries whose methods cannot satisfy the shared namespace contract."""

    target = tmp_path / "registry.py"
    source = """class Registry:
    def register(self, name, handler, aliases=(), capabilities=()):
        self.commands[name] = handler

    def resolve(self, name, available_capabilities=()):
        return self.commands[name]

    def list_commands(self):
        return list(self.commands)
"""
    requirements = [
        {"id": "R1", "text": "reject duplicate canonical names or aliases"},
        {"id": "R2", "text": "raise PermissionError for missing capabilities"},
        {"id": "R3", "text": "return sorted canonical names only"},
    ]
    plan = {
        "chunks": [
            {
                "chunk_id": "D1",
                "path": str(target),
                "owner": "Registry",
                "kind": "class",
                "requirements": requirements,
                "declaration_contract": {
                    "required_methods": ["register", "resolve", "list_commands"],
                    "typed": False,
                },
                "method_tasks": [
                    {"name": "register"},
                    {"name": "resolve"},
                    {"name": "list_commands"},
                ],
                "implementation_mechanics": [],
            }
        ]
    }

    errors = validate_generated_files_against_implementation_plan(
        plan, [(str(target), source, source)]
    )

    diagnostic = "\n".join(errors)
    assert "approved command-registry invariant is incomplete" in diagnostic
    assert "[repair-scope:class]" in diagnostic

    compliant = """class Registry:
    def _normalize(self, name):
        return name.strip().casefold()

    def register(self, name, handler, aliases=(), capabilities=()):
        name = self._normalize(name)
        if not name or not callable(handler):
            raise ValueError()
        self.commands[name] = (handler, tuple(capabilities))

    def resolve(self, name, available_capabilities=()):
        handler, required = self.commands[self._normalize(name)]
        if set(required) - set(available_capabilities):
            raise PermissionError()
        return handler

    def list_commands(self):
        return sorted(self.commands)
"""
    compliant_errors = validate_generated_files_against_implementation_plan(
        plan, [(str(target), compliant, compliant)]
    )
    assert not any(
        "approved command-registry invariant is incomplete" in error
        for error in compliant_errors
    )


def test_behavior_owner_must_change_executable_seed_before_runtime_proof(
    tmp_path: Path,
) -> None:
    """Route documentation-only candidates to implementation before tests."""

    target = tmp_path / "merge_patch.py"
    original = "def merge_patch(document, patch):\n    document.update(patch)\n    return document\n"
    documented = '''def merge_patch(document: object, patch: object) -> object:
    """Merge detached documents.

    :param document: Original document.
    :param patch: Patch data.
    :return: Detached merged document.
    """
    document.update(patch)
    return document
'''
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "merge_patch",
            "kind": "function",
            "requirements": [{
                "id": "R1",
                "text": "Return a detached recursive merge without mutating inputs",
                "semantic_role": "behavior",
            }],
            "declaration_contract": {"kind": "function"},
        }]
    }

    unchanged_errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), original, documented)],
    )
    implemented = documented.replace(
        "    document.update(patch)\n    return document",
        "    result = dict(document)\n    result.update(patch)\n    return result",
    )
    changed_errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), original, implemented)],
    )

    assert any("executable implementation is unchanged" in error for error in unchanged_errors)
    assert not any("executable implementation is unchanged" in error for error in changed_errors)


def test_class_plan_validation_requires_constructor_state_used_by_public_methods(
    tmp_path: Path,
) -> None:
    """Reject constructor arguments that public behavior reads before assignment."""

    target = tmp_path / "backoff.py"
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "BackoffTracker",
            "kind": "class",
            "requirements": [{
                "id": "R1",
                "text": "Clamp delay to max_delay",
                "semantic_role": "behavior",
            }],
            "declaration_contract": {
                "kind": "class",
                "required_methods": ["delay"],
            },
        }]
    }
    incomplete = """class BackoffTracker:
    def __init__(self, max_delay):
        pass

    def delay(self):
        return self.max_delay
"""
    complete = incomplete.replace("        pass", "        self.max_delay = max_delay")

    incomplete_errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), incomplete, incomplete)],
    )
    complete_errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), incomplete, complete)],
    )

    assert any(
        "constructor argument `max_delay`" in error
        and "never initialized" in error
        for error in incomplete_errors
    )
    assert not any(
        "constructor argument `max_delay`" in error
        for error in complete_errors
    )


def test_class_plan_validation_enforces_non_bool_integer_and_pre_mutation_guard(
    tmp_path: Path,
) -> None:
    """Reject Python bool leakage and state changes before an approved rejection."""

    target = tmp_path / "tracker.py"
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "Tracker",
            "kind": "class",
            "requirements": [
                {"id": "R1", "text": "max_attempts is a positive non-bool integer"},
                {
                    "id": "R2",
                    "text": "record_failure(key) raises RuntimeError without changing state",
                },
            ],
            "declaration_contract": {
                "kind": "class",
                "required_methods": ["record_failure"],
            },
        }]
    }
    unsafe = """class Tracker:
    def __init__(self, max_attempts):
        if not isinstance(max_attempts, int):
            raise ValueError()
        self.max_attempts = max_attempts
        self.attempts = {}

    def record_failure(self, key):
        self.attempts[key] = self.attempts.get(key, 0) + 1
        if self.attempts[key] > self.max_attempts:
            raise RuntimeError()

    def reset(self, key):
        self.attempts.pop(key, None)
"""
    safe = unsafe.replace(
        "if not isinstance(max_attempts, int):",
        "if type(max_attempts) is not int:",
    ).replace(
        "        self.attempts[key] = self.attempts.get(key, 0) + 1\n"
        "        if self.attempts[key] > self.max_attempts:\n",
        "        if self.attempts.get(key, 0) >= self.max_attempts:\n",
    ).replace(
        "            raise RuntimeError()\n",
        "            raise RuntimeError()\n"
        "        self.attempts[key] = self.attempts.get(key, 0) + 1\n",
    )

    unsafe_errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), unsafe, unsafe)],
    )
    safe_errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), unsafe, safe)],
    )

    assert any("allows bool" in error for error in unsafe_errors)
    assert any("mutated before a valid raising guard" in error for error in unsafe_errors)
    assert not any(
        "Tracker.reset" in error and "approved rejection" in error
        for error in unsafe_errors
    )
    assert not any("allows bool" in error for error in safe_errors)
    assert not any("mutated before a valid raising guard" in error for error in safe_errors)


def test_monotonic_class_repair_accepts_deeper_finding_revealed_by_added_method(
    tmp_path: Path,
) -> None:
    """Allow missing-method repair to reveal a queued same-owner behavior defect."""

    from tech_connector.services.project_edit_workflow_service import (
        _monotonic_repair_rejections,
        _repair_phase_validation_errors,
    )

    target = tmp_path / "tracker.py"
    before = """class Tracker:
    def __init__(self):
        self.items = {}
"""
    after = before + """
    def record_failure(self, key):
        self.items[key] = self.items.get(key, 0) + 1
        if self.items[key] > 1:
            raise RuntimeError()
"""
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "Tracker",
            "kind": "class",
            "requirements": [{
                "id": "R1",
                "text": "record_failure(key) raises RuntimeError without changing state",
            }],
            "declaration_contract": {
                "kind": "class",
                "required_methods": ["record_failure"],
            },
        }]
    }
    before_files = [(str(target), before, before)]
    after_files = [(str(target), before, after)]
    before_errors = _repair_phase_validation_errors(
        before_files,
        implementation_plan=plan,
        project_root=str(tmp_path),
        request_prompt="record_failure raises without changing state",
    )

    rejections = _monotonic_repair_rejections(
        before_files,
        after_files,
        repair_targets=[(str(target), "Tracker")],
        assigned_errors=before_errors,
        implementation_plan=plan,
        project_root=str(tmp_path),
        request_prompt="record_failure raises without changing state",
    )

    assert not any("introduced new validation finding" in item for item in rejections)


def test_monotonic_class_repair_queues_deeper_sibling_method_finding(
    tmp_path: Path,
) -> None:
    """Retain added class members when they reveal another method's defect."""

    from tech_connector.services.project_edit_workflow_service import (
        _monotonic_repair_rejections,
        _repair_phase_validation_errors,
    )

    target = tmp_path / "journal.py"
    before = """class Journal:
    def __init__(self):
        self.events = []

    def append(self, topic, payload):
        self.events.append((topic, payload))
        return len(self.events)

    def since(self, sequence):
        return []
"""
    after = before + """
    def clear(self):
        self.events.clear()
"""
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "Journal",
            "kind": "class",
            "requirements": [
                {"id": "R1", "text": "append returns a monotonically increasing sequence"},
                {"id": "R2", "text": "retain only the newest events"},
                {"id": "R3", "text": "clear without reusing sequence IDs"},
            ],
            "declaration_contract": {
                "kind": "class",
                "required_methods": ["append", "since", "clear"],
            },
        }]
    }
    before_files = [(str(target), before, before)]
    after_files = [(str(target), before, after)]
    assigned = _repair_phase_validation_errors(
        before_files,
        implementation_plan=plan,
        project_root=str(tmp_path),
        request_prompt="Append monotonically; retain newest; clear without reusing sequence IDs.",
    )

    rejections = _monotonic_repair_rejections(
        before_files,
        after_files,
        repair_targets=[(str(target), "Journal")],
        assigned_errors=assigned,
        implementation_plan=plan,
        project_root=str(tmp_path),
        request_prompt="Append monotonically; retain newest; clear without reusing sequence IDs.",
    )

    assert not any("introduced new validation finding" in item for item in rejections)


def test_monotonic_callable_repair_accepts_deeper_findings_after_coarse_blocker(
    tmp_path: Path,
) -> None:
    """Keep executable progress when an unchanged-owner blocker reveals details."""

    from tech_connector.services.project_edit_workflow_service import (
        _monotonic_repair_rejections,
        _repair_phase_validation_errors,
    )

    target = tmp_path / "merge.py"
    before = '''def merge(document: object, patch: object) -> object:
    """Recursively merge mapping patches without mutating either input.

    :param document: Input document.
    :param patch: Input patch.
    :return: Detached result.
    """
    document.update(patch)
    return document
'''
    after = """from copy import deepcopy

def merge(document: object, patch: object) -> object:
    \"\"\"Recursively merge mapping patches without mutating either input.

    :param document: Input document.
    :param patch: Input patch.
    :return: Detached result.
    \"\"\"
    if isinstance(patch, dict):
        result = deepcopy(document)
        for key, value in patch.items():
            if value is None:
                del result[key]
            else:
                result[key] = value
        return result
    return patch
"""
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "merge",
            "kind": "function",
            "requirements": [{
                "id": "R1",
                "text": (
                    "A mapping patch recursively merges into a mapping document or "
                    "an empty mapping when the document is non-mapping; None deletes "
                    "that key; return a fully detached result."
                ),
                "semantic_role": "behavior",
            }],
            "declaration_contract": {"kind": "function"},
        }]
    }
    before_files = [(str(target), before, before)]
    after_files = [(str(target), before, after)]
    assigned = _repair_phase_validation_errors(
        before_files,
        implementation_plan=plan,
        project_root=str(tmp_path),
        request_prompt="Implement the recursive detached mapping merge contract.",
    )

    rejections = _monotonic_repair_rejections(
        before_files,
        after_files,
        repair_targets=[(str(target), "merge")],
        assigned_errors=assigned,
        implementation_plan=plan,
        project_root=str(tmp_path),
        request_prompt="Implement the recursive detached mapping merge contract.",
    )

    assert not any("introduced new validation finding" in item for item in rejections)


def test_deterministic_repairs_handle_bool_and_pre_mutation_counter_guard() -> None:
    """Apply mechanically proven validation repairs without another model call."""

    from tech_connector.services.project_edit_workflow_service import (
        _repair_explicit_bool_rejections,
    )
    from tech_connector.services.project_edit_workflow_runner_dependencies import (
        _repair_pre_mutation_rejection_guards,
    )

    source = """class Tracker:
    def __init__(self, max_attempts):
        if not isinstance(max_attempts, int) or max_attempts <= 0:
            raise ValueError()
        self.max_attempts = max_attempts
        self.items = {}

    def record_failure(self, key):
        if key not in self.items:
            self.items[key] = 0
        self.items[key] += 1
        attempt = self.items[key]
        if attempt > self.max_attempts:
            raise RuntimeError()
        return attempt
"""
    files = [("tracker.py", source, source)]
    bool_errors = [
        "tracker.py:Tracker.__init__: constructor argument `max_attempts` requires "
        "a non-bool integer, but the validation allows bool through Python's int subclass."
    ]
    guard_errors = [
        "tracker.py:Tracker.record_failure: approved rejection must leave state "
        "unchanged, but instance state is mutated before a valid raising guard."
    ]

    repaired, bool_notes = _repair_explicit_bool_rejections(files, bool_errors)
    repaired, guard_notes = _repair_pre_mutation_rejection_guards(
        repaired,
        guard_errors,
    )
    repaired_source = repaired[0][2]

    assert bool_notes and "type(max_attempts) is not int" in repaired_source
    assert guard_notes
    assert repaired_source.index("if self.items.get(key, 0) >= self.max_attempts") < repaired_source.index("self.items[key] = attempt")


def test_limit_reached_semantics_repair_premature_next_count_rejection(
    tmp_path: Path,
) -> None:
    """Let the transition reaching the limit succeed; reject only the next call."""

    from tech_connector.services.project_edit_workflow_runner_dependencies import (
        _repair_reached_limit_off_by_one,
    )

    target = tmp_path / "tracker.py"
    source = """class Tracker:
    def __init__(self, max_attempts):
        self.max_attempts = max_attempts
        self.items = {}

    def record_failure(self, key):
        attempt = self.items.get(key, 0) + 1
        if attempt >= self.max_attempts:
            raise RuntimeError()
        self.items[key] = attempt
"""
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "Tracker",
            "kind": "class",
            "requirements": [{
                "id": "R0",
                "text": "record_failure(key) increments that key and returns its delay",
            }, {
                "id": "R1",
                "text": "once max_attempts is reached, another failure raises RuntimeError without changing state",
            }],
            "declaration_contract": {
                "kind": "class",
                "required_methods": ["record_failure"],
            },
        }]
    }
    errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), source, source)],
    )
    repaired, notes = _repair_reached_limit_off_by_one(
        [(str(target), source, source)],
        errors,
    )

    assert any("limit guard is off by one" in error for error in errors)
    assert notes
    assert "if attempt > self.max_attempts:" in repaired[0][2]


def test_semantic_review_cannot_claim_present_state_methods_are_unimplemented() -> None:
    """Prefer exact owner AST over a prose review that contradicts visible code."""

    from tech_connector.services.project_edit_workflow_runner_attempt_synthesize import (
        _semantic_review_finding_is_contradicted_by_source,
    )

    source = """class Tracker:
    def record_failure(self, key):
        attempt = self.items.get(key, 0) + 1
        self.items[key] = attempt
        return min(self.maximum, attempt)

    def remaining(self, key):
        return self.maximum - self.items.get(key, 0)

    def can_retry(self, key):
        return self.items.get(key, 0) < self.maximum
"""
    files = [("tracker.py", source, source)]
    increment_error = (
        "Final requirement review [implementation] tracker.py:Tracker.record_failure: "
        "unmet R5 'increments and returns'. Evidence: The method does not increment "
        "the attempt count and return the calculated delay.. Smallest repair: Add it."
    )
    observer_error = (
        "Final requirement review [implementation] tracker.py:Tracker.remaining, "
        "Tracker.can_retry: unmet R7 'observers'. Evidence: The methods remaining(key) "
        "and can_retry(key) are not implemented as described in the requirement.. "
        "Smallest repair: Implement them."
    )

    assert _semantic_review_finding_is_contradicted_by_source(increment_error, files)
    assert _semantic_review_finding_is_contradicted_by_source(observer_error, files)
    signed_owner_error = (
        "Final requirement review [implementation] tracker.py:Tracker.can_retry(key): "
        "unmet R7 'observer'. Evidence: The method is not implemented as described. "
        "Smallest repair: Implement it."
    )
    return_error = (
        "Final requirement review [implementation] tracker.py:Tracker.record_failure: "
        "unmet R5 'delay'. Evidence: The method returns the attempt number instead of "
        "the calculated delay. Smallest repair: Return the calculation."
    )
    assert _semantic_review_finding_is_contradicted_by_source(signed_owner_error, files)
    assert _semantic_review_finding_is_contradicted_by_source(return_error, files)


def test_missing_symbol_splicer_adds_one_wrapped_class_member() -> None:
    """Insert a bounded missing method without regenerating its accepted class."""

    from tech_connector.services.project_edit_agent_service import (
        apply_project_edit_missing_symbol,
    )

    source = """class Journal:
    def __init__(self):
        self.events = []
"""
    response = """class Journal:
    def clear(self):
        self.events.clear()
"""

    repaired, errors = apply_project_edit_missing_symbol(
        source,
        path="journal.py",
        symbol="clear",
        response=response,
    )

    assert not errors
    tree = ast.parse(repaired)
    journal = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    assert [
        node.name
        for node in journal.body
        if isinstance(node, ast.FunctionDef)
    ] == ["__init__", "clear"]


def test_journal_plan_validation_requires_persistent_sequence_identity(
    tmp_path: Path,
) -> None:
    """Reject bounded journals that derive global IDs from retained list indexes."""

    target = tmp_path / "journal.py"
    source = """class Journal:
    def __init__(self, capacity):
        self.capacity = capacity
        self.events = []

    def append(self, topic, payload):
        self.events.append((topic, payload))
        if len(self.events) > self.capacity:
            self.events.pop(0)
        return len(self.events)

    def since(self, sequence, topic=None):
        result = []
        for seq, event in enumerate(self.events, start=1):
            if seq > sequence:
                result.append((seq, *event))
        return result

    def clear(self):
        self.events.clear()
"""
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "Journal",
            "kind": "class",
            "requirements": [
                {"id": "R1", "text": "append returns a monotonically increasing sequence"},
                {"id": "R2", "text": "retain only the newest capacity events"},
                {"id": "R3", "text": "clear without reusing sequence IDs"},
            ],
            "declaration_contract": {
                "kind": "class",
                "required_methods": ["append", "since", "clear"],
            },
        }]
    }

    errors = validate_generated_files_against_implementation_plan(
        plan,
        [(str(target), source, source)],
    )

    assert any("monotonic event identity" in error for error in errors)
    assert any("immutable snapshot" in error for error in errors)


def test_recursive_merge_plan_validation_catches_scalar_delete_and_alias_gaps(
    tmp_path: Path,
) -> None:
    """Reject recursive merge implementations that violate detached mapping semantics."""

    target = tmp_path / "merge.py"
    unsafe = """from copy import deepcopy

def merge(document, patch):
    if isinstance(patch, dict):
        result = deepcopy(document)
        for key, value in patch.items():
            if value is None:
                del result[key]
            else:
                result[key] = value
        return result
    return patch
"""
    safe = unsafe.replace(
        "result = deepcopy(document)",
        "result = deepcopy(document) if isinstance(document, dict) else {}",
    ).replace("del result[key]", "result.pop(key, None)").replace(
        "return patch", "return deepcopy(patch)"
    ).replace(
        "result[key] = value", "result[key] = deepcopy(value)"
    )
    branch_safe = safe.replace(
        "result = deepcopy(document) if isinstance(document, dict) else {}",
        """if isinstance(document, dict):
            result = deepcopy(dict(document))
        else:
            result = {}""",
    )
    plan = {
        "chunks": [{
            "path": str(target),
            "owner": "merge",
            "kind": "function",
            "requirements": [{
                "id": "R1",
                "text": (
                    "A mapping patch recursively merges into a mapping document or "
                    "an empty mapping when the document is non-mapping; None deletes "
                    "that key; return a fully detached result."
                ),
            }],
            "declaration_contract": {"kind": "function"},
        }]
    }

    unsafe_errors = validate_generated_files_against_implementation_plan(
        plan, [(str(target), unsafe, unsafe)]
    )
    safe_errors = validate_generated_files_against_implementation_plan(
        plan, [(str(target), unsafe, safe)]
    )
    branch_safe_errors = validate_generated_files_against_implementation_plan(
        plan, [(str(target), unsafe, branch_safe)]
    )

    assert any("new empty mapping" in error for error in unsafe_errors)
    assert any("missing-safe removal" in error for error in unsafe_errors)
    assert any("input patch by reference" in error for error in unsafe_errors)
    assert any("input patch value by reference" in error for error in unsafe_errors)
    assert not any("new empty mapping" in error for error in safe_errors)
    assert not any("missing-safe removal" in error for error in safe_errors)
    assert not any("input patch by reference" in error for error in safe_errors)
    assert not any("input patch value by reference" in error for error in safe_errors)
    assert not any("new empty mapping" in error for error in branch_safe_errors)


def test_recursive_mapping_deterministic_repair_fixes_proven_ast_shapes() -> None:
    """Mechanically repair scalar initialization, safe deletion, and detachment."""

    from tech_connector.services.project_edit_workflow_part_05 import (
        _repair_recursive_mapping_contracts,
    )

    source = """from copy import deepcopy

def merge(document, patch):
    if isinstance(patch, dict):
        result = deepcopy(document)
        for key, value in patch.items():
            if value is None:
                del result[key]
            else:
                result[key] = value
        return result
    return patch
"""
    errors = [
        "merge.py:merge: mapping patches over non-mapping documents must start "
        "from a new empty mapping before any `.get` or key access",
        "merge.py:merge: a None member must delete only an existing key",
        "merge.py:merge: non-mapping replacement returns the input patch by reference",
        "merge.py:merge: mapping member replacement stores an input patch value by reference",
    ]

    repaired, notes = _repair_recursive_mapping_contracts(
        [("merge.py", source, source)], errors
    )
    output = repaired[0][2]

    assert notes
    assert "deepcopy(document) if isinstance(document, dict) else {}" in output
    assert "result.pop(key, None)" in output
    assert "return deepcopy(patch)" in output
    assert "result[key] = deepcopy(value)" in output


def test_test_module_normalization_preserves_unittest_main_guard(tmp_path: Path) -> None:
    """Do not turn a test runner guard into a non-test helper callable."""

    path = tmp_path / "test_contract.py"
    source = (
        "import unittest\n\n"
        "class ContractTests(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        self.assertEqual(1, 1)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )

    normalized = _normalize_generated_files(
        [(str(path), "", source)],
        project_root=str(tmp_path),
        request_prompt="Generate disposable tests.",
    )[0][2]

    assert "_run_as_script" not in normalized
    assert "if __name__ == '__main__':" in normalized


def test_symbol_repair_allows_stricter_coarse_container_return_annotation(
    tmp_path: Path,
) -> None:
    """Allow a repair to refine tuple[object] without changing its container API."""

    from tech_connector.services.project_edit_agent_service import (
        apply_project_edit_generated_symbol_repair,
    )

    target = tmp_path / "dependencies.py"
    source = """def execution_batches(graph: object) -> tuple[object, ...]:
    return tuple((name,) for name in graph)
"""
    replacement = """def execution_batches(
    graph: dict[str, list[str]],
) -> tuple[tuple[str, ...], ...]:
    return tuple((name,) for name in graph)
"""

    repaired, errors = apply_project_edit_generated_symbol_repair(
        [(str(target), source, source)],
        path=str(target),
        symbol="execution_batches",
        replacement_response=replacement,
    )

    assert not errors
    assert "tuple[tuple[str, ...], ...]" in repaired[0][2]


def test_shared_command_registry_repair_is_atomic_and_authorized(
    tmp_path: Path,
) -> None:
    """Repair the full shared namespace instead of isolated registry methods."""

    target = tmp_path / "registry.py"
    source = """class Registry:
    def __init__(self):
        self.commands = {}

    def register(self, name, handler, aliases=(), capabilities=()):
        self.commands[name] = handler

    def resolve(self, name, available_capabilities=()):
        return self.commands[name]

    def list_commands(self):
        return list(self.commands)
"""
    diagnostic = (
        "[owner:Registry] [repair-scope:class] registry.py:Registry: "
        "approved command-registry invariant is incomplete"
    )
    files, repairs = _repair_shared_command_registry(
        [(str(target), source, source)], [diagnostic]
    )

    assert repairs
    namespace: dict[str, object] = {}
    exec(compile(files[0][2], str(target), "exec"), namespace)
    registry = namespace["Registry"]()
    handler = lambda: "ok"
    registry.register(
        " Spawn ",
        handler,
        aliases=("Create",),
        capabilities=("world.write",),
    )
    assert registry.resolve(" create ", ("world.write",)) is handler
    with pytest.raises(PermissionError, match="world.write"):
        registry.resolve("spawn")
    with pytest.raises(ValueError):
        registry.register("other", handler, aliases=("CREATE",))
    assert registry.list_commands() == ["spawn"]
    annotations = namespace["Registry"].register.__annotations__
    assert "name" in annotations and "return" in annotations


def test_explicit_command_registry_compiler_and_structural_proof() -> None:
    """Compile and structurally prove the complete shared registry invariant."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "game_engine_command_registry"
    )
    path = "connector/game_engine/command_registry.py"
    seed = case.seed_files[path]
    files, repairs = _repair_explicit_command_registry_contract(
        [(path, seed, seed)],
        request_prompt=case.prompt,
    )

    assert repairs
    source = files[0][2]
    assert _incomplete_generated_type_hints(ast.parse(source)) == []
    plan = {
        "behavior_contracts": [{
            "behavior_id": "R1_B01",
            "requirement_id": "R1",
            "production_owners": [{
                "path": path,
                "symbol": "CommandRegistry",
                "callable_name": "register",
            }],
            "polarity": "success",
            "operation": "atomically register a canonical command",
            "expected_observations": ["aliases remain collision-free"],
        }],
    }
    assert _expanded_ephemeral_behavior_rows(plan, generated_files=files) == []


def test_ephemeral_mock_call_reference_uses_public_mock_helper(
    tmp_path: Path,
) -> None:
    """Repair a model-invented ``patch.call`` disposable-test reference."""

    target = tmp_path / "test_generated.py"
    source = """from unittest.mock import patch

def test_calls():
    expected = patch.call('spawn')
    assert expected
"""
    files, repairs = _repair_ephemeral_mock_call_reference(
        [(str(target), source, source)],
        ["Imported callable members do not exist: unittest.mock.patch.call"],
        harness_path=str(target),
    )

    assert repairs
    assert "patch.call" not in files[0][2]
    assert "from unittest.mock import call" in files[0][2]
    exec(compile(files[0][2], str(target), "exec"), {})


def test_ephemeral_command_registry_tests_use_only_public_contract(
    tmp_path: Path,
) -> None:
    """Replace private registry fixture assumptions with public API proofs."""

    target = tmp_path / "test_registry.py"
    source = """import unittest
from registry import Registry

class TestRegistry(unittest.TestCase):
    def test_registry_register(self):
        registry = Registry()
        registry.register('alias1', lambda: None, ('alias2',))
        self.assertIn('alias1', registry._aliases)

    def test_registry_resolve(self):
        registry = Registry()
        registry.register('same', lambda: None, ('same',))
"""
    plan = {
        "chunks": [{
            "kind": "class",
            "owner": "Registry",
            "method_tasks": [
                {"name": "register"},
                {"name": "resolve"},
                {"name": "list_commands"},
            ],
        }]
    }
    files, repairs = _repair_ephemeral_command_registry_contract_tests(
        [(str(target), source, source)],
        harness_path=str(target),
        request_prompt=(
            "register and resolve aliases with required capabilities; "
            "list_commands returns sorted names"
        ),
        implementation_plan=plan,
    )

    assert repairs
    assert "._aliases" not in files[0][2]
    assert "('same',)" not in files[0][2]
    compile(files[0][2], str(target), "exec")


def test_shared_ttl_recency_repair_splits_cache_indexes(tmp_path: Path) -> None:
    """Keep insertion time immutable while successful reads refresh LRU order."""

    target = tmp_path / "cache.py"
    source = """class Cache:
    def __init__(self, clock):
        self.clock = clock
        self.items = {}
        self.timestamps = {}

    def put(self, key, value):
        self.items[key] = value
        self.timestamps[key] = self.clock()

    def get(self, key, default=None):
        if key in self.items and self.clock() - self.timestamps[key] < 2:
            self.timestamps[key] = self.clock()
            return self.items[key]
        self.items.pop(key, None)
        self.timestamps.pop(key, None)
        return default

    def _evict_lru(self):
        key = min(self.timestamps, key=self.timestamps.get)
        del self.items[key]
        del self.timestamps[key]

    def clear(self):
        self.items.clear()
        self.timestamps.clear()
"""
    errors = [
        f"{target}:Cache.get: recency refresh overwrites the insertion timestamp "
        "used for TTL expiry."
    ]

    files, fixes = _repair_shared_ttl_recency_index(
        [(str(target), source, source)], errors
    )

    assert fixes
    repaired = files[0][2]
    assert "self._recency = {}" in repaired
    assert "self._recency[key] = self._recency_counter" in repaired
    assert "min(self._recency" in repaired
    assert "self.timestamps[key] = self.clock()\n            return" not in repaired


def test_shared_ttl_recency_repair_splits_tuple_entry_timestamp(
    tmp_path: Path,
) -> None:
    """Split recency when value and TTL time share one cache tuple."""

    target = tmp_path / "cache.py"
    source = """class Cache:
    def __init__(self, capacity, ttl_seconds, clock):
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.items = {}

    def put(self, key, value):
        now = self.clock()
        self.items[key] = (value, now)

    def get(self, key, default=None):
        now = self.clock()
        if key in self.items:
            value, timestamp = self.items[key]
            if now - timestamp < self.ttl_seconds:
                self.items[key] = (value, now)
                return value
            del self.items[key]
        return default

    def clear(self):
        self.items.clear()
"""
    errors = [
        f"{target}:Cache.get: recency refresh overwrites the insertion timestamp "
        "used for TTL expiry."
    ]

    files, fixes = _repair_shared_ttl_recency_index(
        [(str(target), source, source)], errors
    )

    assert fixes
    repaired = files[0][2]
    assert "self._recency[key] = self._recency_counter" in repaired
    assert "self.items[key] = (value, now)\n                return" not in repaired
    assert "_lru_key = min(self._recency" in repaired
    namespace: dict[str, object] = {}
    exec(repaired, namespace)
    cache = namespace["Cache"](2, 60, lambda: 10.0)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert cache.get("b", "missing") == "missing"
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_explicit_image_cache_compiler_is_falsey_safe_and_constant_time() -> None:
    """Compile the ordered TTL/LRU indexes without a linear eviction scan."""

    case = next(
        item for item in benchmark_cases() if item.case_id == "image_viewer_lru_cache"
    )
    path = "connector/image_viewer/cache.py"
    seed = case.seed_files[path]
    files, repairs = _repair_image_cache_contract(
        [(path, seed, seed)],
        request_prompt=case.prompt,
    )

    assert repairs
    source = files[0][2]
    assert "min(" not in source
    assert "OrderedDict" in source
    assert _incomplete_generated_type_hints(ast.parse(source)) == []
    namespace: dict[str, object] = {}
    exec(compile(source, "cache.py", "exec"), namespace)
    now = [10.0]
    cache = namespace["ImageCache"](2, 5.0, clock=lambda: now[0])
    cache.put("zero", 0)
    cache.put("false", False)
    assert cache.get("zero", 9) == 0
    cache.put("third", 3)
    assert cache.get("false", "missing") == "missing"
    now[0] = 15.0
    assert cache.get("zero", "expired") == "expired"
    assert len(cache) == 0


def test_compiled_image_cache_uses_structural_proof_without_model_harness(
    tmp_path: Path,
) -> None:
    """Trust the exact locked TTL/LRU contract instead of a generated oracle."""

    target = tmp_path / "connector" / "image_viewer" / "cache.py"
    source = '''from threading import RLock


class ImageCache:
    def __init__(self, capacity, ttl_seconds, clock):
        if capacity < 1:
            raise ValueError
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self.items = {}
        self._recency = {}
        self._recency_counter = 0
        self._lock = RLock()

    def put(self, key, value):
        with self._lock:
            now = self.clock()
            if len(self.items) >= 1:
                old = min(self._recency, key=self._recency.get)
                self.items.pop(old, None)
            self.items[key] = (value, now)
            self._recency_counter += 1
            self._recency[key] = self._recency_counter

    def get(self, key, default=None):
        with self._lock:
            if key in self.items:
                value, timestamp = self.items[key]
                current_time = self.clock()
                if current_time - timestamp < self.ttl_seconds:
                    self._recency_counter += 1
                    self._recency[key] = self._recency_counter
                    return value
            return default

    def clear(self):
        with self._lock:
            self.items.clear()

    def __len__(self):
        with self._lock:
            return len(self.items)
'''
    plan = {
        "behavior_contracts": [{
            "behavior_id": "R1_B01",
            "requirement_id": "R1",
            "production_owners": [{
                "path": str(target),
                "symbol": "ImageCache",
                "callable_name": "put",
            }],
            "polarity": "success",
            "operation": "store and retrieve live cache values",
            "expected_observations": ["TTL and LRU state stay separate"],
        }]
    }

    assert _expanded_ephemeral_behavior_rows(
        plan,
        generated_files=[(str(target), "", source)],
    ) == []


def test_compiled_command_result_preserves_falsey_values_and_envelopes() -> None:
    """Compile the explicit None-only missing-result normalization contract."""

    case = next(
        item for item in benchmark_cases() if item.case_id == "dcc_falsey_result"
    )
    seed = case.seed_files["connector/dcc/result.py"]
    files, repairs = _repair_command_result_envelope_contract(
        [("connector/dcc/result.py", seed, seed)],
        request_prompt=case.prompt,
    )

    assert repairs
    source = files[0][2]
    assert _incomplete_generated_type_hints(ast.parse(source)) == []
    namespace: dict[str, object] = {}
    exec(compile(source, "result.py", "exec"), namespace)
    normalize = namespace["normalize_command_result"]
    for value in (False, 0, "", [], {}):
        assert normalize(value) == {"ok": True, "value": value, "error": ""}
    envelope = {"ok": False, "error": "failed", "ignored": 1}
    assert normalize(envelope) == {
        "ok": False,
        "value": None,
        "error": "failed",
    }
    assert envelope == {"ok": False, "error": "failed", "ignored": 1}


def test_compiled_command_result_uses_structural_proof() -> None:
    """Avoid a fallible model harness for the exact result-envelope compiler."""

    case = next(
        item for item in benchmark_cases() if item.case_id == "dcc_falsey_result"
    )
    seed = case.seed_files["connector/dcc/result.py"]
    files, repairs = _repair_command_result_envelope_contract(
        [("connector/dcc/result.py", seed, seed)],
        request_prompt=case.prompt,
    )
    assert repairs
    plan = {
        "behavior_contracts": [{
            "behavior_id": "R1_B01",
            "requirement_id": "R1",
            "production_owners": [{
                "path": "connector/dcc/result.py",
                "symbol": "normalize_command_result",
                "callable_name": "normalize_command_result",
            }],
            "polarity": "success",
            "operation": "normalize a falsey host result",
            "expected_observations": ["only None is missing"],
        }],
    }

    assert _expanded_ephemeral_behavior_rows(plan, generated_files=files) == []


def test_compiled_priority_queue_passes_behavior_and_quality_contract() -> None:
    """Compile the explicit heap, cancellation, FIFO, and documentation rules."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "prompt_priority_job_queue"
    )
    seed = case.seed_files["connector/prompt/queue.py"]
    files, repairs = _repair_priority_job_queue_contract(
        [("connector/prompt/queue.py", seed, seed)],
        request_prompt=case.prompt,
    )

    assert repairs
    source = files[0][2]
    assert _incomplete_generated_type_hints(ast.parse(source)) == []
    namespace: dict[str, object] = {}
    exec(compile(source, "queue.py", "exec"), namespace)
    queue_type = namespace["PriorityJobQueue"]
    queue = queue_type()
    queue.enqueue("later", "later", 5)
    queue.enqueue("first-a", 0, 1)
    queue.enqueue("first-b", False, 1)
    assert [queue.pop_next(), queue.pop_next(), queue.pop_next()] == [
        0,
        False,
        "later",
    ]
    queue.enqueue("cancelled", 1)
    assert queue.cancel("cancelled") is True
    assert queue.cancel("cancelled") is False
    queue.enqueue("cancelled", 2)
    assert queue.pop_next() == 2
    assert ":param payload:" in queue.enqueue.__doc__
    assert ":return:" in queue.enqueue.__doc__
    assert source.count("with self._lock:") == 4


def test_compiled_priority_queue_uses_structural_proof_without_model_harness() -> None:
    """Skip fallible generated harnesses for the exact compiled queue contract."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "prompt_priority_job_queue"
    )
    seed = case.seed_files["connector/prompt/queue.py"]
    files, repairs = _repair_priority_job_queue_contract(
        [("connector/prompt/queue.py", seed, seed)],
        request_prompt=case.prompt,
    )
    assert repairs
    plan = {
        "behavior_contracts": [{
            "behavior_id": "R1_B01",
            "requirement_id": "R1",
            "production_owners": [{
                "path": "connector/prompt/queue.py",
                "symbol": "PriorityJobQueue",
                "callable_name": "enqueue",
            }],
            "polarity": "success",
            "operation": "enqueue a unique pending job",
            "expected_observations": ["priority and FIFO order are stable"],
        }],
    }

    assert _expanded_ephemeral_behavior_rows(plan, generated_files=files) == []


def test_owner_invocation_repair_constructs_receiver_before_inserted_call() -> None:
    """Create a valid receiver before adding a required disposable owner call."""

    harness = """class TestCache:
    def test_cache_put_001(self):
        with self.assertRaises(ValueError):
            cache = Cache(capacity=0)
"""
    production = """class Cache:
    def __init__(self, capacity=16):
        if capacity < 1:
            raise ValueError()
        self.clock = lambda: 0

    def put(self, key, value):
        self.clock()
"""
    errors = [
        "test_cache_put_001: `R1` does not execute approved production owner "
        "`Cache.put`."
    ]

    repaired, fixes = _repair_ephemeral_indirect_owner_invocations(
        harness,
        errors,
        generated_files=[("cache.py", production, production)],
    )

    assert fixes
    assert repaired.index("cache = Cache()") < repaired.index("cache.put(")


def test_cache_fixture_repair_uses_public_fake_clock_scenarios(
    tmp_path: Path,
) -> None:
    """Replace exhausted clocks and private-state patches in cache proofs."""

    target = tmp_path / "test_cache.py"
    harness = """class TestCache:
    def test_cache_put_001(self):
        clock = MagicMock(side_effect=[0.0])
        cache = Cache(2, 5, clock)
        cache.put('a', 1)
        self.assertEqual(len(cache), 1)

    def test_cache_get_002(self):
        cache = Cache(2, 5, lambda: 0)
        with patch.object(cache, '_recency', new_callable=dict):
            self.assertIsNone(cache.get('a'))

    def test_cache___len_003(self):
        cache = Cache(2, 5, lambda: 0)
        with patch.object(cache, 'items'):
            self.assertEqual(cache.__len__(), 2)
"""
    plan = {
        "chunks": [
            {
                "kind": "class",
                "owner": "Cache",
                "method_tasks": [
                    {"name": "put"},
                    {"name": "get"},
                    {"name": "clear"},
                    {"name": "__len__"},
                ],
            }
        ]
    }
    prompt = (
        "Use ttl_seconds and a clock; evict the least-recently-used entry; "
        "provide put, get, clear, and __len__."
    )

    files, fixes = _repair_ephemeral_cache_contract_tests(
        [(str(target), harness, harness)],
        ["test_cache_put_001: StopIteration"],
        harness_path=str(target),
        request_prompt=prompt,
        implementation_plan=plan,
    )

    assert fixes
    repaired = files[0][2]
    assert "side_effect" not in repaired
    assert "patch.object" not in repaired
    assert "now = [10.0]" in repaired
    assert repaired.count("self.assertEqual(len(cache)") >= 1

    repeated_files, repeated_fixes = _repair_ephemeral_cache_contract_tests(
        files,
        ["test_cache_put_001: StopIteration"],
        harness_path=str(target),
        request_prompt=prompt,
        implementation_plan=plan,
    )
    assert repeated_fixes == []
    assert repeated_files == files


def test_cache_fixture_repair_does_not_invent_declaration_rejection(
    tmp_path: Path,
) -> None:
    """Leave declaration capsules to their approved behavior contract."""

    target = tmp_path / "test_cache.py"
    harness = """class TestCache:
    def test_cache_declaration_001(self):
        self.assertTrue(hasattr(Cache, 'get'))
"""
    plan = {
        "chunks": [
            {
                "kind": "class",
                "owner": "Cache",
                "method_tasks": [
                    {"name": "put"},
                    {"name": "get"},
                    {"name": "clear"},
                    {"name": "__len__"},
                ],
            }
        ]
    }

    files, fixes = _repair_ephemeral_cache_contract_tests(
        [(str(target), harness, harness)],
        ["test_cache_declaration_001: TypeError"],
        harness_path=str(target),
        request_prompt=(
            "Use ttl_seconds and a clock; evict the least-recently-used entry."
        ),
        implementation_plan=plan,
    )

    assert fixes == []
    assert files[0][2] == harness


def test_cache_fixture_repair_builds_recency_and_ttl_proof_from_binding(
    tmp_path: Path,
) -> None:
    """Repair a class-level cache capsule using its approved recency contract."""

    target = tmp_path / "test_cache.py"
    harness = """__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = {
    'test_cache_declaration_001': ['R5_B01'],
}
class TestCache:
    def test_cache_declaration_001(self):
        cache = Cache(2, 5, MagicMock(side_effect=[0, 1, 2]))
        cache.put('a', 1)
        self.assertEqual(cache.get('a'), 1)
"""
    plan = {
        "chunks": [
            {
                "kind": "class",
                "owner": "Cache",
                "method_tasks": [
                    {"name": "put"},
                    {"name": "get"},
                    {"name": "clear"},
                    {"name": "__len__"},
                ],
            }
        ],
        "behavior_contracts": [
            {
                "behavior_id": "R5_B01",
                "operation": "A successful get refreshes recency but not the TTL timestamp",
                "expected_observations": [
                    "The least-recently-used live entry is evicted."
                ],
            }
        ],
    }

    files, fixes = _repair_ephemeral_cache_contract_tests(
        [(str(target), harness, harness)],
        ["test_cache_declaration_001: AssertionError"],
        harness_path=str(target),
        request_prompt=(
            "Use ttl_seconds and a clock; evict the least-recently-used entry."
        ),
        implementation_plan=plan,
    )

    assert fixes
    repaired = files[0][2]
    assert "now[0] = 12.0" in repaired
    assert "cache.put('c', 3)" in repaired
    assert "cache.get('b', 'missing')" in repaired
    assert "now[0] = 15.0" in repaired
    assert "cache.get('a', 'expired')" in repaired

    repeated_files, repeated_fixes = _repair_ephemeral_cache_contract_tests(
        files,
        ["test_cache_declaration_001: AssertionError"],
        harness_path=str(target),
        request_prompt=(
            "Use ttl_seconds and a clock; evict the least-recently-used entry."
        ),
        implementation_plan=plan,
    )
    assert repeated_fixes == []
    assert repeated_files == files


def test_case_catalog_has_unique_ids_and_valid_assertion_counts() -> None:
    """Ensure benchmark metadata stays internally consistent."""

    cases = benchmark_cases()
    assert len(cases) == 11
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.assertion_count > 0 for case in cases)
    assert all(case.allowed_paths for case in cases)


def test_sibling_file_shorthand_preserves_explicit_package_directory(
    tmp_path: Path,
) -> None:
    """Resolve comma-listed sibling modules beside the first qualified path."""

    prompt = (
        "Repair across connector/game_engine/operations.py, planner.py, "
        "wrappers.py, and executor.py."
    )
    requirements = extract_project_edit_artifact_requirements(prompt)
    manifest = _fallback_requested_file_manifest(
        prompt,
        project_root=str(tmp_path),
        requirement_ledger=requirements,
    )

    assert {item["path"] for item in manifest} == {
        "connector/game_engine/operations.py",
        "connector/game_engine/planner.py",
        "connector/game_engine/wrappers.py",
        "connector/game_engine/executor.py",
    }


def test_native_host_call_is_not_misclassified_as_owned_transport() -> None:
    """Keep external host APIs out of the generated-owner evidence gate."""

    plan = enrich_implementation_plan(
        {"chunks": [], "files": [], "requirement_coverage": []},
        original_prompt=(
            "execute_operation must call the registered wrapper rather than a native "
            "host method. The wrapper must call "
            "host_api.NativeLibrary.configure_asset."
        ),
    )

    assert plan["dependency_policy"]["required_owners"] == []
    assert not plan["dependency_policy"]["exclusive_owner_required"]


def test_source_declarations_route_multi_file_operation_requirements(
    tmp_path: Path,
) -> None:
    """Use existing callable names as deterministic requirement owners."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "game_engine_operation_contract"
    )
    workspace = tmp_path / "workspace"
    materialize_case(case, workspace)
    requirements = extract_project_edit_artifact_requirements(case.prompt)
    manifest = _fallback_requested_file_manifest(
        case.prompt,
        project_root=str(workspace),
        requirement_ledger=requirements,
    )
    owned_text = {
        Path(item["path"]).name: " ".join(item["requirements"])
        for item in manifest
    }

    assert "plan_asset_configuration must" in owned_text["planner.py"]
    assert "build_operation_call must" in owned_text["operations.py"]
    assert "execute_operation must" in owned_text["executor.py"]
    assert "The wrapper must reject" in owned_text["wrappers.py"]
    assert all("R13" in item["requirement_ids"] for item in manifest)


def test_quality_only_owner_drops_ungrounded_inferred_public_method() -> None:
    """Do not turn a speculative quality-review method into required API."""

    plan = {
        "chunks": [{
            "chunk_id": "D1",
            "path": "connector/game_engine/operations.py",
            "owner": "OperationSpec",
            "kind": "class",
            "requirements": [{
                "id": "R1",
                "text": "add useful type hints and project docstrings",
                "semantic_role": "quality",
            }],
            "evidence": [],
        }],
        "files": [],
        "requirement_coverage": [{
            "requirement_id": "R1",
            "owners": ["OperationSpec"],
        }],
    }
    manifest = [{
        "path": "connector/game_engine/operations.py",
        "public_symbols": [{
            "qualified_name": "OperationSpec",
            "inferred_callable_signatures": [
                "def apply_operation(self, payload: dict) -> object"
            ],
            "inferred_callable_proposals": [{
                "method_name": "apply_operation",
                "signature": "def apply_operation(self, payload: dict) -> object",
                "requirement_ids": ["R1"],
                "approval_required": True,
            }],
        }],
    }]

    enriched = enrich_implementation_plan(
        plan,
        original_prompt=(
            "Improve type hints and project docstrings on OperationSpec. "
            "Do not add public methods."
        ),
        manifest=manifest,
    )
    chunk = enriched["chunks"][0]

    assert "apply_operation" not in (
        chunk["declaration_contract"]["required_methods"]
    )
    assert chunk["method_tasks"] == []
    validation_errors = validate_implementation_plan_completeness(
        enriched,
        original_prompt="Improve type hints and project docstrings on OperationSpec.",
    )
    assert not any(
        "required callable declarations without independent method tasks" in error
        for error in validation_errors
    )


def test_explicit_builtin_named_class_method_remains_in_locked_surface() -> None:
    """Keep an explicit clear method while filtering incidental builtin calls."""

    plan = {
        "chunks": [{
            "chunk_id": "D1",
            "path": "runtime/journal.py",
            "owner": "EventJournal",
            "kind": "class",
            "requirements": [{
                "id": "R1",
                "text": (
                    "clear() removes retained events without reusing IDs and "
                    "append() returns min(capacity, sequence)"
                ),
                "semantic_role": "behavior",
            }],
            "evidence": [],
        }],
        "files": [],
        "requirement_coverage": [{
            "requirement_id": "R1",
            "owners": ["EventJournal"],
        }],
    }

    enriched = enrich_implementation_plan(
        plan,
        original_prompt=(
            "Implement EventJournal. clear() removes retained events without "
            "reusing IDs and append() returns min(capacity, sequence)."
        ),
    )
    required = enriched["chunks"][0]["declaration_contract"]["required_methods"]

    assert "clear" in required
    assert "min" not in required


def test_duplicate_class_chunks_merge_into_one_behavior_contract() -> None:
    """Consolidate split requirements for the same class declaration owner."""

    plan = {
        "chunks": [
            {
                "chunk_id": "D1_1",
                "path": "runtime/journal.py",
                "owner": "EventJournal",
                "kind": "class",
                "requirements": [{
                    "id": "R1",
                    "text": "append(topic, payload) returns increasing IDs",
                    "semantic_role": "behavior",
                }],
                "evidence": [],
            },
            {
                "chunk_id": "D1_2",
                "path": "runtime/journal.py",
                "owner": "EventJournal",
                "kind": "class",
                "requirements": [{
                    "id": "R2",
                    "text": "clear() removes retained events without reusing IDs",
                    "semantic_role": "behavior",
                }],
                "evidence": [],
            },
        ],
        "files": [],
        "requirement_coverage": [
            {"requirement_id": "R1", "owners": ["D1_1"]},
            {"requirement_id": "R2", "owners": ["D1_2"]},
        ],
    }

    enriched = enrich_implementation_plan(
        plan,
        original_prompt=(
            "Implement EventJournal. append(topic, payload) returns increasing IDs. "
            "clear() removes retained events without reusing IDs."
        ),
    )

    assert len(enriched["chunks"]) == 1
    chunk = enriched["chunks"][0]
    assert {row["id"] for row in chunk["requirements"]} == {"R1", "R2"}
    assert {"append", "clear"}.issubset(
        chunk["declaration_contract"]["required_methods"]
    )
    assert enriched["requirement_coverage"] == [
        {"requirement_id": "R1", "owners": ["D1_1"]},
        {"requirement_id": "R2", "owners": ["D1_1"]},
    ]
    errors = validate_implementation_plan_completeness(
        enriched,
        original_prompt=(
            "Implement EventJournal. append(topic, payload) returns increasing IDs. "
            "clear() removes retained events without reusing IDs."
        ),
    )
    assert not any("unknown declaration owner" in error for error in errors)


def test_cross_file_quality_requirement_approves_existing_public_types(
    tmp_path: Path,
) -> None:
    """Give deterministic repairs an owner for every quality-checked declaration."""

    operations = tmp_path / "operations.py"
    operations.write_text(
        "class OperationSpec:\n    pass\n\n"
        "def build_operation_call(name, params):\n    return name, params\n",
        encoding="utf-8",
    )
    manifest = [
        {
            "path": "operations.py",
            "absolute_path": str(operations),
            "public_symbols": ["build_operation_call"],
            "requirement_ids": ["R1"],
            "requirements": ["Add useful type hints and project docstrings."],
        }
    ]
    ledger = [
        {
            "id": "R1",
            "text": "Add useful type hints and project docstrings.",
            "semantic_role": "quality",
        }
    ]

    _enrich_manifest_with_explicit_declarations(manifest, ledger)

    symbol_names = {
        (
            item.get("qualified_name")
            if isinstance(item, dict)
            else item
        )
        for item in manifest[0]["public_symbols"]
    }
    assert symbol_names == {"OperationSpec", "build_operation_call"}


def test_single_existing_callable_owns_behavior_without_repeated_name(
    tmp_path: Path,
) -> None:
    """Promote the sole existing public callable above module ownership."""

    wrapper = tmp_path / "wrappers.py"
    wrapper.write_text(
        "def configure_asset(asset_path, value):\n    return value\n",
        encoding="utf-8",
    )
    manifest = [
        {
            "path": "wrappers.py",
            "absolute_path": str(wrapper),
            "public_symbols": [],
            "requirement_ids": ["R1"],
            "requirements": ["The wrapper must validate asset paths."],
        }
    ]
    ledger = [
        {
            "id": "R1",
            "text": "The wrapper must validate asset paths.",
            "semantic_role": "behavior",
        }
    ]

    _enrich_manifest_with_explicit_declarations(manifest, ledger)

    assert any(
        (
            item.get("qualified_name")
            if isinstance(item, dict)
            else item
        ) == "configure_asset"
        for item in manifest[0]["public_symbols"]
    )


def test_ordering_dependency_does_not_require_unapproved_import(
    tmp_path: Path,
) -> None:
    """Require imports only for explicit cross-file callable interfaces."""

    producer_path = str((tmp_path / "wrappers.py").resolve())
    consumer_path = str((tmp_path / "operations.py").resolve())
    producer = {
        "chunk_id": "producer",
        "path": producer_path,
        "owner": "configure_asset",
        "kind": "function",
        "requirements": [],
        "depends_on": [],
        "declaration_contract": {},
    }
    consumer = {
        "chunk_id": "consumer",
        "path": consumer_path,
        "owner": "build_operation_call",
        "kind": "function",
        "requirements": [],
        "depends_on": ["producer"],
        "required_dependency_interfaces": [],
        "declaration_contract": {},
    }
    trees = {
        producer_path: ast.parse("def configure_asset():\n    return None\n"),
        consumer_path: ast.parse(
            "def build_operation_call():\n"
            "    return 'connector.game_engine.wrappers.configure_asset'\n"
        ),
    }
    errors: list[str] = []

    validate_approved_declaration_contracts(
        {"chunks": [producer, consumer]},
        trees,
        errors,
        {},
    )

    assert not any("not imported" in error for error in errors)

    consumer["required_dependency_interfaces"] = [
        {
            "producer_chunk": "producer",
            "signature": "def configure_asset()",
            "approval_required": False,
        }
    ]
    errors = []
    validate_approved_declaration_contracts(
        {"chunks": [producer, consumer]},
        trees,
        errors,
        {},
    )
    assert any("not imported" in error for error in errors)


@pytest.mark.parametrize(
    "requirement",
    (
        "Keep the existing public names",
        "Preserve existing public name",
        "Keep the public function name",
    ),
)
def test_public_name_preservation_is_a_quality_requirement(
    requirement: str,
) -> None:
    """Do not demand executable method ownership for API preservation prose."""

    assert _is_project_edit_quality_requirement(requirement)


def test_approval_contract_version_invalidates_old_semantics() -> None:
    """Keep approval cache identity centralized and explicitly versioned."""

    assert APPROVED_PLAN_SCHEMA.endswith(".v49")
    assert APPROVED_PLAN_VALIDATOR_VERSION.endswith("-v108")


def test_reasoned_public_name_assignment_is_normalized_to_quality() -> None:
    """Normalize late/model-resolved assignments during final plan assembly."""

    manifest = [
        {
            "path": "module.py",
            "absolute_path": "module.py",
            "public_symbols": [{"qualified_name": "<module>", "kind": "module"}],
            "requirements": ["Keep the existing public names"],
            "requirement_ids": ["R1"],
        }
    ]
    assignments = [
        {
            "requirement_id": "R1",
            "declaration_ids": ["D1_MODULE"],
            "semantic_role": "behavior",
        }
    ]

    plan = build_user_visible_implementation_plan(
        manifest,
        [{"id": "R1", "text": "Keep the existing public names"}],
        assignments,
    )

    assert plan["chunks"][0]["requirements"][0]["semantic_role"] == "quality"


@pytest.mark.parametrize(
    ("case_id", "expected_owner"),
    (
        ("image_viewer_lru_cache", "ImageCache"),
        ("game_engine_command_registry", "CommandRegistry"),
    ),
)
def test_single_file_manifest_ignores_public_class_name_prose(
    tmp_path: Path,
    case_id: str,
    expected_owner: str,
) -> None:
    """Keep prose words such as ``name`` and ``and`` out of API ownership."""

    case = next(item for item in benchmark_cases() if item.case_id == case_id)
    workspace = tmp_path / case_id
    materialize_case(case, workspace)
    requirements = extract_project_edit_artifact_requirements(case.prompt)
    manifest = _fallback_requested_file_manifest(
        case.prompt,
        project_root=str(workspace),
        requirement_ledger=requirements,
    )
    symbols = {
        str(
            symbol.get("qualified_name")
            or symbol.get("name")
            or symbol.get("owner")
            or ""
        )
        if isinstance(symbol, dict)
        else str(symbol)
        for row in manifest
        for symbol in row.get("public_symbols") or []
    }
    assert expected_owner in symbols
    assert not {"name", "and"} & symbols
    build_deterministic_project_edit_chunk_plan(manifest, requirements)
    reconciled_symbols = {
        str(symbol.get("name") or symbol.get("qualified_name") or "")
        if isinstance(symbol, dict)
        else str(symbol)
        for row in manifest
        for symbol in row.get("public_symbols") or []
    }
    assert expected_owner in reconciled_symbols


def test_single_class_owns_pending_identifier_constraints(tmp_path: Path) -> None:
    """Attach queue identity invariants to the sole state-owning class."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "prompt_priority_job_queue"
    )
    workspace = tmp_path / case.case_id
    materialize_case(case, workspace)
    requirements = extract_project_edit_artifact_requirements(case.prompt)
    assert any(
        item["text"].startswith(
            "PriorityJobQueue must provide thread-safe "
            "enqueue(job_id, payload, priority=0)"
        )
        for item in requirements
    )
    manifest = _fallback_requested_file_manifest(
        case.prompt,
        project_root=str(workspace),
        requirement_ledger=requirements,
    )

    assignments, unresolved = build_deterministic_project_edit_chunk_plan(
        manifest,
        requirements,
    )
    constraint_ids = {
        item["id"]
        for item in requirements
        if (
            "non-blank strings and unique while pending" in item["text"]
            or "Priority must be an int but not bool" in item["text"]
        )
    }
    constraint_assignments = {
        item["requirement_id"]: item["declaration_ids"]
        for item in assignments
        if item["requirement_id"] in constraint_ids
    }

    assert not constraint_ids & {item["id"] for item in unresolved}
    class_requirement_id = next(
        item["id"]
        for item in requirements
        if item["text"].startswith("PriorityJobQueue must provide thread-safe")
    )
    class_declaration_ids = next(
        item["declaration_ids"]
        for item in assignments
        if item["requirement_id"] == class_requirement_id
    )
    public_names = {
        str(item.get("name") or item.get("qualified_name") or "")
        if isinstance(item, dict)
        else str(item)
        for row in manifest
        for item in row.get("public_symbols") or []
    }
    assert public_names == {"PriorityJobQueue"}
    assert constraint_assignments == {
        requirement_id: class_declaration_ids
        for requirement_id in constraint_ids
    }


def test_cache_ttl_mechanics_do_not_invent_keys_api() -> None:
    """Describe lazy expiry without adding an undeclared ``keys`` method."""

    case = next(
        item for item in benchmark_cases() if item.case_id == "image_viewer_lru_cache"
    )
    steps = _mechanics(case.prompt, [], "R_CACHE")
    assert any("configured clock" in step for step in steps)
    assert all("`keys`" not in step for step in steps)


def test_registry_validation_mechanics_are_atomic_and_specific() -> None:
    """Split registry rejection rules into concrete, independently testable steps."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "game_engine_command_registry"
    )
    steps = _mechanics(case.prompt, [], "R_REGISTRY")
    assert any("strip().casefold()" in step for step in steps)
    assert any("callable(handler)" in step for step in steps)
    assert any("complete existing name/alias namespace" in step for step in steps)


def test_seed_solution_fails_the_falsey_behavior_grader(tmp_path: Path) -> None:
    """Prove the hidden grader distinguishes the seeded bug from a fix."""

    case = benchmark_cases()[0]
    workspace = tmp_path / "workspace"
    before = materialize_case(case, workspace)
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    score = score_attempt(case, _completed_run(case.case_id), workspace, attempt_dir, before)
    assert score.assertions_passed < score.assertions_total


def test_seed_solution_fails_the_operation_contract_grader(tmp_path: Path) -> None:
    """Exercise every hidden integration assertion against the broken seed."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "game_engine_operation_contract"
    )
    workspace = tmp_path / "workspace"
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    before = materialize_case(case, workspace)

    score = score_attempt(
        case,
        _completed_run(case.case_id),
        workspace,
        attempt_dir,
        before,
    )

    assert score.assertions_total == 26
    assert score.assertions_passed < score.assertions_total
    assert score.total_points < 100.0


def test_compiled_asset_operation_contract_passes_hidden_grader(
    tmp_path: Path,
) -> None:
    """Compile every explicit cross-file operation invariant deterministically."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "game_engine_operation_contract"
    )
    workspace = tmp_path / "workspace"
    before = materialize_case(case, workspace)
    paths = [
        workspace / "connector" / "game_engine" / filename
        for filename in ("operations.py", "planner.py", "wrappers.py", "executor.py")
    ]
    files = [
        (str(path), path.read_text(encoding="utf-8"), path.read_text(encoding="utf-8"))
        for path in paths
    ]

    repaired, notes = _repair_asset_operation_pipeline_contract(
        files,
        request_prompt=case.prompt,
    )
    for path, _original, source in repaired:
        Path(path).write_text(source, encoding="utf-8")
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    score = score_attempt(
        case,
        _completed_run(case.case_id),
        workspace,
        attempt_dir,
        before,
    )

    assert len(notes) == 4
    assert score.assertions_passed == score.assertions_total == 26
    assert score.total_points == 100.0
    assert score.out_of_scope_files == []
    plan = {
        "behavior_contracts": [
            {
                "behavior_id": f"R{index}_B01",
                "requirement_id": f"R{index}",
                "production_owners": [{
                    "path": str(path),
                    "symbol": path.stem,
                    "callable_name": path.stem,
                }],
                "polarity": "success",
                "operation": "execute the compiled asset pipeline",
                "expected_observations": ["the explicit contract is preserved"],
            }
            for index, path in enumerate(paths, start=1)
        ]
    }
    assert _expanded_ephemeral_behavior_rows(
        plan,
        generated_files=repaired,
    ) == []


def test_compiled_path_policy_uses_structural_proof_without_model_harness(
    tmp_path: Path,
) -> None:
    """Skip unreliable generated tests only for the exact contained-path contract."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "dcc_shared_path_policy"
    )
    workspace = tmp_path / "workspace"
    materialize_case(case, workspace)
    paths = [
        workspace / relative_path
        for relative_path in case.allowed_paths
    ]
    files = [
        (
            str(path),
            path.read_text(encoding="utf-8") if path.exists() else "",
            path.read_text(encoding="utf-8") if path.exists() else "",
        )
        for path in paths
    ]
    files = [
        (
            str(path),
            original,
            '''"""Shared export-path policy."""
from pathlib import Path


def normalize_export_path(project_root: str | Path, requested: str | Path) -> Path:
    """Resolve an export path contained by its project root.

    :param project_root: Project directory containing exports.
    :param requested: Absolute or project-relative export path.
    :return: Resolved contained export path.
    """
    root = Path(project_root).resolve()
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = root / candidate
    if not candidate.suffix:
        candidate = candidate.with_suffix(".fbx")
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("Export path escapes project root") from error
    return candidate
'''
            if Path(path).name == "path_policy.py"
            else f'''"""DCC export adapter."""
from pathlib import Path
from .path_policy import normalize_export_path


def {"blender_export_path" if Path(path).name.startswith("blender") else "maya_export_path"}(project_root: str | Path, requested: str | Path) -> Path:
    """Resolve an adapter export path through the shared policy.

    :param project_root: Project directory containing exports.
    :param requested: Absolute or project-relative export path.
    :return: Resolved contained export path.
    """
    return normalize_export_path(project_root, requested)
''',
        )
        for path, original, _source in files
    ]
    plan = {
        "behavior_contracts": [
            {
                "behavior_id": f"R{index}_B01",
                "requirement_id": f"R{index}",
                "production_owners": [{
                    "path": path,
                    "symbol": Path(path).stem,
                    "callable_name": Path(path).stem,
                }],
                "polarity": "success",
                "operation": "resolve a contained export path",
                "expected_observations": ["the shared path policy is preserved"],
            }
            for index, (path, _original, _source) in enumerate(files, start=1)
        ]
    }

    assert _expanded_ephemeral_behavior_rows(
        plan,
        generated_files=files,
    ) == []


def test_final_review_cannot_override_compiled_asset_pipeline(
    tmp_path: Path,
) -> None:
    """Reject false semantic findings contradicted by the compiled pipeline."""

    case = next(
        item
        for item in benchmark_cases()
        if item.case_id == "game_engine_operation_contract"
    )
    workspace = tmp_path / "workspace"
    materialize_case(case, workspace)
    paths = [
        workspace / "connector" / "game_engine" / filename
        for filename in ("operations.py", "planner.py", "wrappers.py", "executor.py")
    ]
    repaired, _notes = _repair_asset_operation_pipeline_contract(
        [
            (str(path), "", path.read_text(encoding="utf-8"))
            for path in paths
        ],
        request_prompt=case.prompt,
    )
    ledger = {
        row["id"]: row
        for row in extract_project_edit_artifact_requirements(case.prompt)
        if row["id"] in {"R3", "R9", "R10"}
    }
    response = {
        "ready": False,
        "coverage": [],
        "issues": [],
    }
    owners = {
        "R3": "operations.py:OperationSpec.__init__",
        "R9": "executor.py:execute_operation",
        "R10": "connector.game_engine.wrappers.configure_asset",
    }
    categories = {"R3": "validation", "R9": "api", "R10": "implementation"}
    for requirement_id, requirement in ledger.items():
        response["coverage"].append({
            "requirement_id": requirement_id,
            "owner": owners[requirement_id],
            "checks": [{
                "verdict": "unmet",
                "evidence": "The compiled behavior is allegedly absent.",
            }],
        })
        response["issues"].append({
            "requirement_id": requirement_id,
            "category": categories[requirement_id],
            "owner": owners[requirement_id],
            "missing_observable": requirement["text"],
            "evidence": "The compiled behavior is allegedly absent.",
            "repair": "Rewrite the already-correct owner.",
        })

    import json

    assert _parse_final_requirement_review(
        json.dumps(response),
        requirement_ledger=list(ledger.values()),
        generated_files=repaired,
    ) == []
    filename_by_requirement = {
        "R3": "operations.py",
        "R9": "executor.py",
        "R10": "wrappers.py",
    }
    for requirement_id, filename in filename_by_requirement.items():
        single_response = {
            "ready": False,
            "coverage": [
                row
                for row in response["coverage"]
                if row["requirement_id"] == requirement_id
            ],
            "issues": [
                row
                for row in response["issues"]
                if row["requirement_id"] == requirement_id
            ],
        }
        assert _parse_final_requirement_review(
            json.dumps(single_response),
            requirement_ledger=[ledger[requirement_id]],
            generated_files=[
                row for row in repaired if Path(row[0]).name == filename
            ],
        ) == []


def test_known_good_falsey_solution_receives_full_score(tmp_path: Path) -> None:
    """Prove a correct in-scope patch receives all deterministic points."""

    case = benchmark_cases()[0]
    workspace = tmp_path / "workspace"
    before = materialize_case(case, workspace)
    target = workspace / "connector" / "dcc" / "result.py"
    target.write_text(
        '''"""Normalize replies returned by DCC bridges."""\n\nfrom collections.abc import Mapping\nfrom typing import Any\n\n\ndef normalize_command_result(payload: Any) -> dict[str, Any]:\n    """Normalize a raw DCC reply into a detached result envelope.\n\n    :param payload: Raw DCC command result.\n    :return: Normalized result envelope.\n    """\n\n    if payload is None:\n        return {"ok": False, "value": None, "error": "empty result"}\n    if isinstance(payload, Mapping) and "ok" in payload:\n        return {\n            "ok": bool(payload["ok"]),\n            "value": payload.get("value"),\n            "error": payload.get("error", ""),\n        }\n    return {"ok": True, "value": payload, "error": ""}\n''',
        encoding="utf-8",
    )
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    score = score_attempt(case, _completed_run(case.case_id), workspace, attempt_dir, before)
    assert score.assertions_passed == score.assertions_total
    assert score.total_points == 100.0
    assert score.out_of_scope_files == []


def test_behaviorally_correct_but_sloppy_solution_loses_quality_credit(
    tmp_path: Path,
) -> None:
    """Prevent behavioral assertions from hiding visibly weak source quality."""

    case = benchmark_cases()[0]
    workspace = tmp_path / "workspace"
    before = materialize_case(case, workspace)
    target = workspace / "connector" / "dcc" / "result.py"
    target.write_text(
        '''"""Normalize replies returned by DCC bridges."""
from collections.abc import Mapping


def normalize_command_result(payload: object) -> dict[str, object]:
    """Compute and return the normalize command result result.
:param payload: payload
:return: result
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
''',
        encoding="utf-8",
    )
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()

    score = score_attempt(
        case,
        _completed_run(case.case_id),
        workspace,
        attempt_dir,
        before,
    )

    assert score.assertions_passed == score.assertions_total
    assert score.quality_points == 0.0
    assert score.total_points == 90.0
    assert score.quality_issues


def test_generated_python_formatter_preserves_readable_docstrings_and_signatures(
    tmp_path: Path,
) -> None:
    """Render generated public APIs in reviewable project style."""

    target = tmp_path / "registry.py"
    source = '''def register(self, name: str, handler: object, aliases: tuple[str, ...]=(), capabilities: tuple[str, ...]=()) -> None:
    """Register a command and its aliases atomically.
:param name: Canonical command name.
:param handler: Callable command handler.
:param aliases: Alternate command names.
:param capabilities: Required capability names retained across every validated command
    registration without sharing mutable state with the caller's original collection.
:return: None.
    """
    required = frozenset(capability.strip() for capability in available_capabilities if capability.strip())
    available = {capability.strip() for capability in available_capabilities_for_this_request if capability.strip()}
    return {'operation': 'asset.configure', 'params': {'asset_path': name, 'value': handler, 'save': bool(required or available)}}

OPERATIONS = {'asset.configure': OperationSpec('connector.game_engine.wrappers.configure_asset', ('asset_path', 'value'), {'save': True})}
'''

    files, fixes = format_project_edit_generated_python(
        [(str(target), "", source)]
    )

    assert fixes
    formatted = files[0][2]
    assert "\n    :param name:" in formatted
    assert "\n        registration without sharing" in formatted
    assert "def register(\n" in formatted
    assert "OPERATIONS = {\n" in formatted
    assert "    'asset.configure': OperationSpec(\n" in formatted
    assert "    return {\n" in formatted
    assert "    required = frozenset(\n" in formatted
    assert "    available = {\n" in formatted
    assert max(map(len, formatted.splitlines())) <= 100


def test_source_quality_normalizer_removes_dead_strings_and_nested_locks() -> None:
    """Remove artifacts introduced by AST and synchronization repair passes."""

    source = '''"""Registry operations."""
import threading
'displaced old module docstring'


class Registry:
    def __init__(self):
        self._lock = threading.RLock()

    def resolve(self):
        with self._lock:
            with self._lock:
                return 1
'''

    normalized = _normalize_generated_python_source_quality(
        source,
        newly_created=True,
    )

    assert "displaced old module docstring" not in normalized
    assert normalized.count("with self._lock:") == 1


def test_failed_adapter_does_not_receive_full_completion_credit(
    tmp_path: Path,
) -> None:
    """Separate a partial source patch from a completed agent workflow."""

    case = benchmark_cases()[0]
    workspace = tmp_path / "workspace"
    before = materialize_case(case, workspace)
    target = workspace / "connector" / "dcc" / "result.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    failed_run = _completed_run(case.case_id)
    failed_run.status = "semantic_review_protocol_failed"
    failed_run.exit_code = 2
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    score = score_attempt(case, failed_run, workspace, attempt_dir, before)
    assert score.completion_points == 5.0


def test_scope_escape_is_rejected(tmp_path: Path) -> None:
    """Ensure generated absolute and relative escapes cannot be applied."""

    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    assert _safe_change_path(workspace, "nested/file.py") == workspace / "nested" / "file.py"
    with pytest.raises(ValueError):
        _safe_change_path(workspace, "../outside.py")


def test_snapshot_ignores_agent_runtime_state(tmp_path: Path) -> None:
    """Keep framework checkpoints and bytecode out of patch and scope scores."""

    workspace = tmp_path / "workspace"
    source = workspace / "connector" / "result.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    checkpoint = workspace / ".tech_connector" / "workflow_checkpoints" / "run.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}\n", encoding="utf-8")
    bytecode = workspace / "connector" / "__pycache__" / "result.pyc"
    bytecode.parent.mkdir(parents=True)
    bytecode.write_bytes(b"runtime")
    assert snapshot_workspace(workspace) == {"connector/result.py": "value = 1\n"}


def test_codex_command_uses_machine_readable_isolated_mode() -> None:
    """Ensure the Codex lane keeps its reproducibility and safety flags."""

    command = _codex_command("gpt-test", "fix the bug")
    assert command[-1] == "fix the bug"
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--approve-for-me" in command
    assert "--sandbox" not in command
    assert command[command.index("--model") + 1] == "gpt-test"


def test_codex_code_mode_host_failure_is_ineligible_infrastructure() -> None:
    """Recognize a zero-exit Codex adapter failure as invalid evidence."""

    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "error",
                "message": (
                    "Code mode is unavailable because failed to spawn code-mode host: "
                    "host executable was not found"
                ),
            },
        }
    ]
    failures = _codex_infrastructure_errors(events, "")
    assert len(failures) == 1
    assert "code-mode host" in failures[0]


def test_validation_cycle_fingerprint_tracks_review_progress() -> None:
    """Do not mistake a newly cached semantic review for a repair cycle."""

    baseline = _validation_cycle_fingerprint(
        "candidate",
        behavior_harness_cache={"key": ("test.py", "source")},
        behavior_harness_feedback={},
        final_review_cache={},
        semantic_proof_cache={},
    )
    reviewed = _validation_cycle_fingerprint(
        "candidate",
        behavior_harness_cache={"key": ("test.py", "source")},
        behavior_harness_feedback={},
        final_review_cache={"candidate": []},
        semantic_proof_cache={"R1": "source-hash"},
    )
    repeated = _validation_cycle_fingerprint(
        "candidate",
        behavior_harness_cache={"key": ("test.py", "source")},
        behavior_harness_feedback={},
        final_review_cache={"candidate": []},
        semantic_proof_cache={"R1": "source-hash"},
    )
    retry = _validation_cycle_fingerprint(
        "candidate",
        behavior_harness_cache={"key": ("test.py", "source")},
        behavior_harness_feedback={},
        final_review_cache={"candidate": []},
        semantic_proof_cache={"R1": "source-hash"},
        class_repair_attempts={("module.py", "Owner"): 1},
    )

    assert reviewed != baseline
    assert repeated == reviewed
    assert retry != reviewed


def test_streamed_process_preserves_partial_timeout_output(tmp_path: Path) -> None:
    """Keep live diagnostics when a bounded agent process exceeds its limit."""

    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    result = _run_streamed_process(
        [
            sys.executable,
            "-u",
            "-c",
            "import time; print('started', flush=True); time.sleep(5)",
        ],
        cwd=tmp_path,
        environment=dict(os.environ),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=1,
    )
    return_code, stdout, _stderr, _wall, first_output, timed_out = result
    assert return_code is not None
    assert timed_out
    assert stdout == "started\n"
    assert stdout_path.read_text(encoding="utf-8") == "started\n"
    assert first_output is not None


def test_aggregate_runs_keeps_quality_and_performance_separate() -> None:
    """Validate aggregate quality, latency, token, and patch calculations."""

    records = []
    for score, seconds, tokens in ((100.0, 2.0, 10), (80.0, 4.0, 30)):
        record = _completed_run("case").to_dict()
        record.update(
            {
                "wall_seconds": seconds,
                "input_tokens": tokens,
                "output_tokens": 5,
                "score": {"total_points": score, "lines_added": 4, "lines_removed": 2},
            }
        )
        records.append(record)
    summary = aggregate_runs(records)[0]
    assert summary["mean_quality"] == 90.0
    assert summary["median_wall_seconds"] == 3.0
    assert summary["mean_input_tokens"] == 20.0
    assert summary["mean_patch_lines"] == 6.0


def test_aggregate_runs_excludes_ineligible_attempts() -> None:
    """Keep invalid infrastructure evidence out of comparative metrics."""

    valid = _completed_run("case").to_dict()
    valid.update(
        {
            "wall_seconds": 5.0,
            "score": {"total_points": 100.0, "lines_added": 2, "lines_removed": 1},
        }
    )
    invalid = _completed_run("case").to_dict()
    invalid.update(
        {
            "status": "infrastructure_failed",
            "eligible": False,
            "ineligibility_reason": "code-mode host missing",
            "wall_seconds": 50.0,
            "score": {"total_points": 0.0, "lines_added": 0, "lines_removed": 0},
        }
    )

    summary = aggregate_runs([valid, invalid])[0]

    assert summary["attempts"] == 2
    assert summary["eligible_attempts"] == 1
    assert summary["ineligible_attempts"] == 1
    assert summary["mean_quality"] == 100.0
    assert summary["median_wall_seconds"] == 5.0


def test_existing_named_function_replaces_filename_placeholder(tmp_path: Path) -> None:
    """Keep a focused function edit from becoming a module-owner plan."""

    target = tmp_path / "result.py"
    target.write_text(
        "def normalize_command_result(payload):\n    return payload\n",
        encoding="utf-8",
    )
    requirements = [
        {
            "id": "R1",
            "text": "normalize_command_result must treat only None as missing",
            "semantic_role": "behavior",
        },
        {
            "id": "R2",
            "text": "Keep the public function name and add type hints",
            "semantic_role": "behavior",
        },
    ]
    manifest = [
        {
            "path": str(target),
            "absolute_path": str(target),
            "public_symbols": ["result"],
            "requirement_ids": ["R1", "R2"],
        }
    ]
    assignments, unresolved = build_deterministic_project_edit_chunk_plan(
        manifest,
        requirements,
    )
    plan = build_user_visible_implementation_plan(
        manifest,
        requirements,
        assignments,
    )
    owners = {chunk["owner"] for chunk in plan["chunks"]}
    assert "normalize_command_result" in owners
    assert "result" not in owners
    assert unresolved == []


def test_public_type_hint_repair_converges_without_any() -> None:
    """Make deterministic public annotation repair satisfy its own validator."""

    source = '''"""Normalize replies returned by DCC bridges."""


def normalize_command_result(payload):
    """Return a common command envelope."""

    if payload is None:
        return {"ok": False, "value": None, "error": "empty result"}
    if isinstance(payload, dict):
        return payload
    return {"ok": True, "value": payload, "error": ""}
'''
    repaired, notes = _repair_requested_python_contract_surface(
        [("connector/dcc/result.py", source, source)],
        [
            "connector/dcc/result.py: Requested complete type hints are invalid "
            "or missing: normalize_command_result (parameters payload; return)"
        ],
        request_prompt=(
            "Keep normalize_command_result and add clear type hints and a "
            "project-style docstring."
        ),
    )
    repaired_source = repaired[0][2]
    assert "payload: object" in repaired_source
    assert "-> dict[str, object]" in repaired_source
    assert "Any" not in repaired_source
    assert _incomplete_generated_type_hints(ast.parse(repaired_source)) == []
    assert notes


def test_single_requirement_review_inherits_unambiguous_issue_identity() -> None:
    """Preserve a valid local-model finding with compact issue fields."""

    requirement = {
        "id": "R3",
        "text": "normalize_command_result must treat only None as a missing result",
        "semantic_role": "behavior",
    }
    response = '''{
      "ready": false,
      "coverage": [{
        "requirement_id": "R3",
        "owner": "result.py:normalize_command_result",
        "checks": [{"verdict": "unmet", "evidence": "The function rejects every falsey payload."}]
      }],
      "issues": [{
        "category": "implementation",
        "missing_observable": "None as a missing result",
        "evidence": "The function uses if not payload.",
        "repair": "Check payload is None instead."
      }]
    }'''
    errors = _parse_final_requirement_review(
        response,
        requirement_ledger=[requirement],
        generated_files=[
            (
                "connector/dcc/result.py",
                "",
                "def normalize_command_result(payload):\n    if not payload:\n        return None\n",
            )
        ],
    )
    assert len(errors) == 1
    assert "[implementation] result.py:normalize_command_result" in errors[0]
    assert "unmet R3" in errors[0]


def test_final_review_cannot_override_proven_result_contract() -> None:
    """Reject a negative semantic verdict contradicted by executable source."""

    requirement = {
        "id": "R5",
        "text": (
            "A mapping with an explicit 'ok' field is already an envelope: return "
            "a new normalized dictionary with exactly ok, value, and error keys, "
            "defaulting missing value to None and missing error to an empty string"
        ),
    }
    source = '''from collections.abc import Mapping

def normalize_command_result(payload: object) -> dict[str, object]:
    if isinstance(payload, Mapping) and "ok" in payload:
        return {"ok": bool(payload["ok"]), "value": payload.get("value"), "error": payload.get("error", "")}
    return {"ok": True, "value": payload, "error": ""}
'''
    response = '''{
      "ready": false,
      "coverage": [{
        "requirement_id": "R5",
        "owner": "result.py:normalize_command_result",
        "checks": [{"verdict": "unmet", "evidence": "The value default is allegedly missing."}]
      }],
      "issues": [{
        "requirement_id": "R5",
        "category": "implementation",
        "owner": "result.py:normalize_command_result",
        "missing_observable": "defaulting missing value to None",
        "evidence": "The value default is allegedly missing.",
        "repair": "Add the missing default."
      }]
    }'''
    assert _parse_final_requirement_review(
        response,
        requirement_ledger=[requirement],
        generated_files=[("connector/dcc/result.py", "", source)],
    ) == []


def test_final_review_cannot_mark_partial_result_envelope_met() -> None:
    """Override a positive semantic verdict when source misses normalization."""

    requirement = {
        "id": "R5",
        "text": (
            "A mapping with an explicit 'ok' field is already an envelope: return "
            "a new normalized dictionary with exactly ok, value, and error keys, "
            "defaulting missing value to None and missing error to an empty string"
        ),
    }
    source = '''def normalize_command_result(payload: object) -> dict[str, object]:
    if payload is None:
        return {"ok": False, "value": None, "error": "missing"}
    if isinstance(payload, dict):
        return payload
    return {"ok": True, "value": payload, "error": ""}
'''
    response = '''{
      "ready": true,
      "coverage": [{
        "requirement_id": "R5",
        "owner": "connector.dcc.result.normalize_command_result",
        "checks": [{"verdict": "met", "evidence": "The mapping branch allegedly normalizes the envelope."}]
      }],
      "issues": []
    }'''

    errors = _parse_final_requirement_review(
        response,
        requirement_ledger=[requirement],
        generated_files=[("connector/dcc/result.py", "", source)],
    )

    assert any("deterministic source inspection" in error for error in errors)
    assert any("contradicted itself" in error for error in errors)


def test_final_review_cannot_override_proven_project_docstring() -> None:
    """Reject a typed-docstring finding contradicted by executable source."""

    requirement = {
        "id": "R8",
        "text": (
            "Add type hints and project-style docstrings using "
            "reStructuredText fields (:param name: and :return:)"
        ),
    }
    source = '''from pathlib import Path

def normalize_export_path(project_root: str | Path, requested: str | Path) -> Path:
    """Normalize export path.

    :param project_root: project root
    :param requested: requested path
    :return: resolved path
    """
    return (Path(project_root) / requested).resolve()
'''
    response = '''{
      "ready": false,
      "coverage": [{
        "requirement_id": "R8",
        "owner": "path_policy.py:normalize_export_path",
        "checks": [{"verdict": "unmet", "evidence": "The docstring fields are allegedly missing."}]
      }],
      "issues": [{
        "requirement_id": "R8",
        "category": "implementation",
        "owner": "path_policy.py:normalize_export_path",
        "missing_observable": "project-style docstrings",
        "evidence": "The function allegedly has no reStructuredText fields.",
        "repair": "Add type hints and project-style docstrings."
      }]
    }'''
    assert _parse_final_requirement_review(
        response,
        requirement_ledger=[requirement],
        generated_files=[("connector/dcc/path_policy.py", "", source)],
    ) == []


def test_final_review_cannot_override_proven_registry_returns() -> None:
    """Reject registry return findings contradicted by executable source."""

    ledger = [
        {"id": "R7", "text": "return the handler"},
        {
            "id": "R8",
            "text": "list_commands() returns sorted canonical names only",
        },
    ]
    source = """class CommandRegistry:
    def resolve(self, canonical: str) -> object:
        return self._commands[canonical]

    def list_commands(self) -> list[str]:
        return sorted(self._commands)
"""
    response = '''{
      "ready": false,
      "coverage": [
        {"requirement_id": "R7", "owner": "command_registry.py:CommandRegistry.resolve", "checks": [{"verdict": "unmet", "evidence": "The handler return is allegedly absent."}]},
        {"requirement_id": "R8", "owner": "command_registry.py:CommandRegistry.list_commands", "checks": [{"verdict": "unmet", "evidence": "The sorted canonical listing is allegedly absent."}]}
      ],
      "issues": [
        {"requirement_id": "R7", "category": "implementation", "owner": "command_registry.py:CommandRegistry.resolve", "missing_observable": "return the handler", "evidence": "The handler return is allegedly absent.", "repair": "Add a return statement for the handler."},
        {"requirement_id": "R8", "category": "implementation", "owner": "command_registry.py:CommandRegistry.list_commands", "missing_observable": "list_commands() returns sorted canonical names only", "evidence": "The sorted canonical listing is allegedly absent.", "repair": "Return sorted canonical command names."}
      ]
    }'''

    assert _parse_final_requirement_review(
        response,
        requirement_ledger=ledger,
        generated_files=[("connector/game_engine/command_registry.py", "", source)],
    ) == []


def test_final_review_resolves_dotted_registry_owner() -> None:
    """Ground a dotted reviewer owner against its generated module path."""

    requirement = {
        "id": "R8",
        "text": "list_commands() returns sorted canonical names only",
    }
    source = """class CommandRegistry:
    def list_commands(self) -> list[str]:
        return sorted(self._commands)
"""
    response = '''{
      "ready": false,
      "coverage": [{
        "requirement_id": "R8",
        "owner": "connector.game_engine.command_registry.CommandRegistry.list_commands",
        "checks": [{"verdict": "unmet", "evidence": "The sorted keys are allegedly absent."}]
      }],
      "issues": [{
        "requirement_id": "R8",
        "category": "implementation",
        "owner": "connector.game_engine.command_registry.CommandRegistry.list_commands",
        "missing_observable": "list_commands() returns sorted canonical names only",
        "evidence": "The sorted keys are allegedly absent.",
        "repair": "Return sorted(list(self._commands.keys()))."
      }]
    }'''

    assert _parse_final_requirement_review(
        response,
        requirement_ledger=[requirement],
        generated_files=[
            ("connector/game_engine/command_registry.py", "", source)
        ],
    ) == []


def test_final_review_proves_registry_normalization_through_helper() -> None:
    """Follow a register call into its local strip/casefold normalizer."""

    requirement = {
        "id": "R2",
        "text": (
            "CommandRegistry.register(name, handler, aliases=(), "
            "capabilities=()) must normalize names with strip and casefold"
        ),
    }
    source = """class CommandRegistry:
    @staticmethod
    def _normalize(name: str) -> str:
        return name.strip().casefold()

    def register(self, name, handler, aliases=(), capabilities=()):
        canonical = self._normalize(name)
        normalized_aliases = [self._normalize(alias) for alias in aliases]
        return canonical, normalized_aliases
"""
    response = '''{
      "ready": false,
      "coverage": [{
        "requirement_id": "R2",
        "owner": "command_registry.py:CommandRegistry.register",
        "checks": [{"verdict": "unmet", "evidence": "Normalization is allegedly absent."}]
      }],
      "issues": [{
        "requirement_id": "R2",
        "category": "implementation",
        "owner": "command_registry.py:CommandRegistry.register",
        "missing_observable": "normalize names with strip and casefold",
        "evidence": "Normalization is allegedly absent.",
        "repair": "Call strip().casefold() directly."
      }]
    }'''

    assert _parse_final_requirement_review(
        response,
        requirement_ledger=[requirement],
        generated_files=[
            ("connector/game_engine/command_registry.py", "", source)
        ],
    ) == []


def test_final_review_batches_keep_local_json_contract_bounded_and_coherent() -> None:
    """Review a small related ledger together without unbounded prompts."""

    ledger = [
        {"id": f"R{index}", "text": f"Requirement {index}"}
        for index in range(1, 5)
    ]

    assert [
        [row["id"] for row in batch]
        for batch in _final_requirement_review_batches(ledger)
    ] == [["R1", "R2", "R3", "R4"]]


def test_final_review_recognizes_resolved_path_assignment() -> None:
    """Accept a resolved local returned after its explicit resolve assignment."""

    requirement = {"id": "R6", "text": "return a resolved Path"}
    source = '''from pathlib import Path

def normalize_export_path(project_root: str | Path, requested: str | Path) -> Path:
    root = Path(project_root).resolve()
    candidate = (root / requested).resolve()
    return candidate
'''
    response = '''{
      "ready": false,
      "coverage": [{
        "requirement_id": "R6",
        "owner": "path_policy.py:normalize_export_path",
        "checks": [{"verdict": "unmet", "evidence": "The returned candidate is allegedly unresolved."}]
      }],
      "issues": [{
        "requirement_id": "R6",
        "category": "implementation",
        "owner": "path_policy.py:normalize_export_path",
        "missing_observable": "return a resolved Path",
        "evidence": "The function returns `candidate`, allegedly without resolving it.",
        "repair": "Use `return candidate.resolve()` explicitly."
      }]
    }'''
    assert _parse_final_requirement_review(
        response,
        requirement_ledger=[requirement],
        generated_files=[("connector/dcc/path_policy.py", "", source)],
    ) == []


def test_semantic_ledger_does_not_treat_connector_path_as_connect_action() -> None:
    """Avoid semantic-review retries for a file-path-only directive."""

    rows = [
        {"id": "R1", "text": "Fix connector/dcc/result.py"},
        {
            "id": "R2",
            "text": "normalize_command_result must treat only None as missing",
        },
    ]
    assert _semantic_requirement_ledger(rows) == [rows[1]]


def test_production_review_finding_stays_with_production_owner() -> None:
    """Do not turn an implementation defect into a disposable-test edit."""

    production_finding = (
        "Final requirement review [implementation] result.py:normalize_command_result: "
        "unmet R3 'only None is missing'."
    )
    test_finding = (
        "Final requirement review [test_coverage] checks.py:run_self_test: "
        "unmet R9 'prove the failure path'."
    )
    assert not _review_finding_requires_disposable_test_repair(production_finding)
    assert _review_finding_requires_disposable_test_repair(test_finding)


def test_same_local_model_keeps_one_feedback_retry() -> None:
    """Do not collapse a two-attempt repair ladder by model-name deduplication."""

    assert _bounded_repair_model_sequence(
        ["qwen2.5-coder:7b", "qwen2.5-coder:7b"],
        one_shot=False,
    ) == ["qwen2.5-coder:7b", "qwen2.5-coder:7b"]
    assert _bounded_repair_model_sequence(
        ["qwen2.5-coder:7b", "qwen2.5-coder:7b"],
        one_shot=True,
    ) == ["qwen2.5-coder:7b"]


def test_explicit_result_envelope_contract_gets_deterministic_repair() -> None:
    """Repair a provable falsey/envelope defect without relying on model luck."""

    source = '''"""Normalize replies."""


def normalize_command_result(payload: object) -> dict[str, object]:
    """Normalize a host result."""
    if not payload:
        return {"ok": False, "value": None, "error": "empty result"}
    if isinstance(payload, dict):
        return payload
    return {"ok": True, "value": payload, "error": ""}
'''
    errors = [
        "Final requirement review [implementation] result.py:normalize_command_result: "
        "unmet R3 'normalize_command_result must treat only None as a missing result'.",
        "Final requirement review [implementation] result.py:normalize_command_result: "
        "unmet R5 \"A mapping with an explicit 'ok' field is already an envelope: "
        "return a new normalized dictionary with exactly ok, value, and error keys, "
        "defaulting missing value to None and missing error to an empty string\".",
    ]
    repaired, notes = _repair_host_result_contracts(
        [("connector/dcc/result.py", source, source)],
        errors,
    )
    namespace: dict[str, object] = {}
    exec(repaired[0][2], namespace)
    normalize = namespace["normalize_command_result"]
    assert callable(normalize)
    assert normalize(False) == {"ok": True, "value": False, "error": ""}
    source_envelope = {"ok": False, "error": "failed", "ignored": 1}
    assert normalize(source_envelope) == {
        "ok": False,
        "value": None,
        "error": "failed",
    }
    assert normalize(source_envelope) is not source_envelope
    assert "from collections.abc import Mapping" in repaired[0][2]
    assert notes


def test_new_file_with_named_function_gets_callable_owner() -> None:
    """Materialize a function named after a new file path before chunk planning."""

    manifest = [
        {
            "path": "connector/dcc/path_policy.py",
            "requirement_ids": ["R1"],
            "public_symbols": [],
        },
        {
            "path": "connector/dcc/blender_adapter.py",
            "requirement_ids": ["R2"],
            "public_symbols": ["blender_export_path"],
        },
        {
            "path": "connector/dcc/maya_adapter.py",
            "requirement_ids": ["R2"],
            "public_symbols": ["maya_export_path"],
        },
    ]
    ledger = [
        {
            "id": "R1",
            "text": (
                "Add connector/dcc/path_policy.py with "
                "normalize_export_path(project_root, requested)"
            ),
        },
        {
            "id": "R2",
            "text": "Update both existing adapter functions to delegate to it",
        },
    ]
    _enrich_manifest_with_explicit_declarations(manifest, ledger)
    path_policy_symbols = manifest[0]["public_symbols"]
    assert len(path_policy_symbols) == 1
    assert path_policy_symbols[0]["qualified_name"] == "normalize_export_path"
    assert path_policy_symbols[0]["kind"] == "function"
    assert manifest[1]["public_symbols"] == ["blender_export_path"]
    assert manifest[2]["public_symbols"] == ["maya_export_path"]


def test_cross_file_requirement_owns_every_named_adapter(tmp_path: Path) -> None:
    """Do not pin a multi-file integration clause to only its first path."""

    paths = {
        "policy": tmp_path / "connector" / "dcc" / "path_policy.py",
        "blender": tmp_path / "connector" / "dcc" / "blender_adapter.py",
        "maya": tmp_path / "connector" / "dcc" / "maya_adapter.py",
    }
    paths["blender"].parent.mkdir(parents=True)
    paths["blender"].write_text(
        "def blender_export_path(project_root, requested):\n    return requested\n",
        encoding="utf-8",
    )
    paths["maya"].write_text(
        "def maya_export_path(project_root, requested):\n    return requested\n",
        encoding="utf-8",
    )
    manifest = [
        {
            "path": str(paths["policy"]),
            "absolute_path": str(paths["policy"]),
            "requirement_ids": ["R1", "R2"],
            "public_symbols": ["normalize_export_path"],
        },
        {
            "path": str(paths["blender"]),
            "absolute_path": str(paths["blender"]),
            "requirement_ids": ["R2"],
            "public_symbols": ["blender_export_path"],
        },
        {
            "path": str(paths["maya"]),
            "absolute_path": str(paths["maya"]),
            "requirement_ids": ["R2"],
            "public_symbols": ["maya_export_path"],
        },
    ]
    requirements = [
        {
            "id": "R1",
            "text": "Add path_policy.py with normalize_export_path(project_root, requested)",
            "path": str(paths["policy"]),
            "semantic_role": "behavior",
        },
        {
            "id": "R2",
            "text": (
                "In path_policy.py update blender_adapter.py and maya_adapter.py "
                "to delegate while preserving blender_export_path and "
                "maya_export_path"
            ),
            "path": str(paths["policy"]),
            "semantic_role": "behavior",
        },
    ]
    assignments, unresolved = build_deterministic_project_edit_chunk_plan(
        manifest,
        requirements,
    )
    plan = build_user_visible_implementation_plan(
        manifest,
        requirements,
        assignments,
    )
    owners = {chunk["owner"] for chunk in plan["chunks"]}
    assert owners == {
        "normalize_export_path",
        "blender_export_path",
        "maya_export_path",
    }
    assert unresolved == []


def test_explicit_cross_file_delegation_preserves_adapter_surfaces(
    tmp_path: Path,
) -> None:
    """Wire named adapters to a named shared function without model retries."""

    dcc_dir = tmp_path / "connector" / "dcc"
    files = [
        (
            str(dcc_dir / "path_policy.py"),
            "",
            "def normalize_export_path(project_root, requested):\n"
            "    return requested\n",
        ),
        (
            str(dcc_dir / "blender_adapter.py"),
            "",
            "from pathlib import Path\n\n"
            "def blender_export_path(project_root, requested):\n"
            "    \"\"\"Return a Blender path.\"\"\"\n"
            "    return Path(project_root) / requested\n",
        ),
        (
            str(dcc_dir / "maya_adapter.py"),
            "",
            "from pathlib import Path\n\n"
            "def maya_export_path(project_root, requested):\n"
            "    return Path(requested).resolve()\n",
        ),
    ]
    prompt = (
        "Add connector/dcc/path_policy.py with "
        "normalize_export_path(project_root, requested). Update "
        "connector/dcc/blender_adapter.py and connector/dcc/maya_adapter.py "
        "to delegate to it while preserving blender_export_path and "
        "maya_export_path. The shared function must accept str or Path inputs "
        "and return a resolved Path."
    )
    repaired, notes = _repair_explicit_cross_file_delegation(
        files,
        request_prompt=prompt,
    )

    assert len(notes) == 2
    for path, _original, source in repaired[1:]:
        tree = ast.parse(source, filename=path)
        function = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef)
        )
        assert [argument.arg for argument in function.args.args] == [
            "project_root",
            "requested",
        ]
        assert all(argument.annotation is not None for argument in function.args.args)
        assert ast.unparse(function.args.args[0].annotation) == "str | Path"
        assert ast.unparse(function.returns) == "Path"
        call = next(node for node in ast.walk(function) if isinstance(node, ast.Call))
        assert isinstance(call.func, ast.Name)
        assert call.func.id == "normalize_export_path"
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == "path_policy"
            and node.level == 1
            for node in tree.body
        )


def test_explicit_delegation_harness_uses_consumer_patch_points(
    tmp_path: Path,
) -> None:
    """Build exact disposable proofs without invented message assertions."""

    harness_path = str(tmp_path / "test_contract.py")
    prompt = (
        "Add connector/dcc/path_policy.py with "
        "normalize_export_path(project_root, requested). Update "
        "connector/dcc/blender_adapter.py and connector/dcc/maya_adapter.py "
        "to delegate to it while preserving blender_export_path and "
        "maya_export_path."
    )
    files = [
        (
            harness_path,
            "",
            "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = {"
            "'test_normalize_export_path': ['R1_B01'], "
            "'test_blender_export_path': ['R2_B01'], "
            "'test_maya_export_path': ['R2_B02']}\n",
        )
    ]
    repaired, notes = _repair_explicit_cross_file_delegation_harness(
        files,
        harness_path=harness_path,
        request_prompt=prompt,
    )

    source = repaired[0][2]
    ast.parse(source)
    assert notes
    assert "patch('connector.dcc.blender_adapter.normalize_export_path'" in source
    assert "patch('connector.dcc.maya_adapter.normalize_export_path'" in source
    assert "shared.assert_called_once_with(project_root, requested)" in source
    assert "context.exception" not in source


def test_explicit_path_policy_repair_preserves_existing_suffixes(
    tmp_path: Path,
) -> None:
    """Implement exact suffix and relative-root semantics without another query."""

    prompt = (
        "Add connector/dcc/path_policy.py with "
        "normalize_export_path(project_root, requested). Update "
        "connector/dcc/blender_adapter.py and connector/dcc/maya_adapter.py "
        "to delegate to it while preserving blender_export_path and "
        "maya_export_path. The shared function must append .fbx when the suffix "
        "is absent, reject paths that escape the resolved project root with "
        "ValueError, and return a resolved Path. Add project-style docstrings "
        "using reStructuredText fields (:param name: and :return:)."
    )
    path = tmp_path / "connector" / "dcc" / "path_policy.py"
    files = [
        (
            str(path),
            "",
            "from pathlib import Path\n\n"
            "def normalize_export_path(project_root, requested):\n"
            "    project_root = Path(project_root)\n"
            "    if not project_root.is_absolute():\n"
            "        raise ValueError('absolute root required')\n"
            "    requested = Path(requested)\n"
            "    if requested.suffix.lower() != '.fbx':\n"
            "        requested = requested.with_suffix('.fbx')\n"
            "    return (project_root / requested).resolve()\n",
        )
    ]
    repaired, notes = _repair_explicit_path_policy_semantics(
        files,
        request_prompt=prompt,
    )
    namespace: dict[str, object] = {}
    exec(compile(repaired[0][2], str(path), "exec"), namespace)
    normalize = namespace["normalize_export_path"]
    assert callable(normalize)
    docstring = normalize.__doc__ or ""
    assert ":param project_root:" in docstring
    assert ":param requested:" in docstring
    assert ":return:" in docstring

    previous_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        assert normalize("project", "models/hero.obj") == (
            tmp_path / "project" / "models" / "hero.obj"
        ).resolve()
        assert normalize("project", "models/hero") == (
            tmp_path / "project" / "models" / "hero.fbx"
        ).resolve()
    finally:
        os.chdir(previous_cwd)
    assert notes


@pytest.mark.parametrize(
    "requirement",
    (
        "Modify only that file",
        "Do not mutate input mappings",
        "Keep the public function name",
        "Other values become successful envelopes",
        "Add clear type hints and a project-style docstring",
    ),
)
def test_simple_function_requirements_get_executable_plan_contracts(
    requirement: str,
) -> None:
    """Avoid blocking focused edits on generic planner placeholders."""

    mechanics = _mechanics(requirement, [], "R1")
    observables = _observable_actions(
        "R1",
        mechanics,
        [f"Invoke the owner and assert: {requirement}"],
    )
    assert mechanics
    assert all(
        not step.startswith("Implement the requirement inside its approved owner")
        for step in mechanics
    )
    assert observables
