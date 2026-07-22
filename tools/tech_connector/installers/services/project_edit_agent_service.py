"""Project-aware edit agent orchestration.

This module ties together existing Tech Connector pieces:

- project edit target discovery from :mod:`services.project_service`
- XML file-change parsing and resilient replacement from :mod:`knowledge.search`
- persistent undo sessions from :mod:`services.change_history_service`
- lightweight Python validation via ``py_compile``

It does not call an LLM by itself. The UI/router can use
``build_project_edit_agent_request`` to prepare the grounded prompt, pass that to
the selected coding model, then feed the model text into
``apply_project_edit_agent_response``.
"""

from __future__ import annotations

import py_compile
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectEditPlan:
    prompt: str
    discovery: dict[str, Any]
    discovery_context: str
    model_prompt: str
    active_path: str = ""
    intelligence_packet: dict[str, Any] = field(default_factory=dict)
    adaptive_plan: dict[str, Any] = field(default_factory=dict)
    domain_experts: list[dict[str, Any]] = field(default_factory=list)
    success_contract: list[str] = field(default_factory=list)
    stages: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ProjectEditPromptStage:
    key: str
    label: str
    system_prompt: str
    user_prompt: str
    model_tier: str = "local_code"
    num_ctx: int = 8192
    num_predict: int = 1200
    timeout: int = 180
    resource_lane: str = "local_model_serial"
    no_progress_seconds: int = 30
    prefer_coder: bool = True


@dataclass
class ProjectEditApplyResult:
    ok: bool
    status: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    validation: list[dict[str, Any]] = field(default_factory=list)
    change_session_path: str = ""
    errors: list[str] = field(default_factory=list)


def build_project_edit_agent_request(
    prompt: str,
    *,
    active_path: str | None = None,
    limit: int = 8,
) -> ProjectEditPlan:
    """Build the grounded edit request sent to the coding model."""

    from services.project_service import (
        build_project_edit_target_prompt,
        discover_edit_targets,
        format_edit_target_context,
    )

    try:
        discovery = discover_edit_targets(prompt, active_path=active_path, limit=limit)
    except Exception as exc:
        discovery = _fallback_project_edit_discovery(
            prompt,
            active_path=active_path,
            error=exc,
        )
    discovery_context = format_edit_target_context(discovery)
    intelligence_packet = _build_project_edit_intelligence_packet(
        prompt,
        active_path=active_path,
        limit=limit,
    )
    adaptive_plan = build_code_agent_adaptive_plan(
        prompt,
        discovery=discovery,
        active_path=active_path,
        intelligence_packet=intelligence_packet,
    )
    domain_experts = select_code_agent_experts(
        prompt,
        discovery=discovery,
        active_path=active_path,
    )
    model_prompt = build_project_edit_target_prompt(
        question=prompt,
        discovery_context=discovery_context,
        active_path=active_path,
    )
    adaptive_section = render_code_agent_adaptive_plan(adaptive_plan)
    if adaptive_section:
        model_prompt = f"{model_prompt}\n\n{adaptive_section}\n"
    expert_section = render_code_agent_expert_context(domain_experts)
    if expert_section:
        model_prompt = f"{model_prompt}\n\n{expert_section}\n"
    intelligence_section = _render_project_edit_intelligence_packet(intelligence_packet)
    if intelligence_section:
        model_prompt = f"{model_prompt}\n\n{intelligence_section}\n"
    return ProjectEditPlan(
        prompt=prompt,
        active_path=active_path or "",
        discovery=discovery,
        discovery_context=discovery_context,
        intelligence_packet=intelligence_packet,
        adaptive_plan=adaptive_plan,
        domain_experts=domain_experts,
        success_contract=list(adaptive_plan.get("success_contract") or []),
        model_prompt=model_prompt,
        stages=[
            _stage("request", "Accepted project edit request"),
            _stage("code_intelligence", "Built IDE-style code intelligence packet"),
            _stage("target_discovery", "Gathered indexed target evidence"),
            _stage("expert_selection", "Selected code and domain expert lenses"),
            _stage("adaptive_planning", "Built objective-to-output code plan"),
            _stage("planning", "Prepared grounded coding-model prompt"),
        ],
    )


def _build_project_edit_intelligence_packet(
    prompt: str,
    *,
    active_path: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    try:
        from services.code_intelligence_service import build_code_intelligence_packet

        return build_code_intelligence_packet(
            prompt,
            active_path=active_path,
            limit=max(8, min(int(limit or 8) * 3, 30)),
            include_repo_map=True,
        )
    except Exception as exc:
        return {
            "objective": prompt or "",
            "active_path": active_path or "",
            "mode": "unknown",
            "scope": "project",
            "terms": [],
            "repo_map": {},
            "symbols": [],
            "usages": {},
            "project_context": "",
            "sufficiency": {
                "answerable": False,
                "confidence": 0.0,
                "reasons": ["code_intelligence_failed"],
                "missing_requirements": [str(exc)],
            },
            "validation_plan": [],
            "deterministic_answer": "",
            "can_answer_without_model": False,
        }


def _render_project_edit_intelligence_packet(packet: dict[str, Any]) -> str:
    try:
        from services.code_intelligence_service import render_code_intelligence_packet

        return render_code_intelligence_packet(packet, max_context_chars=4500)
    except Exception:
        return ""


def _fallback_project_edit_discovery(
    prompt: str,
    *,
    active_path: str | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    """Build minimal target evidence when the project index is unavailable."""

    target = {
        "path": active_path or "",
        "score": 1 if active_path else 0,
        "symbols": [],
        "chunks": [],
    }
    return {
        "question": prompt,
        "terms": re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt or "")[:12],
        "scope": "project",
        "project_roots": [],
        "best_target": target if active_path else {},
        "targets": [target] if active_path else [],
        "confidence": "low" if active_path else "none",
        "warnings": [
            "Project index target discovery was unavailable; using active file fallback.",
            str(error or ""),
        ],
    }


def build_code_agent_adaptive_plan(
    prompt: str,
    *,
    discovery: dict[str, Any] | None = None,
    active_path: str | None = None,
    intelligence_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, adaptive code-agent plan for an objective."""

    discovery = dict(discovery or {})
    intelligence_packet = dict(intelligence_packet or {})
    confidence = str(discovery.get("confidence") or "unknown")
    best_target = dict(discovery.get("best_target") or {})
    target_path = str(best_target.get("path") or active_path or "")
    requires_confirmation = confidence not in {"high", "medium"}
    target_available = bool(target_path)
    decision = {
        "route": "project_edit",
        "provider": "project_index",
        "confidence": 0.9 if confidence == "high" else 0.7 if confidence == "medium" else 0.45,
        "intent_category": "code_edit",
        "mutation_scope": "code_change",
        "risk_level": "medium" if confidence in {"high", "medium"} else "high",
        "requires_plan": True,
        "requires_confirmation": requires_confirmation,
        "can_execute_directly": target_available and not requires_confirmation,
        "context_resolvers": [
            "code_intelligence_packet",
            "repo_map",
            "symbol_lookup",
            "references_usages",
            "active_file_context",
            "validation_planner",
        ],
        "deterministic_steps": [
            "build_code_intelligence_packet",
            "build_repo_map",
            "search_symbols_docstrings_and_signatures",
            "search_references_usages_imports_and_calls",
            "discover_edit_targets",
            "format_edit_target_context",
            "parse_multi_file_changes",
            "replace_content_resilient",
            "save_change_session",
            "plan_validation_for_paths",
            "py_compile_or_targeted_tests",
        ],
        "capability_gaps": [] if target_available else ["verified edit target"],
    }
    try:
        from services.goal_gap_planning_service import build_goal_gap_plan
        from services.multi_stage_reasoning_service import build_reasoning_pipeline

        gap_plan = build_goal_gap_plan(prompt, decision)
        reasoning = build_reasoning_pipeline(prompt, decision)
    except Exception:
        gap_plan = {}
        reasoning = {}

    return {
        "framework": "adaptive_code_agent_v1",
        "objective": (prompt or "").strip() or "Complete requested code objective",
        "target_confidence": confidence,
        "best_target": target_path,
        "requires_confirmation": requires_confirmation,
        "deterministic_steps": list(decision.get("deterministic_steps") or []),
        "code_intelligence": {
            "mode": intelligence_packet.get("mode"),
            "scope": intelligence_packet.get("scope"),
            "can_answer_without_model": intelligence_packet.get("can_answer_without_model"),
            "terms": list(intelligence_packet.get("terms") or [])[:12],
            "validation_plan": list(intelligence_packet.get("validation_plan") or [])[:8],
        },
        "reasoning_pipeline": reasoning,
        "capability_gap_plan": gap_plan,
        "success_contract": [
            "Produce a successful output for the user objective, not just a detached snippet.",
            "Run deterministic code intelligence before model synthesis: repo map, symbol lookup, references, usages, tests, structured patching, and validation.",
            "Reuse existing project functions, classes, services, and helpers when indexed evidence shows they fit.",
            "Decompose vague or multi-step objectives into inspect, plan, edit, validate, repair, and report stages.",
            "If a direct edit is unsafe, ask for the smallest missing decision and provide the best evidenced default.",
            "For every changed file, provide XML patch tags that can be previewed and applied by the diff system.",
            "After edits, define concrete validation and fallback or rollback steps.",
            "If validation fails, diagnose and repair only from evidence; otherwise report partial completion clearly.",
        ],
        "required_outputs": [
            "project facts used",
            "target decision with confidence",
            "implementation stages",
            "reused functions/classes/helpers",
            "exact patch tags or an explicit blocker",
            "validation commands/results",
            "rollback or recovery path",
            "final outcome status",
        ],
        "fallback_policy": [
            "Do not fabricate missing APIs or paths.",
            "If the target is ambiguous, return a clarification request plus the likely target and why.",
            "If no internal function fits, identify the gap and suggest creating a reusable helper in an appropriate project folder.",
            "If an edit cannot be safely completed, stop before mutation and report what evidence is missing.",
        ],
    }


def select_code_agent_experts(
    prompt: str,
    *,
    discovery: dict[str, Any] | None = None,
    active_path: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Select existing domain experts that should advise a project code edit."""

    discovery = dict(discovery or {})
    host = _infer_code_agent_host(prompt, discovery, active_path)
    expert_prompt = " ".join(
        [
            str(prompt or ""),
            str(active_path or ""),
            str((discovery.get("best_target") or {}).get("path") or ""),
            " ".join(str(item.get("path") or "") for item in discovery.get("candidates") or [] if isinstance(item, dict)),
        ]
    )
    decision = {
        "route": "code_edit",
        "intent_category": "project_edit",
        "host": host,
        "mutation_scope": "code_change",
        "provider": "project_index",
    }
    try:
        from services.domain_expert_service import select_domain_experts

        return select_domain_experts(expert_prompt, decision, limit=limit)
    except Exception:
        return []


def render_code_agent_expert_context(experts: list[dict[str, Any]] | None) -> str:
    """Render a compact advisory packet for code-generation prompts."""

    experts = list(experts or [])
    if not experts:
        return ""
    lines = [
        "Code/domain expert advisory context:",
        "Experts advise only; existing deterministic services still own execution.",
    ]
    for expert in experts[:5]:
        lines.append(
            f"- {expert.get('label') or expert.get('domain')} "
            f"[{expert.get('domain')}; mode={expert.get('mode')}; confidence={expert.get('confidence')}]"
        )
        responsibilities = list(expert.get("responsibilities") or [])[:2]
        required_context = list(expert.get("required_context") or [])[:3]
        validation = list(expert.get("validation_steps") or [])[:3]
        brief = list(expert.get("expert_brief") or [])[:2]
        if responsibilities:
            lines.append("  responsibilities: " + " | ".join(str(item) for item in responsibilities))
        if required_context:
            lines.append("  required context: " + ", ".join(str(item) for item in required_context))
        if validation:
            lines.append("  validation: " + " | ".join(str(item) for item in validation))
        if brief:
            lines.append("  senior brief: " + " | ".join(str(item) for item in brief))
    return "\n".join(lines)


def render_code_agent_adaptive_plan(plan: dict[str, Any] | None) -> str:
    """Render adaptive code-agent rules for the coding-model prompt."""

    if not plan:
        return ""
    lines = [
        "Adaptive code agent execution plan:",
        f"- Framework: {plan.get('framework', '')}",
        f"- Objective: {plan.get('objective', '')}",
        f"- Best target: {plan.get('best_target') or '(none)'}",
        f"- Target confidence: {plan.get('target_confidence', '')}",
        f"- Requires confirmation before mutation: {bool(plan.get('requires_confirmation'))}",
        "",
        "Success contract:",
    ]
    lines.extend(f"- {item}" for item in list(plan.get("success_contract") or []))
    deterministic_steps = list(plan.get("deterministic_steps") or [])
    if deterministic_steps:
        lines.append("")
        lines.append("Deterministic IDE-agent steps before model synthesis:")
        lines.extend(f"- {item}" for item in deterministic_steps)
    lines.append("")
    lines.append("Required output sections:")
    lines.extend(f"- {item}" for item in list(plan.get("required_outputs") or []))
    lines.append("")
    lines.append("Fallback policy:")
    lines.extend(f"- {item}" for item in list(plan.get("fallback_policy") or []))
    reasoning = dict(plan.get("reasoning_pipeline") or {})
    stages = list(reasoning.get("stages") or [])
    if stages:
        lines.append("")
        lines.append("Adaptive stages to follow:")
        for stage in stages[:8]:
            gates = "; ".join(stage.get("verification_gate") or [])
            lines.append(f"- {stage.get('title')}: {stage.get('responsibility')}")
            if gates:
                lines.append(f"  Gate: {gates}")
    gap = dict(plan.get("capability_gap_plan") or {})
    missing = list(gap.get("missing_links") or [])
    if missing:
        lines.append("")
        lines.append("Capability gaps to resolve before claiming success:")
        for item in missing[:5]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('label') or item.get('to') or item}")
            else:
                lines.append(f"- {item}")
    return "\n".join(lines)


def build_project_edit_model_stages(plan: ProjectEditPlan) -> list[ProjectEditPromptStage]:
    """Build smaller LLM stages so large code edits do not rely on one huge call."""

    compact_discovery = _compact_discovery_evidence(plan)
    discovery = _trim_text(plan.discovery_context, 5000)
    adaptive = _trim_text(render_code_agent_adaptive_plan(plan.adaptive_plan), 2200)
    experts = _trim_text(render_code_agent_expert_context(plan.domain_experts), 1800)
    objective = plan.prompt
    target_path = str((plan.discovery.get("best_target") or {}).get("path") or plan.active_path or "")
    common_system = (
        "You are a senior Python/PySide/Maya/Unreal tools engineer inside Tech Connector. "
        "Use only the supplied project evidence. Reuse existing functions, classes, and helpers. "
        "Do not invent files, APIs, imports, or call sites."
    )
    quick_plan_prompt = f"""User objective:
{objective}

Compact target evidence:
{compact_discovery}

Selected expert lenses:
{experts or '(none)'}

Stage task:
Create the first useful handoff quickly. Do not emit XML patches.

Required sections:
1. Intent and whether mutation is actually requested.
2. Best target or top candidate, with evidence.
3. Existing functions/classes/helpers to reuse.
4. Minimal next stage: search-only answer, implementation plan, or patch generation.
5. Blockers or missing context, if any.
"""
    patch_prompt = f"""User objective:
{objective}

Chosen target:
{target_path or '(none)'}

Focused target-discovery evidence:
{discovery}

Selected expert lenses:
{experts or '(none)'}

Adaptive execution contract:
{adaptive}

Stage task:
Produce the smallest safe patchable implementation that completes the objective, or explicitly stop with a blocker.

Rules:
- Reuse the original project function rather than duplicating it.
- Use project-local classes/helpers/patterns when evidence shows they fit.
- Keep changes narrow and testable.
- If target confidence is low or evidence is insufficient, do not invent. Return a blocker report.
- For every file change, use XML patch tags:
  <modify_file path="absolute/or/relative/path.py">
  <<<< ORIGINAL
  exact original block
  ====
  replacement block
  >>>>
  </modify_file>
- For new files only when clearly needed:
  <create_file path="relative/path.py">
  full file content
  </create_file>

Required report after patch tags:
1. What was changed.
2. Existing systems reused.
3. Verification to run.
4. Static vs runtime verification.
5. Rollback path.
"""
    stages = [
        ProjectEditPromptStage(
            key="target_selection_plan",
            label="Selecting target and first implementation plan",
            system_prompt=common_system,
            user_prompt=quick_plan_prompt,
            model_tier="local_plan",
            num_ctx=4096,
            num_predict=550,
            timeout=180,
            no_progress_seconds=25,
            prefer_coder=False,
        )
    ]
    if _project_edit_requires_patch(objective):
        stages.append(
            ProjectEditPromptStage(
                key="patch_generation",
                label="Generating patchable code changes",
                system_prompt=common_system,
                user_prompt=patch_prompt,
                model_tier="local_code",
                num_ctx=6144,
                num_predict=1600,
                timeout=300,
                no_progress_seconds=30,
                prefer_coder=True,
            )
        )
    return stages


def model_for_project_edit_stage(
    stage: ProjectEditPromptStage,
    settings: dict[str, Any] | None = None,
    *,
    selected_model: str | None = None,
) -> str:
    """Return the configured model for a project-edit stage.

    Reuses the existing router model tier settings instead of defining another
    model-routing table. Context-heavy planning stages can use a smaller plan
    model while patch/code generation can reserve the coder model.
    """

    settings = dict(settings or {})
    tier = (stage.model_tier or "").strip()
    if tier == "local_plan":
        model = settings.get("router_local_plan") or settings.get("plan_model") or settings.get("general_model")
    elif tier == "local_deep":
        model = settings.get("router_local_deep") or settings.get("model") or selected_model
    elif tier == "local_fast":
        model = settings.get("router_fast_llm_model") or settings.get("router_local_plan") or settings.get("general_model")
    elif tier == "local_code":
        model = settings.get("router_local_code") or settings.get("code_model")
    else:
        model = None
    return str(model or selected_model or settings.get("model") or "ollama:qwen2.5-coder:14b")


def _compact_discovery_evidence(plan: ProjectEditPlan) -> str:
    discovery = dict(plan.discovery or {})
    lines = [
        f"Active path: {plan.active_path or '(none)'}",
        f"Target confidence: {discovery.get('confidence') or 'unknown'}",
    ]
    best = discovery.get("best_target")
    if isinstance(best, dict) and best:
        lines.append("Best target:")
        lines.append(_format_candidate_line(best))
    candidates = [item for item in discovery.get("candidates") or [] if isinstance(item, dict)]
    if candidates:
        lines.append("Top candidates:")
        for item in candidates[:5]:
            lines.append(_format_candidate_line(item))
    if not best and not candidates:
        context = _trim_text(plan.discovery_context, 1800)
        if context:
            lines.append("Discovery context:")
            lines.append(context)
    return "\n".join(lines)


def _format_candidate_line(item: dict[str, Any]) -> str:
    name = item.get("name") or item.get("symbol") or item.get("label") or "(unnamed)"
    kind = item.get("kind") or item.get("type") or ""
    path = item.get("path") or item.get("file") or ""
    line = item.get("line") or item.get("lineno") or ""
    summary = str(item.get("summary") or item.get("signature") or item.get("text") or "")
    location = f"{path}:{line}" if path and line else str(path or "")
    parts = [str(name)]
    if kind:
        parts.append(f"kind={kind}")
    if location:
        parts.append(f"location={location}")
    if summary:
        parts.append(f"summary={_trim_text(summary, 220)}")
    return "- " + " | ".join(parts)


def _project_edit_requires_patch(prompt: str) -> bool:
    lower = (prompt or "").lower()
    if re.search(r"\b(do not edit|do not change|do not make changes|don't edit|no edits|without editing|explain how|plan only)\b", lower):
        return False
    if re.search(r"\b(what functions|which functions|where is|where are|list|show|explain|summarize|inspect|identify|determine|report what you find)\b", lower) and not re.search(
        r"\b(then|after that|and add|and create|implement|patch|modify|change|update|fix|wire|connect|build it|make it)\b",
        lower,
    ):
        return False
    return bool(
        re.search(
            r"\b(add|create|write|generate|implement|insert|improve|refactor|fix|update|patch|wire|connect|repair|make|build)\b",
            lower,
        )
    )


def preview_project_edit_agent_response(
    model_response: str,
    *,
    project_root: str | None = None,
) -> ProjectEditApplyResult:
    """Parse and resolve model-produced file changes without writing them."""

    changes, errors = _resolve_model_changes(model_response, project_root=project_root)
    return ProjectEditApplyResult(
        ok=not errors and bool(changes),
        status="preview_ready" if changes and not errors else "preview_failed",
        changes=changes,
        errors=errors or ([] if changes else ["No <modify_file> or <create_file> changes found."]),
    )


def apply_project_edit_agent_response(
    model_response: str,
    *,
    project_root: str | None = None,
    validate: bool = True,
) -> ProjectEditApplyResult:
    """Apply model-produced XML file changes, save undo, and run validation."""

    preview = preview_project_edit_agent_response(model_response, project_root=project_root)
    if not preview.ok:
        return preview

    pending = {
        item["path"]: {
            "action": item["action"],
            "original_content": item.get("before", ""),
            "new_content": item.get("after", ""),
            "current": item.get("after", ""),
        }
        for item in preview.changes
    }

    change_session_path = ""
    try:
        from services.change_history_service import create_change_session, save_change_session

        session = create_change_session(pending, summary="Project Edit Agent changes")
        change_session_path = str(save_change_session(session))
    except Exception as exc:
        preview.errors.append(f"Could not save undo session: {exc}")
        return ProjectEditApplyResult(
            ok=False,
            status="undo_session_failed",
            changes=preview.changes,
            errors=preview.errors,
        )

    write_errors: list[str] = []
    written: list[dict[str, Any]] = []
    for item in preview.changes:
        path = Path(item["path"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item.get("after", ""), encoding="utf-8")
            written.append(item)
        except Exception as exc:
            write_errors.append(f"{path}: {exc}")

    validation = _validate_changes(written) if validate else []
    validation_failed = [item for item in validation if not item.get("ok")]
    ok = not write_errors and not validation_failed
    return ProjectEditApplyResult(
        ok=ok,
        status="applied" if ok else "applied_with_validation_errors",
        changes=written,
        validation=validation,
        change_session_path=change_session_path,
        errors=write_errors + [str(item.get("message")) for item in validation_failed],
    )


def render_project_edit_agent_report(result: ProjectEditApplyResult) -> str:
    """Render a concise Codex-style report for chat."""

    lines = [
        "Project Edit Agent Report",
        f"Status: {result.status}",
        f"Outcome: {'complete' if result.ok else 'needs attention'}",
        "",
        "Files:",
    ]
    if not result.changes:
        lines.append("- No file changes were applied.")
    for item in result.changes:
        before = item.get("before", "")
        after = item.get("after", "")
        delta = _line_delta(before, after)
        lines.append(f"- {item.get('action')} {item.get('path')} ({delta})")
    if result.change_session_path:
        lines.extend(["", f"Undo session: {result.change_session_path}"])
    if result.validation:
        lines.append("")
        lines.append("Validation:")
        for item in result.validation:
            label = "passed" if item.get("ok") else "failed"
            lines.append(f"- {label}: {item.get('command') or item.get('path')} - {item.get('message')}")
    if result.errors:
        lines.append("")
        lines.append("Warnings / Errors:")
        lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines)


def validate_project_edit_paths(paths: list[str]) -> list[dict[str, Any]]:
    """Validate changed files using the same checks as the project edit agent."""

    return _validate_changes([{"path": path} for path in paths])


def _resolve_model_changes(
    model_response: str,
    *,
    project_root: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    from knowledge.search import parse_multi_file_changes, replace_content_resilient

    changes = parse_multi_file_changes(model_response or "", project_root or "")
    resolved: list[dict[str, Any]] = []
    errors: list[str] = []
    for change in changes:
        action = str(change.get("action") or "")
        path = str(change.get("path") or "")
        if not path:
            errors.append("Change is missing a path.")
            continue
        if action == "create":
            resolved.append(
                {
                    "action": "create",
                    "path": path,
                    "before": "",
                    "after": str(change.get("new_content") or ""),
                }
            )
            continue
        if action != "modify":
            errors.append(f"Unsupported change action for {path}: {action}")
            continue
        p = Path(path)
        if not p.exists():
            errors.append(f"Cannot modify missing file: {path}")
            continue
        before = p.read_text(encoding="utf-8", errors="replace")
        matched, after = replace_content_resilient(
            before,
            str(change.get("original_content") or ""),
            str(change.get("new_content") or ""),
        )
        if not matched:
            errors.append(f"Original block did not match: {path}")
            continue
        resolved.append({"action": "modify", "path": path, "before": before, "after": after})
    return resolved, errors


def _validate_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in changes:
        path = Path(str(item.get("path") or ""))
        if path.suffix.lower() != ".py":
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            results.append(
                {
                    "ok": True,
                    "path": str(path),
                    "command": f"py_compile {path.name}",
                    "message": "Python syntax check passed.",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "path": str(path),
                    "command": f"py_compile {path.name}",
                    "message": str(exc),
                }
            )
    return results


def _stage(key: str, label: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": "completed"}


def _trim_text(text: str, max_chars: int) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 80
    return text[:head].rstrip() + "\n\n... [middle omitted for staged prompt] ...\n\n" + text[-tail:].lstrip()


def _infer_code_agent_host(prompt: str, discovery: dict[str, Any], active_path: str | None) -> str:
    text = " ".join(
        [
            str(prompt or ""),
            str(active_path or ""),
            " ".join(str(root) for root in discovery.get("project_roots") or []),
            str((discovery.get("best_target") or {}).get("path") or ""),
        ]
    ).lower().replace("\\", "/")
    if "maya" in text or "cmds" in text or "/maya_tools/" in text:
        return "maya"
    if "unreal" in text or "blueprint" in text or "/unreal" in text:
        return "unreal"
    if "blender" in text or "/blender" in text:
        return "blender"
    if "houdini" in text:
        return "houdini"
    return "python"


def _line_delta(before: str, after: str) -> str:
    before_lines = len((before or "").splitlines())
    after_lines = len((after or "").splitlines())
    delta = after_lines - before_lines
    return f"{before_lines} -> {after_lines} lines, delta {delta:+d}"
