"""Project-edit workflow phase: _run_attempt_prepare_phase."""

from __future__ import annotations
import sys
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import (
    _WorkflowReturn,
    _WorkflowBreak,
    _WorkflowContinue,
)


def _defer_union_annotations_for_legacy_python(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Keep generated typing references executable on the target Python."""

    class _LegacyUnionAnnotationNormalizer(_deps.ast.NodeTransformer):
        changed = False

        def _annotation(self, annotation: _deps.ast.AST | None) -> _deps.ast.AST | None:
            if annotation is None:
                return None

            class _UnionNormalizer(_deps.ast.NodeTransformer):
                def visit_BinOp(self, node: _deps.ast.BinOp) -> _deps.ast.AST:
                    if not isinstance(node.op, _deps.ast.BitOr):
                        return self.generic_visit(node)
                    parts: list[_deps.ast.AST] = []

                    def collect(part: _deps.ast.AST) -> None:
                        if isinstance(part, _deps.ast.BinOp) and isinstance(part.op, _deps.ast.BitOr):
                            collect(part.left)
                            collect(part.right)
                        else:
                            parts.append(self.visit(part))

                    collect(node)
                    normalizer.changed = True
                    return _deps.ast.copy_location(
                        _deps.ast.Subscript(
                            value=_deps.ast.Attribute(
                                value=_deps.ast.Name(id="typing", ctx=_deps.ast.Load()),
                                attr="Union",
                                ctx=_deps.ast.Load(),
                            ),
                            slice=_deps.ast.Tuple(elts=parts, ctx=_deps.ast.Load()),
                            ctx=_deps.ast.Load(),
                        ),
                        node,
                    )

            normalizer = self
            return _UnionNormalizer().visit(annotation)

        def visit_arg(self, node: _deps.ast.arg) -> _deps.ast.arg:
            node.annotation = self._annotation(node.annotation)
            return node

        def visit_AnnAssign(self, node: _deps.ast.AnnAssign) -> _deps.ast.AnnAssign:
            node.annotation = self._annotation(node.annotation)
            return node

        def visit_FunctionDef(self, node: _deps.ast.FunctionDef) -> _deps.ast.FunctionDef:
            node.returns = self._annotation(node.returns)
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: _deps.ast.AsyncFunctionDef) -> _deps.ast.AsyncFunctionDef:
            node.returns = self._annotation(node.returns)
            return self.generic_visit(node)

    updated: list[tuple[str, str, str]] = []
    repaired_paths: list[str] = []
    for path, original, source in generated_files:
        try:
            tree = _deps.ast.parse(source, filename=path)
        except SyntaxError:
            updated.append((path, original, source))
            continue
        normalizer = _LegacyUnionAnnotationNormalizer()
        if sys.version_info < (3, 10):
            tree = normalizer.visit(tree)
        has_typing_binding = any(
            (
                isinstance(node, _deps.ast.Import)
                and any(
                    (alias.asname or alias.name.split(".", 1)[0]) == "typing"
                    for alias in node.names
                )
            ) or (
                isinstance(node, _deps.ast.ImportFrom)
                and any((alias.asname or alias.name) == "typing" for alias in node.names)
            ) or (
                isinstance(node, (_deps.ast.FunctionDef, _deps.ast.ClassDef))
                and node.name == "typing"
            ) or (
                isinstance(node, (_deps.ast.Assign, _deps.ast.AnnAssign))
                and any(
                    isinstance(target, _deps.ast.Name) and target.id == "typing"
                    for target in (node.targets if isinstance(node, _deps.ast.Assign) else [node.target])
                )
            )
            for node in tree.body
        )
        needs_typing_import = not has_typing_binding and any(
            isinstance(node, _deps.ast.Attribute)
            and isinstance(node.value, _deps.ast.Name)
            and node.value.id == "typing"
            for node in _deps.ast.walk(tree)
        )
        if not normalizer.changed and not needs_typing_import:
            updated.append((path, original, source))
            continue
        if needs_typing_import:
            insertion = 1 if (
                tree.body and isinstance(tree.body[0], _deps.ast.Expr)
                and isinstance(tree.body[0].value, _deps.ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ) else 0
            while insertion < len(tree.body) and isinstance(tree.body[insertion], _deps.ast.ImportFrom) and tree.body[insertion].module == "__future__":
                insertion += 1
            tree.body.insert(insertion, _deps.ast.Import(names=[_deps.ast.alias(name="typing")]))
        _deps.ast.fix_missing_locations(tree)
        repaired = _deps.ast.unparse(tree).rstrip() + "\n"
        compile(repaired, path, "exec")
        updated.append((path, original, repaired))
        repaired_paths.append(path)
    return updated, repaired_paths


def _behavior_harness_generation_model(
    settings: dict[str, _deps.Any], selected_model: str
) -> str:
    """Use an explicit local proof model only when local-only routing permits it."""

    cloud_selected = str(selected_model or "").lower().startswith(
        ("openai:", "anthropic:", "claude:", "google:", "gemini:", "x:", "grok:")
    )
    if str(settings.get("model_source_mode") or "") == "local_only" and cloud_selected:
        return _deps._small_owner_reasoning_model(settings, "")
    if str(settings.get("model_source_mode") or "") == "local_only":
        proof_model = str(settings.get("local_behavior_harness_model") or "").strip()
        if proof_model:
            return proof_model.removeprefix("ollama:")
    if selected_model:
        return selected_model.removeprefix("ollama:")
    return _deps._small_owner_reasoning_model(settings, selected_model)


def _is_disposable_harness_contract_error(error: str) -> bool:
    """Identify test-authoring defects that cannot justify production edits."""

    return any(
        marker in str(error)
        for marker in (
            "does not execute approved production owner",
            "Disposable behavior harness",
            "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__",
            "Generated callables reference undefined names in Test",
            "Generated callables reference undefined names in <module>",
            "Imported callable members do not exist",
            "Generated test methods are placeholders",
            "Generated test methods need stronger behavioral proof",
            "fixture variables never consumed",
            "executes no observable assertion",
        )
    )


def _retry_malformed_disposable_audit(
    attempt: int, errors: list[str]
) -> bool:
    """Spend one extra audit call only on invalid replacement syntax."""

    return attempt == 1 and any(
        "replacement did not parse" in str(issue) for issue in errors
    )


def _runtime_audit_proof_progress(before: list[str], after: list[str]) -> bool:
    """Reject equivalent or worse disposable repairs before another model pass."""

    return len(after) <= len(before) and sorted(map(str, after)) != sorted(map(str, before))


def _preflight_behavior_capsule(
    source: str,
    behavior_rows: list[dict[str, _deps.Any]],
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
    project_root: str | None = None,
) -> list[str]:
    """Reject faulty singleton tests before they contaminate a merged harness."""

    errors = _deps._ephemeral_harness_call_graph_errors(
        source, generated_files, request_prompt=request_prompt
    )
    errors.extend(
        _disposable_harness_invalid_imports(
            source, generated_files, project_root=project_root
        )
    )
    errors.extend(
        _deps._ephemeral_harness_behavior_contract_errors(
            source, behavior_rows, generated_files=generated_files,
            request_prompt=request_prompt,
        )
    )
    return list(dict.fromkeys(errors))


def _group_behavior_proof_batches(
    behavior_rows: list[dict[str, _deps.Any]],
    *,
    max_test_groups: int = 3,
) -> list[list[dict[str, _deps.Any]]]:
    """Batch exact-test groups without separating clauses sharing one test."""

    groups: dict[str, list[dict[str, _deps.Any]]] = {}
    for row in behavior_rows:
        groups.setdefault(str(row.get("test_name") or ""), []).append(row)
    grouped = list(groups.values())
    width = max(1, max_test_groups)
    return [
        [row for group in grouped[start : start + width] for row in group]
        for start in range(0, len(grouped), width)
    ]


def _salvage_behavior_proof_batch(
    response: str,
    behavior_rows: list[dict[str, _deps.Any]],
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
    project_root: str,
) -> tuple[list[str], list[list[dict[str, _deps.Any]]]]:
    """Keep independently valid proofs and retry only failed exact-test groups."""

    accepted: list[str] = []
    retry: list[list[dict[str, _deps.Any]]] = []
    groups = _group_behavior_proof_batches(behavior_rows, max_test_groups=1)
    for group in groups:
        behavior_ids = [str(row.get("behavior_id") or "") for row in group]
        test_names = [str(row.get("test_name") or "") for row in group]
        source, errors = _deps._parse_ephemeral_behavior_harness(
            response,
            behavior_ids,
            test_names,
            request_prompt=request_prompt,
        )
        if not errors:
            source, _ = _normalize_disposable_builtin_exception_imports(
                source, generated_files, project_root=project_root
            )
            source, _ = _deps._repair_ephemeral_literal_oracles(
                source, request_prompt, group
            )
            errors = _preflight_behavior_capsule(
                source,
                group,
                generated_files,
                request_prompt=request_prompt,
                project_root=project_root,
            )
        if errors or not source.strip():
            retry.append(group)
        else:
            accepted.append(source)
    return accepted, retry


def _single_behavior_repair_system_prompt(original: str, attempt: int) -> str:
    """Use a compact rescue prompt only after two detailed local retries fail."""

    if attempt < 3:
        return original
    return (
        "Write one complete Python unittest module for the single approved "
        "behavior contract in the user message. Include exactly its required "
        "test_name, import the real public callable, and execute that callable. "
        "Never patch the callable under test. Patch only actual external host "
        "dependencies if needed. Assert only the behavior explicitly requested "
        "for this clause; do not invent exception messages or extra rejection "
        "cases. Correct the listed validator error and return Python source only."
    )


def _single_behavior_fixture_guidance(errors: list[str]) -> str:
    """Give the small proof model concrete, contract-preserving fixture shapes."""

    message = " | ".join(errors)
    guidance: list[str] = []
    if "case-insensitive deduplication proof" in message:
        guidance.append(
            "For the deduplication clause, pass the owner a literal snapshot "
            "containing both {'name': 'Walk', 'enabled': True} and "
            "{'name': 'walk', 'enabled': True}; assert the first spelling "
            "survives. Both duplicate rows must explicitly be enabled."
        )
    if "unknown-or-disabled selection rejection" in message:
        guidance.append(
            "For the selection-rejection clause, use two separate "
            "with self.assertRaises(ValueError) blocks. In one, pass a "
            "valid snapshot containing {'name': 'Walk', 'enabled': False} "
            "and selected_names=['Walk']. In the other, pass a valid "
            "snapshot containing {'name': 'Walk', 'enabled': True} and "
            "selected_names=['Missing']. Pass those literal fixtures "
            "directly to the owner, with any other required arguments."
        )
    if "invents assertRaises behavior" in message:
        guidance.append(
            "This clause does not authorize a rejection case. Write the test "
            "body afresh using a valid input, call the real owner normally, "
            "and assert its approved return value or the input's unchanged "
            "state. Do not include any assertRaises or empty with block."
        )
    return "\n".join(guidance)


def _disposable_harness_invalid_imports(
    harness_source: str,
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str | None = None,
) -> list[str]:
    """Reject imports of class members that are not module exports."""

    try:
        harness_tree = _deps.ast.parse(harness_source)
    except SyntaxError:
        return []
    exports_by_stem: dict[str, list[set[str]]] = {}
    candidate_module_trees: dict[str, _deps.ast.Module] = {}
    for path, _original, source in generated_files:
        try:
            module_tree = _deps.ast.parse(source, filename=path)
        except SyntaxError:
            continue
        if project_root:
            try:
                module_name = ".".join(
                    _deps.Path(path).resolve()
                    .relative_to(_deps.Path(project_root).resolve())
                    .with_suffix("").parts
                )
            except (OSError, ValueError):
                module_name = ""
            if module_name:
                candidate_module_trees[module_name] = module_tree
        exports: set[str] = set()
        for node in module_tree.body:
            if isinstance(node, (_deps.ast.ClassDef, _deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef)):
                exports.add(node.name)
            elif isinstance(node, _deps.ast.Import):
                exports.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, _deps.ast.ImportFrom):
                exports.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, _deps.ast.Assign):
                exports.update(target.id for target in node.targets if isinstance(target, _deps.ast.Name))
            elif isinstance(node, _deps.ast.AnnAssign) and isinstance(node.target, _deps.ast.Name):
                exports.add(node.target.id)
        exports_by_stem.setdefault(_deps.Path(path).stem, []).append(exports)
    invalid: list[str] = []
    for node in harness_tree.body:
        if not isinstance(node, _deps.ast.ImportFrom) or not node.module:
            continue
        candidates = exports_by_stem.get(node.module.rsplit(".", 1)[-1], [])
        if len(candidates) != 1:
            continue
        invalid.extend(
            f"{node.module}.{alias.name}"
            for alias in node.names
            if alias.name != "*" and alias.name not in candidates[0]
        )
    if candidate_module_trees:
        module_aliases: dict[str, str] = {}
        for node in harness_tree.body:
            if isinstance(node, _deps.ast.Import):
                for alias in node.names:
                    if alias.asname:
                        module_aliases[alias.asname] = alias.name
                    else:
                        module_aliases[alias.name.split(".", 1)[0]] = alias.name.split(".", 1)[0]
            elif isinstance(node, _deps.ast.ImportFrom) and node.module:
                for alias in node.names:
                    module_aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

        class _ModuleCallVisitor(_deps.ast.NodeVisitor):
            def __init__(self) -> None:
                self.local_scopes: list[set[str]] = []

            def visit_FunctionDef(self, node: _deps.ast.FunctionDef) -> None:
                locals_here = {name.id for name in _deps.ast.walk(node) if isinstance(name, _deps.ast.Name) and isinstance(name.ctx, _deps.ast.Store)}
                locals_here.update(arg.arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs)
                if node.args.vararg:
                    locals_here.add(node.args.vararg.arg)
                if node.args.kwarg:
                    locals_here.add(node.args.kwarg.arg)
                self.local_scopes.append(locals_here)
                self.generic_visit(node)
                self.local_scopes.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node: _deps.ast.Call) -> None:
                parts: list[str] = []
                cursor = node.func
                while isinstance(cursor, _deps.ast.Attribute):
                    parts.append(cursor.attr)
                    cursor = cursor.value
                if isinstance(cursor, _deps.ast.Name):
                    root_name = cursor.id
                    if root_name in module_aliases and not any(root_name in scope for scope in self.local_scopes):
                        qualified = ".".join([module_aliases[root_name], *reversed(parts)])
                        for module_name, module_tree in candidate_module_trees.items():
                            if not qualified.startswith(module_name + "."):
                                continue
                            member = qualified[len(module_name) + 1:].split(".", 1)[0]
                            exports = exports_by_stem.get(module_name.rsplit(".", 1)[-1], [])
                            if len(exports) == 1 and member not in exports[0]:
                                invalid.append(f"{module_name}.{member}")
                            break
                self.generic_visit(node)

        _ModuleCallVisitor().visit(harness_tree)
    if not invalid:
        return []
    error = (
        "Disposable behavior harness imports nonexistent module-level member(s): "
        + ", ".join(sorted(set(invalid)))
    )
    builtin_names = sorted({
        name.rsplit(".", 1)[-1]
        for name in invalid
        if name.rsplit(".", 1)[-1] in {
            "ValueError", "TypeError", "KeyError", "RuntimeError", "AssertionError",
        }
    })
    if builtin_names:
        error += (
            ". " + ", ".join(builtin_names)
            + (" is a Python built-in exception; use it directly in the test "
               if len(builtin_names) == 1 else
               " are Python built-in exceptions; use them directly in the test ")
            + "instead of importing from the generated project module."
        )
    return [error]


def _normalize_disposable_builtin_exception_imports(
    harness_source: str,
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str,
) -> tuple[str, list[str]]:
    """Remove only invalid, unaliased built-in exception imports from tests.

    An exception imported from the generated module is left alone when that
    module actually exports it. The built-in remains available by name after
    removal. This never changes production source or a non-built-in import.
    """

    try:
        tree = _deps.ast.parse(harness_source)
    except SyntaxError:
        return harness_source, []
    exports_by_module: dict[str, set[str]] = {}
    for path, _original, source in generated_files:
        try:
            module_name = ".".join(
                _deps.Path(path).resolve()
                .relative_to(_deps.Path(project_root).resolve())
                .with_suffix("").parts
            )
        except (OSError, ValueError):
            continue
        try:
            module_tree = _deps.ast.parse(source, filename=path)
        except SyntaxError:
            continue
        exports = {
            node.name for node in module_tree.body
            if isinstance(node, (_deps.ast.ClassDef, _deps.ast.FunctionDef,
                                 _deps.ast.AsyncFunctionDef))
        }
        exports.update(
            target.id
            for node in module_tree.body
            if isinstance(node, _deps.ast.Assign)
            for target in node.targets
            if isinstance(target, _deps.ast.Name)
        )
        exports.update(
            alias.asname or alias.name for node in module_tree.body
            if isinstance(node, _deps.ast.ImportFrom) for alias in node.names
        )
        exports_by_module[module_name] = exports

    builtin_exceptions = {
        "ValueError", "TypeError", "KeyError", "RuntimeError", "AssertionError",
    }
    repairs: list[str] = []
    kept_body: list[_deps.ast.stmt] = []
    for node in tree.body:
        if not isinstance(node, _deps.ast.ImportFrom) or not node.module:
            kept_body.append(node)
            continue
        exports = exports_by_module.get(node.module)
        if exports is None:
            kept_body.append(node)
            continue
        retained = []
        for alias in node.names:
            if (
                alias.asname is None
                and alias.name in builtin_exceptions
                and alias.name not in exports
            ):
                repairs.append(f"{node.module}.{alias.name}")
            else:
                retained.append(alias)
        if retained:
            node.names = retained
            kept_body.append(node)
    if not repairs:
        return harness_source, []
    tree.body = kept_body
    return _deps.ast.unparse(_deps.ast.fix_missing_locations(tree)) + "\n", repairs


def _validation_cycle_fingerprint(
    candidate: str,
    *,
    behavior_harness_cache: dict[str, tuple[str, str]],
    behavior_harness_feedback: dict[str, str],
    final_review_cache: dict[str, list[str]],
    semantic_proof_cache: dict[str, str],
    class_repair_attempts: dict[tuple[str, str], int] | None = None,
    active_harness_source: str = "",
) -> str:
    """Fingerprint every validation state that can advance without a code change.

    :param candidate: complete multi-file candidate
    :param behavior_harness_cache: cached disposable harnesses
    :param behavior_harness_feedback: feedback used to rebuild harnesses
    :param final_review_cache: request-to-code review findings by candidate
    :param semantic_proof_cache: source hashes proven for requirements
    :param class_repair_attempts: bounded owner-repair strategy state
    :param active_harness_source: currently repaired disposable harness
    :return: stable validation-cycle fingerprint
    """

    return _deps._checkpoint_hash(
        {
            "candidate": _deps._candidate_checkpoint_fingerprint(candidate),
            "behavior_harnesses": sorted(
                _deps._checkpoint_hash(
                    {"cache_key": cache_key, "path": path, "source": source}
                )
                for cache_key, (path, source) in behavior_harness_cache.items()
            ),
            "behavior_harness_feedback": sorted(
                (
                    (str(cache_key), _deps._checkpoint_hash(str(feedback)))
                    for cache_key, feedback in behavior_harness_feedback.items()
                )
            ),
            "final_review": {
                "present": candidate in final_review_cache,
                "findings": list(final_review_cache.get(candidate) or []),
            },
        "semantic_proofs": sorted(
                (str(requirement_id), str(source_hash))
                for requirement_id, source_hash in semantic_proof_cache.items()
            ),
            "class_repair_attempts": sorted(
                (str(path), str(symbol), int(count))
                for (path, symbol), count in (class_repair_attempts or {}).items()
            ),
            "active_harness": _deps._checkpoint_hash(active_harness_source),
        }
    )


class _ProjectEditAttemptPreparePhase:
    """Provide the attempt prepare workflow phase."""

    def _run_attempt_prepare_phase(self) -> None:
        """Run the attempt prepare phase.

        :return: None.
        """
        self.validation_candidate_fingerprint = _validation_cycle_fingerprint(
            self.candidate,
            behavior_harness_cache=self.behavior_harness_cache,
            behavior_harness_feedback=self.behavior_harness_feedback,
            final_review_cache=self.final_review_cache,
            semantic_proof_cache=self.semantic_proof_cache,
            class_repair_attempts=self.class_repair_attempts,
            active_harness_source=getattr(self, "harness_source", ""),
        )
        if (
            self.validation_candidate_fingerprint
            in self.seen_validation_candidate_fingerprints
        ):
            self.generated_files = _deps._normalize_generated_files(
                self.generated_files,
                project_root=self.root,
                request_prompt=self.prompt,
            )
            self.candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            repeated_candidate_errors = _deps._repair_phase_validation_errors(
                self.generated_files,
                implementation_plan=self.implementation_plan,
                project_root=self.root,
                request_prompt=self.prompt,
                harness_path=getattr(self, "ephemeral_validation_path", ""),
            )
            if not repeated_candidate_errors:
                if self.status_callback:
                    self.status_callback(
                        "A repeated candidate now passes the deepest validation "
                        "gate; completing from the normalized candidate instead "
                        "of replaying stale repair findings."
                    )
                if self.dry_run:
                    clean_preview = _deps.preview_project_edit_agent_response(
                        self.candidate,
                        project_root=self.root,
                        request_prompt=self.prompt,
                        behavioral_proof_deferred=True,
                    )
                    raise _WorkflowReturn(
                        _deps.ProjectEditWorkflowResult(
                            ok=True,
                            status="preview_ok",
                            candidate=self.candidate,
                            preview=clean_preview,
                            timings=self.timings,
                        )
                    )
                self.seen_validation_candidate_fingerprints.discard(
                    self.validation_candidate_fingerprint
                )
                self.last_validation_errors = []
            else:
                if self.status_callback:
                    self.status_callback(
                        "Stopped a repeated package candidate before validation; equivalent deterministic repairs cannot cycle indefinitely."
                    )
                retained_preview = _deps.preview_project_edit_agent_response(
                    self.candidate,
                    project_root=self.root,
                    request_prompt=self.prompt,
                    behavioral_proof_deferred=True,
                )
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="repair_cycle_detected",
                        candidate=self.candidate,
                        preview=retained_preview,
                        errors=list(
                            dict.fromkeys(
                                [
                                    *repeated_candidate_errors,
                                    "A previously validated package candidate reappeared during repair. The candidate was retained and no equivalent repair was repeated.",
                                ]
                            )
                        ),
                        timings=self.timings,
                    )
                )
        self.seen_validation_candidate_fingerprints.add(
            self.validation_candidate_fingerprint
        )
        self.cached_review = self.final_review_cache.get(self.candidate)
        _deps._save_workflow_checkpoint(
            self.root,
            self.prompt,
            self.selected_model,
            self.generated_files,
            {
                "attempt": self.attempt,
                "class_repair_attempts": [
                    [path, symbol, count]
                    for (path, symbol), count in self.class_repair_attempts.items()
                ],
                "stalled_callable_symbols": [
                    [path, symbol]
                    for path, symbol in sorted(self.stalled_callable_symbols)
                ],
                "strong_callable_symbols": [
                    [path, symbol]
                    for path, symbol in sorted(self.strong_callable_symbols)
                ],
                "compact_callable_attempts": [
                    [path, symbol, count]
                    for (path, symbol), count in sorted(
                        self.compact_callable_attempts.items()
                    )
                ],
                "file_repair_attempts": [
                    [path, count]
                    for path, count in sorted(self.file_repair_attempts.items())
                ],
                "final_review_fingerprint": (
                    _deps._candidate_checkpoint_fingerprint(self.candidate)
                    if self.cached_review is not None
                    else ""
                ),
                "final_review_errors": list(self.cached_review or []),
                "semantic_proofs": [
                    [requirement_id, source_hash]
                    for requirement_id, source_hash in sorted(
                        self.semantic_proof_cache.items()
                    )
                ],
                "behavior_harness": self.restored_workflow_state.get(
                    "behavior_harness"
                ),
                "chunk_coverage": self.chunk_coverage,
                "complete": False,
            },
            implementation_plan_hash=self.approval_id,
        )
        self.generated_files, self.snapshot_plan_repairs = (
            self.apply_deterministic_implementation_plan_repairs(
                self.implementation_plan, self.generated_files
            )
        )
        if self.snapshot_plan_repairs:
            self.generated_files, self._unused_import_repairs = (
                _deps.remove_project_edit_unused_imports(self.generated_files)
            )
            self.candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            if self.status_callback:
                self.status_callback(
                    "Applied approved deterministic symbol repairs before validation: "
                    + "; ".join(self.snapshot_plan_repairs)
                )
        self.generated_files, self.prevalidation_path_policy_repairs = (
            _deps._repair_explicit_path_policy_semantics(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.prevalidation_result_repairs = (
            _deps._repair_command_result_envelope_contract(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.prevalidation_cache_repairs = (
            _deps._repair_image_cache_contract(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.prevalidation_queue_repairs = (
            _deps._repair_priority_job_queue_contract(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.prevalidation_registry_repairs = (
            _deps._repair_explicit_command_registry_contract(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.prevalidation_delegation_repairs = (
            _deps._repair_explicit_cross_file_delegation(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.prevalidation_contract_repairs = [
            *self.prevalidation_path_policy_repairs,
            *self.prevalidation_result_repairs,
            *self.prevalidation_cache_repairs,
            *self.prevalidation_queue_repairs,
            *self.prevalidation_registry_repairs,
            *self.prevalidation_delegation_repairs,
        ]
        if self.prevalidation_contract_repairs:
            self.generated_files = _deps._normalize_generated_files(
                self.generated_files,
                project_root=self.root,
                request_prompt=self.prompt,
            )
            self.candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            if self.status_callback:
                self.status_callback(
                    "Applied explicit cross-file contracts before validation: "
                    + "; ".join(self.prevalidation_contract_repairs)
                )
        self.generated_files, deferred_annotations = (
            _defer_union_annotations_for_legacy_python(self.generated_files)
        )
        if deferred_annotations:
            deferred_paths = {
                _deps.Path(path).resolve() for path in deferred_annotations
            }
            for file_index, record in enumerate(self.generated_files):
                if _deps.Path(record[0]).resolve() not in deferred_paths:
                    continue
                formatted, _formatting_notes = (
                    _deps.format_project_edit_generated_python([record])
                )
                self.generated_files[file_index] = formatted[0]
            self.candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            if self.status_callback:
                self.status_callback(
                    "Normalized generated typing references for runtime compatibility: "
                    + ", ".join(_deps.Path(path).name for path in deferred_annotations)
                )
        self.validation_started = _deps.time.perf_counter()
        self.active_validation_files = self.generated_files
        self.ephemeral_validation_path = ""
        self.approved_plan_errors = (
            self.validate_generated_files_against_implementation_plan(
                self.implementation_plan, self.generated_files
            )
        )
        if self.approved_plan_errors:
            self.generated_files, self.boundary_repairs = (
                _deps._repair_explicit_boundary_contracts(
                    self.generated_files, self.approved_plan_errors,
                )
            )
            if self.boundary_repairs:
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                self.active_validation_files = self.generated_files
                self.approved_plan_errors = (
                    self.validate_generated_files_against_implementation_plan(
                        self.implementation_plan, self.generated_files
                    )
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied source-grounded boundary repairs: "
                        + "; ".join(self.boundary_repairs)
                    )
        if self.approved_plan_errors:
            self.preview = _deps.ProjectEditApplyResult(
                ok=False,
                status="approved_plan_validation_failed",
                errors=list(self.approved_plan_errors),
            )
            self.errors = list(self.approved_plan_errors)
            if self.status_callback:
                self.status_callback(
                    f"Approved-plan validation blocked runtime execution with {len(self.errors)} contract issue(s)."
                )
        else:
            self.approved_behavior_rows = _deps._approved_behavior_contract_rows(
                self.implementation_plan
            )
            self.preview = _deps.preview_project_edit_agent_response(
                self.candidate,
                project_root=self.root,
                request_prompt=self.prompt,
                behavioral_proof_deferred=bool(self.approved_behavior_rows),
            )
            if self.status_callback:
                for self.validation_result in self.preview.validation or []:
                    if self.validation_result.get("check") == "validation_timing":
                        self.status_callback(
                            str(self.validation_result.get("message") or "")
                        )
            self.errors = list(self.preview.errors or [])
        self.last_validation_errors = list(self.errors)
        if self.preview.ok and (not self.errors):
            self.harness_cache_key = _deps._checkpoint_hash(
                {
                    "prompt": self.prompt,
                    "plan": self.implementation_plan,
                    "harness_contract": "approved-behavior-sidecar-v33",
                }
            )
            self.runtime_behavior_rows = _deps._expanded_ephemeral_behavior_rows(
                self.implementation_plan, generated_files=self.generated_files
            )
            self.runtime_behavior_rows = [
                row
                for row in self.runtime_behavior_rows
                if self.semantic_proof_cache.get(
                    str(row.get("requirement_id") or "")
                )
                != _deps._requirement_source_hash(
                    str(row.get("requirement_id") or ""),
                    implementation_plan=self.implementation_plan,
                    generated_files=self.generated_files,
                )
            ]
            self.all_behavior_rows = _deps._expanded_ephemeral_behavior_rows(
                self.implementation_plan
            )
            self.runtime_source_behavior_ids = {
                str(
                    row.get("source_behavior_id")
                    or _deps.re.sub(
                        r"__owner_\d+$",
                        "",
                        str(row.get("behavior_id") or ""),
                    )
                )
                for row in self.runtime_behavior_rows
            }
            self.behavior_ids_by_requirement: dict[str, set[str]] = {}
            for self.behavior_row in self.all_behavior_rows:
                self.behavior_requirement_id = str(
                    self.behavior_row.get("requirement_id") or ""
                )
                self.source_behavior_id = str(
                    self.behavior_row.get("source_behavior_id")
                    or _deps.re.sub(
                        r"__owner_\d+$",
                        "",
                        str(self.behavior_row.get("behavior_id") or ""),
                    )
                )
                if self.behavior_requirement_id and self.source_behavior_id:
                    self.behavior_ids_by_requirement.setdefault(
                        self.behavior_requirement_id,
                        set(),
                    ).add(self.source_behavior_id)
            self.structurally_proven_requirement_ids = {
                requirement_id
                for requirement_id, behavior_ids in (
                    self.behavior_ids_by_requirement.items()
                )
                if behavior_ids
                and behavior_ids.isdisjoint(self.runtime_source_behavior_ids)
            }
            for self.requirement_id in self.structurally_proven_requirement_ids:
                self.semantic_proof_cache[self.requirement_id] = (
                    _deps._requirement_source_hash(
                        self.requirement_id,
                        implementation_plan=self.implementation_plan,
                        generated_files=self.generated_files,
                    )
                )
            self.required_behavior_ids = [
                str(row.get("behavior_id") or "")
                for row in self.runtime_behavior_rows
                if str(row.get("behavior_id") or "")
            ]
            self.required_harness_test_names = [
                str(row.get("test_name") or "").strip()
                for row in self.runtime_behavior_rows
                if str(row.get("behavior_id") or "")
            ]
            if len(self.required_harness_test_names) != len(
                self.required_behavior_ids
            ) or not all(self.required_harness_test_names):
                self.required_harness_test_names = []
            self.harness_entry = self.behavior_harness_cache.get(self.harness_cache_key)
            if (
                self.harness_entry is None
                and not self.runtime_behavior_rows
                and self.status_callback
            ):
                self.status_callback(
                    "Skipping disposable harness generation: source-hashed "
                    "executable proofs already cover every runtime behavior row."
                )
            if self.harness_entry is None and self.runtime_behavior_rows:
                if self.status_callback:
                    self.approved_rows = self.runtime_behavior_rows
                    self.structural_proof_count = max(
                        0, len(self.all_behavior_rows) - len(self.approved_rows)
                    )
                    self.status_callback(
                        f"Deterministic structural proof covers {self.structural_proof_count} owner contract(s); compiling runtime proof from {len(self.approved_rows)} approved behavior contract(s) and {sum((len(row.get('execution_steps') or []) for row in self.approved_rows))} ordered state transition(s)"
                    )
                self.harness_stage, self.required_behavior_ids = (
                    _deps._build_ephemeral_behavior_harness_stage(
                        prompt=self.prompt,
                        implementation_plan=self.implementation_plan,
                        generated_files=self.generated_files,
                        project_root=self.root,
                    )
                )
                if self.harness_stage is not None:
                    self.prebuilt_harness_response = ""
                    self.shard_harness_feedback = ""
                    if len(self.runtime_behavior_rows) > 1:
                        # Share the large production-source prompt across a few
                        # exact-test groups, then independently retain valid
                        # proofs instead of discarding a whole partial batch.
                        self.pending_harness_batches = _group_behavior_proof_batches(
                            self.runtime_behavior_rows
                        )
                        self.accepted_harness_sources: list[str] = []
                        self.shard_sequence = 0
                        while self.pending_harness_batches:
                            self.batch = self.pending_harness_batches.pop(0)
                            self.shard_sequence += 1
                            self.batch_stage, self.batch_behavior_ids = (
                                _deps._build_ephemeral_behavior_harness_stage(
                                    prompt=self.prompt,
                                    implementation_plan=self.implementation_plan,
                                    generated_files=self.generated_files,
                                    project_root=self.root,
                                    behavior_rows_override=self.batch,
                                )
                            )
                            if self.batch_stage is None:
                                continue
                            self.batch_test_names = [
                                str(row.get("test_name") or "").strip()
                                for row in self.batch
                                if isinstance(row, _deps.Mapping)
                                and str(row.get("test_name") or "").strip()
                            ]
                            if len(self.batch_test_names) != len(
                                self.batch_behavior_ids
                            ):
                                self.batch_test_names = []
                            if self.status_callback:
                                self.status_callback(
                                    f"Generating disposable behavior capsule {self.shard_sequence} for "
                                    + ", ".join(self.batch_behavior_ids)
                                    + "."
                                )
                            self.batch_response, self.batch_timing = _deps._query_stage(
                                self.batch_stage,
                                selected_model=_behavior_harness_generation_model(
                                    self.settings, self.selected_model
                                ),
                                settings=self.settings,
                                timeout=self.timeout,
                            )
                            self.batch_timing.update(
                                {
                                    "attempt": self.attempt,
                                    "strategy_attempt": self.shard_sequence,
                                    "stage": "ephemeral_behavior_harness_shard",
                                }
                            )
                            self.timings.append(self.batch_timing)
                            self.batch_response = (
                                _deps._ensure_ephemeral_behavior_bindings(
                                    self.batch_response,
                                    self.batch_behavior_ids,
                                    self.batch_test_names,
                                )
                            )
                            self.batch_source, self.batch_errors = (
                                _deps._parse_ephemeral_behavior_harness(
                                    self.batch_response,
                                    self.batch_behavior_ids,
                                    self.batch_test_names,
                                    request_prompt=self.prompt,
                                )
                            )
                            if not self.batch_errors:
                                self.batch_source, self.builtin_import_repairs = (
                                    _normalize_disposable_builtin_exception_imports(
                                        self.batch_source, self.generated_files,
                                        project_root=self.root,
                                    )
                                )
                                if self.builtin_import_repairs and self.status_callback:
                                    self.status_callback(
                                        "Removed invalid built-in exception imports "
                                        "from disposable proof: "
                                        + ", ".join(self.builtin_import_repairs)
                                    )
                                self.batch_source, self.batch_oracle_repairs = (
                                    _deps._repair_ephemeral_literal_oracles(
                                        self.batch_source, self.prompt, self.batch
                                    )
                                )
                                if self.batch_oracle_repairs and self.status_callback:
                                    self.status_callback(
                                        "Corrected request-grounded disposable literal oracles: "
                                        + "; ".join(self.batch_oracle_repairs)
                                    )
                                self.batch_errors.extend(
                                    _preflight_behavior_capsule(
                                        self.batch_source,
                                        self.batch,
                                        self.generated_files,
                                        request_prompt=self.prompt,
                                        project_root=self.root,
                                    )
                                )
                            self.batch_group_count = len({
                                str(row.get("test_name") or "") for row in self.batch
                            })
                            if (
                                self.batch_errors
                                and self.batch_group_count > 1
                                and self.batch_source.strip()
                            ):
                                self.salvaged_sources, self.retry_groups = (
                                    _salvage_behavior_proof_batch(
                                        self.batch_response,
                                        self.batch,
                                        self.generated_files,
                                        request_prompt=self.prompt,
                                        project_root=self.root,
                                    )
                                )
                                if self.retry_groups:
                                    self.accepted_harness_sources.extend(
                                        self.salvaged_sources
                                    )
                                    self.pending_harness_batches = (
                                        self.retry_groups
                                        + self.pending_harness_batches
                                    )
                                    if self.status_callback:
                                        self.status_callback(
                                            "Retained "
                                            f"{len(self.salvaged_sources)}/{self.batch_group_count} "
                                            "independently valid disposable proofs; "
                                            "retrying failed test groups individually."
                                        )
                                    continue
                            if self.batch_errors and len(self.batch) > 1:
                                if self.status_callback:
                                    self.status_callback(
                                        "Disposable class behavior capsule was incomplete; falling back once to the complete-harness generator without singleton fan-out."
                                    )
                                self.shard_harness_feedback = " | ".join(
                                    self.batch_errors
                                )
                                continue
                            self.singleton_attempt = 0
                            self.previous_singleton_response = str(
                                self.batch_response or ""
                            )
                            while self.batch_errors and self.singleton_attempt < 3:
                                self.singleton_attempt += 1
                                if self.status_callback:
                                    self.status_callback(
                                        f"Disposable behavior {self.batch_behavior_ids[0]} preflight: "
                                        + " | ".join(self.batch_errors)[:900]
                                    )
                                self.repeated_candidate = (
                                    self.singleton_attempt > 1
                                    and str(self.batch_response or "").strip()
                                    == self.previous_singleton_response.strip()
                                )
                                self.previous_singleton_response = str(
                                    self.batch_response or ""
                                )
                                self.fixture_guidance = (
                                    _single_behavior_fixture_guidance(self.batch_errors)
                                )
                                self.rejected_candidate_context = (
                                    "\nDo not reuse the prior rejected test body; write a fresh positive-case test."
                                    if any(
                                        "invents assertRaises behavior" in error
                                        for error in self.batch_errors
                                    )
                                    else "\nPrevious rejected candidate (do not repeat it):\n```python\n"
                                    + str(self.batch_response or "")[:6000]
                                    + "\n```"
                                )
                                self.focused_batch_stage = _deps.replace(
                                    self.batch_stage,
                                    system_prompt=_single_behavior_repair_system_prompt(
                                        self.batch_stage.system_prompt,
                                        self.singleton_attempt,
                                    ),
                                    user_prompt=self.batch_stage.user_prompt
                                    + "\n\nTHE PREVIOUS SINGLE-BEHAVIOR CAPSULE WAS REJECTED:\n"
                                    + " | ".join(self.batch_errors)
                                    + self.rejected_candidate_context
                                    + "\nReturn only the complete unittest module for this one exact behavior ID. "
                                    + "Change the failing test body to directly execute the public production callable; "
                                    + "do not patch the public callable or assert outcomes unrelated to this contract."
                                    + (
                                        "\nFIXTURE REPAIR GUIDANCE:\n"
                                        + self.fixture_guidance
                                        if self.fixture_guidance
                                        else ""
                                    )
                                    + (
                                        "\nThe previous candidate was unchanged. Use a different implementation strategy and replace the failing test body."
                                        if self.repeated_candidate
                                        else ""
                                    ),
                                    metadata={
                                        **dict(self.batch_stage.metadata or {}),
                                        "repair_temperature": min(
                                            0.15 + self.singleton_attempt * 0.1, 0.65
                                        ),
                                        "repair_scope": "single_behavior_test",
                                    },
                                )
                                if self.status_callback:
                                    self.status_callback(
                                        f"Repairing disposable behavior {self.batch_behavior_ids[0]}, attempt {self.singleton_attempt}; production files remain frozen."
                                    )
                                self.batch_response, self.batch_timing = (
                                    _deps._query_stage(
                                        self.focused_batch_stage,
                                        selected_model=_behavior_harness_generation_model(
                                            self.settings, self.selected_model
                                        ),
                                        settings=self.settings,
                                        timeout=self.timeout,
                                    )
                                )
                                self.batch_timing.update(
                                    {
                                        "attempt": self.attempt,
                                        "strategy_attempt": self.shard_sequence,
                                        "stage": "ephemeral_behavior_harness_singleton",
                                    }
                                )
                                self.timings.append(self.batch_timing)
                                self.batch_response = (
                                    _deps._ensure_ephemeral_behavior_bindings(
                                        self.batch_response,
                                        self.batch_behavior_ids,
                                        self.batch_test_names,
                                    )
                                )
                                self.batch_source, self.batch_errors = (
                                    _deps._parse_ephemeral_behavior_harness(
                                        self.batch_response,
                                        self.batch_behavior_ids,
                                        self.batch_test_names,
                                        request_prompt=self.prompt,
                                    )
                                )
                                if not self.batch_errors:
                                    self.batch_source, self.builtin_import_repairs = (
                                        _normalize_disposable_builtin_exception_imports(
                                            self.batch_source, self.generated_files,
                                            project_root=self.root,
                                        )
                                    )
                                    if self.builtin_import_repairs and self.status_callback:
                                        self.status_callback(
                                            "Removed invalid built-in exception imports "
                                            "from disposable proof: "
                                            + ", ".join(self.builtin_import_repairs)
                                        )
                                    self.batch_source, self.batch_oracle_repairs = (
                                        _deps._repair_ephemeral_literal_oracles(
                                            self.batch_source, self.prompt, self.batch
                                        )
                                    )
                                    if self.batch_oracle_repairs and self.status_callback:
                                        self.status_callback(
                                            "Corrected request-grounded disposable literal oracles: "
                                            + "; ".join(self.batch_oracle_repairs)
                                        )
                                    self.batch_errors.extend(
                                        _preflight_behavior_capsule(
                                            self.batch_source,
                                            self.batch,
                                            self.generated_files,
                                            request_prompt=self.prompt,
                                            project_root=self.root,
                                        )
                                    )
                            if not self.batch_errors and self.batch_source.strip():
                                self.accepted_harness_sources.append(self.batch_source)
                        if self.accepted_harness_sources:
                            self.prebuilt_harness_response = (
                                self.accepted_harness_sources[0]
                                if len(self.accepted_harness_sources) == 1
                                else _deps._merge_ephemeral_harness_sources(
                                    self.accepted_harness_sources
                                )
                            )
                    self.harness_feedback = self.behavior_harness_feedback.get(
                        self.harness_cache_key, self.shard_harness_feedback
                    )
                    self.previous_harness_response = ""
                    for self.harness_attempt in range(1, 3):
                        self.current_harness_stage = self.harness_stage
                        if self.harness_feedback:
                            self.current_harness_stage = _deps.replace(
                                self.harness_stage,
                                user_prompt=self.harness_stage.user_prompt
                                + "\n\nREJECTED HARNESS FEEDBACK:\n"
                                + self.harness_feedback
                                + "\nReturn a complete replacement unittest module. Do not repeat the rejected response.",
                            )
                        if self.status_callback:
                            self.status_callback(
                                f"Generating disposable public-API tests for every executable behavior clause, attempt {self.harness_attempt}."
                            )
                        if self.prebuilt_harness_response:
                            self.harness_response = self.prebuilt_harness_response
                            self.prebuilt_harness_response = ""
                        else:
                            self.harness_response, self.harness_timing = (
                                _deps._query_stage(
                                    self.current_harness_stage,
                                    selected_model=_behavior_harness_generation_model(
                                        self.settings, self.selected_model
                                    ),
                                    settings=self.settings,
                                    timeout=self.timeout,
                                )
                            )
                            self.harness_timing.update(
                                {
                                    "attempt": self.attempt,
                                    "strategy_attempt": self.harness_attempt,
                                    "stage": "ephemeral_behavior_harness",
                                }
                            )
                            self.timings.append(self.harness_timing)
                        self.harness_response = (
                            _deps._ensure_ephemeral_behavior_bindings(
                                self.harness_response,
                                self.required_behavior_ids,
                                self.required_harness_test_names,
                            )
                        )
                        self.harness_source, self.harness_errors = (
                            _deps._parse_ephemeral_behavior_harness(
                                self.harness_response,
                                self.required_behavior_ids,
                                self.required_harness_test_names,
                                request_prompt=self.prompt,
                            )
                        )
                        if not self.harness_errors:
                            self.harness_source, self.literal_oracle_repairs = (
                                _deps._repair_ephemeral_literal_oracles(
                                    self.harness_source,
                                    self.prompt,
                                    list(self.harness_stage.metadata.get("behavior_rows", [])),
                                )
                            )
                            if self.literal_oracle_repairs and self.status_callback:
                                self.status_callback(
                                    "Corrected request-grounded disposable literal oracles: "
                                    + "; ".join(self.literal_oracle_repairs)
                                )
                            self.harness_name = (
                                "test_requirement_contract_"
                                + self.harness_cache_key[:12]
                                + ".py"
                            )
                            self.harness_path = str(
                                _deps.Path(_deps.tempfile.gettempdir())
                                / "tech_connector"
                                / "validation"
                                / self.harness_name
                            )
                            self.normalized_harness = _deps._normalize_generated_files(
                                [(self.harness_path, "", self.harness_source)],
                                project_root=self.root,
                                request_prompt=self.prompt,
                            )
                            self.harness_source = self.normalized_harness[0][2]
                            self.harness_source, self.binding_restore_errors = (
                                _deps._parse_ephemeral_behavior_harness(
                                    self.harness_source,
                                    self.required_behavior_ids,
                                    self.required_harness_test_names,
                                )
                            )
                            self.harness_errors.extend(self.binding_restore_errors)
                            (
                                self.harness_source,
                                self.numeric_callable_fixture_repairs,
                            ) = _deps._repair_ephemeral_numeric_callable_fixtures(
                                self.harness_source, self.generated_files
                            )
                            self.harness_source = (
                                _deps._ensure_ephemeral_behavior_bindings(
                                    self.harness_source,
                                    self.required_behavior_ids,
                                    self.required_harness_test_names,
                                )
                            )
                            self.harness_source, self.post_fixture_binding_errors = (
                                _deps._parse_ephemeral_behavior_harness(
                                    self.harness_source,
                                    self.required_behavior_ids,
                                    self.required_harness_test_names,
                                )
                            )
                            self.harness_errors.extend(self.post_fixture_binding_errors)
                            if (
                                self.numeric_callable_fixture_repairs
                                and self.status_callback
                            ):
                                self.status_callback(
                                    "Applied deterministic disposable callable fixture repairs: "
                                    + "; ".join(self.numeric_callable_fixture_repairs)
                                )
                            self.deterministic_harness_errors = (
                                _deps._ephemeral_harness_call_graph_errors(
                                    self.harness_source,
                                    self.generated_files,
                                    request_prompt=self.prompt,
                                )
                            )
                            self.deterministic_harness_errors.extend(
                                _disposable_harness_invalid_imports(
                                    self.harness_source,
                                    self.generated_files,
                                    project_root=self.root,
                                )
                            )
                            self.deterministic_harness_errors.extend(
                                _deps._ephemeral_harness_behavior_contract_errors(
                                    self.harness_source,
                                    list(
                                        self.harness_stage.metadata.get(
                                            "behavior_rows", []
                                        )
                                    ),
                                    generated_files=self.generated_files,
                                    request_prompt=self.prompt,
                                )
                            )
                            if self.deterministic_harness_errors:
                                (
                                    self.harness_source,
                                    self.deterministic_harness_repairs,
                                ) = _deps._repair_ephemeral_harness_call_graph(
                                    self.harness_source,
                                    self.generated_files,
                                    request_prompt=self.prompt,
                                    project_root=self.root,
                                )
                                if self.deterministic_harness_repairs:
                                    self.normalized_harness = (
                                        _deps._normalize_generated_files(
                                            [
                                                (
                                                    self.harness_path,
                                                    "",
                                                    self.harness_source,
                                                )
                                            ],
                                            project_root=self.root,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    self.harness_source = self.normalized_harness[0][2]
                                    self.harness_source, post_audit_oracle_notes = (
                                        _deps._repair_ephemeral_literal_oracles(
                                            self.harness_source,
                                            self.prompt,
                                            list(self.harness_stage.metadata.get("behavior_rows", [])),
                                        )
                                    )
                                    if post_audit_oracle_notes and self.status_callback:
                                        self.status_callback(
                                            "Corrected source-grounded disposable oracles after semantic audit: "
                                            + "; ".join(post_audit_oracle_notes)
                                        )
                                    self.harness_source, self.binding_restore_errors = (
                                        _deps._parse_ephemeral_behavior_harness(
                                            self.harness_source,
                                            self.required_behavior_ids,
                                            self.required_harness_test_names,
                                        )
                                    )
                                    self.harness_errors.extend(
                                        self.binding_restore_errors
                                    )
                                    self.deterministic_harness_errors = (
                                        _deps._ephemeral_harness_call_graph_errors(
                                            self.harness_source,
                                            self.generated_files,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    self.deterministic_harness_errors.extend(
                                        _deps._ephemeral_harness_behavior_contract_errors(
                                            self.harness_source,
                                            list(
                                                self.harness_stage.metadata.get(
                                                    "behavior_rows", []
                                                )
                                            ),
                                            generated_files=self.generated_files,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    self.deterministic_harness_errors.extend(
                                        _disposable_harness_invalid_imports(
                                            self.harness_source,
                                            self.generated_files,
                                            project_root=self.root,
                                        )
                                    )
                                    if self.status_callback:
                                        self.status_callback(
                                            "Applied deterministic disposable host-fixture repairs: "
                                            + "; ".join(
                                                self.deterministic_harness_repairs
                                            )
                                        )
                            if self.deterministic_harness_errors:
                                if self.status_callback:
                                    self.status_callback(
                                        "Repairing validator-rejected disposable harness before runtime: "
                                        + " | ".join(self.deterministic_harness_errors)
                                    )
                                self.focused_audit_stage = (
                                    _deps._build_ephemeral_harness_audit_stage(
                                        behavior_rows=list(
                                            self.harness_stage.metadata.get(
                                                "behavior_rows", []
                                            )
                                        ),
                                        generated_files=self.generated_files,
                                        harness_source=self.harness_source,
                                        known_issues=self.deterministic_harness_errors,
                                    )
                                )
                                (
                                    self.focused_audit_response,
                                    self.focused_audit_timing,
                                ) = _deps._query_stage(
                                    self.focused_audit_stage,
                                    selected_model=self.selected_model,
                                    settings=self.settings,
                                    timeout=self.timeout,
                                )
                                self.focused_audit_timing.update(
                                    {
                                        "attempt": self.attempt,
                                        "strategy_attempt": self.harness_attempt,
                                        "stage": "ephemeral_behavior_harness_focused_audit",
                                    }
                                )
                                self.timings.append(self.focused_audit_timing)
                                self.focused_issues, self.focused_repairs = (
                                    _deps._parse_ephemeral_harness_audit(
                                        self.focused_audit_response,
                                        accept_validator_repairs=True,
                                    )
                                )
                                if self.status_callback:
                                    self.status_callback(
                                        f"Focused disposable audit returned {len(self.focused_issues)} issue(s) and {len(self.focused_repairs)} exact method replacement(s)."
                                    )
                                if self.focused_repairs:
                                    self.harness_source, self.focused_apply_errors = (
                                        _deps._apply_ephemeral_harness_repairs(
                                            self.harness_source,
                                            self.focused_repairs,
                                            generated_files=self.generated_files,
                                        )
                                    )
                                    if not self.focused_apply_errors:
                                        self.normalized_harness = (
                                            _deps._normalize_generated_files(
                                                [
                                                    (
                                                        self.harness_path,
                                                        "",
                                                        self.harness_source,
                                                    )
                                                ],
                                                project_root=self.root,
                                                request_prompt=self.prompt,
                                            )
                                        )
                                        self.harness_source = self.normalized_harness[
                                            0
                                        ][2]
                                        (
                                            self.harness_source,
                                            self.binding_restore_errors,
                                        ) = _deps._parse_ephemeral_behavior_harness(
                                            self.harness_source,
                                            self.required_behavior_ids,
                                            self.required_harness_test_names,
                                        )
                                        self.harness_errors.extend(
                                            self.binding_restore_errors
                                        )
                                        self.deterministic_harness_errors = (
                                            _deps._ephemeral_harness_call_graph_errors(
                                                self.harness_source,
                                                self.generated_files,
                                                request_prompt=self.prompt,
                                            )
                                        )
                                        self.deterministic_harness_errors.extend(
                                            _deps._ephemeral_harness_behavior_contract_errors(
                                                self.harness_source,
                                                list(
                                                    self.harness_stage.metadata.get(
                                                        "behavior_rows", []
                                                    )
                                                ),
                                                generated_files=self.generated_files,
                                                request_prompt=self.prompt,
                                            )
                                        )
                                        self.deterministic_harness_errors.extend(
                                            _disposable_harness_invalid_imports(
                                                self.harness_source,
                                                self.generated_files,
                                                project_root=self.root,
                                            )
                                        )
                                    else:
                                        self.deterministic_harness_errors.extend(
                                            self.focused_apply_errors
                                        )
                                if self.deterministic_harness_errors:
                                    self.harness_source, self.exact_owner_repairs = (
                                        _deps._repair_ephemeral_indirect_owner_invocations(
                                            self.harness_source,
                                            self.deterministic_harness_errors,
                                            generated_files=self.generated_files,
                                        )
                                    )
                                    if self.exact_owner_repairs:
                                        self.normalized_harness = (
                                            _deps._normalize_generated_files(
                                                [
                                                    (
                                                        self.harness_path,
                                                        "",
                                                        self.harness_source,
                                                    )
                                                ],
                                                project_root=self.root,
                                                request_prompt=self.prompt,
                                            )
                                        )
                                        self.harness_source = self.normalized_harness[
                                            0
                                        ][2]
                                        (
                                            self.harness_source,
                                            self.binding_restore_errors,
                                        ) = _deps._parse_ephemeral_behavior_harness(
                                            self.harness_source,
                                            self.required_behavior_ids,
                                            self.required_harness_test_names,
                                        )
                                        self.deterministic_harness_errors = list(
                                            self.binding_restore_errors
                                        )
                                        self.deterministic_harness_errors.extend(
                                            _deps._ephemeral_harness_call_graph_errors(
                                                self.harness_source,
                                                self.generated_files,
                                                request_prompt=self.prompt,
                                            )
                                        )
                                        self.deterministic_harness_errors.extend(
                                            _deps._ephemeral_harness_behavior_contract_errors(
                                                self.harness_source,
                                                list(
                                                    self.harness_stage.metadata.get(
                                                        "behavior_rows", []
                                                    )
                                                ),
                                                generated_files=self.generated_files,
                                                request_prompt=self.prompt,
                                            )
                                        )
                                        self.deterministic_harness_errors.extend(
                                            _disposable_harness_invalid_imports(
                                                self.harness_source,
                                                self.generated_files,
                                                project_root=self.root,
                                            )
                                        )
                                        if self.status_callback:
                                            self.status_callback(
                                                "Applied deterministic pre-runtime exact-owner test repair: "
                                                + "; ".join(self.exact_owner_repairs)
                                            )
                                if self.deterministic_harness_errors:
                                    self.harness_errors.extend(
                                        self.deterministic_harness_errors
                                    )
                                    self.harness_feedback = " | ".join(
                                        self.harness_errors
                                    )
                                    self.previous_harness_response = self.harness_source
                                    self.prebuilt_harness_response = ""
                                    if self.status_callback:
                                        self.status_callback(
                                            "Exact disposable test-method repair did not clear its assigned failures; changing harness generation strategy with exact owner feedback while preserving production files."
                                        )
                                        self.status_callback(
                                            "Rejected disposable harness source:\n"
                                            + self.harness_source
                                        )
                                    continue
                                if self.status_callback:
                                    self.status_callback(
                                        "Focused disposable harness repairs passed deterministic call-graph checks."
                                    )
                            self.audit_rows = list(
                                self.harness_stage.metadata.get("behavior_rows", [])
                            )
                            self.audit_issues: list[str] = []
                            self.audit_repairs: list[dict[str, str]] = []
                            self.audit_batch_size = 3
                            self.harness_bindings, self.harness_binding_errors = (
                                _deps._ephemeral_behavior_bindings(self.harness_source)
                            )
                            self.bound_behavior_ids = {
                                behavior_id
                                for behavior_ids in self.harness_bindings.values()
                                for behavior_id in behavior_ids
                            }
                            self.deterministic_harness_proof_complete = bool(
                                not self.harness_binding_errors
                                and set(self.required_behavior_ids).issubset(
                                    self.bound_behavior_ids
                                )
                                and (
                                    not _deps._ephemeral_harness_call_graph_errors(
                                        self.harness_source,
                                        self.generated_files,
                                        request_prompt=self.prompt,
                                    )
                                )
                                and (
                                    not _deps._ephemeral_harness_behavior_contract_errors(
                                        self.harness_source,
                                        self.audit_rows,
                                        generated_files=self.generated_files,
                                        request_prompt=self.prompt,
                                    )
                                )
                            )
                            self.audit_batches = (
                                []
                                if self.deterministic_harness_proof_complete
                                else [
                                    self.audit_rows[
                                        index : index + self.audit_batch_size
                                    ]
                                    for index in range(
                                        0, len(self.audit_rows), self.audit_batch_size
                                    )
                                ]
                            )
                            if (
                                self.deterministic_harness_proof_complete
                                and self.status_callback
                            ):
                                self.status_callback(
                                    "Skipping redundant model harness audit; exact behavior bindings and deterministic call-graph checks are complete. Final source-grounded semantic review remains required."
                                )
                            for self.audit_batch_index, self.audit_batch in enumerate(
                                self.audit_batches, start=1
                            ):
                                self.audit_stage = (
                                    _deps._build_ephemeral_harness_audit_stage(
                                        behavior_rows=self.audit_batch,
                                        generated_files=self.generated_files,
                                        harness_source=self.harness_source,
                                    )
                                )
                                if self.status_callback:
                                    self.status_callback(
                                        f"Auditing disposable behavior capsule {self.audit_batch_index}/{len(self.audit_batches)} against the production call graph."
                                    )
                                self.audit_response, self.audit_timing = (
                                    _deps._query_stage(
                                        self.audit_stage,
                                        selected_model=self.selected_model,
                                        settings=self.settings,
                                        timeout=self.timeout,
                                    )
                                )
                                self.audit_timing.update(
                                    {
                                        "attempt": self.attempt,
                                        "strategy_attempt": self.harness_attempt,
                                        "strategy_batch": self.audit_batch_index,
                                        "stage": "ephemeral_behavior_harness_audit",
                                    }
                                )
                                self.timings.append(self.audit_timing)
                                self.batch_issues, self.batch_repairs = (
                                    _deps._parse_ephemeral_harness_audit(
                                        self.audit_response
                                    )
                                )
                                self.audit_issues.extend(self.batch_issues)
                                self.audit_repairs.extend(self.batch_repairs)
                            if self.status_callback:
                                self.status_callback(
                                    f"Disposable behavior-capsule audits found {len(self.audit_issues)} issue(s) and {len(self.audit_repairs)} exact test-method replacement(s)."
                                )
                            if self.audit_repairs:
                                self.harness_source, self.audit_apply_errors = (
                                    _deps._apply_ephemeral_harness_repairs(
                                        self.harness_source,
                                        self.audit_repairs,
                                        generated_files=self.generated_files,
                                    )
                                )
                                if self.audit_apply_errors:
                                    self.harness_errors.extend(self.audit_apply_errors)
                                else:
                                    self.normalized_harness = (
                                        _deps._normalize_generated_files(
                                            [
                                                (
                                                    self.harness_path,
                                                    "",
                                                    self.harness_source,
                                                )
                                            ],
                                            project_root=self.root,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    self.harness_source = self.normalized_harness[0][2]
                                    self.harness_source, self.binding_restore_errors = (
                                        _deps._parse_ephemeral_behavior_harness(
                                            self.harness_source,
                                            self.required_behavior_ids,
                                            self.required_harness_test_names,
                                        )
                                    )
                                    self.harness_errors = list(
                                        self.binding_restore_errors
                                    )
                                    self.harness_errors.extend(
                                        _deps._ephemeral_harness_call_graph_errors(
                                            self.harness_source,
                                            self.generated_files,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    self.harness_errors.extend(
                                        _deps._ephemeral_harness_behavior_contract_errors(
                                            self.harness_source,
                                            list(
                                                self.harness_stage.metadata.get(
                                                    "behavior_rows", []
                                                )
                                            ),
                                            generated_files=self.generated_files,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    if self.status_callback:
                                        self.status_callback(
                                            "Applied audited disposable test-method repairs: "
                                            + ", ".join(
                                                (
                                                    str(repair.get("test") or "")
                                                    for repair in self.audit_repairs
                                                )
                                            )
                                        )
                            elif self.audit_issues:
                                self.harness_errors.extend(self.audit_issues)
                            if self.harness_errors:
                                self.harness_feedback = " | ".join(self.harness_errors)
                                self.previous_harness_response = self.harness_response
                                if self.status_callback:
                                    self.status_callback(
                                        "Disposable semantic review left exact test-method failures; preserving all accepted production and harness owners."
                                    )
                                break
                            self.harness_entry = (
                                self.harness_path,
                                self.harness_source,
                            )
                            self.behavior_harness_cache[self.harness_cache_key] = (
                                self.harness_path,
                                self.harness_source,
                            )
                            self.persist_behavior_harness(
                                self.harness_cache_key,
                                self.harness_path,
                                self.harness_source,
                            )
                            self.behavior_harness_feedback.pop(
                                self.harness_cache_key, None
                            )
                            break
                        self.unchanged = (
                            bool(self.previous_harness_response)
                            and self.harness_response.strip()
                            == self.previous_harness_response.strip()
                        )
                        self.harness_feedback = " | ".join(self.harness_errors)
                        if self.unchanged:
                            self.harness_feedback += " | The response was unchanged; do not spend another equivalent model call on this harness strategy."
                        self.previous_harness_response = self.harness_response
                        if self.status_callback:
                            self.status_callback(
                                "Rejected disposable harness: " + self.harness_feedback
                            )
                            self.status_callback(
                                "Rejected disposable harness source:\n"
                                + str(self.harness_source or self.harness_response)
                            )
                        if self.unchanged:
                            if self.status_callback:
                                self.status_callback(
                                    "Disposable harness repair was unchanged; changing strategy while preserving production files and accepted behavior proofs."
                                )
                            continue
            if (
                self.harness_entry is None
                and self.runtime_behavior_rows
                and not self.errors
            ):
                # A rejected disposable harness is missing proof, not proof
                # that production passed. Never let the later static-only
                # review silently turn this path into preview_ok.
                retained_preview = _deps.preview_project_edit_agent_response(
                    self.candidate,
                    project_root=self.root,
                    request_prompt=self.prompt,
                    behavioral_proof_deferred=True,
                )
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="behavioral_proof_deferred",
                        candidate=self.candidate,
                        preview=retained_preview,
                        errors=list(self.harness_errors) or [
                            "Required disposable behavior proof could not be "
                            "validated; production correctness is unverified."
                        ],
                        timings=self.timings,
                    )
                )
            if self.harness_entry is not None and (not self.errors):
                self.ephemeral_validation_path, self.harness_source = self.harness_entry
                self.harness_source, self.unapproved_rejection_repairs = (
                    _deps._repair_unapproved_ephemeral_rejections(
                        self.harness_source,
                        _deps._expanded_ephemeral_behavior_rows(
                            self.implementation_plan,
                            generated_files=self.generated_files,
                        ),
                    )
                )
                if self.unapproved_rejection_repairs:
                    self.harness_entry = (
                        self.ephemeral_validation_path,
                        self.harness_source,
                    )
                    self.persist_behavior_harness(
                        self.harness_cache_key,
                        self.ephemeral_validation_path,
                        self.harness_source,
                    )
                    if self.status_callback:
                        self.status_callback(
                            "Applied deterministic disposable oracle repair: "
                            + "; ".join(self.unapproved_rejection_repairs)
                        )
                self.harness_source, self.numeric_callable_fixture_repairs = (
                    _deps._repair_ephemeral_numeric_callable_fixtures(
                        self.harness_source, self.generated_files
                    )
                )
                if self.numeric_callable_fixture_repairs:
                    self.harness_entry = (
                        self.ephemeral_validation_path,
                        self.harness_source,
                    )
                    self.behavior_harness_cache[self.harness_cache_key] = (
                        self.harness_entry
                    )
                    if self.status_callback:
                        self.status_callback(
                            "Applied deterministic disposable callable fixture repairs at the shared execution boundary: "
                            + "; ".join(self.numeric_callable_fixture_repairs)
                        )
                self.active_validation_files = [
                    *self.generated_files,
                    (self.ephemeral_validation_path, "", self.harness_source),
                ]
                self.harness_candidate = _deps.build_project_edit_multi_file_candidate(
                    self.active_validation_files
                )
                self.harness_preview = _deps.preview_project_edit_agent_response(
                    self.harness_candidate,
                    project_root=self.root,
                    allowed_external_paths={self.ephemeral_validation_path},
                    request_prompt="Run the supplied disposable unittest module as an authoritative validation harness. It is not an output artifact.",
                )
                self.harness_preview_errors = [
                    *_deps._ephemeral_harness_behavior_contract_errors(
                        self.harness_source,
                        _deps._expanded_ephemeral_behavior_rows(
                            self.implementation_plan,
                            generated_files=self.generated_files,
                        ),
                        generated_files=self.generated_files,
                        request_prompt=self.prompt,
                    ),
                    *list(self.harness_preview.errors or []),
                ]
                self.runtime_test_owned_failure = bool(
                    self.harness_preview_errors
                ) and _deps._runtime_deepest_frame_is_test(self.harness_preview_errors)
                self.approved_observation_assertion_failure = any(
                    (
                        "AssertionError" in str(error)
                        for error in self.harness_preview_errors
                    )
                )
                self.approved_behavior_contract_failure = any(
                    (
                        "APPROVED BEHAVIOR CONTRACT FAILURE" in str(error)
                        for error in self.harness_preview_errors
                    )
                )
                self.harness_contract_failure = any(
                    _is_disposable_harness_contract_error(error)
                    for error in self.harness_preview_errors
                )
                self.harness_setup_or_runtime_exception = any(
                    (
                        _deps.re.search(
                            "\\b(?:AttributeError|TypeError|NameError|KeyError|IndexError|ImportError|ModuleNotFoundError|SyntaxError|unittest\\.mock)\\b",
                            str(error),
                        )
                        for error in self.harness_preview_errors
                    )
                )
                self.harness_owned_failure = (
                    not self.approved_observation_assertion_failure
                    and (not self.approved_behavior_contract_failure)
                    and (
                        self.harness_contract_failure
                        or (
                            self.runtime_test_owned_failure
                            and self.harness_setup_or_runtime_exception
                        )
                    )
                )
                self.oracle_checked_files, self.implicit_default_oracle_repairs = (
                    _deps._repair_ephemeral_runtime_fixture_contracts(
                        self.active_validation_files,
                        self.harness_preview_errors,
                        harness_path=self.ephemeral_validation_path,
                        request_prompt=self.prompt,
                        implementation_plan=self.implementation_plan,
                    )
                )
                if self.implicit_default_oracle_repairs:
                    self.harness_source = next(
                        (
                            source
                            for path, _original, source in self.oracle_checked_files
                            if path == self.ephemeral_validation_path
                        )
                    )
                    self.harness_entry = (
                        self.ephemeral_validation_path,
                        self.harness_source,
                    )
                    self.behavior_harness_cache[self.harness_cache_key] = (
                        self.harness_entry
                    )
                    self.persist_behavior_harness(
                        self.harness_cache_key,
                        self.ephemeral_validation_path,
                        self.harness_source,
                    )
                    if self.status_callback:
                        self.status_callback(
                            "Corrected disposable test-oracle expectations before production repair routing: "
                            + "; ".join(self.implicit_default_oracle_repairs)
                        )
                    raise _WorkflowContinue()
                if self.harness_owned_failure:
                    self.runtime_audit_candidate_key = (
                        _deps._candidate_checkpoint_fingerprint(self.candidate)
                    )
                    if self.runtime_audit_repair_counts.get(
                        self.runtime_audit_candidate_key, 0
                    ) >= 4:
                        if self.status_callback:
                            self.status_callback(
                                "Disposable runtime-proof repair budget exhausted for unchanged production; retaining the candidate and deferring proof."
                            )
                        retained_preview = _deps.preview_project_edit_agent_response(
                            self.candidate,
                            project_root=self.root,
                            request_prompt=self.prompt,
                            behavioral_proof_deferred=True,
                        )
                        raise _WorkflowReturn(
                            _deps.ProjectEditWorkflowResult(
                                ok=False,
                                status="behavioral_proof_deferred",
                                candidate=self.candidate,
                                preview=retained_preview,
                                errors=list(self.harness_preview_errors),
                                timings=self.timings,
                            )
                        )
                    if self.status_callback:
                        self.status_callback(
                            "Failure is owned by disposable test methods; freezing production and auditing only the exact failing tests against the production call graph."
                        )
                    self.runtime_audit_source = self.harness_source
                    self.runtime_audit_known_issues = list(self.harness_preview_errors)
                    self.accepted_runtime_audit_source = ""
                    self.seen_runtime_audit_sources = {self.harness_source}
                    self.seen_runtime_rejection_fingerprints: set[str] = set()
                    # One source-grounded audit is the normal budget. Permit one
                    # syntax-only retry when its own replacement did not parse;
                    # never spend another model call on semantic disagreement.
                    for self.runtime_audit_attempt in range(1, 3):
                        self.runtime_audit_stage = (
                            _deps._build_ephemeral_harness_audit_stage(
                                behavior_rows=_deps._expanded_ephemeral_behavior_rows(
                                    self.implementation_plan,
                                    generated_files=self.generated_files,
                                ),
                                generated_files=self.generated_files,
                                harness_source=self.runtime_audit_source,
                                known_issues=self.runtime_audit_known_issues,
                            )
                        )
                        self.runtime_audit_response, self.runtime_audit_timing = (
                            _deps._query_stage(
                                self.runtime_audit_stage,
                                selected_model=self.selected_model,
                                settings=self.settings,
                                timeout=self.timeout,
                            )
                        )
                        self.runtime_audit_timing.update(
                            {
                                "attempt": self.attempt,
                                "strategy_attempt": self.runtime_audit_attempt,
                                "stage": "ephemeral_behavior_harness_runtime_audit",
                            }
                        )
                        self.timings.append(self.runtime_audit_timing)
                        self.runtime_audit_issues, self.runtime_audit_repairs = (
                            _deps._parse_ephemeral_harness_audit(
                                self.runtime_audit_response,
                                accept_validator_repairs=True,
                            )
                        )
                        self.allowed_runtime_test_names = set(
                            self.required_harness_test_names
                        )
                        self.runtime_audit_repairs = [
                            repair
                            for repair in self.runtime_audit_repairs
                            if str(repair.get("test") or "")
                            in self.allowed_runtime_test_names
                        ]
                        if self.status_callback:
                            self.status_callback(
                                f"Runtime disposable audit attempt {self.runtime_audit_attempt} returned {len(self.runtime_audit_issues)} issue(s) and {len(self.runtime_audit_repairs)} exact test-method replacement(s)."
                            )
                        if not self.runtime_audit_repairs:
                            self.runtime_audit_known_issues = (
                                self.runtime_audit_issues
                                or self.runtime_audit_known_issues
                            )
                            break
                        (
                            self.repaired_harness_source,
                            self.runtime_audit_apply_errors,
                        ) = _deps._apply_ephemeral_harness_repairs(
                            self.runtime_audit_source,
                            self.runtime_audit_repairs,
                            generated_files=self.generated_files,
                        )
                        if not self.runtime_audit_apply_errors:
                            self.normalized_harness = _deps._normalize_generated_files(
                                [
                                    (
                                        self.ephemeral_validation_path,
                                        "",
                                        self.repaired_harness_source,
                                    )
                                ],
                                project_root=self.root,
                                request_prompt=self.prompt,
                            )
                            self.repaired_harness_source = self.normalized_harness[0][2]
                            self.repaired_harness_source, post_audit_oracle_notes = (
                                _deps._repair_ephemeral_literal_oracles(
                                    self.repaired_harness_source,
                                    self.prompt,
                                    _deps._expanded_ephemeral_behavior_rows(
                                        self.implementation_plan,
                                        generated_files=self.generated_files,
                                    ),
                                )
                            )
                            if post_audit_oracle_notes and self.status_callback:
                                self.status_callback(
                                    "Corrected source-grounded disposable oracles after runtime audit: "
                                    + "; ".join(post_audit_oracle_notes)
                                )
                            (
                                self.repaired_harness_source,
                                self.binding_restore_errors,
                            ) = _deps._parse_ephemeral_behavior_harness(
                                self.repaired_harness_source,
                                self.required_behavior_ids,
                                self.required_harness_test_names,
                            )
                            self.runtime_audit_apply_errors.extend(
                                self.binding_restore_errors
                            )
                            self.runtime_audit_apply_errors.extend(
                                _deps._ephemeral_harness_call_graph_errors(
                                    self.repaired_harness_source,
                                    self.generated_files,
                                    request_prompt=self.prompt,
                                )
                            )
                            self.runtime_audit_apply_errors.extend(
                                _deps._ephemeral_harness_behavior_contract_errors(
                                    self.repaired_harness_source,
                                    _deps._expanded_ephemeral_behavior_rows(
                                        self.implementation_plan,
                                        generated_files=self.generated_files,
                                    ),
                                    generated_files=self.generated_files,
                                    request_prompt=self.prompt,
                                )
                            )
                            if self.runtime_audit_apply_errors:
                                (
                                    self.repaired_harness_source,
                                    self.indirect_owner_repairs,
                                ) = _deps._repair_ephemeral_indirect_owner_invocations(
                                    self.repaired_harness_source,
                                    self.runtime_audit_apply_errors,
                                    generated_files=self.generated_files,
                                )
                                if self.indirect_owner_repairs:
                                    self.runtime_audit_apply_errors = (
                                        _deps._ephemeral_harness_call_graph_errors(
                                            self.repaired_harness_source,
                                            self.generated_files,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    self.runtime_audit_apply_errors.extend(
                                        _deps._ephemeral_harness_behavior_contract_errors(
                                            self.repaired_harness_source,
                                            _deps._expanded_ephemeral_behavior_rows(
                                                self.implementation_plan,
                                                generated_files=self.generated_files,
                                            ),
                                            generated_files=self.generated_files,
                                            request_prompt=self.prompt,
                                        )
                                    )
                                    if self.status_callback:
                                        self.status_callback(
                                            "Applied deterministic exact-owner test repair: "
                                            + "; ".join(self.indirect_owner_repairs)
                                        )
                        if not self.runtime_audit_apply_errors:
                            self.audit_validation_candidate = (
                                _deps.build_project_edit_multi_file_candidate([
                                    *self.generated_files,
                                    (self.ephemeral_validation_path, "", self.repaired_harness_source),
                                ])
                            )
                            self.audit_validation_preview = (
                                _deps.preview_project_edit_agent_response(
                                    self.audit_validation_candidate,
                                    project_root=self.root,
                                    allowed_external_paths={self.ephemeral_validation_path},
                                    request_prompt=(
                                        "Run the supplied disposable unittest module as an authoritative "
                                        "validation harness. It is not an output artifact."
                                    ),
                                )
                            )
                            self.audit_validation_errors = [
                                *_deps._ephemeral_harness_behavior_contract_errors(
                                    self.repaired_harness_source,
                                    _deps._expanded_ephemeral_behavior_rows(
                                        self.implementation_plan,
                                        generated_files=self.generated_files,
                                    ),
                                    generated_files=self.generated_files,
                                    request_prompt=self.prompt,
                                ),
                                *list(self.audit_validation_preview.errors or []),
                            ]
                            if not _runtime_audit_proof_progress(
                                self.harness_preview_errors,
                                self.audit_validation_errors,
                            ):
                                self.runtime_audit_apply_errors.append(
                                    "Disposable test-method replacement made no validated proof progress."
                                )
                        if (
                            self.repaired_harness_source
                            in self.seen_runtime_audit_sources
                        ):
                            self.runtime_audit_apply_errors.append(
                                "Disposable test-method repair returned an unchanged or previously rejected harness."
                            )
                        if self.runtime_audit_apply_errors:
                            self.runtime_audit_source = self.repaired_harness_source
                            self.runtime_audit_known_issues = (
                                self.runtime_audit_apply_errors
                            )
                            self.rejection_fingerprint = _deps._checkpoint_hash(
                                {
                                    "source": self.repaired_harness_source,
                                    "issues": sorted(
                                        (
                                            str(issue)
                                            for issue in self.runtime_audit_apply_errors
                                        )
                                    ),
                                }
                            )
                            self.repeated_rejection = (
                                self.rejection_fingerprint
                                in self.seen_runtime_rejection_fingerprints
                            )
                            self.seen_runtime_rejection_fingerprints.add(
                                self.rejection_fingerprint
                            )
                            self.seen_runtime_audit_sources.add(
                                self.repaired_harness_source
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Rejected disposable test-method repair attempt {self.runtime_audit_attempt}: "
                                    + " | ".join(self.runtime_audit_apply_errors)
                                )
                            if self.repeated_rejection:
                                if self.status_callback:
                                    self.status_callback(
                                        "Equivalent disposable repair rejection reappeared; changing harness strategy without another equivalent model call."
                                    )
                                break
                            if _retry_malformed_disposable_audit(
                                self.runtime_audit_attempt,
                                self.runtime_audit_apply_errors,
                            ):
                                self.runtime_audit_known_issues = [
                                    *self.harness_preview_errors,
                                    *self.runtime_audit_apply_errors,
                                    "The previous disposable replacement was invalid Python. Return exactly one complete, parseable test method per named failure; escape embedded newlines in quoted data.",
                                ]
                                if self.status_callback:
                                    self.status_callback(
                                        "Retrying one malformed disposable test-method replacement with its syntax error; production remains frozen."
                                    )
                                continue
                            break
                        self.accepted_runtime_audit_source = (
                            self.repaired_harness_source
                        )
                        break
                    if self.accepted_runtime_audit_source:
                        self.runtime_audit_repair_counts[
                            self.runtime_audit_candidate_key
                        ] = self.runtime_audit_repair_counts.get(
                            self.runtime_audit_candidate_key, 0
                        ) + 1
                        self.harness_source = self.accepted_runtime_audit_source
                        self.harness_entry = (
                            self.ephemeral_validation_path,
                            self.harness_source,
                        )
                        self.behavior_harness_cache[self.harness_cache_key] = (
                            self.harness_entry
                        )
                        self.persist_behavior_harness(
                            self.harness_cache_key,
                            self.ephemeral_validation_path,
                            self.harness_source,
                        )
                        if self.status_callback:
                            self.status_callback(
                                "Applied exact runtime-owned disposable test-method repairs; production remains unchanged."
                            )
                        raise _WorkflowContinue()
                    if self.runtime_audit_source != self.harness_source:
                        if self.status_callback:
                            self.status_callback(
                                "Disposable test repair budget was exhausted with production unchanged; retaining the best production patch and deferring behavioral proof instead of rebuilding equivalent harnesses."
                            )
                    retained_preview = _deps.preview_project_edit_agent_response(
                        self.candidate,
                        project_root=self.root,
                        request_prompt=self.prompt,
                        behavioral_proof_deferred=True,
                    )
                    raise _WorkflowReturn(
                        _deps.ProjectEditWorkflowResult(
                            ok=False,
                            status="behavioral_proof_deferred",
                            candidate=self.candidate,
                            preview=retained_preview,
                            errors=list(self.runtime_audit_known_issues),
                            timings=self.timings,
                        )
                    )
                self.harness_quality_errors = [
                    error
                    for error in self.harness_preview_errors
                    if not str(error).startswith(
                        "Disposable generated-patch validation failed:"
                    )
                ]
                if self.harness_quality_errors:
                    self.errors.extend(self.harness_quality_errors)
                    if self.status_callback:
                        self.status_callback(
                            "Disposable harness quality failure retained for exact test-method repair: "
                            + " | ".join(self.harness_quality_errors)
                        )
                self.harness_runtime_defect = self.harness_owned_failure
                if self.harness_runtime_defect:
                    self.errors.extend(self.harness_preview_errors)
                    self.errors.append(
                        "The disposable test raised inside its own test body. Repair only the exact failing test method unless causal analysis proves a production owner."
                    )
                    if self.status_callback:
                        self.status_callback(
                            "Disposable runtime-test defect retained for exact test-method causal repair."
                        )
                elif not self.harness_quality_errors:
                    self.errors.extend(self.harness_preview_errors)
                if not self.harness_quality_errors and (
                    not self.harness_runtime_defect
                ):
                    self.persist_behavior_harness(
                        self.harness_cache_key,
                        self.ephemeral_validation_path,
                        self.harness_source,
                    )
                if self.status_callback:
                    self.status_callback(
                        "Disposable requirement tests "
                        + (
                            "passed."
                            if self.harness_preview.ok
                            and (not self.harness_preview_errors)
                            else f"reported {len(self.harness_preview_errors)} behavior or proof-coverage failure(s)."
                        )
                    )
                if self.errors and self.ephemeral_validation_path:
                    (
                        self.repaired_validation_files,
                        self.explicit_delegation_harness_repairs,
                    ) = _deps._repair_explicit_cross_file_delegation_harness(
                        self.active_validation_files,
                        harness_path=self.ephemeral_validation_path,
                        request_prompt=self.prompt,
                    )
                    self.repaired_validation_files, self.exception_type_repairs = (
                        _deps._repair_ephemeral_expected_exception_types(
                            self.repaired_validation_files,
                            self.generated_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                            request_prompt=self.prompt,
                        )
                    )
                    self.repaired_validation_files, self.host_import_repairs = (
                        _deps._repair_ephemeral_missing_host_import(
                            self.repaired_validation_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                        )
                    )
                    self.repaired_validation_files, self.progress_recorder_repairs = (
                        _deps._repair_ephemeral_progress_recorders(
                            self.repaired_validation_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                        )
                    )
                    self.repaired_validation_files, self.host_assertion_repairs = (
                        _deps._repair_ephemeral_host_and_status_assertions(
                            self.repaired_validation_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                        )
                    )
                    self.repaired_validation_files, self.unused_fixture_repairs = (
                        _deps._repair_ephemeral_unused_fixture_assignments(
                            self.repaired_validation_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                        )
                    )
                    (
                        self.repaired_validation_files,
                        self.mocked_owner_repairs,
                    ) = _deps._repair_ephemeral_mocked_production_methods(
                        self.repaired_validation_files,
                        self.errors,
                        harness_path=self.ephemeral_validation_path,
                    )
                    (
                        self.repaired_validation_files,
                        self.builtin_patch_repairs,
                    ) = _deps._repair_ephemeral_builtin_patch_targets(
                        self.repaired_validation_files,
                        self.errors,
                        harness_path=self.ephemeral_validation_path,
                    )
                    (
                        self.repaired_validation_files,
                        self.command_registry_fixture_repairs,
                    ) = _deps._repair_ephemeral_command_registry_contract_tests(
                        self.repaired_validation_files,
                        harness_path=self.ephemeral_validation_path,
                        request_prompt=self.prompt,
                        implementation_plan=self.implementation_plan,
                    )
                    (
                        self.repaired_validation_files,
                        self.mock_call_reference_repairs,
                    ) = _deps._repair_ephemeral_mock_call_reference(
                        self.repaired_validation_files,
                        self.errors,
                        harness_path=self.ephemeral_validation_path,
                    )
                    self.repaired_validation_files, self.runtime_fixture_repairs = (
                        _deps._repair_ephemeral_runtime_fixture_contracts(
                            self.repaired_validation_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                            request_prompt=self.prompt,
                            implementation_plan=self.implementation_plan,
                        )
                    )
                    self.repaired_validation_files, self.consumer_patch_repairs = (
                        _deps._repair_ephemeral_consumer_patch_targets(
                            self.repaired_validation_files,
                            harness_path=self.ephemeral_validation_path,
                            request_prompt=self.prompt,
                        )
                    )
                    self.repaired_validation_files, self.semantic_progress_repairs = (
                        _deps._repair_ephemeral_semantic_progress_proofs(
                            self.repaired_validation_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                        )
                    )
                    self.repaired_validation_files, self.combo_fixture_repairs = (
                        _deps._repair_ephemeral_invalid_combo_choices(
                            self.repaired_validation_files,
                            self.errors,
                            harness_path=self.ephemeral_validation_path,
                        )
                    )
                    self.harness_repairs = [
                        *self.explicit_delegation_harness_repairs,
                        *self.exception_type_repairs,
                        *self.host_import_repairs,
                        *self.progress_recorder_repairs,
                        *self.host_assertion_repairs,
                        *self.unused_fixture_repairs,
                        *self.mocked_owner_repairs,
                        *self.builtin_patch_repairs,
                        *self.command_registry_fixture_repairs,
                        *self.mock_call_reference_repairs,
                        *self.runtime_fixture_repairs,
                        *self.consumer_patch_repairs,
                        *self.semantic_progress_repairs,
                        *self.combo_fixture_repairs,
                    ]
                    if self.harness_repairs:
                        self.harness_source = next(
                            (
                                source
                                for path, _original, source in self.repaired_validation_files
                                if path == self.ephemeral_validation_path
                            )
                        )
                        self.harness_entry = (
                            self.ephemeral_validation_path,
                            self.harness_source,
                        )
                        self.persist_behavior_harness(
                            self.harness_cache_key,
                            self.ephemeral_validation_path,
                            self.harness_source,
                        )
                        self.active_validation_files = self.repaired_validation_files
                        if self.status_callback:
                            self.status_callback(
                                "Applied deterministic disposable harness repair: "
                                + "; ".join(self.harness_repairs)
                            )
                        raise _WorkflowContinue()
