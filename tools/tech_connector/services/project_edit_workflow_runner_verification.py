"""Project-edit workflow phase: _run_verification_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import _WorkflowReturn


class _ProjectEditVerificationPhase:
    """Provide the verification workflow phase."""

    def _run_verification_phase(self) -> None:
        """Run the verification phase.

        :return: None.
        """
        for self.chunk_index, (
            self.chunk_path,
            self._chunk_original,
            self.chunk_stage,
        ) in enumerate(self.chunk_stages, start=1):
            self.chunk_read_error = str(
                (self.chunk_stage.metadata or {}).get("existing_source_read_error")
                or ""
            )
            if self.chunk_read_error:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="existing_source_unreadable",
                        errors=[
                            f"Refusing to treat existing file as missing: {self.chunk_path}: {self.chunk_read_error}"
                        ],
                        timings=self.timings,
                        implementation_plan=self.implementation_plan,
                        approval_id=self.approval_id,
                    )
                )
            self.capsule_error = str(
                (self.chunk_stage.metadata or {}).get("capsule_error") or ""
            )
            if self.capsule_error:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="owner_capsule_invalid",
                        errors=[
                            f"{self.chunk_path}: {self.capsule_error} Generation was not invoked."
                        ],
                        timings=self.timings,
                        implementation_plan=self.implementation_plan,
                        approval_id=self.approval_id,
                    )
                )
            if str(self._chunk_original or "").strip():
                if self.status_callback:
                    self.status_callback(
                        f"Preserving existing {_deps.Path(self.chunk_path).name}; initial complete-file generation is forbidden for non-empty files."
                    )
                continue
            self.chunk_metadata = self.chunk_stage.metadata or {}
            self.file_chunk_ids = [
                str(item) for item in self.chunk_metadata.get("chunk_ids") or []
            ]
            self.chunk_owner = str(
                self.chunk_metadata.get("owner")
                or ", ".join(
                    (str(item) for item in self.chunk_metadata.get("owners") or [])
                )
                or "<module>"
            )
            self.chunk_id = str(
                self.chunk_metadata.get("chunk_id")
                or (self.file_chunk_ids[0] if self.file_chunk_ids else self.chunk_owner)
            )
            self.evidence_query = "\n".join(
                [
                    f"Target file: {self.chunk_path}",
                    f"Implementation owner: {self.chunk_owner}",
                    "Requirements: "
                    + ", ".join(self.chunk_metadata.get("requirement_ids") or []),
                ]
            )
            self.chunk_stage = _deps.replace(
                self.chunk_stage,
                user_prompt=self.chunk_stage.user_prompt
                + "\n\nMANDATORY EXECUTABLE EXAMPLE AND TYPING RULES:\n- A runnable example must initialize every injected dependency with concrete,\n  contract-valid values before its first use. Do not use an unconfigured mock as\n  a clock, numeric provider, collection, path, or other value-bearing dependency.\n- Prefer a small deterministic local fake over unittest.mock in production\n  examples unless mocking was explicitly requested.\n- Generic classes must define every type parameter and import every annotation\n  symbol they reference. Use concrete constructible return containers rather than\n  instantiating abstract typing views.\n",
            )
            self.chunk_errors: list[str] = []
            self.chunk_feedback = ""
            self.prior_fingerprints: set[str] = set()
            for self.chunk_attempt in _deps.itertools.count(1):
                self.dependency_ids = set(self.chunk_metadata.get("depends_on") or [])
                from tech_connector.services.project_edit_agent_service import (
                    summarize_project_edit_generated_interface,
                )

                self.summarize_project_edit_generated_interface = (
                    summarize_project_edit_generated_interface
                )
                self.dependency_context = "\n\n".join(
                    (
                        f"Validated dependency {dependency_id} interface:\n"
                        + self.summarize_project_edit_generated_interface(
                            dependency_id, source
                        )
                        for dependency_id, source in self.generated_chunk_sources.items()
                        if dependency_id in self.dependency_ids
                    )
                )
                self.suffix = self.chunk_feedback
                if self.dependency_context:
                    self.suffix += (
                        "\n\nValidated dependency chunks. Use their exact interfaces; do not repeat their implementations:\n"
                        + self.dependency_context
                    )
                self.complete_input_characters = len(
                    self.chunk_stage.system_prompt
                    + self.chunk_stage.user_prompt
                    + self.suffix
                )
                self.complete_input_tokens = max(1, self.complete_input_characters // 3)
                self.complete_num_ctx = max(
                    self.chunk_stage.num_ctx,
                    (self.complete_input_tokens + 3071) // 1024 * 1024,
                )
                self.packed_chunk_stage = _deps.replace(
                    self.chunk_stage, num_ctx=self.complete_num_ctx
                )
                if self.status_callback:
                    if self.chunk_errors:
                        self.status_callback(
                            f"{self.chunk_stage.label} ({self.chunk_index}; attempt {self.chunk_attempt}) fixing only this owner: "
                            + " | ".join(self.chunk_errors[:3])
                        )
                    else:
                        self.status_callback(
                            f"{self.chunk_stage.label} ({self.chunk_index}; attempt {self.chunk_attempt})"
                        )
                self.chunk_response, self.chunk_timing = _deps._query_stage(
                    self.packed_chunk_stage,
                    selected_model=_deps._generation_task_model(
                        self.chunk_stage, self.selected_model, self.chunk_attempt
                    ),
                    settings=self.settings,
                    timeout=self.timeout,
                    suffix=self.suffix,
                )
                if not str(self.chunk_response or "").strip():
                    self.chunk_timing.update(
                        {
                            "attempt": self.chunk_attempt,
                            "path": self.chunk_path,
                            "chunk_id": self.chunk_id,
                            "owner": self.chunk_owner,
                            "requirement_ids": list(
                                self.chunk_metadata.get("requirement_ids") or []
                            ),
                            "failure_fingerprint": "empty_model_response",
                            "capsule_complete_input_characters": self.complete_input_characters,
                            "capsule_estimated_input_tokens": self.complete_input_tokens,
                            "capsule_effective_num_ctx": self.complete_num_ctx,
                            "capsule_context_truncated": False,
                        }
                    )
                    self.timings.append(self.chunk_timing)
                    self.chunk_errors = [
                        "The model transport returned no code for the approved owner."
                    ]
                    self.chunk_feedback = "\n\nTRANSPORT RETRY: Emit raw Python immediately for the same approved owner. Do not explain, re-plan, or return an empty response."
                    if self.status_callback:
                        self.status_callback(
                            f"No code received for {self.chunk_owner}; retaining the approved plan and retrying this exact missing owner with the warmed model. No candidate code was discarded."
                        )
                    continue
                self.chunk_fingerprint = _deps._checkpoint_hash(
                    str(self.chunk_response or "")
                )
                self.repeated_response = (
                    self.chunk_fingerprint in self.prior_fingerprints
                )
                self.prior_fingerprints.add(self.chunk_fingerprint)
                if self.chunk_metadata.get("mode") == "approved_file":
                    self.chunk_source, self.chunk_errors = (
                        _deps.parse_project_edit_generated_file(
                            self.chunk_response,
                            path=self.chunk_path,
                            expected_public_symbols=list(
                                self.chunk_metadata.get("expected_public_symbols") or []
                            ),
                        )
                    )
                    if self.chunk_source and self.chunk_errors:
                        self.expected_symbols = list(
                            self.chunk_metadata.get("expected_public_symbols") or []
                        )
                        for self.missing_symbol in self.expected_symbols:
                            if not any(
                                (
                                    "omitted manifest-declared public symbols" in error
                                    and self.missing_symbol in error
                                    for error in self.chunk_errors
                                )
                            ):
                                continue
                            self.missing_stage = (
                                _deps.build_project_edit_missing_symbol_stage(
                                    path=self.chunk_path,
                                    symbol=self.missing_symbol,
                                    source=self.chunk_source,
                                    objective=self.user_prompt,
                                    contracts=[
                                        _deps.json.dumps(item, ensure_ascii=True)
                                        for item in self.chunk_metadata.get(
                                            "approved_contracts"
                                        )
                                        or []
                                    ],
                                    algorithm_steps=[],
                                )
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Repairing only missing declaration {self.missing_symbol} in {_deps.Path(self.chunk_path).name}."
                                )
                            self.missing_response, self.missing_timing = (
                                _deps._query_stage(
                                    self.missing_stage,
                                    selected_model=_deps._focused_repair_model(
                                        self.selected_model, 2
                                    ),
                                    settings=self.settings,
                                    timeout=self.timeout,
                                )
                            )
                            self.missing_timing.update(
                                {
                                    "attempt": 1,
                                    "path": self.chunk_path,
                                    "symbol": self.missing_symbol,
                                    "stage": "approved_file_missing_symbol_repair",
                                }
                            )
                            self.timings.append(self.missing_timing)
                            self.chunk_source, self.missing_errors = (
                                _deps.apply_project_edit_missing_symbol(
                                    self.chunk_source,
                                    path=self.chunk_path,
                                    symbol=self.missing_symbol,
                                    response=self.missing_response,
                                    objective=self.user_prompt,
                                )
                            )
                            if self.missing_errors:
                                self.chunk_errors = self.missing_errors
                                continue
                            self.chunk_source, self.chunk_errors = (
                                _deps.parse_project_edit_generated_file(
                                    self.chunk_source,
                                    path=self.chunk_path,
                                    expected_public_symbols=self.expected_symbols,
                                )
                            )
                    if self.chunk_source and (not self.chunk_errors):
                        self.declaration_contract = (
                            self.plan_chunk.get("declaration_contract") or {}
                        )
                        if bool(self.declaration_contract.get("public_surface_locked")):
                            try:
                                self.locked_tree = _deps.ast.parse(
                                    self.chunk_source, filename=self.chunk_path
                                )
                            except SyntaxError:
                                self.locked_tree = None
                            if self.locked_tree is not None:
                                self.approved_public_methods = {
                                    str(value)
                                    for value in self.declaration_contract.get(
                                        "required_methods", []
                                    )
                                    if str(value) and (not str(value).startswith("_"))
                                }
                                self.approved_public_methods.update(
                                    (
                                        match.group(1)
                                        for signature in self.declaration_contract.get(
                                            "callable_signatures", []
                                        )
                                        for match in [
                                            _deps.re.match(
                                                "(?:async\\s+)?def\\s+([A-Za-z_][A-Za-z0-9_]*)\\s*\\(",
                                                str(signature).strip(),
                                            )
                                        ]
                                        if match
                                        and (not match.group(1).startswith("_"))
                                    )
                                )
                                self.approved_public_methods.add("__init__")
                                self.removed_public_methods: list[str] = []
                                for self.class_node in (
                                    node
                                    for node in self.locked_tree.body
                                    if isinstance(node, _deps.ast.ClassDef)
                                    and node.name == self.chunk_owner
                                ):
                                    self.retained_body: list[_deps.ast.stmt] = []
                                    for self.statement in self.class_node.body:
                                        if (
                                            isinstance(
                                                self.statement,
                                                (
                                                    _deps.ast.FunctionDef,
                                                    _deps.ast.AsyncFunctionDef,
                                                ),
                                            )
                                            and (
                                                not self.statement.name.startswith("_")
                                            )
                                            and (
                                                self.statement.name
                                                not in self.approved_public_methods
                                            )
                                        ):
                                            self.removed_public_methods.append(
                                                self.statement.name
                                            )
                                            continue
                                        self.retained_body.append(self.statement)
                                    self.class_node.body = self.retained_body
                                if self.removed_public_methods:
                                    _deps.ast.fix_missing_locations(self.locked_tree)
                                    self.chunk_source = (
                                        _deps.ast.unparse(self.locked_tree).rstrip()
                                        + "\n"
                                    )
                                    if self.status_callback:
                                        self.status_callback(
                                            f"Removed dependency/public callable copies forbidden by the locked owner contract for {self.chunk_owner}: "
                                            + ", ".join(
                                                sorted(set(self.removed_public_methods))
                                            )
                                        )
                        self.initial_contract_errors = (
                            self.validate_generated_files_against_implementation_plan(
                                self.implementation_plan,
                                [
                                    (
                                        self.chunk_path,
                                        self._chunk_original,
                                        self.chunk_source,
                                    )
                                ],
                            )
                        )
                        self.structural_markers = (
                            "approved declaration",
                            "approved method",
                            "approved attribute",
                            "approved callable",
                            "approved base",
                            "verified base",
                            "signal",
                            "constructor-reachable",
                            "undeclared public",
                        )
                        self.chunk_errors = [
                            error
                            for error in self.initial_contract_errors
                            if any(
                                (
                                    marker in str(error).casefold()
                                    for marker in self.structural_markers
                                )
                            )
                        ]
                        self.placeholder_names = list(
                            dict.fromkeys(
                                (
                                    name
                                    for error in self.chunk_errors
                                    for group in _deps.re.findall(
                                        "placeholder callable bodies[^:]*:\\s*([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?(?:\\s*,\\s*[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?)*)",
                                        error,
                                        flags=_deps.re.IGNORECASE,
                                    )
                                    for name in (
                                        value.strip() for value in group.split(",")
                                    )
                                    if name
                                )
                            )
                        )
                        self.provisional_files = [
                            (self.chunk_path, self._chunk_original, self.chunk_source)
                        ]
                        try:
                            self.placeholder_tree = _deps.ast.parse(
                                self.chunk_source, filename=self.chunk_path
                            )
                        except SyntaxError:
                            self.placeholder_tree = None
                        self.approved_method_tasks = {
                            str(task.get("name") or "").strip(): dict(task)
                            for contract in self.chunk_metadata.get(
                                "approved_contracts"
                            )
                            or []
                            if isinstance(contract, dict)
                            for task in contract.get("method_tasks") or []
                            if isinstance(task, dict)
                            and str(task.get("name") or "").strip()
                        }
                        for self.placeholder_name in self.placeholder_names:
                            if self.placeholder_tree is None:
                                break
                            if "." in self.placeholder_name:
                                self.target_symbol = self.placeholder_name
                            else:
                                self.owner_class = next(
                                    (
                                        node.name
                                        for node in self.placeholder_tree.body
                                        if isinstance(node, _deps.ast.ClassDef)
                                        and any(
                                            (
                                                isinstance(
                                                    child,
                                                    (
                                                        _deps.ast.FunctionDef,
                                                        _deps.ast.AsyncFunctionDef,
                                                    ),
                                                )
                                                and child.name == self.placeholder_name
                                                for child in node.body
                                            )
                                        )
                                    ),
                                    "",
                                )
                                self.target_symbol = (
                                    f"{self.owner_class}.{self.placeholder_name}"
                                    if self.owner_class
                                    else self.placeholder_name
                                )
                            self.target_method_name = self.target_symbol.rsplit(".", 1)[
                                -1
                            ]
                            self.target_method_task = self.approved_method_tasks.get(
                                self.target_method_name, {}
                            )
                            self.target_validation_errors = list(self.chunk_errors)
                            if self.target_method_task:
                                self.target_validation_errors.append(
                                    "Approved callable signature: "
                                    + str(
                                        self.target_method_task.get("signature") or ""
                                    )
                                )
                                self.target_validation_errors.extend(
                                    (
                                        "Approved callable mechanic: " + str(mechanic)
                                        for mechanic in self.target_method_task.get(
                                            "implementation_mechanics"
                                        )
                                        or []
                                        if str(mechanic).strip()
                                    )
                                )
                            self.target_validation_errors.extend(
                                (
                                    "Approved owner assertion: " + str(assertion)
                                    for assertion in self.chunk_metadata.get(
                                        "machine_assertions"
                                    )
                                    or []
                                    if str(assertion).startswith(
                                        f"{self.chunk_owner}.{self.target_method_name}:"
                                    )
                                    or (
                                        str(assertion).startswith(
                                            f"{self.chunk_owner}:"
                                        )
                                        and "import and consume validated dependency"
                                        in str(assertion)
                                    )
                                )
                            )
                            self.repair_contract, self.contract_errors = (
                                _deps.build_project_edit_function_repair_contract(
                                    self.provisional_files,
                                    target={
                                        "path": self.chunk_path,
                                        "symbol": self.target_symbol,
                                    },
                                    validation_errors=self.target_validation_errors,
                                    objective=self.user_prompt,
                                )
                            )
                            if self.contract_errors:
                                self.chunk_errors = self.contract_errors
                                continue
                            self.repair_stage = (
                                _deps.build_project_edit_function_repair_stage(
                                    self.repair_contract, attempt=2
                                )
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Repairing only placeholder callable {self.target_symbol} in {_deps.Path(self.chunk_path).name}."
                                )
                            self.replacement, self.repair_timing = _deps._query_stage(
                                self.repair_stage,
                                selected_model=_deps._focused_repair_model(
                                    self.selected_model, 2
                                ),
                                settings=self.settings,
                                timeout=self.timeout,
                            )
                            self.repair_timing.update(
                                {
                                    "attempt": 1,
                                    "path": self.chunk_path,
                                    "symbol": self.target_symbol,
                                    "stage": "approved_file_callable_repair",
                                }
                            )
                            self.timings.append(self.repair_timing)
                            self.provisional_files, self.repair_errors = (
                                _deps.apply_project_edit_generated_symbol_repair(
                                    self.provisional_files,
                                    path=self.chunk_path,
                                    symbol=self.target_symbol,
                                    replacement_response=self.replacement,
                                    forbidden_names=list(
                                        self.repair_contract.get("forbidden_names")
                                        or []
                                    ),
                                )
                            )
                            if self.repair_errors:
                                if self.status_callback:
                                    self.status_callback(
                                        f"Rejected callable repair {self.target_symbol}: "
                                        + " | ".join(self.repair_errors[:4])
                                    )
                                self.chunk_errors = self.repair_errors
                                continue
                            self.chunk_source = self.provisional_files[-1][2]
                            self.placeholder_tree = _deps.ast.parse(
                                self.chunk_source, filename=self.chunk_path
                            )
                            self.chunk_source, self.chunk_errors = (
                                _deps.parse_project_edit_generated_file(
                                    self.chunk_source,
                                    path=self.chunk_path,
                                    expected_public_symbols=self.expected_symbols,
                                )
                            )
                else:
                    self.direct_declaration_contract = (
                        self.chunk_metadata.get("declaration_contract") or {}
                    )
                    self.helper_contract_sources = [
                        (
                            self.direct_declaration_contract
                            if isinstance(self.direct_declaration_contract, dict)
                            else {}
                        ),
                        *[
                            approved_contract.get("declaration_contract") or {}
                            for approved_contract in self.chunk_metadata.get(
                                "approved_contracts"
                            )
                            or []
                            if isinstance(approved_contract, dict)
                        ],
                    ]
                    self.approved_helper_contracts = [
                        dict(helper)
                        for declaration_contract in self.helper_contract_sources
                        if isinstance(declaration_contract, dict)
                        for helper in declaration_contract.get("helper_declarations")
                        or []
                        if isinstance(helper, dict)
                        and str(helper.get("owner") or "").strip()
                    ]
                    self.approved_helper_names = list(
                        dict.fromkeys(
                            (
                                str(helper.get("owner") or "").strip()
                                for helper in self.approved_helper_contracts
                            )
                        )
                    )
                    self.declaration_contract = (
                        self.chunk_metadata.get("declaration_contract") or {}
                    )
                    self.required_method_names = list(
                        dict.fromkeys(
                            [
                                *[
                                    str(value)
                                    .split("(", 1)[0]
                                    .removeprefix("def ")
                                    .rsplit(".", 1)[-1]
                                    .strip()
                                    for value in self.declaration_contract.get(
                                        "callable_signatures"
                                    )
                                    or []
                                    if str(value).strip()
                                ],
                                *[
                                    match.group("method")
                                    for assertion in self.chunk_metadata.get(
                                        "machine_assertions"
                                    )
                                    or []
                                    for match in [
                                        _deps.re.match(
                                            f"^{_deps.re.escape(self.chunk_owner)}\\.(?P<method>[A-Za-z_][A-Za-z0-9_]*):",
                                            str(assertion),
                                        )
                                    ]
                                    if match
                                ],
                                *[
                                    str(value).strip()
                                    for value in self.chunk_metadata.get(
                                        "required_methods"
                                    )
                                    or []
                                    if str(value).strip()
                                ],
                            ]
                        )
                    )
                    if self.status_callback and self.approved_helper_names:
                        self.status_callback(
                            "Approved same-file helper declarations: "
                            + ", ".join(self.approved_helper_names)
                        )
                    self.chunk_source, self.chunk_errors = (
                        _deps.parse_project_edit_generated_chunk(
                            self.chunk_response,
                            owner=self.chunk_owner,
                            kind=str(self.chunk_metadata.get("kind") or "symbol"),
                            allowed_declarations=self.approved_helper_names,
                            required_methods=self.required_method_names,
                        )
                    )
                    if self.chunk_source and self.chunk_owner == "<module>":
                        self.forbidden_module_owners = {
                            str(value)
                            for value in self.chunk_metadata.get("all_file_owners")
                            or []
                            if str(value)
                        }
                        self.module_tree = _deps.ast.parse(
                            self.chunk_source, filename=self.chunk_path
                        )
                        self.source_lines = self.chunk_source.splitlines()
                        self.retained_nodes = [
                            node
                            for node in self.module_tree.body
                            if not (
                                isinstance(
                                    node,
                                    (
                                        _deps.ast.ClassDef,
                                        _deps.ast.FunctionDef,
                                        _deps.ast.AsyncFunctionDef,
                                    ),
                                )
                                and (
                                    node.name in self.forbidden_module_owners
                                    or not node.name.startswith("_")
                                )
                            )
                        ]
                        if len(self.retained_nodes) != len(self.module_tree.body):
                            self.chunk_source = (
                                "\n\n".join(
                                    (
                                        "\n".join(
                                            self.source_lines[
                                                node.lineno - 1 : node.end_lineno
                                            ]
                                        ).strip()
                                        for node in self.retained_nodes
                                    )
                                ).rstrip()
                                + "\n"
                            )
                            self.chunk_source, self.chunk_errors = (
                                _deps.parse_project_edit_generated_chunk(
                                    self.chunk_source,
                                    owner=self.chunk_owner,
                                    kind=str(
                                        self.chunk_metadata.get("kind") or "symbol"
                                    ),
                                    allowed_declarations=self.approved_helper_names,
                                    required_methods=self.required_method_names,
                                )
                            )
                    if self.chunk_source and self.chunk_owner != "<module>":
                        self.dependency_chunks = {
                            str(item.get("chunk_id") or ""): item
                            for item in self.implementation_plan.get("chunks") or []
                            if isinstance(item, dict)
                        }
                        try:
                            self.dependency_tree = _deps.ast.parse(
                                self.chunk_source, filename=self.chunk_path
                            )
                        except SyntaxError:
                            self.dependency_tree = None
                        self.inserted_dependency_imports: list[str] = []
                        if self.dependency_tree is not None:
                            self.imported_names = {
                                alias.asname or alias.name.rsplit(".", 1)[-1]
                                for node in self.dependency_tree.body
                                if isinstance(
                                    node, (_deps.ast.Import, _deps.ast.ImportFrom)
                                )
                                for alias in node.names
                            }
                            for self.dependency_id in (
                                self.chunk_metadata.get("depends_on") or []
                            ):
                                self.dependency_chunk = self.dependency_chunks.get(
                                    str(self.dependency_id), {}
                                )
                                self.dependency_owner = (
                                    str(self.dependency_chunk.get("owner") or "")
                                    .split("(", 1)[0]
                                    .rsplit(".", 1)[-1]
                                )
                                self.dependency_path = str(
                                    self.dependency_chunk.get("path") or ""
                                )
                                if (
                                    not self.dependency_owner
                                    or self.dependency_owner == "<module>"
                                    or (not self.dependency_path)
                                    or (self.dependency_owner in self.imported_names)
                                ):
                                    continue
                                try:
                                    self.relative_module = (
                                        _deps.Path(self.dependency_path)
                                        .resolve()
                                        .relative_to(_deps.Path(self.root).resolve())
                                        .with_suffix("")
                                    )
                                except ValueError:
                                    continue
                                self.module_name = ".".join(self.relative_module.parts)
                                self.dependency_tree.body.insert(
                                    0,
                                    _deps.ast.ImportFrom(
                                        module=self.module_name,
                                        names=[
                                            _deps.ast.alias(name=self.dependency_owner)
                                        ],
                                        level=0,
                                    ),
                                )
                                self.imported_names.add(self.dependency_owner)
                                self.inserted_dependency_imports.append(
                                    f"{self.module_name}.{self.dependency_owner}"
                                )
                        if (
                            self.inserted_dependency_imports
                            and self.dependency_tree is not None
                        ):
                            _deps.ast.fix_missing_locations(self.dependency_tree)
                            self.chunk_source = (
                                _deps.ast.unparse(self.dependency_tree).rstrip() + "\n"
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Materialized approved dependencies before repairing {self.chunk_owner}: "
                                    + ", ".join(self.inserted_dependency_imports)
                                )
                    if self.chunk_source and self.chunk_errors:
                        self.missing_method_names = list(
                            dict.fromkeys(
                                (
                                    name.strip()
                                    for error in self.chunk_errors
                                    for group in _deps.re.findall(
                                        "Missing approved methods:\\s*([A-Za-z_][A-Za-z0-9_]*(?:\\s*,\\s*[A-Za-z_][A-Za-z0-9_]*)*)",
                                        error,
                                    )
                                    for name in group.split(",")
                                    if name.strip()
                                )
                            )
                        )
                        if self.missing_method_names and self.chunk_owner != "<module>":
                            try:
                                self.missing_tree = _deps.ast.parse(
                                    self.chunk_source, filename=self.chunk_path
                                )
                            except SyntaxError:
                                self.missing_tree = None
                            self.owner_name = self.chunk_owner.split("(", 1)[0].rsplit(
                                ".", 1
                            )[-1]
                            self.owner_node = next(
                                (
                                    node
                                    for node in (
                                        self.missing_tree.body
                                        if self.missing_tree
                                        else []
                                    )
                                    if isinstance(node, _deps.ast.ClassDef)
                                    and node.name == self.owner_name
                                ),
                                None,
                            )
                            self.signature_by_name = {
                                str(signature)
                                .split("(", 1)[0]
                                .removeprefix("def ")
                                .rsplit(".", 1)[-1]
                                .strip(): str(signature)
                                .strip()
                                for signature in self.declaration_contract.get(
                                    "callable_signatures"
                                )
                                or []
                                if str(signature).strip()
                            }
                            self.inserted_methods: list[str] = []
                            if self.owner_node is not None:
                                for self.method_name in self.missing_method_names:
                                    self.raw_signature = self.signature_by_name.get(
                                        self.method_name,
                                        f"def {self.method_name}(self) -> None",
                                    )
                                    if not self.raw_signature.startswith("def "):
                                        self.raw_signature = "def " + self.raw_signature
                                    try:
                                        self.method_node = _deps.ast.parse(
                                            self.raw_signature.rstrip(":")
                                            + ":\n    pass\n",
                                            filename=f"<missing-method:{self.owner_name}.{self.method_name}>",
                                        ).body[0]
                                    except SyntaxError:
                                        continue
                                    self.owner_node.body.append(self.method_node)
                                    self.inserted_methods.append(self.method_name)
                            if self.inserted_methods and self.missing_tree is not None:
                                _deps.ast.fix_missing_locations(self.missing_tree)
                                self.chunk_source = (
                                    _deps.ast.unparse(self.missing_tree).rstrip() + "\n"
                                )
                                self.chunk_errors = [
                                    error
                                    for error in self.chunk_errors
                                    if "Missing approved methods:" not in error
                                ]
                                self.chunk_errors.append(
                                    f"[owner:{self.chunk_owner}] Placeholder callable bodies: "
                                    + ", ".join(
                                        (
                                            f"{self.owner_name}.{method_name}"
                                            for method_name in self.inserted_methods
                                        )
                                    )
                                )
                        self.placeholder_names = list(
                            dict.fromkeys(
                                (
                                    name
                                    for error in self.chunk_errors
                                    for group in _deps.re.findall(
                                        "placeholder callable bodies[^:]*:\\s*([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?(?:\\s*,\\s*[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?)*)",
                                        error,
                                        flags=_deps.re.IGNORECASE,
                                    )
                                    for name in (
                                        value.strip() for value in group.split(",")
                                    )
                                    if name
                                )
                            )
                        )
                        self.provisional_files = [
                            (self.chunk_path, self._chunk_original, self.chunk_source)
                        ]
                        try:
                            self.placeholder_tree = _deps.ast.parse(
                                self.chunk_source, filename=self.chunk_path
                            )
                        except SyntaxError:
                            self.placeholder_tree = None
                        self.approved_method_tasks = {
                            str(task.get("name") or "").strip(): dict(task)
                            for contract in self.chunk_metadata.get(
                                "approved_contracts"
                            )
                            or []
                            if isinstance(contract, dict)
                            for task in contract.get("method_tasks") or []
                            if isinstance(task, dict)
                            and str(task.get("name") or "").strip()
                        }
                        for self.placeholder_name in self.placeholder_names:
                            if self.placeholder_tree is None:
                                break
                            if "." in self.placeholder_name:
                                self.target_symbol = self.placeholder_name
                            else:
                                self.owner_class = next(
                                    (
                                        node.name
                                        for node in self.placeholder_tree.body
                                        if isinstance(node, _deps.ast.ClassDef)
                                        and any(
                                            (
                                                isinstance(
                                                    child,
                                                    (
                                                        _deps.ast.FunctionDef,
                                                        _deps.ast.AsyncFunctionDef,
                                                    ),
                                                )
                                                and child.name == self.placeholder_name
                                                for child in node.body
                                            )
                                        )
                                    ),
                                    "",
                                )
                                self.target_symbol = (
                                    f"{self.owner_class}.{self.placeholder_name}"
                                    if self.owner_class
                                    else self.placeholder_name
                                )
                            self.target_method_name = self.target_symbol.rsplit(".", 1)[
                                -1
                            ]
                            self.target_method_task = self.approved_method_tasks.get(
                                self.target_method_name, {}
                            )
                            self.target_validation_errors = list(self.chunk_errors)
                            self.target_validation_errors.append(
                                "Do not call an undeclared private helper. Perform the approved state transition directly unless the helper is explicitly approved in this owner capsule."
                            )
                            if self.target_method_task:
                                self.target_validation_errors.append(
                                    "Approved callable signature: "
                                    + str(
                                        self.target_method_task.get("signature") or ""
                                    )
                                )
                                self.target_validation_errors.extend(
                                    (
                                        "Approved callable mechanic: " + str(mechanic)
                                        for mechanic in self.target_method_task.get(
                                            "implementation_mechanics"
                                        )
                                        or []
                                        if str(mechanic).strip()
                                    )
                                )
                            self.target_validation_errors.extend(
                                (
                                    "Approved owner assertion: " + str(assertion)
                                    for assertion in self.chunk_metadata.get(
                                        "machine_assertions"
                                    )
                                    or []
                                    if str(assertion).startswith(
                                        f"{self.chunk_owner}.{self.target_method_name}:"
                                    )
                                    or (
                                        str(assertion).startswith(
                                            f"{self.chunk_owner}:"
                                        )
                                        and "import and consume validated dependency"
                                        in str(assertion)
                                    )
                                )
                            )
                            self.dependency_chunks = {
                                str(item.get("chunk_id") or ""): item
                                for item in self.implementation_plan.get("chunks") or []
                                if isinstance(item, dict)
                            }
                            for self.dependency_id in (
                                self.chunk_metadata.get("depends_on") or []
                            ):
                                self.dependency_chunk = self.dependency_chunks.get(
                                    str(self.dependency_id), {}
                                )
                                if not self.dependency_chunk:
                                    continue
                                self.target_validation_errors.append(
                                    "Approved dependency owner contract: "
                                    + _deps.json.dumps(
                                        {
                                            "owner": self.dependency_chunk.get("owner"),
                                            "declaration_contract": self.dependency_chunk.get(
                                                "declaration_contract"
                                            )
                                            or {},
                                            "method_tasks": self.dependency_chunk.get(
                                                "method_tasks"
                                            )
                                            or [],
                                            "observable_contracts": self.dependency_chunk.get(
                                                "observable_contracts"
                                            )
                                            or [],
                                            "selected_evidence": [
                                                {
                                                    "name": evidence.get("name"),
                                                    "signature": evidence.get(
                                                        "signature"
                                                    ),
                                                    "return_schema": evidence.get(
                                                        "return_schema"
                                                    ),
                                                }
                                                for evidence in self.dependency_chunk.get(
                                                    "evidence"
                                                )
                                                or []
                                                if isinstance(evidence, dict)
                                                and evidence.get(
                                                    "selected_for_generation"
                                                )
                                            ],
                                        },
                                        ensure_ascii=True,
                                        separators=(",", ":"),
                                    )
                                )
                            self.repair_contract, self.contract_errors = (
                                _deps.build_project_edit_function_repair_contract(
                                    self.provisional_files,
                                    target={
                                        "path": self.chunk_path,
                                        "symbol": self.target_symbol,
                                    },
                                    validation_errors=self.target_validation_errors,
                                    objective=self.user_prompt,
                                )
                            )
                            if self.contract_errors:
                                self.chunk_errors = self.contract_errors
                                continue
                            self.repair_stage = (
                                _deps.build_project_edit_function_repair_stage(
                                    self.repair_contract, attempt=2
                                )
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Repairing only placeholder callable {self.target_symbol} in {_deps.Path(self.chunk_path).name}."
                                )
                            self.replacement, self.repair_timing = _deps._query_stage(
                                self.repair_stage,
                                selected_model=_deps._focused_repair_model(
                                    self.selected_model, 2
                                ),
                                settings=self.settings,
                                timeout=self.timeout,
                            )
                            self.repair_timing.update(
                                {
                                    "attempt": 1,
                                    "path": self.chunk_path,
                                    "symbol": self.target_symbol,
                                    "stage": "approved_owner_callable_repair",
                                }
                            )
                            self.timings.append(self.repair_timing)
                            self.provisional_files, self.repair_errors = (
                                _deps.apply_project_edit_generated_symbol_repair(
                                    self.provisional_files,
                                    path=self.chunk_path,
                                    symbol=self.target_symbol,
                                    replacement_response=self.replacement,
                                    forbidden_names=list(
                                        self.repair_contract.get("forbidden_names")
                                        or []
                                    ),
                                )
                            )
                            if self.repair_errors:
                                if self.status_callback:
                                    self.status_callback(
                                        f"Rejected callable repair {self.target_symbol}: "
                                        + " | ".join(self.repair_errors[:4])
                                    )
                                self.chunk_errors = self.repair_errors
                                continue
                            self.chunk_source = self.provisional_files[-1][2]
                            self.placeholder_tree = _deps.ast.parse(
                                self.chunk_source, filename=self.chunk_path
                            )
                            self.chunk_source, self.chunk_errors = (
                                _deps.parse_project_edit_generated_chunk(
                                    self.chunk_source,
                                    owner=self.chunk_owner,
                                    kind=str(
                                        self.chunk_metadata.get("kind") or "symbol"
                                    ),
                                    allowed_declarations=self.approved_helper_names,
                                    required_methods=self.required_method_names,
                                )
                            )
                    if (
                        self.chunk_source
                        and self.chunk_owner != "<module>"
                        and self.approved_helper_contracts
                    ):
                        try:
                            self.helper_tree = _deps.ast.parse(
                                self.chunk_source, filename=self.chunk_path
                            )
                        except SyntaxError:
                            self.helper_tree = None
                        self.existing_helper_names = {
                            node.name
                            for node in (
                                self.helper_tree.body if self.helper_tree else []
                            )
                            if isinstance(
                                node,
                                (
                                    _deps.ast.ClassDef,
                                    _deps.ast.FunctionDef,
                                    _deps.ast.AsyncFunctionDef,
                                ),
                            )
                        }
                        for self.helper_contract in self.approved_helper_contracts:
                            self.helper_name = str(
                                self.helper_contract.get("owner") or ""
                            ).strip()
                            if (
                                not self.helper_name
                                or self.helper_name in self.existing_helper_names
                            ):
                                continue
                            self.helper_stage = (
                                _deps.build_project_edit_missing_symbol_stage(
                                    path=self.chunk_path,
                                    symbol=self.helper_name,
                                    source=self.chunk_source,
                                    objective=self.user_prompt,
                                    contracts=[
                                        _deps.json.dumps(
                                            self.helper_contract, ensure_ascii=True
                                        )
                                    ],
                                    algorithm_steps=[
                                        str(
                                            self.helper_contract.get("responsibility")
                                            or ""
                                        )
                                    ],
                                )
                            )
                            if self.status_callback:
                                self.status_callback(
                                    f"Repairing only missing approved helper {self.helper_name} in {_deps.Path(self.chunk_path).name}."
                                )
                            self.helper_response, self.helper_timing = (
                                _deps._query_stage(
                                    self.helper_stage,
                                    selected_model=_deps._focused_repair_model(
                                        self.selected_model, 2
                                    ),
                                    settings=self.settings,
                                    timeout=self.timeout,
                                )
                            )
                            self.helper_timing.update(
                                {
                                    "attempt": 1,
                                    "path": self.chunk_path,
                                    "symbol": self.helper_name,
                                    "stage": "approved_helper_missing_symbol_repair",
                                }
                            )
                            self.timings.append(self.helper_timing)
                            self.chunk_source, self.helper_errors = (
                                _deps.apply_project_edit_missing_symbol(
                                    self.chunk_source,
                                    path=self.chunk_path,
                                    symbol=self.helper_name,
                                    response=self.helper_response,
                                    objective=self.user_prompt,
                                )
                            )
                            if self.helper_errors:
                                self.chunk_errors = self.helper_errors
                                continue
                            self.existing_helper_names.add(self.helper_name)
                        self.chunk_source, self.chunk_errors = (
                            _deps.parse_project_edit_generated_chunk(
                                self.chunk_source,
                                owner=self.chunk_owner,
                                kind=str(self.chunk_metadata.get("kind") or "symbol"),
                                allowed_declarations=self.approved_helper_names,
                                required_methods=self.required_method_names,
                            )
                        )
                self.failure_fingerprint = _deps._checkpoint_hash(self.chunk_errors)
                self.chunk_timing.update(
                    {
                        "attempt": self.chunk_attempt,
                        "path": self.chunk_path,
                        "chunk_id": self.chunk_id,
                        "owner": self.chunk_owner,
                        "requirement_ids": list(
                            self.chunk_metadata.get("requirement_ids") or []
                        ),
                        "failure_fingerprint": self.failure_fingerprint,
                        "capsule_complete_input_characters": self.complete_input_characters,
                        "capsule_estimated_input_tokens": self.complete_input_tokens,
                        "capsule_effective_num_ctx": self.complete_num_ctx,
                        "capsule_context_truncated": False,
                    }
                )
                self.timings.append(self.chunk_timing)
                if self.chunk_source and (not self.chunk_errors):
                    self.validated_chunks.append(
                        (
                            self.chunk_path,
                            (
                                "<module>"
                                if self.chunk_metadata.get("mode") == "approved_file"
                                else self.chunk_owner
                            ),
                            self.chunk_source,
                        )
                    )
                    self.completed_chunk_ids = self.file_chunk_ids or [self.chunk_id]
                    for self.completed_chunk_id in self.completed_chunk_ids:
                        self.generated_chunk_sources[self.completed_chunk_id] = (
                            self.chunk_source
                        )
                    for self.coverage_row in self.chunk_coverage:
                        if self.coverage_row["chunk_id"] in self.completed_chunk_ids:
                            self.coverage_row["implemented"] = True
                            self.coverage_row["validated"] = True
                    break
                if (
                    self.chunk_source
                    and self.chunk_errors
                    and (self.chunk_metadata.get("mode") != "approved_file")
                ):
                    try:
                        compile(
                            _deps.ast.parse(
                                self.chunk_source, filename=self.chunk_path
                            ),
                            self.chunk_path,
                            "exec",
                        )
                    except (SyntaxError, ValueError):
                        pass
                    else:
                        self.validated_chunks.append(
                            (self.chunk_path, self.chunk_owner, self.chunk_source)
                        )
                        self.completed_chunk_ids = self.file_chunk_ids or [
                            self.chunk_id
                        ]
                        for self.completed_chunk_id in self.completed_chunk_ids:
                            self.generated_chunk_sources[self.completed_chunk_id] = (
                                self.chunk_source
                            )
                        for self.coverage_row in self.chunk_coverage:
                            if (
                                self.coverage_row["chunk_id"]
                                in self.completed_chunk_ids
                            ):
                                self.coverage_row["implemented"] = True
                        if self.status_callback:
                            self.status_callback(
                                f"Preserving syntactically valid owner {self.chunk_owner}; remaining failures will use symbol/class repair without regenerating it."
                            )
                        break
                if self.status_callback:
                    self.status_callback(
                        f"Rejected {self.chunk_stage.label} [owner={self.chunk_owner}; failure={self.failure_fingerprint[:12]}]: "
                        + " | ".join(self.chunk_errors[:4])
                    )
                    if self.repeated_response:
                        self.status_callback(
                            "Repeated chunk response detected; escalating model/evidence strategy without expanding the repair boundary."
                        )
                self.chunk_feedback = (
                    "\n\nRepair only this implementation owner. The prior chunk was rejected for these deterministic failures:\n- "
                    + "\n- ".join(self.chunk_errors[:8])
                    + "\nReturn a changed, complete raw-Python chunk for this owner only."
                )
                if self.chunk_metadata.get("mode") == "approved_file":
                    if self.chunk_source:
                        self.resolved_chunk_path = str(
                            _deps.Path(self.chunk_path).resolve()
                        )
                        self.rejected_file_candidates[self.resolved_chunk_path] = (
                            self.chunk_source
                        )
                        self.rejected_file_errors[self.resolved_chunk_path] = list(
                            self.chunk_errors
                        )
                    self.chunk_pipeline_failed = True
                    if self.status_callback:
                        self.status_callback(
                            f"Retained the rejected candidate for {_deps.Path(self.chunk_path).name}; complete-file regeneration is forbidden and recovery will target only its proven owner or syntax region."
                        )
                    break
                if self.repeated_response or self.chunk_attempt >= 3:
                    self.chunk_pipeline_failed = True
                    if self.status_callback:
                        self.status_callback(
                            f"Chunk strategy exhausted for {self.chunk_owner}; preserving the candidate and changing to a bounded owner strategy."
                        )
                    break
            if self.chunk_pipeline_failed:
                break
        if self.chunk_pipeline_failed:
            self.reusable_validated_chunks = list(self.validated_chunks)
            if self.reusable_validated_chunks:
                self.chunk_assembled_files, self.chunk_assembly_errors = (
                    _deps.assemble_project_edit_generated_chunks(
                        self.reusable_validated_chunks
                    )
                )
                if self.status_callback and (not self.chunk_assembly_errors):
                    self.status_callback(
                        "Preserving already-valid generated files; only the rejected file will enter bounded recovery."
                    )
            else:
                self.chunk_assembled_files = []
                self.chunk_assembly_errors = [
                    "One or more owner chunks exhausted their distinct repair strategies."
                ]
        else:
            self.chunk_assembled_files, self.chunk_assembly_errors = (
                _deps.assemble_project_edit_generated_chunks(self.validated_chunks)
            )
        if self.chunk_assembly_errors:
            if self.status_callback:
                self.status_callback(
                    "Chunk assembly was not eligible for validation; continuing with retained candidates and bounded owner/region repair only: "
                    + " | ".join(self.chunk_assembly_errors[:4])
                )
        else:
            self.chunk_generated_by_path = {
                str(_deps.Path(path).resolve()): source
                for path, _original, source in self.chunk_assembled_files
            }
            self.assembled_paths = set(self.chunk_generated_by_path)
            for self.coverage_row in self.chunk_coverage:
                self.declaration = next(
                    (
                        item
                        for item in (self.chunk_plan_stage.metadata or {}).get(
                            "declarations", []
                        )
                        if str(item.get("declaration_id") or "")
                        == self.coverage_row["chunk_id"]
                    ),
                    None,
                )
                if (
                    self.declaration
                    and str(
                        _deps.Path(str(self.declaration.get("path") or "")).resolve()
                    )
                    in self.assembled_paths
                ):
                    self.coverage_row["assembled"] = True
            if self.status_callback:
                self.status_callback(
                    f"Assembled {len(self.validated_chunks)} validated implementation chunk(s) into {len(self.chunk_generated_by_path)} file(s)."
                )
        self.qualified_reference_symbols = _deps._qualified_reference_member_symbols(
            self.workflow_prompt
        )
        self.symbol_owners: dict[str, str] = {}
        for (
            self.owned_path,
            self._owned_source,
            self.owned_stage,
        ) in self.artifact_file_stages:
            if _deps.Path(self.owned_path).name.startswith("test_"):
                continue
            for self.raw_symbol in (self.owned_stage.metadata or {}).get(
                "expected_public_symbols"
            ) or []:
                self.symbol = _deps._manifest_symbol_name(self.raw_symbol)
                self.inferred_prose_acronym = bool(
                    self.symbol and _deps.re.fullmatch("[A-Z]{2,}[a-z]?", self.symbol)
                )
                if (
                    self.symbol
                    and (not self.symbol.startswith("__"))
                    and (not self.inferred_prose_acronym)
                    and (self.symbol not in self.qualified_reference_symbols)
                ):
                    self.symbol_owners.setdefault(self.symbol, self.owned_path)
        self.symbol_owners = {
            symbol: owner
            for symbol, owner in self.symbol_owners.items()
            if symbol not in self.qualified_reference_symbols
        }
        if self.status_callback and self.symbol_owners:
            self.status_callback(
                "Resolved symbol ownership: "
                + ", ".join(
                    (
                        f"{symbol}->{_deps.Path(owner).name}"
                        for symbol, owner in sorted(self.symbol_owners.items())
                    )
                )
            )
        self.generated_files: list[tuple[str, str, str]] = []
        self.restored_files = self.early_restored_files
        self.restored_workflow_state = self.early_restored_workflow_state
        self.restored_by_path = {
            str(_deps.Path(path).resolve()): source
            for path, _original, source in self.restored_files
        }
        self.restored_by_path.update(self.chunk_generated_by_path)
        if self.restored_by_path and self.status_callback:
            self.status_callback(
                f"Using {len(self.restored_by_path)} generated candidate file(s); completion remains blocked until current validation passes."
            )
        self.file_records: dict[
            str, tuple[str, _deps.ProjectEditPromptStage, list[str]]
        ] = {}
        for self.file_index, (self.path, self.original_source, self.stage) in enumerate(
            self.artifact_file_stages, start=1
        ):
            self.source_read_error = str(
                (self.stage.metadata or {}).get("existing_source_read_error") or ""
            )
            if self.source_read_error:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="existing_source_unreadable",
                        errors=[
                            f"Refusing to treat existing file as missing: {self.path}: {self.source_read_error}"
                        ],
                        timings=self.timings,
                        implementation_plan=self.implementation_plan,
                        approval_id=self.approval_id,
                    )
                )
            if _deps.Path(self.path).name.startswith("test_"):
                self.stage = _deps.replace(
                    self.stage,
                    user_prompt=self.stage.user_prompt
                    + "\n\nMANDATORY BEHAVIORAL TEST FIXTURE RULES:\n- Create one substantive test for every behavior the objective explicitly says\n  to prove; do not silently omit rejection, boundary, callback, or round-trip cases.\n- Success fixtures must satisfy every production invariant. Compute real hashes,\n  digests, signatures, lengths, ranges, identifiers, and related validated values\n  from the fixture data instead of using empty strings or placeholders.\n- Invalid fixtures belong only in explicit negative tests using assertRaises or an\n  equivalent observable failure assertion. Never weaken production validation to\n  make an invalid success fixture pass.\n- Use temporary directories/files and deterministic mocks for external state.\n  Tests must not read, overwrite, or leave artifacts in the process working directory.\n- Host SDKs may be unavailable during tests. Patch or inject the exact production\n  module host binding and use configured sentinel members for expected arguments;\n  do not import or reference `unreal`, `maya`, `bpy`, or `pyfbsdk` directly from\n  the test body.\n",
                )
            else:
                self.stage = _deps.replace(
                    self.stage,
                    user_prompt=self.stage.user_prompt
                    + "\n\nMUTABILITY SCOPE RULE:\n- Apply frozen/immutable record semantics only to classes the objective explicitly\n  identifies as immutable. Stateful services, managers, writers, queues, registries,\n  dialogs, and adapters must remain mutable unless explicitly requested otherwise.\n\nEXECUTABLE EXAMPLE AND TYPING RULES:\n- Runnable examples must initialize injected dependencies with concrete,\n  contract-valid values before first use; prefer deterministic local fakes over\n  unconfigured mocks.\n- Generic classes must define every type parameter and import every annotation\n  symbol they reference. Return concrete constructible containers rather than\n  instantiating abstract typing views.\n",
                )
            self.resolved_path = str(_deps.Path(self.path).resolve())
            self.parse_errors: list[str] = list(
                self.rejected_file_errors.get(self.resolved_path) or []
            )
            self.rejected_source = str(
                self.rejected_file_candidates.get(self.resolved_path) or ""
            )
            self.output_source = ""
            self.expected_symbols = [
                _deps._manifest_symbol_name(symbol)
                for symbol in (self.stage.metadata or {}).get("expected_public_symbols")
                or []
            ]
            self.expected_symbols = [
                symbol for symbol in self.expected_symbols if symbol
            ]
            self.expected_symbols = [
                symbol
                for symbol in self.expected_symbols
                if not str(symbol).rsplit(".", 1)[-1].startswith("__")
                and str(symbol).split("(", 1)[0].rsplit(".", 1)[-1]
                not in self.qualified_reference_symbols
                and (
                    not _deps.re.fullmatch(
                        "[A-Z]{2,}[a-z]?",
                        str(symbol).split("(", 1)[0].rsplit(".", 1)[-1],
                    )
                )
                and (
                    self.symbol_owners.get(
                        str(symbol).split("(", 1)[0].rsplit(".", 1)[-1], self.path
                    )
                    == self.path
                )
            ]
            self.expected_symbols.extend(
                (
                    symbol
                    for symbol, owner in self.symbol_owners.items()
                    if owner == self.path and symbol not in self.expected_symbols
                )
            )
            if _deps.Path(self.path).name.startswith("test_"):
                self.expected_symbols = [
                    symbol
                    for symbol in self.expected_symbols
                    if str(symbol).startswith(("Test", "test_"))
                ]
            if str(self.original_source or "").strip():
                self.file_records[self.path] = (
                    self.original_source,
                    self.stage,
                    self.expected_symbols,
                )
                self.generated_files.append(
                    (self.path, self.original_source, self.original_source)
                )
                if self.status_callback:
                    self.status_callback(
                        f"Loaded existing {_deps.Path(self.path).name} unchanged; only exact symbol, class, callable, import, or syntax-region patches may modify it."
                    )
                continue
            self.restored_source = self.restored_by_path.get(
                str(_deps.Path(self.path).resolve())
            )
            if self.restored_source:
                self.file_records[self.path] = (
                    self.original_source,
                    self.stage,
                    self.expected_symbols,
                )
                self.generated_files.append(
                    (self.path, self.original_source, self.restored_source)
                )
                if self.status_callback:
                    if (
                        str(_deps.Path(self.path).resolve())
                        in self.chunk_generated_by_path
                    ):
                        self.status_callback(
                            f"Using assembled owner chunks for {_deps.Path(self.path).name}; full-file generation skipped."
                        )
                    else:
                        self.status_callback(
                            f"Reusing checkpointed {_deps.Path(self.path).name}; generation skipped."
                        )
                continue
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="owner_generation_incomplete",
                    errors=[
                        f"{self.path}: approved owner capsules did not assemble a candidate file. Full-file generation is forbidden after plan approval; resume the exact missing or rejected owner instead."
                    ],
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id=self.approval_id,
                )
            )
            self.stage = _deps.replace(
                self.stage,
                user_prompt=self.stage.user_prompt
                + _deps._federated_symbol_evidence_context(
                    "\n".join(
                        [
                            self.workflow_prompt,
                            f"Target file: {self.path}",
                            "Expected public symbols: "
                            + ", ".join(self.expected_symbols),
                        ]
                    ),
                    project_root=self.root,
                    generated_files=self.generated_files,
                ),
            )
            self.file_records[self.path] = (
                self.original_source,
                self.stage,
                self.expected_symbols,
            )
            self.seen_raw_response_hashes: set[str] = set()
            self.seen_candidate_hashes: set[str] = set()
            self.seen_failure_fingerprints: set[tuple[str, str]] = set()
            self.syntax_region_attempt = 0
            for self.attempt in range(1, 5):
                self.suffix = ""
                if self.generated_files:
                    self.dependency_context = "\n\n".join(
                        (
                            self.summarize_project_edit_generated_interface(
                                dependency_path, dependency_source
                            )
                            for dependency_path, _original, dependency_source in self.generated_files
                        )
                    )
                    self.suffix += (
                        "\n\nCompleted dependency files. Import and call their public APIs; do not duplicate them:\n"
                        + self.dependency_context
                    )
                    if _deps.Path(self.path).name.startswith("test_"):
                        self.verified_boundaries = (
                            _deps._verified_external_boundary_targets(
                                self.generated_files, self.root
                            )
                        )
                        self.suffix += (
                            "\n\nVERIFIED PATCH/INJECTION TARGET ALLOWLIST:\n"
                            + (
                                "\n".join(
                                    (
                                        f"- {target}"
                                        for target in self.verified_boundaries
                                    )
                                )
                                if self.verified_boundaries
                                else "- (none; do not invent or patch an external target)"
                            )
                            + "\nUse only these exact targets when mocking an external boundary. Never invent a module, wrapper, function, or attribute."
                        )
                if self.parse_errors:
                    self.suffix += (
                        f"\n\nRevision attempt {self.attempt}. Fix only these deterministic failures:\n- "
                        + "\n- ".join(self.parse_errors)
                    )
                if self.rejected_source and (
                    not any(
                        (
                            token in " ".join(self.parse_errors).lower()
                            for token in ("syntax", "parse", "unterminated")
                        )
                    )
                ):
                    self.output_source = self.rejected_source
                    break
                if self.status_callback:
                    if self.parse_errors:
                        self.retry_reason = " | ".join(
                            (
                                str(error).replace("\n", " ")[:240]
                                for error in self.parse_errors[:3]
                            )
                        )
                        self.status_callback(
                            f"{self.stage.label} ({self.file_index}; attempt {self.attempt}) fixing: {self.retry_reason}"
                        )
                    else:
                        self.status_callback(
                            f"{self.stage.label} ({self.file_index}; attempt {self.attempt}) performing the sole initial complete-file generation"
                        )
                self.syntax_failure = bool(
                    self.rejected_source
                    and self.parse_errors
                    and any(
                        (
                            token in " ".join(self.parse_errors).lower()
                            for token in ("syntax", "parse", "unterminated")
                        )
                    )
                )
                self.syntax_repair_bounds: tuple[int, int] | None = None
                self.active_stage = self.stage
                if self.syntax_failure:
                    self.syntax_region_attempt += 1
                    self.active_stage, self.syntax_start, self.syntax_end = (
                        _deps._build_syntax_region_repair_stage(
                            self.stage,
                            source=self.rejected_source,
                            path=self.path,
                            failures=self.parse_errors,
                            attempt=self.syntax_region_attempt,
                        )
                    )
                    self.syntax_repair_bounds = (self.syntax_start, self.syntax_end)
                    if self.status_callback:
                        self.status_callback(
                            f"Syntax strategy transition: repairing only {_deps.Path(self.path).name}:{self.syntax_start}-{self.syntax_end}; complete-file regeneration skipped."
                        )
                self.response, self.timing = _deps._query_stage(
                    self.active_stage,
                    selected_model=(
                        _deps._strong_task_model(self.selected_model)
                        if self.syntax_failure and self.syntax_region_attempt > 1
                        else _deps._generation_task_model(
                            self.active_stage, self.selected_model, self.attempt
                        )
                    ),
                    settings=self.settings,
                    timeout=self.timeout,
                    suffix="" if self.syntax_failure else self.suffix,
                )
                self.timing.update({"attempt": self.attempt, "path": self.path})
                self.timings.append(self.timing)
                self.raw_response_hash = _deps._checkpoint_hash(self.response or "")
                if self.raw_response_hash in self.seen_raw_response_hashes:
                    self.output_source = self.rejected_source
                    self.parse_errors = [
                        (
                            "Syntax-region model returned an identical rejected response; expand the bounded region before validation."
                            if self.syntax_failure
                            else "Model returned an identical rejected response; strategy must change before validation."
                        )
                    ]
                    if self.status_callback:
                        self.status_callback(
                            "Rejected identical raw candidate before validation; expanding only the syntax repair region."
                        )
                    continue
                self.seen_raw_response_hashes.add(self.raw_response_hash)
                if self.syntax_repair_bounds is not None:
                    self.output_source, self.parse_errors = (
                        _deps._apply_syntax_region_repair(
                            self.rejected_source,
                            self.response,
                            start_line=self.syntax_repair_bounds[0],
                            end_line=self.syntax_repair_bounds[1],
                        )
                    )
                    if not self.parse_errors:
                        self.candidate_hash = _deps._checkpoint_hash(self.output_source)
                        if self.candidate_hash in self.seen_candidate_hashes:
                            self.parse_errors = [
                                "Syntax-region repair produced an identical rejected candidate; strategy must change before validation."
                            ]
                            if self.status_callback:
                                self.status_callback(
                                    "Rejected identical applied candidate before validation; expanding only the repair region."
                                )
                        else:
                            self.seen_candidate_hashes.add(self.candidate_hash)
                            self.output_source, self.parse_errors = (
                                _deps.parse_project_edit_generated_file(
                                    self.output_source,
                                    path=self.path,
                                    expected_public_symbols=self.expected_symbols,
                                )
                            )
                else:
                    self.output_source, self.parse_errors = (
                        _deps.parse_project_edit_generated_file(
                            self.response,
                            path=self.path,
                            expected_public_symbols=self.expected_symbols,
                        )
                    )
                    if self.output_source:
                        self.candidate_hash = _deps._checkpoint_hash(self.output_source)
                        if self.candidate_hash in self.seen_candidate_hashes:
                            self.parse_errors = [
                                "Generated candidate is identical to an already rejected candidate; strategy must change before validation."
                            ]
                        else:
                            self.seen_candidate_hashes.add(self.candidate_hash)
                if self.output_source:
                    self.parse_errors.extend(
                        _deps._requested_immutable_record_errors(
                            self.output_source, self.prompt
                        )
                    )
                    self.parse_errors.extend(
                        _deps._requested_public_constructor_errors(
                            self.output_source, self.prompt, self.expected_symbols
                        )
                    )
                self.focused_symbol_failure = False
                if self.output_source and self.parse_errors and self.expected_symbols:
                    for self.missing_symbol in self.expected_symbols:
                        if not any(
                            (
                                "omitted manifest-declared public symbols" in error
                                and self.missing_symbol in error
                                for error in self.parse_errors
                            )
                        ):
                            continue
                        self.symbol_stage = (
                            _deps.build_project_edit_missing_symbol_stage(
                                path=self.path,
                                symbol=self.missing_symbol,
                                source=self.output_source,
                                objective=self.prompt,
                                contracts=list(
                                    (self.stage.metadata or {}).get("contracts") or []
                                ),
                                algorithm_steps=list(
                                    (self.stage.metadata or {}).get("algorithm_steps")
                                    or []
                                ),
                            )
                        )
                        if self.status_callback:
                            self.status_callback(
                                f"Attempt {self.attempt} omitted required symbol {self.missing_symbol}; generating only that missing symbol."
                            )
                        self.symbol_errors: list[str] = []
                        for self.symbol_attempt in range(1, 3):
                            self.symbol_response, self.symbol_timing = (
                                _deps._query_stage(
                                    self.symbol_stage,
                                    selected_model=_deps._focused_repair_model(
                                        self.selected_model,
                                        self.attempt + self.symbol_attempt - 1,
                                    ),
                                    settings=self.settings,
                                    timeout=self.timeout,
                                )
                            )
                            self.symbol_timing.update(
                                {
                                    "attempt": self.symbol_attempt,
                                    "path": self.path,
                                    "symbol": self.missing_symbol,
                                    "strategy": "missing_symbol_only",
                                }
                            )
                            self.timings.append(self.symbol_timing)
                            self.candidate_source, self.symbol_errors = (
                                _deps.apply_project_edit_missing_symbol(
                                    self.output_source,
                                    path=self.path,
                                    symbol=self.missing_symbol,
                                    response=self.symbol_response,
                                    objective=self.prompt,
                                )
                            )
                            if not self.symbol_errors:
                                self.output_source = self.candidate_source
                                break
                            self.symbol_stage = _deps.replace(
                                self.symbol_stage,
                                user_prompt=self.symbol_stage.user_prompt
                                + "\n\nThe prior declaration-only response was rejected during exact insertion. Return a materially different declaration fixing only these errors:\n- "
                                + "\n- ".join(self.symbol_errors[:6]),
                                metadata={
                                    **dict(self.symbol_stage.metadata or {}),
                                    "strategy": "missing_symbol_error_focused",
                                    "prior_errors": list(self.symbol_errors),
                                },
                            )
                        if self.symbol_errors:
                            self.parse_errors = self.symbol_errors
                            self.focused_symbol_failure = True
                            continue
                        self.output_source, self.parse_errors = (
                            _deps.parse_project_edit_generated_file(
                                self.output_source,
                                path=self.path,
                                expected_public_symbols=self.expected_symbols,
                            )
                        )
                        if not self.parse_errors:
                            break
                if self.output_source and (not self.parse_errors):
                    break
                self.failure_fingerprint = _deps._checkpoint_hash(self.parse_errors)
                self.failure_strategy = (
                    "syntax_region_repair"
                    if self.syntax_failure
                    else "initial_file_generation"
                )
                self.repeated_failure = (
                    self.failure_fingerprint,
                    self.failure_strategy,
                ) in self.seen_failure_fingerprints
                self.seen_failure_fingerprints.add(
                    (self.failure_fingerprint, self.failure_strategy)
                )
                self.placeholder_only = bool(
                    self.output_source and self.parse_errors
                ) and all(
                    (
                        "placeholder callable bodies" in error
                        for error in self.parse_errors
                    )
                )
                if self.placeholder_only:
                    self.rejected_source = self.output_source
                    if self.status_callback:
                        self.status_callback(
                            f"Routing {_deps.Path(self.path).name} placeholder failures to focused callable completion instead of regenerating the file."
                        )
                    break
                if self.status_callback:
                    self.normalized_failures = " ".join(self.parse_errors).lower()
                    if (
                        "syntax" in self.normalized_failures
                        or "parse" in self.normalized_failures
                    ):
                        self.failure_category = "syntax/parse"
                    elif "placeholder" in self.normalized_failures:
                        self.failure_category = "placeholder implementation"
                    elif (
                        "omitted" in self.normalized_failures
                        or "symbol" in self.normalized_failures
                    ):
                        self.failure_category = "required symbol"
                    elif (
                        "immutable" in self.normalized_failures
                        or "frozen" in self.normalized_failures
                    ):
                        self.failure_category = "immutable record contract"
                    elif "import" in self.normalized_failures:
                        self.failure_category = "import surface"
                    else:
                        self.failure_category = "file contract"
                    self.rejection_reason = (
                        " | ".join(
                            (
                                str(error).replace("\n", " ")[:240]
                                for error in self.parse_errors[:3]
                            )
                        )
                        or "model response did not produce usable Python source"
                    )
                    self.status_callback(
                        f"Rejected {_deps.Path(self.path).name} attempt {self.attempt} [{self.failure_category}]: {self.rejection_reason}"
                    )
                    if self.repeated_failure:
                        self.status_callback(
                            "Repeated failure fingerprint detected; an equivalent strategy will not be invoked again."
                        )
                if self.output_source:
                    self.rejected_source = self.output_source
                if self.repeated_failure or self.focused_symbol_failure:
                    break
            if self.output_source and any(
                ("placeholder callable bodies" in error for error in self.parse_errors)
            ):
                self.placeholder_names = list(
                    dict.fromkeys(
                        (
                            name
                            for error in self.parse_errors
                            for group in _deps.re.findall(
                                "placeholder callable bodies[^:]*:\\s*([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?(?:\\s*,\\s*[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?)*)",
                                error,
                            )
                            for name in (value.strip() for value in group.split(","))
                            if name
                        )
                    )
                )
                self.provisional_files = [
                    *self.generated_files,
                    (self.path, self.original_source, self.output_source),
                ]
                try:
                    self.placeholder_tree = _deps.ast.parse(
                        self.output_source, filename=self.path
                    )
                except SyntaxError:
                    self.placeholder_tree = None
                for self.placeholder_name in self.placeholder_names:
                    if self.placeholder_tree is None:
                        break
                    if "." in self.placeholder_name:
                        self.target_symbol = self.placeholder_name
                    else:
                        self.owner_class = next(
                            (
                                node.name
                                for node in self.placeholder_tree.body
                                if isinstance(node, _deps.ast.ClassDef)
                                and any(
                                    (
                                        isinstance(
                                            child,
                                            (
                                                _deps.ast.FunctionDef,
                                                _deps.ast.AsyncFunctionDef,
                                            ),
                                        )
                                        and child.name == self.placeholder_name
                                        for child in node.body
                                    )
                                )
                            ),
                            "",
                        )
                        self.target_symbol = (
                            f"{self.owner_class}.{self.placeholder_name}"
                            if self.owner_class
                            else self.placeholder_name
                        )
                    self.contract, self.contract_errors = (
                        _deps.build_project_edit_function_repair_contract(
                            self.provisional_files,
                            target={"path": self.path, "symbol": self.target_symbol},
                            validation_errors=self.parse_errors,
                            objective=self.prompt,
                        )
                    )
                    if self.contract_errors:
                        continue
                    self.repair_stage = _deps.build_project_edit_function_repair_stage(
                        self.contract, attempt=self.max_attempts
                    )
                    if self.status_callback:
                        self.status_callback(
                            f"Completing placeholder {self.target_symbol}"
                        )
                    self.replacement, self.timing = _deps._query_stage(
                        self.repair_stage,
                        selected_model=_deps._focused_repair_model(
                            self.selected_model, self.max_attempts
                        ),
                        settings=self.settings,
                        timeout=self.timeout,
                    )
                    self.timing.update(
                        {
                            "attempt": self.max_attempts,
                            "path": self.path,
                            "symbol": self.target_symbol,
                            "stage": "placeholder_function_repair",
                        }
                    )
                    self.timings.append(self.timing)
                    self.provisional_files, self.repair_errors = (
                        _deps.apply_project_edit_generated_symbol_repair(
                            self.provisional_files,
                            path=self.path,
                            symbol=self.target_symbol,
                            replacement_response=self.replacement,
                            forbidden_names=list(
                                self.contract.get("forbidden_names") or []
                            ),
                        )
                    )
                    if self.repair_errors:
                        self.parse_errors = self.repair_errors
                        continue
                    self.output_source = self.provisional_files[-1][2]
                    self.placeholder_tree = _deps.ast.parse(
                        self.output_source, filename=self.path
                    )
                    self.output_source, self.parse_errors = (
                        _deps.parse_project_edit_generated_file(
                            self.output_source,
                            path=self.path,
                            expected_public_symbols=self.expected_symbols,
                        )
                    )
                    if self.parse_errors:
                        self.provisional_files[-1] = (
                            self.path,
                            self.original_source,
                            self.output_source,
                        )
                        self.provisional_files, self.import_repairs = (
                            _deps._repair_proven_import_surface(
                                self.provisional_files,
                                self.parse_errors,
                                self.prompt,
                                self.root,
                            )
                        )
                        if self.import_repairs:
                            self.output_source = self.provisional_files[-1][2]
                            self.placeholder_tree = _deps.ast.parse(
                                self.output_source, filename=self.path
                            )
                            self.output_source, self.parse_errors = (
                                _deps.parse_project_edit_generated_file(
                                    self.output_source,
                                    path=self.path,
                                    expected_public_symbols=self.expected_symbols,
                                )
                            )
            if self.parse_errors or not self.output_source:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="file_generation_failed",
                        errors=[f"{self.path}: {error}" for error in self.parse_errors]
                        or [f"{self.path}: model returned no usable Python source."],
                        timings=self.timings,
                    )
                )
            self.output_source = _deps._remove_foreign_manifest_symbols(
                self.output_source, path=self.path, symbol_owners=self.symbol_owners
            )
            self.output_source, self._dependency_repairs = (
                _deps.repair_project_edit_duplicate_dependency_symbols(
                    self.output_source,
                    path=self.path,
                    project_root=self.root,
                    generated_files=self.generated_files,
                )
            )
            if _deps.Path(self.path).name.startswith("test_"):
                self.output_source = _deps._ensure_qt_test_application(
                    self.output_source
                )
            self.generated_files.append(
                (self.path, self.original_source, self.output_source)
            )
            self.file_records[self.path] = (
                self.original_source,
                self.stage,
                self.expected_symbols,
            )
        if self.status_callback:
            self.status_callback(
                "Generated top-level symbols: "
                + _deps._describe_top_level_symbols(self.generated_files)
            )
        self.generated_files = _deps._normalize_generated_files(
            self.generated_files, project_root=self.root, request_prompt=self.prompt
        )
        if self.status_callback:
            self.status_callback(
                "Normalized top-level symbols: "
                + _deps._describe_top_level_symbols(self.generated_files)
            )
        self.generated_files = _deps._enforce_manifest_symbol_owners(
            self.generated_files, self.symbol_owners, project_root=self.root
        )
        self.generated_files, self._cross_file_repairs = (
            _deps.resolve_project_edit_cross_file_symbols(
                self.generated_files, project_root=self.root
            )
        )
        self.completed_owned_symbol = False
        for self.owned_symbol, self.owner_path in self.symbol_owners.items():
            self.owner_index = next(
                (
                    index
                    for index, (path, _original_source, _source) in enumerate(
                        self.generated_files
                    )
                    if path == self.owner_path
                ),
                None,
            )
            if self.owner_index is None:
                continue
            self.path, self.original_source, self.owner_source = self.generated_files[
                self.owner_index
            ]
            try:
                _deps.ast.parse(self.owner_source, filename=self.path)
            except SyntaxError:
                continue
            if _deps._source_defines_symbol(
                self.owner_source, self.owned_symbol, self.prompt
            ):
                continue
            self._record_original, self.owner_stage, self._expected_symbols = (
                self.file_records[self.path]
            )
            self.symbol_stage = _deps.build_project_edit_missing_symbol_stage(
                path=self.path,
                symbol=self.owned_symbol,
                source=self.owner_source,
                objective=self.prompt,
                contracts=list(
                    (self.owner_stage.metadata or {}).get("contracts") or []
                ),
                algorithm_steps=list(
                    (self.owner_stage.metadata or {}).get("algorithm_steps") or []
                ),
            )
            self.completion_feedback = ""
            self.rejected_completion_fingerprints: set[str] = set()
            for self.completion_attempt in _deps.itertools.count(1):
                self.symbol_response, self.symbol_timing = _deps._query_stage(
                    self.symbol_stage,
                    selected_model=_deps._focused_repair_model(
                        self.selected_model, self.completion_attempt + 1
                    ),
                    settings=self.settings,
                    timeout=self.timeout,
                    suffix=self.completion_feedback,
                )
                self.symbol_timing.update(
                    {
                        "attempt": self.completion_attempt,
                        "path": self.path,
                        "symbol": self.owned_symbol,
                        "reason": "post-normalization ownership completion",
                    }
                )
                self.timings.append(self.symbol_timing)
                self.completed_source, self.completion_errors = (
                    _deps.apply_project_edit_missing_symbol(
                        self.owner_source,
                        path=self.path,
                        symbol=self.owned_symbol,
                        response=self.symbol_response,
                        objective=self.prompt,
                    )
                )
                if not self.completion_errors:
                    break
                self.rejection_fingerprint = "\n".join(
                    [
                        str(self.symbol_response or "").strip(),
                        *sorted((str(error) for error in self.completion_errors)),
                    ]
                )
                if self.rejection_fingerprint in self.rejected_completion_fingerprints:
                    raise _WorkflowReturn(
                        _deps.ProjectEditWorkflowResult(
                            ok=False,
                            status="missing_symbol_repair_stalled",
                            candidate=_deps.build_project_edit_multi_file_candidate(
                                self.generated_files
                            ),
                            errors=[
                                f"Missing-symbol repair for {self.owned_symbol} repeated an identical rejected response. The candidate was preserved and no equivalent retry was invoked.",
                                *self.completion_errors,
                            ],
                            timings=self.timings,
                        )
                    )
                self.rejected_completion_fingerprints.add(self.rejection_fingerprint)
                if self.status_callback:
                    self.status_callback(
                        f"Rejected missing-symbol repair for {self.owned_symbol}, attempt {self.completion_attempt}: {'; '.join(self.completion_errors)}"
                    )
                self.completion_feedback = (
                    f"\n\nThe prior bounded missing-symbol response was rejected. Return only one complete, materially different declaration for {self.owned_symbol}. Fix these exact application failures:\n- "
                    + "\n- ".join(self.completion_errors[:6])
                )
            self.generated_files[self.owner_index] = (
                self.path,
                self.original_source,
                self.completed_source,
            )
            self.completed_owned_symbol = True
        if self.completed_owned_symbol:
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
        self.generated_files, self.deterministic_plan_repairs = (
            self.apply_deterministic_implementation_plan_repairs(
                self.implementation_plan, self.generated_files
            )
        )
        if self.deterministic_plan_repairs and self.status_callback:
            self.status_callback(
                "Applied approved deterministic AST repairs: "
                + "; ".join(self.deterministic_plan_repairs)
            )
        self.generated_files, self._unused_import_repairs = (
            _deps.remove_project_edit_unused_imports(self.generated_files)
        )
        if self.status_callback:
            self.status_callback(
                "Ownership-enforced top-level symbols: "
                + _deps._describe_top_level_symbols(self.generated_files)
            )
        self.candidate = _deps.build_project_edit_multi_file_candidate(
            self.generated_files
        )
        self.previous_signature: tuple[str, ...] | None = None
        self.pending_symbol_progress_check: (
            tuple[str, str, tuple[str, ...], str] | None
        ) = None
        self.preview: _deps.ProjectEditApplyResult | None = None
        self.class_repair_attempts: dict[tuple[str, str], int] = {
            (str(row[0]), str(row[1])): int(row[2])
            for row in self.restored_workflow_state.get("class_repair_attempts", [])
            if isinstance(row, list) and len(row) == 3
        }
        self.class_repair_rejections: dict[tuple[str, str], list[str]] = {}
        self.runtime_snapshot_repair_plans: dict[
            tuple[str, ...], dict[tuple[str, str], dict[str, _deps.Any]]
        ] = {}
        self.signature_repetitions: dict[tuple[str, ...], int] = {}
        self.stalled_callable_symbols: set[tuple[str, str]] = {
            (str(row[0]), str(row[1]))
            for row in self.restored_workflow_state.get("stalled_callable_symbols", [])
            if isinstance(row, list) and len(row) == 2
        }
        self.strong_callable_symbols: set[tuple[str, str]] = {
            (str(row[0]), str(row[1]))
            for row in self.restored_workflow_state.get("strong_callable_symbols", [])
            if isinstance(row, list) and len(row) == 2
        }
        self.compact_callable_attempts: dict[tuple[str, str], int] = {
            (str(row[0]), str(row[1])): int(row[2])
            for row in self.restored_workflow_state.get("compact_callable_attempts", [])
            if isinstance(row, list) and len(row) == 3
        }
        self.file_repair_attempts: dict[str, int] = {
            str(row[0]): int(row[1])
            for row in self.restored_workflow_state.get("file_repair_attempts", [])
            if isinstance(row, list) and len(row) == 2
        }
        self.final_review_cache: dict[str, list[str]] = {}
        self.semantic_proof_cache: dict[str, str] = {
            str(row[0]): str(row[1])
            for row in self.restored_workflow_state.get("semantic_proofs", [])
            if isinstance(row, list) and len(row) == 2
        }
        self.behavior_harness_cache: dict[str, tuple[str, str]] = {}
        self.behavior_harness_feedback: dict[str, str] = {}
        self.persisted_harness = (
            self.restored_workflow_state.get("behavior_harness")
            if isinstance(self.restored_workflow_state, dict)
            else None
        )
        if isinstance(self.persisted_harness, dict):
            self.persisted_key = str(self.persisted_harness.get("cache_key") or "")
            self.persisted_path = str(self.persisted_harness.get("path") or "")
            self.persisted_source = str(self.persisted_harness.get("source") or "")
            if self.persisted_key and self.persisted_path and self.persisted_source:
                self.behavior_harness_cache[self.persisted_key] = (
                    self.persisted_path,
                    self.persisted_source,
                )

        def persist_behavior_harness(cache_key: str, path: str, source: str) -> None:
            self.behavior_harness_cache[cache_key] = (path, source)
            checkpoint_state = dict(self.restored_workflow_state or {})
            checkpoint_state.update(
                {
                    "complete": False,
                    "validation_state": "candidate",
                    "behavior_harness": {
                        "cache_key": cache_key,
                        "path": path,
                        "source": source,
                    },
                }
            )
            _deps._save_workflow_checkpoint(
                self.root,
                self.prompt,
                self.selected_model,
                self.generated_files,
                checkpoint_state,
                implementation_plan_hash=self.approval_id,
            )
            self.restored_workflow_state = checkpoint_state

        self.persist_behavior_harness = persist_behavior_harness
        self.restored_review_fingerprint = str(
            self.restored_workflow_state.get("final_review_fingerprint") or ""
        )
        self.restored_review_errors = self.restored_workflow_state.get(
            "final_review_errors"
        )
        if (
            self.restored_review_fingerprint
            and self.restored_review_fingerprint
            == _deps._candidate_checkpoint_fingerprint(self.candidate)
            and isinstance(self.restored_review_errors, list)
        ):
            self.final_review_cache[self.candidate] = [
                str(error) for error in self.restored_review_errors
            ]
        self.starting_attempt = int(self.restored_workflow_state.get("attempt") or 0)
        self.seen_validation_candidate_fingerprints: set[str] = set()
        self.last_validation_errors = list(
            self.restored_review_errors
            if isinstance(self.restored_review_errors, list)
            else []
        )
