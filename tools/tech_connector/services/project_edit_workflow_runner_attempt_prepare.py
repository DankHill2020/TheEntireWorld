"""Project-edit workflow phase: _run_attempt_prepare_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import (
    _WorkflowReturn,
    _WorkflowBreak,
    _WorkflowContinue,
)


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
        self.validation_started = _deps.time.perf_counter()
        self.active_validation_files = self.generated_files
        self.ephemeral_validation_path = ""
        self.approved_plan_errors = (
            self.validate_generated_files_against_implementation_plan(
                self.implementation_plan, self.generated_files
            )
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
                        self.owner_batches: dict[
                            tuple[str, str, str], list[dict[str, _deps.Any]]
                        ] = {}
                        for self.row in self.runtime_behavior_rows:
                            self.owner_execution = self.row.get("owner_execution") or {}
                            self.owner_class_name = str(
                                self.owner_execution.get("class_name") or ""
                            )
                            self.owner_key = (
                                self.owner_class_name
                                or str(self.owner_execution.get("symbol") or ""),
                                self.owner_class_name,
                                "" if self.owner_class_name else str(
                                    self.owner_execution.get("callable_name") or ""
                                ),
                            )
                            self.owner_batches.setdefault(self.owner_key, []).append(
                                self.row
                            )
                        self.pending_harness_batches = list(self.owner_batches.values())
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
                                selected_model=_deps._small_owner_reasoning_model(
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
                                )
                            )
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
                            while self.batch_errors and self.singleton_attempt < 2:
                                self.singleton_attempt += 1
                                self.repeated_candidate = (
                                    self.singleton_attempt > 1
                                    and str(self.batch_response or "").strip()
                                    == self.previous_singleton_response.strip()
                                )
                                self.previous_singleton_response = str(
                                    self.batch_response or ""
                                )
                                self.focused_batch_stage = _deps.replace(
                                    self.batch_stage,
                                    user_prompt=self.batch_stage.user_prompt
                                    + "\n\nTHE PREVIOUS SINGLE-BEHAVIOR CAPSULE WAS REJECTED:\n"
                                    + " | ".join(self.batch_errors)
                                    + "\nReturn only the complete unittest module for this one exact behavior ID."
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
                                        selected_model=self.selected_model,
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
                    for self.harness_attempt in range(1, 2):
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
                                    selected_model=_deps._small_owner_reasoning_model(
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
                            )
                        )
                        if not self.harness_errors:
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
                                _deps._ephemeral_harness_behavior_contract_errors(
                                    self.harness_source,
                                    list(
                                        self.harness_stage.metadata.get(
                                            "behavior_rows", []
                                        )
                                    ),
                                    generated_files=self.generated_files,
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
                    (
                        marker in str(error)
                        for error in self.harness_preview_errors
                        for marker in (
                            "does not execute approved production owner",
                            "Disposable behavior harness",
                            "__TECH_CONNECTOR_BEHAVIOR_BINDINGS__",
                            "Generated callables reference undefined names in Test",
                            "executes no observable assertion",
                        )
                    )
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
                    if self.status_callback:
                        self.status_callback(
                            "Failure is owned by disposable test methods; freezing production and auditing only the exact failing tests against the production call graph."
                        )
                    self.runtime_audit_source = self.harness_source
                    self.runtime_audit_known_issues = list(self.harness_preview_errors)
                    self.accepted_runtime_audit_source = ""
                    self.seen_runtime_audit_sources = {self.harness_source}
                    self.seen_runtime_rejection_fingerprints: set[str] = set()
                    # One source-grounded runtime audit is the bounded recovery
                    # budget for an unchanged production candidate. Repeated
                    # model rewrites of disposable tests cannot improve code and
                    # previously dominated end-to-end latency.
                    for self.runtime_audit_attempt in range(1, 2):
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
                            continue
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
                                        )
                                    )
                                    if self.status_callback:
                                        self.status_callback(
                                            "Applied deterministic exact-owner test repair: "
                                            + "; ".join(self.indirect_owner_repairs)
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
                            continue
                        self.accepted_runtime_audit_source = (
                            self.repaired_harness_source
                        )
                        break
                    if self.accepted_runtime_audit_source:
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
                            and (not self.harness_preview.errors)
                            else f"reported {len(self.harness_preview.errors or [])} behavior failure(s)."
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
