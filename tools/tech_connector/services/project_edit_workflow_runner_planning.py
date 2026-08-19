"""Project-edit workflow phase: _run_planning_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_requirement_semantics import (
    is_project_edit_quality_requirement as _is_project_edit_quality_requirement,
)
from tech_connector.services.project_edit_workflow_runner_control import _WorkflowReturn


class _ProjectEditPlanningPhase:
    """Provide the planning workflow phase."""

    def _run_planning_phase(self) -> None:
        """Run the planning phase.

        :return: None.
        """
        "Run the shared one-or-many-file stages used by every project editor."
        self.settings = dict(self.settings or {})
        self.resolved_route = _deps.resolve_llm_provider_route(
            self.selected_model, self.settings
        )
        if not self.resolved_route.cloud_active:
            self.selected_model = self.resolved_route.model
        self.root = str(_deps.Path(self.project_root).resolve())
        self.user_prompt = str(self.original_prompt or self.prompt)
        self.workflow_prompt = self.prompt
        if self.dry_run and "preview only" not in self.prompt.lower():
            self.workflow_prompt = (
                self.prompt.rstrip()
                + "\n\nPreview only; do not apply changes. Return complete working code for every requested file."
            )
        if self.dry_run and "disposable workspace" not in self.workflow_prompt.lower():
            self.workflow_prompt += "\nGenerate and validate only inside a disposable workspace; never write to live project files."
        self.explicit_python_files = {
            _deps.Path(match.group(0)).name
            for match in _deps.re.finditer(
                "\\b[A-Za-z_][A-Za-z0-9_]*\\.py\\b", self.workflow_prompt
            )
        }
        self.explicit_dotted_modules = _deps._explicit_dotted_module_requests(
            self.workflow_prompt
        )
        self.explicit_requested_files = {
            *self.explicit_python_files,
            *[
                module_name.rsplit(".", 1)[-1] + ".py"
                for module_name in self.explicit_dotted_modules
            ],
        }
        self.deterministic_manifest_available = bool(
            self.explicit_requested_files or self.active_path
        )
        self.plan_started = _deps.time.perf_counter()
        self.plan = (
            _deps.ProjectEditPlan(
                prompt=self.workflow_prompt,
                active_path=self.active_path or "",
                discovery={
                    "status": "explicit_target",
                    "requested_files": sorted(self.explicit_requested_files),
                },
                discovery_context="Exact paths are owned by the deterministic manifest.",
                model_prompt=self.workflow_prompt,
            )
            if self.deterministic_manifest_available
            else _deps.build_project_edit_agent_request(
                self.workflow_prompt, active_path=self.active_path or None, limit=8
            )
        )
        self.timings: list[dict[str, _deps.Any]] = [
            {
                "stage": "project_edit_plan",
                "label": "Resolving project edit plan",
                "model": "deterministic",
                "elapsed_ms": (_deps.time.perf_counter() - self.plan_started) * 1000.0,
            }
        ]
        self.manifest_stage = _deps.build_project_edit_artifact_manifest_stage(
            self.plan
        )
        if self.manifest_stage is None and (not self.deterministic_manifest_available):
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="not_multi_file_artifact",
                    errors=[
                        "The shared artifact workflow could not identify an exact artifact owner."
                    ],
                    timings=self.timings,
                )
            )
        self.requirement_ledger = _deps.extract_project_edit_artifact_requirements(
            self.user_prompt
        )
        self.early_cached_approval = None
        if self.approved_plan_id:
            from tech_connector.services.implementation_plan_quality_service import (
                load_approved_plan_candidate as _load_approved_plan_candidate,
            )

            self._load_approved_plan_candidate = _load_approved_plan_candidate
            self.early_cached_approval = self._load_approved_plan_candidate(
                self.approved_plan_id, prompt=self.user_prompt, project_root=self.root
            )
            if self.early_cached_approval:
                self.requirement_ledger = [
                    dict(item)
                    for item in self.early_cached_approval.get("requirement_ledger", [])
                ]
                if self.status_callback:
                    self.status_callback(
                        "Reusing the unchanged approved implementation plan and its grounded evidence."
                    )
        self.semantic_review_required = (
            _deps._requirement_ledger_needs_semantic_review(self.requirement_ledger)
            and self.early_cached_approval is None
        )
        self.skip_contract_generation = bool(
            self.deterministic_manifest_available
            and self.requirement_ledger
            and (not self.semantic_review_required)
        )
        self.contract_stage = _deps.build_project_edit_integration_contract_stage(
            self.plan
        )
        self.contract_stage = _deps.replace(
            self.contract_stage,
            user_prompt=self.contract_stage.user_prompt
            + "\n\nGeneric completeness rules:\n- Treat slash-separated or paired actions such as save/load, encode/decode, start/stop, and import/export as distinct operations with distinct callable signatures unless the user explicitly requests one combined operation.\n- For every callback requirement, define the owning callable signature, when the callback fires, and the exact ordered argument types and meanings.\n- Preserve every explicitly named method, state transition, rejection case, round trip, and test proof as a separate contract fact.",
        )
        self.requests_qt_ui = bool(
            _deps.re.search(
                "\\b(?:qt|pyside6?|pyqt[56]?)\\b",
                self.prompt,
                flags=_deps.re.IGNORECASE,
            )
            and _deps.re.search(
                "\\b(?:ui|dialog|window|widget|panel|picker)\\b",
                self.prompt,
                flags=_deps.re.IGNORECASE,
            )
        )
        self.indexed_base_owner_context = (
            ""
            if self.skip_contract_generation
            else _deps._indexed_requested_base_owner_context(
                self.workflow_prompt, self.root
            )
        )
        if self.indexed_base_owner_context:
            self.contract_stage = _deps.replace(
                self.contract_stage,
                user_prompt=self.contract_stage.user_prompt
                + self.indexed_base_owner_context,
            )
        if not self.skip_contract_generation:
            self.contract_stage = _deps.replace(
                self.contract_stage,
                user_prompt=self.contract_stage.user_prompt
                + _deps._federated_symbol_evidence_context(
                    self.workflow_prompt, project_root=self.root
                ),
            )
        if self.requests_qt_ui:
            self.available_qt_binding = _deps._available_qt_binding()
            self.contract_stage = _deps.replace(
                self.contract_stage,
                user_prompt=self.contract_stage.user_prompt
                + f"\n\nMANDATORY QT UI CONTRACT:\n- The importable Qt binding resolved for this project is\n  {self.available_qt_binding or 'not currently importable'}; use it rather than inventing\n  or mixing bindings.\n- Own a public QWidget, QDialog, or existing project modeless-dialog subclass.\n- Specify concrete controls, layouts, signals, and fully implemented handlers.\n- Every requested control must participate in observable behavior.\n- When interaction is requested anywhere on the screen, the UI must provide a\n  full-screen or virtual-desktop overlay (or an equivalently verified global\n  interaction mechanism), use a crosshair cursor, receive clicks outside the\n  original tool window, map the global position to the correct QScreen, hide the\n  overlay before capture, and sample the clicked QImage pixel. A mouse handler on\n  a small ordinary window does not satisfy an anywhere-on-screen request.\n- Tests must mock or inject the QScreen/capture boundary. They must not depend on\n  the test machine's real desktop pixels, geometry, or display availability.\n- If the UI file is newly created, include a QApplication-safe __main__ launch\n  path that constructs, shows, and runs the window.\n- Include a focused test that constructs the UI and proves its primary interaction.\n",
            )
        self.contract_response = (
            _deps.json.dumps(
                {
                    "source": "deterministic_requirement_ledger",
                    "requirements": self.requirement_ledger,
                },
                ensure_ascii=True,
            )
            if self.skip_contract_generation
            else ""
        )
        self.contract_errors: list[str] = []
        self.contract_feedback = ""
        if self.skip_contract_generation and self.status_callback:
            self.status_callback(
                "Skipping package-contract inference; explicit targets and the deterministic requirement ledger are complete."
            )
        for self.attempt in (
            () if self.skip_contract_generation else _deps.itertools.count(1)
        ):
            if self.status_callback:
                self.status_callback(
                    f"{self.contract_stage.label}, attempt {self.attempt}"
                )
            self.raw_contract, self.timing = _deps._query_stage(
                self.contract_stage,
                selected_model=_deps._focused_repair_model(
                    self.selected_model, self.attempt
                ),
                settings=self.settings,
                timeout=self.timeout,
                suffix=self.contract_feedback,
            )
            self.timing["attempt"] = self.attempt
            self.timings.append(self.timing)
            self.contract_response, self.contract_errors = (
                _deps.complete_project_edit_integration_contract_response(
                    self.raw_contract, self.requirement_ledger
                )
            )
            if not self.contract_errors:
                break
            self.contract_feedback = (
                "\n\nThe prior integration contract was rejected. Return a corrected complete contract that fixes only these failures:\n- "
                + "\n- ".join(self.contract_errors[:8])
            )
        if self.contract_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="integration_contract_failed",
                    errors=self.contract_errors,
                    timings=self.timings,
                )
            )
        self.contract_review_suffix = f"\n\nIndependent semantic contract quality pass.\nCandidate contract:\n```json\n{self.contract_response}\n```\n\nReturn a corrected complete contract using the original schema. Do not merely approve or summarize the candidate.\nProve all of the following in the corrected signatures, data layout, and invariants:\n- Every requested state that can be queried, traversed, resumed, cancelled, migrated, finalized, or reported can be\n  constructed through the public input/mutation API.\n- Every canonical record contains every identity, relationship, offset, digest, callable, or payload field consumed\n  by another operation; no consumer relies on a field absent from that record.\n- When the domain is a graph or ordered pipeline, each relationship stores both endpoints and any executable payload\n  needed downstream, and traversal has an explicit target or completion condition.\n- Reusable methods receive caller-selected values rather than hard-coding sentinel domain values.\n- Tests can arrange every requested success, rejection, failure, recovery, and immutability case using only those\n  public signatures.\nReplace any contradictory candidate fact instead of preserving it.\n"
        self.reviewed_contract = ""
        self.review_errors: list[str] = []
        if not self.semantic_review_required:
            self.reviewed_contract = self.contract_response
            if self.status_callback:
                self.status_callback(
                    "Skipping semantic contract review; the deterministic requirement ledger is complete and unambiguous."
                )
        for self.review_attempt in (
            _deps.itertools.count(1) if self.semantic_review_required else ()
        ):
            if self.status_callback:
                self.status_callback(
                    f"Reviewing shared contract semantics, attempt {self.review_attempt}"
                )
            self.reviewed_raw, self.review_timing = _deps._query_stage(
                self.contract_stage,
                selected_model=_deps._focused_repair_model(
                    self.selected_model, self.review_attempt
                ),
                settings=self.settings,
                timeout=self.timeout,
                suffix=self.contract_review_suffix,
            )
            self.review_timing.update(
                {
                    "attempt": self.review_attempt,
                    "stage": "artifact_integration_contract_review",
                    "label": "Reviewing shared contract semantics",
                }
            )
            self.timings.append(self.review_timing)
            self.reviewed_contract, self.review_errors = (
                _deps.complete_project_edit_integration_contract_response(
                    self.reviewed_raw, self.requirement_ledger
                )
            )
            if not self.review_errors:
                self.contract_response = self.reviewed_contract
                break
            self.contract_review_suffix += (
                "\n\nThe semantic review response was structurally rejected. Correct these failures while retaining the semantic proof:\n- "
                + "\n- ".join(self.review_errors[:8])
            )
        if self.review_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="integration_contract_review_failed",
                    errors=self.review_errors,
                    timings=self.timings,
                )
            )
        self.manifest_stage = (
            self.manifest_stage
            if self.skip_contract_generation
            else _deps.build_project_edit_artifact_manifest_stage(
                self.plan, approved_plan=self.contract_response
            )
        )
        if self.manifest_stage is None and (not self.deterministic_manifest_available):
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="manifest_unavailable",
                    errors=[
                        "The validated integration contract did not produce a manifest stage."
                    ],
                    timings=self.timings,
                )
            )
        if self.requests_qt_ui and self.manifest_stage is not None:
            self.manifest_stage = _deps.replace(
                self.manifest_stage,
                user_prompt=self.manifest_stage.user_prompt
                + "\n\nQT UI OWNERSHIP REQUIREMENTS:\n- Assign one public Qt window/dialog/widget class to a production file.\n- Assign its interaction handlers to that same class.\n- For a newly created UI file, require a runnable __main__ launch path.\n- Assign focused construction-and-interaction checks to disposable validation\n  unless the request explicitly requires a permanent test artifact.\n- Do not replace the requested UI with only utility functions.\n",
            )
        self.requested_filenames = {
            _deps.Path(match.group(0)).name
            for match in _deps.re.finditer(
                "\\b[A-Za-z_][A-Za-z0-9_]*\\.py\\b", self.prompt
            )
        }
        self.requested_filenames.update(
            (
                module_name.rsplit(".", 1)[-1] + ".py"
                for module_name in _deps._explicit_dotted_module_requests(self.prompt)
            )
        )
        self.manifest: list[dict[str, _deps.Any]] = []
        self.manifest_errors: list[str] = []
        self.manifest_feedback = ""
        if self.requested_filenames or self.active_path:
            self.manifest = _deps._fallback_requested_file_manifest(
                self.workflow_prompt,
                project_root=self.root,
                requirement_ledger=self.requirement_ledger,
            )
            if self.status_callback:
                self.status_callback("Using deterministic requested-file manifest.")
        else:
            if self.manifest_stage is None:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="manifest_unavailable",
                        errors=[
                            "No deterministic or generated artifact manifest is available."
                        ],
                        timings=self.timings,
                    )
                )
            for self.attempt in _deps.itertools.count(1):
                if self.status_callback:
                    self.status_callback(
                        f"{self.manifest_stage.label}, attempt {self.attempt}"
                    )
                self.response, self.timing = _deps._query_stage(
                    self.manifest_stage,
                    selected_model=_deps._focused_repair_model(
                        self.selected_model, self.attempt
                    ),
                    settings=self.settings,
                    timeout=self.timeout,
                    suffix=self.manifest_feedback,
                )
                self.timing["attempt"] = self.attempt
                self.timings.append(self.timing)
                self.manifest, self.manifest_errors = (
                    _deps.parse_project_edit_artifact_manifest(
                        _deps._normalize_manifest_contract(
                            self.response, self.workflow_prompt
                        ),
                        project_root=self.root,
                        requirement_ledger=self.requirement_ledger,
                        strict_architecture=True,
                    )
                )
                if not self.manifest_errors and self.requested_filenames:
                    self.planned_filenames = {
                        _deps.Path(str(item.get("path") or "")).name
                        for item in self.manifest
                    }
                    self.missing_files = sorted(
                        self.requested_filenames - self.planned_filenames
                    )
                    if self.missing_files:
                        self.manifest_errors = [
                            "Artifact manifest omitted explicitly requested files: "
                            + ", ".join(self.missing_files)
                        ]
                if not self.manifest_errors:
                    break
                self.manifest_feedback = (
                    "\n\nThe prior manifest was rejected. Return a complete corrected manifest that fixes only these validation failures:\n- "
                    + "\n- ".join(self.manifest_errors[:8])
                )
        if self.manifest_errors:
            self.manifest = _deps._fallback_requested_file_manifest(
                self.workflow_prompt,
                project_root=self.root,
                requirement_ledger=self.requirement_ledger,
            )
            if self.status_callback and self.manifest:
                self.status_callback(
                    "Using deterministic requested-file manifest after architecture retries."
                )
            if not self.manifest:
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status="manifest_failed",
                        errors=self.manifest_errors,
                        timings=self.timings,
                    )
                )
        self.single_file_scope = bool(
            _deps.re.search(
                "\\b(?:exactly|only)\\s+(?:one|1)\\s+(?:new\\s+)?(?:[A-Za-z0-9_+-]+\\s+){0,3}files?\\b|\\bno\\s+(?:other|extra|additional)\\s+files?\\b|\\bdo\\s+not\\s+(?:add|create|generate|write)\\s+(?:any\\s+)?(?:other|extra|additional)\\s+files?\\b",
                self.user_prompt,
                flags=_deps.re.IGNORECASE,
            )
        )
        if self.single_file_scope:
            self.production_manifest = [
                item for item in self.manifest if not bool(item.get("is_test"))
            ]
            if len(self.production_manifest) == 1:
                self.manifest = self.production_manifest
        if self.early_cached_approval:
            self.manifest = [
                dict(item) for item in self.early_cached_approval.get("manifest", [])
            ]
        from tech_connector.services.symbol_evidence_service import (
            build_symbol_evidence_packet,
            extract_symbol_evidence_queries,
        )

        self.build_symbol_evidence_packet = build_symbol_evidence_packet
        self.extract_symbol_evidence_queries = extract_symbol_evidence_queries
        self.preplan_grounding: dict[str, _deps.Any] = {}
        if not self.early_cached_approval:
            self.requires_external_grounding = bool(
                _deps.re.search(
                    "\\b(?:API|adapter|bridge|transport|plugin|PySide|PyQt|Qt|maya|unreal|blender|motionbuilder|bpy|pyfbsdk|import|export|execute)\\b|\\b(?:existing|internal|official|installed|third[- ]party)\\b[^.!?\\n]{0,100}\\b(?:class|function|method|callable|module)\\b|\\b[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*){2,}\\s*\\(",
                    self.user_prompt,
                    flags=_deps.re.IGNORECASE,
                )
            )
            if self.requires_external_grounding:
                self.preplan_grounding = self.build_symbol_evidence_packet(
                    self.user_prompt,
                    project_root=self.root,
                    generated_overlay=[],
                    limit=32,
                    allow_official_research=True,
                    capability_search=True,
                )
            else:
                self.preplan_grounding = {
                    "schema": "tech_connector.symbol_evidence.v2",
                    "project_root": self.root,
                    "snapshot_id": "self-contained-standard-library",
                    "queries": [],
                    "capability_intents": [],
                    "evidence": [],
                    "provider_errors": [],
                    "unresolved_host_api_queries": [],
                    "unresolved_capability_intents": [],
                    "capability_acquisition_requests": [],
                    "local_capability_resolution_complete": True,
                    "online_capability_search_performed": False,
                    "cache_hit": True,
                    "lookup_decisions": [
                        {
                            "decision": "external_grounding",
                            "executed": False,
                            "reason": "request is self-contained and requires no external callable evidence",
                        }
                    ],
                    "evidence_total_ms": 0.0,
                }
            if self.status_callback:
                self.status_callback(
                    f"Pre-plan capability grounding: {len(self.preplan_grounding.get('capability_intents') or [])} intents, {len(self.preplan_grounding.get('evidence') or [])} evidence records, {self.preplan_grounding.get('evidence_total_ms', 0)}ms, cache={('hit' if self.preplan_grounding.get('cache_hit') else 'miss')}, online={('yes' if self.preplan_grounding.get('online_capability_search_performed') else 'no')}"
                )
                for self.decision in (
                    self.preplan_grounding.get("lookup_decisions") or []
                ):
                    self.status_callback(
                        f"Evidence decision: {self.decision.get('decision')}={('run' if self.decision.get('executed') else 'skip')} ({self.decision.get('reason')})"
                    )
            self.acquisition_requests = list(
                self.preplan_grounding.get("capability_acquisition_requests") or []
            )
            self.unresolved_capability_intents = list(
                self.preplan_grounding.get("unresolved_capability_intents") or []
            )
            if self.acquisition_requests or self.unresolved_capability_intents:
                self.local_complete = bool(
                    self.preplan_grounding.get(
                        "local_capability_resolution_complete", True
                    )
                )
                if self.status_callback:
                    self.status_callback(
                        "Planning paused: "
                        + (
                            "local capability resolution did not complete."
                            if not self.local_complete
                            else "reviewed capability acquisition is required."
                        )
                    )
                raise _WorkflowReturn(
                    _deps.ProjectEditWorkflowResult(
                        ok=False,
                        status=(
                            "capability_local_resolution_failed"
                            if not self.local_complete
                            else (
                                "capability_acquisition_required"
                                if self.acquisition_requests
                                else "plan_evidence_unresolved"
                            )
                        ),
                        errors=[
                            "Implementation planning is paused because one or more dependency-like capabilities have no authoritative callable signature. No API or target will be invented.",
                            *[
                                str(
                                    item.get("source_clause")
                                    or item.get("query")
                                    or item
                                )
                                for item in self.unresolved_capability_intents
                            ],
                        ],
                        timings=self.timings,
                        implementation_plan={
                            "schema": "tech_connector.capability_grounding_pause.v1",
                            "objective": self.user_prompt,
                            "manifest": self.manifest,
                            "requirement_ledger": self.requirement_ledger,
                            "capability_grounding": self.preplan_grounding,
                            "capability_acquisition_requests": self.acquisition_requests,
                            "resume_condition": "Re-run planning after local resolution succeeds or the approved source is credited, AST-verified, indexed, and resolves the original intent.",
                        },
                        approval_id="",
                    )
                )
        _deps._enrich_manifest_with_explicit_declarations(
            self.manifest, self.requirement_ledger
        )
        self.ledger_by_id = {
            str(item.get("id") or item.get("requirement_id") or ""): item
            for item in self.requirement_ledger
            if isinstance(item, _deps.Mapping)
        }
        self.unnamed_behavior_owners: list[dict[str, _deps.Any]] = []
        for self.manifest_item in self.manifest:
            if not isinstance(self.manifest_item, dict) or self.manifest_item.get(
                "is_test"
            ):
                continue
            self.owned_requirements = [
                self.ledger_by_id[requirement_id]
                for requirement_id in {
                    str(value)
                    for value in self.manifest_item.get("requirement_ids") or []
                    if str(value)
                }
                if requirement_id in self.ledger_by_id
            ]
            self.public_symbols = list(self.manifest_item.get("public_symbols") or [])
            for self.symbol_index, self.raw_symbol in enumerate(self.public_symbols):
                self.symbol = self.raw_symbol
                if not isinstance(self.symbol, dict):
                    self.symbol_name = str(self.symbol or "").split("(", 1)[0].strip()
                    if not self.symbol_name:
                        continue
                    self.symbol = {
                        "name": self.symbol_name,
                        "qualified_name": self.symbol_name,
                        "kind": (
                            "class"
                            if self.symbol_name.rsplit(".", 1)[-1][:1].isupper()
                            else "function"
                        ),
                        "requirement_ids": [
                            str(value)
                            for value in self.manifest_item.get("requirement_ids") or []
                            if str(value)
                        ],
                    }
                    self.public_symbols[self.symbol_index] = self.symbol
                self.owner = str(
                    self.symbol.get("qualified_name")
                    or self.symbol.get("name")
                    or self.symbol.get("owner")
                    or ""
                ).strip()
                if (
                    str(self.symbol.get("kind") or "") != "class"
                    or not self.owner
                    or self.symbol.get("inferred_callable_signatures")
                ):
                    continue
                self.owner_requirement_ids = {
                    str(value)
                    for value in self.symbol.get("requirement_ids") or []
                    if str(value)
                }
                self.owner_requirements = [
                    item
                    for item in self.owned_requirements
                    if str(item.get("id") or item.get("requirement_id") or "")
                    in self.owner_requirement_ids
                    and str(item.get("semantic_role") or "behavior")
                    not in {"quality", "structure"}
                ]
                if not self.owner_requirements:
                    continue
                self.owner_text = " ".join(
                    (str(item.get("text") or "") for item in self.owner_requirements)
                )
                self.has_explicit_method = bool(
                    _deps.re.search(
                        f"\\b{_deps.re.escape(self.owner)}\\.([a-z_][A-Za-z0-9_]*)\\s*\\(|\\b(?:define|implement|provide|expose|add)\\w*\\s+(?:a\\s+|an\\s+|the\\s+)?(?:public\\s+)?(?:method|function|callable\\s+)?([a-z_][A-Za-z0-9_]*)\\s*\\(",
                        self.owner_text,
                        flags=_deps.re.IGNORECASE,
                    )
                )
                if self.has_explicit_method:
                    continue
                self.unnamed_behavior_owners.append(
                    {
                        "file": str(
                            self.manifest_item.get("path")
                            or self.manifest_item.get("absolute_path")
                            or ""
                        ),
                        "owner": self.owner,
                        "requirement_ids": sorted(
                            {
                                str(item.get("id") or item.get("requirement_id") or "")
                                for item in self.owner_requirements
                                if str(
                                    item.get("id") or item.get("requirement_id") or ""
                                )
                            }
                        ),
                        "requirements": [
                            {
                                "id": str(
                                    item.get("id") or item.get("requirement_id") or ""
                                ),
                                "text": str(item.get("text") or ""),
                            }
                            for item in self.owner_requirements
                        ],
                    }
                )
            self.manifest_item["public_symbols"] = self.public_symbols
        if self.unnamed_behavior_owners and (not self.early_cached_approval):
            if self.status_callback:
                self.status_callback(
                    f"Resolving callable ownership for {len(self.unnamed_behavior_owners)} behavior-owning class(es)"
                )
            self.declaration_stage = _deps.ProjectEditPromptStage(
                key="implementation_plan_declaration_surface",
                label="Defining unnamed callable surfaces",
                system_prompt="Return JSON only. Decide whether each supplied class requires one public callable to make its owned behavior executable and testable. When needed, provide one concise snake_case method name and a complete typed Python signature beginning with `def name(self`. Infer only parameters necessary for the supplied requirements, including an explicit callback parameter when the requirement defines its callback protocol. Do not add constructor parameters, files, dependencies, UI getters, wrappers, or unrelated convenience methods. For UI classes, list only the private handler signatures required to connect requested controls and receive required completion/error paths; private handler names must start with `_`. A UI class whose requested behavior is construction plus private event handling does not require a new public callable. Every decision remains a proposal visible in the implementation plan and may not be changed by downstream generation or repair.",
                user_prompt=_deps.json.dumps(
                    {"owners": self.unnamed_behavior_owners},
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                model_tier="local_reasoning",
                num_ctx=4096,
                num_predict=900,
                timeout=60,
                no_progress_seconds=20,
                prefer_coder=True,
                coder_preference="standard",
                response_format={
                    "type": "object",
                    "properties": {
                        "owners": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "owner": {"type": "string"},
                                    "needs_callable": {"type": "boolean"},
                                    "method_name": {"type": "string"},
                                    "signature": {"type": "string"},
                                    "private_callables": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "method_name": {"type": "string"},
                                                "signature": {"type": "string"},
                                                "requirement_ids": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                                "rationale": {"type": "string"},
                                            },
                                            "required": [
                                                "method_name",
                                                "signature",
                                                "requirement_ids",
                                                "rationale",
                                            ],
                                            "additionalProperties": False,
                                        },
                                    },
                                    "requirement_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "rationale": {"type": "string"},
                                },
                                "required": [
                                    "owner",
                                    "needs_callable",
                                    "method_name",
                                    "signature",
                                    "private_callables",
                                    "requirement_ids",
                                    "rationale",
                                ],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["owners"],
                    "additionalProperties": False,
                },
                metadata={"disable_thinking": False},
            )
            self.declaration_response, self.declaration_timing = _deps._query_stage(
                self.declaration_stage,
                selected_model=self.selected_model,
                settings=self.settings,
                timeout=self.timeout,
            )
            self.timings.append(self.declaration_timing)
            try:
                self.declaration_payload = _deps.json.loads(self.declaration_response)
            except (TypeError, ValueError, _deps.json.JSONDecodeError):
                self.declaration_payload = {}
            self.allowed_rows = {
                row["owner"]: row for row in self.unnamed_behavior_owners
            }

            def normalize_declaration_payload(
                payload: _deps.Mapping[str, _deps.Any],
            ) -> dict[str, _deps.Any]:
                normalized = _deps.json.loads(_deps.json.dumps(payload, default=str))
                for proposal in normalized.get("owners") or []:
                    if not isinstance(proposal, dict):
                        continue
                    owner = str(proposal.get("owner") or "")
                    allowed = self.allowed_rows.get(owner)
                    if not allowed:
                        continue
                    requirement_text_by_id = {
                        str(item.get("id") or ""): str(item.get("text") or "")
                        for item in allowed["requirements"]
                    }
                    is_ui_owner = bool(
                        owner.endswith(("Dialog", "Window", "Widget", "Panel", "Dock"))
                        or any(
                            (
                                _deps.re.search(
                                    "\\b(?:Qt|UI|dialog|widget|window)\\b",
                                    text,
                                    flags=_deps.re.IGNORECASE,
                                )
                                for text in requirement_text_by_id.values()
                            )
                        )
                    )

                    def declaration_only(signature: str) -> str:
                        return _deps.re.sub(
                            "\\s*:\\s*(?:pass|\\.\\.\\.)\\s*$",
                            "",
                            str(signature or "").strip(),
                        )

                    proposal["signature"] = declaration_only(
                        proposal.get("signature") or ""
                    )
                    private_callables = [
                        dict(item)
                        for item in proposal.get("private_callables") or []
                        if isinstance(item, _deps.Mapping)
                    ]
                    allowed_requirement_ids = set(allowed["requirement_ids"])
                    retained_private_callables: list[dict[str, _deps.Any]] = []
                    for private in private_callables:
                        private["signature"] = declaration_only(
                            private.get("signature") or ""
                        )
                        private["requirement_ids"] = [
                            str(value)
                            for value in private.get("requirement_ids") or []
                            if str(value) in allowed_requirement_ids
                        ]
                        if private["requirement_ids"]:
                            retained_private_callables.append(private)
                    private_callables = retained_private_callables
                    if not is_ui_owner:
                        private_callables = []
                    method_name = str(proposal.get("method_name") or "").strip()
                    if is_ui_owner:
                        if proposal.get("needs_callable") and method_name.startswith(
                            "_"
                        ):
                            private_callables.append(
                                {
                                    "method_name": method_name,
                                    "signature": proposal["signature"],
                                    "requirement_ids": list(
                                        proposal.get("requirement_ids") or []
                                    ),
                                    "rationale": str(proposal.get("rationale") or ""),
                                }
                            )
                            proposal["needs_callable"] = False
                            proposal["method_name"] = ""
                            proposal["signature"] = ""
                            proposal["requirement_ids"] = []
                        for (
                            requirement_id,
                            requirement_text,
                        ) in requirement_text_by_id.items():
                            is_declaration_requirement = bool(
                                _deps.re.search(
                                    "\\b(?:define|contain|contains|containing|with)\\b",
                                    requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                                and _deps.re.search(
                                    "\\b(?:class|dialog|widget|window|panel)\\b",
                                    requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                                and (
                                    not _deps.re.search(
                                        "\\b(?:connect|clicked|triggered|execute|deliver|emit|return|reject|validate)\\b",
                                        requirement_text,
                                        flags=_deps.re.IGNORECASE,
                                    )
                                )
                            )
                            if is_declaration_requirement:
                                for private in private_callables:
                                    private["requirement_ids"] = [
                                        value
                                        for value in private.get("requirement_ids", [])
                                        if value != requirement_id
                                    ]
                            is_connection_requirement = bool(
                                _deps.re.search(
                                    "\\bconnect\\b|\\bclicked\\b|\\btriggered\\b",
                                    requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            if is_connection_requirement:
                                control_match = _deps.re.search(
                                    "\\b([a-z_][A-Za-z0-9_]*(?:_btn|_button))\\b",
                                    requirement_text,
                                )
                                control_name = (
                                    control_match.group(1)
                                    if control_match
                                    else "action"
                                )
                                control_stem = _deps.re.sub(
                                    "_(?:btn|button)$", "", control_name
                                )
                                exact_handler = next(
                                    (
                                        private
                                        for private in private_callables
                                        if control_stem
                                        and control_stem.casefold()
                                        in str(
                                            private.get("method_name") or ""
                                        ).casefold()
                                        or _deps.re.search(
                                            "(?:click|trigger)",
                                            str(private.get("method_name") or ""),
                                            flags=_deps.re.IGNORECASE,
                                        )
                                    ),
                                    None,
                                )
                                for private in private_callables:
                                    if private is exact_handler:
                                        continue
                                    private["requirement_ids"] = [
                                        value
                                        for value in private.get("requirement_ids", [])
                                        if value != requirement_id
                                    ]
                                if exact_handler is not None:
                                    exact_handler["requirement_ids"] = list(
                                        dict.fromkeys(
                                            [
                                                *list(
                                                    exact_handler.get(
                                                        "requirement_ids", []
                                                    )
                                                ),
                                                requirement_id,
                                            ]
                                        )
                                    )
                                else:
                                    handler_name = f"_on_{control_name}_clicked"
                                    private_callables.append(
                                        {
                                            "method_name": handler_name,
                                            "signature": f"def {handler_name}(self) -> None",
                                            "requirement_ids": [requirement_id],
                                            "rationale": "Own the explicitly requested control connection inside the UI class.",
                                        }
                                    )
                            needs_result_and_error = bool(
                                _deps.re.search(
                                    "\\b(?:result|completion|success)\\b",
                                    requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                                and _deps.re.search(
                                    "\\b(?:error|failure)\\b",
                                    requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            is_worker_requirement = bool(
                                _deps.re.search(
                                    "\\b(?:worker|background|thread)\\b",
                                    requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            if is_worker_requirement:
                                for private in private_callables:
                                    private_name = str(private.get("method_name") or "")
                                    if _deps.re.search(
                                        "(?:start|run|execute|dispatch|background|worker|result|success|finish|complete|error|fail)",
                                        private_name,
                                        flags=_deps.re.IGNORECASE,
                                    ):
                                        continue
                                    private["requirement_ids"] = [
                                        value
                                        for value in private.get("requirement_ids", [])
                                        if value != requirement_id
                                    ]
                            if needs_result_and_error:
                                owned = [
                                    private
                                    for private in private_callables
                                    if requirement_id
                                    in {
                                        str(value)
                                        for value in private.get("requirement_ids", [])
                                    }
                                ]
                                has_result = any(
                                    (
                                        _deps.re.search(
                                            "(?:result|success|finish|complete)",
                                            str(item.get("method_name") or ""),
                                            flags=_deps.re.IGNORECASE,
                                        )
                                        for item in owned
                                    )
                                )
                                has_error = any(
                                    (
                                        _deps.re.search(
                                            "(?:error|fail)",
                                            str(item.get("method_name") or ""),
                                            flags=_deps.re.IGNORECASE,
                                        )
                                        for item in owned
                                    )
                                )
                                if not has_result:
                                    private_callables.append(
                                        {
                                            "method_name": "_on_worker_result",
                                            "signature": "def _on_worker_result(self, result: object) -> None",
                                            "requirement_ids": [requirement_id],
                                            "rationale": "Receive the explicitly requested worker result path.",
                                        }
                                    )
                                if not has_error:
                                    private_callables.append(
                                        {
                                            "method_name": "_on_worker_error",
                                            "signature": "def _on_worker_error(self, error: str) -> None",
                                            "requirement_ids": [requirement_id],
                                            "rationale": "Receive the explicitly requested worker error path.",
                                        }
                                    )
                            needs_background_dispatch = bool(
                                _deps.re.search(
                                    "\\b(?:outside|off)\\s+(?:of\\s+)?(?:the\\s+)?UI\\s+thread\\b|\\bnon[- ]blocking\\b|\\bbackground\\s+(?:worker|thread|task)\\b",
                                    requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            if needs_background_dispatch and (
                                not any(
                                    (
                                        requirement_id
                                        in {
                                            str(value)
                                            for value in private.get(
                                                "requirement_ids", []
                                            )
                                        }
                                        and (
                                            _deps.re.search(
                                                "(?:start|run|execute|dispatch|background)",
                                                str(private.get("method_name") or ""),
                                                flags=_deps.re.IGNORECASE,
                                            )
                                            or (
                                                "worker"
                                                in str(
                                                    private.get("method_name") or ""
                                                ).casefold()
                                                and (
                                                    not _deps.re.search(
                                                        "(?:result|success|finish|complete|error|fail|cleanup|clean_up|release|dispose)",
                                                        str(
                                                            private.get("method_name")
                                                            or ""
                                                        ),
                                                        flags=_deps.re.IGNORECASE,
                                                    )
                                                )
                                            )
                                        )
                                        for private in private_callables
                                    )
                                )
                            ):
                                private_callables.append(
                                    {
                                        "method_name": "_start_background_operation",
                                        "signature": "def _start_background_operation(self) -> None",
                                        "requirement_ids": [requirement_id],
                                        "rationale": "Own the explicitly requested non-blocking dispatch boundary.",
                                    }
                                )
                            if needs_background_dispatch and (
                                not any(
                                    (
                                        requirement_id
                                        in {
                                            str(value)
                                            for value in private.get(
                                                "requirement_ids", []
                                            )
                                        }
                                        and _deps.re.search(
                                            "(?:cleanup|clean_up|release|dispose)",
                                            str(private.get("method_name") or ""),
                                            flags=_deps.re.IGNORECASE,
                                        )
                                        for private in private_callables
                                    )
                                )
                            ):
                                private_callables.append(
                                    {
                                        "method_name": "_cleanup_worker",
                                        "signature": "def _cleanup_worker(self) -> None",
                                        "requirement_ids": [requirement_id],
                                        "rationale": "Own the required worker-finished cleanup path and release the retained worker.",
                                    }
                                )
                        private_callables = [
                            private
                            for private in private_callables
                            if private.get("requirement_ids")
                        ]
                        for private in private_callables:
                            private_name = str(private.get("method_name") or "")
                            if not private_name.startswith("_connect_"):
                                continue
                            private["requirement_ids"] = [
                                requirement_id
                                for requirement_id in private.get("requirement_ids", [])
                                if _deps.re.search(
                                    "\\b(?:connect|wire|bind|attach)\\b",
                                    requirement_text_by_id.get(str(requirement_id), ""),
                                    flags=_deps.re.IGNORECASE,
                                )
                            ]
                        private_callables = [
                            private
                            for private in private_callables
                            if private.get("requirement_ids")
                        ]
                        construction_requirement_ids = {
                            requirement_id
                            for requirement_id, requirement_text in requirement_text_by_id.items()
                            if _deps.re.search(
                                "\\b(?:during|in|from)\\s+construction\\b|\\bconstructor(?:-reachable)?\\b|\\b__init__\\b",
                                requirement_text,
                                flags=_deps.re.IGNORECASE,
                            )
                        }
                        initializer = next(
                            (
                                private
                                for private in private_callables
                                if _deps.re.search(
                                    "(?:^|_)(?:init|initialize|setup|build)(?:_|$).*(?:ui|widget|layout)|(?:^|_)(?:ui|widget|layout)(?:_|$).*(?:init|initialize|setup|build)",
                                    str(private.get("method_name") or ""),
                                    flags=_deps.re.IGNORECASE,
                                )
                            ),
                            None,
                        )
                        if initializer is not None and construction_requirement_ids:
                            retained_private_callables = []
                            for private in private_callables:
                                private_name = str(private.get("method_name") or "")
                                private_ids = {
                                    str(value)
                                    for value in private.get("requirement_ids", [])
                                }
                                if (
                                    private is not initializer
                                    and private_name.startswith("_connect_")
                                    and (private_ids <= construction_requirement_ids)
                                ):
                                    initializer["requirement_ids"] = list(
                                        dict.fromkeys(
                                            [
                                                *initializer.get("requirement_ids", []),
                                                *private.get("requirement_ids", []),
                                            ]
                                        )
                                    )
                                    continue
                                retained_private_callables.append(private)
                            private_callables = retained_private_callables
                        signal_requirement_text = " ".join(
                            requirement_text_by_id.values()
                        )
                        signal_role_handlers: dict[str, dict[str, _deps.Any]] = {}
                        non_signal_role_handlers: list[dict[str, _deps.Any]] = []
                        for private in private_callables:
                            private_name = str(
                                private.get("method_name") or ""
                            ).casefold()
                            role = next(
                                (
                                    candidate_role
                                    for candidate_role in (
                                        "progress",
                                        "error",
                                        "result",
                                    )
                                    if private_name.startswith(("_handle_", "_on_"))
                                    and _deps.re.search(
                                        f"(?:^|_){candidate_role}(?:_|$)", private_name
                                    )
                                ),
                                "",
                            )
                            if not role:
                                non_signal_role_handlers.append(private)
                                continue
                            existing = signal_role_handlers.get(role)
                            signal_specific = "_signal" in private_name
                            prefer_signal_specific = bool(
                                _deps.re.search(
                                    f"\\b{role}\\b[^.!?\\n]{{0,80}}\\bsignals?\\b|\\bsignals?\\b[^.!?\\n]{{0,80}}\\b{role}\\b",
                                    signal_requirement_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                            )
                            if existing is None or (
                                prefer_signal_specific
                                and signal_specific
                                and (
                                    "_signal"
                                    not in str(
                                        existing.get("method_name") or ""
                                    ).casefold()
                                )
                            ):
                                selected = private
                                if existing is not None:
                                    selected["requirement_ids"] = list(
                                        dict.fromkeys(
                                            [
                                                *existing.get("requirement_ids", []),
                                                *selected.get("requirement_ids", []),
                                            ]
                                        )
                                    )
                                signal_role_handlers[role] = selected
                            else:
                                existing["requirement_ids"] = list(
                                    dict.fromkeys(
                                        [
                                            *existing.get("requirement_ids", []),
                                            *private.get("requirement_ids", []),
                                        ]
                                    )
                                )
                        private_callables = [
                            *non_signal_role_handlers,
                            *signal_role_handlers.values(),
                        ]
                    else:
                        explicit_callable_surfaces = list(
                            dict.fromkeys(
                                (
                                    match.group("surface").strip()
                                    for requirement_text in requirement_text_by_id.values()
                                    for match in _deps.re.finditer(
                                        "\\b(?P<surface>[a-z_][A-Za-z0-9_]*\\s*\\(\\s*self\\b[^)]*\\))",
                                        requirement_text,
                                    )
                                )
                            )
                        )
                        if (
                            proposal.get("needs_callable")
                            and len(explicit_callable_surfaces) == 1
                        ):
                            explicit_surface = explicit_callable_surfaces[0]
                            explicit_name = explicit_surface.split("(", 1)[0].strip()
                            if method_name and method_name != explicit_name:
                                proposal["method_name"] = explicit_name
                                proposal["signature"] = (
                                    f"def {explicit_surface} -> object"
                                )
                                proposal["requirement_ids"] = list(
                                    requirement_text_by_id
                                )
                                proposal["rationale"] = (
                                    "Attach all owned behavioral modifiers to the single public callable explicitly declared by the request; do not invent a sibling operation."
                                )
                                method_name = explicit_name
                        if proposal.get("needs_callable") and method_name.startswith(
                            "_"
                        ):
                            public_name = method_name.lstrip("_")
                            proposal["method_name"] = public_name
                            proposal["signature"] = _deps.re.sub(
                                f"^def\\s+{_deps.re.escape(method_name)}\\b",
                                f"def {public_name}",
                                proposal["signature"],
                            )
                        if not proposal.get("needs_callable") and private_callables:
                            promoted = private_callables.pop(0)
                            private_name = str(promoted.get("method_name") or "")
                            public_name = private_name.lstrip("_")
                            proposal["needs_callable"] = True
                            proposal["method_name"] = public_name
                            proposal["signature"] = _deps.re.sub(
                                f"^def\\s+{_deps.re.escape(private_name)}\\b",
                                f"def {public_name}",
                                str(promoted.get("signature") or ""),
                            )
                            proposal["requirement_ids"] = list(
                                promoted.get("requirement_ids") or []
                            )
                            proposal["rationale"] = str(promoted.get("rationale") or "")
                        behavior_text = " ".join(requirement_text_by_id.values())
                        signature = str(proposal.get("signature") or "")
                        if (
                            "progress_callback" in behavior_text
                            and "progress_callback" not in signature
                        ):
                            close_index = signature.rfind(")")
                            if close_index >= 0:
                                separator = (
                                    ""
                                    if signature[:close_index].rstrip().endswith("(")
                                    else ", "
                                )
                                signature = (
                                    signature[:close_index]
                                    + separator
                                    + "progress_callback: Callable[[int, int, str], None] | None = None"
                                    + signature[close_index:]
                                )
                        elif "progress_callback" in behavior_text and _deps.re.search(
                            "\\bprogress_callback\\s*=\\s*None\\b", signature
                        ):
                            signature = _deps.re.sub(
                                "\\bprogress_callback\\s*=\\s*None\\b",
                                "progress_callback: Callable[[int, int, str], None] | None = None",
                                signature,
                            )
                        if _deps.re.search(
                            "\\breturns?\\b", behavior_text, flags=_deps.re.IGNORECASE
                        ) and (
                            "->" not in signature
                            or _deps.re.search("->\\s*None\\s*$", signature)
                        ):
                            if _deps.re.search(
                                "\\bstructured\\b[^.!?\\n]{0,60}\\brecords?\\b|\\brecords?\\b[^.!?\\n]{0,60}\\bstructured\\b",
                                behavior_text,
                                flags=_deps.re.IGNORECASE,
                            ):
                                return_annotation = "list[dict[str, object]]"
                            elif _deps.re.search(
                                "\\b(?:records?|items?|entries|list)\\b",
                                behavior_text,
                                flags=_deps.re.IGNORECASE,
                            ):
                                return_annotation = "list[object]"
                            elif _deps.re.search(
                                "\\b(?:mapping|dictionary|dict)\\b",
                                behavior_text,
                                flags=_deps.re.IGNORECASE,
                            ):
                                return_annotation = "dict[str, object]"
                            else:
                                return_annotation = "object"
                            if "->" in signature:
                                signature = _deps.re.sub(
                                    "->\\s*None\\s*$",
                                    f"-> {return_annotation}",
                                    signature,
                                )
                            else:
                                signature += f" -> {return_annotation}"
                        proposal["signature"] = signature
                        private_callables = []
                    proposal["private_callables"] = private_callables
                return normalized

            self.normalize_declaration_payload = normalize_declaration_payload
            self.declaration_payload = self.normalize_declaration_payload(
                self.declaration_payload
            )

            def declaration_protocol_errors(
                payload: _deps.Mapping[str, _deps.Any],
            ) -> list[str]:
                errors: list[str] = []
                returned = {
                    str(item.get("owner") or ""): item
                    for item in payload.get("owners") or []
                    if isinstance(item, _deps.Mapping)
                }
                for owner, allowed in self.allowed_rows.items():
                    proposal = returned.get(owner)
                    if proposal is None:
                        errors.append(f"{owner}: missing declaration decision")
                        continue
                    requirement_text_by_id = {
                        str(item.get("id") or ""): str(item.get("text") or "")
                        for item in allowed["requirements"]
                    }
                    is_ui_owner = bool(
                        owner.endswith(("Dialog", "Window", "Widget", "Panel", "Dock"))
                        or any(
                            (
                                _deps.re.search(
                                    "\\b(?:Qt|UI|dialog|widget|window)\\b",
                                    text,
                                    flags=_deps.re.IGNORECASE,
                                )
                                for text in requirement_text_by_id.values()
                            )
                        )
                    )
                    method_name = str(proposal.get("method_name") or "").strip()
                    signature = str(proposal.get("signature") or "").strip()
                    if is_ui_owner and proposal.get("needs_callable"):
                        errors.append(
                            f"{owner}: construction/event behavior must use private handlers, not a new public callable"
                        )
                    if not is_ui_owner:
                        if not proposal.get("needs_callable"):
                            errors.append(
                                f"{owner}: executable behavior has no public operation"
                            )
                        elif not _deps.re.fullmatch("[a-z][A-Za-z0-9_]*", method_name):
                            errors.append(
                                f"{owner}: public method `{method_name}` must not start with an underscore"
                            )
                        elif not _deps.re.match(
                            f"def\\s+{_deps.re.escape(method_name)}\\s*\\(\\s*self\\b",
                            signature,
                        ):
                            errors.append(
                                f"{owner}: signature does not declare `{method_name}`"
                            )
                        if _deps.re.search(":\\s*(?:pass|\\.\\.\\.)\\s*$", signature):
                            errors.append(
                                f"{owner}: signature contains a callable body"
                            )
                        behavior_text = " ".join(requirement_text_by_id.values())
                        if (
                            "progress_callback" in behavior_text
                            and "progress_callback" not in signature
                        ):
                            errors.append(
                                f"{owner}: signature omits required progress_callback"
                            )
                        if _deps.re.search(
                            "\\breturns?\\b", behavior_text, _deps.re.IGNORECASE
                        ) and (
                            "->" not in signature
                            or _deps.re.search("->\\s*None\\s*$", signature)
                        ):
                            errors.append(
                                f"{owner}: signature omits the requested return contract"
                            )
                    private_callables = [
                        item
                        for item in proposal.get("private_callables") or []
                        if isinstance(item, _deps.Mapping)
                    ]
                    for private in private_callables:
                        private_name = str(private.get("method_name") or "").strip()
                        private_signature = str(private.get("signature") or "").strip()
                        private_ids = {
                            str(value)
                            for value in private.get("requirement_ids") or []
                            if str(value)
                        }
                        if not _deps.re.fullmatch("_[a-z][A-Za-z0-9_]*", private_name):
                            errors.append(
                                f"{owner}: private handler `{private_name}` must start with one underscore"
                            )
                        if not _deps.re.match(
                            f"def\\s+{_deps.re.escape(private_name)}\\s*\\(\\s*self\\b",
                            private_signature,
                        ):
                            errors.append(
                                f"{owner}: private signature does not declare `{private_name}`"
                            )
                        if _deps.re.search(
                            ":\\s*(?:pass|\\.\\.\\.)\\s*$", private_signature
                        ):
                            errors.append(
                                f"{owner}.{private_name}: signature contains a body"
                            )
                        if not private_ids.issubset(set(allowed["requirement_ids"])):
                            errors.append(
                                f"{owner}.{private_name}: owns non-behavioral or foreign requirement IDs"
                            )
                    for (
                        requirement_id,
                        requirement_text,
                    ) in requirement_text_by_id.items():
                        required_handler_count = 0
                        if _deps.re.search(
                            "\\bconnect\\b|\\bclicked\\b|\\btriggered\\b",
                            requirement_text,
                            flags=_deps.re.IGNORECASE,
                        ):
                            required_handler_count = max(required_handler_count, 1)
                        if _deps.re.search(
                            "\\b(?:result|completion|success)\\b",
                            requirement_text,
                            flags=_deps.re.IGNORECASE,
                        ) and _deps.re.search(
                            "\\b(?:error|failure)\\b",
                            requirement_text,
                            flags=_deps.re.IGNORECASE,
                        ):
                            required_handler_count = max(required_handler_count, 2)
                        owned_handlers = sum(
                            (
                                requirement_id
                                in {
                                    str(value)
                                    for value in private.get("requirement_ids") or []
                                }
                                for private in private_callables
                            )
                        )
                        if owned_handlers < required_handler_count:
                            errors.append(
                                f"{owner}: requirement {requirement_id} needs {required_handler_count} private handler(s), got {owned_handlers}"
                            )
                return list(dict.fromkeys(errors))

            self.declaration_protocol_errors = declaration_protocol_errors
            self.declaration_errors = self.declaration_protocol_errors(
                self.declaration_payload
            )
            if self.declaration_errors:
                if self.status_callback:
                    self.status_callback(
                        "Refining callable ownership before chunk planning: "
                        + " | ".join(self.declaration_errors)
                    )
                self.declaration_response, self.retry_timing = _deps._query_stage(
                    self.declaration_stage,
                    selected_model=self.selected_model,
                    settings=self.settings,
                    timeout=self.timeout,
                    suffix="\n\nREJECTED DECLARATION DECISION:\n"
                    + " | ".join(self.declaration_errors)
                    + "\nReturn a corrected replacement for every owner. Signatures are declarations only and must never contain `pass`, ellipses, or a body.",
                )
                self.retry_timing["strategy_attempt"] = 2
                self.timings.append(self.retry_timing)
                try:
                    self.declaration_payload = _deps.json.loads(
                        self.declaration_response
                    )
                except (TypeError, ValueError, _deps.json.JSONDecodeError):
                    self.declaration_payload = {}
                self.declaration_payload = self.normalize_declaration_payload(
                    self.declaration_payload
                )
                self.declaration_errors = self.declaration_protocol_errors(
                    self.declaration_payload
                )
                if self.declaration_errors:
                    self.declaration_payload = {}
                    if self.status_callback:
                        self.status_callback(
                            "Callable ownership remains invalid; refusing to enrich the plan: "
                            + " | ".join(self.declaration_errors)
                        )
            self.proposals_by_owner = {
                str(item.get("owner") or ""): item
                for item in self.declaration_payload.get("owners") or []
                if isinstance(item, _deps.Mapping)
            }
            for self.manifest_item in self.manifest:
                if not isinstance(self.manifest_item, dict):
                    continue
                for self.symbol in self.manifest_item.get("public_symbols") or []:
                    if not isinstance(self.symbol, dict):
                        continue
                    self.owner = str(
                        self.symbol.get("qualified_name")
                        or self.symbol.get("name")
                        or self.symbol.get("owner")
                        or ""
                    )
                    self.proposal = self.proposals_by_owner.get(self.owner)
                    self.allowed = self.allowed_rows.get(self.owner)
                    if not self.proposal or not self.allowed:
                        continue
                    if self.proposal.get("needs_callable"):
                        self.method_name = str(
                            self.proposal.get("method_name") or ""
                        ).strip()
                        self.signature = str(
                            self.proposal.get("signature") or ""
                        ).strip()
                        self.approved_ids = {
                            str(value)
                            for value in self.proposal.get("requirement_ids") or []
                            if str(value)
                        }
                        if (
                            _deps.re.fullmatch("[a-z_][A-Za-z0-9_]*", self.method_name)
                            and _deps.re.match(
                                f"def\\s+{_deps.re.escape(self.method_name)}\\s*\\(\\s*self\\b",
                                self.signature,
                            )
                            and self.approved_ids
                            and self.approved_ids.issubset(
                                set(self.allowed["requirement_ids"])
                            )
                        ):
                            self.symbol["inferred_callable_signatures"] = [
                                self.signature
                            ]
                            self.symbol["inferred_callable_proposals"] = [
                                {
                                    "method_name": self.method_name,
                                    "signature": self.signature,
                                    "requirement_ids": sorted(self.approved_ids),
                                    "rationale": str(
                                        self.proposal.get("rationale") or ""
                                    ).strip(),
                                    "source": "focused_declaration_reasoning",
                                    "approval_required": True,
                                }
                            ]
                    self.private_proposals: list[dict[str, _deps.Any]] = []
                    for self.private in self.proposal.get("private_callables") or []:
                        if not isinstance(self.private, _deps.Mapping):
                            continue
                        self.private_name = str(
                            self.private.get("method_name") or ""
                        ).strip()
                        self.private_signature = str(
                            self.private.get("signature") or ""
                        ).strip()
                        self.private_ids = {
                            str(value)
                            for value in self.private.get("requirement_ids") or []
                            if str(value)
                        }
                        if (
                            not _deps.re.fullmatch(
                                "_[a-z_][A-Za-z0-9_]*", self.private_name
                            )
                            or not _deps.re.match(
                                f"def\\s+{_deps.re.escape(self.private_name)}\\s*\\(\\s*self\\b",
                                self.private_signature,
                            )
                            or (not self.private_ids)
                            or (
                                not self.private_ids.issubset(
                                    set(self.allowed["requirement_ids"])
                                )
                            )
                        ):
                            continue
                        self.private_proposals.append(
                            {
                                "method_name": self.private_name,
                                "signature": self.private_signature,
                                "requirement_ids": sorted(self.private_ids),
                                "rationale": str(
                                    self.private.get("rationale") or ""
                                ).strip(),
                                "source": "focused_declaration_reasoning",
                                "approval_required": True,
                            }
                        )
                    if self.private_proposals:
                        self.symbol["inferred_private_callable_signatures"] = [
                            item["signature"] for item in self.private_proposals
                        ]
                        self.symbol["inferred_private_callable_proposals"] = (
                            self.private_proposals
                        )
        self.artifact_file_stages = list(
            _deps.build_project_edit_artifact_file_stages(self.plan, self.manifest)
        )
        self.chunk_generated_by_path: dict[str, str] = {}
        if self.early_cached_approval:
            self.chunk_plan = [
                dict(item) for item in self.early_cached_approval.get("assignments", [])
            ]
            self.unresolved_requirements = []
        else:
            self.chunk_plan, self.unresolved_requirements = (
                _deps.build_deterministic_project_edit_chunk_plan(
                    self.manifest, self.requirement_ledger
                )
            )
            self.section_assignments, self.unresolved_requirements = (
                _deps._resolve_structurally_sectioned_module_requirements(
                    self.manifest, self.requirement_ledger, self.unresolved_requirements
                )
            )
            self.section_requirement_ids = {
                str(item.get("requirement_id") or "")
                for item in self.section_assignments
            }
            self.chunk_plan = [
                item
                for item in self.chunk_plan
                if str(item.get("requirement_id") or "")
                not in self.section_requirement_ids
            ]
            self.chunk_plan.extend(self.section_assignments)
            self.requirement_by_id = {
                str(item.get("id") or item.get("requirement_id") or ""): item
                for item in self.requirement_ledger
                if isinstance(item, _deps.Mapping)
            }
            for self.assignment in self.chunk_plan:
                self.requirement_text = str(
                    self.requirement_by_id.get(
                        str(self.assignment.get("requirement_id") or ""), {}
                    ).get("text")
                    or ""
                )
                if _deps.re.search(
                    "^\\s*(?:create|add|build|generate|write)\\b[^.!?\\n]{0,140}\\b(?:package|files?)\\b",
                    self.requirement_text,
                    flags=_deps.re.IGNORECASE,
                ):
                    self.assignment["semantic_role"] = "structure"
                elif _deps.re.search(
                    "^\\s*(?:fix|edit|modify|update)\\s+[^.!?\\n]*\\.py\\s*$",
                    self.requirement_text,
                    flags=_deps.re.IGNORECASE,
                ):
                    self.assignment["semantic_role"] = "structure"
                elif _deps.re.search(
                    r"\bimports?\b",
                    self.requirement_text,
                    flags=_deps.re.IGNORECASE,
                ):
                    self.assignment["semantic_role"] = "import"
                elif _is_project_edit_quality_requirement(self.requirement_text):
                    self.assignment["semantic_role"] = "quality"
            self.module_owned_behavior_ids = {
                str(item.get("requirement_id") or "")
                for item in self.chunk_plan
                if (
                    not list(item.get("declaration_ids") or [])
                    or all(
                        (
                            str(declaration_id).endswith("_MODULE")
                            for declaration_id in item.get("declaration_ids") or []
                        )
                    )
                )
                and str(
                    item.get("semantic_role")
                    or self.requirement_by_id.get(
                        str(item.get("requirement_id") or ""), {}
                    ).get("semantic_role")
                    or "behavior"
                ).casefold()
                not in {
                    "constant",
                    "entry_point",
                    "export",
                    "import",
                    "module_wiring",
                    "package_wiring",
                    "structure",
                }
            }
            if self.module_owned_behavior_ids:
                self.chunk_plan = [
                    item
                    for item in self.chunk_plan
                    if str(item.get("requirement_id") or "")
                    not in self.module_owned_behavior_ids
                ]
                self.unresolved_ids = {
                    str(item.get("id") or item.get("requirement_id") or "")
                    for item in self.unresolved_requirements
                    if isinstance(item, _deps.Mapping)
                }
                self.unresolved_requirements.extend(
                    (
                        dict(self.requirement_by_id[requirement_id])
                        for requirement_id in sorted(self.module_owned_behavior_ids)
                        if requirement_id in self.requirement_by_id
                        and requirement_id not in self.unresolved_ids
                    )
                )
                if self.status_callback:
                    self.status_callback(
                        "Escalating executable module-only requirements to declaration reasoning: "
                        + ", ".join(sorted(self.module_owned_behavior_ids))
                    )
            self.already_planned_requirement_ids = {
                str(item.get("requirement_id") or "")
                for item in self.chunk_plan
                if item.get("declaration_ids")
            }
            self.unresolved_requirements = [
                item
                for item in self.unresolved_requirements
                if str(item.get("id") or item.get("requirement_id") or "")
                not in self.already_planned_requirement_ids
            ]
        self.chunk_plan_stage = _deps.build_project_edit_chunk_plan_stage(
            self.plan,
            self.manifest,
            self.unresolved_requirements[:1] or self.requirement_ledger,
            grounding_packet=self.preplan_grounding,
        )
        self.requirement_by_id = {
            str(item.get("id") or item.get("requirement_id") or ""): item
            for item in self.requirement_ledger
            if isinstance(item, _deps.Mapping)
        }
        self.declaration_rows = [
            dict(item)
            for item in (self.chunk_plan_stage.metadata or {}).get("declarations", [])
            if isinstance(item, _deps.Mapping)
            and str(item.get("declaration_id") or "")
            and (not str(item.get("declaration_id") or "").endswith("_MODULE"))
        ]
        for self.assignment in self.chunk_plan:
            self.requirement_id = str(self.assignment.get("requirement_id") or "")
            self.requirement = self.requirement_by_id.get(self.requirement_id, {})
            self.requirement_text = str(self.requirement.get("text") or "")
            if str(self.assignment.get("semantic_role") or "").casefold() != "quality":
                continue
            self.explicitly_named = [
                row
                for row in self.declaration_rows
                if str(row.get("owner") or "")
                and _deps.re.search(
                    f"(?<![.\\w]){_deps.re.escape(str(row.get('owner') or ''))}(?![.\\w])",
                    self.requirement_text,
                )
                or (
                    str(row.get("path") or "")
                    and _deps.Path(str(row.get("path") or "")).name.casefold()
                    in self.requirement_text.casefold()
                )
            ]
            self.quality_owners = self.explicitly_named or self.declaration_rows
            self.assignment["declaration_ids"] = list(
                dict.fromkeys(
                    (
                        str(row.get("declaration_id") or "")
                        for row in self.quality_owners
                    )
                )
            )
            if self.status_callback and len(self.quality_owners) > 1:
                self.status_callback(
                    f"Applying unscoped quality requirement {self.requirement_id} to all {len(self.quality_owners)} approved production declarations."
                )
        self.chunk_plan_errors: list[str] = []
        if self.status_callback:
            self.status_callback(
                "Requirement ledger: "
                + "; ".join(
                    (
                        f"{item.get('id') or item.get('requirement_id')}={str(item.get('text') or item.get('requirement') or '')[:180]}"
                        for item in self.requirement_ledger
                    )
                )
            )
            self.status_callback(
                "Owner candidates: "
                + "; ".join(
                    (
                        f"{item.get('declaration_id')}={_deps.Path(str(item.get('path') or '')).name}:{item.get('owner')}"
                        for item in (self.chunk_plan_stage.metadata or {}).get(
                            "declarations", []
                        )
                    )
                )
            )
        self.unresolved_plan_failures: list[str] = []
        for self.unresolved_index, self.unresolved_requirement in enumerate(
            self.unresolved_requirements, start=1
        ):
            self.requirement_stage = _deps.build_project_edit_chunk_plan_stage(
                self.plan,
                self.manifest,
                [self.unresolved_requirement],
                grounding_packet=self.preplan_grounding,
            )
            self.requirement_id = str(
                self.unresolved_requirement.get("id")
                or self.unresolved_requirement.get("requirement_id")
                or ""
            )
            self.requirement_feedback = ""
            self.resolved_assignment: list[dict[str, _deps.Any]] = []
            self.allowed_declarations = [
                dict(item)
                for item in (self.requirement_stage.metadata or {}).get(
                    "declarations", []
                )
                if isinstance(item, _deps.Mapping)
                and str(item.get("declaration_id") or "")
            ]
            self.prior_failure_fingerprints: set[str] = set()
            for self.chunk_plan_attempt in range(1, 4):
                if self.status_callback:
                    self.strategy_reason = (
                        "initial semantic ownership decision"
                        if self.chunk_plan_attempt == 1
                        else (
                            "retrying with parser findings and the exact approved declaration IDs"
                            if self.chunk_plan_attempt == 2
                            else "escalating the same requirement to the strongest configured local ownership reasoner"
                        )
                    )
                    self.status_callback(
                        f"Resolving ambiguous requirement {self.requirement_id} ({self.unresolved_index}/{len(self.unresolved_requirements)}), strategy {self.chunk_plan_attempt}: {self.strategy_reason}"
                    )
                self.chunk_plan_response, self.chunk_plan_timing = _deps._query_stage(
                    self.requirement_stage,
                    selected_model=_deps._focused_repair_model(
                        self.selected_model, self.chunk_plan_attempt
                    ),
                    settings=self.settings,
                    timeout=self.timeout,
                    suffix=self.requirement_feedback,
                )
                self.resolved_assignment, self.requirement_errors = (
                    _deps.parse_project_edit_chunk_plan(
                        self.chunk_plan_response, stage=self.requirement_stage
                    )
                )
                self.chunk_plan_timing.update(
                    {
                        "attempt": self.chunk_plan_attempt,
                        "owner": self.requirement_id,
                        "failure_fingerprint": _deps._checkpoint_hash(
                            self.requirement_errors
                        ),
                    }
                )
                self.timings.append(self.chunk_plan_timing)
                if not self.requirement_errors:
                    self.chunk_plan.extend(self.resolved_assignment)
                    break
                self.failure_fingerprint = _deps._checkpoint_hash(
                    self.requirement_errors
                )
                if (
                    self.failure_fingerprint in self.prior_failure_fingerprints
                    and self.status_callback
                ):
                    self.status_callback(
                        f"Ownership failure for {self.requirement_id} repeated unchanged; discarding the equivalent retry path and changing strategy"
                    )
                self.prior_failure_fingerprints.add(self.failure_fingerprint)
                if len(self.allowed_declarations) == 1:
                    self.sole_owner = self.allowed_declarations[0]
                    self.resolved_assignment = [
                        {
                            "requirement_id": self.requirement_id,
                            "semantic_role": str(
                                self.unresolved_requirement.get("semantic_role")
                                or "behavior"
                            ),
                            "declaration_ids": [
                                str(self.sole_owner.get("declaration_id") or "")
                            ],
                            "depends_on": [],
                            "reason": "deterministic unique-owner recovery after the model returned an owner outside the approved manifest",
                        }
                    ]
                    self.chunk_plan.extend(self.resolved_assignment)
                    if self.status_callback:
                        self.status_callback(
                            f"Recovered {self.requirement_id} without inventing a target: the approved manifest contains exactly one declaration, {self.sole_owner.get('declaration_id')}={_deps.Path(str(self.sole_owner.get('path') or '')).name}:{self.sole_owner.get('owner') or '<module>'}"
                        )
                    break
                if self.status_callback:
                    self.status_callback(
                        f"Rejected ownership for {self.requirement_id} because it violated the approved manifest: "
                        + " | ".join(self.requirement_errors[:4])
                    )
                self.requirement_feedback = (
                    "\n\nResolve this one requirement only. The prior decision failed:\n- "
                    + "\n- ".join(self.requirement_errors[:6])
                    + "\nUse only these exact declaration IDs: "
                    + ", ".join(
                        (
                            str(item.get("declaration_id") or "")
                            for item in self.allowed_declarations
                        )
                    )
                    + ". Do not copy an example ID or create a new ID."
                )
            else:
                self.unresolved_plan_failures.append(
                    f"{self.requirement_id}: " + " | ".join(self.requirement_errors[:4])
                )
        self.required_ids = {
            str(item.get("id") or item.get("requirement_id") or "")
            for item in self.requirement_ledger
        }
        self.planned_ids = {
            str(item.get("requirement_id") or "") for item in self.chunk_plan
        }
        self.missing_plan_ids = sorted(self.required_ids - self.planned_ids)
        if self.unresolved_plan_failures or self.missing_plan_ids:
            self.chunk_plan_errors = list(self.unresolved_plan_failures)
            if self.missing_plan_ids:
                self.chunk_plan_errors.append(
                    "Implementation plan omitted requirement IDs: "
                    + ", ".join(self.missing_plan_ids)
                )
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="plan_resolution_failed",
                    errors=self.chunk_plan_errors,
                    timings=self.timings,
                )
            )
        if self.status_callback and self.chunk_plan:
            self.declaration_names = {
                str(
                    item.get("declaration_id") or ""
                ): f"{_deps.Path(str(item.get('path') or '')).name}:{item.get('owner') or '<module>'}"
                for item in (self.chunk_plan_stage.metadata or {}).get(
                    "declarations", []
                )
            }
            self.status_callback(
                f"Accepted chunk ownership plan ({len(self.chunk_plan) - len(self.unresolved_requirements)} deterministic, {len(self.unresolved_requirements)} reasoned): "
                + "; ".join(
                    (
                        f"{assignment['requirement_id']}->"
                        + ",".join(
                            (
                                self.declaration_names.get(owner, owner)
                                for owner in assignment.get("declaration_ids") or []
                            )
                        )
                        for assignment in self.chunk_plan
                    )
                )
            )
        if self.early_cached_approval:
            self.implementation_plan = dict(
                self.early_cached_approval["implementation_plan"]
            )
            self.manifest = [
                dict(item) for item in self.early_cached_approval.get("manifest", [])
            ]
            self.requirement_ledger = [
                dict(item)
                for item in self.early_cached_approval.get("requirement_ledger", [])
            ]
            self.chunk_plan = [
                dict(item) for item in self.early_cached_approval.get("assignments", [])
            ]
        else:
            self.implementation_plan = _deps.build_user_visible_implementation_plan(
                self.manifest,
                self.requirement_ledger,
                self.chunk_plan,
                plan=self.plan,
                grounding_packet=self.preplan_grounding,
            )
        self.evidence_started = _deps.time.perf_counter()
        self.unresolved_plan_evidence: list[str] = []
        self.planned_owner_names = {
            str(chunk.get("owner") or "").rsplit(".", 1)[-1]
            for chunk in self.implementation_plan.get("chunks") or []
            if str(chunk.get("owner") or "") != "<module>"
        }
        self.method_contract_errors: list[str] = []
        self.internal_adapter_evidence_required = bool(
            _deps.re.search(
                "\\b(?:internal|existing|project|our)\\s+(?:[A-Za-z0-9_.+-]+\\s+){0,6}(?:adapter|bridge|capability|function|method|api|tool|service)s?\\b|\\b(?:internal|existing|project|our)\\b[^.!?\\n]{0,120}\\b(?:[A-Z][A-Za-z0-9_]*?(?:Adapter|Bridge)|capability|function|method|api|tool|service)\\b|\\bthrough\\s+(?:the\\s+)?(?:internal|existing|project)\\s+(?:[A-Za-z0-9_.+-]+\\s+){0,4}(?:adapter|bridge)\\b|\\bour\\b[^,.;]{0,80}\\b(?:function|method|api|tool|service)\\b|\\b(?:without|rather\\s+than|instead\\s+of)\\s+importing\\s+(?:maya\\.cmds|unreal|bpy|pyfbsdk)\\b",
                self.user_prompt,
                flags=_deps.re.IGNORECASE,
            )
        )
        self.evidence_project_root = (
            _deps.Path(__file__).resolve().parents[2]
            if self.internal_adapter_evidence_required
            else self.root
        )
        if self.status_callback:
            self.status_callback(
                f"Evidence scope: {self.evidence_project_root} (internal_adapter_contract={self.internal_adapter_evidence_required})"
            )

        def _evidence_strength_rank(
            item: _deps.Mapping[str, _deps.Any],
        ) -> tuple[int, str]:
            if bool(item.get("selected_for_generation")):
                priority = 0
            elif bool(item.get("dependency_for_selected")):
                priority = 1
            elif bool(item.get("authoritative_signature")):
                priority = 2
            elif str(item.get("provider") or "") == "official_public_api_research":
                priority = 3
            elif str(item.get("confidence") or "") == "exact":
                priority = 4
            elif "usage" in str(item.get("provider") or ""):
                priority = 6
            else:
                priority = 5
            return (
                priority,
                str(item.get("qualified_name") or item.get("name") or "").casefold(),
            )

        self._evidence_strength_rank = _evidence_strength_rank

        self.explicit_delegation_spec = (
            _deps._explicit_cross_file_delegation_spec(self.user_prompt)
        )

        def _requires_callable_evidence(text: str) -> bool:
            lowered_text = text.casefold()
            if self.explicit_delegation_spec is not None:
                return False
            if _deps.re.search(
                "\\b[A-Z][A-Za-z0-9_]*\\s+must\\s+(?:expose|define|implement|provide)\\s+[a-z_][A-Za-z0-9_]*\\s*\\(",
                text,
            ):
                return False
            if _deps.re.match(
                r"^\s*(?:in\s+\S+\s+)?imports?\b",
                text,
                flags=_deps.re.IGNORECASE,
            ):
                return False
            qualified_call_roots = {
                root.casefold()
                for root in _deps.re.findall(
                    r"\b([A-Za-z_][A-Za-z0-9_]*)"
                    r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+\s*\(",
                    text,
                )
            }
            standard_or_local_roots = {
                "ast",
                "collections",
                "dataclasses",
                "datetime",
                "functools",
                "itertools",
                "json",
                "math",
                "os",
                "pathlib",
                "re",
                "sys",
                "time",
                "typing",
            }
            standard_or_local_roots.update(
                str(item.get("owner") or "").rsplit(".", 1)[-1].casefold()
                for item in (self.chunk_plan_stage.metadata or {}).get(
                    "declarations", []
                )
                if isinstance(item, _deps.Mapping)
                and str(item.get("owner") or "") not in {"", "<module>"}
            )
            explicit_external_surface = bool(
                _deps.re.search(
                    r"\b(?:API|adapter|bridge|transport|worker|thread|callback|"
                    r"signal|unreal|maya|blender|motionbuilder|bpy|pyfbsdk|"
                    r"PySide|PyQt|Qt|import|export)\b",
                    text,
                    flags=_deps.re.IGNORECASE,
                )
            )
            if (
                qualified_call_roots
                and qualified_call_roots <= standard_or_local_roots
                and not explicit_external_surface
            ):
                return False
            return bool(
                _deps.re.search(
                    "\\b(?:API|adapter|bridge|transport|worker|thread|callback|signal|unreal|maya|blender|motionbuilder|bpy|pyfbsdk|PySide|PyQt|Qt|import|export)\\b",
                    text,
                    flags=_deps.re.IGNORECASE,
                )
                or _deps.re.search(
                    "\\b(?:through|via|using)\\b[^.!?\\n]{0,100}\\b(?:client|dependency|factory|library|manager|module|package)\\b",
                    text,
                    flags=_deps.re.IGNORECASE,
                )
                or _deps.re.search(
                    "\\b[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)+\\s*\\(",
                    text,
                )
            )

        self._requires_callable_evidence = _requires_callable_evidence

        def _complete_callable_evidence(item: _deps.Mapping[str, _deps.Any]) -> bool:
            """Reject truncated callable signatures before planning can select them."""
            if str(item.get("access_kind") or "").casefold() == "property":
                return bool(str(item.get("signature") or "").strip())
            if str(item.get("kind") or "").casefold() in {"class", "module"}:
                return bool(str(item.get("signature") or "").strip())
            signature = " ".join(str(item.get("signature") or "").split())
            if signature.startswith("def "):
                signature = signature[4:]
            opening = signature.find("(")
            if opening <= 0:
                return False
            depth = 0
            closing = -1
            for index, character in enumerate(signature[opening:], start=opening):
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closing = index
                        break
                if depth < 0:
                    return False
            if closing < 0 or depth != 0:
                return False
            suffix = signature[closing + 1 :].strip().rstrip(":").strip()
            return not suffix or suffix.startswith("->")

        self._complete_callable_evidence = _complete_callable_evidence
        self.indexed_requested_base_records = (
            _deps._indexed_requested_base_owner_records(self.user_prompt, self.root)
        )
