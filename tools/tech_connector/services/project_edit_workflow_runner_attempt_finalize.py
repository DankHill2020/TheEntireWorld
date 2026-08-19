"""Project-edit workflow phase: _run_attempt_finalize_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import (
    _WorkflowReturn,
    _WorkflowBreak,
    _WorkflowContinue,
)


def _bounded_repair_model_sequence(
    models: list[str],
    *,
    one_shot: bool,
) -> list[str]:
    """Build a bounded repair ladder without erasing feedback retries.

    :param models: Preferred model sequence from compact to strong.
    :param one_shot: Whether the diagnostic is a deterministic mechanical fix.
    :return: One or two model slots for the focused repair loop.
    """

    unique_models = list(dict.fromkeys(model for model in models if model))
    if not unique_models:
        return []
    if one_shot:
        return unique_models[:1]
    if len(unique_models) == 1:
        return [unique_models[0], unique_models[0]]
    return unique_models[:2]


class _ProjectEditAttemptFinalizePhase:
    """Provide the attempt finalize workflow phase."""

    def _run_attempt_finalize_phase(self) -> None:
        """Run the attempt finalize phase.

        :return: None.
        """
        if self.callable_targets:
            self.generated_files, self.early_path_policy_repairs = (
                _deps._repair_explicit_path_policy_semantics(
                    self.generated_files,
                    request_prompt=self.prompt,
                )
            )
            self.generated_files, self.early_delegation_repairs = (
                _deps._repair_explicit_cross_file_delegation(
                    self.generated_files,
                    request_prompt=self.prompt,
                )
            )
            self.early_explicit_contract_repairs = [
                *self.early_path_policy_repairs,
                *self.early_delegation_repairs,
            ]
            if self.early_explicit_contract_repairs:
                self.delegated_owners = {
                    note.split(":", 1)[1].split(" ", 1)[0]
                    for note in self.early_delegation_repairs
                    if ":" in note
                }
                self.delegated_chunk_ids = {
                    str(chunk.get("chunk_id") or "")
                    for chunk in self.implementation_plan.get("chunks") or []
                    if isinstance(chunk, _deps.Mapping)
                    and str(chunk.get("owner") or "") in self.delegated_owners
                }
                for self.coverage_row in self.chunk_coverage:
                    if (
                        str(self.coverage_row.get("chunk_id") or "")
                        in self.delegated_chunk_ids
                    ):
                        self.coverage_row.update(
                            implemented=True,
                            validated=True,
                            assembled=True,
                        )
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
                        "Applied explicit cross-file contract before model repair: "
                        + "; ".join(self.early_explicit_contract_repairs)
                    )
                raise _WorkflowContinue()
            self.repaired_any = False
            self.callable_repair_errors: list[str] = []
            for self.target in self.callable_targets:
                self.target_repaired = False
                self.target_is_harness = bool(
                    self.ephemeral_validation_path
                    and str(self.target.get("path") or "")
                    == self.ephemeral_validation_path
                )
                self.repair_scope_files = (
                    self.active_validation_files
                    if self.target_is_harness
                    else self.generated_files
                )
                self.target_key = (str(self.target["path"]), str(self.target["symbol"]))
                self.target_owner_name, self._, self.target_method_name = str(
                    self.target["symbol"]
                ).partition(".")
                if not self.target_method_name:
                    self.target_method_name = self.target_owner_name
                self.approved_signature = next(
                    (
                        str(signature)
                        for plan_chunk in self.implementation_plan.get("chunks") or []
                        if isinstance(plan_chunk, dict)
                        and str(plan_chunk.get("owner") or "") == self.target_owner_name
                        and (
                            _deps.Path(str(plan_chunk.get("path") or "")).resolve()
                            == _deps.Path(str(self.target["path"])).resolve()
                        )
                        for signature in (
                            plan_chunk.get("declaration_contract") or {}
                        ).get("callable_signatures")
                        or []
                        if _deps.re.search(
                            f"\\bdef\\s+{_deps.re.escape(self.target_method_name)}\\s*\\(",
                            str(signature),
                        )
                    ),
                    "",
                )
                self.snapshot_owner_plan = self.snapshot_plan_by_owner.get(
                    self.target_key
                )
                self.target_errors = _deps._callable_failure_evidence(
                    self.validation_snapshot_errors,
                    str(self.target.get("symbol") or ""),
                )
                self.owner_plan_chunk = next(
                    (
                        chunk
                        for chunk in self.implementation_plan.get("chunks") or []
                        if isinstance(chunk, _deps.Mapping)
                        and str(chunk.get("owner") or "") == self.target_owner_name
                        and (
                            _deps.Path(str(chunk.get("path") or "")).resolve()
                            == _deps.Path(str(self.target["path"])).resolve()
                        )
                    ),
                    {},
                )
                self.causal_owner_errors = [
                    error
                    for error in self.validation_snapshot_errors
                    if (
                        str(self.target.get("path") or "") in error
                        or _deps.Path(str(self.target.get("path") or "")).name in error
                    )
                    and _deps.re.search(
                        f":{_deps.re.escape(self.target_owner_name)}(?:\\.|:)", error
                    )
                ]
                self.target_errors = list(
                    dict.fromkeys([*self.target_errors, *self.causal_owner_errors])
                )
                self.repair_terms = {
                    self.target_method_name.casefold(),
                    *(
                        value.casefold()
                        for error in self.target_errors
                        for value in _deps.re.findall(
                            "`([A-Za-z_][A-Za-z0-9_.]*)`", error
                        )
                    ),
                }
                self.target_error_text = "\n".join(self.target_errors).casefold()
                if "progress" in self.target_error_text:
                    self.repair_terms.update({"progress", "callback"})
                if "signal" in self.target_error_text:
                    self.repair_terms.update({"signal", "emit"})
                if "import" in self.target_error_text:
                    self.repair_terms.add("import")
                self.relevant_mechanics: list[dict[str, _deps.Any]] = []
                for self.row in (
                    self.owner_plan_chunk.get("implementation_mechanics") or []
                ):
                    if not isinstance(self.row, _deps.Mapping):
                        continue
                    self.relevant_steps = [
                        str(step)
                        for step in self.row.get("steps") or []
                        if any(
                            (
                                term and term in str(step).casefold()
                                for term in self.repair_terms
                            )
                        )
                    ]
                    if self.relevant_steps:
                        self.relevant_mechanics.append(
                            {
                                "requirement_id": str(
                                    self.row.get("requirement_id") or ""
                                ),
                                "steps": self.relevant_steps,
                            }
                        )
                self.evidence_required = any(
                    (
                        marker in self.target_error_text
                        for marker in (
                            "api",
                            "attribute access",
                            "import",
                            "mapping",
                            "signature",
                            "undefined",
                            "unverified",
                        )
                    )
                )
                self.relevant_requirement_ids = {
                    str(row.get("requirement_id") or "")
                    for row in self.relevant_mechanics
                    if str(row.get("requirement_id") or "")
                }
                self.relevant_requirements: list[_deps.Any] = []
                for self.requirement in self.owner_plan_chunk.get("requirements") or []:
                    if isinstance(self.requirement, _deps.Mapping):
                        self.requirement_id = str(
                            self.requirement.get("id")
                            or self.requirement.get("requirement_id")
                            or ""
                        )
                        if (
                            self.relevant_requirement_ids
                            and self.requirement_id not in self.relevant_requirement_ids
                        ):
                            continue
                        self.relevant_requirements.append(
                            {
                                key: self.requirement.get(key)
                                for key in ("id", "requirement_id", "text")
                                if self.requirement.get(key)
                            }
                        )
                    else:
                        self.requirement_id = str(self.requirement)
                        if (
                            self.relevant_requirement_ids
                            and self.requirement_id not in self.relevant_requirement_ids
                        ):
                            continue
                        self.relevant_requirements.append(self.requirement_id)
                self.owner_capsule = {
                    "owner": str(self.target.get("symbol") or ""),
                    "signature": self.approved_signature,
                    "requirements": self.relevant_requirements,
                    "mechanics": self.relevant_mechanics,
                    "evidence": [
                        {
                            key: (
                                str(item.get(key) or "")[-1600:]
                                if key == "source"
                                else item.get(key)
                            )
                            for key in (
                                "qualified_name",
                                "signature",
                                "return_annotation",
                                "source",
                                "import_statement",
                            )
                            if item.get(key)
                        }
                        for item in self.owner_plan_chunk.get("evidence") or []
                        if isinstance(item, _deps.Mapping)
                        and self.evidence_required
                        and (
                            bool(item.get("selected_for_generation"))
                            or bool(item.get("dependency_for_selected"))
                        )
                    ],
                }
                self.target_has_explicit_mechanical_fix = any(
                    (
                        marker in self.target_error_text
                        for marker in (
                            "all progress updates occur after",
                            "approved attribute",
                            "declared but never emitted",
                            "must inject",
                            "missing required import",
                            "not valid python",
                            "qt signal declaration",
                            "reconstructed outside",
                            "returns mapping records",
                            "internal dependency returns mapping",
                            "do not prove requested key",
                            "syntaxerror",
                            "worker operation passes",
                        )
                    )
                )
                if any(
                    (
                        "progress updates require at least two observable callback invocations"
                        in error
                        or "all progress updates occur after the approved work" in error
                        for error in self.target_errors
                    )
                ):
                    self.target_errors.append(
                        "PROGRESS LIFECYCLE REPAIR: Emit integer progress through the approved callback before the first blocking or dependency operation, emit completion after the work, and ensure at least two statically observable callback sites. Progress must describe the real operation; do not add a cosmetic post-processing loop."
                    )
                self.unused_attributes = list(
                    dict.fromkeys(
                        (
                            match.group(1)
                            for error in self.target_errors
                            for match in [
                                _deps.re.search(
                                    "approved attribute `([^`]+)` is constructed but has no meaningful runtime read",
                                    error,
                                )
                            ]
                            if match
                        )
                    )
                )
                if self.unused_attributes:
                    self.target_errors.append(
                        "INPUT CONSUMPTION REPAIR: Read and meaningfully apply these approved inputs in this callable's real result or state transition: "
                        + ", ".join(self.unused_attributes)
                        + ". Do not satisfy this by assigning, discarding, or displaying a synthetic value; preserve the owner mechanics and observable request semantics."
                    )
                self.approved_behavior_rows = _deps._expanded_ephemeral_behavior_rows(
                    self.implementation_plan, generated_files=self.generated_files
                )
                if self.target_is_harness:
                    self.harness_bindings, self._binding_errors = (
                        _deps._ephemeral_behavior_bindings(self.harness_source)
                    )
                    self.target_behavior_ids = set(
                        self.harness_bindings.get(
                            str(self.target.get("symbol") or "").rsplit(".", 1)[-1], []
                        )
                    )
                    self.target_behavior_contracts = [
                        contract
                        for contract in self.approved_behavior_rows
                        if str(contract.get("behavior_id") or "")
                        in self.target_behavior_ids
                    ]
                else:
                    self.target_behavior_contracts = [
                        contract
                        for contract in self.approved_behavior_rows
                        if any(
                            (
                                str(owner.get("symbol") or "")
                                == str(self.target.get("symbol") or "")
                                for owner in contract.get("production_owners") or []
                                if isinstance(owner, _deps.Mapping)
                            )
                        )
                    ]
                if self.target_behavior_contracts:
                    self.target_errors = [
                        _deps.re.sub(
                            "\\s+Smallest repair:.*\\Z",
                            "",
                            error,
                            flags=_deps.re.DOTALL | _deps.re.IGNORECASE,
                        ).strip()
                        for error in self.target_errors
                    ]
                    self.target_errors.append(
                        "CONTRACT PRECEDENCE: Treat the approved behavior contracts and their expected observations as authoritative. Reviewer findings identify failed behavior but do not prescribe implementation. Repair the observable behavior, not merely annotations, container syntax, or formatting. When an observation mutates nested values returned by an owner and requires the owner's state to remain unchanged, the returned object graph must not share mutable references with that internal state. Detaching data must preserve every field value not explicitly named as changing; do not invoke an unrelated public transformation merely to construct the detached result."
                    )
                    if self.target_is_harness:
                        self.target_errors.append(
                            "DISPOSABLE TEST REPAIR BOUNDARY: The target is one generated test method, not production code. Preserve its valid setup and assertions, execute every exact production owner required by the bound behavior contract, consume or remove every fixture variable, and add the smallest direct public-API assertion that proves the failed observation. Do not reimplement the production algorithm, edit a production callable, return another test method, or return the whole test module."
                        )
                    self.behavior_contract_text = _deps.json.dumps(
                        self.target_behavior_contracts, ensure_ascii=True
                    ).casefold()
                    if not self.target_is_harness and (
                        "nested mutable" in self.behavior_contract_text
                        or "must not share mutable references"
                        in self.behavior_contract_text
                        or "detached object graph" in self.behavior_contract_text
                    ):
                        self.target_errors.append(
                            "VERIFIED PYTHON STANDARD-LIBRARY CAPABILITY: `from copy import deepcopy` is valid, and `deepcopy(value)` recursively copies nested mutable state while preserving the copied values. A local function import is valid when the repair boundary cannot modify module imports. Use this capability when it is the smallest way to satisfy the approved non-aliasing observation; do not substitute an unrelated domain transformation."
                        )
                    self.target_errors.append(
                        "APPROVED BEHAVIOR CONTRACTS FOR THIS OWNER: "
                        + _deps.json.dumps(
                            self.target_behavior_contracts,
                            ensure_ascii=True,
                            separators=(",", ":"),
                        )
                    )
                self.focused_repair_scope_files = [
                    record
                    for record in self.repair_scope_files
                    if _deps.Path(record[0]).resolve()
                    == _deps.Path(str(self.target["path"])).resolve()
                ]
                self.repair_objective = "Repair only the exact callable in the approved atomic owner capsule and preserve unrelated executable behavior."
                self.contract, self.contract_errors = (
                    _deps.build_project_edit_function_repair_contract(
                        self.focused_repair_scope_files or self.repair_scope_files,
                        target=self.target,
                        validation_errors=self.target_errors,
                        objective=self.repair_objective,
                    )
                )
                self.contract["atomic_owner_capsule_payload"] = self.owner_capsule
                if self.contract_errors:
                    continue
                self.focused_regressions: list[str] = []
                if self.snapshot_owner_plan and self.snapshot_owner_plan.get(
                    "replacement"
                ):
                    self.current_target_source = next(
                        (
                            source
                            for path, _original, source in self.repair_scope_files
                            if _deps.Path(path).resolve()
                            == _deps.Path(str(self.target["path"])).resolve()
                        ),
                        "",
                    )
                    self.snapshot_replacement = _deps._preserve_callable_docstring(
                        self.current_target_source,
                        str(self.target["symbol"]),
                        str(self.snapshot_owner_plan["replacement"]),
                    )
                    self.current_behavior = _deps._callable_behavior_fingerprint(
                        self.current_target_source, str(self.target["symbol"])
                    )
                    self.proposed_behavior = _deps._callable_behavior_fingerprint(
                        self.snapshot_replacement, str(self.target["symbol"])
                    )
                    if (
                        self.current_behavior
                        and self.proposed_behavior
                        and (self.current_behavior == self.proposed_behavior)
                    ):
                        self.failure_detail = (
                            "the snapshot replacement changed no executable behavior"
                        )
                        self.callable_repair_errors.append(
                            f"{self.target['symbol']}: {self.failure_detail}."
                        )
                        self.stalled_callable_symbols.add(self.target_key)
                        if self.status_callback:
                            self.status_callback(
                                f"Rejected atomic snapshot repair for {self.target['symbol']}: {self.failure_detail}."
                            )
                        continue
                    self.updated_files, self.splice_errors = (
                        _deps.apply_project_edit_generated_symbol_repair(
                            self.repair_scope_files,
                            path=self.target["path"],
                            symbol=self.target["symbol"],
                            replacement_response=self.snapshot_replacement,
                            forbidden_names=list(
                                self.contract.get("forbidden_names") or []
                            ),
                            approved_signature=self.approved_signature,
                        )
                    )
                    if (
                        self.splice_errors
                        or self.updated_files == self.repair_scope_files
                    ):
                        self.failure_detail = (
                            "; ".join(self.splice_errors)
                            or "the snapshot replacement normalized to unchanged code"
                        )
                        self.callable_repair_errors.append(
                            f"{self.target['symbol']}: {self.failure_detail}."
                        )
                        self.stalled_callable_symbols.add(self.target_key)
                        if self.status_callback:
                            self.status_callback(
                                f"Rejected atomic snapshot repair for {self.target['symbol']}: {self.failure_detail}."
                            )
                        continue
                    self.snapshot_regressions: list[str] = []
                    if not self.target_is_harness:
                        self.current_contract_errors = (
                            self.validate_generated_files_against_implementation_plan(
                                self.implementation_plan, self.generated_files
                            )
                        )
                        self.proposed_contract_errors = (
                            self.validate_generated_files_against_implementation_plan(
                                self.implementation_plan, self.updated_files
                            )
                        )
                        self.snapshot_regressions = [
                            error
                            for error in self.proposed_contract_errors
                            if error not in self.current_contract_errors
                            and (
                                not _deps._contract_error_is_owned_by_other_callable(
                                    error, str(self.target["symbol"])
                                )
                            )
                        ]
                    if self.snapshot_regressions:
                        self.callable_repair_errors.append(
                            f"{self.target['symbol']}: atomic runtime replacement regressed a previously clean approved-plan contract: "
                            + " | ".join(self.snapshot_regressions[:3])
                        )
                        self.snapshot_owner_plan = None
                        if self.status_callback:
                            self.status_callback(
                                f"Rejected atomic snapshot repair for {self.target['symbol']} because it regressed previously validated behavior."
                            )
                    else:
                        if self.target_is_harness:
                            self.harness_source = next(
                                (
                                    source
                                    for path, _original, source in self.updated_files
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
                            self.active_validation_files = self.updated_files
                        else:
                            self.generated_files = self.updated_files
                        self.repaired_any = True
                        self.target_repaired = True
                        self.stalled_callable_symbols.discard(self.target_key)
                        if self.status_callback:
                            self.status_callback(
                                f"Applied atomic snapshot repair for {self.target['symbol']} covering {', '.join(self.snapshot_owner_plan['failure_ids'])}."
                            )
                        continue
                self.repair_plan: dict[str, _deps.Any] | None = None
                if self.snapshot_owner_plan:
                    self.repair_plan = {
                        "root_cause": self.snapshot_owner_plan["root_cause"],
                        "algorithm_steps": self.snapshot_owner_plan["algorithm_steps"],
                        "postconditions": self.snapshot_owner_plan["postconditions"],
                    }
                elif (
                    self.needs_repair_plan
                    or len(self.target_behavior_contracts) >= 3
                ) and (
                    not self.target_has_explicit_mechanical_fix
                ):
                    self.plan_stage = (
                        _deps.build_project_edit_function_repair_plan_stage(
                            self.contract
                        )
                    )
                    if self.status_callback:
                        self.status_callback(
                            f"Diagnosing callable {self.target['symbol']}"
                        )
                    self.plan_response, self.plan_timing = _deps._query_stage(
                        self.plan_stage,
                        selected_model=_deps._small_owner_reasoning_model(
                            self.settings, self.selected_model
                        ),
                        settings=self.settings,
                        timeout=self.timeout,
                    )
                    self.plan_timing.update(
                        {
                            "attempt": self.attempt + 1,
                            "path": self.target["path"],
                            "symbol": self.target["symbol"],
                            "stage": "focused_function_repair_plan",
                        }
                    )
                    self.timings.append(self.plan_timing)
                    self.repair_plan, self.plan_errors = (
                        _deps.parse_project_edit_function_repair_plan(
                            self.plan_response, contract=self.contract
                        )
                    )
                    if self.plan_errors:
                        self.callable_repair_errors.extend(
                            (
                                f"{self.target['symbol']}: {error}"
                                for error in self.plan_errors
                            )
                        )
                        self.repair_plan = {}
                        if self.status_callback:
                            self.status_callback(
                                f"Rejected optional repair plan for {self.target['symbol']}: "
                                + " | ".join(self.plan_errors[:3])
                                + "; proceeding with direct grounded symbol repair."
                            )
                    elif self.repair_plan and self.status_callback:
                        self.status_callback(
                            f"Repair diagnosis for {self.target['symbol']}: {self.repair_plan.get('root_cause') or 'root cause resolved'}; applying only this callable's approved algorithm."
                        )
                self.repair_stage = _deps.build_project_edit_function_repair_stage(
                    self.contract,
                    attempt=self.attempt + 1,
                    repair_plan=self.repair_plan,
                )
                self.repair_stage = _deps.replace(
                    self.repair_stage,
                    metadata={
                        **dict(self.repair_stage.metadata or {}),
                        "owner_source": str(self.contract.get("source") or ""),
                    },
                )
                self.target_callable_name = str(self.target.get("symbol") or "").rsplit(
                    ".", 1
                )[-1]
                self.target_documentation_only = bool(self.target_errors) and all(
                    (
                        "Requested useful docstrings are too vague:" in error
                        for error in self.target_errors
                    )
                )
                self.target_is_verification = (
                    self.target_is_harness
                    or self.target_callable_name in {"run_self_test", "self_test"}
                    or self.target_callable_name.startswith("test_")
                    or _deps.Path(str(self.target.get("path") or "")).name.startswith(
                        "test_"
                    )
                )
                if self.target_documentation_only:
                    self.repair_stage = _deps.replace(
                        self.repair_stage,
                        user_prompt=self.repair_stage.user_prompt
                        + "\n\nDOCUMENTATION-ONLY REPAIR:\n- Every supplied failure for this callable concerns its documentation only.\n- Preserve the signature, decorators, and every executable statement exactly.\n- Replace only the docstring with a concrete behavioral summary and semantic\n  :param, :return, and :raises descriptions required by the request.\n- A documentation-only source change is substantive for this repair. Do not\n  alter the algorithm merely to make the replacement executable fingerprint\n  differ.\n",
                    )
                if self.target_is_verification:
                    self.verification_file_source = next(
                        (
                            source
                            for path, _original, source in self.repair_scope_files
                            if _deps.Path(path).resolve()
                            == _deps.Path(str(self.target.get("path") or "")).resolve()
                        ),
                        "",
                    )
                    self.verification_plan = [
                        {
                            "owner": str(chunk.get("owner") or ""),
                            "kind": str(chunk.get("kind") or ""),
                            "declaration_contract": chunk.get("declaration_contract")
                            or {},
                            "requirements": chunk.get("requirements") or [],
                            "validation_cases": chunk.get("validation_cases") or [],
                        }
                        for chunk in self.implementation_plan.get("chunks") or []
                        if isinstance(chunk, dict)
                        and (
                            str(chunk.get("owner") or "")
                            == str(self.target.get("symbol") or "")
                            or str(chunk.get("kind") or "") == "class"
                        )
                        and (
                            _deps.Path(str(chunk.get("path") or "")).resolve()
                            == _deps.Path(str(self.target.get("path") or "")).resolve()
                        )
                    ]
                    self.repair_stage = _deps.replace(
                        self.repair_stage,
                        system_prompt="Repair one explicitly requested Python verification callable. Return only the complete callable replacement, without markdown or explanation. Satisfy every supplied failure in one coherent body. Preserve its exact signature and docstring. Use only approved public declarations and built-in assert/try/except constructs; never introduce pytest, unittest, undeclared imports, private state, or invented attributes.",
                        user_prompt=f"ORIGINAL REQUEST:\n{self.prompt}\n\nEXACT REMAINING FAILURES:\n{chr(10).join(self.target_errors)}\n\nAPPROVED DECLARATIONS AND PROOF CASES:\n{_deps.json.dumps(self.verification_plan, indent=2, ensure_ascii=True)}\n\nCURRENT FILE:\n```python\n{self.verification_file_source}\n```\n\nPROOF SHAPES:\n- Defensive copy: construct the object with a named mutable variable, mutate\n  that exact same variable afterward, then assert the object still exposes the\n  original behavior. Mutating a separate copy or a variable that was never\n  passed to the constructor is not proof.\n- Validation: execute every explicitly invalid public operation inside built-in\n  try/except for the required exception; raise AssertionError if it succeeds.\n- Replacement/order/tie stability: snapshot the public ordered view, replace an\n  existing key, assert unchanged order and the updated public lookup result.\n- Detached immutable view: store the public view, mutate through an approved\n  public method, then assert the stored value is a tuple and remains unchanged.\n- Repeatable non-mutating lookup: snapshot public state, call the same lookup\n  twice, compare both results, and assert public state equals the snapshot.\n- Boolean removal result: remove one existing key and assert the result is\n  exactly True, then remove that same absent key and assert exactly False.\n\nReturn only the complete `{self.target_callable_name}` definition. Every listed\nproof clause must have explicit setup, action, and assertion/exception evidence.\n",
                    )
                if (
                    self.target_callable_name.startswith(
                        ("add", "set", "register", "update", "append", "insert")
                    )
                    and len(
                        set(
                            _deps.re.findall(
                                "\\btest_[A-Za-z0-9_]+\\b", "\n".join(self.errors)
                            )
                        )
                    )
                    >= 2
                    and ("AssertionError:" in "\n".join(self.errors))
                ):
                    self.repair_stage = _deps.replace(
                        self.repair_stage,
                        user_prompt=self.repair_stage.user_prompt
                        + "\n\nSHARED STATE-WRITER DIAGNOSIS:\nMultiple observer tests fail with assertion mismatches after calling this\nmutator. Inspect the owning class state initialization, sibling observer\nsemantics, bounded callers, and objective together. Repair the shared state at\nthe point it is written instead of compensating in every observer. For paired\nforward/reverse mappings, make each key/value direction match the public method\nnames and update both directions atomically. Preserve the initialized container\ntypes and use only operations supported by those exact types. Do not return the\ncurrent mutator unchanged when its writes contradict the observer contract.\n",
                    )
                if any(
                    (
                        marker in error
                        for error in self.errors
                        for marker in ("AttributeError:", "TypeError:", "NameError:")
                    )
                ):
                    self.repair_stage = _deps.replace(
                        self.repair_stage,
                        user_prompt=self.repair_stage.user_prompt
                        + "\n\nRUNTIME FAILURE RULE:\nThe supplied traceback is authoritative API evidence. Change the exact failing\ncall or name; do not return the current callable unchanged. Resolve the real\nowner/import or conversion path from the available runtime API, preserve all\nunrelated working lines, and return only this callable replacement.\n",
                    )
                if not self.snapshot_owner_plan and (not self.target_is_verification):
                    self.repair_stage = _deps.replace(
                        self.repair_stage,
                        user_prompt=self.repair_stage.user_prompt
                        + _deps._federated_symbol_evidence_context(
                            "\n".join(
                                [
                                    self.prompt,
                                    f"Repair symbol: {self.target['symbol']}",
                                    *self.target_errors,
                                ]
                            ),
                            project_root=self.root,
                            generated_files=self.generated_files,
                        ),
                    )
                if (
                    _deps.Path(str(self.target.get("path") or "")).name.startswith(
                        "test_"
                    )
                    and any(
                        (
                            marker in "\n".join(self.errors).lower()
                            for marker in (
                                "undefined name",
                                "undefined names",
                                "nameerror:",
                                "unboundlocalerror:",
                            )
                        )
                    )
                    and _deps.re.search(
                        "\\b(?:unreal|maya|cmds|bpy|pyfbsdk)\\b",
                        "\n".join(self.errors),
                        flags=_deps.re.IGNORECASE,
                    )
                ):
                    self.repair_stage = _deps.replace(
                        self.repair_stage,
                        user_prompt=self.repair_stage.user_prompt
                        + "\n\nHOST TEST BINDING REPAIR:\nPreserve this test method's decorators and exact signature. Do not import or\nreference an unavailable host SDK directly. Use the already patched/injected\nhost binding owned by the production module, or configure sentinel class/enum\nmembers on that patched binding and assert against those sentinels. Change only\nthe test body and keep every requested behavioral assertion. When the test\nalready imports a production class directly, add a local import of that class's\nproduction module inside the test and bind the host through\n`production_module.<host_binding>`; never repeat the unbound SDK root.\n",
                    )
                if self.status_callback:
                    self.status_callback(
                        f"Repairing callable {self.target['symbol']}, attempt {self.attempt + 1}"
                    )
                self.repair_feedback = ""
                self.strong_model = _deps._strong_task_model(self.selected_model)
                self.compact_model = (
                    self.strong_model
                    if len(self.manifest) > 1
                    else _deps._compact_callable_repair_model(self.selected_model)
                )
                if self.snapshot_owner_plan:
                    self.repair_models = [self.strong_model, self.strong_model]
                elif self.target_is_verification:
                    self.repair_models = [self.strong_model, self.strong_model]
                elif self.target_key in self.strong_callable_symbols:
                    self.repair_models = [self.strong_model, self.strong_model]
                else:
                    self.compact_remaining = max(
                        0, 1 - self.compact_callable_attempts.get(self.target_key, 0)
                    )
                    self.repair_models = [
                        *[self.compact_model] * self.compact_remaining,
                        self.strong_model,
                    ]
                    if len(self.repair_models) == 1:
                        self.repair_models.append(self.strong_model)
                self.repair_models = _bounded_repair_model_sequence(
                    self.repair_models,
                    one_shot=self.target_has_explicit_mechanical_fix,
                )
                for self.symbol_attempt, self.repair_model in enumerate(
                    self.repair_models, 1
                ):
                    if self.repair_model.casefold() == self.compact_model.casefold():
                        self.compact_callable_attempts[self.target_key] = (
                            self.compact_callable_attempts.get(self.target_key, 0) + 1
                        )
                    if self.status_callback:
                        self.status_callback(
                            f"Callable repair model {self.symbol_attempt}/{len(self.repair_models)} for {self.target['symbol']}: {self.repair_model}"
                        )
                    self.replacement, self.timing = _deps._query_stage(
                        self.repair_stage,
                        selected_model=self.repair_model,
                        settings=self.settings,
                        timeout=self.timeout,
                        suffix=self.repair_feedback,
                    )
                    self.timing.update(
                        {
                            "attempt": self.attempt + 1,
                            "symbol_attempt": self.symbol_attempt,
                            "path": self.target["path"],
                            "symbol": self.target["symbol"],
                            "stage": "focused_function_repair",
                        }
                    )
                    self.timings.append(self.timing)
                    self.current_target_source_for_docstring = next(
                        (
                            source
                            for path, _original, source in self.repair_scope_files
                            if _deps.Path(path).resolve()
                            == _deps.Path(str(self.target["path"])).resolve()
                        ),
                        "",
                    )
                    if not self.target_documentation_only:
                        self.replacement = _deps._preserve_callable_docstring(
                            self.current_target_source_for_docstring,
                            str(self.target["symbol"]),
                            self.replacement,
                        )
                    if (
                        self.target_behavior_contracts
                        and _deps.re.search("\\bdeepcopy\\s*\\(", self.replacement)
                        and (
                            not _deps.re.search(
                                "\\b(?:from\\s+copy\\s+import\\s+deepcopy|import\\s+copy)\\b",
                                self.replacement,
                            )
                        )
                    ):
                        try:
                            self.replacement_tree = _deps.ast.parse(self.replacement)
                        except SyntaxError:
                            self.replacement_tree = None
                        self.replacement_callable = (
                            self.replacement_tree.body[0]
                            if self.replacement_tree is not None
                            and self.replacement_tree.body
                            and isinstance(
                                self.replacement_tree.body[0],
                                (_deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef),
                            )
                            else None
                        )
                        if self.replacement_callable is not None:
                            self.import_index = (
                                1
                                if _deps.ast.get_docstring(
                                    self.replacement_callable, clean=False
                                )
                                else 0
                            )
                            self.replacement_callable.body.insert(
                                self.import_index,
                                _deps.ast.ImportFrom(
                                    module="copy",
                                    names=[
                                        _deps.ast.alias(name="deepcopy", asname=None)
                                    ],
                                    level=0,
                                ),
                            )
                            _deps.ast.fix_missing_locations(self.replacement_tree)
                            self.replacement = (
                                _deps.ast.unparse(self.replacement_tree).rstrip() + "\n"
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Completed verified local dependency import for {self.target['symbol']}: from copy import deepcopy"
                                )
                    self.updated_files, self.splice_errors = (
                        _deps.apply_project_edit_generated_symbol_repair(
                            self.repair_scope_files,
                            path=self.target["path"],
                            symbol=self.target["symbol"],
                            replacement_response=self.replacement,
                            forbidden_names=list(
                                self.contract.get("forbidden_names") or []
                            ),
                            approved_signature=self.approved_signature,
                        )
                    )
                    if (
                        not self.splice_errors
                        and self.updated_files != self.repair_scope_files
                    ):
                        self.updated_files, self._docstring_repairs = (
                            _deps._repair_requested_python_contract_surface(
                                self.updated_files,
                                self.errors,
                                request_prompt=self.prompt,
                            )
                        )
                    if (
                        not self.splice_errors
                        and self.updated_files != self.repair_scope_files
                    ):
                        self.current_target_source = next(
                            (
                                source
                                for path, _original, source in self.repair_scope_files
                                if _deps.Path(path).resolve()
                                == _deps.Path(str(self.target["path"])).resolve()
                            ),
                            "",
                        )
                        self.proposed_target_source = next(
                            (
                                source
                                for path, _original, source in self.updated_files
                                if _deps.Path(path).resolve()
                                == _deps.Path(str(self.target["path"])).resolve()
                            ),
                            "",
                        )
                        self.current_target_behavior = (
                            _deps._callable_behavior_fingerprint(
                                self.current_target_source, str(self.target["symbol"])
                            )
                        )
                        self.proposed_target_behavior = (
                            _deps._callable_behavior_fingerprint(
                                self.proposed_target_source, str(self.target["symbol"])
                            )
                        )
                        if (
                            not self.target_documentation_only
                            and self.current_target_behavior
                            and self.proposed_target_behavior
                            and (
                                self.current_target_behavior
                                == self.proposed_target_behavior
                            )
                        ):
                            self.splice_errors = [
                                "focused replacement changed no executable behavior in the exact target callable"
                            ]
                    if (
                        not self.splice_errors
                        and self.updated_files != self.repair_scope_files
                        and (not self.target_is_harness)
                    ):
                        self.current_contract_errors = (
                            self.validate_generated_files_against_implementation_plan(
                                self.implementation_plan, self.generated_files
                            )
                        )
                        self.proposed_contract_errors = (
                            self.validate_generated_files_against_implementation_plan(
                                self.implementation_plan, self.updated_files
                            )
                        )
                        self.focused_regressions = [
                            error
                            for error in self.proposed_contract_errors
                            if error not in self.current_contract_errors
                            and (
                                not _deps._contract_error_is_owned_by_other_callable(
                                    error, str(self.target["symbol"])
                                )
                            )
                        ]
                        if self.focused_regressions and self.target_is_verification:

                            def verification_failure_weight(
                                contract_errors: list[str],
                            ) -> int:
                                weight = 0
                                for contract_error in contract_errors:
                                    if _deps._contract_error_is_owned_by_other_callable(
                                        contract_error, str(self.target["symbol"])
                                    ):
                                        continue
                                    clause_match = _deps.re.search(
                                        "does not independently prove clause\\(s\\): (.+?)\\. Repair only this callable",
                                        contract_error,
                                    )
                                    if clause_match:
                                        weight += len(
                                            [
                                                clause
                                                for clause in clause_match.group(
                                                    1
                                                ).split(",")
                                                if clause.strip()
                                            ]
                                        )
                                    else:
                                        weight += 1
                                return weight

                            self.verification_failure_weight = (
                                verification_failure_weight
                            )
                            self.current_weight = self.verification_failure_weight(
                                self.current_contract_errors
                            )
                            self.proposed_weight = self.verification_failure_weight(
                                self.proposed_contract_errors
                            )
                            if 0 <= self.proposed_weight < self.current_weight:
                                self.focused_regressions = []
                                if self.status_callback:
                                    self.status_callback(
                                        f"Retaining monotonic verification progress for {self.target['symbol']}: remaining obligation weight {self.current_weight}->{self.proposed_weight}; the candidate remains incomplete and will be revalidated before completion."
                                    )
                        self.current_owned_contract_errors = [
                            error
                            for error in self.current_contract_errors
                            if not _deps._contract_error_is_owned_by_other_callable(
                                error, str(self.target["symbol"])
                            )
                        ]
                        self.proposed_owned_contract_errors = [
                            error
                            for error in self.proposed_contract_errors
                            if not _deps._contract_error_is_owned_by_other_callable(
                                error, str(self.target["symbol"])
                            )
                        ]
                        self.resolved_coarse_owner_blocker = any(
                            "executable implementation is unchanged"
                            in str(error).casefold()
                            for error in self.current_owned_contract_errors
                        ) and not any(
                            "executable implementation is unchanged"
                            in str(error).casefold()
                            for error in self.proposed_owned_contract_errors
                        )
                        if self.resolved_coarse_owner_blocker:
                            self.focused_regressions = []
                            if self.status_callback:
                                self.status_callback(
                                    f"Retaining executable progress for {self.target['symbol']}; "
                                    "the coarse unchanged-owner blocker is resolved and newly "
                                    "visible same-owner contract details will be repaired next."
                                )
                        if (
                            self.current_owned_contract_errors
                            and len(self.proposed_owned_contract_errors)
                            >= len(self.current_owned_contract_errors)
                            and not self.resolved_coarse_owner_blocker
                        ):
                            self.focused_regressions.append(
                                "focused replacement changed source but did not reduce the target owner's validated contract failure count"
                            )
                        if self.focused_regressions:
                            self.splice_errors = [
                                "focused replacement regressed a previously clean approved-plan contract: "
                                + " | ".join(self.focused_regressions[:3])
                            ]
                    if (
                        not self.splice_errors
                        and self.updated_files != self.repair_scope_files
                    ):
                        self.baseline_transaction_files = list(self.repair_scope_files)
                        self.proposed_transaction_files = list(self.updated_files)
                        self.transaction_harness_path = ""
                        if self.target_is_harness:
                            self.transaction_harness_path = (
                                self.ephemeral_validation_path
                            )
                        elif self.ephemeral_validation_path and self.harness_source:
                            self.transaction_harness_path = (
                                self.ephemeral_validation_path
                            )
                            self.baseline_transaction_files.append(
                                (
                                    self.ephemeral_validation_path,
                                    "",
                                    self.harness_source,
                                )
                            )
                            self.proposed_transaction_files.append(
                                (
                                    self.ephemeral_validation_path,
                                    "",
                                    self.harness_source,
                                )
                            )
                        self.splice_errors.extend(
                            _deps._monotonic_repair_rejections(
                                self.baseline_transaction_files,
                                self.proposed_transaction_files,
                                repair_targets=[
                                    (
                                        str(self.target["path"]),
                                        str(self.target["symbol"]),
                                    )
                                ],
                                assigned_errors=self.target_errors,
                                implementation_plan=self.implementation_plan,
                                project_root=self.root,
                                request_prompt=self.prompt,
                                harness_path=self.transaction_harness_path,
                            )
                        )
                    if (
                        not self.splice_errors
                        and self.updated_files != self.repair_scope_files
                    ):
                        if self.target_is_harness:
                            self.harness_source = next(
                                (
                                    source
                                    for path, _original, source in self.updated_files
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
                            self.active_validation_files = self.updated_files
                        else:
                            self.generated_files = self.updated_files
                        self.repaired_any = True
                        self.target_repaired = True
                        self.pending_symbol_progress_check = (
                            str(self.target["path"]),
                            str(self.target["symbol"]),
                            self.signature,
                            self.repair_model,
                        )
                        self.stalled_callable_symbols.discard(
                            (self.target["path"], self.target["symbol"])
                        )
                        break
                    if self.splice_errors:
                        self.failure_detail = "; ".join(self.splice_errors)
                    else:
                        self.failure_detail = "the returned replacement normalized to the unchanged current symbol"
                    self.callable_repair_errors.append(
                        f"{self.target['symbol']}: {self.failure_detail}."
                    )
                    if self.target_is_verification and self.focused_regressions:
                        self.repair_feedback = (
                            f"\n\nIMPROVED BUT NOT YET ACCEPTED BRANCH CANDIDATE:\nRepair retry {self.symbol_attempt + 1}. Continue from the complete candidate below; do not restart from the older callable. It reduced the original failures but was not accepted because {self.failure_detail}.\nExact branch candidate:\n```python\n"
                            + str(self.replacement or "")
                            + "\n```\nPreserve every setup/action/assertion already present in this branch. Add or correct only the missing proof clauses named above. Return the complete revised callable, using only approved public APIs and built-in Python."
                        )
                    else:
                        self.repair_feedback = (
                            f"\n\nREJECTED SYMBOL REPAIR:\nRepair retry {self.symbol_attempt + 1}. The previous response was rejected because {self.failure_detail}.\nExact rejected response:\n```python\n"
                            + str(self.replacement or "")[-2000:]
                            + f"\n```\nReturn a materially changed, complete replacement for only {self.target['symbol']} that fixes the supplied validation failure. Do not return the whole file, do not repeat the rejected implementation, and preserve unrelated working behavior. Write the corrected algorithm from the validated failure and postconditions rather than copying the rejected body."
                        )
                    if self.status_callback:
                        self.status_callback(
                            f"Rejected repair for {self.target['symbol']} because {self.failure_detail}."
                        )
                        if self.symbol_attempt == 1:
                            self.status_callback(
                                f"Current {self.target['symbol']} body:\n"
                                + str(self.contract.get("source") or "")[-3000:]
                            )
                            self.status_callback(
                                f"Rejected {self.target['symbol']} response:\n"
                                + str(self.replacement or "")[-3000:]
                            )
                    self.equivalent_repair = bool(
                        "AST-equivalent" in self.failure_detail
                        or "changed no executable behavior" in self.failure_detail
                        or "unchanged current symbol" in self.failure_detail
                    )
                    if self.equivalent_repair and self.symbol_attempt < len(
                        self.repair_models
                    ):
                        self.repair_feedback = (
                            "\n\nUNCHANGED REPAIR REJECTED:\nThe previous response was executable-AST-equivalent to the current callable and fixed none of its diagnostics. Change only the failing executable statements. Address every supplied owner-local validation finding directly; do not repeat, reformat, or merely re-document the current body.\n"
                            + "\n".join(self.target_errors)
                        )
                        if self.status_callback:
                            self.status_callback(
                                f"Escalating {self.target['symbol']} after an unchanged repair to a stricter owner-local transformation."
                            )
                        continue
                    if self.equivalent_repair or self.symbol_attempt >= len(
                        self.repair_models
                    ):
                        self.stalled_callable_symbols.add(
                            (self.target["path"], self.target["symbol"])
                        )
                        if self.status_callback:
                            self.status_callback(
                                f"Changing repair strategy for {self.target['symbol']} after its single snapshot-approved attempt produced no valid change; an equivalent repair will not be repeated."
                            )
                        break
                if self.target_repaired:
                    if self.status_callback:
                        self.status_callback(
                            f"Applied focused repair for {self.target['symbol']}; continuing with any independent failure owners before package revalidation."
                        )
            if self.repaired_any:
                self.generated_files = _deps._normalize_generated_files(
                    self.generated_files,
                    project_root=self.root,
                    request_prompt=self.prompt,
                )
                self.generated_files = _deps._enforce_manifest_symbol_owners(
                    self.generated_files, self.symbol_owners, project_root=self.root
                )
                self.generated_files, self._cross_file_repairs = (
                    _deps.resolve_project_edit_cross_file_symbols(
                        self.generated_files, project_root=self.root
                    )
                )
                self.candidate = _deps.build_project_edit_multi_file_candidate(
                    self.generated_files
                )
                raise _WorkflowContinue()
            if self.status_callback:
                self.status_callback(
                    "Focused callable repair returned no accepted change; retaining the candidate and its original unresolved code failures without promoting repair-orchestration diagnostics into quality failures."
                )
            _deps._save_workflow_checkpoint(
                self.root,
                self.prompt,
                self.selected_model,
                self.generated_files,
                {
                    "attempt": self.attempt,
                    "complete": False,
                    "validation_state": "candidate",
                },
                implementation_plan_hash=self.approval_id,
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
                    status="symbol_repair_stalled",
                    candidate=self.candidate,
                    preview=retained_preview,
                    errors=self.errors,
                    timings=self.timings,
                )
            )
        if self.status_callback:
            self.status_callback(
                "No exact symbol or module repair owner was proven. Full-file repair is forbidden once a candidate exists."
            )
        _deps._save_workflow_checkpoint(
            self.root,
            self.prompt,
            self.selected_model,
            self.generated_files,
            {
                "attempt": self.attempt,
                "complete": False,
                "validation_state": "candidate",
            },
            implementation_plan_hash=self.approval_id,
        )
        self.unmapped_retained_preview = _deps.preview_project_edit_agent_response(
            self.candidate,
            project_root=self.root,
            request_prompt=self.prompt,
            behavioral_proof_deferred=True,
        )
        raise _WorkflowReturn(
            _deps.ProjectEditWorkflowResult(
                ok=False,
                status="symbol_repair_unmapped",
                candidate=self.candidate,
                preview=self.unmapped_retained_preview,
                errors=[
                    "Validation remains, but no monotonic symbol/module repair owner was proven. The existing candidate was retained; full-file repair is forbidden."
                ]
                + self.errors,
                timings=self.timings,
            )
        )
        self.affected_paths = [
            path
            for path in self.file_records
            if any(
                (
                    path.lower() in error.lower()
                    or _deps.re.search(
                        f"(?<![A-Za-z0-9_]){_deps.re.escape(_deps.Path(path).name.lower())}(?![A-Za-z0-9_.])",
                        error.lower(),
                    )
                    for error in self.errors
                )
            )
        ]
        if self.fixture_targets:
            self.affected_paths = list(
                dict.fromkeys(
                    (
                        str(target.get("path") or "")
                        for target in [
                            *self.fixture_targets,
                            *self.failing_test_targets,
                        ]
                        if str(target.get("path") or "") in self.file_records
                    )
                )
            )
        if not self.affected_paths and any(
            ("disposable" in error.lower() for error in self.errors)
        ):
            self.affected_paths = [
                path
                for path in self.file_records
                if _deps.Path(path).name.startswith("test_")
            ]
        if not self.affected_paths and self.test_proof_failure:
            self.affected_paths = list(
                dict.fromkeys(
                    (
                        str(target.get("path") or "")
                        for target in self.test_callable_targets
                        if str(target.get("path") or "") in self.file_records
                    )
                )
            )
            if not self.affected_paths:
                self.affected_paths = [
                    path
                    for path in self.file_records
                    if _deps.Path(path).name.startswith("test_")
                ]
        if not self.affected_paths:
            self.error_text = "\n".join(self.errors)
            for self.path, self._original, self.source in self.generated_files:
                try:
                    self.tree = _deps.ast.parse(self.source, filename=self.path)
                except SyntaxError:
                    continue
                self.defined_symbols = {
                    node.name
                    for node in _deps.ast.walk(self.tree)
                    if isinstance(
                        node,
                        (
                            _deps.ast.ClassDef,
                            _deps.ast.FunctionDef,
                            _deps.ast.AsyncFunctionDef,
                        ),
                    )
                }
                if any(
                    (
                        _deps.re.search(
                            f"\\b{_deps.re.escape(symbol)}\\b", self.error_text
                        )
                        for symbol in self.defined_symbols
                    )
                ):
                    self.affected_paths.append(self.path)
        if not self.affected_paths:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="repair_unmapped",
                    candidate=self.candidate,
                    preview=self.preview,
                    errors=["Could not map validation failures to an owning file."]
                    + self.errors,
                    timings=self.timings,
                )
            )
        self.affected_paths = [
            path
            for path in self.affected_paths
            if self.file_repair_attempts.get(path, 0) < 3
        ]
        if not self.affected_paths:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="repair_strategy_exhausted",
                    candidate=self.candidate,
                    preview=self.preview,
                    errors=[
                        "Every proven file owner exhausted its task-local 3B, 3B, 7B repair ladder without clearing validation.",
                        *self.errors,
                    ],
                    timings=self.timings,
                )
            )
        raise _WorkflowReturn(
            _deps.ProjectEditWorkflowResult(
                ok=False,
                status="bounded_repair_owner_required",
                candidate=self.candidate,
                preview=self.preview,
                errors=[
                    "Validation reached a file-level fallback without proving an exact module, class, callable, import, or syntax-region owner. The candidate was preserved; complete-file regeneration and replacement are forbidden.",
                    *self.errors,
                ],
                timings=self.timings,
            )
        )
        self.generated_files = _deps._normalize_generated_files(
            self.generated_files, project_root=self.root, request_prompt=self.prompt
        )
        self.generated_files = _deps._enforce_manifest_symbol_owners(
            self.generated_files, self.symbol_owners, project_root=self.root
        )
        self.generated_files, self._cross_file_repairs = (
            _deps.resolve_project_edit_cross_file_symbols(
                self.generated_files, project_root=self.root
            )
        )
        self.candidate = _deps.build_project_edit_multi_file_candidate(
            self.generated_files
        )
