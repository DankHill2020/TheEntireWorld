"""Project-edit workflow phase: _run_attempt_synthesize_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import (
    _WorkflowReturn,
    _WorkflowBreak,
    _WorkflowContinue,
)


def _review_finding_requires_disposable_test_repair(error: str) -> bool:
    """Return whether a semantic finding is owned by test proof.

    :param error: Source-grounded final-review finding.
    :return: True only for an explicit test-coverage category.
    """

    return bool(
        _deps.re.search(
            r"Final requirement review \[test_coverage\]",
            str(error or ""),
            flags=_deps.re.IGNORECASE,
        )
    )


def _semantic_review_finding_is_contradicted_by_source(
    error: str,
    generated_files: list[tuple[str, str, str]],
) -> bool:
    """Return whether a review accusation is disproven by exact owner AST."""

    text = str(error or "")
    owner_match = _deps.re.search(
        r"\.py:(?P<owners>[A-Za-z_][A-Za-z0-9_.]*(?:\([^)]*\))?(?:,\s*"
        r"[A-Za-z_][A-Za-z0-9_.]*(?:\([^)]*\))?)*):\s*unmet\s+R[1-9][0-9]*",
        text,
    )
    if owner_match is None:
        return False
    requested_owners = {
        _deps.re.sub(r"\([^)]*\)$", "", value.strip())
        for value in owner_match.group("owners").split(",")
        if "." in value
    }
    if not requested_owners:
        return False
    callable_nodes: dict[str, _deps.ast.AST] = {}
    class_nodes: dict[str, _deps.ast.ClassDef] = {}
    for _path, _original, source in generated_files:
        try:
            tree = _deps.ast.parse(source)
        except SyntaxError:
            continue
        for class_node in (
            node for node in tree.body if isinstance(node, _deps.ast.ClassDef)
        ):
            class_nodes[class_node.name] = class_node
            for member in class_node.body:
                if isinstance(
                    member,
                    (_deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef),
                ):
                    callable_nodes[f"{class_node.name}.{member.name}"] = member
    owners = [
        callable_nodes.get(owner)
        or (
            class_nodes.get(owner.rsplit(".", 1)[0])
            if owner.endswith(".__init__")
            else None
        )
        for owner in requested_owners
    ]
    if any(owner is None for owner in owners):
        return False

    evidence = text.split("Evidence:", 1)[-1].split("Smallest repair:", 1)[0]
    evidence_lower = evidence.casefold()
    if "lacks type hints and docstrings" in evidence_lower:
        data_owners = [
            owner for owner in owners if isinstance(owner, _deps.ast.ClassDef)
        ]
        if len(data_owners) != len(owners):
            return False
        for owner in data_owners:
            annotated_fields = {
                node.target.id
                for node in owner.body
                if isinstance(node, _deps.ast.AnnAssign)
                and isinstance(node.target, _deps.ast.Name)
            }
            docstring = _deps.ast.get_docstring(owner) or ""
            if not annotated_fields or any(
                f":param {field}:" not in docstring for field in annotated_fields
            ):
                return False
        return True
    if "not implemented" in evidence_lower:
        return all(
            any(
                isinstance(node, _deps.ast.Return)
                and node.value is not None
                for node in _deps.ast.walk(owner)
            )
            for owner in owners
        )
    if "does not increment" in evidence_lower and "return" in evidence_lower:
        owner = owners[0]
        mutates_state = any(
            isinstance(node, (_deps.ast.Assign, _deps.ast.AnnAssign, _deps.ast.AugAssign))
            and any(
                (
                    isinstance(child, _deps.ast.Attribute)
                    and isinstance(child.value, _deps.ast.Name)
                    and child.value.id == "self"
                )
                or (
                    isinstance(child, _deps.ast.Subscript)
                    and isinstance(child.value, _deps.ast.Attribute)
                    and isinstance(child.value.value, _deps.ast.Name)
                    and child.value.value.id == "self"
                )
                for child in _deps.ast.walk(node)
            )
            for node in _deps.ast.walk(owner)
        )
        returns_value = any(
            isinstance(node, _deps.ast.Return) and node.value is not None
            for node in _deps.ast.walk(owner)
        )
        return mutates_state and returns_value
    if "returns the attempt number instead" in evidence_lower:
        owner = owners[0]
        return any(
            isinstance(node, _deps.ast.Return)
            and isinstance(node.value, _deps.ast.Call)
            and (
                isinstance(node.value.func, _deps.ast.Name)
                and node.value.func.id in {"min", "max"}
                or isinstance(node.value.func, _deps.ast.Attribute)
            )
            for node in _deps.ast.walk(owner)
        )
    return False


class _ProjectEditAttemptSynthesizePhase:
    """Provide the attempt synthesize workflow phase."""

    def _run_attempt_synthesize_phase(self) -> None:
        """Run the attempt synthesize phase.

        :return: None.
        """
        if self.preview.ok and (not self.errors):
            self.current_registered_contracts = (
                _deps._verify_registered_contract_repairs(
                    self.generated_files,
                    getattr(self, "registered_contract_repairs", {}),
                    request_prompt=self.prompt,
                )
            )
            if self.current_registered_contracts:
                for self.requirement_id in (
                    _deps._registered_contract_proven_requirement_ids(
                        self.requirement_ledger,
                        self.current_registered_contracts,
                    )
                ):
                    self.semantic_proof_cache[self.requirement_id] = (
                        _deps._requirement_source_hash(
                            self.requirement_id,
                            implementation_plan=self.implementation_plan,
                            generated_files=self.generated_files,
                        )
                    )
            self.review_errors = self.final_review_cache.get(self.candidate)
            if self.review_errors is None:
                if self.ephemeral_validation_path and self.harness_source:
                    self.passed_bindings, self.binding_errors = (
                        _deps._ephemeral_behavior_bindings(self.harness_source)
                    )
                    if not self.binding_errors:
                        self.passed_behavior_ids = {
                            _deps.re.sub("__owner_\\d+$", "", behavior_id)
                            for behavior_ids in self.passed_bindings.values()
                            for behavior_id in behavior_ids
                        }
                        self.proven_requirement_ids = {
                            str(row.get("requirement_id") or "")
                            for row in _deps._approved_behavior_contract_rows(
                                self.implementation_plan
                            )
                            if str(row.get("behavior_id") or "")
                            in self.passed_behavior_ids
                            and str(row.get("requirement_id") or "")
                        }
                        if (
                            self.proven_requirement_ids
                            and getattr(self, "harness_preview", None) is not None
                            and self.harness_preview.ok
                            and not self.harness_preview.errors
                        ):
                            for self.requirement_id in self.proven_requirement_ids:
                                self.semantic_proof_cache[self.requirement_id] = (
                                    _deps._requirement_source_hash(
                                        self.requirement_id,
                                        implementation_plan=self.implementation_plan,
                                        generated_files=self.generated_files,
                                    )
                                )
                        if self.proven_requirement_ids and self.status_callback:
                            self.status_callback(
                                "Recorded executable runtime observations for "
                                + ", ".join(sorted(self.proven_requirement_ids))
                                + "; exact-owner passing assertions take precedence over weaker prose-only review."
                            )
                self.semantic_ledger = _deps._semantic_requirement_ledger(
                    self.requirement_ledger, generated_files=self.generated_files
                )
                self.local_single_file_runtime_proven = bool(
                    self.ephemeral_validation_path
                    and len(self.generated_files) == 1
                    and getattr(self, "harness_preview", None) is not None
                    and self.harness_preview.ok
                    and not self.harness_preview.errors
                    and bool(getattr(self, "proven_requirement_ids", set()))
                    and (
                        not _deps.re.search(
                            "\\b(?:unreal|maya(?:\\.cmds)?|cmds|bpy|pyfbsdk|PySide6|PySide2|PyQt6|PyQt5)(?:\\.[A-Za-z_][A-Za-z0-9_]*)+\\s*\\(",
                            self.prompt,
                        )
                    )
                )
                self.has_requested_verification_chunk = any(
                    (
                        isinstance(chunk, dict)
                        and any(
                            (
                                isinstance(requirement, dict)
                                and str(requirement.get("semantic_role") or "")
                                == "verification"
                                for requirement in chunk.get("requirements") or []
                            )
                        )
                        for chunk in self.implementation_plan.get("chunks") or []
                    )
                )
                if self.local_single_file_runtime_proven and (
                    not self.has_requested_verification_chunk
                ):
                    for self.row in self.semantic_ledger:
                        self.requirement_id = str(
                            self.row.get("id") or self.row.get("requirement_id") or ""
                        )
                        if self.requirement_id:
                            self.semantic_proof_cache[self.requirement_id] = (
                                _deps._requirement_source_hash(
                                    self.requirement_id,
                                    implementation_plan=self.implementation_plan,
                                    generated_files=self.generated_files,
                                )
                            )
                    if self.status_callback and self.semantic_ledger:
                        self.status_callback(
                            "Skipping redundant final LLM review: deterministic quality gates and the disposable single-file runtime proof cover all local semantic clauses."
                        )
                self.pending_semantic_ledger = [
                    row
                    for row in self.semantic_ledger
                    if self.semantic_proof_cache.get(
                        str(row.get("id") or row.get("requirement_id") or "")
                    )
                    != _deps._requirement_source_hash(
                        str(row.get("id") or row.get("requirement_id") or ""),
                        implementation_plan=self.implementation_plan,
                        generated_files=self.generated_files,
                    )
                ]
                if self.pending_semantic_ledger:
                    self.review_errors = []
                    self.review_protocol_failures: list[str] = []
                    self.review_batches = _deps._final_requirement_review_batches(
                        self.pending_semantic_ledger
                    )
                    if self.status_callback:
                        self.status_callback(
                            f"All currently materialized deterministic checks passed; {len(self.pending_semantic_ledger)} changed or unproven behavioral requirement(s) still require source-grounded review in {len(self.review_batches)} bounded batch(es) before this candidate can be called clean."
                        )
                    for self.batch_index, self.review_batch in enumerate(
                        self.review_batches, start=1
                    ):
                        self.batch_ids = [
                            str(row.get("id") or row.get("requirement_id") or "")
                            for row in self.review_batch
                        ]
                        self.review_files = _deps._generated_files_for_requirements(
                            self.review_batch,
                            implementation_plan=self.implementation_plan,
                            generated_files=self.generated_files,
                        )
                        self.evidence_query = "\n".join(
                            (
                                str(
                                    row.get("text")
                                    or row.get("requirement")
                                    or row.get("description")
                                    or ""
                                )
                                for row in self.review_batch
                            )
                        )
                        self.grounded_review_evidence = (
                            _deps._federated_symbol_evidence_context(
                                self.evidence_query,
                                project_root=self.root,
                                generated_files=self.review_files,
                            )
                        )
                        self.review_stage = _deps._build_final_requirement_review_stage(
                            prompt=self.prompt,
                            requirement_ledger=self.review_batch,
                            generated_files=self.review_files,
                            project_root=self.root,
                            grounded_evidence=self.grounded_review_evidence,
                        )
                        if self.status_callback:
                            self.status_callback(
                                f"Reviewing semantic batch {self.batch_index}/{len(self.review_batches)}: "
                                + ", ".join(self.batch_ids)
                            )
                        self.review_response, self.retry_timing = _deps._query_stage(
                            self.review_stage,
                            selected_model=self.selected_model,
                            settings=self.settings,
                            timeout=self.timeout,
                        )
                        self.retry_timing.update(
                            {
                                "attempt": self.attempt,
                                "stage": "final_requirement_review",
                                "batch_index": self.batch_index,
                                "batch_count": len(self.review_batches),
                                "requirement_ids": self.batch_ids,
                            }
                        )
                        self.timings.append(self.retry_timing)
                        self.batch_errors = _deps._parse_final_requirement_review(
                            self.review_response,
                            requirement_ledger=self.review_batch,
                            generated_files=self.review_files,
                        )
                        self.review_protocol_markers = (
                            "was not valid JSON",
                            "omitted its required issues list",
                            "omitted per-requirement coverage evidence",
                            "did not inspect requirement IDs",
                            "supplied no obligation evidence",
                            "supplied malformed obligation evidence",
                            "supplied ungrounded obligation evidence",
                            "marked ",
                            "contradicted itself",
                        )
                        if self.batch_errors and all(
                            (
                                any(
                                    (
                                        marker in error
                                        for marker in self.review_protocol_markers
                                    )
                                )
                                for error in self.batch_errors
                            )
                        ):
                            if self.status_callback:
                                self.status_callback(
                                    f"Semantic batch {self.batch_index} returned a protocol-invalid response; retrying only this batch with a larger output allowance."
                                )
                            self.expanded_review_stage = _deps.replace(
                                self.review_stage,
                                num_predict=max(
                                    self.review_stage.num_predict + 600,
                                    self.review_stage.num_predict * 2,
                                ),
                            )
                            self.review_response, self.retry_timing = (
                                _deps._query_stage(
                                    self.expanded_review_stage,
                                    selected_model=self.selected_model,
                                    settings=self.settings,
                                    timeout=self.timeout,
                                    suffix="\n\nThe previous response failed protocol:\n- "
                                    + "\n- ".join(self.batch_errors)
                                    + "\nReturn one compact JSON object. Include exactly one coverage row for each supplied ID, concise checks, and an issues array. Do not repeat requirement text.",
                                )
                            )
                            self.retry_timing.update(
                                {
                                    "attempt": self.attempt,
                                    "stage": "final_requirement_review_protocol_retry",
                                    "batch_index": self.batch_index,
                                    "batch_count": len(self.review_batches),
                                    "requirement_ids": self.batch_ids,
                                    "strategy": "expanded_batch_output_allowance",
                                }
                            )
                            self.timings.append(self.retry_timing)
                            self.batch_errors = _deps._parse_final_requirement_review(
                                self.review_response,
                                requirement_ledger=self.review_batch,
                                generated_files=self.review_files,
                            )
                        self.protocol_batch_errors = [
                            error
                            for error in self.batch_errors
                            if any(
                                (
                                    marker in error
                                    for marker in self.review_protocol_markers
                                )
                            )
                        ]
                        self.semantic_batch_errors = [
                            error
                            for error in self.batch_errors
                            if error not in self.protocol_batch_errors
                        ]
                        if self.protocol_batch_errors and self.semantic_batch_errors:
                            self.review_errors.extend(self.semantic_batch_errors)
                            if self.status_callback:
                                self.status_callback(
                                    "Separated mixed semantic results: grounded code issues continue while reviewer-protocol defects are recorded without recursive re-review."
                                )
                            self.review_protocol_failures.append(
                                "Reviewer returned mixed semantic and protocol-invalid findings for "
                                + ", ".join(self.batch_ids)
                            )
                            continue
                        self.protocol_only_failure = bool(
                            self.batch_errors
                            and all(
                                (
                                    any(
                                        (
                                            marker in error
                                            for marker in self.review_protocol_markers
                                        )
                                    )
                                    for error in self.batch_errors
                                )
                            )
                        )
                        if self.protocol_only_failure and len(self.review_batch) > 1:
                            self.review_protocol_failures.append(
                                "Semantic reviewer remained protocol-invalid for bounded batch "
                                + ", ".join(self.batch_ids)
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Semantic batch {self.batch_index} remained protocol-invalid after its focused retry; recording the evaluator failure without recursive subdivision or code repair."
                                )
                            continue
                        if self.protocol_only_failure:
                            self.single_requirement_id = self.batch_ids[0]
                            self.final_protocol_stage = _deps.replace(
                                self.review_stage,
                                num_ctx=max(self.review_stage.num_ctx, 12288),
                                num_predict=max(
                                    self.review_stage.num_predict * 2, 2400
                                ),
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Escalating the single-requirement semantic review for {self.single_requirement_id}; source repair remains paused until review JSON is valid."
                                )
                            self.review_response, self.final_protocol_timing = (
                                _deps._query_stage(
                                    self.final_protocol_stage,
                                    selected_model=_deps._causal_repair_escalation_model(
                                        self.settings, self.selected_model
                                    ),
                                    settings=self.settings,
                                    timeout=self.timeout,
                                    suffix="\n\nReview only the one supplied requirement. Return one compact JSON object with one coverage row and an issues array. Use the requirement ID as canonical identity and do not repeat its text.",
                                )
                            )
                            self.final_protocol_timing.update(
                                {
                                    "attempt": self.attempt,
                                    "stage": "final_requirement_review_single_protocol_escalation",
                                    "batch_index": self.batch_index,
                                    "requirement_ids": self.batch_ids,
                                    "strategy": "single_requirement_stronger_model",
                                }
                            )
                            self.timings.append(self.final_protocol_timing)
                            self.batch_errors = _deps._parse_final_requirement_review(
                                self.review_response,
                                requirement_ledger=self.review_batch,
                                generated_files=self.review_files,
                            )
                            self.protocol_only_failure = bool(
                                self.batch_errors
                                and all(
                                    (
                                        any(
                                            (
                                                marker in error
                                                for marker in self.review_protocol_markers
                                            )
                                        )
                                        for error in self.batch_errors
                                    )
                                )
                            )
                            if self.protocol_only_failure:
                                self.review_protocol_failures.append(
                                    f"{self.single_requirement_id} owned by "
                                    + ", ".join(
                                        (
                                            _deps.Path(path).name
                                            for path, _original, _source in self.review_files
                                        )
                                    )
                                    + ": semantic reviewer remained protocol-invalid after bounded batch, expanded batch, subdivision, and single-requirement model escalation."
                                )
                                continue
                        self.review_errors.extend(self.batch_errors)
                        for (
                            self.requirement_id
                        ) in _deps._clean_final_review_requirement_ids(
                            self.review_response, self.review_batch
                        ):
                            self.semantic_proof_cache[self.requirement_id] = (
                                _deps._requirement_source_hash(
                                    self.requirement_id,
                                    implementation_plan=self.implementation_plan,
                                    generated_files=self.generated_files,
                                )
                            )
                else:
                    self.review_errors = []
                    self.review_protocol_failures = []
                if self.review_protocol_failures:
                    if self.status_callback:
                        self.status_callback(
                            "Semantic review protocol remains unresolved for "
                            + ", ".join(self.review_protocol_failures)
                            + "; code repair was not invoked."
                        )
                    raise _WorkflowReturn(
                        _deps.ProjectEditWorkflowResult(
                            ok=False,
                            status="semantic_review_protocol_failed",
                            candidate=self.candidate,
                            preview=self.preview,
                            errors=[
                                "Semantic reviewer protocol failure is not a source-code failure. No full-file or symbol repair was attempted.",
                                *self.review_protocol_failures,
                            ],
                            timings=self.timings,
                            implementation_plan=self.implementation_plan,
                            approval_id=self.approval_id,
                        )
                    )
                self.stale_review_errors = [
                    error
                    for error in self.review_errors
                    if _semantic_review_finding_is_contradicted_by_source(
                        error,
                        self.generated_files,
                    )
                ]
                if self.stale_review_errors:
                    self.review_errors = [
                        error
                        for error in self.review_errors
                        if error not in self.stale_review_errors
                    ]
                    if self.status_callback:
                        self.status_callback(
                            "Discarded semantic-review finding(s) contradicted by "
                            "the exact owner AST: "
                            + " | ".join(self.stale_review_errors)
                        )
                self.final_review_cache[self.candidate] = self.review_errors
                if self.status_callback:
                    self.status_callback(
                        f"Request-to-code review finished with {len(self.review_errors)} remaining semantic requirement issue(s)."
                    )
            self.semantic_harness_proof_errors: list[str] = []
            if self.review_errors and self.harness_source:
                self.behavior_bindings, self.binding_errors = (
                    _deps._ephemeral_behavior_bindings(self.harness_source)
                )
                if not self.binding_errors and self.behavior_bindings:
                    self.behavior_rows = _deps._expanded_ephemeral_behavior_rows(
                        self.implementation_plan, generated_files=self.generated_files
                    )
                    self.behavior_requirement_ids = {
                        str(row.get("behavior_id") or ""): str(
                            row.get("requirement_id") or ""
                        )
                        for row in self.behavior_rows
                    }
                    try:
                        self.harness_tree = _deps.ast.parse(self.harness_source)
                    except SyntaxError:
                        self.harness_tree = None
                    self.test_symbols: dict[str, str] = {}
                    if self.harness_tree is not None:
                        for self.class_node in (
                            node
                            for node in _deps.ast.walk(self.harness_tree)
                            if isinstance(node, _deps.ast.ClassDef)
                        ):
                            for self.member in self.class_node.body:
                                if isinstance(
                                    self.member,
                                    (_deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef),
                                ) and self.member.name.startswith("test_"):
                                    self.test_symbols[self.member.name] = (
                                        f"{self.class_node.name}.{self.member.name}"
                                    )
                    self.seen_semantic_tests: set[tuple[str, str]] = set()
                    for self.review_error in self.review_errors:
                        if not _review_finding_requires_disposable_test_repair(
                            self.review_error
                        ):
                            continue
                        self.review_requirement_ids = set(
                            _deps.re.findall("\\bR[1-9][0-9]*\\b", self.review_error)
                        )
                        if not self.review_requirement_ids:
                            continue
                        for (
                            self.test_name,
                            self.behavior_ids,
                        ) in self.behavior_bindings.items():
                            self.matched_behavior_ids = [
                                behavior_id
                                for behavior_id in self.behavior_ids
                                if self.behavior_requirement_ids.get(behavior_id)
                                in self.review_requirement_ids
                            ]
                            if not self.matched_behavior_ids:
                                continue
                            self.test_symbol = self.test_symbols.get(
                                self.test_name, self.test_name
                            )
                            self.proof_key = (
                                self.test_symbol,
                                ",".join(sorted(self.matched_behavior_ids)),
                            )
                            if self.proof_key in self.seen_semantic_tests:
                                continue
                            self.seen_semantic_tests.add(self.proof_key)
                            self.semantic_harness_proof_errors.append(
                                f"Generated test methods need stronger behavioral proof: {self.test_symbol}; {self.test_symbol} does not expose the post-build semantic finding for approved behavior "
                                + ", ".join(sorted(self.matched_behavior_ids))
                                + ". Strengthen only this disposable test so its actions and assertions execute every approved expected observation. Semantic finding: "
                                + self.review_error
                            )
            self.errors.extend(self.review_errors)
            self.errors.extend(self.semantic_harness_proof_errors)
        if self.errors and self.status_callback:
            self.status_callback(
                "Quality failure evidence: "
                + _deps._compact_validation_error_summary(self.errors)
            )
        self.timings.append(
            {
                "stage": (
                    "final_quality_review"
                    if self.attempt == 0
                    else "focused_repair_validation"
                ),
                "label": "Validating complete multi-file candidate",
                "model": "deterministic",
                "attempt": self.attempt,
                "elapsed_ms": (_deps.time.perf_counter() - self.validation_started)
                * 1000.0,
            }
        )
        if self.status_callback:
            self.status_callback(
                f"Candidate validation finished in {self.timings[-1]['elapsed_ms']:.0f}ms with {len(self.errors)} remaining issue(s)."
            )
        if self.preview.ok and (not self.errors):
            if self.dry_run:
                _deps._save_workflow_checkpoint(
                    self.root,
                    self.prompt,
                    self.selected_model,
                    self.generated_files,
                    {
                        "attempt": self.attempt,
                        "final_review_fingerprint": _deps._candidate_checkpoint_fingerprint(
                            self.candidate
                        ),
                        "final_review_errors": [],
                        "semantic_proofs": [
                            [requirement_id, source_hash]
                            for requirement_id, source_hash in sorted(
                                self.semantic_proof_cache.items()
                            )
                        ],
                        "chunk_coverage": self.chunk_coverage,
                        "complete": True,
                    },
                    implementation_plan_hash=self.approval_id,
                )
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=True,
                        status="preview_ok",
                        candidate=self.candidate,
                        preview=self.preview,
                        timings=self.timings,
                    )
                )
            self.applied = _deps.apply_project_edit_agent_response(
                self.candidate,
                project_root=self.root,
                validate=True,
                request_prompt=self.prompt,
                behavioral_proof_satisfied=True,
            )
            if self.applied.ok:
                _deps._clear_workflow_checkpoint(
                    self.root, self.prompt, self.selected_model
                )
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=self.applied.ok,
                    status="ok" if self.applied.ok else "apply_failed",
                    candidate=self.candidate,
                    preview=self.applied,
                    errors=list(self.applied.errors or []),
                    timings=self.timings,
                )
            )
        self.validation_snapshot_errors = list(self.errors)
        self.pre_deterministic_files = list(self.generated_files)
        self.pre_deterministic_candidate_fingerprint = (
            _deps._candidate_checkpoint_fingerprint(self.candidate)
        )
        self.quality_focus, self.errors = _deps._focused_repair_quality_errors(
            self.errors
        )
        if self.status_callback:
            self.status_callback(
                f"Repair pass focus: {self.quality_focus}; {len(self.errors)} owning failure(s)."
            )
        self.generated_files, self.local_quality_repairs = (
            _deps._repair_standardized_local_quality_issues(
                self.generated_files, [*self.validation_snapshot_errors, *self.errors]
            )
        )
        self.generated_files, self.contract_surface_repairs = (
            _deps._repair_requested_python_contract_surface(
                self.generated_files,
                self.validation_snapshot_errors,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.inferred_type_repairs = (
            _deps._repair_inferred_collection_type_hints(self.generated_files)
        )
        self.generated_files, self.stable_order_proof_repairs = (
            _deps._repair_missing_stable_order_self_test_proof(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.unreal_signature_repairs = (
            _deps._repair_authoritative_unreal_call_signatures(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.unreal_property_repairs = (
            _deps._repair_official_unreal_editor_property_names(
                self.generated_files,
                self.validation_snapshot_errors,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.host_result_repairs = (
            _deps._repair_host_result_contracts(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.asset_operation_repairs = (
            _deps._repair_asset_operation_pipeline_contract(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.cross_file_delegation_repairs = (
            _deps._repair_explicit_cross_file_delegation(
                self.generated_files,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.unreal_enum_repairs = (
            _deps._repair_official_unreal_enum_members(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.integer_progress_repairs = (
            _deps._repair_integer_progress_contracts(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.ui_reconstruction_repairs = (
            _deps._repair_misplaced_ui_attribute_reconstruction(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.include_state_repairs = (
            _deps._repair_include_state_checkbox_consumption(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.local_signal_repairs = (
            _deps._repair_local_qt_signal_scaffolding(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.worker_progress_repairs = (
            _deps._repair_qt_worker_progress_injection(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.worker_progress_routing_repairs = (
            _deps._repair_worker_constructor_progress_routing(self.generated_files)
        )
        self.generated_files, self.locked_public_surface_repairs = (
            _deps._repair_locked_undeclared_public_methods(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.cross_thread_callback_repairs = (
            _deps._repair_cross_thread_callback_routing(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.unretained_worker_repairs = (
            _deps._repair_unretained_worker_dispatch(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.nested_worker_operation_repairs = (
            _deps._repair_nested_worker_operation_protocol(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.entry_point_owner_repairs = (
            _deps._repair_entry_point_owner_reference(
                self.generated_files,
                self.validation_snapshot_errors,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.delegated_launcher_repairs = (
            _deps._repair_unreachable_delegated_launcher(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.delegated_launcher_repairs)
        self.generated_files, self.unresolved_signal_repairs = (
            _deps._repair_unresolved_signal_connections(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.unresolved_signal_repairs)
        self.generated_files, self.unreachable_private_repairs = (
            _deps._repair_unreferenced_private_helpers(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.unreachable_private_repairs)
        self.generated_files, self.cross_file_import_repairs = (
            _deps._repair_missing_cross_file_imports(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.cross_file_import_repairs)
        self.generated_files, self.dependency_method_owner_repairs = (
            _deps._repair_locked_dependency_method_ownership(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.dependency_method_owner_repairs)
        self.generated_files, self.verified_worker_repairs = (
            _deps._repair_verified_qt_worker_integration(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.verified_worker_repairs)
        self.generated_files, self.result_consumer_repairs = (
            _deps._repair_qt_result_consumer_contract(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.result_consumer_repairs)
        self.generated_files, self.mapping_record_repairs = (
            _deps._repair_mapping_record_attribute_access(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.mapping_record_repairs)
        self.generated_files, self.omitted_state_repairs = (
            _deps._repair_omitted_selective_states(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.entry_point_owner_repairs.extend(self.omitted_state_repairs)
        self.generated_files, self.selective_record_repairs = (
            _deps._repair_selective_record_append(
                self.generated_files,
                [
                    error
                    for error in self.validation_snapshot_errors
                    if "selective return predicate omits requested state(s):"
                    not in str(error)
                ],
            )
        )
        self.generated_files, self.initial_progress_repairs = (
            _deps._repair_initial_progress_boundary(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.missing_path_repairs = (
            _deps._repair_missing_path_state(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.worker_release_repairs = (
            _deps._repair_worker_terminal_release(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.worker_finished_cleanup_repairs = (
            _deps._repair_required_worker_finished_cleanup(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.exact_handler_routing_repairs = (
            _deps._repair_unreachable_qt_handler_routing(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.worker_lifecycle_repairs = (
            _deps._repair_qt_worker_lifecycle_ownership(self.generated_files)
        )
        self.generated_files, self.duplicate_signal_repairs = (
            _deps._dedupe_constructor_signal_connections(self.generated_files)
        )
        self.generated_files, self.normalized_mapping_repairs = (
            _deps._repair_normalized_literal_mapping_keys(self.generated_files)
        )
        self.generated_files, self.mapping_assignment_repairs = (
            _deps._repair_contract_proven_mapping_assignment_keys(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.order_operation_repairs = (
            _deps._repair_contract_proven_order_operations(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.defensive_copy_proof_repairs = (
            _deps._repair_verification_defensive_copy_proof(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.validation_order_repairs = (
            _deps._repair_input_validation_before_host_side_effects(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.qt_progress_repairs = (
            _deps._repair_qt_progress_surface_contracts(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.exact_result_repairs = (
            _deps._repair_exactly_one_host_result_contracts(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.bool_rejection_repairs = (
            _deps._repair_explicit_bool_rejections(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.finally_cleanup_repairs = (
            _deps._repair_required_finally_cleanup(
                self.generated_files,
                self.validation_snapshot_errors,
            )
        )
        self.entry_point_owner_repairs.extend(self.finally_cleanup_repairs)
        self.generated_files, self.pre_mutation_guard_repairs = (
            _deps._repair_pre_mutation_rejection_guards(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.limit_boundary_repairs = (
            _deps._repair_reached_limit_off_by_one(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.recursive_mapping_repairs = (
            _deps._repair_recursive_mapping_contracts(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.generated_files, self.dependency_batch_repairs = (
            _deps._repair_dependency_execution_batches(
                self.generated_files,
                self.validation_snapshot_errors,
                request_prompt=self.prompt,
            )
        )
        self.generated_files, self.constructor_state_repairs = (
            _deps._repair_missing_constructor_state(
                self.generated_files,
                self.validation_snapshot_errors,
            )
        )
        self.generated_files, self.final_cross_file_dependency_repairs = (
            _deps._repair_missing_cross_file_imports(
                self.generated_files, self.validation_snapshot_errors
            )
        )
        self.deterministic_contract_repairs = [
            *self.local_quality_repairs,
            *self.contract_surface_repairs,
            *self.inferred_type_repairs,
            *self.stable_order_proof_repairs,
            *self.unreal_signature_repairs,
            *self.unreal_property_repairs,
            *self.host_result_repairs,
            *self.asset_operation_repairs,
            *self.cross_file_delegation_repairs,
            *self.unreal_enum_repairs,
            *self.integer_progress_repairs,
            *self.ui_reconstruction_repairs,
            *self.include_state_repairs,
            *self.local_signal_repairs,
            *self.worker_progress_repairs,
            *self.worker_progress_routing_repairs,
            *self.locked_public_surface_repairs,
            *self.cross_thread_callback_repairs,
            *self.unretained_worker_repairs,
            *self.nested_worker_operation_repairs,
            *self.entry_point_owner_repairs,
            *self.selective_record_repairs,
            *self.initial_progress_repairs,
            *self.missing_path_repairs,
            *self.worker_release_repairs,
            *self.worker_finished_cleanup_repairs,
            *self.exact_handler_routing_repairs,
            *self.worker_lifecycle_repairs,
            *self.duplicate_signal_repairs,
            *self.normalized_mapping_repairs,
            *self.mapping_assignment_repairs,
            *self.order_operation_repairs,
            *self.defensive_copy_proof_repairs,
            *self.validation_order_repairs,
            *self.qt_progress_repairs,
            *self.exact_result_repairs,
            *self.bool_rejection_repairs,
            *self.pre_mutation_guard_repairs,
            *self.limit_boundary_repairs,
            *self.recursive_mapping_repairs,
            *self.dependency_batch_repairs,
            *self.constructor_state_repairs,
            *self.final_cross_file_dependency_repairs,
        ]
        if self.deterministic_contract_repairs:
            self.generated_files = _deps._normalize_generated_files(
                self.generated_files, project_root=self.root, request_prompt=self.prompt
            )
            self.deterministic_after_errors = _deps._repair_phase_validation_errors(
                self.generated_files,
                implementation_plan=self.implementation_plan,
                project_root=self.root,
                request_prompt=self.prompt,
            )
            self.before_findings = _deps._validation_finding_map(
                self.validation_snapshot_errors, self.root
            )
            self.after_findings = _deps._validation_finding_map(
                self.deterministic_after_errors, self.root
            )
            from reasoning_runtime import ConvergencePolicy, ValidationFinding

            self.ConvergencePolicy = ConvergencePolicy
            self.ValidationFinding = ValidationFinding
            self.protected_markers = (
                "approved callable",
                "approved class",
                "approved helper declaration",
                "approved helper method",
                "approved method",
                "approved module entry point",
                "approved public symbol",
                "approved signal",
                "is missing",
                "syntax",
            )
            self.repaired_candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            self.convergence_decision = self.ConvergencePolicy().evaluate(
                (
                    self.ValidationFinding(
                        category="project_edit", message=message, fingerprint=str(key)
                    )
                    for key, message in self.before_findings.items()
                ),
                (
                    self.ValidationFinding(
                        category="project_edit",
                        message=message,
                        fingerprint=str(key),
                        metadata={
                            "protected": any(
                                (
                                    marker in message.casefold()
                                    for marker in self.protected_markers
                                )
                            )
                        },
                    )
                    for key, message in self.after_findings.items()
                ),
                candidate_changed=_deps._candidate_checkpoint_fingerprint(
                    self.repaired_candidate
                )
                != self.pre_deterministic_candidate_fingerprint,
            )
            self.latent_quality_transition = bool(
                self.before_findings
                and not (set(self.before_findings) & set(self.after_findings))
                and self.after_findings
                and all(
                    str(message).startswith(
                        (
                            "Generated Python presentation defects:",
                            "Requested complete type hints are invalid or missing:",
                            "Requested useful docstrings are too vague:",
                            "Requested docstrings are missing:",
                        )
                    )
                    for message in self.after_findings.values()
                )
            )
            if (
                not self.convergence_decision.accepted
                and not self.latent_quality_transition
            ):
                self.generated_files = self.pre_deterministic_files
                self.errors = list(self.validation_snapshot_errors)
                if self.status_callback:
                    self.status_callback(
                        f"Rejected deterministic repair transaction ({self.convergence_decision.summary}); retained the previous candidate."
                    )
                self.deterministic_contract_repairs = []
            elif (
                not self.convergence_decision.accepted
                and self.latent_quality_transition
                and self.status_callback
            ):
                self.status_callback(
                    "Accepted deterministic repair after it resolved every current "
                    "blocker and revealed only downstream annotation/docstring "
                    "findings on the next validation layer."
                )
            if (
                self.deterministic_contract_repairs
                and _deps._candidate_checkpoint_fingerprint(self.repaired_candidate)
                != self.pre_deterministic_candidate_fingerprint
            ):
                self.candidate = self.repaired_candidate
                if self.backoff_tracker_repairs and (
                    _deps._verify_backoff_tracker_contract(
                        self.generated_files,
                        request_prompt=self.prompt,
                    )
                ):
                    for self.requirement_row in self.requirement_ledger:
                        self.requirement_id = str(
                            self.requirement_row.get("id")
                            or self.requirement_row.get("requirement_id")
                            or ""
                        )
                        if self.requirement_id:
                            self.semantic_proof_cache[self.requirement_id] = (
                                _deps._requirement_source_hash(
                                    self.requirement_id,
                                    implementation_plan=self.implementation_plan,
                                    generated_files=self.generated_files,
                                )
                            )
                    if self.status_callback:
                        self.status_callback(
                            "Recorded isolated executable proof for the complete "
                            "compiled backoff contract."
                        )
                if self.status_callback:
                    self.status_callback(
                        "Applied deterministic contract-surface repair: "
                        + "; ".join(self.deterministic_contract_repairs)
                    )
                raise _WorkflowContinue()
            if self.status_callback:
                self.status_callback(
                    "Deterministic repair proposed no observable code change; falling through to the exact owner repair strategy."
                )
        self.generated_files, self.patch_target_repairs = (
            _deps._repair_invalid_patch_targets(
                self.generated_files, self.errors, self.root
            )
        )
        self.generated_files, self.nested_lock_repairs = (
            _deps._repair_nested_non_reentrant_locks(self.generated_files, self.errors)
        )
        self.generated_files, self.command_registry_repairs = (
            _deps._repair_shared_command_registry(self.generated_files, self.errors)
        )
        self.generated_files, self.missing_sync_repairs = (
            _deps._repair_missing_synchronization_boundaries(
                self.generated_files, self.errors
            )
        )
        self.generated_files, self.dataclass_repairs = (
            _deps._repair_unrequested_frozen_dataclass(
                self.generated_files, self.errors, self.prompt
            )
        )
        self.generated_files, self.verified_api_repairs = (
            _deps._repair_verified_qt_runtime_api(self.generated_files, self.errors)
        )
        self.generated_files, self.overlay_repairs = (
            _deps._repair_screen_overlay_capture_order(
                self.generated_files, self.errors
            )
        )
        self.generated_files, self.import_surface_repairs = (
            _deps._repair_proven_import_surface(
                self.generated_files,
                self.errors,
                self.prompt,
                self.root,
                verified_import_statements=[
                    str(item.get("import_statement") or "")
                    for chunk in self.implementation_plan.get("chunks") or []
                    if isinstance(chunk, _deps.Mapping)
                    for item in chunk.get("evidence") or []
                    if isinstance(item, _deps.Mapping)
                    and (
                        bool(item.get("selected_for_generation"))
                        or bool(item.get("dependency_for_selected"))
                    )
                    and str(item.get("import_statement") or "")
                ],
            )
        )
        self.generated_files, self.host_binding_repair = (
            _deps._repair_unbound_host_test_binding(
                self.generated_files, errors=self.errors, targets=[]
            )
        )
        self.generated_files, self.unused_binding_repairs = (
            _deps._repair_unused_test_bindings(self.generated_files, self.errors)
        )
        self.generated_files, self.undefined_mock_repairs = (
            _deps._repair_undefined_test_mock_bindings(
                self.generated_files, self.errors
            )
        )
        self.deterministic_repairs = [
            *self.patch_target_repairs,
            *self.nested_lock_repairs,
            *self.command_registry_repairs,
            *self.missing_sync_repairs,
            *self.dataclass_repairs,
            *self.verified_api_repairs,
            *self.overlay_repairs,
            *self.import_surface_repairs,
            *([self.host_binding_repair] if self.host_binding_repair else []),
            *self.unused_binding_repairs,
            *self.undefined_mock_repairs,
        ]
        if self.deterministic_repairs:
            self.generated_files = _deps._normalize_generated_files(
                self.generated_files, project_root=self.root, request_prompt=self.prompt
            )
            self.repaired_candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            if (
                _deps._candidate_checkpoint_fingerprint(self.repaired_candidate)
                != self.pre_deterministic_candidate_fingerprint
            ):
                self.candidate = self.repaired_candidate
                if self.status_callback:
                    self.status_callback(
                        "Applied verified runtime API repair: "
                        + "; ".join(self.deterministic_repairs)
                    )
                raise _WorkflowContinue()
            if self.status_callback:
                self.status_callback(
                    "Verified runtime repair proposed no observable code change; falling through to the exact owner repair strategy."
                )
        self.generated_files, self.partial_result_repairs = (
            _deps._repair_dropped_partial_iterable_result(
                self.generated_files, self.errors
            )
        )
        if self.partial_result_repairs:
            if self.status_callback:
                self.status_callback(
                    "Applied deterministic runtime repair: "
                    + "; ".join(self.partial_result_repairs)
                )
            self.generated_files = _deps._normalize_generated_files(
                self.generated_files, project_root=self.root, request_prompt=self.prompt
            )
            self.candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            raise _WorkflowContinue()
        self.signature = _deps.project_edit_validation_failure_signature(self.errors)
        self.causal_changed_owner_key: tuple[str, str] | None = None
        if self.pending_symbol_progress_check is not None:
            (
                self.pending_path,
                self.pending_symbol,
                self.prior_signature,
                self.pending_model,
            ) = self.pending_symbol_progress_check
            self.causal_changed_owner_key = (self.pending_path, self.pending_symbol)
            if self.signature == self.prior_signature:
                self.pending_key = (self.pending_path, self.pending_symbol)
                self.strong_model = _deps._strong_task_model(self.selected_model)
                if (
                    self.pending_model.casefold() != self.strong_model.casefold()
                    and self.compact_callable_attempts.get(self.pending_key, 0) < 2
                ):
                    if self.status_callback:
                        self.status_callback(
                            f"Accepted compact repair for {self.pending_symbol} did not clear its validation fingerprint; retrying that exact callable once with refreshed failure evidence."
                        )
                elif self.pending_model.casefold() != self.strong_model.casefold():
                    self.strong_callable_symbols.add(self.pending_key)
                    if self.status_callback:
                        self.status_callback(
                            f"Accepted compact repair for {self.pending_symbol} did not clear its validation fingerprint; escalating that exact callable from {self.pending_model} to {self.strong_model}."
                        )
                elif self.signature_repetitions.get(self.signature, 0) < 2:
                    if self.status_callback:
                        self.status_callback(
                            f"Accepted strong-model repair for {self.pending_symbol} changed the owned source but left a residual validation failure; retrying that exact callable once with the refreshed, smaller failure snapshot."
                        )
                else:
                    self.stalled_callable_symbols.add(self.pending_key)
                    if self.status_callback:
                        self.status_callback(
                            f"Accepted strong-model repair for {self.pending_symbol} did not change its validation failure signature; marking that owner stalled and selecting a different causal owner."
                        )
            self.pending_symbol_progress_check = None
        self.signature_repetitions[self.signature] = (
            self.signature_repetitions.get(self.signature, 0) + 1
        )
        if self.signature_repetitions[self.signature] >= 3:
            if self.status_callback:
                self.status_callback(
                    "The package validation fingerprint repeated, but completion is governed by each failing owner's task-local repair ladder; continuing with the next unexhausted owner or boundary."
                )
            self.signature_repetitions[self.signature] = 0
        self.needs_repair_plan = (
            self.signature == self.previous_signature
            and any(
                (
                    marker in "\n".join(self.errors).lower()
                    for marker in (
                        "algorithm",
                        "cycle",
                        "ordering",
                        "coalesc",
                        "state transition",
                        "race",
                        "deadlock",
                    )
                )
            )
            or (
                "Disposable generated-patch validation failed:"
                in "\n".join(self.errors)
                and any(
                    (
                        marker in "\n".join(self.errors)
                        for marker in ("AssertionError:", "runtime assertion failed")
                    )
                )
            )
        )
        self.previous_signature = self.signature
        self.callable_targets = _deps._callable_repair_targets(
            self.active_validation_files, self.errors
        )
        for self.behavior_target in reversed(
            _deps._behavior_harness_production_targets(
                self.implementation_plan, self.errors
            )
        ):
            self.callable_targets = [
                target
                for target in self.callable_targets
                if target != self.behavior_target
            ]
            self.callable_targets.insert(0, self.behavior_target)
        self.failing_test_targets = _deps._runtime_failing_test_targets(
            self.active_validation_files, self.errors
        )
        self.requested_verification_symbols = set(
            _deps.re.findall(
                "\\b(?:add|define|implement|include|provide|expose)\\s+(?:an?\\s+|the\\s+)?([a-z_][A-Za-z0-9_]*)\\s*\\([^)]*\\)[^.!?\\n]{0,220}\\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|validates?|self[- ]test|fake\\s+(?:clock|client|host|service))\\b",
                self.prompt,
                flags=_deps.re.IGNORECASE,
            )
        )
        self.requested_verification_symbols.update(
            (
                str(chunk.get("owner") or "").rsplit(".", 1)[-1]
                for chunk in self.implementation_plan.get("chunks") or []
                if isinstance(chunk, dict)
                and str(chunk.get("kind") or "") == "function"
                and any(
                    (
                        str(requirement.get("semantic_role") or "") == "verification"
                        for requirement in chunk.get("requirements") or []
                        if isinstance(requirement, dict)
                    )
                )
            )
        )
        self.runtime_diagnostics = "\n".join(self.errors)
        for (
            self.verification_path,
            self._original,
            self.verification_source,
        ) in self.active_validation_files:
            try:
                self.verification_tree = _deps.ast.parse(
                    self.verification_source, filename=self.verification_path
                )
            except SyntaxError:
                continue
            for self.verification_node in self.verification_tree.body:
                if (
                    isinstance(
                        self.verification_node,
                        (_deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef),
                    )
                    and self.verification_node.name
                    in self.requested_verification_symbols
                    and _deps.re.search(
                        f"\\bin\\s+{_deps.re.escape(self.verification_node.name)}\\b",
                        self.runtime_diagnostics,
                    )
                    and any(
                        (
                            isinstance(child, _deps.ast.Assert)
                            for child in _deps.ast.walk(self.verification_node)
                        )
                    )
                ):
                    self.verification_target = {
                        "path": self.verification_path,
                        "symbol": self.verification_node.name,
                    }
                    if self.verification_target not in self.failing_test_targets:
                        self.failing_test_targets.append(self.verification_target)
        for self.verification_target in self.callable_targets:
            if (
                str(self.verification_target.get("symbol") or "").rsplit(".", 1)[-1]
                in self.requested_verification_symbols
                and self.verification_target not in self.failing_test_targets
            ):
                self.failing_test_targets.append(self.verification_target)
        if self.failing_test_targets and self.status_callback:
            self.status_callback(
                "Runtime verification owner candidates: "
                + ", ".join(
                    (
                        str(target.get("symbol") or "")
                        for target in self.failing_test_targets
                    )
                )
            )
        self.runtime_production_targets = _deps._runtime_test_production_repair_targets(
            self.active_validation_files, self.errors
        )
        (
            self.failing_behavior_requirement_ids,
            self.approved_behavior_production_targets,
            self.failing_behavior_contracts,
        ) = _deps._runtime_behavior_contract_targets(
            self.harness_source if self.ephemeral_validation_path else "",
            self.errors,
            self.implementation_plan,
        )
        if self.failing_behavior_contracts:
            if self.status_callback:
                self.status_callback(
                    "Runtime proof isolated failure to approved behavior sequence(s): "
                    + ", ".join(
                        (
                            str(contract.get("behavior_id") or "")
                            for contract in self.failing_behavior_contracts
                        )
                    )
                    + "; preserving unrelated production owners"
                )
            self.errors = [
                *self.errors,
                "APPROVED BEHAVIOR CONTRACT FAILURE: "
                + _deps.json.dumps(
                    self.failing_behavior_contracts,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            ]
        self.module_timeout_targets = _deps._module_timeout_repair_targets(
            self.active_validation_files, self.errors
        )
        self.wiring_target = _deps._ui_wiring_owner_repair_target(
            self.active_validation_files, self.errors
        )
        self.fixture_targets = _deps._runtime_expected_error_test_targets(
            self.active_validation_files, self.errors, self.prompt
        )
        if self.fixture_targets:
            self.callable_targets = list(
                {
                    (
                        str(target.get("path") or ""),
                        str(target.get("symbol") or ""),
                    ): target
                    for target in [*self.fixture_targets, *self.failing_test_targets]
                }.values()
            )
            self.errors = [
                *self.errors,
                "RUNTIME FIXTURE OWNERSHIP: production correctly rejected an invalid success-test fixture. Repair only the failing test method by constructing and adding every required prerequisite before the dependent object. Preserve direct expected-value assertions. Do not convert a success test into assertRaises unless that test explicitly owns the requested rejection.",
            ]
        elif self.wiring_target is not None:
            self.callable_targets = [
                target
                for target in self.callable_targets
                if target != self.wiring_target
            ]
            self.callable_targets.insert(0, self.wiring_target)
        else:
            for self.timeout_target in reversed(self.module_timeout_targets):
                self.callable_targets = [
                    target
                    for target in self.callable_targets
                    if target != self.timeout_target
                ]
                self.callable_targets.insert(0, self.timeout_target)
            for self.runtime_target in reversed(self.runtime_production_targets):
                self.callable_targets = [
                    target
                    for target in self.callable_targets
                    if target != self.runtime_target
                ]
                self.callable_targets.insert(0, self.runtime_target)
            for self.test_target in reversed(self.failing_test_targets):
                self.callable_targets = [
                    target
                    for target in self.callable_targets
                    if target != self.test_target
                ]
                self.callable_targets.insert(0, self.test_target)
        self.semantic_errors = [
            error
            for error in self.errors
            if not error.startswith("Disposable generated-patch validation failed:")
        ]
        self.runtime_failure_in_requested_verification = (
            bool(self.failing_test_targets)
            and "Disposable generated-patch validation failed:"
            in self.runtime_diagnostics
            and any(
                (
                    _deps.re.search(
                        f"\\bin\\s+{_deps.re.escape(str(target.get('symbol') or '').rsplit('.', 1)[-1])}\\b",
                        self.runtime_diagnostics,
                    )
                    for target in self.failing_test_targets
                    if str(target.get("symbol") or "")
                )
            )
        )
        self.verification_owns_runtime_failure = (
            self.runtime_failure_in_requested_verification
            and (not self.semantic_errors)
            and ("AssertionError" not in self.runtime_diagnostics)
            and bool(
                _deps.re.findall(
                    'File "[^"]+", line \\d+, in ([A-Za-z_][A-Za-z0-9_]*)',
                    self.runtime_diagnostics,
                )
            )
            and (
                _deps.re.findall(
                    'File "[^"]+", line \\d+, in ([A-Za-z_][A-Za-z0-9_]*)',
                    self.runtime_diagnostics,
                )[-1]
                in {
                    str(target.get("symbol") or "").rsplit(".", 1)[-1]
                    for target in self.failing_test_targets
                }
            )
        )
        if self.verification_owns_runtime_failure and self.status_callback:
            self.status_callback(
                "Runtime failure is owned by the requested verification callable; production symbols remain locked because no independent production contract validator reported a failure."
            )
        if self.semantic_errors and self.wiring_target is None:
            self.behavioral_targets = _deps._behavioral_owner_repair_targets(
                self.active_validation_files, self.semantic_errors, self.prompt
            )
            self.named_approved_behavior_targets = [
                target
                for target in self.approved_behavior_production_targets
                if any(
                    (
                        "_"
                        + str(target.get("symbol") or "")
                        .rsplit(".", 1)[-1]
                        .casefold()
                        + "_"
                    )
                    in (
                        "_"
                        + str(test_target.get("symbol") or "")
                        .rsplit(".", 1)[-1]
                        .casefold()
                        + "_"
                    )
                    for test_target in self.failing_test_targets
                )
            ]
            if len(self.named_approved_behavior_targets) == 1:
                self.behavioral_targets = list(
                    self.named_approved_behavior_targets
                )
                if self.status_callback:
                    self.status_callback(
                        "Mapped the uniquely named failing behavior test to "
                        "approved production owner "
                        + str(self.behavioral_targets[0].get("symbol") or "")
                    )
            if len(self.behavioral_targets) > 1 and (
                not any(("[owner:" in error for error in self.semantic_errors))
            ):
                self.owner_stage = _deps._build_behavioral_owner_resolution_stage(
                    self.generated_files,
                    self.behavioral_targets,
                    self.semantic_errors,
                    self.prompt,
                )
                self.owner_response, self.owner_timing = _deps._query_stage(
                    self.owner_stage,
                    selected_model=_deps._small_owner_reasoning_model(
                        self.settings, self.selected_model
                    ),
                    settings=self.settings,
                    timeout=self.timeout,
                )
                self.owner_timing["attempt"] = self.attempt
                self.timings.append(self.owner_timing)
                self.selected_owner = _deps._parse_behavioral_owner_resolution(
                    self.owner_response, self.behavioral_targets
                )
                if self.selected_owner is None:
                    if self.status_callback:
                        self.status_callback(
                            "3B owner resolution was invalid; escalating the same bounded candidate selection to the coding model."
                        )
                    self.owner_response, self.owner_timing = _deps._query_stage(
                        self.owner_stage,
                        selected_model=self.selected_model,
                        settings=self.settings,
                        timeout=self.timeout,
                    )
                    self.owner_timing.update(
                        {
                            "attempt": self.attempt,
                            "reason": "owner_resolution_escalation",
                        }
                    )
                    self.timings.append(self.owner_timing)
                    self.selected_owner = _deps._parse_behavioral_owner_resolution(
                        self.owner_response, self.behavioral_targets
                    )
                self.behavioral_targets = (
                    [self.selected_owner] if self.selected_owner is not None else []
                )
            for self.behavioral_target in self.behavioral_targets:
                if self.behavioral_target not in self.callable_targets:
                    self.callable_targets.append(self.behavioral_target)
        self.assertion_only_runtime_failure = "AssertionError:" in "\n".join(
            self.errors
        ) and (
            not _deps.re.search(
                "\\b(?:AttributeError|TypeError|NameError|KeyError|IndexError|RuntimeError|FrozenInstanceError):",
                "\n".join(self.errors),
            )
        )
        self.runtime_failure_owned_by_test = (
            _deps._runtime_deepest_frame_is_test(self.errors)
            and (not self.assertion_only_runtime_failure)
            or self.verification_owns_runtime_failure
        )
        if self.runtime_failure_owned_by_test:
            self.callable_targets = [
                target
                for target in self.callable_targets
                if _deps.Path(str(target.get("path") or "")).name.startswith("test_")
            ]
        if (
            self.approved_behavior_production_targets
            and (
                self.assertion_only_runtime_failure
                or (
                    self.failing_behavior_contracts
                    and not self.fixture_targets
                )
            )
        ):
            self.callable_targets = list(self.approved_behavior_production_targets)
            if self.status_callback:
                self.status_callback(
                    "Mapped audited behavior failure "
                    + ", ".join(sorted(self.failing_behavior_requirement_ids))
                    + " to approved production owner(s): "
                    + ", ".join(
                        (
                            str(target.get("symbol") or "")
                            for target in self.approved_behavior_production_targets
                        )
                    )
                )
        self.callable_targets = [
            target
            for target in self.callable_targets
            if (str(target.get("path") or ""), str(target.get("symbol") or ""))
            not in self.stalled_callable_symbols
        ]
        self.verification_target_keys = {
            (str(target.get("path") or ""), str(target.get("symbol") or ""))
            for target in self.failing_test_targets
        }
        self.production_callable_targets = [
            target
            for target in self.callable_targets
            if (str(target.get("path") or ""), str(target.get("symbol") or ""))
            not in self.verification_target_keys
            and (not _deps.Path(str(target.get("path") or "")).name.startswith("test_"))
        ]
        self.test_proof_failure = any(
            (
                "Generated test methods need stronger behavioral proof" in error
                or "fixture variables never consumed" in error
                or "external command fixtures require" in error
                for error in self.semantic_errors
            )
        )
        self.test_contract_failure = any(
            (
                "generated test accesses unapproved" in error
                for error in self.semantic_errors
            )
        )
        self.harness_oracle_invalid = bool(
            self.test_proof_failure
            or self.test_contract_failure
            or (
                _deps._runtime_deepest_frame_is_test(self.errors)
                and (not self.assertion_only_runtime_failure)
            )
        )
        self.test_callable_targets = [
            target
            for target in self.callable_targets
            if (str(target.get("path") or ""), str(target.get("symbol") or ""))
            in self.verification_target_keys
            or _deps.Path(str(target.get("path") or "")).name.startswith("test_")
        ]
        self.named_test_callable_targets = [
            target
            for target in self.test_callable_targets
            if str(target.get("symbol") or "") in "\n".join(self.semantic_errors)
        ]
        self.explicit_test_failure = any(
            (
                str(target.get("symbol") or "") in "\n".join(self.semantic_errors)
                for target in self.test_callable_targets
            )
        )
        self.explicit_production_failure = any(
            (
                str(target.get("symbol") or "") in "\n".join(self.semantic_errors)
                for target in self.production_callable_targets
            )
        )
        if self.harness_oracle_invalid and self.named_test_callable_targets:
            self.callable_targets = self.named_test_callable_targets
        elif self.harness_oracle_invalid and self.test_callable_targets:
            self.callable_targets = self.test_callable_targets
        elif self.explicit_test_failure and self.explicit_production_failure:
            self.callable_targets = list(self.production_callable_targets)
        elif self.explicit_test_failure and self.test_callable_targets:
            self.callable_targets = self.test_callable_targets
        elif self.verification_owns_runtime_failure and self.test_callable_targets:
            self.callable_targets = self.test_callable_targets
        elif self.runtime_failure_owned_by_test and self.test_callable_targets:
            self.callable_targets = self.test_callable_targets
        elif self.production_callable_targets and (
            not self.runtime_failure_owned_by_test
        ):
            self.callable_targets = self.production_callable_targets
        self.audited_production_owner_lock = bool(
            self.approved_behavior_production_targets
            and (
                self.assertion_only_runtime_failure
                or (
                    self.failing_behavior_contracts
                    and not self.fixture_targets
                )
            )
            and (not self.harness_oracle_invalid)
        )
        if self.audited_production_owner_lock:
            self.causal_changed_owner = next(
                (
                    target
                    for target in self.approved_behavior_production_targets
                    if (str(target.get("path") or ""), str(target.get("symbol") or ""))
                    == self.causal_changed_owner_key
                ),
                None,
            )
            self.callable_targets = (
                [self.causal_changed_owner]
                if self.causal_changed_owner is not None
                else (
                    list(self.named_approved_behavior_targets)
                    if len(self.named_approved_behavior_targets) == 1
                    else list(self.approved_behavior_production_targets)
                )
            )
            self.failing_test_targets = []
            self.verification_target_keys = set()
            self.production_callable_targets = list(self.callable_targets)
            self.test_callable_targets = []
        self.snapshot_plan_by_owner: dict[tuple[str, str], dict[str, _deps.Any]] = {}
        self.repaired_validation_files, self.longest_prefix_expectation_repair = (
            _deps._repair_stale_longest_prefix_expectation(
                self.active_validation_files, self.errors, request_prompt=self.prompt
            )
        )
        if self.longest_prefix_expectation_repair:
            if self.harness_entry is not None:
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
            else:
                self.generated_files = self.repaired_validation_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
            if self.status_callback:
                self.status_callback(
                    "Applied bounded deterministic runtime oracle repair: "
                    + self.longest_prefix_expectation_repair
                )
            raise _WorkflowContinue()
