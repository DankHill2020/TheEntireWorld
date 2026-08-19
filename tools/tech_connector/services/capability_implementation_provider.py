"""Grounded model-backed implementation for capability-acquisition jobs."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import re
from typing import Any, Callable

from tech_connector.services.capability_acquisition_coordinator import AcquisitionJob


ModelQuery = Callable[..., str]


class ModelBackedCapabilityImplementationProvider:
    """Generate, disposable-test, apply, and verify one missing operation."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        active_path: str = "",
        settings: dict[str, Any] | None = None,
        model_query: ModelQuery | None = None,
        plan_builder: Callable[..., Any] | None = None,
        stage_builder: Callable[[Any], list[Any]] | None = None,
        previewer: Callable[..., Any] | None = None,
        applier: Callable[..., Any] | None = None,
        temp_validator: Callable[..., dict[str, Any]] | None = None,
        operation_validator: Callable[[str], dict[str, Any]] | None = None,
        live_operation_validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        route_classifier: Callable[..., Any] | None = None,
        alignment_verifier: Callable[..., dict[str, Any]] | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.active_path = str(active_path or "")
        self.settings = dict(settings or {})
        self._model_query = model_query or self._default_model_query
        self._plan_builder = plan_builder
        self._stage_builder = stage_builder
        self._previewer = previewer
        self._applier = applier
        self._temp_validator = temp_validator
        self._operation_validator = operation_validator
        self._live_operation_validator = live_operation_validator
        self._route_classifier = route_classifier
        self._alignment_verifier = alignment_verifier
        self._progress_callback = progress_callback
        self._state: dict[str, Any] = {}

    def _emit_progress(self, phase: str, **payload: Any) -> None:
        if not self._progress_callback:
            return
        try:
            self._progress_callback(phase, {"phase": phase, **payload})
        except Exception:
            pass

    def run_stage(self, step: dict[str, Any], job: AcquisitionJob) -> dict[str, Any]:
        action = str(step.get("action") or "").lower()
        step_id = str(step.get("step_id") or "")
        if step_id == "confirm_capability_gap" or action == "resolve":
            return self._confirm_gap(job)
        if step_id == "research_host_api" or action == "search":
            return self._research(job)
        if step_id == "design_dcc_adapter" or action == "plan":
            return self._design(job)
        if step_id == "implement_dcc_adapter" or action == "modify":
            return self._implement(job)
        if step_id == "validate_dcc_adapter" or action == "validate":
            return self._validate(job)
        if step_id == "replan_original_request" or action == "replan":
            return self._replan(job)
        return {"ok": False, "error": f"Unsupported acquisition stage: {step_id or action}"}

    def _objective(self, job: AcquisitionJob) -> str:
        gap = self._gap_operation(job)
        resume = str(job.plan.get("resume_operation") or "")
        additions = "\n".join(f"- {item}" for item in job.context_addenda)
        objective = (
            f"Implement and register the real callable `{gap}` needed to resume `{resume}`.\n"
            f"Original request:\n{job.original_request}\n"
            "Do not add a registry-only or placeholder implementation. Reuse an existing Python/API path when it is sufficient; "
            "use the Unreal C++ bridge only when reflected Python cannot satisfy the contract. Add focused tests and readback proof. "
            "Approval grants bounded authority to repair every failed quality gate by modifying or creating evidence-backed owner, "
            "registry, adapter, plugin, and focused-test files inside the project root. Do not wait for separate approval for each repair; "
            "unrelated files and validator weakening are outside the approved scope."
            + (f"\nAdditional user context:\n{additions}" if additions else "")
        )
        contract = dict(job.plan.get("requested_behavior_contract") or {})
        if contract:
            objective += (
                "\nThe following deterministic behavior contract is mandatory and must be proven by code plus tests:\n"
                + json.dumps(contract, indent=2, default=str)
            )
        return objective

    @staticmethod
    def _gap_operation(job: AcquisitionJob) -> str:
        return str(job.plan.get("requested_operation") or "").strip()

    def _confirm_gap(self, job: AcquisitionJob) -> dict[str, Any]:
        status = self._validate_operation(self._gap_operation(job))
        if status.get("callable_found"):
            self._state["already_available"] = True
            return {"ok": True, "evidence": [status], "already_available": True}
        return {
            "ok": True,
            "evidence": [status],
            "message": status.get("reason") or "The requested operation is not callable yet.",
        }

    def _research(self, job: AcquisitionJob) -> dict[str, Any]:
        plan = self._build_plan(self._objective(job), job)
        self._state["edit_plan"] = plan
        self._state["context_revision"] = len(job.context_addenda)
        self._state["required_implementation_layer"] = self._infer_implementation_layer(job)
        self._state["host_api_evidence"] = self._unreal_host_api_evidence(job)
        discovery = dict(getattr(plan, "discovery", {}) or {})
        candidates = list(discovery.get("candidates") or discovery.get("targets") or [])
        best = dict(discovery.get("best_target") or {})
        if not best and not candidates:
            return {"ok": False, "error": "Target discovery found no evidence-backed implementation location."}
        return {
            "ok": True,
            "evidence": {
                "best_target": best,
                "candidate_count": len(candidates),
                "project_roots": list(discovery.get("project_roots") or []),
                "required_implementation_layer": self._state["required_implementation_layer"],
                "host_api_evidence_files": list(self._state.get("host_api_evidence_files") or []),
            },
        }

    def _infer_implementation_layer(self, job: AcquisitionJob) -> str:
        contract = dict(job.plan.get("requested_behavior_contract") or {})
        explicit = str(contract.get("required_implementation_layer") or "").strip()
        if explicit:
            return explicit
        if str(job.plan.get("host") or "").lower() != "unreal":
            return "python_or_registered_host_api"
        wrapper_contract = self._canonical_cpp_wrapper_contract(job)
        if wrapper_contract:
            self._state["cpp_wrapper_contract"] = wrapper_contract
            return "reflected_cpp_bridge"
        namespace = self._gap_operation(job).partition(".")[0]
        for path in self._owner_paths(job):
            if path.name != f"{namespace}.py":
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"requires_[a-z0-9_]+_(?:strategy|body)", source):
                return "reflected_cpp_bridge"
        return "python_or_reflected_cpp_bridge"

    def _ensure_current_plan(self, job: AcquisitionJob) -> Any:
        if (
            self._state.get("edit_plan") is None
            or int(self._state.get("context_revision") or 0) != len(job.context_addenda)
        ):
            self._state["edit_plan"] = self._build_plan(self._objective(job), job)
            self._state["context_revision"] = len(job.context_addenda)
        return self._state["edit_plan"]

    def _design(self, job: AcquisitionJob) -> dict[str, Any]:
        from tech_connector.services.project_edit_agent_service import (
            render_grounded_project_edit_handoff,
            validate_project_edit_plan_output,
        )

        edit_plan = self._ensure_current_plan(job)
        output = render_grounded_project_edit_handoff(edit_plan)
        output = output.replace(
            "Approval scope: approval permits code generation and diff preview only; it does not write files.",
            "Approval scope: Approve & Start permits bounded code generation, validation-driven repair, disposable validation, "
            "application with an undo session, and live callable readback across evidence-backed owner and focused-test files.",
        )
        errors = validate_project_edit_plan_output(edit_plan, output)
        if errors:
            return {"ok": False, "error": "Grounded implementation plan failed: " + "; ".join(errors[:4])}
        self._state["approved_plan"] = output
        alignment = self._verify_design_alignment(job)
        self._state["plan_alignment"] = alignment
        return {
            "ok": True,
            "evidence": [output, alignment],
            "model": "deterministic_plus_semantic_critic",
        }

    def _verify_design_alignment(self, job: AcquisitionJob) -> dict[str, Any]:
        contract = dict(job.plan.get("requested_behavior_contract") or {})
        if not contract:
            return {
                "framework": "prompt_plan_alignment_v1",
                "status": "skipped_no_behavior_contract",
                "matches_request": True,
                "elapsed_ms": 0.0,
            }
        verifier = self._alignment_verifier
        chunks = self._alignment_chunks(job, contract)
        self._state["requirement_chunks"] = chunks
        self._refresh_requirement_fulfillment(job)
        if verifier is None:
            from tech_connector.services.prompt.prompt_plan_verification_service import verify_prompt_plan_alignment
            from tech_connector.services.prompt.prompt_plan_verification_service import _default_alignment_model_query

            if chunks:
                chunk_results = []
                for index, chunk in enumerate(chunks, start=1):
                    self._emit_progress(
                        "requirement_verification",
                        label=f"Verifying requirement {index}/{len(chunks)}",
                        current=index,
                        total=len(chunks),
                        requirement_id=chunk["id"],
                        requirement=chunk["requirement"],
                    )
                    focused_prompt = chunk["requirement"]
                    verdict = dict(verify_prompt_plan_alignment(
                        focused_prompt,
                        {"operation_plan": {
                            "operation": contract.get("original_operation") or job.plan.get("resume_operation") or "",
                            "steps": [chunk["evidence"]],
                        }},
                        model_query=_default_alignment_model_query,
                        fallback_model_query=_default_alignment_model_query,
                        primary_tier="semantic_alignment_8b",
                    ) or {})
                    chunk_results.append({
                        "id": chunk["id"],
                        "requirement": chunk["requirement"],
                        "source": chunk["source"],
                        "plan_evidence": chunk["evidence"],
                        **verdict,
                    })
                failures = [row for row in chunk_results if not row.get("matches_request")]
                self._state["requirement_verdicts"] = chunk_results
                return {
                    "framework": "prompt_plan_alignment_v2_chunked",
                    "status": "mismatch" if failures else "verified",
                    "matches_request": not failures,
                    "confidence": min(
                        (float(row.get("confidence") or 0.0) for row in chunk_results),
                        default=0.0,
                    ),
                    "missing": [
                        {"request_fragment": row["id"], "reason": row.get("reason") or "Focused requirement did not match."}
                        for row in failures
                    ],
                    "distorted": [],
                    "unsupported_claims": [],
                    "chunks": chunk_results,
                    "original_request_preserved": job.original_request,
                    "elapsed_ms": round(sum(float(row.get("elapsed_ms") or 0.0) for row in chunk_results), 3),
                    "model_role": "semantic_plan_critic",
                    "verifier_tier": "semantic_general_8b_chunked",
                }
            verifier = verify_prompt_plan_alignment
        return dict(verifier(job.original_request, self._alignment_candidate(job, contract)) or {})

    def _alignment_candidate(self, job: AcquisitionJob, contract: dict[str, Any]) -> dict[str, Any]:
        planned = [str(item) for item in list(contract.get("planned_steps") or [])]
        parameter_names = [str(item) for item in list(contract.get("required_parameter_names") or [])]
        result_evidence = contract.get("required_result_evidence") or []
        if not isinstance(result_evidence, (list, tuple, set)):
            result_evidence = [result_evidence]
        behavior_steps = list(dict.fromkeys(filter(None, [
            *planned,
            (
                "Implement the requested strategy: " + str(contract.get("source_strategy"))
                if contract.get("source_strategy")
                else ""
            ),
            "Expose the requested editable controls: " + ", ".join(parameter_names)
            if parameter_names
            else "",
            *[str(item) for item in result_evidence],
            str(contract.get("acceptance") or ""),
        ])))
        candidate = {
            "route": "target_discovery",
            "operation_plan": {
                "operation": contract.get("original_operation") or job.plan.get("resume_operation") or self._gap_operation(job),
                "steps": behavior_steps,
                "params": {
                    "source_strategy": contract.get("source_strategy"),
                    "required_arguments": contract.get("required_arguments") or [],
                    "required_parameter_names": contract.get("required_parameter_names") or [],
                    "implementation_dependency": contract.get("missing_operation") or self._gap_operation(job),
                },
            },
            "task_graph": {},
            "known_gaps": [],
        }
        return candidate

    def _alignment_chunks(self, job: AcquisitionJob, contract: dict[str, Any]) -> list[dict[str, str]]:
        candidate = self._alignment_candidate(job, contract)
        steps = [str(item) for item in candidate["operation_plan"]["steps"]]
        from tech_connector.services.reasoning.semantic_execution_contract_service import (
            build_requirement_verification_chunks,
        )

        semantic_contract = (
            job.plan.get("semantic_execution_contract")
            or dict(job.plan.get("prompt_execution_context") or {}).get("semantic_execution_contract")
            or {}
        )
        task_graph = (
            job.plan.get("task_graph")
            or dict(job.plan.get("prompt_execution_context") or {}).get("task_graph")
            or {}
        )
        return build_requirement_verification_chunks(
            job.original_request,
            semantic_contract=semantic_contract,
            behavior_contract=contract,
            task_graph=task_graph,
            candidate_steps=steps,
        )

    def _refresh_requirement_fulfillment(
        self,
        job: AcquisitionJob,
        *,
        artifacts: list[str] | None = None,
        validation_evidence: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        from tech_connector.services.reasoning.semantic_execution_contract_service import (
            build_requirement_fulfillment_links,
        )

        links = build_requirement_fulfillment_links(
            list(self._state.get("requirement_chunks") or []),
            operation=self._gap_operation(job),
            artifacts=artifacts or list(self._state.get("applied_paths") or []),
            validation_evidence=validation_evidence or [],
        )
        verdicts = {
            str(row.get("id") or ""): row
            for row in list(self._state.get("requirement_verdicts") or [])
        }
        for link in links:
            verdict = verdicts.get(str(link.get("requirement_id") or ""))
            if verdict:
                link["semantic_verdict"] = {
                    "matches_request": bool(verdict.get("matches_request")),
                    "confidence": float(verdict.get("confidence") or 0.0),
                    "reason": str(verdict.get("reason") or ""),
                }
                if not verdict.get("matches_request"):
                    link["status"] = "unfulfilled"
        self._state["requirement_fulfillment"] = links
        return links

    def _implement(self, job: AcquisitionJob) -> dict[str, Any]:
        from tech_connector.services.project_edit_agent_service import (
            build_project_edit_repair_stage,
        )

        edit_plan = self._ensure_current_plan(job)
        approved_plan = str(self._state.get("approved_plan") or "")
        if not approved_plan:
            return {"ok": False, "error": "No grounded implementation plan is available."}
        patch_stage = next((item for item in self._build_stages(edit_plan) if item.key == "patch_generation"), None)
        if patch_stage is None:
            return {"ok": False, "error": "The grounded edit plan did not produce a patch-generation stage."}
        owner_evidence = str(getattr(edit_plan, "capability_source_evidence", "") or "")
        if self._state.get("required_implementation_layer") == "reflected_cpp_bridge":
            patch_stage.system_prompt = (
                "You are an Unreal Editor C++ bridge engineer. The approved capability cannot be implemented in Python alone. "
                "Return a minimal buildable patch containing: reflected header declaration, functional C++ body, required Build.cs "
                "modules, Python adapter call, canonical operation registration, and a focused mocked test. A command-contract return, "
                "placeholder, duplicated Python function, or missing C++ body is invalid. Use only exact owner evidence."
            )
        prompt = self._implementation_brief(job, owner_evidence)
        repair_context = list(self._state.pop("repair_context", []) or [])
        if repair_context:
            prompt += (
                "\n\nThe previously applied attempt failed these gates. Approval already grants authority to repair them now:\n- "
                + "\n- ".join(str(item) for item in repair_context)
            )
        output = self._generate_initial_candidate(patch_stage, prompt, job)
        last_errors: list[str] = []
        temp_result: dict[str, Any] = {}
        seen_failure_signatures: set[tuple[str, ...]] = set()
        force_quality = False
        for attempt in range(0, 4):
            preview = self._preview(output, job)
            last_errors = [str(item) for item in list(getattr(preview, "errors", []) or [])]
            if last_errors:
                mechanically_repaired, repair_actions = self._mechanically_repair_output(output, last_errors, job)
                if mechanically_repaired != output:
                    output = mechanically_repaired
                    self._state.setdefault("mechanical_repairs", []).extend(repair_actions)
                    preview = self._preview(output, job)
                    last_errors = [str(item) for item in list(getattr(preview, "errors", []) or [])]
            if getattr(preview, "ok", False):
                last_errors.extend(self._behavior_contract_errors(preview, job))
            if getattr(preview, "ok", False) and not last_errors:
                temp_result = self._validate_in_temp(preview)
                if temp_result.get("ok"):
                    applied = self._apply(output, job)
                    if getattr(applied, "ok", False):
                        self._state["applied"] = applied
                        self._state.setdefault("applied_sessions", []).append(
                            str(getattr(applied, "change_session_path", "") or "")
                        )
                        self._state.setdefault("applied_paths", []).extend(
                            str(item.get("path") or "")
                            for item in list(getattr(applied, "changes", []) or [])
                            if str(item.get("path") or "").strip()
                        )
                        self._state["temp_validation"] = temp_result
                        self._state["last_output"] = output
                        paths = [str(item.get("path") or "") for item in list(getattr(applied, "changes", []) or [])]
                        fulfillment = self._refresh_requirement_fulfillment(job, artifacts=paths)
                        return {
                            "ok": True,
                            "artifacts": paths,
                            "evidence": {
                                "temp_workspace": temp_result.get("temp_workspace"),
                                "validation_commands": temp_result.get("commands") or [],
                                "undo_session": str(getattr(applied, "change_session_path", "") or ""),
                                "repair_attempts": attempt,
                                "requirement_fulfillment": fulfillment,
                            },
                        }
                    last_errors = [
                        "Validated patch could not be applied: "
                        + "; ".join(str(item) for item in list(getattr(applied, "errors", []) or [])[:6])
                    ]
                else:
                    last_errors = self._temp_failure_errors(temp_result)
            if attempt >= 3:
                break
            signature = tuple(sorted(set(last_errors)))
            if signature and signature in seen_failure_signatures:
                force_quality = True
            seen_failure_signatures.add(signature)
            repair = build_project_edit_repair_stage(
                edit_plan,
                output,
                last_errors,
                attempt=attempt + 1,
                approved_plan=approved_plan,
            )
            repair.user_prompt = self._minimal_repair_prompt(
                job=job,
                candidate=output,
                errors=last_errors,
                owner_evidence=owner_evidence,
            )
            localized = self._repair_candidate_artifacts(
                repair,
                candidate=output,
                errors=last_errors,
                job=job,
                owner_evidence=owner_evidence,
                profile="quality" if force_quality or attempt >= 2 else "standard",
            )
            if localized:
                output = localized
                continue
            self._promote_code_stage(
                repair,
                profile="quality" if force_quality or attempt >= 2 else "standard",
            )
            repaired = str(self._model_query(repair, self._model_for(repair)) or "").strip()
            if not repaired:
                break
            output = repaired
        return {
            "ok": False,
            "error": "Automatic repair exhausted its current model budget: " + "; ".join(last_errors[:6]),
            "temp_validation": temp_result,
        }

    def _generate_initial_candidate(self, patch_stage: Any, prompt: str, job: AcquisitionJob) -> str:
        if self._state.get("required_implementation_layer") != "reflected_cpp_bridge":
            return str(self._model_query(patch_stage, self._model_for(patch_stage), prompt) or "").strip()

        wrapper_contract = self._canonical_cpp_wrapper_contract(job)
        wrapper_function = str(
            wrapper_contract.get("wrapper_function")
            or dict(job.plan.get("requested_behavior_contract") or {}).get("required_cpp_method")
            or ""
        ).strip()
        python_call = str(
            wrapper_contract.get("python_call")
            or dict(job.plan.get("requested_behavior_contract") or {}).get("required_python_bridge_call")
            or ""
        ).strip()
        operation = self._gap_operation(job)
        namespace = operation.partition(".")[0]
        adapter_method = operation.partition(".")[2]
        module_names = ", ".join(str(item) for item in wrapper_contract.get("required_modules") or [])
        minimum_contract = "; ".join(str(item) for item in wrapper_contract.get("minimum_contract") or [])
        wrapper_function_label = wrapper_function or "the required reflected method from the behavior contract"
        artifact_specs = [
            (
                "cpp_declaration_modules",
                ("AIStudioBridgeLibrary.h", "AIStudioBridge.Build.cs"),
                "Return only the reflected UFUNCTION declaration and required Build.cs dependency changes. "
                "For both non-Python files use insert_before_text, insert_after_text, or replace_text with an exact unique source anchor copied verbatim from evidence. Never use a Python symbol action.",
                900,
            ),
            (
                "cpp_functional_body",
                ("AIStudioBridgeLibrary.cpp",),
                f"Return only includes plus the complete functional C++ body for UAIStudioBridgeLibrary::{wrapper_function_label}. "
                "Use only Unreal classes and methods shown in supplied project or engine-source evidence. If an API is not evidenced, report it as a remaining gap instead of inventing it. "
                "Use language-neutral exact-text actions; never put :line suffixes in paths and never emit UFUNCTION in the .cpp file. "
                f"Required modules: {module_names or 'derive only from verified evidence'}. Minimum functional contract: {minimum_contract or 'mutate, save, and read back the requested result'}. "
                "Include validation and JSON readback evidence; no placeholder body.",
                1400,
            ),
            (
                "python_adapter_registry",
                (f"unreal_tools/{namespace}.py", "unreal_operation_service.py"),
                f"Return a public unreal_tools.{namespace}.{adapter_method} adapter that imports unreal at call time, calls `{python_call}`, parses its JSON result, and returns the established JSON result contract. "
                f"Also register `{operation}` in the canonical Unreal operation catalog. Do not duplicate request parsing or a parent composite.",
                900,
            ),
            (
                "focused_behavior_test",
                ("test_unreal_execution_pipeline.py",),
                "Return one compact focused unittest method that patches the Python adapter's Unreal boundary and directly proves success, rejected/invalid input behavior, and the operation's required readback evidence. Use an exact indexed Class.method anchor from the brief.",
                1050,
            ),
        ]
        combined_changes: list[dict[str, Any]] = []
        reports = {"changed": [], "reused": [], "verification": [], "remaining_gaps": []}
        prior_interfaces = ""
        parse_failures: list[str] = []
        owners = self._owner_paths(job)
        for key, file_names, instruction, token_budget in artifact_specs:
            self._emit_progress(
                "artifact_generation",
                label=f"Generating {key.replace('_', ' ')}",
                artifact=key,
            )
            stage = copy.copy(patch_stage)
            stage.key = key
            stage.label = key.replace("_", " ").title()
            stage.num_predict = token_budget
            stage.timeout = 120
            allowed_names = {Path(value).name for value in file_names}
            relevant_paths = [path for path in owners if path.name in allowed_names]
            evidence = self._owner_source_evidence(relevant_paths, job)
            if key == "cpp_functional_body" and self._state.get("host_api_evidence"):
                evidence += "\n\nVerified Unreal Engine source evidence:\n" + str(self._state["host_api_evidence"])
            artifact_prompt = "\n".join([
                self._implementation_brief(job, ""),
                f"Current artifact: {key}",
                instruction,
                "Only these files are allowed in this response:",
                *[f"- {path}" for path in relevant_paths],
                "Exact evidence for this artifact:",
                evidence,
                "Previously generated interface declarations (for signature consistency only):",
                prior_interfaces[-5000:],
                "Return one complete JSON patch object. Do not repeat changes from earlier artifacts.",
            ])
            raw = str(self._model_query(stage, self._model_for(stage), artifact_prompt) or "").strip()
            try:
                payload = json.loads(raw)
            except Exception as exc:
                retry_prompt = "\n".join([
                    artifact_prompt,
                    "The previous response was invalid or truncated JSON:",
                    str(exc),
                    "Return a smaller complete JSON object now. Keep only the minimum code needed for this artifact.",
                ])
                raw = str(self._model_query(stage, self._model_for(stage), retry_prompt) or "").strip()
                try:
                    payload = json.loads(raw)
                except Exception as retry_exc:
                    parse_failures.append(f"{key}: {retry_exc}")
                    continue
            changes = [dict(item) for item in list(payload.get("changes") or []) if isinstance(item, dict)]
            self._normalize_artifact_changes(changes)
            combined_changes.extend(changes)
            prior_interfaces += "\n" + "\n".join(
                str(item.get("new_content") or "")
                for item in changes
            )
            report = dict(payload.get("report") or {})
            for report_key in reports:
                reports[report_key].extend(str(item) for item in list(report.get(report_key) or []))
            self._emit_progress(
                "artifact_generated",
                label=f"Generated {key.replace('_', ' ')}",
                artifact=key,
                change_count=len(changes),
            )
        if parse_failures:
            reports["remaining_gaps"].extend(parse_failures)
            self._state["artifact_generation_failures"] = parse_failures
        for key in reports:
            reports[key] = list(dict.fromkeys(reports[key]))
        return json.dumps({
            "changes": combined_changes,
            "report": reports,
            "blocked_reason": "" if combined_changes else "; ".join(parse_failures),
        }, indent=2)

    def _canonical_cpp_wrapper_contract(self, job: AcquisitionJob) -> dict[str, Any]:
        contract = dict(job.plan.get("requested_behavior_contract") or {})
        operation = str(contract.get("missing_operation") or self._gap_operation(job)).strip()
        try:
            from tech_connector.services.unreal.cpp_domain_wrapper_requirements_service import (
                get_cpp_domain_wrapper_requirement,
            )

            requirement = get_cpp_domain_wrapper_requirement(operation)
        except Exception:
            requirement = None
        canonical = requirement.to_dict() if requirement is not None else {}
        if contract.get("required_cpp_method"):
            canonical["wrapper_function"] = str(contract["required_cpp_method"])
        if contract.get("required_python_bridge_call"):
            canonical["python_call"] = str(contract["required_python_bridge_call"])
        if contract.get("required_unreal_modules"):
            canonical["required_modules"] = tuple(contract["required_unreal_modules"])
        return canonical

    def _normalize_artifact_changes(self, changes: list[dict[str, Any]]) -> None:
        """Normalize harmless locator syntax without guessing an edit anchor."""

        for change in changes:
            raw_path = str(change.get("path") or "")
            match = re.match(r"^(.*\.[A-Za-z0-9]+):(\d+)$", raw_path)
            if match and Path(match.group(1)).exists():
                change["path"] = match.group(1)

    def _implementation_brief(self, job: AcquisitionJob, owner_evidence: str) -> str:
        contract = dict(job.plan.get("requested_behavior_contract") or {})
        compact_contract = {
            key: contract.get(key)
            for key in (
                "original_operation", "missing_operation", "request_fragment", "source_strategy",
                "required_arguments", "required_parameter_names", "required_result_evidence", "acceptance",
                "required_implementation_layer", "required_cpp_method", "required_python_bridge_call",
                "required_unreal_modules", "required_implementation_evidence",
            )
            if contract.get(key) not in (None, "", [])
        }
        alignment = dict(self._state.get("plan_alignment") or {})
        owners = self._owner_paths(job)
        tests = [path for path in owners if path.name.startswith("test_")]
        anchors = self._focused_test_anchors(job)
        lines = [
            "Implement one missing callable from verified project evidence.",
            f"Original request: {job.original_request}",
            f"Missing callable: {self._gap_operation(job)}",
            f"Resume operation: {job.plan.get('resume_operation') or ''}",
            f"Required implementation layer: {self._state.get('required_implementation_layer') or contract.get('required_implementation_layer') or 'evidence_decides'}",
            "Mandatory behavior contract:",
            json.dumps(compact_contract, indent=2, default=str),
            "Semantic coverage critic (advisory; deterministic contract remains authoritative):",
            json.dumps({
                "matches_request": alignment.get("matches_request"),
                "missing": alignment.get("missing") or [],
                "distorted": alignment.get("distorted") or [],
                "unsupported_claims": alignment.get("unsupported_claims") or [],
            }, indent=2, default=str),
            "Allowed owner files:",
            *[f"- {path}" for path in owners],
            "Completion requirements:",
            "- Implement the behavior itself; metadata-only returns and generic asset creation are invalid.",
            "- Use only APIs evidenced below, or add a reflected C++ bridge body plus adapter and build proof.",
            "- Add a useful docstring to every new public callable.",
            "- Include a direct focused test with mocked host APIs for success and failure behavior.",
            "- Use symbol edits and preserve unrelated behavior.",
        ]
        if tests:
            lines.append(f"Exact focused test owner: {tests[0]}")
        if anchors:
            lines.append("Valid test anchors: " + ", ".join(anchors[:8]))
        if owner_evidence:
            lines.extend(["Verified owner evidence:", owner_evidence])
        lines.append("Return exactly the required JSON patch object with no Markdown.")
        return "\n".join(lines)

    def _minimal_repair_prompt(
        self,
        *,
        job: AcquisitionJob,
        candidate: str,
        errors: list[str],
        owner_evidence: str,
    ) -> str:
        return "\n".join([
            "Repair only the unresolved failures in this candidate. Preserve every passing operation.",
            f"Missing callable: {self._gap_operation(job)}",
            "Failures:",
            *[f"- {item}" for item in errors],
            "Candidate JSON:",
            candidate,
            "Exact owner evidence:",
            owner_evidence,
            self._repair_directives(errors, job),
            "Return exactly one complete replacement JSON patch object. Do not add unrelated changes.",
        ])

    def _repair_candidate_artifacts(
        self,
        repair_stage: Any,
        *,
        candidate: str,
        errors: list[str],
        job: AcquisitionJob,
        owner_evidence: str,
        profile: str,
    ) -> str:
        """Repair only files implicated by diagnostics and preserve passing changes."""

        try:
            payload = json.loads(candidate)
        except Exception:
            return ""
        changes = [dict(item) for item in list(payload.get("changes") or []) if isinstance(item, dict)]
        affected = self._affected_artifact_paths(changes, errors)
        all_paths = {str(item.get("path") or "") for item in changes if str(item.get("path") or "")}
        if not affected or affected == all_paths:
            return ""

        affected_changes = [
            item for item in changes if str(item.get("path") or "") in affected
        ]
        stage = copy.copy(repair_stage)
        stage.key = "artifact_local_repair"
        stage.label = "Artifact-local repair"
        stage.user_prompt = "\n".join([
            "Repair only the affected artifacts listed below. Passing artifacts are intentionally omitted and must not be regenerated.",
            f"Missing callable: {self._gap_operation(job)}",
            "Failed gates:",
            *[f"- {item}" for item in errors],
            "Affected artifact paths:",
            *[f"- {path}" for path in sorted(affected)],
            "Current affected changes:",
            json.dumps(affected_changes, indent=2),
            "Exact owner evidence:",
            owner_evidence,
            self._repair_directives(errors, job),
            "Return one valid JSON patch object containing changes only for the affected paths.",
        ])
        self._promote_code_stage(stage, profile=profile)
        self._emit_progress(
            "artifact_repair",
            label="Repairing only failed artifacts",
            paths=sorted(affected),
            errors=list(errors),
        )
        raw = str(self._model_query(stage, self._model_for(stage)) or "").strip()
        try:
            repaired_payload = json.loads(raw)
        except Exception:
            return ""
        repaired_changes = [
            dict(item)
            for item in list(repaired_payload.get("changes") or [])
            if isinstance(item, dict) and str(item.get("path") or "") in affected
        ]
        if not repaired_changes:
            return ""
        self._normalize_artifact_changes(repaired_changes)
        merged_changes = [
            item for item in changes if str(item.get("path") or "") not in affected
        ]
        merged_changes.extend(repaired_changes)
        report = dict(payload.get("report") or {})
        repair_report = dict(repaired_payload.get("report") or {})
        for key in ("changed", "reused", "verification", "remaining_gaps"):
            report[key] = list(dict.fromkeys([
                *[str(item) for item in list(report.get(key) or [])],
                *[str(item) for item in list(repair_report.get(key) or [])],
            ]))
        report.setdefault("verification", []).append(
            "Artifact-local repair preserved passing paths and regenerated only: "
            + ", ".join(sorted(affected))
        )
        self._state.setdefault("artifact_local_repairs", []).append({
            "paths": sorted(affected),
            "errors": list(errors),
        })
        return json.dumps({
            **payload,
            "changes": merged_changes,
            "report": report,
        }, indent=2)

    @staticmethod
    def _affected_artifact_paths(
        changes: list[dict[str, Any]],
        errors: list[str],
    ) -> set[str]:
        paths = {str(item.get("path") or "") for item in changes if str(item.get("path") or "")}
        lowered = "\n".join(str(item) for item in errors).lower()
        direct = {
            path for path in paths
            if path.lower() in lowered or Path(path).name.lower() in lowered
        }
        if direct:
            return direct

        selected: set[str] = set()
        for path in paths:
            value = path.lower().replace("\\", "/")
            name = Path(path).name.lower()
            is_test = name.startswith("test_") or "/tests/" in value
            if any(token in lowered for token in ("build.cs", "module dependency", "missing module")):
                if name.endswith(".build.cs"):
                    selected.add(path)
            if any(token in lowered for token in ("ufunction", "declaration", "header")):
                if name.endswith((".h", ".build.cs")):
                    selected.add(path)
            if any(token in lowered for token in ("c++", "cpp", "compiler", "linker", "functional body")):
                if name.endswith((".cpp", ".h", ".build.cs")):
                    selected.add(path)
            if any(token in lowered for token in ("adapter", "python call", "importable callable", "reflected call")):
                if name.endswith(".py") and not is_test:
                    selected.add(path)
            if any(token in lowered for token in ("registry", "catalog", "operation mapping")):
                if name.endswith(".py") and any(token in name for token in ("operation", "registry", "capability")):
                    selected.add(path)
            if any(token in lowered for token in ("test", "mock", "assert")):
                if is_test:
                    selected.add(path)
        return selected

    def _mechanically_repair_output(
        self,
        output: str,
        errors: list[str],
        job: AcquisitionJob,
    ) -> tuple[str, list[str]]:
        try:
            payload = json.loads(output)
        except Exception:
            return output, []
        changed = False
        actions: list[str] = []
        missing_docstrings: set[str] = set()
        missing_anchors: list[tuple[str, str]] = []
        unresolved_import = False
        for error in errors:
            match = re.search(r"docstrings?:\s*(.+)$", str(error), re.IGNORECASE)
            if match:
                missing_docstrings.update(name.strip() for name in match.group(1).split(",") if name.strip())
            anchor_match = re.search(r"Indexed Python symbol was not found:\s*(\S+)\s+in\s+(.+)$", str(error))
            if anchor_match:
                missing_anchors.append((anchor_match.group(1), anchor_match.group(2).strip()))
            if "New import could not be resolved or accounted for" in str(error):
                unresolved_import = True
        for change in list(payload.get("changes") or []):
            code = str(change.get("new_content") or "")
            if code and missing_docstrings:
                repaired = self._insert_missing_docstrings(code, missing_docstrings)
                if repaired != code:
                    change["new_content"] = repaired
                    changed = True
                    actions.append("inserted_missing_public_docstring")
            for missing_anchor, raw_path in missing_anchors:
                if (
                    str(change.get("target_symbol") or "") != missing_anchor
                    or Path(str(change.get("path") or "")).resolve() != Path(raw_path).resolve()
                ):
                    continue
                anchors = self._focused_test_anchors(job)
                if not anchors:
                    continue
                replacement = anchors[0]
                change["target_symbol"] = replacement
                if "." in replacement:
                    snippet = str(change.get("new_content") or "")
                    nonblank = [line for line in snippet.splitlines() if line.strip()]
                    if nonblank and not nonblank[0].startswith((" ", "\t")):
                        change["new_content"] = "\n".join(
                            ("    " + line) if line.strip() else line
                            for line in snippet.splitlines()
                        )
                    change["new_content"] = re.sub(
                        r"(?m)^(\s*def\s+test_[A-Za-z0-9_]+)\(\s*\)\s*:",
                        r"\1(self):",
                        str(change.get("new_content") or ""),
                        count=1,
                    )
                changed = True
                actions.append(f"reanchored_test_change:{replacement}")
            if unresolved_import and Path(str(change.get("path") or "")).name.startswith("test_"):
                operation_symbol = self._gap_operation(job).rpartition(".")[-1]
                namespace = self._gap_operation(job).partition(".")[0]
                snippet = str(change.get("new_content") or "")
                repaired = re.sub(
                    rf"(?m)^(\s*)from\s+{re.escape(namespace)}\s+import\s+{re.escape(operation_symbol)}\s*$",
                    rf"\1from unreal_tools.{namespace} import {operation_symbol}",
                    snippet,
                )
                if repaired != snippet:
                    change["new_content"] = repaired
                    changed = True
                    actions.append("normalized_focused_test_import")
        if changed:
            return json.dumps(payload, indent=2), actions
        return output, actions

    @staticmethod
    def _insert_missing_docstrings(code: str, names: set[str]) -> str:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code
        lines = code.splitlines()
        insertions: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in names:
                continue
            if ast.get_docstring(node, clean=False) is not None or not node.body:
                continue
            first_line = int(node.body[0].lineno) - 1
            indent = re.match(r"\s*", lines[first_line]).group(0)
            parameters = [
                argument.arg
                for argument in [
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                ]
                if argument.arg not in {"self", "cls"}
            ]
            if node.args.vararg is not None:
                parameters.append(node.args.vararg.arg)
            if node.args.kwarg is not None:
                parameters.append(node.args.kwarg.arg)
            words = node.name.strip("_").replace("_", " ").split()
            verb = {
                "apply": "Applies",
                "build": "Builds",
                "create": "Creates",
                "find": "Finds",
                "get": "Gets",
                "inspect": "Inspects",
                "list": "Lists",
                "normalize": "Normalizes",
                "repair": "Repairs",
                "resolve": "Resolves",
                "set": "Sets",
                "synthesize": "Synthesizes",
                "update": "Updates",
                "validate": "Validates",
            }.get(words[0].casefold() if words else "")
            summary = (
                " ".join([verb, *words[1:]])
                if verb
                else "Handles " + " ".join(words or ["capability"])
            )
            docstring_lines = [f'{indent}"""{summary}.', ""]
            docstring_lines.extend(
                f"{indent}:param {parameter}: {parameter.replace('_', ' ')}"
                for parameter in parameters
            )
            docstring_lines.extend([f"{indent}:return: result", f'{indent}"""'])
            insertions.append((first_line, "\n".join(docstring_lines)))
        for index, text in sorted(insertions, reverse=True):
            lines.insert(index, text)
        return "\n".join(lines)

    def _behavior_contract_errors(self, preview: Any, job: AcquisitionJob) -> list[str]:
        contract = dict(job.plan.get("requested_behavior_contract") or {})
        if not contract:
            return []
        operation_symbol = self._gap_operation(job).rpartition(".")[-1]
        namespace = self._gap_operation(job).partition(".")[0]
        source_strategy = str(contract.get("source_strategy") or "")
        source_chunks: list[str] = []
        test_chunks: list[str] = []
        cpp_chunks: list[str] = []
        header_chunks: list[str] = []
        build_chunks: list[str] = []
        adapter_chunks: list[str] = []
        registry_chunks: list[str] = []
        for change in list(getattr(preview, "changes", []) or []):
            text = str(change.get("after") or change.get("new_content") or "")
            path = Path(str(change.get("path") or ""))
            if path.name.startswith("test_"):
                test_chunks.append(text)
            else:
                source_chunks.append(text)
            if path.suffix.lower() in {".cpp", ".cc"}:
                cpp_chunks.append(text)
            elif path.suffix.lower() in {".h", ".hpp"}:
                header_chunks.append(text)
            elif path.name.endswith(".Build.cs"):
                build_chunks.append(text)
            if path.as_posix().endswith(f"unreal_tools/{namespace}.py"):
                adapter_chunks.append(text)
            if path.name == "unreal_operation_service.py":
                registry_chunks.append(text)
        source = "\n".join(source_chunks)
        tests = "\n".join(test_chunks)
        errors: list[str] = []
        if operation_symbol not in source:
            errors.append(f"Behavior contract missing callable definition: {operation_symbol}")
        if source_strategy and source_strategy not in source:
            errors.append(f"Behavior contract missing source-strategy dispatch: {source_strategy}")
        for row in list(contract.get("required_implementation_evidence") or []):
            if isinstance(row, dict):
                any_of = [str(item) for item in list(row.get("any_of") or []) if str(item)]
                all_of = [str(item) for item in list(row.get("all_of") or []) if str(item)]
                label = str(row.get("label") or "required implementation evidence")
            else:
                any_of = [str(row)]
                all_of = []
                label = str(row)
            if any_of and not any(marker in source for marker in any_of):
                errors.append(f"Behavior contract is missing {label}: expected any of {', '.join(any_of)}")
            missing_all = [marker for marker in all_of if marker not in source]
            if missing_all:
                errors.append(f"Behavior contract is missing {label}: {', '.join(missing_all)}")
        if re.search(r"\b(?:placeholder|todo|implement the logic .* here)\b", source, re.IGNORECASE):
            errors.append("Behavior contract contains placeholder implementation text.")
        required_layer = str(
            contract.get("required_implementation_layer")
            or self._state.get("required_implementation_layer")
            or ""
        )
        if required_layer == "reflected_cpp_bridge":
            wrapper_contract = self._canonical_cpp_wrapper_contract(job)
            cpp_method = str(
                contract.get("required_cpp_method")
                or wrapper_contract.get("wrapper_function")
                or ""
            )
            python_call = str(
                contract.get("required_python_bridge_call")
                or wrapper_contract.get("python_call")
                or ""
            )
            cpp_source = "\n".join(cpp_chunks)
            header_source = "\n".join(header_chunks)
            adapter_source = "\n".join(adapter_chunks)
            registry_source = "\n".join(registry_chunks)
            if not cpp_chunks or (cpp_method and cpp_method not in cpp_source):
                errors.append(f"Required reflected C++ body is missing: {cpp_method or operation_symbol}")
            if not header_chunks or (cpp_method and cpp_method not in header_source):
                errors.append(f"Required reflected C++ declaration is missing: {cpp_method or operation_symbol}")
            if cpp_method and not re.search(
                rf"UFUNCTION\s*\([^)]*\)\s*static\s+FString\s+{re.escape(cpp_method)}\s*\(",
                header_source,
                re.DOTALL,
            ):
                errors.append(f"C++ declaration is not a reflected static UFUNCTION: {cpp_method}")
            if operation_symbol and not re.search(rf"\bdef\s+{re.escape(operation_symbol)}\s*\(", adapter_source):
                errors.append(f"Python adapter callable is missing from unreal_tools: {operation_symbol}")
            reflected_method = python_call.partition("(")[0]
            if reflected_method and reflected_method not in adapter_source:
                errors.append(f"Python adapter does not call the required reflected bridge: {python_call}")
            operation_key = str(contract.get("missing_operation") or self._gap_operation(job))
            expected_function = f"unreal_tools.{namespace}.{operation_symbol}"
            if operation_key not in registry_source or expected_function not in registry_source:
                errors.append(
                    f"Canonical Unreal operation registration is missing: {operation_key} -> {expected_function}"
                )
            modules = [
                str(item)
                for item in list(
                    contract.get("required_unreal_modules")
                    or wrapper_contract.get("required_modules")
                    or []
                )
            ]
            build_source = "\n".join(build_chunks)
            missing_modules = [module for module in modules if module not in build_source]
            if missing_modules:
                errors.append("Plugin Build.cs is missing required Unreal modules: " + ", ".join(missing_modules))
        if operation_symbol not in tests:
            errors.append(f"Focused test does not call the acquired callable directly: {operation_symbol}")
        if source_strategy and source_strategy not in tests:
            errors.append(f"Focused test does not exercise source strategy: {source_strategy}")
        if tests and not any(marker in tests for marker in ("mock", "patch", "Fake", "stub")):
            errors.append("Focused disposable test must mock unavailable Unreal host APIs.")
        return errors

    @staticmethod
    def _temp_failure_errors(result: dict[str, Any]) -> list[str]:
        errors = [str(item) for item in list(result.get("errors") or []) if str(item).strip()]
        for command in list(result.get("commands") or []):
            if int(command.get("exit_code", 0) or 0) == 0:
                continue
            rendered = command.get("command") or []
            detail = str(command.get("stderr") or command.get("stdout") or "").strip()
            errors.append(
                "Disposable validation command failed: "
                + " ".join(str(item) for item in rendered)
                + (f"\n{detail[-4000:]}" if detail else "")
            )
        return errors or ["Disposable patch validation failed without diagnostic output."]

    def _validate(self, job: AcquisitionJob) -> dict[str, Any]:
        from tech_connector.services.project_edit_agent_service import validate_project_edit_paths

        for repair_attempt in range(0, 3):
            applied = self._state.get("applied")
            if applied is None and not self._state.get("already_available"):
                failures = ["No applied implementation is available to validate."]
                evidence: list[Any] = []
            else:
                paths = list(dict.fromkeys(
                    str(item) for item in list(self._state.get("applied_paths") or []) if str(item).strip()
                ))
                if not paths and applied:
                    paths = [str(item.get("path") or "") for item in list(getattr(applied, "changes", []) or [])]
                path_results = validate_project_edit_paths(paths) if paths else []
                failed = [item for item in path_results if not item.get("ok")]
                operation_status = self._validate_operation(self._gap_operation(job))
                evidence = [operation_status, *path_results]
                failures = []
                if failed:
                    failures.append("Post-apply path validation failed: " + repr(failed))
                if not operation_status.get("callable_found"):
                    failures.append(
                        "The patch passed static checks but the requested operation is still not an importable callable: "
                        + str(operation_status.get("reason") or operation_status)
                    )
                if not failures and str(job.plan.get("host") or "unreal").lower() == "unreal":
                    live_status = self._validate_live_operation(operation_status, job)
                    evidence.append(live_status)
                    if live_status.get("requires_editor"):
                        return {
                            "ok": False,
                            "pause_required": True,
                            "message": live_status.get("message") or "Open or restart Unreal, then resume validation.",
                            "evidence": evidence,
                        }
                    if not live_status.get("ok"):
                        failures.append(
                            "Unreal live callable proof failed: "
                            + str(live_status.get("error") or live_status.get("message") or live_status)
                        )
                if not failures:
                    self._state["operation_status"] = operation_status
                    if str(job.plan.get("host") or "").lower() == "unreal":
                        live_evidence = next(
                            (
                                item
                                for item in reversed(evidence)
                                if isinstance(item, dict)
                                and item.get("check")
                                == "unreal_disposable_operation_behavior_readback"
                            ),
                            {},
                        )
                        if live_evidence:
                            from tech_connector.game_engine.integration.operation_evidence_service import (
                                record_operation_validation,
                            )

                            receipt = record_operation_validation(
                                self._gap_operation(job),
                                callable_path=str(operation_status.get("function") or ""),
                                evidence=live_evidence,
                            )
                            evidence.append({"operation_validation_receipt": receipt})
                    fulfillment = self._refresh_requirement_fulfillment(
                        job,
                        validation_evidence=evidence,
                    )
                    return {
                        "ok": True,
                        "evidence": evidence,
                        "repair_attempts": repair_attempt,
                        "requirement_fulfillment": fulfillment,
                    }
            if repair_attempt >= 2:
                rollback = self._rollback_applied_sessions()
                return {
                    "ok": False,
                    "error": "Automatic post-apply repair exhausted its model budget: " + "; ".join(failures[:6]),
                    "evidence": evidence,
                    "rollback": rollback,
                }
            self._state["repair_context"] = failures
            repaired = self._implement(job)
            if not repaired.get("ok"):
                rollback = self._rollback_applied_sessions()
                return {**repaired, "rollback": rollback}

        return {"ok": False, "error": "Post-apply validation ended unexpectedly."}

    def _rollback_applied_sessions(self) -> dict[str, Any]:
        from tech_connector.services.change_history_service import load_change_session, undo_change_session

        changed: list[str] = []
        errors: list[str] = []
        sessions = [str(item) for item in list(self._state.get("applied_sessions") or []) if str(item).strip()]
        for path in reversed(sessions):
            session = load_change_session(path)
            ok, message, restored = undo_change_session(session)
            changed.extend(restored)
            if not ok:
                errors.append(message)
        self._state["applied_sessions"] = []
        self._state["applied_paths"] = []
        self._state.pop("applied", None)
        return {"ok": not errors, "sessions": sessions, "changed": changed, "errors": errors}

    def _validate_live_operation(
        self,
        operation_status: dict[str, Any],
        job: AcquisitionJob | None = None,
    ) -> dict[str, Any]:
        if self._live_operation_validator:
            return dict(self._live_operation_validator(operation_status) or {})
        contract = dict(job.plan.get("requested_behavior_contract") or {}) if job is not None else {}
        function_path = str(operation_status.get("function") or "").strip()
        if not function_path:
            return {"ok": False, "message": "The registered operation has no function path."}
        if function_path.startswith("unreal.AIStudioBridgeLibrary."):
            method = function_path.rsplit(".", 1)[-1]
            probe = (
                "import unreal\n"
                f"target = getattr(unreal.AIStudioBridgeLibrary, {method!r}, None)\n"
                "assert callable(target), 'Reflected AIStudioBridge callable is unavailable'\n"
                "print('AI_STUDIO_LIVE_CALLABLE_OK')\n"
            )
        else:
            module_name, separator, symbol = function_path.rpartition(".")
            if not separator:
                return {"ok": False, "message": "The registered function path is not fully qualified."}
            probe = (
                "import importlib\n"
                f"module = importlib.import_module({module_name!r})\n"
                f"target = getattr(module, {symbol!r}, None)\n"
                "assert callable(target), 'Registered Python callable is unavailable in Unreal'\n"
                "print('AI_STUDIO_LIVE_CALLABLE_OK')\n"
            )
        required_bridge_call = str(
            contract.get("required_python_bridge_call") or ""
        ).partition("(")[0]
        if required_bridge_call.startswith("unreal.AIStudioBridgeLibrary."):
            bridge_method = required_bridge_call.rsplit(".", 1)[-1]
            probe += (
                f"bridge_target = getattr(unreal.AIStudioBridgeLibrary, {bridge_method!r}, None)\n"
                "assert callable(bridge_target), 'Required reflected AIStudioBridge dependency is unavailable'\n"
                "print('AI_STUDIO_REQUIRED_BRIDGE_OK')\n"
            )
        try:
            from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

            response = UnrealBridge().execute_python(probe, timeout=12.0, reset_globals=True)
        except Exception as exc:
            return {
                "ok": False,
                "requires_editor": True,
                "message": f"Open or restart Unreal so the acquired callable can be loaded, then Resume. ({exc})",
            }
        if not response.get("ok"):
            error = str(response.get("error") or response.get("raw") or "Unreal bridge is unavailable.")
            if "required reflected aistudiobridge dependency is unavailable" in error.lower():
                return {
                    "ok": False,
                    "requires_editor": True,
                    "message": (
                        "The updated AIStudioBridge source is present, but Unreal has the "
                        "previous DLL loaded. Deploy the validated binary, restart Unreal, "
                        "then Resume at live validation."
                    ),
                    "error": error,
                }
            connection_markers = ("connect", "refused", "timed out", "timeout", "unavailable", "not running")
            if any(marker in error.lower() for marker in connection_markers):
                return {
                    "ok": False,
                    "requires_editor": True,
                    "message": "Open or restart Unreal so the acquired callable can be loaded, then Resume.",
                    "error": error,
                }
            return {"ok": False, "error": error, "response": response}
        from tech_connector.services.unreal.live_validation_fixture_service import (
            build_operation_disposable_fixture,
        )

        fixture = build_operation_disposable_fixture(
            self._gap_operation(job),
            context={
                "arguments": dict(job.plan.get("resume_arguments") or {}),
                "behavior_contract": contract,
                "operation_status": operation_status,
            },
        )
        if fixture:
            self._emit_progress(
                "live_fixture_validation",
                label=f"Running disposable fixture for {self._gap_operation(job)}",
                fixture_id=fixture.get("id"),
            )
            try:
                fixture_response = UnrealBridge().execute_python(
                    str(fixture["python_script"]),
                    timeout=90.0,
                    reset_globals=True,
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "requires_editor": True,
                    "message": f"Open or restart Unreal, then Resume the disposable proof. ({exc})",
                    "fixture": fixture,
                }
            fixture_result = next(
                (
                    candidate
                    for candidate in (
                        fixture_response.get("python_result"),
                        fixture_response.get("result"),
                        fixture_response.get("data"),
                    )
                    if isinstance(candidate, dict)
                ),
                {},
            )
            if isinstance(fixture_result, str):
                try:
                    fixture_result = json.loads(fixture_result)
                except Exception:
                    fixture_result = {}
            if not fixture_response.get("ok") or not isinstance(fixture_result, dict) or not fixture_result.get("ok"):
                return {
                    "ok": False,
                    "error": "Disposable Unreal behavioral proof failed.",
                    "fixture": fixture,
                    "response": fixture_response,
                    "fixture_result": fixture_result,
                }
            cleanup_result: dict[str, Any] = {}
            cleanup_script = str(fixture.get("cleanup_python_script") or "")
            if cleanup_script:
                try:
                    cleanup_response = UnrealBridge().execute_python(
                        cleanup_script,
                        timeout=30.0,
                        reset_globals=True,
                    )
                except Exception as exc:
                    return {
                        "ok": False,
                        "error": "Disposable Unreal fixture cleanup failed.",
                        "fixture": fixture,
                        "fixture_result": fixture_result,
                        "cleanup_error": str(exc),
                    }
                cleanup_result = next(
                    (
                        candidate
                        for candidate in (
                            cleanup_response.get("python_result"),
                            cleanup_response.get("result"),
                            cleanup_response.get("data"),
                        )
                        if isinstance(candidate, dict)
                    ),
                    {},
                )
                if not cleanup_response.get("ok") or not cleanup_result.get("ok"):
                    return {
                        "ok": False,
                        "error": "Disposable Unreal fixture cleanup failed.",
                        "fixture": fixture,
                        "fixture_result": fixture_result,
                        "cleanup_response": cleanup_response,
                        "cleanup_result": cleanup_result,
                    }
            return {
                "ok": True,
                "check": "unreal_disposable_operation_behavior_readback",
                "callable_response": response,
                "fixture": fixture,
                "fixture_result": fixture_result,
                "cleanup_result": cleanup_result,
            }
        return {"ok": True, "check": "unreal_live_callable_readback", "response": response}

    def _replan(self, job: AcquisitionJob) -> dict[str, Any]:
        classifier = self._route_classifier
        if classifier is None:
            from tech_connector.services.prompt.prompt_route_service import classify_prompt_route

            classifier = classify_prompt_route
        prompt = job.original_request
        if job.context_addenda:
            prompt += "\n\nAdditional context:\n- " + "\n- ".join(job.context_addenda)
        for repair_attempt in range(0, 3):
            decision = classifier(prompt)
            data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
            gaps = list(data.get("capability_gaps") or [])
            gap_remains = (
                self._gap_operation(job) in gaps
                or str(data.get("operation_mode") or "") == "acquire_then_resume"
            )
            if not gap_remains:
                return {
                    "ok": True,
                    "evidence": data,
                    "resume_operation": job.plan.get("resume_operation"),
                    "repair_attempts": repair_attempt,
                }
            if repair_attempt >= 2:
                rollback = self._rollback_applied_sessions()
                return {
                    "ok": False,
                    "error": "Replanning still reports the acquired capability as missing after automatic repair.",
                    "evidence": data,
                    "rollback": rollback,
                }
            self._state["repair_context"] = [
                "The original request still routes to capability acquisition after implementation. "
                f"Ensure `{self._gap_operation(job)}` is registered in the canonical operation inventory and resolves to the callable."
            ]
            repaired = self._implement(job)
            if not repaired.get("ok"):
                rollback = self._rollback_applied_sessions()
                return {**repaired, "rollback": rollback}
            validated = self._validate(job)
            if not validated.get("ok"):
                if validated.get("pause_required"):
                    return validated
                rollback = self._rollback_applied_sessions()
                return {**validated, "rollback": rollback}

        return {"ok": False, "error": "Replanning ended unexpectedly."}

    def _repair_directives(self, errors: list[str], job: AcquisitionJob) -> str:
        lowered = "\n".join(str(item) for item in errors).lower()
        directives = [
            "\n\nMandatory bounded repair rules:",
            "- Preserve valid behavior from the prior candidate while correcting every listed failure.",
            "- Prefer replace_symbol/insert_before_symbol/insert_after_symbol over rewriting an entire file.",
        ]
        if "docstring" in lowered:
            directives.append("- Add a useful docstring directly inside every reported new public callable.")
        if "focused test" in lowered or "test file" in lowered:
            test_paths = [
                path for path in self._owner_paths(job)
                if path.name.startswith("test_") and path.suffix == ".py"
            ]
            directives.append(
                "- Add or update a focused unittest in this exact evidence-backed test owner: "
                + (str(test_paths[0]) if test_paths else "tech_connector/examples/tests")
            )
            directives.append("- The returned changes array is invalid unless it includes that focused test change.")
        if "indexed python symbol was not found" in lowered:
            anchors = self._focused_test_anchors(job)
            if anchors:
                directives.append(
                    "- Use insert_after_symbol with one of these exact indexed test anchors: "
                    + ", ".join(anchors[:6])
                )
        return "\n".join(directives)

    def _focused_test_anchors(self, job: AcquisitionJob) -> list[str]:
        anchors: list[str] = []
        for path in self._owner_paths(job):
            if not path.name.startswith("test_") or path.suffix != ".py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
            except Exception:
                continue
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                methods = [child.name for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
                relevant = [name for name in methods if "niagara" in name.lower()] or methods
                anchors.extend(f"{node.name}.{name}" for name in relevant[:4])
        return anchors

    def _owner_paths(self, job: AcquisitionJob) -> list[Path]:
        operation = self._gap_operation(job)
        namespace = operation.partition(".")[0].strip().lower()
        host = str(job.plan.get("host") or "unreal").strip().lower()
        candidates: list[Path] = []
        if namespace:
            candidates.extend([
                self.project_root / f"{host}_tools" / f"{namespace}.py",
                self.project_root / "tech_connector" / "services" / host / f"{namespace}.py",
            ])
        if host == "unreal":
            candidates.append(
                self.project_root / "tech_connector" / "services" / "unreal" / "unreal_operation_service.py"
            )
            candidates.append(
                self.project_root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp"
            )
            plugin_private_root = (
                self.project_root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Private"
            )
            candidates.extend(sorted(plugin_private_root.glob("AIStudioBridgeLibrary*.inl")))
            candidates.append(
                self.project_root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "Public" / "AIStudioBridgeLibrary.h"
            )
            candidates.append(
                self.project_root / "plugins" / "AIStudioBridge" / "Source" / "AIStudioBridge" / "AIStudioBridge.Build.cs"
            )
            candidates.append(
                self.project_root / "examples" / "tech_connector" / "tests" / "test_unreal_execution_pipeline.py"
            )
            resume = str(job.plan.get("resume_operation") or "")
            try:
                from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS

                function_path = str(getattr(UNREAL_OPERATIONS.get(resume), "function", "") or "")
                module_name = function_path.rpartition(".")[0]
                if module_name:
                    module_path = self.project_root / (module_name.replace(".", "/") + ".py")
                    candidates.insert(0, module_path)
            except Exception:
                pass
        paths = list(dict.fromkeys(path.resolve() for path in candidates if path.exists()))
        contract = dict(job.plan.get("requested_behavior_contract") or {})
        if contract.get("required_implementation_layer") == "reflected_cpp_bridge":
            def priority(path: Path) -> tuple[int, str]:
                if path.suffix.lower() in {".cpp", ".cc"}:
                    return (0, str(path))
                if path.suffix.lower() in {".h", ".hpp"}:
                    return (1, str(path))
                if path.name.endswith(".Build.cs"):
                    return (2, str(path))
                if path == self.project_root / f"{host}_tools" / f"{namespace}.py":
                    return (3, str(path))
                if path.name == "unreal_operation_service.py":
                    return (4, str(path))
                if path.name.startswith("test_"):
                    return (6, str(path))
                return (5, str(path))

            paths.sort(key=priority)
        return paths

    def _build_plan(self, objective: str, job: AcquisitionJob | None = None) -> Any:
        builder = self._plan_builder
        if builder is None:
            from tech_connector.services.project_edit_agent_service import build_project_edit_agent_request

            builder = build_project_edit_agent_request
        owner_paths = self._owner_paths(job) if job is not None else []
        active_path = str(owner_paths[0]) if owner_paths else self.active_path
        if owner_paths:
            objective += (
                "\n\nEvidence-backed domain ownership candidates:\n- "
                + "\n- ".join(str(path) for path in owner_paths)
                + "\nKeep implementation and registration inside these owners unless indexed imports prove another project-local owner is required."
            )
        plan = builder(objective, active_path=active_path, limit=12)
        if owner_paths:
            owner_keys = {str(path).casefold() for path in owner_paths}
            current_best = str((getattr(plan, "discovery", {}) or {}).get("best_target", {}).get("path") or "")
            if current_best.casefold() not in owner_keys:
                discovery = self._owner_discovery(owner_paths, job)
                plan.discovery = discovery
                try:
                    from tech_connector.services.project_service import format_edit_target_context

                    plan.discovery_context = format_edit_target_context(discovery)
                except Exception:
                    plan.discovery_context = "\n".join(str(path) for path in owner_paths)
            evidence = self._owner_source_evidence(owner_paths, job)
            if evidence:
                plan.capability_source_evidence = evidence
        return plan

    def _owner_source_evidence(self, owner_paths: list[Path], job: AcquisitionJob | None) -> str:
        operations = [
            self._gap_operation(job) if job is not None else "",
            str(job.plan.get("resume_operation") or "") if job is not None else "",
        ]
        terms = {
            term.casefold()
            for operation in operations
            for term in operation.replace(".", "_").split("_")
            if len(term) >= 4
        }
        terms.update({"niagara", "capability_gaps", "cpp_body_required"})
        blocks: list[str] = []
        budget = 7500
        for path in owner_paths:
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            excerpts: list[tuple[int, int, str]] = []
            if path.suffix.lower() == ".py":
                try:
                    tree = ast.parse(source, filename=str(path))
                    for node in tree.body:
                        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            continue
                        segment = ast.get_source_segment(source, node) or ""
                        score = sum(8 for term in terms if term in node.name.casefold())
                        score += sum(min(segment.casefold().count(term), 3) for term in terms)
                        if score:
                            excerpts.append((score, int(getattr(node, "lineno", 1)), segment))
                except Exception:
                    excerpts = []
            else:
                lines = source.splitlines()
                hits = [
                    index for index, line in enumerate(lines)
                    if any(term in line.casefold() for term in terms)
                ]
                used: list[tuple[int, int]] = []
                for hit in hits[:8]:
                    start, end = max(0, hit - 25), min(len(lines), hit + 55)
                    if any(start < prior_end and end > prior_start for prior_start, prior_end in used):
                        continue
                    used.append((start, end))
                    excerpts.append((10, start + 1, "\n".join(lines[start:end])))
                    if len(used) >= 2:
                        break
            for _score, line, segment in sorted(excerpts, key=lambda item: -item[0])[:3]:
                excerpt = segment[:2600]
                block = f"File: {path}:{line}\n{excerpt}"
                if len("\n\n".join([*blocks, block])) > budget:
                    continue
                blocks.append(block)
        return "\n\n".join(blocks)

    def _owner_discovery(self, owner_paths: list[Path], job: AcquisitionJob | None) -> dict[str, Any]:
        needles = {
            value.casefold()
            for operation in (
                self._gap_operation(job) if job is not None else "",
                str(job.plan.get("resume_operation") or "") if job is not None else "",
            )
            for value in operation.replace(".", "_").split("_")
            if len(value) >= 4
        }
        candidates = []
        for rank, path in enumerate(owner_paths):
            symbols: list[dict[str, Any]] = []
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(path))
                nodes = [
                    node for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                ]
                nodes.sort(
                    key=lambda node: (
                        not any(needle in node.name.casefold() for needle in needles),
                        int(getattr(node, "lineno", 0)),
                    )
                )
                for node in nodes[:16]:
                    symbols.append({
                        "name": node.name,
                        "qualname": node.name,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                        "signature": node.name,
                        "start_line": int(getattr(node, "lineno", 0)),
                        "end_line": int(getattr(node, "end_lineno", 0)),
                        "source": ast.get_source_segment(source, node) or "",
                        "path": str(path),
                        "source_scope": "project",
                    })
            except Exception:
                symbols = []
            candidates.append({
                "path": str(path),
                "score": 100 - rank,
                "symbols": symbols,
                "chunks": [],
                "source_scope": "project",
                "scope_score": 100,
            })
        return {
            "query": self._objective(job) if job is not None else "capability implementation",
            "project_roots": [str(self.project_root)],
            "confidence": "high",
            "best_target": candidates[0],
            "candidates": candidates,
            "targets": candidates,
            "errors": [],
        }

    def _build_stages(self, plan: Any) -> list[Any]:
        builder = self._stage_builder
        if builder is None:
            from tech_connector.services.project_edit_agent_service import build_project_edit_model_stages

            builder = build_project_edit_model_stages
        stages = list(builder(plan) or [])
        for stage in stages:
            if str(getattr(stage, "key", "")) in {"patch_generation", "patch_repair", "syntax_repair"}:
                self._promote_code_stage(stage, profile="standard")
        return stages

    @staticmethod
    def _promote_code_stage(stage: Any, *, profile: str) -> None:
        stage.model_tier = "local_code"
        stage.coder_preference = profile
        if profile == "quality":
            stage.num_ctx = max(8192, int(getattr(stage, "num_ctx", 0) or 0))
            stage.num_predict = min(1400, max(1000, int(getattr(stage, "num_predict", 0) or 0)))
            stage.timeout = min(180, max(120, int(getattr(stage, "timeout", 0) or 0)))
        else:
            stage.num_ctx = max(6144, int(getattr(stage, "num_ctx", 0) or 0))
            stage.num_predict = min(1100, max(800, int(getattr(stage, "num_predict", 0) or 0)))
            stage.timeout = min(120, max(90, int(getattr(stage, "timeout", 0) or 0)))

    def _preview(self, output: str, job: AcquisitionJob) -> Any:
        previewer = self._previewer
        if previewer is None:
            from tech_connector.services.project_edit_agent_service import preview_project_edit_agent_response

            previewer = preview_project_edit_agent_response
        return previewer(output, project_root=str(self.project_root), request_prompt=self._objective(job))

    def _apply(self, output: str, job: AcquisitionJob) -> Any:
        applier = self._applier
        if applier is None:
            from tech_connector.services.project_edit_agent_service import apply_project_edit_agent_response

            applier = apply_project_edit_agent_response
        return applier(output, project_root=str(self.project_root), validate=True, request_prompt=self._objective(job))

    def _validate_in_temp(self, preview: Any) -> dict[str, Any]:
        validator = self._temp_validator
        if validator is None:
            from tech_connector.services.code_operation_service import validate_patch_in_temp_workspace

            validator = validate_patch_in_temp_workspace
        patch_files = []
        py_paths = []
        cpp_paths = []
        for item in list(getattr(preview, "changes", []) or []):
            path = Path(str(item.get("path") or "")).resolve()
            try:
                relative = path.relative_to(self.project_root).as_posix()
            except ValueError:
                return {"ok": False, "errors": [f"patch_path_outside_project:{path}"]}
            patch_files.append({"path": relative, "content": str(item.get("after") or "")})
            if relative.endswith(".py"):
                py_paths.append(relative)
            if Path(relative).suffix.lower() in {".cpp", ".cc", ".c", ".h", ".hpp", ".cs", ".uplugin"}:
                cpp_paths.append(relative)
        commands = [["python", "-m", "py_compile", *py_paths]] if py_paths else []
        focused_tests = [
            path[:-3].replace("/", ".").replace("\\", ".")
            for path in py_paths
            if Path(path).name.startswith("test_")
        ]
        if focused_tests:
            commands.append(["python", "-m", "unittest", *focused_tests])
        copy_paths = ["tech_connector", "unreal_tools", "tech_connector/examples/tests"]
        timeout_seconds = 30
        if cpp_paths:
            run_uat = self._unreal_run_uat()
            plugin_descriptor = self.project_root / "plugins" / "AIStudioBridge" / "AIStudioBridge.uplugin"
            if run_uat is None or not plugin_descriptor.exists():
                return {
                    "ok": False,
                    "errors": ["unreal_cpp_patch_requires_disposable_buildplugin_validation"],
                }
            copy_paths.append("plugins/AIStudioBridge")
            commands.append([
                str(run_uat),
                "BuildPlugin",
                "-Plugin={workspace}/plugins/AIStudioBridge/AIStudioBridge.uplugin",
                "-Package={workspace}/plugin_build",
                "-Rocket",
            ])
            timeout_seconds = 900
        return validator(
            source_root=self.project_root,
            patch_files=patch_files,
            copy_paths=copy_paths,
            validation_commands=commands,
            timeout_seconds=timeout_seconds,
            keep_workspace=True,
        )

    def _unreal_run_uat(self) -> Path | None:
        root = self._unreal_engine_root()
        if root is not None:
            path = root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
            if path.is_file():
                return path
        return None

    def _unreal_engine_root(self) -> Path | None:
        candidates = []
        configured = str(
            self.settings.get("unreal_engine_root")
            or self.settings.get("engine_root")
            or ""
        ).strip()
        if configured:
            candidates.append(Path(configured))
        candidates.extend([
            Path("C:/Program Files/Epic Games/UE_5.8"),
            Path("C:/Program Files/Epic Games/UE_5.7"),
        ])
        for root in candidates:
            if (root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat").is_file():
                return root
        return None

    def _unreal_host_api_evidence(self, job: AcquisitionJob) -> str:
        if str(job.plan.get("host") or "").lower() != "unreal":
            return ""
        root = self._unreal_engine_root()
        namespace = self._gap_operation(job).partition(".")[0].lower()
        if root is None:
            return ""
        engine = root / "Engine"
        domain_roots = {
            "niagara": [engine / "Plugins" / "FX" / "Niagara" / "Source"],
            "anim_graph": [
                engine / "Source" / "Editor" / "AnimGraph",
                engine / "Source" / "Editor" / "AnimationBlueprintEditor",
            ],
            "blueprint": [
                engine / "Source" / "Editor" / "BlueprintGraph",
                engine / "Source" / "Editor" / "Kismet",
                engine / "Source" / "Editor" / "UnrealEd",
            ],
            "control_rig": [engine / "Plugins" / "Animation" / "ControlRig" / "Source"],
            "retarget": [engine / "Plugins" / "Animation" / "IKRig" / "Source"],
            "motion_matching": [engine / "Plugins" / "Animation" / "PoseSearch" / "Source"],
            "physics": [
                engine / "Source" / "Runtime" / "Engine",
                engine / "Source" / "Runtime" / "PhysicsCore",
                engine / "Source" / "Editor" / "PhysicsAssetEditor",
            ],
            "material": [
                engine / "Source" / "Runtime" / "Engine" / "Classes" / "Materials",
                engine / "Source" / "Editor" / "MaterialEditor",
            ],
            "asset": [engine / "Source" / "Editor" / "UnrealEd"],
        }
        wrapper_contract = self._canonical_cpp_wrapper_contract(job)
        operation_leaf = self._gap_operation(job).partition(".")[2]
        operation_terms = [
            value
            for value in re.split(r"[^a-zA-Z0-9]+", operation_leaf)
            if len(value) >= 4 and value.lower() not in {"create", "delete", "remove", "property"}
        ]
        canonical_needles = {
            "niagara": ("AddEmitterHandle", "InitializeEmitter", "AddModuleIfMissing", "AddScriptModuleToStack"),
            "anim_graph": ("FBlueprintEditorUtils", "UAnimGraphNode_StateMachine"),
            "blueprint": ("FBlueprintEditorUtils", "FKismetEditorUtilities"),
            "control_rig": ("UControlRigBlueprint", "UControlRigBlueprintFactory"),
            "retarget": ("UIKRigDefinition", "UIKRetargeter", "UIKRigController"),
            "motion_matching": ("UPoseSearchDatabase", "UPoseSearchSchema"),
            "physics": ("UPhysicsAsset", "FPhysicsAssetUtils"),
            "material": ("UMaterial", "UMaterialExpression"),
            "asset": ("FAssetToolsModule", "UEditorAssetLibrary"),
        }
        needles = list(canonical_needles.get(namespace, ()))
        wrapper_function = str(wrapper_contract.get("wrapper_function") or "")
        if wrapper_function:
            needles.append(wrapper_function)
        needles.extend(operation_terms)
        source_roots = [path for path in domain_roots.get(namespace, []) if path.exists()]
        if not source_roots or not needles:
            return ""

        requests: list[tuple[Path, tuple[str, ...]]] = []
        seen_paths: set[Path] = set()
        for source_root in source_roots:
            candidates = (
                [source_root]
                if source_root.is_file()
                else list(source_root.rglob("*.h")) + list(source_root.rglob("*.cpp"))
            )
            for path in candidates[:1800]:
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                matched_needles = tuple(needle for needle in needles if needle.lower() in text.lower())
                if matched_needles:
                    requests.append((path, matched_needles))
                if len(requests) >= 40:
                    break
            if len(requests) >= 40:
                break
        blocks: list[str] = []
        evidence_files: list[str] = []
        for path, needles in requests:
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            matched: set[int] = set()
            for index, line in enumerate(lines):
                if not any(needle.lower() in line.lower() for needle in needles):
                    continue
                start = max(0, index - 8)
                end = min(len(lines), index + 18)
                if any(abs(index - prior) < 20 for prior in matched):
                    continue
                matched.add(index)
                blocks.append(f"Engine file: {path}:{start + 1}\n" + "\n".join(lines[start:end]))
                if len(blocks) >= 18:
                    break
            if matched:
                evidence_files.append(str(path))
            if len(blocks) >= 18:
                break
        self._state["host_api_evidence_files"] = evidence_files
        return "\n\n".join(blocks)[:14000]

    def _validate_operation(self, operation: str) -> dict[str, Any]:
        if self._operation_validator:
            return dict(self._operation_validator(operation) or {})
        try:
            from tech_connector.services.unreal.feature_planning_service import _local_operation_status

            return dict(_local_operation_status(operation) or {})
        except Exception as exc:
            return {"operation": operation, "registered": False, "callable_found": False, "reason": str(exc)}

    def _model_for(self, stage: Any) -> str:
        from tech_connector.services.project_edit_agent_service import model_for_project_edit_stage

        return model_for_project_edit_stage(stage, self.settings)

    @staticmethod
    def _default_model_query(stage: Any, model: str, prompt: str | None = None) -> str:
        from tech_connector.knowledge.search import query_ollama_text

        return str(query_ollama_text(
            model=model,
            system_prompt=stage.system_prompt,
            user_prompt=prompt if prompt is not None else stage.user_prompt,
            num_ctx=stage.num_ctx,
            num_predict=stage.num_predict,
            timeout=stage.timeout,
            prefer_coder=stage.prefer_coder,
            coder_preference=stage.coder_preference,
            think=False,
            response_format=stage.response_format or None,
            temperature=0.0,
        ) or "")

