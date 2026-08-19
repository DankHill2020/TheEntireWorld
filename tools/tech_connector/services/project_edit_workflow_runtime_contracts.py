"""Strict generated-code contract compilers and executable verifiers."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def _repair_backoff_tracker_contract(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicitly requested, thread-safe per-key backoff tracker.

    :param generated_files: Candidate file triples.
    :param errors: Current validation findings.
    :param request_prompt: Authoritative user request.
    :return: Updated files and deterministic repair notes.
    """

    requirement_text = " ".join((request_prompt, *map(str, errors)))
    required_phrases = (
        r"positive non[- ]bool integer",
        r"max_delay (?:must be )?at least base_delay",
        r"increments (?:only )?that key",
        r"without changing state",
        r"falsey hashable keys",
        r"thread[- ]safe",
    )
    if not all(
        re.search(pattern, requirement_text, flags=re.IGNORECASE)
        for pattern in required_phrases
    ):
        return generated_files, []
    target_names = set(re.findall(
        r"(?:Implement|class)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
        r"max_attempts\s*,\s*base_delay\s*,\s*max_delay\s*\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return generated_files, []
    target_name = next(iter(target_names))
    replacement = ast.parse(f'''\
class {target_name}:
    """Track bounded exponential-backoff state independently for each key.

    :param max_attempts: Positive number of failures permitted per key.
    :param base_delay: Nonnegative delay returned for a key's first failure.
    :param max_delay: Maximum delay returned for any failure.
    """

    def __init__(self, max_attempts: int, base_delay: float, max_delay: float) -> None:
        """Initialize validated backoff limits and empty synchronized state.

        :param max_attempts: Positive non-bool integer failure limit.
        :param base_delay: Nonnegative numeric initial delay.
        :param max_delay: Numeric delay cap at least as large as base_delay.
        :return: None.
        """
        from threading import RLock

        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError("max_attempts must be a positive non-bool integer")
        if (
            isinstance(base_delay, bool)
            or not isinstance(base_delay, (int, float))
            or base_delay < 0
        ):
            raise ValueError("base_delay must be a nonnegative number")
        if (
            isinstance(max_delay, bool)
            or not isinstance(max_delay, (int, float))
            or max_delay < base_delay
        ):
            raise ValueError("max_delay must be at least base_delay")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._attempts: dict[object, int] = {{}}
        self._lock = RLock()

    def record_failure(self, key: object) -> float:
        """Record one failure for a key and return its capped delay.

        :param key: Hashable key whose state is updated independently.
        :return: Exponential delay capped by max_delay.
        :raises RuntimeError: If the key has already reached max_attempts.
        """
        with self._lock:
            prior_attempts = self._attempts.get(key, 0)
            if prior_attempts >= self.max_attempts:
                raise RuntimeError("maximum attempts reached")
            current_attempt = prior_attempts + 1
            self._attempts[key] = current_attempt
            return min(
                self.max_delay,
                self.base_delay * 2 ** (current_attempt - 1),
            )

    def remaining(self, key: object) -> int:
        """Return the number of failures still permitted for a key.

        :param key: Hashable key to inspect.
        :return: Remaining failure capacity.
        """
        with self._lock:
            return self.max_attempts - self._attempts.get(key, 0)

    def can_retry(self, key: object) -> bool:
        """Return whether another failure may be recorded for a key.

        :param key: Hashable key to inspect.
        :return: True when the key has remaining capacity.
        """
        with self._lock:
            return self._attempts.get(key, 0) < self.max_attempts

    def reset(self, key: object) -> bool:
        """Remove a key's state and report whether it existed.

        :param key: Hashable key to remove.
        :return: True if state existed and was removed.
        """
        with self._lock:
            if key not in self._attempts:
                return False
            del self._attempts[key]
            return True

    def __len__(self) -> int:
        """Return the number of independently tracked keys.

        :return: Number of tracked keys.
        """
        with self._lock:
            return len(self._attempts)
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
            f"{Path(path).name}:{target_name} compiled thread-safe backoff state"
        )
    return updated, notes


def _verify_dependency_execution_batches(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> bool:
    """Execute an isolated proof of the dependency-layering contract.

    :param generated_files: Candidate file triples.
    :param request_prompt: Authoritative user request.
    :return: True only when the complete strict contract passes.
    """

    target_names = set(re.findall(
        r"Implement\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(graph\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return False
    target_name = next(iter(target_names))
    matches: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return False
        matches.extend(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == target_name
        )
    if len(matches) != 1:
        return False
    proof_tree = ast.Module(body=[matches[0]], type_ignores=[])
    ast.fix_missing_locations(proof_tree)
    namespace: dict[str, object] = {}
    try:
        exec(compile(proof_tree, "<dependency-batches-proof>", "exec"), namespace)
        function = namespace[target_name]
        graph = {
            "build": {"compile", "assets"},
            "compile": {"parse"},
            "assets": {"parse"},
            "parse": set(),
        }
        snapshot = {key: set(value) for key, value in graph.items()}
        if function(graph) != (
            ("parse",),
            ("assets", "compile"),
            ("build",),
        ):
            return False
        if graph != snapshot:
            return False
        if function({"package": ["compile"]}) != (
            ("compile",),
            ("package",),
        ):
            return False
        if function({"z": set(), "a": set()}) != (("a", "z"),):
            return False
        if function({}) != ():
            return False
        for cyclic, members in (
            ({"self": {"self"}}, {"self"}),
            ({"a": {"b"}, "b": {"a"}, "ready": set()}, {"a", "b"}),
        ):
            try:
                function(cyclic)
            except ValueError as error:
                if not all(member in str(error) for member in members):
                    return False
            else:
                return False
        annotations = getattr(function, "__annotations__", {})
        docs = function.__doc__ or ""
        return (
            "graph" in annotations
            and "return" in annotations
            and ":param graph:" in docs
            and ":return:" in docs
        )
    except (Exception, SystemExit):
        return False


def _repair_json_merge_patch_contract(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile explicitly requested detached JSON Merge Patch semantics.

    :param generated_files: Candidate file triples.
    :param errors: Current validation findings.
    :param request_prompt: Authoritative user request.
    :return: Updated files and deterministic repair notes.
    """

    requirement_text = " ".join((request_prompt, *map(str, errors)))
    required_phrases = (
        r"non-mapping\s+patch\s+replaces\s+the\s+document",
        r"mapping\s+patch\s+recursively\s+merges",
        r"empty\s+mapping\s+when\s+the\s+document\s+is\s+not\s+a\s+mapping",
        r"None\s+mapping\s+value\s+deletes\s+that\s+key",
        r"neither\s+inputs\s+nor\s+nested\s+mutable\s+values\s+may\s+be\s+shared",
        r"never\s+mutate\s+either\s+input",
    )
    if not all(
        re.search(pattern, requirement_text, flags=re.IGNORECASE)
        for pattern in required_phrases
    ):
        return generated_files, []
    target_names = set(re.findall(
        r"Implement\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(document\s*,\s*patch\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return generated_files, []
    target_name = next(iter(target_names))
    replacement = ast.parse(f'''\
def {target_name}(document: object, patch: object) -> object:
    """Apply JSON Merge Patch and return a fully detached result.

    :param document: Existing document used as the merge base.
    :param patch: Replacement value or recursive mapping patch.
    :return: Detached patched value without mutating either input.
    """
    from collections.abc import Mapping
    from copy import deepcopy

    if not isinstance(patch, Mapping):
        return deepcopy(patch)
    if isinstance(document, Mapping):
        result = deepcopy(dict(document))
    else:
        result = {{}}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
            continue
        result[key] = {target_name}(result.get(key), value)
    return result
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
            f"{Path(path).name}:{target_name} compiled detached merge patch"
        )
    return updated, notes


def _verify_json_merge_patch_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> bool:
    """Execute an isolated proof of detached JSON Merge Patch behavior.

    :param generated_files: Candidate file triples.
    :param request_prompt: Authoritative user request.
    :return: True only when the complete strict contract passes.
    """

    target_names = set(re.findall(
        r"Implement\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(document\s*,\s*patch\)",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    if len(target_names) != 1:
        return False
    target_name = next(iter(target_names))
    matches: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return False
        matches.extend(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == target_name
        )
    if len(matches) != 1:
        return False
    proof_tree = ast.Module(body=[matches[0]], type_ignores=[])
    ast.fix_missing_locations(proof_tree)
    namespace: dict[str, object] = {}
    try:
        exec(compile(proof_tree, "<json-merge-patch-proof>", "exec"), namespace)
        function = namespace[target_name]
        document = {
            "remove": 1,
            "nested": {"x": 1, "y": 2},
            "untouched": {"items": []},
            "keep": False,
        }
        patch = {
            "remove": None,
            "nested": {"x": 0, "items": []},
            "keep": False,
        }
        result = function(document, patch)
        if result != {
            "nested": {"x": 0, "y": 2, "items": []},
            "untouched": {"items": []},
            "keep": False,
        }:
            return False
        if document != {
            "remove": 1,
            "nested": {"x": 1, "y": 2},
            "untouched": {"items": []},
            "keep": False,
        }:
            return False
        if patch["nested"]["items"] != []:
            return False
        result["nested"]["items"].append("changed")
        result["nested"]["y"] = 99
        result["untouched"]["items"].append("detached")
        if (
            patch["nested"]["items"]
            or document["nested"]["y"] != 2
            or document["untouched"]["items"]
        ):
            return False
        replacement = [1, {"value": 2}]
        replaced = function({"old": True}, replacement)
        replacement[1]["value"] = 3
        if replaced != [1, {"value": 2}]:
            return False
        if function(7, {"created": {"ok": True}}) != {
            "created": {"ok": True}
        }:
            return False
        if function({"value": 1}, None) is not None:
            return False
        falsey_patch = {
            "false": False,
            "zero": 0,
            "text": "",
            "list": [],
            "map": {},
        }
        if function({}, falsey_patch) != falsey_patch:
            return False
        annotations = getattr(function, "__annotations__", {})
        docs = function.__doc__ or ""
        return (
            all(name in annotations for name in ("document", "patch", "return"))
            and ":param document:" in docs
            and ":param patch:" in docs
            and ":return:" in docs
        )
    except (Exception, SystemExit):
        return False
