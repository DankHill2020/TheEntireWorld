"""Interaction-quality helpers for progressive execution and result cards."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tech_connector.services.engineering_reasoning_service import EngineeringReasoning


def build_execution_plan(decision: dict[str, Any], request: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    import re
    request = request or {}
    decision = decision or {}
    route = decision.get("route") or ""
    host = request.get("execution_environment") or decision.get("host") or ""
    target = request.get("callable_name") or decision.get("callable_name") or decision.get("target_identifier") or ""
    
    if not target or target == "operation":
        if route == "dcc_prototype":
            target = f"Generate {host.capitalize()} prototype script" if host else "Generate prototype script"
        else:
            target = "DCC operation"
            
    route_desc = {
        "dcc_prototype": "Prototype DCC automation script",
        "unreal_capability": "Execute Unreal Engine capability",
        "dcc_execute": "Execute DCC operation",
        "target_discovery": "Discover code change targets",
        "project_search": "Search project codebase",
        "project_health": "Check project health",
        "action_graph": "Execute multi-DCC workflow pipeline",
    }.get(route, route.replace("_", " "))
    
    host_desc = f"{host.capitalize()} connection" if host else "DCC connection"
    
    prompt = request.get("raw_request") or request.get("query") or request.get("text") or decision.get("query") or decision.get("text") or ""
    raw_steps = []
    if prompt:
        parts = re.split(r"\b(?:then|and|afterwards|next)\b|,", prompt)
        for part in parts:
            p = part.strip().strip(".!?,")
            if p and len(p) > 6 and not any(w in p.lower() for w in ("i want you", "please", "make sure")):
                raw_steps.append(p[0].upper() + p[1:])
                
    steps = [
        {"id": "route", "label": "Understand request", "status": "completed", "detail": route_desc},
        {"id": "resolve_callable", "label": "Resolve target operation", "status": "completed" if target else "pending", "detail": str(target)},
        {"id": "inspect_signature", "label": "Inspect parameter metadata", "status": "completed" if request.get("argument_schema") is not None else "pending"},
        {"id": "resolve_context", "label": "Verify host environment", "status": "completed" if host else "pending", "detail": host_desc},
    ]
    
    keyword_args = request.get("keyword_args") or decision.get("keyword_args") or {}
    if keyword_args:
        args_summary = ", ".join(f"{k}={repr(v)}" for k, v in keyword_args.items())
        steps.append({"id": "validate_arguments", "label": "Validate arguments", "status": "completed", "detail": args_summary})
    else:
        steps.append({"id": "validate_arguments", "label": "Validate arguments", "status": "blocked" if request.get("missing_slots") else "completed"})
        
    if raw_steps:
        for idx, r_step in enumerate(raw_steps, start=1):
            steps.append({
                "id": f"sub_step_{idx}",
                "label": f"Sub-step {idx}",
                "status": "pending",
                "detail": r_step
            })
    else:
        steps.append({"id": "execute", "label": "Execute operation", "status": "pending"})
        
    test_action = "Verify outputs in DCC scene"
    if host == "unreal":
        test_action = "Verify asset/blueprint is imported/created in Unreal Content Browser"
    elif host == "maya":
        test_action = "Verify rigging/node hierarchy in Maya Outliner"
    elif host == "blender":
        test_action = "Verify output files/scene collection in Blender"
    elif host == "substance_painter":
        test_action = "Verify layers and texture sets in Substance Painter"
    elif host == "motionbuilder":
        test_action = "Verify animation/character takes in MotionBuilder"
        
    steps.append({"id": "verify_outputs", "label": "How to verify/test", "status": "pending", "detail": test_action})
    steps.append({"id": "report", "label": "Report results", "status": "pending"})
    
    return steps


def update_execution_plan(plan: list[dict[str, Any]], *, status: str, result_type: str = "") -> list[dict[str, Any]]:
    updated = [dict(step) for step in plan]
    for step in updated:
        step_id = str(step.get("id") or "")
        if step_id == "execute" or step_id.startswith("sub_step_"):
            if status in {"completed", "queued", "preview"}:
                step["status"] = "completed"
            elif status in {"failed", "terminal_failure"}:
                step["status"] = "failed"
            elif status in {"missing_slots", "confirmation_required"}:
                step["status"] = "paused"
        if step_id == "verify_outputs":
            if status in {"completed", "queued"}:
                step["status"] = "completed"
            elif status in {"failed", "terminal_failure"}:
                step["status"] = "failed"
            elif status in {"missing_slots", "confirmation_required"}:
                step["status"] = "paused"
        if step_id == "report" and status in {"completed", "queued", "preview", "failed", "terminal_failure"}:
            step["status"] = "completed"
    if result_type:
        updated.append({"id": "result_type", "label": "Result type", "status": "info", "detail": result_type})
    return updated


def build_result_card(
    *,
    decision: dict[str, Any],
    request: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    request = request or {}
    dispatch_result = dispatch_result or {}
    status = dispatch_result.get("status") or "ready"
    target = request.get("callable_name") or request.get("target_identifier") or decision.get("target_identifier") or ""
    warnings = list(dispatch_result.get("warnings") or [])
    affected = list(dispatch_result.get("affected_targets") or [])
    suggestions = follow_up_suggestions(decision=decision, request=request, dispatch_result=dispatch_result)
    return {
        "summary": _summary_for_status(status, target),
        "status": status,
        "target": target,
        "execution_environment": request.get("execution_environment") or decision.get("host") or "",
        "operation_mode": request.get("operation_mode") or decision.get("operation_mode") or "",
        "actions_performed": _actions_for_status(status, request, dispatch_result),
        "warnings": warnings,
        "affected_objects": affected,
        "files_changed": list(dispatch_result.get("files_changed") or []),
        "scene_changes": list(dispatch_result.get("scene_changes") or []),
        "performance": {"duration_ms": duration_ms} if duration_ms is not None else {},
        "undo_available": bool(dispatch_result.get("undo_available")),
        "follow_up_suggestions": suggestions,
        "diagnostics": dispatch_result.get("retry_metadata") or {},
        "logs": dispatch_result.get("rendered_output") or dispatch_result.get("user_message") or "",
        "raw_available": dispatch_result.get("raw_result") is not None,
    }


def recovery_options(*, result_type: str, dispatch_result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    dispatch_result = dispatch_result or {}
    if result_type in {"missing_adapter", "missing_capabilities"}:
        return [{"action": "reconnect", "label": "Reconnect host"}, {"action": "choose_host", "label": "Choose a host"}]
    if result_type == "dcc_failed":
        retry = dispatch_result.get("retry_metadata") or {}
        if retry.get("method"):
            return [{"action": "retry", "label": "Retry"}, {"action": "diagnose", "label": "Show diagnostics"}]
    if result_type == "dcc_missing_slots":
        return [{"action": "clarify", "label": "Provide missing value"}, {"action": "refresh_choices", "label": "Refresh choices"}]
    return []


def render_execution_plan_text(plan: list[dict[str, Any]] | None) -> str:
    plan = list(plan or [])
    if not plan:
        return ""
    lines = ["Execution Plan"]
    for index, step in enumerate(plan, start=1):
        status = str(step.get("status") or "pending").replace("_", " ")
        label = str(step.get("label") or step.get("id") or f"Step {index}")
        detail = str(step.get("detail") or "").strip()
        suffix = f" - {detail}" if detail else ""
        lines.append(f"{index}. [{status}] {label}{suffix}")
    return "\n".join(lines)


def render_result_card_text(card: dict[str, Any] | None, recovery: list[dict[str, Any]] | None = None) -> str:
    card = dict(card or {})
    if not card:
        return ""
    lines = ["Result"]
    summary = str(card.get("summary") or "").strip()
    if summary:
        lines.append(summary)
    target = str(card.get("target") or "").strip()
    environment = str(card.get("execution_environment") or "").strip()
    status = str(card.get("status") or "").strip()
    facts = []
    if status:
        facts.append(f"status: {status}")
    if target:
        facts.append(f"target: {target}")
    if environment:
        facts.append(f"host: {environment}")
    if facts:
        lines.append("Facts: " + ", ".join(facts))
    actions = [str(item) for item in list(card.get("actions_performed") or []) if str(item).strip()]
    if actions:
        lines.append("Actions: " + "; ".join(actions[:5]))
    warnings = [str(item) for item in list(card.get("warnings") or []) if str(item).strip()]
    if warnings:
        lines.append("Warnings: " + "; ".join(warnings[:4]))
    suggestions = list(card.get("follow_up_suggestions") or [])
    if suggestions:
        labels = [str(item.get("label") or item.get("action") or "") for item in suggestions if isinstance(item, dict)]
        labels = [label for label in labels if label]
        if labels:
            lines.append("Next: " + "; ".join(labels[:3]))
    recovery = list(recovery or [])
    if recovery:
        labels = [str(item.get("label") or item.get("action") or "") for item in recovery if isinstance(item, dict)]
        labels = [label for label in labels if label]
        if labels:
            lines.append("Recovery: " + "; ".join(labels[:3]))
    logs = str(card.get("logs") or "").strip()
    if logs and logs != summary:
        lines.append("Output: " + _compact_line(logs, 260))
    return "\n".join(lines)


def render_structured_interaction_summary(metadata: dict[str, Any] | None) -> str:
    metadata = dict(metadata or {})
    blocks = []
    plan_text = render_execution_plan_text(metadata.get("execution_plan"))
    result_text = render_result_card_text(metadata.get("result_card"), metadata.get("recovery_options"))
    if plan_text:
        blocks.append(plan_text)
    if result_text:
        blocks.append(result_text)
    return "\n\n".join(blocks)


def _is_multi_step_or_pipeline_request(prompt: str) -> bool:
    q = (prompt or "").lower()
    if any(term in q for term in ("pipeline", "workflow", "chain", "sequence", "multi-step", "multiple things", "series of")):
        return True
    if "and" in q or "then" in q or "after" in q or "next" in q:
        mutative_verbs = ("create", "make", "add", "attach", "set", "compile", "rollback", "connect", "link", "spawn")
        matches = sum(1 for verb in mutative_verbs if verb in q)
        if matches >= 2:
            return True
    return False


def follow_up_suggestions(
    *,
    decision: dict[str, Any],
    request: dict[str, Any],
    dispatch_result: dict[str, Any],
) -> list[dict[str, str]]:
    status = dispatch_result.get("status") or ""
    target = str(request.get("callable_name") or request.get("target_identifier") or decision.get("target_identifier") or "")
    
    suggestions: list[dict[str, str]] = []
    
    prompt = request.get("raw_request") or request.get("query") or request.get("text") or decision.get("query") or ""
    if _is_multi_step_or_pipeline_request(prompt):
        suggestions.append({"action": "create_pipeline", "label": "Create Pipeline"})
        
    if status not in {"completed", "queued"}:
        return suggestions[:3]
        
    if "create_rig" in target:
        suggestions.append({"action": "validate_rig", "label": "Validate the rig"})
    if request.get("execution_environment") == "unreal":
        suggestions.append({"action": "inspect_result", "label": "Inspect Unreal result"})
    if decision.get("route") in {"project_health", "target_discovery"}:
        suggestions.append({"action": "apply_fix", "label": "Apply the suggested fix"})
    return suggestions[:3]


def _summary_for_status(status: str, target: str) -> str:
    if status == "completed":
        return f"I've successfully completed the {target or 'operation'}."
    if status == "queued":
        return f"I've queued up the {target or 'operation'} in the host application."
    if status == "preview":
        return f"I've prepared a preview of the {target or 'operation'} for you to review."
    if status == "missing_slots":
        return f"The {target or 'operation'} is set up and ready to go, but I'll need a bit more input first."
    if status == "confirmation_required":
        return f"The {target or 'operation'} is ready. I'm just waiting for your confirmation to execute it."
    if status == "failed":
        return f"Unfortunately, the {target or 'operation'} ran into an error and couldn't complete."
    return f"The status of the {target or 'operation'} is currently: {status}."


def _actions_for_status(status: str, request: dict[str, Any], dispatch_result: dict[str, Any]) -> list[str]:
    actions = ["Resolved route", "Prepared execution request"]
    if request.get("argument_schema"):
        actions.append("Inspected callable metadata")
    if request.get("missing_slots"):
        actions.append("Identified missing input")

    steps = None
    struct_data = dispatch_result.get("structured_data") or {}
    if isinstance(struct_data, dict):
        steps = struct_data.get("steps_executed")

    if not steps:
        raw = dispatch_result.get("raw_result") or dispatch_result.get("user_message")
        if isinstance(raw, str):
            try:
                import json
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    raw = parsed
            except Exception:
                pass
        if isinstance(raw, dict):
            steps = raw.get("steps_executed")
            if not steps and isinstance(raw.get("data"), dict):
                steps = raw["data"].get("steps_executed")
            if not steps and isinstance(raw.get("result"), dict):
                steps = raw["result"].get("steps_executed")
            if not steps and isinstance(raw.get("data"), str):
                try:
                    import json
                    parsed_data = json.loads(raw["data"])
                    if isinstance(parsed_data, dict):
                        steps = parsed_data.get("steps_executed")
                except Exception:
                    pass

    if steps and isinstance(steps, (list, tuple)):
        for step in steps:
            actions.append(str(step))
    else:
        if status in {"completed", "queued", "preview"}:
            actions.append("Dispatched operation")

    if status in {"failed", "terminal_failure"}:
        actions.append("Captured failure diagnostics")
    return actions


def _compact_line(text: str, limit: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


# ---------------------------------------------------------------------------
# Senior engineering reasoning helpers
# ---------------------------------------------------------------------------

def is_senior_engineering_prompt(prompt: str) -> bool:
    """Return True when the prompt warrants structured engineering reasoning.

    Delegates to engineering_reasoning_service.is_senior_engineering_prompt.
    Safe to call even if the service import fails.
    """
    try:
        from tech_connector.services.engineering_reasoning_service import is_senior_engineering_prompt as _impl
        return _impl(prompt)
    except Exception:
        return False


def render_engineering_reasoning_text(reasoning: "EngineeringReasoning") -> str:
    """Serialize an EngineeringReasoning object to a structured text block.

    The block starts with the sentinel line ``Engineering Reasoning`` which is
    detected by the chat renderer and styled as a rich Engineering Reasoning Card.
    """
    lines = ["Engineering Reasoning"]

    # --- Understanding ---
    lines.append("\n== UNDERSTANDING ==")
    if reasoning.goal:
        lines.append(f"Goal: {reasoning.goal}")
    for item in (reasoning.success_criteria or []):
        lines.append(f"Success: {item}")
    for item in (reasoning.constraints or []):
        lines.append(f"Constraint: {item}")
    for item in (reasoning.unknowns or []):
        lines.append(f"Unknown: {item}")

    # --- Investigation ---
    lines.append("\n== INVESTIGATION ==")
    if reasoning.files_inspected:
        for f in reasoning.files_inspected:
            lines.append(f"Inspected: {f}")
    if reasoning.existing_implementations:
        for e in reasoning.existing_implementations:
            lines.append(f"Found: {e}")
    if reasoning.architecture_notes:
        for note in reasoning.architecture_notes:
            lines.append(f"Note: {note}")
    if reasoning.investigation_queries and not reasoning.files_inspected:
        for q in reasoning.investigation_queries:
            lines.append(f"Query: {q}")

    # --- Solutions ---
    lines.append("\n== POSSIBLE SOLUTIONS ==")
    for opt in (reasoning.options or []):
        rec = " [RECOMMENDED]" if opt.name == reasoning.recommended_option else ""
        lines.append(f"{opt.name}: {opt.description} [Risk: {opt.risk.upper()}]{rec}")
        for pro in (opt.pros or []):
            lines.append(f"  Pro: {pro}")
        for con in (opt.cons or []):
            lines.append(f"  Con: {con}")

    # --- Execution Plan ---
    lines.append("\n== EXECUTION PLAN ==")
    for i, step in enumerate(reasoning.execution_steps or [], start=1):
        lines.append(f"Step {i}: {step}")

    # --- Verification ---
    lines.append("\n== VERIFICATION ==")
    for item in (reasoning.verification_steps or []):
        lines.append(f"Verify: {item}")

    # --- Risks ---
    lines.append("\n== POTENTIAL RISKS ==")
    for item in (reasoning.risks or []):
        lines.append(f"Risk: {item}")

    return "\n".join(lines)


def format_tool_result_aesthetic(result: Any) -> str:
    if not isinstance(result, dict):
        if isinstance(result, list):
            import json
            try:
                if len(result) < 5:
                    return json.dumps(result, indent=2, default=str)
                raw_json = json.dumps(result, indent=2, default=str)
                return (
                    f"**List of {len(result)} items**\n\n"
                    f"<details>\n"
                    f"<summary>🔍 View full list ({len(raw_json)} chars)</summary>\n\n"
                    f"```json\n"
                    f"{raw_json}\n"
                    f"```\n"
                    f"</details>"
                )
            except Exception:
                pass
        return str(result)

    import html
    lines = ["**Summary of query results:**\n"]
    
    high_level_keys = ["ok", "connected", "loaded_level", "project_name", "engine_version", "status", "target", "cache_used"]
    summary_items = []
    for k in high_level_keys:
        if k in result:
            val = result[k]
            if isinstance(val, bool):
                val_str = "🟢 True" if val else "🔴 False"
            else:
                val_str = str(val)
            summary_items.append(f"- **{k}**: {val_str}")
            
    list_summaries = []
    for k, v in result.items():
        if k not in high_level_keys:
            if isinstance(v, list):
                list_summaries.append(f"- **{k}**: {len(v)} items")
            elif isinstance(v, dict):
                list_summaries.append(f"- **{k}**: {len(v)} keys/values")
            else:
                if not isinstance(v, (list, dict)) and len(str(v)) < 80:
                    summary_items.append(f"- **{k}**: {v}")
            
    if summary_items:
        lines.extend(summary_items)
    if list_summaries:
        lines.append("\n**Data Collections:**")
        lines.extend(list_summaries)
        
    import json
    raw_json = json.dumps(result, indent=2, default=str)
    lines.append(f"\n<details>\n<summary>🔍 View full raw response data ({len(raw_json)} chars)</summary>\n\n```json\n{raw_json}\n```\n</details>")
    
    return "\n".join(lines)
