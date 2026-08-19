"""Project-edit workflow phase: _run_generation_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import _WorkflowReturn


class _ProjectEditGenerationPhase:
    """Provide the generation workflow phase."""

    def _run_generation_phase(self) -> None:
        """Run the generation phase.

        :return: None.
        """
        for self.sequence_batch_index in range(
            0, len(self.behavior_sequence_inputs), 6
        ):
            self.sequence_batch = self.behavior_sequence_inputs[
                self.sequence_batch_index : self.sequence_batch_index + 6
            ]
            self.sequence_batch = [
                row
                for row in self.sequence_batch
                if row["requirement_id"] not in self.sequenced_steps_by_requirement
            ]
            if not self.sequence_batch:
                continue
            if self.status_callback:
                self.status_callback(
                    f"Sequencing state-aware behavior batch {self.sequence_batch_index // 6 + 1}/{(len(self.behavior_sequence_inputs) + 5) // 6}: "
                    + ", ".join((row["requirement_id"] for row in self.sequence_batch))
                )
            self.sequence_stage = _deps.ProjectEditPromptStage(
                key="implementation_plan_behavior_sequence",
                label="Sequencing approved behavior state transitions",
                system_prompt="Return JSON only. Convert each supplied behavior into the smallest ordered runtime proof using only its approved production_owners. Each step must name one exact approved chunk_id and callable_name. Setup steps construct caller inputs or establish state and therefore must not require facts that do not yet exist. Actions perform the requested transition. Observations read or assert the result. Symbolic requires facts must have been produced by an earlier step and not invalidated. Put direct assertions on the exact step where the behavior becomes observable; an action may own an exception assertion. Observe state before a later destructive action invalidates it. Include every approved production owner at least once, preserve causal order, and do not invent methods, dependencies, or behavior. A UI action must read values from the actual exposed controls rather than disconnected shadow fields. Route those values into verified dependency parameters using the exact supplied signature and value shape. Every observation assertion must state an executable predicate with the exact owner-visible value, call result, exception, callback arguments, or state transition being compared. Exposing a control means construct, attach, and read it; it does not imply that production populates, updates, displays, saves, emits, or otherwise mutates that control or another resource. Such a state change is allowed only when the supplied requirement explicitly requests that change. Phrases such as 'items updated', 'works', 'is valid', or 'result displayed' are not assertions.",
                user_prompt=_deps.json.dumps(
                    {"behavior_contracts": self.sequence_batch},
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                model_tier="local_reasoning",
                num_ctx=4096,
                num_predict=-1,
                timeout=90,
                no_progress_seconds=20,
                prefer_coder=True,
                coder_preference="standard",
                response_format={
                    "type": "object",
                    "properties": {
                        "contracts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "requirement_id": {"type": "string"},
                                    "execution_steps": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "step_id": {"type": "string"},
                                                "phase": {
                                                    "type": "string",
                                                    "enum": [
                                                        "setup",
                                                        "action",
                                                        "observation",
                                                    ],
                                                },
                                                "chunk_id": {"type": "string"},
                                                "callable_name": {"type": "string"},
                                                "instruction": {"type": "string"},
                                                "requires": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                                "produces": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                                "invalidates": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                                "assertions": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                            },
                                            "required": [
                                                "step_id",
                                                "phase",
                                                "chunk_id",
                                                "callable_name",
                                                "instruction",
                                                "requires",
                                                "produces",
                                                "invalidates",
                                                "assertions",
                                            ],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": ["requirement_id", "execution_steps"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["contracts"],
                    "additionalProperties": False,
                },
                metadata={"disable_thinking": False},
            )
            self.approved_sequence_ids = {
                row["requirement_id"] for row in self.sequence_batch
            }
            self.sequence_rows_by_id = {
                row["requirement_id"]: row for row in self.sequence_batch
            }

            def deterministic_sequence(
                sequence_row: _deps.Mapping[str, _deps.Any],
            ) -> list[dict[str, _deps.Any]]:
                """Compile a minimal executable proof from approved plan facts."""
                owners = [
                    owner
                    for owner in sequence_row.get("production_owners") or []
                    if isinstance(owner, _deps.Mapping)
                    and str(owner.get("chunk_id") or "")
                    and str(owner.get("callable_name") or "")
                ]
                if not owners:
                    return []
                declaration_owner = next(
                    (
                        owner
                        for owner in owners
                        if str(owner.get("callable_name") or "") == "<declaration>"
                    ),
                    owners[0],
                )
                action_owners = [
                    owner for owner in owners if owner is not declaration_owner
                ] or [declaration_owner]
                attributes = list(
                    dict.fromkeys(
                        (
                            str(attribute.get("name") or "")
                            for attribute in sequence_row.get("declared_attributes")
                            or []
                            if isinstance(attribute, _deps.Mapping)
                            and str(attribute.get("name") or "")
                        )
                    )
                )
                attribute_facts = [f"self.{name}" for name in attributes]
                dependencies = [
                    dependency
                    for dependency in sequence_row.get("verified_dependencies") or []
                    if isinstance(dependency, _deps.Mapping)
                    and str(dependency.get("name") or "")
                ]
                dependency_labels: list[str] = []
                for dependency in dependencies:
                    dependency_name = str(dependency.get("name") or "")
                    dependency_labels.append(dependency_name)
                dependency_contract = (
                    "; ".join(dependency_labels) or "the approved owner behavior"
                )
                operation = str(
                    sequence_row.get("operation")
                    or sequence_row.get("requirement")
                    or ""
                ).strip()
                mechanics = [
                    str(value).strip()
                    for value in sequence_row.get("mechanics") or []
                    if str(value).strip()
                ]
                approved_observations = list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in (
                            sequence_row.get("expected_observations")
                            or sequence_row.get("validation_checks")
                            or []
                        )
                        if str(value).strip()
                    )
                )
                if not approved_observations and operation:
                    approved_observations = [
                        "Invoke the approved owner and assert this exact clause: "
                        + operation
                    ]
                steps: list[dict[str, _deps.Any]] = [
                    {
                        "step_id": "S1",
                        "phase": "setup",
                        "chunk_id": str(declaration_owner.get("chunk_id") or ""),
                        "callable_name": str(
                            declaration_owner.get("callable_name") or ""
                        ),
                        "instruction": (
                            "Construct the caller-visible inputs needed to prove this "
                            f"exact approved operation without invoking it: {operation}"
                        ),
                        "requires": [],
                        "produces": attribute_facts,
                        "invalidates": [],
                        "assertions": [],
                    }
                ]
                result_facts: list[str] = []
                for owner_index, owner in enumerate(action_owners, start=2):
                    result_fact = (
                        "verified_call_result"
                        if len(action_owners) == 1
                        else f"verified_call_result_{owner_index - 1}"
                    )
                    result_facts.append(result_fact)
                    steps.append(
                        {
                            "step_id": f"S{owner_index}",
                            "phase": "action",
                            "chunk_id": str(owner.get("chunk_id") or ""),
                            "callable_name": str(owner.get("callable_name") or ""),
                            "instruction": (
                                "Invoke the approved callable with inputs that exercise "
                                f"this exact operation and retain its result: {operation}"
                                + (
                                    f" Use the verified dependency contract `{dependency_contract}` "
                                    "with signature-compatible values."
                                    if dependencies
                                    else ""
                                )
                                + (
                                    " Apply these approved mechanics: "
                                    + " ".join(mechanics)
                                    if mechanics
                                    else ""
                                )
                            ),
                            "requires": attribute_facts,
                            "produces": [result_fact],
                            "invalidates": [],
                            "assertions": [],
                        }
                    )
                observation_owner = action_owners[-1]
                assertions = approved_observations
                steps.append(
                    {
                        "step_id": f"S{len(steps) + 1}",
                        "phase": "observation",
                        "chunk_id": str(observation_owner.get("chunk_id") or ""),
                        "callable_name": str(
                            observation_owner.get("callable_name") or ""
                        ),
                        "instruction": (
                            "Observe and assert the exact approved postcondition "
                            f"immediately after the action: {operation}"
                        ),
                        "requires": result_facts,
                        "produces": [],
                        "invalidates": [],
                        "assertions": assertions,
                    }
                )
                return steps

            self.deterministic_sequence = deterministic_sequence
            self.deterministic_batch = {
                requirement_id: self.deterministic_sequence(
                    self.sequence_rows_by_id[requirement_id]
                )
                for requirement_id in self.approved_sequence_ids
            }
            if all(self.deterministic_batch.values()):
                self.sequenced_steps_by_requirement.update(self.deterministic_batch)
                if self.status_callback:
                    self.status_callback(
                        "Compiled executable behavior proofs directly from approved owners, fields, mechanics, and verified signatures."
                    )
                continue
            self.prior_sequence_response = ""
            self.sequence_feedback = ""
            for self.sequence_attempt in range(1, 2):
                self.sequence_response, self.sequence_timing = _deps._query_stage(
                    self.sequence_stage,
                    selected_model=self.selected_model,
                    settings=self.settings,
                    timeout=self.timeout,
                    suffix=self.sequence_feedback,
                )
                self.sequence_timing["strategy_attempt"] = self.sequence_attempt
                self.timings.append(self.sequence_timing)
                try:
                    self.sequence_payload = _deps.json.loads(self.sequence_response)
                except (TypeError, ValueError, _deps.json.JSONDecodeError):
                    self.sequence_payload = {}
                self.proposed_sequences: dict[str, list[dict[str, _deps.Any]]] = {}
                self.sequence_protocol_errors: list[str] = []
                for self.sequence_contract in (
                    self.sequence_payload.get("contracts") or []
                ):
                    if not isinstance(self.sequence_contract, _deps.Mapping):
                        continue
                    self.sequence_requirement_id = str(
                        self.sequence_contract.get("requirement_id") or ""
                    )
                    if self.sequence_requirement_id not in self.approved_sequence_ids:
                        continue
                    self.steps = [
                        dict(step)
                        for step in self.sequence_contract.get("execution_steps") or []
                        if isinstance(step, _deps.Mapping)
                    ]
                    self.proposed_sequences[self.sequence_requirement_id] = self.steps
                    self.known_sequence_facts: set[str] = set()
                    for self.step in self.steps:
                        self.step_assertions = list(self.step.get("assertions") or [])
                        self.approved_behavior_text = " ".join(
                            (
                                str(value)
                                for value in (
                                    self.sequence_rows_by_id[
                                        self.sequence_requirement_id
                                    ].get("operation")
                                    or "",
                                    *(
                                        self.sequence_rows_by_id[
                                            self.sequence_requirement_id
                                        ].get("expected_observations")
                                        or []
                                    ),
                                )
                            )
                        ).casefold()
                        if (
                            str(self.step.get("phase") or "").casefold()
                            == "observation"
                        ):
                            for self.assertion in self.step_assertions:
                                self.assertion_text = str(self.assertion).strip()
                                self.assertion_fields = {
                                    match.group(0)
                                    for match in _deps.re.finditer(
                                        "\\bself(?:\\.[A-Za-z_][A-Za-z0-9_]*)+",
                                        self.assertion_text,
                                    )
                                }
                                self.unknown_fields = {
                                    field
                                    for field in self.assertion_fields
                                    if field not in self.known_sequence_facts
                                    and (
                                        not any(
                                            (
                                                field.startswith(fact + ".")
                                                for fact in self.known_sequence_facts
                                            )
                                        )
                                    )
                                }
                                if self.unknown_fields:
                                    self.sequence_protocol_errors.append(
                                        f"{self.sequence_requirement_id} observation references state not produced by an approved earlier step: "
                                        + ", ".join(sorted(self.unknown_fields))
                                    )
                        for self.assertion in self.step_assertions:
                            self.assertion_text = str(self.assertion).strip()
                            self.unapproved_mutations = [
                                label
                                for label, pattern in (
                                    ("update", "\\bupdat(?:e|ed|es|ing)\\b"),
                                    ("populate", "\\bpopulat(?:e|ed|es|ing)\\b"),
                                    ("fill", "\\bfill(?:ed|s|ing)?\\b"),
                                    ("display", "\\bdisplay(?:ed|s|ing)?\\b"),
                                    ("show", "\\bshow(?:n|s|ing)?\\b"),
                                    ("save", "\\bsav(?:e|ed|es|ing)\\b"),
                                    ("write", "\\bwrit(?:e|es|ing|ten)\\b"),
                                    ("delete", "\\bdelet(?:e|ed|es|ing)\\b"),
                                    ("remove", "\\bremov(?:e|ed|es|ing)\\b"),
                                    ("emit", "\\bemit(?:ted|s|ting)?\\b"),
                                )
                                if _deps.re.search(
                                    pattern,
                                    self.assertion_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                                and (
                                    not _deps.re.search(
                                        pattern,
                                        self.approved_behavior_text,
                                        flags=_deps.re.IGNORECASE,
                                    )
                                )
                            ]
                            if self.unapproved_mutations:
                                self.sequence_protocol_errors.append(
                                    f"{self.sequence_requirement_id} observation invents an unrequested state change: "
                                    + ", ".join(self.unapproved_mutations)
                                )
                            self.has_predicate = bool(
                                _deps.re.search(
                                    "\\bassert\\b|==|!=|<=|>=|\\bis\\b|\\bin\\b|\\braises?\\b|\\bemits?\\b|\\breturns?\\b|\\.(?:count|text|value|currentText|isEnabled)\\s*\\(",
                                    self.assertion_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            self.vague_outcome = bool(
                                _deps.re.search(
                                    "\\b(?:updated|displayed|shown|works?|valid|correct|created|called)\\s*$",
                                    self.assertion_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            if (
                                not self.assertion_text
                                or self.vague_outcome
                                or (not self.has_predicate)
                            ):
                                self.sequence_protocol_errors.append(
                                    f"{self.sequence_requirement_id} observation must replace vague assertion `{self.assertion_text or '<empty>'}` with an exact executable predicate."
                                )
                        self.known_sequence_facts.update(
                            (
                                str(value).strip()
                                for value in self.step.get("produces") or []
                                if str(value).strip()
                            )
                        )
                self.missing_sequences = self.approved_sequence_ids - set(
                    self.proposed_sequences
                )
                if self.missing_sequences:
                    self.sequence_protocol_errors.append(
                        "Missing ordered behavior sequence for "
                        + ", ".join(sorted(self.missing_sequences))
                    )
                if not self.sequence_protocol_errors:
                    self.sequenced_steps_by_requirement.update(self.proposed_sequences)
                    break
                self.unchanged = (
                    bool(self.prior_sequence_response)
                    and self.sequence_response.strip()
                    == self.prior_sequence_response.strip()
                )
                if self.unchanged:
                    for self.requirement_id in self.approved_sequence_ids:
                        self.fallback_steps = self.deterministic_sequence(
                            self.sequence_rows_by_id[self.requirement_id]
                        )
                        if self.fallback_steps:
                            self.sequenced_steps_by_requirement[self.requirement_id] = (
                                self.fallback_steps
                            )
                    if self.status_callback:
                        self.status_callback(
                            "Model sequence remained equivalent; compiled executable behavior proof deterministically from approved owners, fields, and verified signatures."
                        )
                    break
                self.prior_sequence_response = self.sequence_response
                self.sequence_feedback = (
                    "\n\nREJECTED SEQUENCE:\n"
                    + " | ".join(self.sequence_protocol_errors)
                    + "\nReturn corrected contracts only. Preserve valid owners and steps, but replace every vague observation with an exact predicate grounded in the supplied requirement and verified signatures."
                )
                if self.status_callback:
                    self.status_callback(
                        "Refining behavior sequence before approval: "
                        + " | ".join(self.sequence_protocol_errors)
                    )
            else:
                for self.requirement_id in self.approved_sequence_ids:
                    self.fallback_steps = self.deterministic_sequence(
                        self.sequence_rows_by_id[self.requirement_id]
                    )
                    if self.fallback_steps:
                        self.sequenced_steps_by_requirement[self.requirement_id] = (
                            self.fallback_steps
                        )
                    else:
                        self.behavior_contract_errors.extend(
                            self.sequence_protocol_errors
                        )
                if self.status_callback and (not self.behavior_contract_errors):
                    self.status_callback(
                        "Compiled executable behavior proof deterministically after model sequencing remained non-executable."
                    )
        for self.contract in self.candidate_behavior_contracts:
            if not isinstance(self.contract, dict):
                continue
            self.requirement_id = str(self.contract.get("requirement_id") or "")
            if self.requirement_id in self.sequenced_steps_by_requirement:
                self.contract["execution_steps"] = self.sequenced_steps_by_requirement[
                    self.requirement_id
                ]
        self.behavior_contracts_by_requirement: dict[str, dict[str, _deps.Any]] = {}
        for self.contract_index, self.raw_contract in enumerate(
            self.candidate_behavior_contracts, start=1
        ):
            if not isinstance(self.raw_contract, _deps.Mapping):
                self.behavior_contract_errors.append(
                    f"behavior contract {self.contract_index} is not an object"
                )
                continue
            self.requirement_id = str(self.raw_contract.get("requirement_id") or "")
            if self.requirement_id not in self.behavior_requirement_ids:
                continue
            if self.requirement_id in self.behavior_contracts_by_requirement:
                self.behavior_contract_errors.append(
                    f"behavior contract has invalid or duplicate requirement `{self.requirement_id or '<missing>'}`"
                )
                continue
            self.normalized_owners: list[dict[str, str]] = []
            for self.raw_owner in self.raw_contract.get("production_owners") or []:
                if not isinstance(self.raw_owner, _deps.Mapping):
                    continue
                self.chunk_id = str(self.raw_owner.get("chunk_id") or "")
                self.callable_name = str(self.raw_owner.get("callable_name") or "")
                self.chunk = self.chunks_by_id.get(self.chunk_id)
                if self.chunk is None or not self.callable_name:
                    continue
                self.chunk_kind = str(self.chunk.get("kind") or "")
                self.chunk_owner = str(self.chunk.get("owner") or "")
                self.declared_callables = {
                    str(task.get("name") or "")
                    for task in self.chunk.get("method_tasks") or []
                    if isinstance(task, _deps.Mapping) and str(task.get("name") or "")
                }
                if self.chunk_kind == "class":
                    self.declared_callables.add("<declaration>")
                    if (
                        self.callable_name == "__init__"
                        and "__init__" not in self.declared_callables
                    ):
                        self.callable_name = "<declaration>"
                if self.chunk_kind in {"function", "async_function"}:
                    self.function_owner_name = self.chunk_owner.rsplit(".", 1)[-1]
                    self.declared_callables.add(self.function_owner_name)
                    if self.callable_name == "<declaration>":
                        self.callable_name = self.function_owner_name
                elif self.chunk_kind == "module":
                    self.declared_callables.add("<module>")
                if self.callable_name not in self.declared_callables:
                    self.behavior_contract_errors.append(
                        f"{self.requirement_id} names undeclared callable `{self.chunk_id}:{self.callable_name}`"
                    )
                    continue
                self.normalized_owners.append(
                    {
                        "chunk_id": self.chunk_id,
                        "path": str(self.chunk.get("path") or ""),
                        "symbol": (
                            (
                                self.chunk_owner
                                if self.callable_name == "<declaration>"
                                else f"{self.chunk_owner}.{self.callable_name}"
                            )
                            if self.chunk_kind == "class"
                            else self.chunk_owner
                        ),
                        "callable_name": self.callable_name,
                    }
                )
            self.operation = self.contract_requirement_text.get(
                self.requirement_id, ""
            ).strip()
            self.expected_observations = list(
                dict.fromkeys(
                    [
                        *self.contract_validation_checks.get(self.requirement_id, []),
                        *self.contract_observable_checks.get(self.requirement_id, []),
                    ]
                )
            )
            self.owner_pairs = {
                (owner["chunk_id"], owner["callable_name"])
                for owner in self.normalized_owners
            }
            self.execution_steps: list[dict[str, _deps.Any]] = []
            self.available_facts: set[str] = set(
                self.contract_dependency_facts.get(self.requirement_id, set())
            )
            self.seen_step_ids: set[str] = set()
            self.seen_step_owner_pairs: set[tuple[str, str]] = set()
            self.observation_count = 0
            self.action_count = 0
            for self.step_index, self.raw_step in enumerate(
                self.raw_contract.get("execution_steps") or [], start=1
            ):
                if not isinstance(self.raw_step, _deps.Mapping):
                    self.behavior_contract_errors.append(
                        f"{self.requirement_id} execution step {self.step_index} is not an object"
                    )
                    continue
                self.step_id = str(self.raw_step.get("step_id") or "").strip()
                self.phase = str(self.raw_step.get("phase") or "").strip().casefold()
                self.chunk_id = str(self.raw_step.get("chunk_id") or "").strip()
                self.callable_name = str(
                    self.raw_step.get("callable_name") or ""
                ).strip()
                self.step_chunk = self.chunks_by_id.get(self.chunk_id) or {}
                if (
                    self.callable_name == "<declaration>"
                    and str(self.step_chunk.get("kind") or "")
                    in {"function", "async_function"}
                ):
                    self.callable_name = str(
                        self.step_chunk.get("owner") or ""
                    ).rsplit(".", 1)[-1]
                if (
                    self.callable_name == "__init__"
                    and (self.chunk_id, "<declaration>") in self.owner_pairs
                ):
                    self.callable_name = "<declaration>"
                self.instruction = str(self.raw_step.get("instruction") or "").strip()
                self.requires = list(
                    dict.fromkeys(
                        (
                            str(value).strip()
                            for value in self.raw_step.get("requires") or []
                            if str(value).strip()
                        )
                    )
                )
                self.produces = list(
                    dict.fromkeys(
                        (
                            str(value).strip()
                            for value in self.raw_step.get("produces") or []
                            if str(value).strip()
                        )
                    )
                )
                self.invalidates = list(
                    dict.fromkeys(
                        (
                            str(value).strip()
                            for value in self.raw_step.get("invalidates") or []
                            if str(value).strip()
                        )
                    )
                )
                self.assertions = list(
                    dict.fromkeys(
                        (
                            str(value).strip()
                            for value in self.raw_step.get("assertions") or []
                            if str(value).strip()
                        )
                    )
                )
                if (
                    not self.step_id
                    or self.step_id in self.seen_step_ids
                    or self.phase not in {"setup", "action", "observation"}
                    or ((self.chunk_id, self.callable_name) not in self.owner_pairs)
                    or (not self.instruction)
                ):
                    self.behavior_contract_errors.append(
                        f"{self.requirement_id} has invalid execution step `{self.step_id or self.step_index}`"
                    )
                    continue

                def state_fact_identity(value: str) -> tuple[str, ...]:
                    tokens = [
                        token
                        for token in _deps.re.split("[._]+", value.casefold())
                        if token
                        and token not in {"self", "widget", "control", "input", "field"}
                    ]
                    return tuple(tokens)

                self.state_fact_identity = state_fact_identity
                self.resolved_requires: list[str] = []
                self.missing_facts: list[str] = []
                for self.fact in self.requires:
                    if self.fact in self.available_facts:
                        self.resolved_requires.append(self.fact)
                        continue
                    self.equivalent_facts = [
                        available
                        for available in self.available_facts
                        if self.state_fact_identity(available)
                        == self.state_fact_identity(self.fact)
                    ]
                    if len(self.equivalent_facts) == 1:
                        self.resolved_requires.append(self.equivalent_facts[0])
                    else:
                        self.missing_facts.append(self.fact)
                if self.missing_facts:
                    self.behavior_contract_errors.append(
                        f"{self.requirement_id} step `{self.step_id}` requires unavailable state: "
                        + ", ".join(self.missing_facts)
                    )
                    continue
                self.requires = list(dict.fromkeys(self.resolved_requires))
                if self.phase == "observation" and (not self.assertions):
                    self.assertions = [
                        observation
                        for observation in self.expected_observations
                        if observation
                        and (
                            not any(
                                (
                                    observation in step.get("assertions", [])
                                    for step in self.execution_steps
                                )
                            )
                        )
                    ]
                    if not self.assertions:
                        self.behavior_contract_errors.append(
                            f"{self.requirement_id} observation step `{self.step_id}` has no direct assertion"
                        )
                        continue
                if self.assertions:
                    self.observation_count += 1
                if self.phase == "action":
                    self.action_count += 1
                self.seen_step_ids.add(self.step_id)
                self.seen_step_owner_pairs.add((self.chunk_id, self.callable_name))
                self.available_facts.difference_update(self.invalidates)
                self.available_facts.update(self.produces)
                self.execution_steps.append(
                    {
                        "step_id": self.step_id,
                        "phase": self.phase,
                        "chunk_id": self.chunk_id,
                        "callable_name": self.callable_name,
                        "instruction": self.instruction,
                        "requires": self.requires,
                        "produces": self.produces,
                        "invalidates": self.invalidates,
                        "assertions": self.assertions,
                    }
                )
            self.sequenced_assertions = list(
                dict.fromkeys(
                    (
                        assertion
                        for step in self.execution_steps
                        if step.get("phase") == "observation"
                        for assertion in step.get("assertions") or []
                        if str(assertion).strip()
                    )
                )
            )
            if self.sequenced_assertions:
                self.expected_observations = self.sequenced_assertions
            self.missing_step_owners = self.owner_pairs - self.seen_step_owner_pairs
            self.declaration_only = bool(
                "declaration"
                in self.contract_action_kinds.get(self.requirement_id, set())
            )
            if (
                not self.execution_steps
                or self.observation_count == 0
                or (self.action_count == 0 and (not self.declaration_only))
                or self.missing_step_owners
            ):
                self.missing_owner_text = ", ".join(
                    (
                        f"{chunk_id}:{callable_name}"
                        for chunk_id, callable_name in sorted(self.missing_step_owners)
                    )
                )
                self.behavior_contract_errors.append(
                    f"{self.requirement_id} lacks a complete ordered state proof"
                    + (
                        f"; unsequenced owners: {self.missing_owner_text}"
                        if self.missing_owner_text
                        else ""
                    )
                )
            if (
                not self.normalized_owners
                or not self.operation
                or (not self.expected_observations)
            ):
                self.behavior_contract_errors.append(
                    f"{self.requirement_id} lacks a declared owner, operation, or observable outcome"
                )
                continue
            self.behavior_contracts_by_requirement[self.requirement_id] = {
                "behavior_id": f"{self.requirement_id}_B01",
                "requirement_id": self.requirement_id,
                "production_owners": self.normalized_owners,
                "polarity": (
                    "rejection"
                    if "rejection"
                    in self.contract_action_kinds.get(self.requirement_id, set())
                    else (
                        "invariant"
                        if "declaration"
                        in self.contract_action_kinds.get(self.requirement_id, set())
                        else "transition"
                    )
                ),
                "preconditions": [],
                "operation": self.operation,
                "expected_observations": self.expected_observations,
                "execution_steps": self.execution_steps,
            }
        self.missing_behavior_contracts = sorted(
            self.behavior_requirement_ids - set(self.behavior_contracts_by_requirement)
        )
        if self.missing_behavior_contracts:
            self.behavior_contract_errors.append(
                "missing behavior contracts for "
                + ", ".join(self.missing_behavior_contracts)
            )
        if self.behavior_contract_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_semantic_audit_failed",
                    errors=[
                        "Plan semantic audit returned invalid behavior ownership: "
                        + "; ".join(self.behavior_contract_errors)
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        self.implementation_plan["behavior_contracts"] = list(
            self.behavior_contracts_by_requirement.values()
        )
        if self.status_callback:
            self.behavior_step_count = sum(
                (
                    len(contract.get("execution_steps") or [])
                    for contract in self.implementation_plan["behavior_contracts"]
                )
            )
            self.status_callback(
                f"Approved ordered behavior plan: {len(self.implementation_plan['behavior_contracts'])} contract(s), {self.behavior_step_count} state-aware step(s), all prerequisite facts and callable owners resolved"
            )
        self.mechanics_by_chunk_requirement = {
            str(chunk.get("chunk_id") or ""): {
                str(row.get("requirement_id") or ""): list(row.get("steps") or [])
                for row in chunk.get("implementation_mechanics") or []
                if isinstance(row, _deps.Mapping)
            }
            for chunk in self.chunks_by_id.values()
        }
        self.validations_by_chunk_requirement = {
            str(chunk.get("chunk_id") or ""): {
                str(row.get("requirement_id") or ""): list(row.get("checks") or [])
                for row in chunk.get("validation_cases") or []
                if isinstance(row, _deps.Mapping)
            }
            for chunk in self.chunks_by_id.values()
        }
        self.mapped_requirements_by_callable: dict[tuple[str, str], list[str]] = {}
        for self.contract in self.implementation_plan["behavior_contracts"]:
            for self.owner in self.contract["production_owners"]:
                self.mapped_requirements_by_callable.setdefault(
                    (self.owner["chunk_id"], self.owner["callable_name"]), []
                ).append(self.contract["requirement_id"])
        for self.chunk_id, self.chunk in self.chunks_by_id.items():
            for self.task in self.chunk.get("method_tasks") or []:
                if not isinstance(self.task, dict):
                    continue
                self.method_name = str(self.task.get("name") or "")
                self.retained_ids = [
                    str(value)
                    for value in self.task.get("requirement_ids") or []
                    if str(value) and str(value) not in self.behavior_requirement_ids
                ]
                self.assigned_ids = list(
                    dict.fromkeys(
                        [
                            *self.retained_ids,
                            *self.mapped_requirements_by_callable.get(
                                (self.chunk_id, self.method_name), []
                            ),
                        ]
                    )
                )
                self.task["requirement_ids"] = self.assigned_ids
                self.task["behavior_ids"] = [
                    value
                    for value in self.assigned_ids
                    if value in self.behavior_requirement_ids
                ]
                self.task["implementation_mechanics"] = list(
                    dict.fromkeys(
                        (
                            str(step)
                            for requirement_id in self.assigned_ids
                            for step in self.mechanics_by_chunk_requirement.get(
                                self.chunk_id, {}
                            ).get(requirement_id, [])
                            if str(step)
                        )
                    )
                )
                self.task["validation_cases"] = list(
                    dict.fromkeys(
                        (
                            str(check)
                            for requirement_id in self.assigned_ids
                            for check in self.validations_by_chunk_requirement.get(
                                self.chunk_id, {}
                            ).get(requirement_id, [])
                            if str(check)
                        )
                    )
                )
            self.materialize_threaded_progress_declarations(self.chunk)
        self.named_chunks = [
            chunk
            for chunk in self.chunks_by_id.values()
            if str(chunk.get("owner") or "") != "<module>"
        ]
        self.explicit_delegation_spec = (
            _deps._explicit_cross_file_delegation_spec(self.user_prompt)
        )
        self.explicit_delegation_chunk_ids: set[str] = set()
        self.explicit_dependency_corrections: list[dict[str, _deps.Any]] = []
        if self.explicit_delegation_spec is not None:
            (
                self.shared_prompt_path,
                self.shared_owner,
                _shared_parameters,
                self.requested_adapters,
            ) = self.explicit_delegation_spec

            def _matches_prompt_path(chunk: _deps.Mapping, prompt_path: str) -> bool:
                normalized = str(chunk.get("path") or "").replace("\\", "/")
                requested = prompt_path.replace("\\", "/")
                return normalized.casefold().endswith("/" + requested.casefold()) or (
                    normalized.casefold() == requested.casefold()
                )

            self.shared_chunk = next(
                (
                    chunk
                    for chunk in self.named_chunks
                    if str(chunk.get("owner") or "") == self.shared_owner
                    and _matches_prompt_path(chunk, self.shared_prompt_path)
                ),
                None,
            )
            self.adapter_chunks: list[dict[str, _deps.Any]] = []
            for self.adapter_path, self.adapter_owner in (
                self.requested_adapters.items()
            ):
                self.adapter_chunk = next(
                    (
                        chunk
                        for chunk in self.named_chunks
                        if str(chunk.get("owner") or "") == self.adapter_owner
                        and _matches_prompt_path(chunk, self.adapter_path)
                    ),
                    None,
                )
                if self.adapter_chunk is not None:
                    self.adapter_chunks.append(self.adapter_chunk)
            if self.shared_chunk is not None and (
                len(self.adapter_chunks) == len(self.requested_adapters)
            ):
                self.named_chunk_ids = {
                    str(chunk.get("chunk_id") or "") for chunk in self.named_chunks
                }
                self.shared_chunk_id = str(self.shared_chunk.get("chunk_id") or "")
                self.explicit_delegation_chunk_ids = {
                    self.shared_chunk_id,
                    *(
                        str(chunk.get("chunk_id") or "")
                        for chunk in self.adapter_chunks
                    ),
                }
                self.shared_chunk["depends_on"] = [
                    dependency_id
                    for dependency_id in self.shared_chunk.get("depends_on") or []
                    if dependency_id not in self.named_chunk_ids
                ]
                for self.adapter_chunk in self.adapter_chunks:
                    self.adapter_chunk_id = str(
                        self.adapter_chunk.get("chunk_id") or ""
                    )
                    self.adapter_chunk["depends_on"] = list(
                        dict.fromkeys(
                            [
                                *(
                                    dependency_id
                                    for dependency_id in self.adapter_chunk.get(
                                        "depends_on"
                                    )
                                    or []
                                    if dependency_id not in self.named_chunk_ids
                                ),
                                self.shared_chunk_id,
                            ]
                        )
                    )
                    self.explicit_dependency_corrections.append(
                        {
                            "chunk_id": self.adapter_chunk_id,
                            "depends_on_chunk_ids": [self.shared_chunk_id],
                            "reason": (
                                "explicit request delegates this adapter to the "
                                "named shared callable"
                            ),
                        }
                    )
        self.dependency_corrections = [
            correction
            for correction in self.semantic_audit.get("dependency_corrections") or []
            if str(correction.get("chunk_id") or "")
            not in self.explicit_delegation_chunk_ids
        ]
        self.dependency_corrections.extend(self.explicit_dependency_corrections)
        self.established_named_dependencies = {
            dependency_id
            for chunk in self.named_chunks
            for dependency_id in chunk.get("depends_on") or []
            if dependency_id in self.chunks_by_id
            and str(self.chunks_by_id[dependency_id].get("owner") or "") != "<module>"
        }
        if (
            len({str(chunk.get("path") or "") for chunk in self.named_chunks}) > 1
            and (not self.established_named_dependencies)
            and (not self.dependency_corrections)
        ):
            self.dependency_stage = _deps.ProjectEditPromptStage(
                key="implementation_plan_dependency_audit",
                label="Resolving cross-file declaration contracts",
                system_prompt="/no_think\nYou are a focused package interface planner. Determine whether one supplied declaration must import or consume another for the original request to form one coherent package. Return only direct, necessary consumer-to-provider chunk dependencies. A data record managed by a service is a dependency; unrelated declarations are not. Do not invent files, owners, or helper APIs. Return JSON only.",
                user_prompt=_deps.json.dumps(
                    {
                        "original_request": self.user_prompt,
                        "declarations": [
                            {
                                "chunk_id": str(chunk.get("chunk_id") or ""),
                                "file": str(chunk.get("path") or ""),
                                "owner": str(chunk.get("owner") or ""),
                                "requirements": list(chunk.get("requirements") or []),
                                "declaration_contract": dict(
                                    chunk.get("declaration_contract") or {}
                                ),
                            }
                            for chunk in self.named_chunks
                        ],
                        "output_contract": {
                            "dependency_corrections": "objects with chunk_id, depends_on_chunk_ids, and reason"
                        },
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                model_tier="local_reasoning",
                num_ctx=3072,
                num_predict=max(140, len(self.named_chunks) * 80),
                timeout=45,
                no_progress_seconds=20,
                prefer_coder=False,
                coder_preference="fast",
                response_format={
                    "type": "object",
                    "properties": {
                        "dependency_corrections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "chunk_id": {"type": "string"},
                                    "depends_on_chunk_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "reason": {"type": "string"},
                                },
                                "required": [
                                    "chunk_id",
                                    "depends_on_chunk_ids",
                                    "reason",
                                ],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["dependency_corrections"],
                    "additionalProperties": False,
                },
                metadata={"disable_thinking": True},
            )
            if self.status_callback:
                self.status_callback(
                    "Resolving cross-file contracts for otherwise disconnected declarations"
                )
            self.dependency_response, self.dependency_timing = _deps._query_stage(
                self.dependency_stage,
                selected_model=self.selected_model,
                settings=self.settings,
                timeout=self.timeout,
            )
            self.timings.append(self.dependency_timing)
            try:
                self.dependency_audit = _deps.json.loads(self.dependency_response)
            except (TypeError, ValueError, _deps.json.JSONDecodeError) as exc:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="plan_semantic_audit_failed",
                        errors=[f"Dependency audit returned invalid JSON: {exc}"],
                        timings=self.timings,
                        implementation_plan=self.implementation_plan,
                        approval_id="",
                    )
                )
            self.dependency_corrections.extend(
                self.dependency_audit.get("dependency_corrections") or []
            )
        self.dependency_correction_errors: list[str] = []
        for self.correction in self.dependency_corrections:
            if not isinstance(self.correction, dict):
                self.dependency_correction_errors.append(
                    "non-object dependency correction"
                )
                continue
            self.chunk_id = str(self.correction.get("chunk_id") or "")
            self.dependency_ids = [
                str(value)
                for value in self.correction.get("depends_on_chunk_ids") or []
                if str(value)
            ]
            if (
                self.chunk_id not in self.chunks_by_id
                or not self.dependency_ids
                or any(
                    (
                        dependency_id not in self.chunks_by_id
                        or dependency_id == self.chunk_id
                        for dependency_id in self.dependency_ids
                    )
                )
            ):
                self.dependency_correction_errors.append(self.chunk_id or "<missing>")
                continue
            self.chunk = self.chunks_by_id[self.chunk_id]
            self.chunk["depends_on"] = list(
                dict.fromkeys(
                    [*list(self.chunk.get("depends_on") or []), *self.dependency_ids]
                )
            )
            if self.status_callback:
                self.status_callback(
                    f"Plan dependency correction: {self.chunk_id} depends on "
                    + ", ".join(self.dependency_ids)
                )
        if self.dependency_correction_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_semantic_audit_failed",
                    errors=[
                        "Plan semantic audit returned invalid dependency corrections: "
                        + ", ".join(self.dependency_correction_errors)
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        self.signature_corrections = list(
            self.semantic_audit.get("signature_corrections") or []
        )
        self.input_requiring_verbs = {
            "add",
            "build",
            "create",
            "delete",
            "find",
            "get",
            "insert",
            "load",
            "process",
            "put",
            "read",
            "register",
            "remove",
            "resolve",
            "save",
            "set",
            "store",
            "transform",
            "unregister",
            "update",
            "write",
        }
        self.corrected_owner_pairs = {
            (
                str(correction.get("chunk_id") or ""),
                str(correction.get("callable_name") or ""),
            )
            for correction in self.signature_corrections
            if isinstance(correction, dict)
        }
        self.suspect_signature_rows: list[dict[str, _deps.Any]] = []
        for self.chunk_id, self.chunk in self.chunks_by_id.items():
            self.contract = self.chunk.get("declaration_contract") or {}
            self.requirement_text = " ".join(
                (
                    str(item.get("text") or "")
                    for item in self.chunk.get("requirements") or []
                    if isinstance(item, dict)
                )
            )
            for self.signature in self.contract.get("callable_signatures") or []:
                self.signature_text = str(self.signature)
                self.match = _deps.re.fullmatch(
                    "def\\s+([a-z_][A-Za-z0-9_]*)\\s*\\(\\s*self\\s*\\)(?:\\s*->\\s*.+)?",
                    self.signature_text,
                )
                if (
                    not self.match
                    or self.match.group(1).split("_", 1)[0]
                    not in self.input_requiring_verbs
                    or (self.chunk_id, self.match.group(1))
                    in self.corrected_owner_pairs
                ):
                    continue
                self.suspect_signature_rows.append(
                    {
                        "chunk_id": self.chunk_id,
                        "owner": str(self.chunk.get("owner") or ""),
                        "callable_name": self.match.group(1),
                        "current_signature": self.signature_text,
                        "assigned_requirements": self.requirement_text,
                        "implementation_mechanics": list(
                            self.chunk.get("implementation_mechanics") or []
                        ),
                        "validation_cases": list(
                            self.chunk.get("validation_cases") or []
                        ),
                    }
                )
        if self.suspect_signature_rows:
            self.signature_stage = _deps.ProjectEditPromptStage(
                key="implementation_plan_signature_audit",
                label="Resolving callable input contracts",
                system_prompt="/no_think\nYou are a focused Python interface planner. For each supplied zero-input method, decide whether its assigned requirement needs caller-selected inputs. Return a correction only when required. Infer the smallest usable parameter list from the requirement. The corrected signature must agree with supplied implementation mechanics and validation cases. Keep self, preserve the callable name, use valid Python syntax, and do not add unrelated options. Return JSON only.",
                user_prompt=_deps.json.dumps(
                    {
                        "original_request": self.user_prompt,
                        "suspect_signatures": self.suspect_signature_rows,
                        "output_contract": {
                            "signature_corrections": "objects with chunk_id, callable_name, corrected_signature, and reason"
                        },
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                model_tier="local_reasoning",
                num_ctx=3072,
                num_predict=max(180, len(self.suspect_signature_rows) * 90),
                timeout=45,
                no_progress_seconds=20,
                prefer_coder=False,
                coder_preference="fast",
                response_format={
                    "type": "object",
                    "properties": {
                        "signature_corrections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "chunk_id": {"type": "string"},
                                    "callable_name": {"type": "string"},
                                    "corrected_signature": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": [
                                    "chunk_id",
                                    "callable_name",
                                    "corrected_signature",
                                    "reason",
                                ],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["signature_corrections"],
                    "additionalProperties": False,
                },
                metadata={"disable_thinking": True},
            )
            if self.status_callback:
                self.status_callback(
                    f"Resolving input contracts for {len(self.suspect_signature_rows)} ambiguous callable signatures"
                )
            self.signature_response, self.signature_timing = _deps._query_stage(
                self.signature_stage,
                selected_model=self.selected_model,
                settings=self.settings,
                timeout=self.timeout,
            )
            self.timings.append(self.signature_timing)
            try:
                self.signature_audit = _deps.json.loads(self.signature_response)
            except (TypeError, ValueError, _deps.json.JSONDecodeError) as exc:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="plan_semantic_audit_failed",
                        errors=[f"Signature audit returned invalid JSON: {exc}"],
                        timings=self.timings,
                        implementation_plan=self.implementation_plan,
                        approval_id="",
                    )
                )
            self.signature_corrections.extend(
                self.signature_audit.get("signature_corrections") or []
            )
        self.signature_correction_errors: list[str] = []
        for self.correction in self.signature_corrections:
            if not isinstance(self.correction, dict):
                self.signature_correction_errors.append(
                    "non-object signature correction"
                )
                continue
            self.chunk_id = str(self.correction.get("chunk_id") or "")
            self.callable_name = str(self.correction.get("callable_name") or "")
            self.corrected_signature = str(
                self.correction.get("corrected_signature") or ""
            ).strip()
            if (
                self.callable_name == "__init__"
                and self.corrected_signature.startswith("def __init__(")
                and (" -> " not in self.corrected_signature)
            ):
                self.corrected_signature += " -> None"
            self.corrected_signature = _deps.re.sub(
                "(:\\s*[^,)=|]+)(\\s*=\\s*None\\b)",
                lambda match: match.group(1).rstrip() + " | None" + match.group(2),
                self.corrected_signature,
            )
            self.chunk = self.chunks_by_id.get(self.chunk_id)
            self.contract = (
                self.chunk.get("declaration_contract") or {}
                if isinstance(self.chunk, dict)
                else {}
            )
            self.allowed_names = {
                "__init__",
                *(
                    [str(self.chunk.get("owner") or "").rsplit(".", 1)[-1]]
                    if isinstance(self.chunk, dict)
                    and str(self.chunk.get("kind") or "") == "function"
                    else []
                ),
                *[
                    str(value)
                    for value in self.contract.get("required_methods") or []
                    if str(value)
                ],
            }
            try:
                self.parsed_signature = _deps.ast.parse(
                    self.corrected_signature + ":\n    pass"
                ).body[0]
            except (SyntaxError, ValueError):
                self.parsed_signature = None
            if (
                self.chunk is None
                or self.callable_name not in self.allowed_names
                or (
                    not isinstance(
                        self.parsed_signature,
                        (_deps.ast.FunctionDef, _deps.ast.AsyncFunctionDef),
                    )
                )
                or (self.parsed_signature.name != self.callable_name)
            ):
                self.signature_correction_errors.append(
                    f"{self.chunk_id or '<missing>'}:{self.callable_name or '<missing>'}"
                )
                continue
            self.signatures = [
                str(value)
                for value in self.contract.get("callable_signatures") or []
                if str(value)
            ]
            self.replacement_pattern = _deps.re.compile(
                f"^def\\s+{_deps.re.escape(self.callable_name)}\\s*\\("
            )
            self.replaced = False
            self.normalized_signatures: list[str] = []
            for self.signature in self.signatures:
                if self.replacement_pattern.search(self.signature):
                    if not self.replaced:
                        self.normalized_signatures.append(self.corrected_signature)
                        self.replaced = True
                    continue
                self.normalized_signatures.append(self.signature)
            if not self.replaced:
                self.normalized_signatures.append(self.corrected_signature)
            self.contract["callable_signatures"] = self.normalized_signatures
            for self.method_task in self.chunk.get("method_tasks") or []:
                if (
                    isinstance(self.method_task, dict)
                    and str(self.method_task.get("name") or "") == self.callable_name
                ):
                    self.method_task["signature"] = self.corrected_signature
            if self.status_callback:
                self.status_callback(
                    f"Plan signature correction: {self.chunk_id}:{self.callable_name} -> {self.corrected_signature}"
                )
        if self.signature_correction_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_semantic_audit_failed",
                    errors=[
                        "Plan semantic audit returned invalid signature corrections: "
                        + ", ".join(self.signature_correction_errors)
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        if self.status_callback:
            self.status_callback("Running deterministic post-audit plan completeness")
        self.post_audit_completeness_errors = (
            self.validate_implementation_plan_completeness(
                self.implementation_plan, original_prompt=self.user_prompt
            )
        )
        if self.status_callback:
            self.status_callback("Deterministic post-audit plan completeness finished")
        if self.post_audit_completeness_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_correction_required",
                    errors=self.post_audit_completeness_errors,
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        self.valid_chunk_ids = {
            str(row.get("chunk_id") or "")
            for row in self.semantic_audit_rows
            if str(row.get("chunk_id") or "")
        }
        self.planned_assignment_map = {
            requirement_id: {
                str(row.get("chunk_id") or "")
                for row in self.semantic_audit_rows
                if requirement_id in row.get("requirement_ids", [])
            }
            for requirement_id in self.valid_requirement_ids
        }
        self.audited_assignment_map: dict[str, set[str]] = {}
        self.invalid_audit_rows: list[str] = []
        for self.row in self.semantic_audit.get("assignments") or []:
            if not isinstance(self.row, dict):
                self.invalid_audit_rows.append("non-object assignment")
                continue
            self.requirement_id = str(self.row.get("requirement_id") or "")
            self.owner_chunk_ids = {
                str(value)
                for value in self.row.get("owner_chunk_ids") or []
                if str(value)
            }
            if (
                self.requirement_id not in self.valid_requirement_ids
                or not self.owner_chunk_ids
                or (not self.owner_chunk_ids <= self.valid_chunk_ids)
                or (self.requirement_id in self.audited_assignment_map)
            ):
                self.invalid_audit_rows.append(self.requirement_id or "<missing>")
                continue
            self.audited_assignment_map[self.requirement_id] = self.owner_chunk_ids
        if self.invalid_audit_rows:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_semantic_audit_failed",
                    errors=[
                        "Plan semantic audit returned invalid owner-correction rows: "
                        + ", ".join(self.invalid_audit_rows)
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        self.semantic_mismatches = [
            requirement_id
            for requirement_id in sorted(self.audited_assignment_map)
            if self.audited_assignment_map[requirement_id]
            != self.planned_assignment_map[requirement_id]
        ]
        if self.semantic_mismatches:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_correction_required",
                    errors=[
                        f"Semantic plan audit disagrees on {requirement_id}: planned {sorted(self.planned_assignment_map[requirement_id])}, independently mapped {sorted(self.audited_assignment_map[requirement_id])}."
                        for requirement_id in self.semantic_mismatches
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        if self.status_callback:
            self.status_callback("Computing deterministic plan approval fingerprint")
        self.approval_id = self.implementation_plan_approval_id(
            self.implementation_plan
        )
        if self.status_callback:
            self.status_callback(
                f"Computed plan approval fingerprint: {self.approval_id[:12]}"
            )
        self.cached_approval = self.early_cached_approval
        if self.approved_plan_id and self.cached_approval is None:
            self.cached_approval = self.load_approved_plan_candidate(
                self.approved_plan_id, prompt=self.user_prompt, project_root=self.root
            )
        if self.cached_approval:
            self.implementation_plan = dict(self.cached_approval["implementation_plan"])
            self.manifest = [
                dict(item) for item in self.cached_approval.get("manifest") or []
            ]
            self.requirement_ledger = [
                dict(item)
                for item in self.cached_approval.get("requirement_ledger") or []
            ]
            self.chunk_plan = [
                dict(item) for item in self.cached_approval.get("assignments") or []
            ]
            self.approval_id = self.approved_plan_id
        else:
            if self.status_callback:
                self.status_callback("Persisting approved plan candidate atomically")
            self.persist_approved_plan_candidate(
                self.approval_id,
                prompt=self.user_prompt,
                project_root=self.root,
                implementation_plan=self.implementation_plan,
                manifest=self.manifest,
                requirement_ledger=self.requirement_ledger,
                assignments=self.chunk_plan,
            )
            if self.status_callback:
                self.status_callback("Approved plan candidate persisted")
        if self.status_callback:
            self.status_callback(
                f"Implementation plan ready for approval: {self.approval_id[:12]}"
            )
        if self.unresolved_plan_evidence:
            self.acquisition_requests = list(
                self.implementation_plan.get("capability_acquisition_requests") or []
            )
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status=(
                        "capability_acquisition_required"
                        if self.acquisition_requests
                        else "plan_evidence_unresolved"
                    ),
                    errors=[
                        "Implementation planning could not verify required callable references after internal, installed, plugin, catalog, capability-graph, and official-source resolution. Generation remains blocked; reviewed acquisition actions are attached when available.",
                        *self.unresolved_plan_evidence,
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        if self.plan_only or self.approved_plan_id != self.approval_id:
            self.approval_errors: list[str] = []
            if self.approved_plan_id and self.approved_plan_id != self.approval_id:
                self.approval_errors.append(
                    "The supplied plan approval does not match the current requirement ledger, manifest, ownership plan, or dependencies. Review and approve the updated plan."
                )
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_approval_required",
                    errors=self.approval_errors,
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id=self.approval_id,
                )
            )
        self.artifact_file_stages = list(
            _deps.build_project_edit_artifact_file_stages(self.plan, self.manifest)
        )
        self.early_restored_files = _deps._load_workflow_checkpoint(
            self.root, self.prompt, self.selected_model, self.approval_id
        )
        self.early_restored_workflow_state = _deps._load_workflow_checkpoint_state(
            self.root, self.prompt, self.selected_model, self.approval_id
        )
        self.chunk_stages = _deps.build_project_edit_artifact_chunk_stages(
            self.plan,
            self.manifest,
            self.requirement_ledger,
            self.chunk_plan,
            implementation_plan=self.implementation_plan,
        )
        self.chunk_coverage: list[dict[str, _deps.Any]] = [
            {
                "requirement_id": str(assignment["requirement_id"]),
                "chunk_id": str(declaration_id),
                "implemented": False,
                "validated": False,
                "assembled": False,
            }
            for assignment in self.chunk_plan
            for declaration_id in assignment.get("declaration_ids") or []
        ]
        self.deterministic_chunk_ids = {
            str(chunk.get("chunk_id") or "")
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, dict)
            and (not bool(chunk.get("generation_required", True)))
        }
        if self.deterministic_chunk_ids:
            for self.coverage_row in self.chunk_coverage:
                if (
                    str(self.coverage_row.get("chunk_id") or "")
                    in self.deterministic_chunk_ids
                ):
                    self.coverage_row.update(
                        {
                            "implemented": True,
                            "validated": True,
                            "assembled": True,
                            "resolution": "deterministic_non_code_contract",
                        }
                    )
            if self.status_callback:
                self.status_callback(
                    "Resolved deterministic structure/quality chunk(s) without model generation: "
                    + ", ".join(sorted(self.deterministic_chunk_ids))
                )
        if self.early_restored_files:
            self.chunk_stages = []
            self.restored_coverage = (
                self.early_restored_workflow_state.get("chunk_coverage")
                if isinstance(self.early_restored_workflow_state, dict)
                else None
            )
            if isinstance(self.restored_coverage, list):
                self.chunk_coverage = [
                    dict(row) for row in self.restored_coverage if isinstance(row, dict)
                ]
            if self.status_callback:
                self.status_callback(
                    f"Resuming {len(self.early_restored_files)} checkpointed candidate file(s) before generation; all current validators will run again."
                )
        self.validated_chunks: list[tuple[str, str, str]] = []
        self.generated_chunk_sources: dict[str, str] = {}
        self.rejected_file_candidates: dict[str, str] = {}
        self.rejected_file_errors: dict[str, list[str]] = {}
        self.chunk_pipeline_failed = False
