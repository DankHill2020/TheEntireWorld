"""Compact expert and memory context for prompt preparation.

This service does not execute work. It builds a small decision packet from the
existing expert registry, local playbooks, operation memory, and AI work memory
so prompts get stronger guidance without dumping large unrelated context.
"""

from __future__ import annotations

from typing import Any


def _trim(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip().replace("\r", " ").replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


def _active_host(decision: dict[str, Any] | None, host: str = "") -> str:
    decision = decision or {}
    return str(host or decision.get("host") or decision.get("execution_environment") or "").strip().lower()


def build_expert_memory_packet(
    prompt: str,
    decision: dict[str, Any] | None = None,
    *,
    settings: dict[str, Any] | None = None,
    host: str = "",
    thread_context: str = "",
    project_context: str = "",
    tool_context: str = "",
    operation_memory: dict[str, Any] | None = None,
    max_chars: int = 3500,
) -> str:
    """Return a compact expert-memory packet for the current prompt."""
    settings = settings or {}
    if settings.get("expert_memory_packet_enabled", True) is False:
        return ""

    decision = dict(decision or {})
    resolved_host = _active_host(decision, host)

    from tech_connector.services.ai_work_memory_service import relevant_ai_work_entries
    from tech_connector.services.domain_expert_service import select_domain_experts
    from tech_connector.services.operation_memory_service import operation_memory_from_dict
    from tech_connector.services.task_playbook_service import assess_best_practice_coverage, matching_playbooks

    experts = select_domain_experts(
        prompt,
        decision,
        settings=settings,
        limit=int(settings.get("expert_memory_max_experts", 4) or 4),
    )
    playbooks = matching_playbooks(
        prompt,
        host=resolved_host,
        limit=int(settings.get("expert_memory_max_playbooks", 2) or 2),
        thread_context=thread_context,
        project_context=project_context,
        tool_context=tool_context,
    )
    assessment = assess_best_practice_coverage(
        prompt,
        host=resolved_host,
        limit=3,
        thread_context=thread_context,
        project_context=project_context,
        tool_context=tool_context,
    )
    work = relevant_ai_work_entries(
        settings,
        " ".join(part for part in (prompt, thread_context, project_context, tool_context) if part),
        host=resolved_host,
        limit=int(settings.get("expert_memory_max_work_items", 4) or 4),
    )
    mem = operation_memory_from_dict(operation_memory)

    if not any((experts, playbooks, work.get("recent"), work.get("locked"), mem.resolved_slots, assessment.reasons)):
        return ""

    lines: list[str] = [
        "EXPERT MEMORY PACKET:",
        "Use this compact guidance before open-ended planning. Current verified project/host facts override memory when they conflict.",
    ]
    if resolved_host:
        lines.append(f"- Active domain hint: {resolved_host}")

    if experts:
        lines.append("- Expert lenses:")
        for expert in experts[:4]:
            label = expert.get("label") or expert.get("domain")
            lines.append(
                f"  - {label} [{expert.get('domain')}; {expert.get('mode')}; confidence={expert.get('confidence')}]"
            )
            required_context = expert.get("required_context") or []
            validation = expert.get("validation_steps") or []
            brief = expert.get("expert_brief") or []
            if required_context:
                lines.append("    needs: " + "; ".join(_trim(item, 80) for item in required_context[:3]))
            if brief:
                lines.append("    senior cue: " + _trim(" | ".join(str(item) for item in brief[:2]), 260))
            if validation:
                lines.append("    validate: " + "; ".join(_trim(item, 80) for item in validation[:2]))
        if any(expert.get("domain") == "unreal.blueprint_graph" for expert in experts):
            from tech_connector.services.unreal.blueprint_graph_knowledge_service import (
                blueprint_graph_expert_context,
            )

            lines.append("- " + blueprint_graph_expert_context().replace("\n", "\n  "))

    if playbooks:
        lines.append("- Matched known-practice playbooks:")
        for playbook in playbooks[:2]:
            lines.append(f"  - {playbook.key}: {playbook.title}")
            lines.append(f"    summary: {_trim(playbook.summary, 220)}")
            if playbook.prefer_operations:
                lines.append("    prefer: " + ", ".join(playbook.prefer_operations[:4]))
            if playbook.ask_when_missing:
                lines.append("    ask only if missing: " + "; ".join(playbook.ask_when_missing[:3]))
            if playbook.avoid:
                lines.append("    avoid: " + "; ".join(_trim(item, 90) for item in playbook.avoid[:2]))

    if assessment.reasons:
        lines.append(f"- Local practice confidence: {assessment.confidence}")
        for reason in assessment.reasons[:3]:
            lines.append(f"  - {_trim(reason, 180)}")
        if assessment.should_offer_research:
            lines.append("  - If allowed and useful, offer authoritative best-practice research before risky or version-specific execution.")
            lines.append(f"  - Research query: {_trim(assessment.research_query, 220)}")

    if mem.status == "active" and (mem.resolved_slots or mem.selected_assets or mem.selected_objects or mem.selected_file or mem.selected_graph):
        lines.append("- Active operation memory:")
        if mem.selected_host:
            lines.append(f"  - host: {mem.selected_host}")
        if mem.selected_file:
            lines.append(f"  - file: {_trim(mem.selected_file, 160)}")
        if mem.selected_graph:
            lines.append(f"  - graph: {_trim(mem.selected_graph, 120)}")
        if mem.selected_assets:
            lines.append("  - assets: " + ", ".join(_trim(item, 80) for item in mem.selected_assets[:4]))
        if mem.selected_objects:
            lines.append("  - objects: " + ", ".join(_trim(item, 80) for item in mem.selected_objects[:4]))
        if mem.resolved_slots:
            slot_text = ", ".join(f"{key}={_trim(value, 80)}" for key, value in list(mem.resolved_slots.items())[:6])
            lines.append(f"  - resolved slots: {slot_text}")

    locked = work.get("locked") or []
    recent = work.get("recent") or []
    if locked or recent:
        lines.append("- Prior work hints:")
        for item in (locked + recent)[:4]:
            source = item.get("locked_snapshot") or ("recent ok" if item.get("ok") else "recent")
            target = item.get("target_path") or item.get("local_path") or item.get("workflow_path") or item.get("knowledge_path") or "n/a"
            lines.append(
                f"  - [{source}] {item.get('host')} {item.get('mode')}: {_trim(item.get('goal'), 150)} -> {_trim(target, 150)}"
            )

    lines.append("- Use policy: select the smallest safe path, reuse existing project/host services, ask only for blocking unknowns, validate after mutation, and report exact evidence.")
    packet = "\n".join(lines)
    return packet[:max_chars]
