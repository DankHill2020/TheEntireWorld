"""User-facing reasoning narration built from problem formulation and plans.

This service does not expose hidden chain-of-thought. It translates the
observable problem formulation, dependency plan, evidence goals, and validation
criteria into concise progress messages that explain what the system is trying
to accomplish and why each step is necessary.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import re
from typing import Any


_INTERNAL_EVENT_KINDS = {
    "route",
    "route_candidate",
    "tool",
    "intent",
    "request_goal_graph",
    "request_goal",
}

_GENERIC_RUNTIME_MESSAGES = {
    "accepted. routing and preparing context",
    "accepted request - routing",
    "routing request",
    "routing request normally",
    "running deterministic engine request",
    "searching project facts",
    "searching project index",
    "project index ready",
    "answer ready",
    "dispatching via projectsearchhandler",
    "understanding request",
}


@dataclass
class NarrationStep:
    step_id: str
    title: str
    objective: str
    why: str = ""
    success: str = ""
    phase: str = "planning"
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReasoningNarration:
    prompt: str
    interpreted_request: str
    desired_outcome: str
    approach_summary: str
    steps: list[NarrationStep] = field(default_factory=list)
    current_step_id: str = ""
    completed_step_ids: list[str] = field(default_factory=list)
    debug_events_hidden: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "reasoning_narration_v1",
            "prompt": self.prompt,
            "interpreted_request": self.interpreted_request,
            "desired_outcome": self.desired_outcome,
            "approach_summary": self.approach_summary,
            "steps": [step.to_dict() for step in self.steps],
            "current_step_id": self.current_step_id,
            "completed_step_ids": list(self.completed_step_ids),
            "debug_events_hidden": self.debug_events_hidden,
        }


def build_reasoning_narration(
    prompt: str,
    decision: dict[str, Any] | Any | None = None,
) -> dict[str, Any]:
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    formulation = _formulation(prompt, data)
    specialized = _specialized_query_narration(prompt, formulation)
    if specialized:
        return specialized

    interpreted = str(
        formulation.get("interpreted_problem")
        or formulation.get("literal_request")
        or data.get("primary_goal")
        or prompt
    ).strip()
    desired = str(
        formulation.get("desired_outcome")
        or formulation.get("success_definition")
        or ""
    ).strip()

    plan_rows = list(
        formulation.get("candidate_plan")
        or data.get("semantic_plan_steps")
        or (data.get("semantic_execution_contract") or {}).get("plan_steps")
        or (data.get("goal_graph") or {}).get("goals")
        or (data.get("task_graph") or {}).get("goals")
        or []
    )

    steps: list[NarrationStep] = []
    for index, raw in enumerate(plan_rows):
        row = dict(raw or {})
        objective = str(
            row.get("objective")
            or row.get("goal")
            or row.get("title")
            or row.get("description")
            or ""
        ).strip()
        if not objective:
            continue
        step_id = str(
            row.get("step_id")
            or row.get("goal_id")
            or row.get("task_id")
            or f"step_{index + 1}"
        )
        why = str(
            row.get("why")
            or row.get("reason")
            or row.get("rationale")
            or _infer_why(objective, formulation)
        ).strip()
        success = str(
            row.get("success")
            or row.get("success_condition")
            or row.get("stop_when")
            or ""
        ).strip()
        phase = _phase_for_step(row, objective)
        steps.append(
            NarrationStep(
                step_id=step_id,
                title=_short_title(objective, phase),
                objective=objective,
                why=why,
                success=success,
                phase=phase,
                status=str(row.get("status") or "pending"),
                depends_on=[str(value) for value in row.get("depends_on") or []],
            )
        )

    if not steps:
        steps = _fallback_steps(formulation, interpreted)

    current = next(
        (
            step.step_id
            for step in steps
            if step.status in {"ready", "active", "running", "pending"}
            and not step.depends_on
        ),
        steps[0].step_id if steps else "",
    )

    return ReasoningNarration(
        prompt=prompt,
        interpreted_request=interpreted,
        desired_outcome=desired,
        approach_summary=_approach_summary(formulation, steps),
        steps=steps,
        current_step_id=current,
    ).to_dict()


def render_reasoning_narration(
    narration: dict[str, Any] | None,
    *,
    max_steps: int = 6,
) -> str:
    data = dict(narration or {})
    if not data:
        return ""
    lines = [
        "Reasoning Approach",
        "",
        "Understanding",
        str(data.get("interpreted_request") or "Interpreting the requested outcome."),
    ]
    if data.get("desired_outcome"):
        lines.extend(["", "Success looks like", str(data["desired_outcome"])])
    if data.get("approach_summary"):
        lines.extend(["", "Approach", str(data["approach_summary"])])
    steps = list(data.get("steps") or [])
    if steps:
        lines.extend(["", "Plan"])
        current_id = str(data.get("current_step_id") or "")
        for row in steps[:max_steps]:
            step_id = str(row.get("step_id") or "")
            marker = "▶" if step_id == current_id else "□"
            lines.append(f"{marker} {row.get('objective') or row.get('title') or step_id}")
    return "\n".join(lines)


def narrate_progress_message(
    message: str,
    narration: dict[str, Any] | None = None,
) -> str:
    """Translate a plumbing-oriented runtime message into an outcome-oriented one."""
    raw = re.sub(r"\s+", " ", str(message or "")).strip()
    if not raw:
        return ""
    lower = raw.casefold()

    # Never surface dataclass reprs or debug plumbing as normal progress.
    if "activityevent(" in lower:
        return ""
    if lower.startswith("dispatching via ") or lower.startswith("routing through "):
        return ""
    if lower.startswith("route selected:"):
        return ""

    data = dict(narration or {})
    steps = list(data.get("steps") or [])

    if "context changed:" in lower:
        return raw
    if "accepted" in lower or lower in {"routing request", "understanding request"}:
        return _message_for_phase(data, "understanding") or "Understanding the outcome you need..."
    if "searching project facts" in lower or "searching project index" in lower:
        return _message_for_phase(data, "searching") or "Gathering the evidence needed to answer the request..."
    if "project evidence gathered" in lower or "index answer ready" in lower:
        return _message_for_phase(data, "comparing") or "Comparing the strongest candidate evidence..."
    if "answer ready" in lower or lower.endswith(" ready"):
        return _message_for_phase(data, "reporting") or "Preparing the evidence-backed answer..."
    if "validat" in lower or "compile" in lower or "test" in lower:
        return _message_for_phase(data, "validating") or raw
    if "planning" in lower:
        return _message_for_phase(data, "planning") or raw
    if "preparing prompt" in lower or "applying source policy" in lower:
        return _message_for_phase(data, "understanding") or "Attaching the context needed to interpret the request accurately..."

    # Preserve already-specific user-facing messages.
    if len(raw.split()) >= 6 and not any(
        token in lower
        for token in (
            "engine request",
            "handler selected",
            "projectsearchhandler",
            "route_candidate",
        )
    ):
        return raw

    if lower in _GENERIC_RUNTIME_MESSAGES:
        return _current_step_message(data)
    return raw


def narrate_activity_event(
    event: Any,
    narration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = str(getattr(event, "kind", "") or "").strip().lower()
    title = str(getattr(event, "title", "") or "").strip()
    detail = str(getattr(event, "detail", "") or "").strip()
    status = str(getattr(event, "status", "") or "").strip()

    internal = kind in _INTERNAL_EVENT_KINDS
    phase = {
        "intent": "understanding",
        "route_candidate": "understanding",
        "route": "planning",
        "request_goal_graph": "planning",
        "request_goal": "planning",
        "tool": "searching",
        "visible_progress": "searching",
        "result": "comparing",
        "validation": "validating",
        "report": "reporting",
    }.get(kind, "")

    message = _message_for_phase(dict(narration or {}), phase)
    if not message:
        message = narrate_progress_message(detail or title, narration)

    return {
        "kind": kind,
        "phase": phase,
        "message": message,
        "internal": internal,
        "status": status,
        "debug_text": _debug_event_text(event),
    }


def should_show_debug_event(event: Any, *, developer_mode: bool = False) -> bool:
    if developer_mode:
        return True
    kind = str(getattr(event, "kind", "") or "").strip().lower()
    return kind not in _INTERNAL_EVENT_KINDS



def _specialized_query_narration(
    prompt: str,
    formulation: dict[str, Any],
) -> dict[str, Any]:
    lower = re.sub(r"\s+", " ", str(prompt or "")).strip().lower()

    file_behavior = bool(
        re.search(r"\b(?:what|which|find|show|list)\s+files?\b", lower)
        and re.search(r"\bfunctions?\b", lower)
        and re.search(r"\b(create|build|generate|make|setup)\b", lower)
    )
    if file_behavior:
        subject_match = re.search(
            r"\b(?:create|build|generate|make|setup)\s+(.+?)\s+functions?\b",
            lower,
        )
        subject = (subject_match.group(1) if subject_match else "rig").strip()
        narration = ReasoningNarration(
            prompt=prompt,
            interpreted_request=(
                f"Find the project files containing functions that create or build {subject}."
            ),
            desired_outcome=(
                "Return the strongest matching file paths, the supporting functions "
                "inside them, and why those functions count as primary implementations."
            ),
            approach_summary=(
                "Files do not perform the behavior directly; functions do. I will first "
                "find the implementing functions, then resolve and rank their containing files."
            ),
            steps=[
                NarrationStep(
                    "define_behavior",
                    "Define rig-creation behavior",
                    f"Define what counts as creating or building {subject}.",
                    "A filename or incidental word match is not enough to prove implementation behavior.",
                    "The behavior contract and exclusions are explicit.",
                    "understanding",
                    "ready",
                ),
                NarrationStep(
                    "find_functions",
                    "Find creating functions",
                    f"Find candidate functions that create or build {subject}.",
                    "The functions provide the evidence needed to identify the correct files.",
                    "Candidate implementation functions are found or absence is confirmed.",
                    "searching",
                    depends_on=["define_behavior"],
                ),
                NarrationStep(
                    "inspect_functions",
                    "Inspect candidate behavior",
                    "Inspect names, signatures, bodies, docstrings, and call relationships.",
                    "Related helpers must be separated from functions that actually construct the rig.",
                    "Each candidate has positive and negative behavioral evidence.",
                    "comparing",
                    depends_on=["find_functions"],
                ),
                NarrationStep(
                    "resolve_files",
                    "Resolve containing files",
                    "Determine which source files contain the supported implementation functions.",
                    "The requested deliverable is files, but the proof comes from contained functions.",
                    "Every supported function maps to an existing file.",
                    "searching",
                    depends_on=["inspect_functions"],
                ),
                NarrationStep(
                    "rank_files",
                    "Rank primary implementations",
                    "Rank complete rig builders above narrow helpers and incidental matches.",
                    "The final answer should identify the most responsible implementations, not every related function.",
                    "The strongest files are explainably separated from alternatives.",
                    "comparing",
                    depends_on=["resolve_files"],
                ),
                NarrationStep(
                    "report",
                    "Report files and evidence",
                    "Return the matching files with supporting functions and rationale.",
                    "",
                    "The answer directly identifies which files implement the behavior and why.",
                    "reporting",
                    depends_on=["rank_files"],
                ),
            ],
            current_step_id="define_behavior",
        )
        return narration.to_dict()

    reference_function = bool(
        re.search(r"\b(?:that|this|the previous|the last)\s+file\b", lower)
        and re.search(r"\bfunctions?\b", lower)
    )
    if reference_function:
        behavior_match = re.search(
            r"\bfunctions?\b.*?\b(?:to|that|which)\s+(.+?)(?:\?|$)",
            lower,
        )
        if not behavior_match:
            behavior_match = re.search(
                r"\b(?:to|that|which)\s+(.+?)(?:\?|$)",
                lower,
            )
        behavior = (
            behavior_match.group(1).strip()
            if behavior_match
            else "match the requested behavior"
        )
        narration = ReasoningNarration(
            prompt=prompt,
            interpreted_request=(
                f"Determine whether the previously resolved file contains a function that {behavior}."
            ),
            desired_outcome=(
                "Return the matching function if it exists, or clearly explain that no dedicated "
                "helper was found and what evidence was checked."
            ),
            approach_summary=(
                "I must resolve “that file” from conversation context, inspect only that file, "
                "and compare actual function behavior rather than searching the whole project."
            ),
            steps=[
                NarrationStep(
                    "resolve_reference",
                    "Resolve target file",
                    "Resolve “that file” to one concrete source path from recent conversation context.",
                    "The function search cannot be scoped correctly until the reference is concrete.",
                    "One source file is resolved.",
                    "understanding",
                    "ready",
                ),
                NarrationStep(
                    "inventory_file",
                    "Inspect functions in that file",
                    "Enumerate relevant functions only inside the resolved file.",
                    "The question is scoped to one file, not the whole project.",
                    "The file’s candidate functions are known.",
                    "searching",
                    depends_on=["resolve_reference"],
                ),
                NarrationStep(
                    "compare_behavior",
                    "Compare function behavior",
                    f"Determine which candidate actually {behavior}.",
                    "Names alone may describe adjacent behavior without performing the requested detection.",
                    "A dedicated match is identified or absence is established.",
                    "comparing",
                    depends_on=["inventory_file"],
                ),
                NarrationStep(
                    "report",
                    "Report the finding",
                    "Return the matching function and evidence, or explain the capability gap.",
                    "",
                    "The answer clearly distinguishes an existing helper from a proposed new one.",
                    "reporting",
                    depends_on=["compare_behavior"],
                ),
            ],
            current_step_id="resolve_reference",
        )
        return narration.to_dict()

    return {}

def _formulation(prompt: str, decision: dict[str, Any]) -> dict[str, Any]:
    existing = dict(
        decision.get("problem_formulation")
        or (decision.get("request_understanding") or {}).get("problem_formulation")
        or {}
    )
    if existing:
        return existing
    try:
        from services.problem_formulation_service import build_problem_formulation
        result = build_problem_formulation(
            prompt,
            decision,
            context=dict(
                decision.get("context_snapshot")
                or decision.get("operation_memory")
                or {}
            ),
        )
        return result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
    except Exception:
        return {}


def _phase_for_step(row: dict[str, Any], objective: str) -> str:
    action = str(row.get("action") or "").lower()
    text = f"{action} {objective}".lower()
    if any(term in text for term in ("interpret", "understand", "resolve reference", "formulate")):
        return "understanding"
    if any(term in text for term in ("plan", "design", "determine capability gap")):
        return "planning"
    if any(term in text for term in ("search", "find", "inspect", "gather", "resolve containing")):
        return "searching"
    if any(term in text for term in ("rank", "compare", "evaluate", "decide")):
        return "comparing"
    if any(term in text for term in ("validate", "verify", "compile", "test")):
        return "validating"
    if any(term in text for term in ("report", "return", "answer", "summarize")):
        return "reporting"
    if any(term in text for term in ("execute", "apply", "modify", "create")):
        return "executing"
    return "planning"


def _short_title(objective: str, phase: str) -> str:
    compact = re.sub(r"\s+", " ", objective).strip().rstrip(".")
    if len(compact) <= 54:
        return compact
    return compact[:51].rstrip() + "..."


def _infer_why(objective: str, formulation: dict[str, Any]) -> str:
    lower = objective.lower()
    if "resolve" in lower and ("file" in lower or "reference" in lower):
        return "The target must be concrete before its members or behavior can be inspected."
    if "find" in lower and ("function" in lower or "symbol" in lower):
        return "The implementation symbols provide stronger evidence than matching filenames or raw words."
    if "containing file" in lower:
        return "The requested file can only be identified after the implementing symbols are known."
    if "rank" in lower or "compare" in lower:
        return "Related helpers must be separated from the implementation that actually satisfies the request."
    if "validate" in lower or "verify" in lower:
        return "The result should be proven against the requested success condition before reporting completion."
    unknowns = list(formulation.get("unknowns") or [])
    if unknowns:
        return f"This step resolves an unknown needed before action: {unknowns[0]}"
    return ""


def _approach_summary(formulation: dict[str, Any], steps: list[NarrationStep]) -> str:
    explicit = str(
        formulation.get("planning_rationale")
        or formulation.get("problem_summary")
        or ""
    ).strip()
    if explicit:
        return explicit
    if len(steps) >= 2:
        return (
            f"First {steps[0].objective.rstrip('.').lower()}, then "
            f"{steps[1].objective.rstrip('.').lower()}."
        )
    return steps[0].objective if steps else "Gather enough evidence before taking action."


def _fallback_steps(formulation: dict[str, Any], interpreted: str) -> list[NarrationStep]:
    deliverables = " ".join(str(x) for x in formulation.get("deliverables") or []).lower()
    subject = str(formulation.get("subject") or interpreted)
    if "file" in deliverables and any(term in subject.lower() for term in ("function", "create", "build", "implementation")):
        return [
            NarrationStep(
                "find_implementations",
                "Find implementing functions",
                f"Find functions that implement {subject}.",
                "Functions provide the evidence needed to identify the correct files.",
                "Relevant implementation functions are identified.",
                "searching",
            ),
            NarrationStep(
                "resolve_files",
                "Resolve containing files",
                "Determine which files contain the candidate functions.",
                "The user asked for files, but the behavior is implemented by functions.",
                "Each candidate function is associated with its source file.",
                "searching",
                depends_on=["find_implementations"],
            ),
            NarrationStep(
                "rank_implementations",
                "Compare implementations",
                "Rank primary implementations above narrow helpers and incidental matches.",
                "A related helper is not necessarily the implementation the user wants.",
                "The strongest evidence-backed files are identified.",
                "comparing",
                depends_on=["resolve_files"],
            ),
            NarrationStep(
                "report_answer",
                "Report the answer",
                "Return the matching files with supporting function evidence.",
                "",
                "The answer includes files, functions, and why they match.",
                "reporting",
                depends_on=["rank_implementations"],
            ),
        ]
    return [
        NarrationStep(
            "understand",
            "Understand the request",
            "Determine the requested outcome, constraints, and evidence needed.",
            "",
            "The request has a concrete success condition.",
            "understanding",
        ),
        NarrationStep(
            "gather",
            "Gather evidence",
            "Gather only the evidence required to satisfy the interpreted request.",
            "Action should wait until enough relevant evidence exists.",
            "The evidence is sufficient for the requested deliverable.",
            "searching",
            depends_on=["understand"],
        ),
        NarrationStep(
            "report",
            "Report the outcome",
            "Return the result with supporting evidence and remaining uncertainty.",
            "",
            "The requested outcome is delivered clearly.",
            "reporting",
            depends_on=["gather"],
        ),
    ]


def _message_for_phase(data: dict[str, Any], phase: str) -> str:
    if not phase:
        return ""
    steps = list(data.get("steps") or [])
    match = next((row for row in steps if str(row.get("phase") or "") == phase), None)
    if not match:
        return ""
    objective = str(match.get("objective") or match.get("title") or "").strip()
    why = str(match.get("why") or "").strip()
    if phase == "understanding":
        prefix = "Understanding: "
    elif phase == "planning":
        prefix = "Planning: "
    elif phase == "searching":
        prefix = "Searching: "
    elif phase == "comparing":
        prefix = "Comparing: "
    elif phase == "validating":
        prefix = "Validating: "
    elif phase == "executing":
        prefix = "Executing: "
    else:
        prefix = "Answering: "
    message = prefix + objective.rstrip(".") + "."
    if why and len(message) + len(why) < 190:
        message += " " + why.rstrip(".") + "."
    return message


def _current_step_message(data: dict[str, Any]) -> str:
    current_id = str(data.get("current_step_id") or "")
    steps = list(data.get("steps") or [])
    row = next((item for item in steps if str(item.get("step_id") or "") == current_id), None)
    if not row and steps:
        row = steps[0]
    if not row:
        return "Understanding the requested outcome..."
    return _message_for_phase(data, str(row.get("phase") or "")) or str(
        row.get("objective") or row.get("title") or ""
    )


def _debug_event_text(event: Any) -> str:
    try:
        return event.markdown() if hasattr(event, "markdown") else str(event)
    except Exception:
        return str(event)
