"""Project-edit workflow phase: _run_requirement_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import _WorkflowReturn


class _ProjectEditRequirementPhase:
    """Provide the requirement workflow phase."""

    def _run_requirement_phase(self) -> None:
        """Run the requirement phase.

        :return: None.
        """
        if self.incomplete_requirement_ids:
            self.incomplete_rows = [
                {
                    "requirement_id": str(requirement.get("id") or ""),
                    "requirement": str(requirement.get("text") or ""),
                    "chunk_id": str(chunk.get("chunk_id") or ""),
                    "owner": str(chunk.get("owner") or ""),
                    "kind": str(chunk.get("kind") or ""),
                    "declared_callables": list(
                        (chunk.get("declaration_contract") or {}).get(
                            "callable_signatures", []
                        )
                    ),
                    "declared_attributes": [
                        {
                            "name": str(attribute.get("name") or ""),
                            "type": str(attribute.get("type") or ""),
                            "construction_required": bool(
                                attribute.get("construction_required")
                            ),
                            "runtime_use_required": bool(
                                attribute.get("runtime_use_required")
                            ),
                        }
                        for attribute in (chunk.get("declaration_contract") or {}).get(
                            "attributes", []
                        )
                        if isinstance(attribute, _deps.Mapping)
                        and str(attribute.get("name") or "")
                    ],
                    "verified_calls": [
                        {
                            "name": str(call.get("name") or ""),
                            "signature": str(call.get("signature") or ""),
                            "import_statement": str(
                                next(
                                    (
                                        evidence.get("import_statement")
                                        for evidence in chunk.get("evidence") or []
                                        if isinstance(evidence, _deps.Mapping)
                                        and str(evidence.get("name") or "")
                                        == str(call.get("name") or "")
                                        and evidence.get("selected_for_generation")
                                    ),
                                    "",
                                )
                                or ""
                            ),
                            "source_excerpt": str(
                                next(
                                    (
                                        evidence.get("source_excerpt")
                                        for evidence in chunk.get("evidence") or []
                                        if isinstance(evidence, _deps.Mapping)
                                        and str(evidence.get("name") or "")
                                        == str(call.get("name") or "")
                                        and evidence.get("selected_for_generation")
                                    ),
                                    "",
                                )
                                or ""
                            )[:1200],
                        }
                        for call in (chunk.get("declaration_contract") or {}).get(
                            "required_calls", []
                        )
                        if isinstance(call, _deps.Mapping)
                        and str(requirement.get("id") or "")
                        in {str(value) for value in call.get("requirement_ids") or []}
                    ],
                    "existing_mechanics": next(
                        (
                            list(row.get("steps") or [])
                            for row in chunk.get("implementation_mechanics") or []
                            if isinstance(row, _deps.Mapping)
                            and str(row.get("requirement_id") or "")
                            == str(requirement.get("id") or "")
                        ),
                        [],
                    ),
                }
                for chunk in self.implementation_plan.get("chunks") or []
                if isinstance(chunk, _deps.Mapping)
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, _deps.Mapping)
                and str(requirement.get("id") or "") in self.incomplete_requirement_ids
            ]
            if self.incomplete_rows:
                if self.status_callback:
                    self.status_callback(
                        f"Deterministic planning left {len(self.incomplete_rows)} behavior clause(s) unresolved; requesting one focused reasoning pass for concrete mechanics and observable proof"
                    )
                self.completion_stage = _deps.ProjectEditPromptStage(
                    key="implementation_plan_requirement_completion",
                    label="Completing unresolved behavior contracts",
                    system_prompt="Return JSON only. Complete only the supplied unresolved implementation requirements. For each row, provide concrete implementation mechanics that identify the actual state transition or return/rejection behavior, direct public-API validation checks, and machine-inspectable observable actions. Use only the supplied chunk_id and declared callable surface. Never invent files or filenames; the approved manifest is fixed. Do not invent dependencies, public methods, constructor parameters, instance fields, wrapper objects such as `self.ui`, or unrelated behavior. Every `self.<field>` state reference must name a supplied declared_attribute. References to supplied declared_callables are valid both as calls and as callback objects; inherited method calls are allowed. UI mechanics must read values from the declared controls using their real widget accessors instead of disconnected shadow fields. Map those values to verified call parameters using the exact supplied signature and documented value shape. A mechanic must say what changes or is returned; a validation must say what operation runs and what exact result is asserted. Never return comments, TODOs, ellipses, placeholders, 'as needed', 'process later', or any instruction that leaves handling of a returned value unspecified. Every produced value must be consumed by a stated observable UI update, return, or assertion.",
                    user_prompt=_deps.json.dumps(
                        {"unresolved_requirements": self.incomplete_rows},
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
                            "repairs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "requirement_id": {"type": "string"},
                                        "chunk_id": {"type": "string"},
                                        "mechanics": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "validations": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "observable_actions": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "kind": {"type": "string"},
                                                    "mechanic": {"type": "string"},
                                                    "observable": {"type": "string"},
                                                },
                                                "required": [
                                                    "kind",
                                                    "mechanic",
                                                    "observable",
                                                ],
                                                "additionalProperties": False,
                                            },
                                        },
                                    },
                                    "required": [
                                        "requirement_id",
                                        "chunk_id",
                                        "mechanics",
                                        "validations",
                                        "observable_actions",
                                    ],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["repairs"],
                        "additionalProperties": False,
                    },
                    metadata={"disable_thinking": False},
                )
                self.completion_response, self.completion_timing = _deps._query_stage(
                    self.completion_stage,
                    selected_model=self.selected_model,
                    settings=self.settings,
                    timeout=self.timeout,
                )
                self.timings.append(self.completion_timing)
                try:
                    self.completion_payload = _deps.json.loads(self.completion_response)
                except (TypeError, ValueError, _deps.json.JSONDecodeError):
                    self.completion_payload = {}
                self.approved_completion_keys = {
                    (row["requirement_id"], row["chunk_id"])
                    for row in self.incomplete_rows
                }
                self.completion_contract_errors: list[str] = []
                self.rows_by_key = {
                    (row["requirement_id"], row["chunk_id"]): row
                    for row in self.incomplete_rows
                }
                self.common_widget_members = {
                    "setEnabled",
                    "setVisible",
                    "setToolTip",
                    "setStatusTip",
                    "setProperty",
                }
                self.widget_members_by_type = {
                    "QCheckBox": {
                        "checkState",
                        "clicked",
                        "isChecked",
                        "setChecked",
                        "stateChanged",
                        "toggled",
                    },
                    "QComboBox": {
                        "activated",
                        "addItem",
                        "addItems",
                        "currentData",
                        "currentIndex",
                        "currentIndexChanged",
                        "currentText",
                        "currentTextChanged",
                        "setCurrentIndex",
                    },
                    "QDoubleSpinBox": {
                        "setMaximum",
                        "setMinimum",
                        "setRange",
                        "setValue",
                        "value",
                        "valueChanged",
                    },
                    "QLabel": {"clear", "setPixmap", "setText", "text"},
                    "QLineEdit": {
                        "clear",
                        "editingFinished",
                        "setPlaceholderText",
                        "setText",
                        "text",
                        "textChanged",
                    },
                    "QListWidget": {
                        "addItem",
                        "addItems",
                        "clear",
                        "currentItem",
                        "itemSelectionChanged",
                        "selectedItems",
                        "setCurrentItem",
                    },
                    "QProgressBar": {
                        "maximum",
                        "minimum",
                        "reset",
                        "setMaximum",
                        "setMinimum",
                        "setRange",
                        "setValue",
                        "value",
                        "valueChanged",
                    },
                    "QPushButton": {"click", "clicked", "setText"},
                    "QSpinBox": {
                        "setMaximum",
                        "setMinimum",
                        "setRange",
                        "setValue",
                        "value",
                        "valueChanged",
                    },
                    "QTextEdit": {
                        "append",
                        "clear",
                        "setPlainText",
                        "textChanged",
                        "toPlainText",
                    },
                }

                def completion_contract_failures(
                    repair: _deps.Mapping[str, _deps.Any],
                    repair_key: tuple[str, str],
                    source_row: _deps.Mapping[str, _deps.Any],
                ) -> list[str]:
                    failures: list[str] = []
                    declared_attribute_types = {
                        str(attribute.get("name") or ""): str(
                            attribute.get("type") or ""
                        ).rsplit(".", 1)[-1]
                        for attribute in source_row.get("declared_attributes") or []
                        if isinstance(attribute, _deps.Mapping)
                        and str(attribute.get("name") or "")
                    }
                    declared_attributes = set(declared_attribute_types)
                    declared_callables = {
                        match.group(1)
                        for signature in source_row.get("declared_callables") or []
                        for match in [
                            _deps.re.search(
                                "([A-Za-z_][A-Za-z0-9_]*)\\s*\\(", str(signature)
                            )
                        ]
                        if match
                    }
                    contract_text = "\n".join(
                        [
                            *(str(value) for value in repair.get("mechanics") or []),
                            *(str(value) for value in repair.get("validations") or []),
                            *(
                                str(action.get("mechanic") or "")
                                + "\n"
                                + str(action.get("observable") or "")
                                for action in repair.get("observable_actions") or []
                                if isinstance(action, _deps.Mapping)
                            ),
                        ]
                    )
                    if (
                        _deps.re.search(
                            "(?:^|\\s)(?:TODO|TBD)(?:\\s|$)|(?<!\\.)\\.\\.\\.(?!\\.)|\\b(?:as needed|process later)\\b|,\\s*\\.",
                            contract_text,
                            flags=_deps.re.IGNORECASE,
                        )
                        or not contract_text.strip()
                    ):
                        failures.append(
                            f"{repair_key[0]} contains placeholder or malformed mechanics"
                        )
                    undeclared_fields: set[str] = set()
                    undeclared_callables: set[str] = set()
                    for field_match in _deps.re.finditer(
                        "\\bself\\.([A-Za-z_][A-Za-z0-9_]*)", contract_text
                    ):
                        field_name = field_match.group(1)
                        trailing = contract_text[field_match.end() :].lstrip()
                        if trailing.startswith("("):
                            if field_name not in declared_callables:
                                undeclared_callables.add(field_name)
                            continue
                        if field_name in declared_callables:
                            continue
                        if field_name not in declared_attributes:
                            undeclared_fields.add(field_name)
                    undeclared_callables.update(
                        (
                            method_match.group(1)
                            for method_match in _deps.re.finditer(
                                "`([A-Za-z_][A-Za-z0-9_]*)`\\s+method\\b",
                                contract_text,
                                flags=_deps.re.IGNORECASE,
                            )
                            if method_match.group(1) not in declared_callables
                        )
                    )
                    if undeclared_fields:
                        failures.append(
                            f"{repair_key[0]} references undeclared instance field(s): "
                            + ", ".join(sorted(undeclared_fields))
                        )
                    if undeclared_callables:
                        failures.append(
                            f"{repair_key[0]} references undeclared callable(s): "
                            + ", ".join(sorted(undeclared_callables))
                        )
                    for member_match in _deps.re.finditer(
                        "\\bself\\.([A-Za-z_][A-Za-z0-9_]*)\\.([A-Za-z_][A-Za-z0-9_]*)",
                        contract_text,
                    ):
                        field_name, member_name = member_match.groups()
                        widget_type = declared_attribute_types.get(field_name, "")
                        if not widget_type.startswith("Q"):
                            continue
                        allowed_members = (
                            self.widget_members_by_type.get(widget_type, set())
                            | self.common_widget_members
                        )
                        if member_name not in allowed_members:
                            failures.append(
                                f"{repair_key[0]} references unverified {widget_type} member `{field_name}.{member_name}`"
                            )
                    for action in repair.get("observable_actions") or []:
                        if not isinstance(action, _deps.Mapping):
                            continue
                        observable = str(action.get("observable") or "").strip()
                        if _deps.re.search(
                            "\\b(?:updated|displayed|shown|works?|valid|correct|created|called)\\s*$",
                            observable,
                            flags=_deps.re.IGNORECASE,
                        ):
                            failures.append(
                                f"{repair_key[0]} has vague observable `{observable}`"
                            )
                    return failures

                self.completion_contract_failures = completion_contract_failures
                for self.repair in self.completion_payload.get("repairs") or []:
                    if not isinstance(self.repair, _deps.Mapping):
                        continue
                    self.repair_key = (
                        str(self.repair.get("requirement_id") or ""),
                        str(self.repair.get("chunk_id") or ""),
                    )
                    self.source_row = self.rows_by_key.get(self.repair_key)
                    if self.source_row is None:
                        continue
                    self.completion_contract_errors.extend(
                        self.completion_contract_failures(
                            self.repair, self.repair_key, self.source_row
                        )
                    )
                if self.completion_contract_errors:
                    if self.status_callback:
                        self.status_callback(
                            "Rejecting unsafe optional behavior completion and preserving the deterministic plan: "
                            + " | ".join(self.completion_contract_errors)
                        )
                    self.completion_payload = {}
                self.applied_completion_ids: list[str] = []
                for self.repair in self.completion_payload.get("repairs") or []:
                    if not isinstance(self.repair, _deps.Mapping):
                        continue
                    self.repair_key = (
                        str(self.repair.get("requirement_id") or ""),
                        str(self.repair.get("chunk_id") or ""),
                    )
                    self.mechanics = [
                        str(value).strip()
                        for value in self.repair.get("mechanics") or []
                        if str(value).strip()
                    ]
                    self.validations = [
                        str(value).strip()
                        for value in self.repair.get("validations") or []
                        if str(value).strip()
                    ]
                    self.actions = [
                        {
                            "kind": str(action.get("kind") or "").strip(),
                            "mechanic": str(action.get("mechanic") or "").strip(),
                            "observable": str(action.get("observable") or "").strip(),
                        }
                        for action in self.repair.get("observable_actions") or []
                        if isinstance(action, _deps.Mapping)
                        and str(action.get("kind") or "").strip()
                        and str(action.get("mechanic") or "").strip()
                        and str(action.get("observable") or "").strip()
                    ]
                    if (
                        self.repair_key not in self.approved_completion_keys
                        or not self.mechanics
                        or (not self.validations)
                        or (not self.actions)
                    ):
                        continue
                    self.target_chunk = next(
                        (
                            chunk
                            for chunk in self.implementation_plan.get("chunks") or []
                            if isinstance(chunk, dict)
                            and str(chunk.get("chunk_id") or "") == self.repair_key[1]
                        ),
                        None,
                    )
                    if self.target_chunk is None:
                        continue
                    for self.field_name, self.values_key, self.values in (
                        ("implementation_mechanics", "steps", self.mechanics),
                        ("validation_cases", "checks", self.validations),
                        ("observable_contracts", "actions", self.actions),
                    ):
                        self.rows = self.target_chunk.setdefault(self.field_name, [])
                        self.matching_row = next(
                            (
                                row
                                for row in self.rows
                                if isinstance(row, dict)
                                and str(row.get("requirement_id") or "")
                                == self.repair_key[0]
                            ),
                            None,
                        )
                        if self.matching_row is None:
                            self.matching_row = {"requirement_id": self.repair_key[0]}
                            self.rows.append(self.matching_row)
                        self.existing_values = list(
                            self.matching_row.get(self.values_key) or []
                        )
                        self.merged_values: list[_deps.Any] = []
                        self.seen_value_keys: set[str] = set()
                        for self.value in [*self.existing_values, *self.values]:
                            self.value_key = (
                                _deps.json.dumps(
                                    self.value, sort_keys=True, ensure_ascii=True
                                )
                                if isinstance(self.value, (_deps.Mapping, list, tuple))
                                else str(self.value)
                            )
                            if self.value_key in self.seen_value_keys:
                                continue
                            self.seen_value_keys.add(self.value_key)
                            self.merged_values.append(self.value)
                        self.matching_row[self.values_key] = self.merged_values
                    self.applied_completion_ids.append(self.repair_key[0])
                if self.status_callback and self.applied_completion_ids:
                    self.status_callback(
                        "Resolved focused planning clauses: "
                        + ", ".join(sorted(set(self.applied_completion_ids)))
                    )
                for self.chunk in self.implementation_plan.get("chunks") or []:
                    if not isinstance(self.chunk, _deps.Mapping):
                        continue
                    for self.mechanic_row in (
                        self.chunk.get("implementation_mechanics") or []
                    ):
                        if not isinstance(self.mechanic_row, dict):
                            continue
                        self.steps = [
                            str(step).strip()
                            for step in self.mechanic_row.get("steps") or []
                            if str(step).strip()
                        ]
                        self.concrete_steps = [
                            step
                            for step in self.steps
                            if not any(
                                (
                                    pattern.search(step)
                                    for pattern in self.generic_mechanic_patterns
                                )
                            )
                        ]
                        if self.concrete_steps:
                            self.mechanic_row["steps"] = list(
                                dict.fromkeys(self.concrete_steps)
                            )
                self.completeness_errors = (
                    self.validate_implementation_plan_completeness(
                        self.implementation_plan, original_prompt=self.user_prompt
                    )
                )
        if self.completeness_errors:
            self.ambiguous_contracts = {
                (chunk_id, requirement_id)
                for chunk_id, requirement_id in _deps.re.findall(
                    "Chunk `([^`]+)` has ambiguous implementation mechanics for `([^`]+)`",
                    "\n".join(self.completeness_errors),
                )
            }
            self.compiled_contracts: list[str] = []
            for self.chunk in self.implementation_plan.get("chunks") or []:
                if not isinstance(self.chunk, dict):
                    continue
                self.chunk_id = str(self.chunk.get("chunk_id") or "")
                self.declaration_contract = self.chunk.get("declaration_contract") or {}
                self.attributes = [
                    {
                        "name": str(attribute.get("name") or ""),
                        "type": str(attribute.get("type") or ""),
                    }
                    for attribute in self.declaration_contract.get("attributes") or []
                    if isinstance(attribute, _deps.Mapping)
                    and str(attribute.get("name") or "")
                ]
                self.qt_attributes = [
                    attribute
                    for attribute in self.attributes
                    if attribute["type"].rsplit(".", 1)[-1].startswith("Q")
                ]
                self.required_calls = [
                    call
                    for call in self.declaration_contract.get("required_calls") or []
                    if isinstance(call, _deps.Mapping) and str(call.get("name") or "")
                ]
                if not self.qt_attributes or not self.required_calls:
                    continue

                def semantic_terms(value: str) -> set[str]:
                    return {
                        (
                            token[:-3]
                            if token.endswith("ies") and len(token) > 4
                            else (
                                token[:-1]
                                if token.endswith("s") and len(token) > 3
                                else token
                            )
                        )
                        for token in _deps.re.findall(
                            "[a-z0-9]+", value.casefold().replace("_", " ")
                        )
                        if token
                        not in {"input", "field", "widget", "control", "line", "edit"}
                    }

                self.semantic_terms = semantic_terms
                self.attribute_accessors = {
                    "QCheckBox": "isChecked()",
                    "QComboBox": "currentData() or currentText()",
                    "QDoubleSpinBox": "value()",
                    "QLineEdit": "text()",
                    "QListWidget": "selectedItems()",
                    "QSpinBox": "value()",
                    "QTextEdit": "toPlainText()",
                }
                for self.requirement_id in sorted(
                    (
                        requirement_id
                        for candidate_chunk_id, requirement_id in self.ambiguous_contracts
                        if candidate_chunk_id == self.chunk_id
                    )
                ):
                    self.requirement_action_methods = [
                        str(task.get("name") or "")
                        for task in self.chunk.get("method_tasks") or []
                        if isinstance(task, _deps.Mapping)
                        and str(task.get("name") or "")
                        and (str(task.get("name") or "") != "__init__")
                        and (
                            self.requirement_id
                            in {
                                str(value)
                                for value in [
                                    *(task.get("requirement_ids") or []),
                                    *(task.get("behavior_ids") or []),
                                ]
                            }
                        )
                    ]
                    self.requirement_action_methods = list(
                        dict.fromkeys(self.requirement_action_methods)
                    )
                    if len(self.requirement_action_methods) != 1:
                        continue
                    self.action_method = self.requirement_action_methods[0]
                    self.mechanics: list[str] = []
                    for self.call in self.required_calls:
                        self.call_requirement_ids = {
                            str(value)
                            for value in self.call.get("requirement_ids") or []
                        }
                        if (
                            self.call_requirement_ids
                            and self.requirement_id not in self.call_requirement_ids
                        ):
                            continue
                        self.parameter_types = {
                            str(name): str(type_name)
                            for name, type_name in (
                                self.call.get("parameter_types") or {}
                            ).items()
                            if str(name)
                        }
                        self.parameter_sources: list[str] = []
                        for (
                            self.parameter_name,
                            self.parameter_type,
                        ) in self.parameter_types.items():
                            self.parameter_terms = self.semantic_terms(
                                self.parameter_name
                            )
                            self.ranked_attributes = sorted(
                                self.qt_attributes,
                                key=lambda attribute: (
                                    -len(
                                        self.parameter_terms
                                        & self.semantic_terms(attribute["name"])
                                    ),
                                    attribute["name"],
                                ),
                            )
                            self.source_attribute = (
                                self.ranked_attributes[0]
                                if self.ranked_attributes
                                and self.parameter_terms
                                & self.semantic_terms(self.ranked_attributes[0]["name"])
                                else None
                            )
                            if self.source_attribute is None:
                                self.parameter_sources.append(
                                    f"`{self.parameter_name}` uses its verified default"
                                )
                                continue
                            self.widget_type = self.source_attribute["type"].rsplit(
                                ".", 1
                            )[-1]
                            self.accessor = self.attribute_accessors.get(
                                self.widget_type, "its public value accessor"
                            )
                            if _deps.re.search(
                                "\\b(?:list|tuple|set)\\b",
                                self.parameter_type,
                                flags=_deps.re.IGNORECASE,
                            ):
                                self.conversion = (
                                    "strip the text, split comma-separated values, strip each value, discard empty values, and pass the typed collection or None when no values remain"
                                    if self.widget_type in {"QLineEdit", "QTextEdit"}
                                    else f"convert the selected values to the verified `{self.parameter_type}` shape"
                                )
                            else:
                                self.conversion = f"read `{self.accessor}` and preserve the verified `{self.parameter_type}` value shape"
                            self.parameter_sources.append(
                                f"`{self.parameter_name}`: read `self.{self.source_attribute['name']}.{self.accessor}`, then {self.conversion}"
                            )
                        if self.parameter_sources:
                            self.mechanics.append(
                                f"In `self.{self.action_method}`, "
                                + "; ".join(self.parameter_sources)
                                + "."
                            )
                        self.mechanics.append(
                            f"Invoke the verified dependency `{self.call.get('name')}` exactly once using signature `{self.call.get('signature')}` and the normalized values."
                        )
                    if not self.mechanics:
                        continue
                    self.rows = self.chunk.setdefault("implementation_mechanics", [])
                    self.matching_row = next(
                        (
                            row
                            for row in self.rows
                            if isinstance(row, dict)
                            and str(row.get("requirement_id") or "")
                            == self.requirement_id
                        ),
                        None,
                    )
                    if self.matching_row is None:
                        self.matching_row = {"requirement_id": self.requirement_id}
                        self.rows.append(self.matching_row)
                    self.existing_steps = [
                        str(step).strip()
                        for step in self.matching_row.get("steps") or []
                        if str(step).strip()
                    ]
                    self.matching_row["steps"] = list(
                        dict.fromkeys([*self.existing_steps, *self.mechanics])
                    )
                    self.compiled_contracts.append(
                        f"{self.chunk_id}:{self.requirement_id}"
                    )
            if self.compiled_contracts:
                self.completeness_errors = (
                    self.validate_implementation_plan_completeness(
                        self.implementation_plan, original_prompt=self.user_prompt
                    )
                )
                if self.status_callback:
                    self.status_callback(
                        "Compiled rejected ambiguous mechanics from declared owners, Qt field contracts, and verified API signatures: "
                        + ", ".join(self.compiled_contracts)
                    )
        for self.chunk in self.implementation_plan.get("chunks") or []:
            if not isinstance(self.chunk, dict):
                continue
            self.contract_text = " ".join(
                (
                    str(value)
                    for field_name, value_name in (
                        ("implementation_mechanics", "steps"),
                        ("validation_cases", "checks"),
                    )
                    for row in self.chunk.get(field_name) or []
                    if isinstance(row, _deps.Mapping)
                    for value in row.get(value_name) or []
                )
            )
            self.contract_text += " " + " ".join(
                (
                    str(action.get("mechanic") or "")
                    + " "
                    + str(action.get("observable") or "")
                    for row in self.chunk.get("observable_contracts") or []
                    if isinstance(row, _deps.Mapping)
                    for action in row.get("actions") or []
                    if isinstance(action, _deps.Mapping)
                )
            )
            self.selected_return_type = "Any"
            for self.evidence in self.chunk.get("evidence") or []:
                if not isinstance(
                    self.evidence, _deps.Mapping
                ) or not self.evidence.get("selected_for_generation"):
                    continue
                self.return_match = _deps.re.search(
                    "(?:^|\\n)Returns?\\s*\\n[-]+\\s*\\n\\s*([A-Za-z_][A-Za-z0-9_\\[\\], .|]*)",
                    str(self.evidence.get("source_excerpt") or ""),
                    flags=_deps.re.IGNORECASE,
                )
                if self.return_match:
                    self.raw_return = self.return_match.group(1).strip().casefold()
                    if self.raw_return.startswith("dict"):
                        self.selected_return_type = "dict[str, Any]"
                    elif self.raw_return.startswith("list"):
                        self.selected_return_type = "list[Any]"
                    elif self.raw_return.startswith(("str", "bool", "int", "float")):
                        self.selected_return_type = self.raw_return.split()[0]
                    break
            self.declaration_contract = self.chunk.get("declaration_contract") or {}
            for self.task in self.chunk.get("method_tasks") or []:
                if not isinstance(self.task, dict):
                    continue
                self.method_name = str(self.task.get("name") or "")
                self.signature = str(self.task.get("signature") or "")
                if (
                    not self.method_name
                    or "-> None" not in self.signature
                    or (
                        not _deps.re.search(
                            f"(?:\\breturn(?:s|ed|ing)?\\b[^\\n]*\\b{_deps.re.escape(self.method_name)}\\b|\\b{_deps.re.escape(self.method_name)}\\b[^\\n]*\\breturn(?:s|ed|ing)?\\b)",
                            self.contract_text,
                            flags=_deps.re.IGNORECASE,
                        )
                    )
                ):
                    continue
                self.revised_signature = self.signature.replace(
                    "-> None", f"-> {self.selected_return_type}"
                )
                self.task["signature"] = self.revised_signature
                self.declaration_contract["callable_signatures"] = [
                    (
                        self.revised_signature
                        if _deps.re.search(
                            f"\\bdef\\s+{_deps.re.escape(self.method_name)}\\s*\\(",
                            str(candidate),
                        )
                        else candidate
                    )
                    for candidate in self.declaration_contract.get(
                        "callable_signatures", []
                    )
                ]
        if self.completeness_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_correction_required",
                    errors=self.completeness_errors,
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        self.semantic_audit_rows = []
        for self.chunk in self.implementation_plan.get("chunks") or []:
            if not isinstance(self.chunk, dict):
                continue
            self.declaration = self.chunk.get("declaration_contract") or {}
            self.semantic_audit_rows.append(
                {
                    "chunk_id": str(self.chunk.get("chunk_id") or ""),
                    "file": str(self.chunk.get("path") or ""),
                    "owner": str(self.chunk.get("owner") or ""),
                    "kind": str(self.chunk.get("kind") or ""),
                    "requirement_ids": [
                        str(requirement.get("id") or "")
                        for requirement in self.chunk.get("requirements") or []
                        if isinstance(requirement, dict)
                    ],
                    "depends_on": list(self.chunk.get("depends_on") or []),
                    "declaration": {
                        "owner": str(self.declaration.get("owner") or ""),
                        "kind": str(self.declaration.get("kind") or ""),
                        "base": str(self.declaration.get("base") or ""),
                        "callable_signatures": list(
                            self.declaration.get("callable_signatures") or []
                        ),
                        "required_methods": list(
                            self.declaration.get("required_methods") or []
                        ),
                        "fields": list(self.declaration.get("fields") or []),
                        "attributes": list(self.declaration.get("attributes") or []),
                        "decorators": list(self.declaration.get("decorators") or []),
                        "module_entry_point_required": bool(
                            self.declaration.get("module_entry_point_required")
                        ),
                    },
                    "method_tasks": [
                        {
                            "name": str(task.get("name") or ""),
                            "signature": str(task.get("signature") or ""),
                            "requirement_ids": list(
                                task.get("requirement_ids")
                                or task.get("behavior_ids")
                                or []
                            ),
                        }
                        for task in self.chunk.get("method_tasks") or []
                        if isinstance(task, _deps.Mapping)
                    ],
                }
            )
        self.semantic_audit_stage = _deps.ProjectEditPromptStage(
            key="implementation_plan_semantic_audit",
            label="Verifying implementation plan against request",
            system_prompt="/no_think\nYou independently verify every request requirement against the supplied implementation chunk IDs. Return JSON only. Use only supplied requirement IDs and chunk IDs. Report only owner assignments that are wrong; return an empty assignments array when all planned owners are correct. Assign a module entry point to the module chunk. Assign a method requested as part of a class to that class chunk. This is owner verification for a future plan, not code review; do not report missing implementation and do not attempt a whole-package semantic review. Deterministic planning already validated declaration existence, mechanics, and observable checks. Do not echo correct assignments. Treat declaration.callable_signatures and method_tasks as planned declarations that will be generated; do not report them missing because source code does not exist yet. A provider declaration referenced through depends_on is imported by the consumer and must not be redeclared in the consumer file. Audit every supplied callable signature for input feasibility. Caller-selected values must enter through parameters rather than undeclared constants or magically available state. An operation that stores, adds, selects, removes, transforms, or configures a specific value cannot be argument-free when its assigned requirement names the needed inputs. When a signature cannot receive all values required by its assigned requirement, return one narrow signature correction. Preserve signatures that are already sufficient. Do not add optional features or rename requested callables. Verify cross-file dependencies as well: when one requested declaration is clearly the data representation or service consumed by another, return the missing chunk dependency; never connect unrelated declarations. For every requirement, verify that its owner has a concrete implementation mechanic and an observable validation case, then return one behavior contract for every behavior or integration requirement. Each behavior contract must identify the exact declared callable or callables that perform the behavior, its polarity, required preconditions, operation, observable outcomes, and an ordered execution_steps proof. Every execution step must name a declared owner, an actionable instruction, symbolic facts it requires, produces, or invalidates, and direct assertions owned by observation steps. Setup establishes facts, actions transition them, and observations must occur before a later step invalidates the state they require. Never require a fact that no earlier step produced. Method-task ownership in the input is provisional; correct it through behavior_contracts rather than reporting that mismatch as a contract error. Additional private helpers or lifecycle methods are valid when their task explicitly supports an owned requirement or integration boundary. When a requirement explicitly names a declared callable, include that exact callable as a production owner. Use `<declaration>` for class-level field, decorator, inheritance, or generated-constructor behavior. Map constructor validation implemented by a declared lifecycle method such as __post_init__ to that lifecycle method, even though the public test operation constructs the class. Do not map an explicitly named method's behavior to __init__. The declaration_errors and contract_errors arrays are reserved for the post-build semantic reviewer and must be empty in this ownership pass.",
            user_prompt=_deps.json.dumps(
                {
                    "original_request": self.user_prompt,
                    "requirement_ledger": self.requirement_ledger,
                    "planned_chunks": self.semantic_audit_rows,
                    "output_contract": {
                        "assignments": "only incorrect planned owner assignments, with requirement_id and corrected owner_chunk_ids selected only from planned_chunks; otherwise an empty array",
                        "declaration_errors": "reserved for post-build semantic review; always empty",
                        "signature_corrections": "only required corrections, each with chunk_id, callable_name, corrected_signature, and reason; otherwise an empty array",
                        "dependency_corrections": "only missing evidence-backed chunk dependencies, each with chunk_id, depends_on_chunk_ids, and reason; otherwise empty",
                        "behavior_contracts": "one row for every behavior or integration requirement, with only declared callable owners, concrete observable behavior, and ordered state-aware execution_steps",
                        "contract_errors": "reserved for post-build semantic review; always empty",
                    },
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            model_tier="local_reasoning",
            num_ctx=4096,
            num_predict=-1,
            timeout=90,
            no_progress_seconds=20,
            prefer_coder=False,
            coder_preference="fast",
            response_format={
                "type": "object",
                "properties": {
                    "assignments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "requirement_id": {"type": "string"},
                                "owner_chunk_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["requirement_id", "owner_chunk_ids"],
                            "additionalProperties": False,
                        },
                    },
                    "declaration_errors": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
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
                    },
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
                            "required": ["chunk_id", "depends_on_chunk_ids", "reason"],
                            "additionalProperties": False,
                        },
                    },
                    "behavior_contracts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "requirement_id": {"type": "string"},
                                "production_owners": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "chunk_id": {"type": "string"},
                                            "callable_name": {"type": "string"},
                                        },
                                        "required": ["chunk_id", "callable_name"],
                                        "additionalProperties": False,
                                    },
                                },
                                "polarity": {
                                    "type": "string",
                                    "enum": [
                                        "success",
                                        "rejection",
                                        "invariant",
                                        "transition",
                                        "integration",
                                    ],
                                },
                                "preconditions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "operation": {"type": "string"},
                                "expected_observations": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
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
                            "required": [
                                "requirement_id",
                                "production_owners",
                                "polarity",
                                "preconditions",
                                "operation",
                                "expected_observations",
                                "execution_steps",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "contract_errors": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "assignments",
                    "declaration_errors",
                    "signature_corrections",
                    "dependency_corrections",
                    "behavior_contracts",
                    "contract_errors",
                ],
                "additionalProperties": False,
            },
            metadata={"disable_thinking": False},
        )
        self.audited_requirement_ids = {
            str(requirement.get("id") or "")
            for row in self.semantic_audit_rows
            for requirement in [
                {"id": requirement_id}
                for requirement_id in row.get("requirement_ids", [])
            ]
            if str(requirement.get("id") or "")
        }
        self.ledger_requirement_ids = {
            str(row.get("id") or "")
            for row in self.requirement_ledger
            if isinstance(row, dict) and str(row.get("id") or "")
        }
        self.fully_materialized_owner_coverage = (
            bool(self.ledger_requirement_ids)
            and self.ledger_requirement_ids <= self.audited_requirement_ids
        )
        if self.early_cached_approval or self.fully_materialized_owner_coverage:
            self.semantic_audit = {
                "assignments": [
                    {
                        "requirement_id": requirement_id,
                        "owner_chunk_ids": sorted(
                            {
                                str(row.get("chunk_id") or "")
                                for row in self.semantic_audit_rows
                                if requirement_id in row.get("requirement_ids", [])
                            }
                        ),
                    }
                    for requirement_id in {
                        str(row.get("id") or "")
                        for row in self.requirement_ledger
                        if isinstance(row, dict) and str(row.get("id") or "")
                    }
                ],
                "declaration_errors": [],
                "dependency_corrections": [],
                "signature_corrections": [],
                "behavior_contracts": list(
                    self.implementation_plan.get("behavior_contracts") or []
                ),
                "contract_errors": [],
            }
            self.timings.append(
                {
                    "stage": "implementation_plan_semantic_audit",
                    "label": "Using fully materialized semantic plan audit",
                    "model": (
                        "approved_plan_cache"
                        if self.early_cached_approval
                        else "deterministic_owner_coverage"
                    ),
                    "elapsed_ms": 0.0,
                }
            )
        else:
            if self.status_callback:
                self.status_callback(
                    "Verifying the complete implementation plan semantically"
                )
            self.semantic_audit_response, self.semantic_audit_timing = (
                _deps._query_stage(
                    self.semantic_audit_stage,
                    selected_model=self.selected_model,
                    settings=self.settings,
                    timeout=self.timeout,
                )
            )
            self.timings.append(self.semantic_audit_timing)
            try:
                self.semantic_audit = _deps.json.loads(self.semantic_audit_response)
            except (TypeError, ValueError, _deps.json.JSONDecodeError) as exc:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="plan_semantic_audit_failed",
                        errors=[f"Plan semantic audit returned invalid JSON: {exc}"],
                        timings=self.timings,
                        implementation_plan=self.implementation_plan,
                        approval_id="",
                    )
                )
        self.valid_requirement_ids = {
            str(row.get("id") or "")
            for row in self.requirement_ledger
            if isinstance(row, dict) and str(row.get("id") or "")
        }
        self.declaration_errors = [
            str(value).strip()
            for value in self.semantic_audit.get("declaration_errors") or []
            if str(value).strip()
        ]
        self.contract_errors = [
            str(value).strip()
            for value in self.semantic_audit.get("contract_errors") or []
            if str(value).strip()
        ]
        if self.declaration_errors or self.contract_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_correction_required",
                    errors=[
                        f"Semantic plan declaration audit: {error}"
                        for error in self.declaration_errors
                    ]
                    + [
                        f"Semantic plan contract audit: {error}"
                        for error in self.contract_errors
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        self.chunks_by_id = {
            str(chunk.get("chunk_id") or ""): chunk
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, dict) and str(chunk.get("chunk_id") or "")
        }
        self.behavior_requirement_ids: set[str] = set()
        for self.chunk in self.implementation_plan.get("chunks") or []:
            if not isinstance(self.chunk, _deps.Mapping):
                continue
            self.required_call_requirement_ids = {
                str(requirement_id)
                for call in (
                    self.chunk.get("declaration_contract", {}).get("required_calls", [])
                    if isinstance(self.chunk.get("declaration_contract"), _deps.Mapping)
                    else []
                )
                if isinstance(call, _deps.Mapping)
                for requirement_id in call.get("requirement_ids") or []
                if str(requirement_id)
            }
            for self.requirement in self.chunk.get("requirements") or []:
                if not isinstance(self.requirement, _deps.Mapping):
                    continue
                self.requirement_id = str(self.requirement.get("id") or "")
                self.requirement_text = str(self.requirement.get("text") or "")
                self.semantic_role = str(
                    self.requirement.get("semantic_role") or ""
                ).casefold()
                self.interactive_ui_contract = bool(
                    str(self.chunk.get("kind") or "") == "class"
                    and _deps.re.search(
                        "\\b(?:qt|pyside[26]?|pyqt[56]?|ui|dialog|window|widget|panel)\\b",
                        self.requirement_text,
                        flags=_deps.re.IGNORECASE,
                    )
                    and _deps.re.search(
                        "\\b(?:button|connect|control|field|filter|input|progress|selection|signal|slot|status)\\b",
                        self.requirement_text,
                        flags=_deps.re.IGNORECASE,
                    )
                )
                if self.requirement_id and (
                    self.semantic_role in {"behavior", "integration"}
                    or self.requirement_id in self.required_call_requirement_ids
                    or self.interactive_ui_contract
                    or bool(
                        _deps.re.search(
                            r"\b(?:expire|evict|refresh(?:es|ed|ing)?|resolve|"
                            r"register|reject|raise|return|preserve|normalize|"
                            r"atomically|thread-safe)\b",
                            self.requirement_text,
                            flags=_deps.re.IGNORECASE,
                        )
                    )
                ):
                    self.behavior_requirement_ids.add(self.requirement_id)
        self.candidate_behavior_contracts = [
            dict(contract)
            for contract in self.semantic_audit.get("behavior_contracts") or []
            if isinstance(contract, _deps.Mapping)
            and str(contract.get("requirement_id") or "")
            in self.behavior_requirement_ids
        ]
        self.existing_candidate_contract_ids = {
            str(contract.get("requirement_id") or "")
            for contract in self.candidate_behavior_contracts
        }
        for self.requirement_id in sorted(
            self.behavior_requirement_ids - self.existing_candidate_contract_ids
        ):
            self.deterministic_owners: list[dict[str, str]] = []
            for self.chunk_id, self.chunk in self.chunks_by_id.items():
                if not any(
                    (
                        isinstance(requirement, _deps.Mapping)
                        and str(requirement.get("id") or "") == self.requirement_id
                        for requirement in self.chunk.get("requirements") or []
                    )
                ):
                    continue
                self.task_names = [
                    str(task.get("name") or "")
                    for task in self.chunk.get("method_tasks") or []
                    if isinstance(task, _deps.Mapping)
                    and str(task.get("name") or "")
                    and (
                        self.requirement_id
                        in {
                            str(value)
                            for value in [
                                *list(task.get("requirement_ids") or []),
                                *list(task.get("behavior_ids") or []),
                            ]
                        }
                    )
                ]
                self.deterministic_owners.extend(
                    (
                        {"chunk_id": self.chunk_id, "callable_name": task_name}
                        for task_name in self.task_names
                    )
                )
                if not self.task_names:
                    self.deterministic_owners.append(
                        {
                            "chunk_id": self.chunk_id,
                            "callable_name": (
                                "<module>"
                                if str(self.chunk.get("kind") or "") == "module"
                                else "<declaration>"
                            ),
                        }
                    )
            if self.deterministic_owners:
                self.candidate_behavior_contracts.append(
                    {
                        "requirement_id": self.requirement_id,
                        "production_owners": self.deterministic_owners,
                    }
                )
        if (
            self.candidate_behavior_contracts
            and (not self.early_cached_approval)
            and (not self.fully_materialized_owner_coverage)
        ):
            self.behavior_requirement_text = {
                str(requirement.get("id") or ""): str(requirement.get("text") or "")
                for chunk in self.implementation_plan.get("chunks") or []
                if isinstance(chunk, _deps.Mapping)
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, _deps.Mapping)
                and str(requirement.get("id") or "") in self.behavior_requirement_ids
            }
            self.allowed_behavior_owners = [
                {
                    "chunk_id": chunk_id,
                    "owner": str(chunk.get("owner") or ""),
                    "callable_names": list(
                        dict.fromkeys(
                            [
                                *(
                                    ["<declaration>"]
                                    if str(chunk.get("kind") or "") == "class"
                                    else []
                                ),
                                *[
                                    str(task.get("name") or "")
                                    for task in chunk.get("method_tasks") or []
                                    if isinstance(task, _deps.Mapping)
                                    and str(task.get("name") or "")
                                ],
                                *(
                                    [str(chunk.get("owner") or "").rsplit(".", 1)[-1]]
                                    if str(chunk.get("kind") or "")
                                    in {"function", "async_function"}
                                    else []
                                ),
                                *(
                                    ["<module>"]
                                    if str(chunk.get("kind") or "") == "module"
                                    else []
                                ),
                            ]
                        )
                    ),
                }
                for chunk_id, chunk in self.chunks_by_id.items()
            ]
            self.behavior_review_stage = _deps.ProjectEditPromptStage(
                key="implementation_plan_behavior_contract_review",
                label="Reviewing exact behavior ownership",
                system_prompt="Map each supplied requirement to the exact declared callable or callables that implement it. Return JSON only. Use only allowed chunk IDs and callable names. An explicitly named callable must own its behavior. A relationship spanning multiple operations must name every callable needed to implement the relationship. In particular, ordering across insertion and removal needs both owners, and an operation that becomes allowed after another operation needs both owners. Include every callable that could independently cause the observable contract to fail; focused repair can narrow from runtime evidence later. Class fields, decorators, and generated constructors use <declaration>. Lifecycle validation uses its declared lifecycle method. Do not restate or reinterpret behavior.",
                user_prompt=_deps.json.dumps(
                    {
                        "requirements": self.behavior_requirement_text,
                        "allowed_owners": self.allowed_behavior_owners,
                        "proposed_owners": [
                            {
                                "requirement_id": contract.get("requirement_id"),
                                "production_owners": contract.get("production_owners"),
                            }
                            for contract in self.candidate_behavior_contracts
                        ],
                        "output": "owner_mappings with exactly one row per requirement_id and production_owners selected only from allowed_owners",
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                model_tier="local_reasoning",
                num_ctx=4096,
                num_predict=-1,
                timeout=90,
                no_progress_seconds=20,
                prefer_coder=False,
                coder_preference="fast",
                response_format="json",
                metadata={"disable_thinking": False},
            )
            if self.status_callback:
                self.status_callback(
                    "Reviewing exact callable ownership for each behavior"
                )
            self.behavior_review_response, self.behavior_review_timing = (
                _deps._query_stage(
                    self.behavior_review_stage,
                    selected_model=self.selected_model,
                    settings=self.settings,
                    timeout=self.timeout,
                )
            )
            self.timings.append(self.behavior_review_timing)
            try:
                self.behavior_review = _deps.json.loads(self.behavior_review_response)
            except (TypeError, ValueError, _deps.json.JSONDecodeError) as exc:
                self.behavior_review = {}
                if self.status_callback:
                    self.status_callback(
                        "Behavior owner review returned invalid JSON; preserving only independently audited owner mappings."
                    )
            self.owner_mappings = {
                str(contract.get("requirement_id") or ""): list(
                    contract.get("production_owners") or []
                )
                for contract in self.behavior_review.get("owner_mappings") or []
                if isinstance(contract, _deps.Mapping)
                and str(contract.get("requirement_id") or "")
                in self.behavior_requirement_ids
            }
            self.allowed_owner_pairs = {
                (str(allowed_owner.get("chunk_id") or ""), str(callable_name or ""))
                for allowed_owner in self.allowed_behavior_owners
                for callable_name in allowed_owner.get("callable_names") or []
            }
            for self.candidate_contract in self.candidate_behavior_contracts:
                self.requirement_id = str(
                    self.candidate_contract.get("requirement_id") or ""
                )
                if (
                    not self.requirement_id
                    or self.requirement_id in self.owner_mappings
                    or self.requirement_id not in self.behavior_requirement_ids
                ):
                    continue
                self.candidate_owners = [
                    dict(owner)
                    for owner in self.candidate_contract.get("production_owners") or []
                    if isinstance(owner, _deps.Mapping)
                    and (
                        str(owner.get("chunk_id") or ""),
                        str(owner.get("callable_name") or ""),
                    )
                    in self.allowed_owner_pairs
                ]
                if self.candidate_owners:
                    self.owner_mappings[self.requirement_id] = self.candidate_owners
                    if self.status_callback:
                        self.status_callback(
                            f"Recovered omitted behavior owner mapping for {self.requirement_id} from the independently audited plan."
                        )
            self.declaration_requirement_pattern = _deps.re.compile(
                "\\b(?:constructor|__init__|public\\s+parameters?|dataclass\\s+fields?|typed\\s+fields?|decorators?|inherit(?:s|ance|ing)?|base\\s+class)\\b",
                flags=_deps.re.IGNORECASE,
            )
            for self.requirement_id in sorted(
                self.behavior_requirement_ids - set(self.owner_mappings)
            ):
                self.requirement_text = self.behavior_requirement_text.get(
                    self.requirement_id, ""
                )
                self.declaration_owners = [
                    {"chunk_id": chunk_id, "callable_name": "<declaration>"}
                    for chunk_id, chunk in self.chunks_by_id.items()
                    if str(chunk.get("kind") or "") == "class"
                    and any(
                        (
                            isinstance(requirement, _deps.Mapping)
                            and str(requirement.get("id") or "") == self.requirement_id
                            for requirement in chunk.get("requirements") or []
                        )
                    )
                    and ((chunk_id, "<declaration>") in self.allowed_owner_pairs)
                    and (
                        self.declaration_requirement_pattern.search(
                            self.requirement_text
                        )
                        or (
                            _deps.re.search(
                                "\\b(?:reject|validate|forbid|refuse|raise)\\w*\\b|\\b(?:empty|blank|negative|invalid|missing)\\b",
                                self.requirement_text,
                                flags=_deps.re.IGNORECASE,
                            )
                            and any(
                                (
                                    _deps.re.search(
                                        f"\\b{_deps.re.escape(str(field.get('name') or ''))}\\b",
                                        self.requirement_text,
                                        flags=_deps.re.IGNORECASE,
                                    )
                                    for field in chunk.get(
                                        "declaration_contract", {}
                                    ).get("fields")
                                    or []
                                    if str(field.get("name") or "")
                                )
                            )
                        )
                    )
                ]
                if self.declaration_owners:
                    self.owner_mappings[self.requirement_id] = self.declaration_owners
                    if self.status_callback:
                        self.status_callback(
                            f"Assigned declaration-shaped requirement {self.requirement_id} to its approved class declaration."
                        )
            if set(self.owner_mappings) != self.behavior_requirement_ids:
                self.missing_owner_mappings = sorted(
                    self.behavior_requirement_ids - set(self.owner_mappings)
                )
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="plan_semantic_audit_failed",
                        errors=[
                            "Behavior owner review did not return exactly one mapping for every behavioral requirement and no independently audited mapping was available for: "
                            + ", ".join(self.missing_owner_mappings)
                        ],
                        timings=self.timings,
                        implementation_plan=self.implementation_plan,
                        approval_id="",
                    )
                )

            def deterministic_causal_owners(
                requirement_id: str,
            ) -> list[dict[str, str]]:
                requirement_context = self.behavior_requirement_text.get(
                    requirement_id, ""
                ).casefold()
                concept_patterns = {
                    "insert": _deps.re.compile(
                        "\\b(?:add|append|enqueue|insert|put|register|schedule|store)\\w*\\b"
                    ),
                    "remove": _deps.re.compile(
                        "\\b(?:delete|dequeue|discard|pop|remov|release)\\w*\\b"
                    ),
                    "observe": _deps.re.compile(
                        "\\b(?:find|get|iterat|list|order|read|report|snapshot|view)\\w*\\b"
                    ),
                }
                active_concepts = {
                    concept
                    for concept, pattern in concept_patterns.items()
                    if pattern.search(requirement_context)
                }
                if _deps.re.search("\\bduplicate\\b", requirement_context):
                    active_concepts.add("insert")
                if _deps.re.search(
                    "\\b(?:insertion\\s+)?order\\b", requirement_context
                ):
                    active_concepts.update({"insert", "remove", "observe"})
                if "snapshot" in requirement_context and _deps.re.search(
                    "\\b(?:cannot\\s+mutate|detach|immutable|independent)\\b",
                    requirement_context,
                ):
                    active_concepts.update({"insert", "observe"})
                if _deps.re.search(
                    "\\bindexerror\\b[^.!?\\n]{0,80}\\bempty\\b|\\bempty\\b[^.!?\\n]{0,80}\\bindexerror\\b",
                    requirement_context,
                ):
                    active_concepts.discard("observe")
                    active_concepts.add("remove")
                method_prefix_concepts = {
                    "insert": (
                        "add",
                        "append",
                        "enqueue",
                        "insert",
                        "put",
                        "register",
                        "schedule",
                        "store",
                    ),
                    "remove": (
                        "delete",
                        "dequeue",
                        "discard",
                        "pop",
                        "remove",
                        "release",
                    ),
                    "observe": (
                        "find",
                        "get",
                        "iter",
                        "list",
                        "read",
                        "report",
                        "snapshot",
                        "view",
                    ),
                }
                causal: list[dict[str, str]] = []
                for allowed_owner in self.allowed_behavior_owners:
                    chunk_id = str(allowed_owner.get("chunk_id") or "")
                    chunk = self.chunks_by_id.get(chunk_id, {})
                    if not any(
                        (
                            isinstance(requirement, _deps.Mapping)
                            and str(requirement.get("id") or "") == requirement_id
                            for requirement in chunk.get("requirements") or []
                        )
                    ):
                        continue
                    for callable_name in allowed_owner.get("callable_names") or []:
                        lowered_name = str(callable_name).casefold()
                        if lowered_name in {"<declaration>", "<module>"}:
                            continue
                        if any(
                            (
                                concept in active_concepts
                                and lowered_name.startswith(prefixes)
                                for concept, prefixes in method_prefix_concepts.items()
                            )
                        ):
                            causal.append(
                                {
                                    "chunk_id": chunk_id,
                                    "callable_name": str(callable_name),
                                }
                            )
                return causal

            self.deterministic_causal_owners = deterministic_causal_owners
            self.candidate_behavior_contracts = [
                {
                    **contract,
                    "production_owners": list(
                        {
                            (
                                str(owner.get("chunk_id") or ""),
                                str(owner.get("callable_name") or ""),
                            ): dict(owner)
                            for owner in [
                                *(
                                    self.deterministic_causal_owners(
                                        str(contract.get("requirement_id") or "")
                                    )
                                    or self.owner_mappings[
                                        str(contract.get("requirement_id") or "")
                                    ]
                                ),
                                *[
                                    {
                                        "chunk_id": allowed_owner["chunk_id"],
                                        "callable_name": callable_name,
                                    }
                                    for allowed_owner in self.allowed_behavior_owners
                                    for callable_name in allowed_owner["callable_names"]
                                    if callable_name
                                    not in {"<declaration>", "<module>"}
                                    and _deps.re.search(
                                        f"(?<![.\\w]){_deps.re.escape(callable_name)}\\s*\\(",
                                        self.behavior_requirement_text.get(
                                            str(contract.get("requirement_id") or ""),
                                            "",
                                        ),
                                    )
                                ],
                            ]
                            if str(owner.get("chunk_id") or "")
                            and str(owner.get("callable_name") or "")
                        }.values()
                    ),
                }
                for contract in self.candidate_behavior_contracts
            ]
            self.existing_contract_ids = {
                str(contract.get("requirement_id") or "")
                for contract in self.candidate_behavior_contracts
                if isinstance(contract, _deps.Mapping)
            }
            for self.requirement_id in sorted(
                self.behavior_requirement_ids - self.existing_contract_ids
            ):
                self.task_owners = [
                    {
                        "chunk_id": str(chunk.get("chunk_id") or ""),
                        "callable_name": str(task.get("name") or ""),
                    }
                    for chunk in self.implementation_plan.get("chunks") or []
                    if isinstance(chunk, _deps.Mapping)
                    for task in chunk.get("method_tasks") or []
                    if isinstance(task, _deps.Mapping)
                    and str(task.get("name") or "")
                    and (
                        self.requirement_id
                        in {
                            str(value)
                            for value in [
                                *list(task.get("requirement_ids") or []),
                                *list(task.get("behavior_ids") or []),
                            ]
                        }
                    )
                ]
                self.audited_owners = self.task_owners or list(
                    self.owner_mappings.get(self.requirement_id) or []
                )
                if not self.audited_owners:
                    continue
                self.candidate_behavior_contracts.append(
                    {
                        "requirement_id": self.requirement_id,
                        "production_owners": self.audited_owners,
                    }
                )
                if self.status_callback:
                    self.status_callback(
                        f"Restored omitted behavior contract {self.requirement_id} from its deterministic operation, observable checks, and audited owners."
                    )
        self.contract_requirement_text = {
            str(requirement.get("id") or ""): str(requirement.get("text") or "")
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, _deps.Mapping)
            for requirement in chunk.get("requirements") or []
            if isinstance(requirement, _deps.Mapping)
            and str(requirement.get("id") or "") in self.behavior_requirement_ids
        }
        self.contract_validation_checks: dict[str, list[str]] = {}
        self.contract_observable_checks: dict[str, list[str]] = {}
        self.contract_action_kinds: dict[str, set[str]] = {}
        self.contract_dependency_facts: dict[str, set[str]] = {}
        for self.chunk in self.implementation_plan.get("chunks") or []:
            if not isinstance(self.chunk, _deps.Mapping):
                continue
            self.declaration_contract = self.chunk.get("declaration_contract") or {}
            if isinstance(self.declaration_contract, _deps.Mapping):
                for self.required_call in self.declaration_contract.get(
                    "required_calls", []
                ):
                    if not isinstance(self.required_call, _deps.Mapping):
                        continue
                    self.qualified_name = str(self.required_call.get("name") or "")
                    if not self.qualified_name:
                        continue
                    self.dependency_facts = {
                        self.qualified_name,
                        self.qualified_name.rsplit(".", 1)[0],
                        self.qualified_name.rsplit(".", 1)[-1],
                    }
                    for self.requirement_id in self.required_call.get(
                        "requirement_ids", []
                    ):
                        if str(self.requirement_id):
                            self.contract_dependency_facts.setdefault(
                                str(self.requirement_id), set()
                            ).update(self.dependency_facts)
            for self.validation in self.chunk.get("validation_cases") or []:
                if not isinstance(self.validation, _deps.Mapping):
                    continue
                self.requirement_id = str(self.validation.get("requirement_id") or "")
                if self.requirement_id in self.behavior_requirement_ids:
                    self.contract_validation_checks.setdefault(
                        self.requirement_id, []
                    ).extend(
                        (
                            str(check).strip()
                            for check in self.validation.get("checks") or []
                            if str(check).strip()
                        )
                    )
            for self.observable in self.chunk.get("observable_contracts") or []:
                if not isinstance(self.observable, _deps.Mapping):
                    continue
                self.requirement_id = str(self.observable.get("requirement_id") or "")
                if self.requirement_id in self.behavior_requirement_ids:
                    self.contract_observable_checks.setdefault(
                        self.requirement_id, []
                    ).extend(
                        (
                            str(action.get("observable") or "").strip()
                            for action in self.observable.get("actions") or []
                            if isinstance(action, _deps.Mapping)
                            and str(action.get("observable") or "").strip()
                        )
                    )
                    self.contract_action_kinds.setdefault(
                        self.requirement_id, set()
                    ).update(
                        (
                            str(action.get("kind") or "").casefold()
                            for action in self.observable.get("actions") or []
                            if isinstance(action, _deps.Mapping)
                            and str(action.get("kind") or "")
                        )
                    )
        self.selected_behavior_evidence: dict[str, list[dict[str, str]]] = {}
        for self.chunk in self.implementation_plan.get("chunks") or []:
            if not isinstance(self.chunk, _deps.Mapping):
                continue
            for self.evidence in self.chunk.get("evidence") or []:
                if not isinstance(
                    self.evidence, _deps.Mapping
                ) or not self.evidence.get("selected_for_generation"):
                    continue
                self.compact_evidence = {
                    "name": str(self.evidence.get("name") or ""),
                    "signature": str(self.evidence.get("signature") or ""),
                    "import_statement": str(
                        self.evidence.get("import_statement") or ""
                    ),
                    "source_excerpt": str(self.evidence.get("source_excerpt") or "")[
                        :1200
                    ],
                }
                for self.requirement_id in self.evidence.get("requirement_ids") or []:
                    if str(self.requirement_id):
                        self.selected_behavior_evidence.setdefault(
                            str(self.requirement_id), []
                        ).append(self.compact_evidence)
        self.behavior_sequence_inputs = [
            {
                "requirement_id": str(contract.get("requirement_id") or ""),
                "requirement": self.contract_requirement_text.get(
                    str(contract.get("requirement_id") or ""), ""
                ),
                "operation": self.contract_requirement_text.get(
                    str(contract.get("requirement_id") or ""), ""
                ),
                "production_owners": list(contract.get("production_owners") or []),
                "mechanics": [
                    str(step)
                    for chunk in self.implementation_plan.get("chunks") or []
                    if isinstance(chunk, _deps.Mapping)
                    for row in chunk.get("implementation_mechanics") or []
                    if isinstance(row, _deps.Mapping)
                    and str(row.get("requirement_id") or "")
                    == str(contract.get("requirement_id") or "")
                    for step in row.get("steps") or []
                    if str(step)
                ],
                "validation_checks": self.contract_validation_checks.get(
                    str(contract.get("requirement_id") or ""), []
                )
                + self.contract_observable_checks.get(
                    str(contract.get("requirement_id") or ""), []
                ),
                "expected_observations": self.contract_validation_checks.get(
                    str(contract.get("requirement_id") or ""), []
                )
                + self.contract_observable_checks.get(
                    str(contract.get("requirement_id") or ""), []
                ),
                "polarity_hints": sorted(
                    self.contract_action_kinds.get(
                        str(contract.get("requirement_id") or ""), set()
                    )
                ),
                "verified_dependencies": self.selected_behavior_evidence.get(
                    str(contract.get("requirement_id") or ""), []
                ),
                "declared_attributes": [
                    {
                        "name": str(attribute.get("name") or ""),
                        "type": str(attribute.get("type") or ""),
                    }
                    for owner in contract.get("production_owners") or []
                    if isinstance(owner, _deps.Mapping)
                    for owner_chunk in [
                        self.chunks_by_id.get(str(owner.get("chunk_id") or ""), {})
                    ]
                    for attribute in (
                        owner_chunk.get("declaration_contract") or {}
                    ).get("attributes", [])
                    if isinstance(attribute, _deps.Mapping)
                    and str(attribute.get("name") or "")
                ],
            }
            for contract in self.candidate_behavior_contracts
            if isinstance(contract, _deps.Mapping)
            and str(contract.get("requirement_id") or "")
        ]
        self.sequenced_steps_by_requirement: dict[str, list[dict[str, _deps.Any]]] = {}
        self.behavior_contract_errors: list[str] = []
        for self.approved_contract in (
            self.implementation_plan.get("behavior_contracts") or []
        ):
            if not isinstance(self.approved_contract, _deps.Mapping):
                continue
            self.approved_requirement_id = str(
                self.approved_contract.get("requirement_id") or ""
            )
            self.approved_steps = [
                dict(step)
                for step in self.approved_contract.get("execution_steps") or []
                if isinstance(step, _deps.Mapping)
            ]
            if self.approved_requirement_id and self.approved_steps:
                self.sequenced_steps_by_requirement[self.approved_requirement_id] = (
                    self.approved_steps
                )
