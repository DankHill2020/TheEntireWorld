"""Production decision profile for Tech Connector planning and execution.

The profile is intentionally studio-level, not personal. It captures the
default judgment Tech Connector should apply before selecting tools, mutating DCC
state, building pipelines, or asking the user to clarify.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class StudioDecisionRule:
    key: str
    title: str
    priority: int
    applies_to: tuple[str, ...]
    guidance: tuple[str, ...]
    proceed_when: tuple[str, ...] = ()
    pause_when: tuple[str, ...] = ()


STUDIO_DECISION_RULES: tuple[StudioDecisionRule, ...] = (
    StudioDecisionRule(
        key="context.inspect_before_mutation",
        title="Inspect context before mutation",
        priority=100,
        applies_to=("dcc", "engine", "pipeline", "code", "vcs", "messaging"),
        guidance=(
            "Resolve active project, provider, selection, target assets, current file, and thread context before choosing an operation.",
            "Use exact discovered names and paths instead of invented placeholders.",
            "Treat vague follow-ups as references to the current thread/project/tool state before asking the user to restate them.",
        ),
        proceed_when=("target context is explicit or discoverable", "operation is reversible and validation is available"),
        pause_when=("target object/asset/path is missing", "multiple plausible targets would change different user data"),
    ),
    StudioDecisionRule(
        key="execution.prefer_registered_operations",
        title="Prefer registered operations",
        priority=95,
        applies_to=("dcc", "engine", "pipeline"),
        guidance=(
            "Use local bridge capabilities, registered operations, and provider metadata before generating free-form scripts.",
            "Only generate raw host code when the registered operation set cannot express the task.",
            "If generated code is needed, keep it narrow, version-aware, and validation-oriented.",
        ),
        pause_when=("host API or operation semantics are unknown locally", "operation is version-specific and live research is disabled"),
    ),
    StudioDecisionRule(
        key="safety.non_destructive_first",
        title="Choose reversible paths first",
        priority=90,
        applies_to=("dcc", "engine", "pipeline", "code", "vcs"),
        guidance=(
            "Prefer additive, non-destructive, previewable, or staged changes over destructive direct edits.",
            "Preserve authored data, references, animation, constraints, source-control history, and user files unless explicitly asked.",
            "Use undo chunks, transactions, snapshots, branches, diffs, or rollback records when the provider supports them.",
        ),
        proceed_when=("change is reversible", "required target is explicit", "validation can confirm success"),
        pause_when=("operation deletes, overwrites, bakes, renames, migrates, publishes, saves broadly, or changes source-control state",),
    ),
    StudioDecisionRule(
        key="pipelines.validate_data_flow",
        title="Validate pipeline data flow",
        priority=88,
        applies_to=("pipeline", "workflow"),
        guidance=(
            "Every node should declare required inputs, produced outputs, side effects, and validation conditions.",
            "Use green/orange/red state to show fulfilled, incomplete, or broken flow before compile/save/run.",
            "When adding context, connect semantically related upstream functions, not just type-compatible nodes.",
        ),
        pause_when=("required input data is missing", "existing connection breaks downstream assumptions"),
    ),
    StudioDecisionRule(
        key="research.authoritative_when_uncertain",
        title="Research authoritative guidance when uncertain",
        priority=82,
        applies_to=("dcc", "engine", "vcs", "pipeline", "code"),
        guidance=(
            "Use local best-practice guidance immediately when confidence is high.",
            "Offer official-docs or provider-source research when guidance is missing, stale, version-specific, conflicting, or risky.",
            "Persist useful researched guidance as structured local knowledge with source, confidence, version, and validation notes.",
        ),
        pause_when=("operation is high-risk and no authoritative local guidance exists", "selected API appears deprecated or poorly documented"),
    ),
    StudioDecisionRule(
        key="validation.done_means_verified",
        title="Done means verified",
        priority=80,
        applies_to=("dcc", "engine", "pipeline", "code", "vcs", "messaging"),
        guidance=(
            "Define the validation contract before executing a multi-step task.",
            "After mutation, query the host/project/file/job state to verify the expected result.",
            "Report exact changes, validation result, warnings, unresolved assumptions, and next safe actions.",
        ),
        pause_when=("there is no practical validation path for a risky operation",),
    ),
)


def _context_terms(*parts: str) -> set[str]:
    text = " ".join(part or "" for part in parts).lower()
    return set(re.findall(r"[a-z0-9_]+", text))


def matching_studio_rules(
    text: str,
    *,
    host: str = "",
    task_type: str = "",
    limit: int = 6,
) -> list[StudioDecisionRule]:
    terms = _context_terms(text, host, task_type)
    requested = set()
    if host in {"maya", "blender", "houdini", "motionbuilder", "substance_painter"}:
        requested.add("dcc")
    if host in {"unreal", "unity"}:
        requested.add("engine")
    if any(term in terms for term in {"pipeline", "workflow", "graph", "node", "connect"}):
        requested.update({"pipeline", "workflow"})
    if any(term in terms for term in {"git", "github", "perforce", "branch", "commit", "merge", "pr"}):
        requested.add("vcs")
    if any(term in terms for term in {"slack", "discord", "email", "jira", "confluence"}):
        requested.add("messaging")
    if any(term in terms for term in {"file", "code", "python", "script", "function", "class"}):
        requested.add("code")
    if task_type:
        requested.add(task_type)
    if not requested:
        requested.update({"dcc", "engine", "pipeline", "code", "vcs", "messaging"})

    ranked = [
        rule for rule in STUDIO_DECISION_RULES
        if requested.intersection(rule.applies_to)
    ]
    ranked.sort(key=lambda rule: rule.priority, reverse=True)
    return ranked[:max(1, limit)]


def studio_decision_profile_context(
    text: str,
    *,
    host: str = "",
    task_type: str = "",
    limit: int = 6,
) -> str:
    rules = matching_studio_rules(text, host=host, task_type=task_type, limit=limit)
    if not rules:
        return ""
    lines = [
        "STUDIO DECISION PROFILE:",
        "Use this production decision profile when selecting paths, composing multi-step workflows, deciding whether to ask, and reporting outcomes.",
        "Decision order: inspect context -> choose registered/local operation -> prefer reversible/staged changes -> validate data flow and result -> report concrete evidence.",
        "Proceed when the target is explicit or discoverable, the change is low-risk or reversible, and validation is available.",
        "Pause or request approval when a destructive, broad, ambiguous, version-uncertain, or source-control-changing operation is required.",
    ]
    for rule in rules:
        lines.extend(["", f"Rule: {rule.title}", f"Priority: {rule.priority}"])
        lines.extend(f"- {item}" for item in rule.guidance)
        if rule.proceed_when:
            lines.append("Proceed when: " + "; ".join(rule.proceed_when))
        if rule.pause_when:
            lines.append("Pause when: " + "; ".join(rule.pause_when))
    return "\n".join(lines)


def studio_profile_summary() -> dict:
    return {
        "name": "Tech Connector Production Decision Profile",
        "rule_count": len(STUDIO_DECISION_RULES),
        "rules": [
            {
                "key": rule.key,
                "title": rule.title,
                "priority": rule.priority,
                "applies_to": list(rule.applies_to),
            }
            for rule in STUDIO_DECISION_RULES
        ],
    }
