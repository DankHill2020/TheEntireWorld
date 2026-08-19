"""Project-edit workflow phase: _run_attempt_validate_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import (
    _WorkflowReturn,
    _WorkflowBreak,
    _WorkflowContinue,
)


class _ProjectEditAttemptValidatePhase:
    """Provide the attempt validate workflow phase."""

    def _run_attempt_validate_phase(self) -> None:
        """Run the attempt validate phase.

        :return: None.
        """
        if "Disposable generated-patch validation failed:" in "\n".join(self.errors):
            self.repaired_validation_files, self.called_property_repair = (
                _deps._repair_called_approved_property(
                    self.active_validation_files,
                    self.errors,
                    implementation_plan=self.implementation_plan,
                )
            )
            if self.called_property_repair:
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
                        "Applied bounded deterministic verification API repair: "
                        + self.called_property_repair
                    )
                raise _WorkflowContinue()
            self.deterministic_runtime_files, self.stale_existence_assertion_repair = (
                _deps._repair_stale_boolean_existence_assertion(
                    self.generated_files, self.errors, request_prompt=self.prompt
                )
            )
            if self.stale_existence_assertion_repair:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime assertion repair: "
                        + self.stale_existence_assertion_repair
                    )
                raise _WorkflowContinue()
            self.deterministic_runtime_files, self.local_definition_order_repairs = (
                _deps._repair_local_callable_definition_order(
                    self.generated_files, self.errors
                )
            )
            if self.local_definition_order_repairs:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime ordering repair: "
                        + "; ".join(self.local_definition_order_repairs)
                    )
                raise _WorkflowContinue()
            self.deterministic_runtime_files, self.exception_message_repair = (
                _deps._repair_unrequested_exception_message_assertion(
                    self.generated_files, self.errors, request_prompt=self.prompt
                )
            )
            if self.exception_message_repair:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime assertion repair: "
                        + self.exception_message_repair
                    )
                raise _WorkflowContinue()
            self.deterministic_runtime_files, self.orphaned_expectation_repair = (
                _deps._repair_orphaned_result_expectations(
                    self.generated_files, self.errors
                )
            )
            if self.orphaned_expectation_repair:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime fixture repair: "
                        + self.orphaned_expectation_repair
                    )
                raise _WorkflowContinue()
            self.deterministic_runtime_files, self.deterministic_runtime_repair = (
                _deps._repair_uninvoked_mock_callback(self.generated_files, self.errors)
            )
            if self.deterministic_runtime_repair:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime repair: "
                        + self.deterministic_runtime_repair
                    )
                raise _WorkflowContinue()
            self.deterministic_runtime_files, self.deterministic_runtime_repair = (
                _deps._repair_insufficient_fake_clock_advance(
                    self.generated_files, self.errors
                )
            )
            if self.deterministic_runtime_repair:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime repair: "
                        + self.deterministic_runtime_repair
                    )
                raise _WorkflowContinue()
            (
                self.deterministic_runtime_files,
                self.positive_predicate_fixture_repairs,
            ) = _deps._repair_missing_positive_predicate_fixture(self.generated_files)
            if self.positive_predicate_fixture_repairs:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime fixture repair: "
                        + "; ".join(self.positive_predicate_fixture_repairs)
                    )
                raise _WorkflowContinue()
            self.deterministic_runtime_files, self.cross_collection_repair = (
                _deps._repair_cross_collection_removal_polarity(
                    self.generated_files, self.errors, self.failing_test_targets
                )
            )
            if self.cross_collection_repair:
                self.generated_files = self.deterministic_runtime_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                if self.status_callback:
                    self.status_callback(
                        "Applied bounded deterministic runtime state repair: "
                        + self.cross_collection_repair
                    )
                raise _WorkflowContinue()
            self.runtime_failure_batches = (
                []
                if self.audited_production_owner_lock
                else _deps._runtime_failure_target_batches(
                    self.active_validation_files, self.errors
                )
            )
            self.runtime_snapshot_key = _deps._checkpoint_hash(
                {
                    "failure_signature": self.signature,
                    "candidate_fingerprint": _deps._candidate_checkpoint_fingerprint(
                        self.candidate
                    ),
                }
            )
            self.exercised_production_targets = (
                []
                if self.audited_production_owner_lock
                else _deps._production_callables_exercised_by_tests(
                    self.active_validation_files, self.failing_test_targets
                )
            )
            self.assertion_causal_targets = (
                []
                if self.audited_production_owner_lock
                else _deps._runtime_assertion_causal_owner_targets(
                    self.active_validation_files, self.errors, self.failing_test_targets
                )
            )
            if self.assertion_causal_targets and self.status_callback:
                self.status_callback(
                    "Resolved runtime assertion owner from traceback dataflow: "
                    + ", ".join(
                        (
                            str(target.get("symbol") or "")
                            for target in self.assertion_causal_targets
                        )
                    )
                )
            self.satisfied_assertion_targets: set[tuple[str, str]] = set()
            self.active_assertion_causal_targets = [
                target
                for target in self.assertion_causal_targets
                if (str(target.get("path") or ""), str(target.get("symbol") or ""))
                not in self.stalled_callable_symbols
                and (str(target.get("path") or ""), str(target.get("symbol") or ""))
                not in self.satisfied_assertion_targets
            ]
            if len(self.active_assertion_causal_targets) == 1 and (
                not self.failing_test_targets
            ):
                self.callable_targets = list(self.active_assertion_causal_targets)
            elif self.failing_test_targets and self.active_assertion_causal_targets:
                self.callable_targets = list(
                    {
                        (
                            str(target.get("path") or ""),
                            str(target.get("symbol") or ""),
                        ): target
                        for target in [
                            *self.failing_test_targets,
                            *self.active_assertion_causal_targets,
                        ]
                    }.values()
                )
            self.snapshot_candidates = list(
                {
                    (
                        str(target.get("path") or ""),
                        str(target.get("symbol") or ""),
                    ): target
                    for target in [
                        *self.callable_targets,
                        *self.failing_test_targets,
                        *self.runtime_production_targets,
                        *self.module_timeout_targets,
                        *self.exercised_production_targets,
                        *self.assertion_causal_targets,
                        *[
                            target
                            for batch in self.runtime_failure_batches
                            for target in batch["targets"]
                        ],
                    ]
                    if str(target.get("path") or "") and str(target.get("symbol") or "")
                }.values()
            )
            self.direct_runtime_owner_proven = len(self.callable_targets) == 1
            if self.snapshot_candidates and (not self.direct_runtime_owner_proven):
                if self.runtime_snapshot_key not in self.runtime_snapshot_repair_plans:
                    self.focused_batches: list[dict[str, _deps.Any]] = []
                    if self.runtime_failure_batches:
                        self.focused_batches = self.runtime_failure_batches
                    elif self.assertion_causal_targets:
                        self.focused_batches = [
                            {
                                "test_name": "<traceback assertion>",
                                "errors": list(self.errors),
                                "targets": list(
                                    {
                                        (
                                            str(target.get("path") or ""),
                                            str(target.get("symbol") or ""),
                                        ): target
                                        for target in [
                                            *self.failing_test_targets,
                                            *self.assertion_causal_targets,
                                        ]
                                    }.values()
                                ),
                            }
                        ]
                    else:
                        self.focused_test_targets = self.failing_test_targets or [
                            target
                            for target in self.snapshot_candidates
                            if _deps.Path(
                                str(target.get("path") or "")
                            ).name.startswith("test_")
                        ]
                        if self.focused_test_targets:
                            for self.test_target in self.focused_test_targets:
                                self.focused_batches.append(
                                    {
                                        "test_name": str(
                                            self.test_target.get("symbol") or ""
                                        ),
                                        "errors": list(self.errors),
                                        "targets": [
                                            self.test_target,
                                            *_deps._production_callables_exercised_by_tests(
                                                self.active_validation_files,
                                                [self.test_target],
                                            ),
                                        ],
                                    }
                                )
                        else:
                            self.focused_batches = [
                                {
                                    "test_name": "<module runtime>",
                                    "errors": list(self.errors),
                                    "targets": self.snapshot_candidates,
                                }
                            ]
                    self.combined_repairs: dict[
                        tuple[str, str], dict[str, _deps.Any]
                    ] = {}
                    self.snapshot_errors: list[str] = []
                    self.causal_repair_escalated = False
                    for self.focus_index, self.focused_batch in enumerate(
                        self.focused_batches, start=1
                    ):
                        self.focused_candidates = list(
                            self.focused_batch.get("targets") or []
                        )
                        self.focused_validation_errors = list(
                            self.focused_batch.get("errors") or self.errors
                        )
                        self.failing_runtime_test_names = set(
                            _deps.re.findall(
                                "\\btest_[A-Za-z0-9_]+\\b",
                                "\n".join(
                                    (
                                        str(error)
                                        for error in self.focused_validation_errors
                                    )
                                ),
                            )
                        )
                        if self.failing_runtime_test_names:
                            for (
                                self.validation_path,
                                self._validation_original,
                                self.validation_source,
                            ) in self.active_validation_files:
                                if not _deps.Path(self.validation_path).name.startswith(
                                    "test_"
                                ):
                                    continue
                                try:
                                    self.validation_tree = _deps.ast.parse(
                                        self.validation_source,
                                        filename=self.validation_path,
                                    )
                                except SyntaxError:
                                    continue
                                self.focused_candidates.extend(
                                    (
                                        {
                                            "path": self.validation_path,
                                            "symbol": f"{class_node.name}.{method.name}",
                                        }
                                        for class_node in self.validation_tree.body
                                        if isinstance(class_node, _deps.ast.ClassDef)
                                        for method in class_node.body
                                        if isinstance(
                                            method,
                                            (
                                                _deps.ast.FunctionDef,
                                                _deps.ast.AsyncFunctionDef,
                                            ),
                                        )
                                        and method.name
                                        in self.failing_runtime_test_names
                                    )
                                )
                        self.remaining_candidates = list(
                            {
                                (
                                    str(target.get("path") or ""),
                                    str(target.get("symbol") or ""),
                                ): target
                                for target in self.focused_candidates
                            }.values()
                        )
                        self.has_test_candidate = any(
                            (
                                (
                                    str(target.get("path") or ""),
                                    str(target.get("symbol") or ""),
                                )
                                in self.verification_target_keys
                                or _deps.Path(
                                    str(target.get("path") or "")
                                ).name.startswith("test_")
                                for target in self.remaining_candidates
                            )
                        )
                        self.has_production_candidate = any(
                            (
                                (
                                    str(target.get("path") or ""),
                                    str(target.get("symbol") or ""),
                                )
                                not in self.verification_target_keys
                                and (
                                    not _deps.Path(
                                        str(target.get("path") or "")
                                    ).name.startswith("test_")
                                )
                                for target in self.remaining_candidates
                            )
                        )
                        if self.has_test_candidate and self.has_production_candidate:
                            self.owner_stage = (
                                _deps._build_behavioral_owner_resolution_stage(
                                    self.active_validation_files,
                                    self.remaining_candidates,
                                    self.focused_validation_errors,
                                    self.prompt,
                                )
                            )
                            self.owner_response, self.owner_timing = _deps._query_stage(
                                self.owner_stage,
                                selected_model=_deps._causal_repair_reasoning_model(
                                    self.settings, self.selected_model
                                ),
                                settings=self.settings,
                                timeout=self.timeout,
                            )
                            self.owner_timing.update(
                                {
                                    "attempt": self.attempt,
                                    "stage": "runtime_causal_owner_resolution",
                                    "symbol": str(
                                        self.focused_candidates[0].get("symbol") or ""
                                    ),
                                }
                            )
                            self.timings.append(self.owner_timing)
                            self.selected_runtime_owner = (
                                _deps._parse_behavioral_owner_resolution(
                                    self.owner_response, self.remaining_candidates
                                )
                            )
                            if self.selected_runtime_owner is None:
                                self.owner_response, self.owner_timing = (
                                    _deps._query_stage(
                                        self.owner_stage,
                                        selected_model=self.selected_model,
                                        settings=self.settings,
                                        timeout=self.timeout,
                                    )
                                )
                                self.owner_timing.update(
                                    {
                                        "attempt": self.attempt,
                                        "stage": "runtime_causal_owner_resolution",
                                        "reason": "owner_resolution_escalation",
                                    }
                                )
                                self.timings.append(self.owner_timing)
                                self.selected_runtime_owner = (
                                    _deps._parse_behavioral_owner_resolution(
                                        self.owner_response, self.remaining_candidates
                                    )
                                )
                            if self.selected_runtime_owner is not None:
                                self.remaining_candidates = [
                                    self.selected_runtime_owner
                                ]
                        self.test_alternative = next(
                            (
                                target
                                for target in self.focused_candidates
                                if (
                                    str(target.get("path") or ""),
                                    str(target.get("symbol") or ""),
                                )
                                in self.verification_target_keys
                                or _deps.Path(
                                    str(target.get("path") or "")
                                ).name.startswith("test_")
                            ),
                            None,
                        )
                        if self.test_alternative is not None and (
                            not any(
                                (
                                    (
                                        str(target.get("path") or ""),
                                        str(target.get("symbol") or ""),
                                    )
                                    == (
                                        str(self.test_alternative.get("path") or ""),
                                        str(self.test_alternative.get("symbol") or ""),
                                    )
                                    for target in self.remaining_candidates
                                )
                            )
                        ):
                            self.remaining_candidates = [
                                *self.remaining_candidates,
                                self.test_alternative,
                            ]
                        self.focus_symbol = str(
                            self.remaining_candidates[0].get("symbol")
                            or "runtime failure"
                        )
                        self.focused_repairs: list[dict[str, _deps.Any]] = []
                        self.focused_errors: list[str] = []
                        self.rejection_feedback = ""
                        self.seen_analysis_failures: set[str] = set()
                        for self.strategy_attempt in range(
                            1, max(3, len(self.remaining_candidates) + 1) + 1
                        ):
                            (
                                self.snapshot_stage,
                                self.candidate_by_id,
                                self.expected_failure_ids,
                            ) = _deps._build_runtime_snapshot_repair_stage(
                                self.active_validation_files,
                                self.remaining_candidates,
                                self.focused_validation_errors,
                                self.prompt,
                                self.implementation_plan,
                            )
                            if self.rejection_feedback:
                                self.snapshot_stage = _deps.replace(
                                    self.snapshot_stage,
                                    user_prompt=self.snapshot_stage.user_prompt
                                    + "\n\nVALIDATOR-PROVEN STRATEGY CHANGE:\n"
                                    + self.rejection_feedback
                                    + "\nThe rejected owner or response cannot be repeated. Recalculate from the authoritative oracle and return a new valid owner hunk.",
                                )
                            self.complex_production_repair = any(
                                (
                                    not _deps.Path(
                                        str(target.get("path") or "")
                                    ).name.startswith("test_")
                                    for target in self.remaining_candidates
                                )
                            ) and bool(
                                _deps.re.search(
                                    "\\b(?:algorithm|cycle|ordering|dependency|topological|recursion|deadlock|race|state transition)\\b",
                                    "\n".join(
                                        [self.prompt, *self.focused_validation_errors]
                                    ),
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            self.repair_model = (
                                _deps._causal_repair_escalation_model(
                                    self.settings, self.selected_model
                                )
                                if self.causal_repair_escalated
                                or self.complex_production_repair
                                else _deps._causal_repair_reasoning_model(
                                    self.settings, self.selected_model
                                )
                            )
                            if (
                                self.causal_repair_escalated
                                or self.complex_production_repair
                            ):
                                self.snapshot_stage = _deps.replace(
                                    self.snapshot_stage,
                                    num_predict=2500,
                                    timeout=max(self.snapshot_stage.timeout, 150),
                                    no_progress_seconds=max(
                                        self.snapshot_stage.no_progress_seconds, 60
                                    ),
                                )
                            if self.status_callback:
                                self.status_callback(
                                    f"Running focused semantic causal repair {self.focus_index}/{len(self.focused_batches)} for {self.focus_symbol}, strategy {self.strategy_attempt}, model {self.repair_model}."
                                )
                            self.snapshot_response, self.snapshot_timing = (
                                _deps._query_stage(
                                    self.snapshot_stage,
                                    selected_model=self.repair_model,
                                    settings=self.settings,
                                    timeout=self.timeout,
                                )
                            )
                            self.snapshot_timing.update(
                                {
                                    "attempt": self.attempt,
                                    "strategy_attempt": self.strategy_attempt,
                                    "stage": "runtime_snapshot_repair_analysis",
                                    "symbol": self.focus_symbol,
                                }
                            )
                            self.timings.append(self.snapshot_timing)
                            self.focused_repairs, self.focused_errors = (
                                _deps._parse_runtime_snapshot_repair_analysis(
                                    self.snapshot_response,
                                    self.candidate_by_id,
                                    self.expected_failure_ids,
                                )
                            )
                            if not self.focused_errors:
                                break
                            if self.test_alternative is not None and any(
                                (
                                    "returned unchanged code" in error
                                    for error in self.focused_errors
                                )
                            ):
                                self.remaining_candidates = [self.test_alternative]
                                self.causal_repair_escalated = True
                                self.rejection_feedback = "The selected production callable was validator-proven unchanged. Repair the paired generated test method's setup or expected value instead. Return exactly that test method."
                                self.seen_analysis_failures.clear()
                                if self.status_callback:
                                    self.status_callback(
                                        "Production owner was unchanged; switching this failure directly to the paired disposable test method."
                                    )
                                continue
                            if not self.causal_repair_escalated:
                                self.causal_repair_escalated = True
                                if self.status_callback:
                                    self.status_callback(
                                        "Escalating the remaining causal repair phase once after validator-proven unchanged or invalid output."
                                    )
                            self.failure_fingerprint = "\n".join(self.focused_errors)
                            if self.failure_fingerprint in self.seen_analysis_failures:
                                break
                            self.seen_analysis_failures.add(self.failure_fingerprint)
                            self.rejection_feedback = (
                                " | ".join(self.focused_errors)
                                + "\nRejected response:\n"
                                + self.snapshot_response[-4000:]
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Rejected causal strategy for {self.focus_symbol}: "
                                    + " | ".join(self.focused_errors[:3])
                                )
                                self.status_callback(
                                    "Rejected causal response:\n"
                                    + self.snapshot_response[-3000:]
                                )
                            if not self.remaining_candidates:
                                break
                        if self.focused_errors:
                            self.snapshot_errors.extend(
                                (
                                    f"{self.focus_symbol}: {error}"
                                    for error in self.focused_errors
                                )
                            )
                            continue
                        for self.repair in self.focused_repairs:
                            self.key = (self.repair["path"], self.repair["symbol"])
                            self.previous = self.combined_repairs.get(self.key)
                            if (
                                self.previous
                                and self.previous["replacement"]
                                != self.repair["replacement"]
                            ):
                                self.snapshot_errors.append(
                                    f"{self.focus_symbol}: conflicting replacements were returned for {self.repair['symbol']}."
                                )
                                continue
                            if self.previous:
                                self.previous["failure_ids"] = sorted(
                                    {*self.previous["failure_ids"], self.focus_symbol}
                                )
                            else:
                                self.repair["failure_ids"] = [self.focus_symbol]
                                self.combined_repairs[self.key] = self.repair
                    if self.snapshot_errors:
                        raise _WorkflowReturn(
                            _deps.ProjectEditWorkflowResult(
                                ok=False,
                                status="repair_analysis_failed",
                                candidate=self.candidate,
                                preview=self.preview,
                                errors=self.snapshot_errors,
                                timings=self.timings,
                            )
                        )
                    self.runtime_snapshot_repair_plans[self.runtime_snapshot_key] = (
                        self.combined_repairs
                    )
                    if self.status_callback:
                        for self.repair in self.combined_repairs.values():
                            self.status_callback(
                                f"Assigned {self.repair['symbol']} ({('3B mechanical' if self.repair['mechanical'] else '7B behavioral')}): {self.repair['root_cause']}"
                            )
                self.snapshot_plan_by_owner = self.runtime_snapshot_repair_plans[
                    self.runtime_snapshot_key
                ]
                self.callable_targets = [
                    {"path": path, "symbol": symbol}
                    for path, symbol in self.snapshot_plan_by_owner
                    if (path, symbol) not in self.stalled_callable_symbols
                ]
        self.generated_files, self.deterministic_host_repair = (
            _deps._repair_unbound_host_test_binding(
                self.generated_files, errors=self.errors, targets=self.callable_targets
            )
        )
        if self.deterministic_host_repair:
            if self.status_callback:
                self.status_callback(
                    "Applied deterministic host-test binding repair: "
                    + self.deterministic_host_repair
                )
            self.generated_files = _deps._normalize_generated_files(
                self.generated_files, project_root=self.root, request_prompt=self.prompt
            )
            self.candidate = _deps.build_project_edit_multi_file_candidate(
                self.generated_files
            )
            raise _WorkflowContinue()
        self.class_targets: list[tuple[str, str]] = []
        self.behavioral_failure = any(
            (
                "Disposable generated-patch validation failed" in error
                for error in self.errors
            )
        )
        self.runtime_failing_tests = set(
            _deps.re.findall("\\btest_[A-Za-z0-9_]+\\b", "\n".join(self.errors))
        )
        self.shared_state_assertion_failure = (
            self.behavioral_failure
            and len(self.runtime_failing_tests) >= 2
            and ("AssertionError:" in "\n".join(self.errors))
            and (
                not _deps.re.search(
                    "\\b(?:AttributeError|TypeError|NameError|KeyError|IndexError|RuntimeError|FrozenInstanceError):",
                    "\n".join(self.errors),
                )
            )
        )
        self.failing_methods_by_class: dict[tuple[str, str], int] = {}
        for self.target in self.callable_targets:
            self.symbol_parts = str(self.target.get("symbol") or "").split(".", 1)
            if len(self.symbol_parts) != 2:
                continue
            self.key = (str(self.target.get("path") or ""), self.symbol_parts[0])
            self.failing_methods_by_class[self.key] = (
                self.failing_methods_by_class.get(self.key, 0) + 1
            )
        self.error_blob = "\n".join(self.errors)
        for (
            self.class_path,
            self._original_source,
            self.class_source,
        ) in self.generated_files:
            try:
                self.class_tree = _deps.ast.parse(
                    self.class_source, filename=self.class_path
                )
            except SyntaxError:
                continue
            for self.class_node in self.class_tree.body:
                if not isinstance(self.class_node, _deps.ast.ClassDef):
                    continue
                self.substantive_methods = [
                    node
                    for node in self.class_node.body
                    if isinstance(
                        node, (_deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef)
                    )
                    and node.name not in {"__repr__", "__eq__", "__hash__"}
                ]
                self.is_record_class = any(
                    (
                        _deps.ast.unparse(decorator).startswith(
                            ("dataclass", "dataclasses.dataclass")
                        )
                        for decorator in self.class_node.decorator_list
                    )
                )
                self.approved_class_failure = bool(
                    _deps.re.search(
                        f"{_deps.re.escape(self.class_path)}:{_deps.re.escape(self.class_node.name)}(?:\\.|\\:).*?\\bapproved\\b",
                        self.error_blob,
                        flags=_deps.re.IGNORECASE | _deps.re.DOTALL,
                    )
                )
                self.exact_class_failure = bool(
                    _deps.re.search(
                        f"(?:^|\\n){_deps.re.escape(self.class_path)}:{_deps.re.escape(self.class_node.name)}(?:\\.|:)",
                        self.error_blob,
                        flags=_deps.re.IGNORECASE,
                    )
                    or _deps.re.search(
                        f"(?:^|\\n){_deps.re.escape(_deps.Path(self.class_path).name)}:{_deps.re.escape(self.class_node.name)}(?:\\.|:)",
                        self.error_blob,
                        flags=_deps.re.IGNORECASE,
                    )
                )
                self.approved_attribute_names = {
                    str(attribute.get("name") or "")
                    for chunk in self.implementation_plan.get("chunks") or []
                    if isinstance(chunk, dict)
                    and str(
                        _deps.Path(str(chunk.get("path") or "")).resolve()
                    ).casefold()
                    == str(_deps.Path(self.class_path).resolve()).casefold()
                    and (str(chunk.get("owner") or "") == self.class_node.name)
                    for attribute in (chunk.get("declaration_contract") or {}).get(
                        "attributes"
                    )
                    or []
                    if isinstance(attribute, dict) and str(attribute.get("name") or "")
                }
                self.planned_attribute_failure = any(
                    (
                        attribute_name in self.error_blob
                        for attribute_name in self.approved_attribute_names
                    )
                )
                self.actual_self_attributes = {
                    node.attr
                    for node in _deps.ast.walk(self.class_node)
                    if isinstance(node, _deps.ast.Attribute)
                    and isinstance(node.value, _deps.ast.Name)
                    and (node.value.id == "self")
                }
                self.class_attribute_failure = any(
                    (
                        attribute_name in self.error_blob
                        and (
                            "never read" in self.error_blob
                            or "never used" in self.error_blob
                            or "runtime use" in self.error_blob
                        )
                        for attribute_name in self.actual_self_attributes
                    )
                )
                if (
                    not self.substantive_methods
                    and (not self.is_record_class)
                    and (not self.approved_class_failure)
                    and (not self.exact_class_failure)
                    or self.class_node.name.endswith(("Error", "Exception"))
                ):
                    continue
                self.key = (self.class_path, self.class_node.name)
                self.class_named_in_state_failure = bool(
                    _deps.re.search(
                        f"""(?:object|class|type)\\s+['\\"]?{_deps.re.escape(self.class_node.name)}['\\"]?.*?(?:has no attribute|missing|required positional|unexpected keyword|takes \\d+ positional)""",
                        self.error_blob,
                        flags=_deps.re.IGNORECASE | _deps.re.DOTALL,
                    )
                    or _deps.re.search(
                        f"{_deps.re.escape(self.class_node.name)}\\.__init__\\s*\\(",
                        self.error_blob,
                    )
                )
                self.coordinated_ui_architecture_failure = bool(
                    not _deps.Path(self.class_path).name.startswith("test_")
                    and "full-screen/virtual-desktop pick surface" in self.error_blob
                )
                self.import_surface_failure = bool(
                    not _deps.Path(self.class_path).name.startswith("test_")
                    and (
                        "Add Unreal host-module access" in self.error_blob
                        or "looks like a local placeholder API base" in self.error_blob
                        or "not importing a Qt-compatible symbol surface"
                        in self.error_blob
                    )
                    and (
                        self.failing_methods_by_class.get(self.key, 0) >= 1
                        or self.class_node.name in self.error_blob
                    )
                )
                self.multiple_shared_failures = (
                    not _deps.Path(self.class_path).name.startswith("test_")
                    and self.failing_methods_by_class.get(self.key, 0) >= 2
                    and (not self.behavioral_failure)
                )
                self.frozen_record_state_failure = (
                    self.is_record_class
                    and "FrozenInstanceError" in self.error_blob
                    and (self.failing_methods_by_class.get(self.key, 0) >= 1)
                )
                self.named_test_failures = set(
                    _deps.re.findall(
                        f"\\b{_deps.re.escape(self.class_node.name)}\\.(test_[A-Za-z0-9_]+)\\b",
                        self.error_blob,
                    )
                )
                self.concentrated_test_failures = _deps.Path(
                    self.class_path
                ).name.startswith("test_") and (
                    len(self.named_test_failures) >= 2
                    or (self.test_proof_failure and len(self.named_test_failures) >= 2)
                    or self.failing_methods_by_class.get(self.key, 0) >= 3
                )
                self.stalled_class_failure = any(
                    (
                        stalled_path == self.class_path
                        and stalled_symbol.startswith(self.class_node.name + ".")
                        for stalled_path, stalled_symbol in self.stalled_callable_symbols
                    )
                )
                self.shared_state_class_failure = (
                    self.shared_state_assertion_failure
                    and (not _deps.Path(self.class_path).name.startswith("test_"))
                    and any(
                        (
                            method.name.startswith(
                                (
                                    "add",
                                    "set",
                                    "register",
                                    "update",
                                    "append",
                                    "insert",
                                    "remove",
                                    "clear",
                                )
                            )
                            for method in self.substantive_methods
                        )
                    )
                    and any(
                        (
                            str(target.get("path") or "") == self.class_path
                            and str(target.get("symbol") or "").startswith(
                                self.class_node.name + "."
                            )
                            for target in self.callable_targets
                        )
                    )
                )
                if (
                    self.key not in self.class_targets
                    and (
                        self.class_repair_attempts.get(self.key, 0) < 2
                        or self.signature_repetitions.get(self.signature, 0) <= 1
                    )
                    and (
                        self.class_named_in_state_failure
                        or self.frozen_record_state_failure
                        or self.coordinated_ui_architecture_failure
                        or self.import_surface_failure
                        or self.shared_state_class_failure
                        or self.approved_class_failure
                        or self.exact_class_failure
                        or self.planned_attribute_failure
                        or self.class_attribute_failure
                    )
                ):
                    self.class_targets.append(self.key)
        if self.harness_oracle_invalid:
            self.class_targets = [
                key
                for key in self.class_targets
                if _deps.Path(key[0]).name.startswith("test_")
            ]
            self.wiring_target = None
        self.module_or_package_failure = any(
            (
                error.startswith(("[scope:module]", "[scope:package]"))
                for error in self.errors
            )
        )
        self.planned_class_attribute_names = {
            str(attribute.get("name") or "")
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, dict) and str(chunk.get("kind") or "") == "class"
            for attribute in (chunk.get("declaration_contract") or {}).get("attributes")
            or []
            if isinstance(attribute, dict) and str(attribute.get("name") or "")
        }
        self.unique_missing_class_declarations = set(
            _deps.re.findall(
                r"approved (?:method|callable) `([^`]+)` is missing",
                self.error_blob,
            )
        )
        self.coherent_class_repair_required = bool(
            "[repair-scope:class]" in self.error_blob
            or "approved synchronization boundary is missing" in self.error_blob
            or len(self.unique_missing_class_declarations) >= 2
            or "private helper callable(s) are never referenced" in self.error_blob
            or "off-UI-thread contract" in self.error_blob
            or ("background worker" in self.error_blob)
            or ("background execution" in self.error_blob)
            or ("terminal handler must release retained worker" in self.error_blob)
            or any(
                (name in self.error_blob for name in self.planned_class_attribute_names)
            )
        )
        self.callable_targets = _deps._augment_callable_targets_from_validation_causes(
            self.generated_files, self.errors, self.callable_targets
        )
        self.stalled_callable_keys = {
            (str(_deps.Path(path).resolve()), symbol)
            for path, symbol in self.stalled_callable_symbols
        }
        self.callable_targets = [
            target
            for target in self.callable_targets
            if (
                str(_deps.Path(str(target.get("path") or "")).resolve()),
                str(target.get("symbol") or ""),
            )
            not in self.stalled_callable_keys
        ]
        self.exact_callable_class_keys = {
            (
                str(_deps.Path(str(target.get("path") or "")).resolve()),
                str(target.get("symbol") or "").split(".", 1)[0],
            )
            for target in self.callable_targets
            if "." in str(target.get("symbol") or "")
        }
        self.resolved_class_target_keys = {
            (str(_deps.Path(path).resolve()), class_name)
            for path, class_name in self.class_targets
        }
        if self.coherent_class_repair_required:
            self.callable_targets = [
                target
                for target in self.callable_targets
                if (
                    str(_deps.Path(str(target.get("path") or "")).resolve()),
                    str(target.get("symbol") or "").split(".", 1)[0],
                )
                not in self.resolved_class_target_keys
            ]
        else:
            self.class_targets = [
                key
                for key in self.class_targets
                if (str(_deps.Path(key[0]).resolve()), key[1])
                not in self.exact_callable_class_keys
            ]
        if self.status_callback:
            self.status_callback(
                "Repair ownership candidates: "
                + "callables=["
                + ", ".join(
                    (
                        str(target.get("symbol") or "")
                        for target in self.callable_targets
                    )
                )
                + "]; classes=["
                + ", ".join((name for _path, name in self.class_targets))
                + "]; wiring="
                + (
                    str(self.wiring_target.get("symbol") or "")
                    if self.wiring_target
                    else "none"
                )
                + f"; coherent_class={self.coherent_class_repair_required}"
            )
        if (
            len(self.unique_missing_class_declarations) == 1
            and len(self.class_targets) == 1
            and not self.coherent_class_repair_required
            and not self.fixture_targets
        ):
            self.missing_member_name = next(
                iter(self.unique_missing_class_declarations)
            )
            self.missing_member_path, self.missing_member_class = self.class_targets[0]
            self.missing_member_entry = next(
                (
                    entry
                    for entry in self.generated_files
                    if str(_deps.Path(entry[0]).resolve())
                    == str(_deps.Path(self.missing_member_path).resolve())
                ),
                None,
            )
            if self.missing_member_entry is not None:
                self.missing_member_stage = _deps.build_project_edit_missing_symbol_stage(
                    path=self.missing_member_path,
                    symbol=self.missing_member_name,
                    container=self.missing_member_class,
                    source=self.missing_member_entry[2],
                    objective=self.prompt,
                    contracts=[
                        error
                        for error in self.errors
                        if self.missing_member_name in error
                    ],
                    algorithm_steps=[
                        str(requirement.get("text") or "")
                        for chunk in self.implementation_plan.get("chunks") or []
                        if isinstance(chunk, dict)
                        and str(chunk.get("owner") or "") == self.missing_member_class
                        for requirement in chunk.get("requirements") or []
                        if isinstance(requirement, dict)
                        and self.missing_member_name
                        in str(requirement.get("text") or "")
                    ],
                )
                if self.status_callback:
                    self.status_callback(
                        f"Implementing only missing member {self.missing_member_class}."
                        f"{self.missing_member_name}; preserving the accepted class body."
                    )
                self.missing_member_response, self.missing_member_timing = (
                    _deps._query_stage(
                        self.missing_member_stage,
                        selected_model=self.selected_model,
                        settings=self.settings,
                        timeout=self.timeout,
                    )
                )
                self.missing_member_timing.update(
                    {
                        "attempt": self.attempt + 1,
                        "path": self.missing_member_path,
                        "symbol": f"{self.missing_member_class}.{self.missing_member_name}",
                        "stage": "focused_missing_member_repair",
                    }
                )
                self.timings.append(self.missing_member_timing)
                self.missing_member_apply_response = self.missing_member_response
                try:
                    self.missing_member_response_tree = _deps.ast.parse(
                        self.missing_member_response
                    )
                except SyntaxError:
                    self.missing_member_response_tree = None
                self.missing_member_nodes = [
                    node
                    for node in _deps.ast.walk(self.missing_member_response_tree)
                    if isinstance(
                        node, (_deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef)
                    )
                    and node.name == self.missing_member_name
                ] if self.missing_member_response_tree is not None else []
                if len(self.missing_member_nodes) == 1:
                    self.missing_member_node_source = _deps.ast.unparse(
                        self.missing_member_nodes[0]
                    )
                    self.missing_member_apply_response = (
                        f"class {self.missing_member_class}:\n"
                        + "\n".join(
                            " " * 4 + line
                            for line in self.missing_member_node_source.splitlines()
                        )
                        + "\n"
                    )
                (
                    self.missing_member_source,
                    self.missing_member_errors,
                ) = _deps.apply_project_edit_missing_symbol(
                    self.missing_member_entry[2],
                    path=self.missing_member_path,
                    symbol=self.missing_member_name,
                    response=self.missing_member_apply_response,
                    objective=self.prompt,
                )
                if not self.missing_member_errors:
                    self.generated_files = [
                        (
                            path,
                            original,
                            self.missing_member_source
                            if str(_deps.Path(path).resolve())
                            == str(_deps.Path(self.missing_member_path).resolve())
                            else source,
                        )
                        for path, original, source in self.generated_files
                    ]
                    self.generated_files = _deps._normalize_generated_files(
                        self.generated_files,
                        project_root=self.root,
                        request_prompt=self.prompt,
                    )
                    self.candidate = _deps.build_project_edit_multi_file_candidate(
                        self.generated_files
                    )
                    raise _WorkflowContinue()
                if self.status_callback:
                    self.status_callback(
                        "Rejected bounded missing-member repair: "
                        + " | ".join(self.missing_member_errors)
                    )
        if (
            self.class_targets
            and (not self.callable_targets or self.coherent_class_repair_required)
            and (self.wiring_target is None or self.coherent_class_repair_required)
            and (not self.fixture_targets)
        ):
            self.class_targets.sort(
                key=lambda key: sum(
                    (
                        1
                        for error in self.errors
                        if key[1] in error
                        and (key[0] in error or _deps.Path(key[0]).name in error)
                    )
                ),
                reverse=True,
            )
            self.class_targets = self.class_targets[:1]
            for self.class_path, self.class_name in self.class_targets:
                self.class_repair_attempts[self.class_path, self.class_name] = (
                    self.class_repair_attempts.get(
                        (self.class_path, self.class_name), 0
                    )
                    + 1
                )
            self.class_error_source = (
                self.validation_snapshot_errors
                if self.coherent_class_repair_required
                else self.errors
            )
            self.class_owned_errors = [
                error
                for error in self.class_error_source
                if any(
                    (
                        class_name in error
                        and (
                            class_path in error or _deps.Path(class_path).name in error
                        )
                        for class_path, class_name in self.class_targets
                    )
                )
            ] or self.class_error_source
            self.class_owned_errors.extend(
                error
                for key in self.class_targets
                for error in self.class_repair_rejections.get(key, [])
            )
            self.compact_repair_chunks = []
            for self.chunk in self.implementation_plan.get("chunks") or []:
                if not isinstance(self.chunk, dict) or not any(
                    (
                        str(_deps.Path(str(self.chunk.get("path") or "")).resolve())
                        == str(_deps.Path(class_path).resolve())
                        and str(self.chunk.get("owner") or "") == class_name
                        for class_path, class_name in self.class_targets
                    )
                ):
                    continue
                self.compact_repair_chunks.append(
                    {
                        "chunk_id": str(self.chunk.get("chunk_id") or ""),
                        "path": str(self.chunk.get("path") or ""),
                        "owner": str(self.chunk.get("owner") or ""),
                        "kind": str(self.chunk.get("kind") or ""),
                        "requirements": list(self.chunk.get("requirements") or []),
                        "depends_on": list(self.chunk.get("depends_on") or []),
                        "declaration_contract": dict(
                            self.chunk.get("declaration_contract") or {}
                        ),
                        "implementation_mechanics": list(
                            self.chunk.get("implementation_mechanics") or []
                        ),
                        "selected_evidence": [
                            {
                                "name": str(item.get("name") or ""),
                                "signature": str(item.get("signature") or ""),
                                "usage_role": str(item.get("usage_role") or "invoke"),
                                "import_statement": str(
                                    item.get("import_statement") or ""
                                ),
                            }
                            for item in self.chunk.get("evidence") or []
                            if isinstance(item, dict)
                            and (
                                item.get("selected_for_generation")
                                or item.get("dependency_for_selected")
                            )
                        ],
                    }
                )
            self.targeted_class_contract = _deps.json.dumps(
                {
                    "original_request": self.user_prompt,
                    "chunks": self.compact_repair_chunks,
                },
                ensure_ascii=True,
            )
            self.class_stage = _deps.build_project_edit_class_set_repair_stage(
                self.generated_files,
                class_targets=self.class_targets,
                objective=self.prompt,
                approved_contract=self.targeted_class_contract,
                validation_errors=self.class_owned_errors,
                repair_attempt=max(
                    (self.class_repair_attempts[key] for key in self.class_targets)
                ),
            )
            if self.shared_state_assertion_failure and any(
                (
                    not _deps.Path(path).name.startswith("test_")
                    for path, _class_name in self.class_targets
                )
            ):
                self.class_stage = _deps.replace(
                    self.class_stage,
                    user_prompt=self.class_stage.user_prompt
                    + "\n\nSHARED STATE INVARIANT REPAIR:\nSeveral public observers fail after the same state-changing operations. Before\nwriting code, derive a compact invariant table for every instance container:\nsemantic key, semantic value, writer methods, and reader methods. Then return\nthe requested class chunk with one consistent representation.\n\n- Repair the earliest shared state write that contradicts multiple readers;\n  do not compensate independently in each observer.\n- For forward and reverse relationship mappings, update both directions\n  atomically and make key/value orientation agree with public method names.\n- Preserve insertion-order and priority requirements independently; never use\n  a deque-only operation on a list or a list-only operation on another type.\n- Query methods must not consume or mutate stored scheduling state.\n- Removal must inspect the reverse relationship before deleting, then clean\n  both directions without invoking unrelated query behavior for side effects.\n- Reconcile every changed writer with every reader in this returned class.\n- The returned class must materially change the executable invariant that\n  caused the supplied assertion diffs; formatting-only changes are invalid.\n",
                )
            if all(
                (
                    _deps.Path(path).name.startswith("test_")
                    for path, _class_name in self.class_targets
                )
            ):
                self.verified_boundaries = _deps._verified_external_boundary_targets(
                    self.generated_files, self.root
                )
                self.class_stage = _deps.replace(
                    self.class_stage,
                    user_prompt=self.class_stage.user_prompt
                    + "\n\nFOCUSED GENERATED TEST REPAIR CONTRACT:\n- Preserve one substantive test for every explicitly requested behavior.\n- Success fixtures must satisfy production invariants; invalid fixtures belong only\n  inside an explicit negative assertion for requested rejection behavior.\n- Mock or inject process, network, filesystem, clock, desktop, and host boundaries.\n  Never execute real external commands or depend on platform-specific output.\n- Patch only the exact symbol looked up by production, using its complete\n  package-qualified module path. Verify the target exists in the current production\n  source; never invent a convenience wrapper solely for a test.\n- Construct production classes and call their methods with the exact signatures shown\n  in the current generated package. Do not rename constructor parameters, replace\n  record objects with strings, or call unrelated methods as substitutes.\n- The only allowed external patch/injection targets are:\n"
                    + (
                        "\n".join(
                            (f"  - {target}" for target in self.verified_boundaries)
                        )
                        if self.verified_boundaries
                        else "  - (none; do not invent an external target)"
                    )
                    + "\n- Never invent a module, wrapper, function, or attribute for a patch target.\n- Every fixture that can trigger an external command must consume one verified\n  target above through `patch`, `patch.object`, or dependency injection. For an\n  async target, use `AsyncMock` and configure a valid awaited return value matching\n  the current production signature. Returning an unmocked command fixture is invalid.\n- Consume every constructed fixture through the real public API and assert observable\n  results. Do not weaken production behavior to make a stale test pass.\n",
                )
            if any(
                (
                    "full-screen/virtual-desktop pick surface" in error
                    for error in self.errors
                )
            ):
                self.class_stage = _deps.replace(
                    self.class_stage,
                    user_prompt=self.class_stage.user_prompt
                    + "\n\nVERIFIED QT DESKTOP-EYEDROPPER SHAPE:\n- Keep every operation inside methods declared in the returned class. Do not call\n  undeclared convenience helpers.\n- Configure the overlay with\n  self.setCursor(Qt.CursorShape.CrossCursor) and a full-screen or virtual-desktop\n  geometry.\n- Construct the overlay during owner setup but do not show it until the connected\n  activation handler runs. Activation must show, raise, focus, and crosshair the\n  overlay.\n- Use one consistent discovered overlay attribute throughout the class. Never\n  invent a second overlay attribute during repair.\n- Cleanup may run before activation starts, but never set the active flag and then\n  immediately call cleanup. The activation handler must finish in the active state\n  with its timer running and overlay visible.\n- Save the pre-pick hexadecimal value before sampling changes any widget. Escape\n  must restore that exact saved value and its preview before cleanup.\n- Put screen capture in one class-owned helper accepting an explicit global point.\n  Timer sampling passes QCursor.pos(); left-click commit passes the event's\n  globalPosition().toPoint() (or the verified binding equivalent), samples that\n  exact point, updates the widgets, emits the resulting string, then cleans up.\n- Before QScreen.grabWindow(0), hide the actual overlay attribute and process Qt\n  events; after sampling, show/raise/focus it again only while picking remains\n  active. Never hide the owning dialog as a substitute for hiding the overlay.\n- Convert the returned QPixmap with toImage(), call pixelColor(local_x, local_y),\n  and format the QColor through its verified name()/channel API. Do not apply\n  integer bit operations to QColor.\n- Use QApplication.setOverrideCursor(Qt.CursorShape.CrossCursor) and balanced\n  QApplication.restoreOverrideCursor() calls; do not call QCursor.setShape as a\n  class method.\n- The returned class must declare mousePressEvent(self, event),\n  mouseReleaseEvent(self, event), or eventFilter(self, watched, event). A button\n  may activate/show the overlay, but its clicked handler must not immediately\n  sample the button position.\n- In the click handler, obtain the global point, hide the overlay, call\n  QApplication.processEvents(), select the owning screen with\n  QGuiApplication.screenAt(global_point) (falling back to primaryScreen), then\n  sample that screen.\n- Preview capture must hide the overlay object, never the dialog. If picking remains\n  active after preview capture, show/raise/focus the overlay again.\n- Convert global coordinates to screen-local coordinates using screen.geometry().\n- Capture with screen.grabWindow(0), convert with pixmap.toImage(), and read with\n  image.pixelColor(local_x, local_y).\n- Return or display the real QColor. Never use a fixed RGB fallback.\n- Save the current displayed color when activation begins. Escape must restore that\n  saved color and the dialog visibility. A left click must sample its own event global\n  position, update the preview/value, emit that exact committed hex value, clean up,\n  and restore the dialog visibility.\n- Do not introduce a method call unless that method is included in this returned\n  class chunk.\n",
                )
            if all(
                (
                    _deps.Path(path).name.startswith("test_")
                    for path, _class_name in self.class_targets
                )
            ) and _deps.re.search(
                "\\b(?:anywhere|desktop|screen)\\b",
                self.prompt,
                flags=_deps.re.IGNORECASE,
            ):
                self.class_stage = _deps.replace(
                    self.class_stage,
                    user_prompt=self.class_stage.user_prompt
                    + "\n\nFOCUSED QT EYEDROPPER TEST CONTRACT:\n- Test only the finalized production class API visible in the dependency context.\n  Do not preserve stale methods, geometry values, or expectations.\n- Reuse QApplication.instance(); never create or destroy a second application.\n- Do not inspect live desktop colors or assume display geometry. Mock/inject the\n  QScreen, QPixmap, QImage, and QColor boundary used by production.\n- Use a constructor signature verified by the installed Qt API or QTest helpers;\n  never invent a shortened QMouseEvent constructor.\n- Prove construction, crosshair/global pick activation, clicked-color readback,\n  and label/signal output. Return exactly the requested test class.\n",
                )
            if self.status_callback:
                self.class_repair_attempt = max(
                    (self.class_repair_attempts[key] for key in self.class_targets)
                )
                self.class_repair_model = _deps._strong_task_model(self.selected_model)
                self.status_callback(
                    "Repairing coherent class chunks: "
                    + ", ".join((name for _path, name in self.class_targets))
                    + f" with {self.class_repair_model}"
                )
            else:
                self.class_repair_attempt = max(
                    (self.class_repair_attempts[key] for key in self.class_targets)
                )
                self.class_repair_model = _deps._strong_task_model(self.selected_model)
            self.class_response, self.class_timing = _deps._query_stage(
                self.class_stage,
                selected_model=self.class_repair_model,
                settings=self.settings,
                timeout=self.timeout,
            )
            self.class_timing.update(
                {
                    "attempt": self.attempt + 1,
                    "path": ", ".join((path for path, _name in self.class_targets)),
                    "symbol": ", ".join((name for _path, name in self.class_targets)),
                    "stage": "focused_class_set_repair",
                }
            )
            self.timings.append(self.class_timing)
            self.class_baseline_files = list(self.generated_files)
            self.proposed_class_files, self.class_errors = (
                _deps.apply_project_edit_generated_class_set_repair(
                    self.class_baseline_files,
                    class_targets=self.class_targets,
                    replacement_response=self.class_response,
                )
            )
            if not self.class_errors:
                self.proposed_class_files = _deps._normalize_generated_files(
                    self.proposed_class_files,
                    project_root=self.root,
                    request_prompt=self.prompt,
                )
                self.proposed_class_files = _deps._enforce_manifest_symbol_owners(
                    self.proposed_class_files,
                    self.symbol_owners,
                    project_root=self.root,
                )
                self.proposed_class_files, self._cross_file_repairs = (
                    _deps.resolve_project_edit_cross_file_symbols(
                        self.proposed_class_files, project_root=self.root
                    )
                )
                self.proposed_class_files, self._post_class_import_repairs = (
                    _deps._repair_proven_import_surface(
                        self.proposed_class_files,
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
                self.proposed_class_quality_errors = (
                    _deps._repair_phase_validation_errors(
                        self.proposed_class_files,
                        implementation_plan=self.implementation_plan,
                        project_root=self.root,
                        request_prompt=self.prompt,
                    )
                )
                (
                    self.proposed_class_files,
                    self._post_class_public_surface_repairs,
                ) = _deps._repair_locked_undeclared_public_methods(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                (
                    self.proposed_class_files,
                    self._post_class_else_repairs,
                ) = _deps._repair_unnecessary_terminating_else_branches(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                (
                    self.proposed_class_files,
                    self._post_class_ttl_recency_repairs,
                ) = _deps._repair_shared_ttl_recency_index(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                (
                    self.proposed_class_files,
                    self._post_class_command_registry_repairs,
                ) = _deps._repair_shared_command_registry(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                if self._post_class_ttl_recency_repairs and self.status_callback:
                    self.status_callback(
                        "Applied deterministic class invariant repair: "
                        + "; ".join(self._post_class_ttl_recency_repairs)
                    )
                (
                    self.proposed_class_files,
                    self._post_class_quality_repairs,
                ) = _deps._repair_standardized_local_quality_issues(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                (
                    self.proposed_class_files,
                    self._post_class_contract_repairs,
                ) = _deps._repair_requested_python_contract_surface(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                    request_prompt=self.prompt,
                )
                (
                    self.proposed_class_files,
                    self._post_class_lock_repairs,
                ) = _deps._repair_nested_non_reentrant_locks(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                (
                    self.proposed_class_files,
                    self._post_class_sync_repairs,
                ) = _deps._repair_missing_synchronization_boundaries(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                self.proposed_class_quality_errors = (
                    _deps._repair_phase_validation_errors(
                        self.proposed_class_files,
                        implementation_plan=self.implementation_plan,
                        project_root=self.root,
                        request_prompt=self.prompt,
                    )
                )
                (
                    self.proposed_class_files,
                    self._post_class_bool_repairs,
                ) = _deps._repair_explicit_bool_rejections(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                (
                    self.proposed_class_files,
                    self._post_class_guard_repairs,
                ) = _deps._repair_pre_mutation_rejection_guards(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                (
                    self.proposed_class_files,
                    self._post_class_limit_repairs,
                ) = _deps._repair_reached_limit_off_by_one(
                    self.proposed_class_files,
                    self.proposed_class_quality_errors,
                )
                for self._stabilization_pass in range(4):
                    self._stabilization_before = (
                        _deps._candidate_checkpoint_fingerprint(
                            _deps.build_project_edit_multi_file_candidate(
                                self.proposed_class_files
                            )
                        )
                    )
                    self.proposed_class_quality_errors = (
                        _deps._repair_phase_validation_errors(
                            self.proposed_class_files,
                            implementation_plan=self.implementation_plan,
                            project_root=self.root,
                            request_prompt=self.prompt,
                        )
                    )
                    (
                        self.proposed_class_files,
                        self._stabilized_public_repairs,
                    ) = _deps._repair_locked_undeclared_public_methods(
                        self.proposed_class_files,
                        self.proposed_class_quality_errors,
                    )
                    (
                        self.proposed_class_files,
                        self._stabilized_else_repairs,
                    ) = _deps._repair_unnecessary_terminating_else_branches(
                        self.proposed_class_files,
                        self.proposed_class_quality_errors,
                    )
                    (
                        self.proposed_class_files,
                        self._stabilized_ttl_recency_repairs,
                    ) = _deps._repair_shared_ttl_recency_index(
                        self.proposed_class_files,
                        self.proposed_class_quality_errors,
                    )
                    (
                        self.proposed_class_files,
                        self._stabilized_command_registry_repairs,
                    ) = _deps._repair_shared_command_registry(
                        self.proposed_class_files,
                        self.proposed_class_quality_errors,
                    )
                    if (
                        self._stabilized_ttl_recency_repairs
                        and self.status_callback
                    ):
                        self.status_callback(
                            "Applied deterministic stabilized class invariant repair: "
                            + "; ".join(self._stabilized_ttl_recency_repairs)
                        )
                    (
                        self.proposed_class_files,
                        self._stabilized_contract_repairs,
                    ) = _deps._repair_requested_python_contract_surface(
                        self.proposed_class_files,
                        self.proposed_class_quality_errors,
                        request_prompt=self.prompt,
                    )
                    (
                        self.proposed_class_files,
                        self._stabilized_type_repairs,
                    ) = _deps._repair_inferred_collection_type_hints(
                        self.proposed_class_files
                    )
                    self._stabilization_after = (
                        _deps._candidate_checkpoint_fingerprint(
                            _deps.build_project_edit_multi_file_candidate(
                                self.proposed_class_files
                            )
                        )
                    )
                    if self._stabilization_after == self._stabilization_before:
                        break
                self.proposed_class_files = _deps._normalize_generated_files(
                    self.proposed_class_files,
                    project_root=self.root,
                    request_prompt=self.prompt,
                )
                self.class_target_paths = {
                    str(_deps.Path(path).resolve())
                    for path, _class_name in self.class_targets
                }
                self.class_baseline_by_path = {
                    str(_deps.Path(path).resolve()): (path, original, source)
                    for path, original, source in self.class_baseline_files
                }
                self.proposed_class_files = [
                    (
                        entry
                        if str(_deps.Path(entry[0]).resolve())
                        in self.class_target_paths
                        else self.class_baseline_by_path.get(
                            str(_deps.Path(entry[0]).resolve()), entry
                        )
                    )
                    for entry in self.proposed_class_files
                ]
                self.class_baseline_validation_files = list(self.class_baseline_files)
                self.proposed_class_validation_files = list(self.proposed_class_files)
                if self.ephemeral_validation_path and self.harness_source:
                    self.class_baseline_validation_files.append(
                        (self.ephemeral_validation_path, "", self.harness_source)
                    )
                    self.proposed_class_validation_files.append(
                        (self.ephemeral_validation_path, "", self.harness_source)
                    )
                self.class_errors.extend(
                    _deps._monotonic_repair_rejections(
                        self.class_baseline_validation_files,
                        self.proposed_class_validation_files,
                        repair_targets=self.class_targets,
                        assigned_errors=self.class_owned_errors,
                        implementation_plan=self.implementation_plan,
                        project_root=self.root,
                        request_prompt=self.prompt,
                        harness_path=(
                            self.ephemeral_validation_path
                            if self.ephemeral_validation_path and self.harness_source
                            else ""
                        ),
                    )
                )
            if not self.class_errors:
                self.generated_files = self.proposed_class_files
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                raise _WorkflowContinue()
            if (
                self.class_errors
                and max((self.class_repair_attempts[key] for key in self.class_targets))
                < 2
            ):
                for key in self.class_targets:
                    self.class_repair_rejections[key] = list(self.class_errors)
                if self.status_callback:
                    self.status_callback(
                        "Class repair was rejected by owner-safety validation ("
                        + "; ".join(self.class_errors)
                        + "); changing strategy for one bounded owner-only retry."
                    )
                raise _WorkflowContinue()
            if self.status_callback:
                self.status_callback(
                    "Rejected coherent class chunks: " + "; ".join(self.class_errors)
                )
