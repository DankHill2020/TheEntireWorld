"""Process streamlining policy for capability-first execution.

This module is intentionally deterministic. It describes how Tech Connector
should turn repeated reasoning-heavy work into callable capability/function
execution, then into reusable pipeline scripts when the pattern proves useful.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
import re
from typing import Any


@dataclass(frozen=True)
class StreamliningPlan:
    framework: str
    objective: str
    route: str
    execution_mode: str
    capability_first: bool = True
    compile_pipeline_candidate: bool = False
    requires_model_reasoning: bool = False
    fast_path: list[str] = field(default_factory=list)
    loop_policy: list[str] = field(default_factory=list)
    promotion_criteria: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    expected_runtime: str = "fast_function_execution"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_process_streamlining_plan(
    prompt: str,
    *,
    route: str = "",
    known_capabilities: list[dict[str, Any]] | None = None,
    previous_results: list[dict[str, Any]] | None = None,
) -> StreamliningPlan:
    """Build the capability/function/pipeline policy for a user objective."""

    text = prompt or ""
    known_capabilities = list(known_capabilities or [])
    previous_results = list(previous_results or [])
    lower = text.lower()
    mutation = _requires_mutation(lower)
    multi_step = _looks_multi_step(text)
    repeatable = _looks_repeatable(lower) or multi_step
    has_matching_capability = bool(known_capabilities)
    has_failed_result = any(not bool(item.get("ok", True)) for item in previous_results)

    fast_path = [
        "resolve existing capability/function from registry",
        "validate required inputs",
        "execute callable",
        "inspect structured result",
        "report result if objective is satisfied",
    ]
    if mutation:
        fast_path.insert(2, "confirm approval for mutating operation")
        fast_path.append("run validation or compile check")

    missing: list[str] = []
    requires_model = False
    if not has_matching_capability:
        missing.append("matching registered callable capability")
        requires_model = True
    if has_failed_result:
        missing.append("successful callable result")
        requires_model = True
    if multi_step and not has_matching_capability:
        missing.append("ordered function chain")

    compile_candidate = repeatable and (mutation or multi_step)
    execution_mode = "capability_function_loop"
    if compile_candidate and has_matching_capability:
        execution_mode = "compiled_pipeline_candidate"
    elif requires_model:
        execution_mode = "reason_then_function_loop"

    return StreamliningPlan(
        framework="process_streamlining_v1",
        objective=text.strip(),
        route=route or _infer_route(lower),
        execution_mode=execution_mode,
        compile_pipeline_candidate=compile_candidate,
        requires_model_reasoning=requires_model,
        fast_path=fast_path,
        loop_policy=[
            "run one deterministic callable at a time",
            "parse result into data, artifacts, warnings, errors, and next hints",
            "stop immediately when sufficiency checks pass",
            "call the next function only when the result proves it is needed",
            "return to model reasoning only for missing context, failed validation, or no known callable",
        ],
        promotion_criteria=[
            "same or similar operation is likely to be repeated",
            "ordered steps can be expressed as typed inputs and callable functions",
            "validation and rollback/reporting can be encoded",
            "the compiled script can be registered as a pipeline capability",
        ],
        missing=missing,
        expected_runtime="quick deterministic execution after discovery/planning",
    )


def render_streamlining_plan(plan: StreamliningPlan | dict[str, Any] | None) -> str:
    """Render a compact user-facing explanation of the streamlining path."""

    if plan is None:
        return ""
    data = plan.to_dict() if isinstance(plan, StreamliningPlan) else dict(plan)
    lines = [
        "Process streamlining:",
        f"- Route: {data.get('route')}",
        f"- Mode: {data.get('execution_mode')}",
        f"- Expected runtime: {data.get('expected_runtime')}",
    ]
    if data.get("compile_pipeline_candidate"):
        lines.append("- Pipeline candidate: yes, this can become a reusable callable pipeline.")
    if data.get("requires_model_reasoning"):
        lines.append("- Model reasoning: needed only until a callable path is known.")
    missing = list(data.get("missing") or [])
    if missing:
        lines.append("- Missing: " + ", ".join(str(item) for item in missing))
    return "\n".join(lines)


def _requires_mutation(lower: str) -> bool:
    if re.search(r"\b(do not edit|do not change|plan only|explain only|inspect only)\b", lower):
        return False
    return bool(
        re.search(
            r"\b(add|create|write|generate|implement|insert|modify|update|fix|patch|wire|connect|import|export|run|execute|build)\b",
            lower,
        )
    )


def _looks_multi_step(text: str) -> bool:
    lower = text.lower()
    numbered = len(re.findall(r"^\s*\d+[.)]\s+", text, flags=re.MULTILINE))
    connectors = len(re.findall(r"\b(then|after|before|validate|compile|rollback|report|import|export|connect)\b", lower))
    return numbered >= 3 or connectors >= 3


def _looks_repeatable(lower: str) -> bool:
    return bool(
        re.search(
            r"\b(reusable|pipeline|workflow|repeat|again|template|standard|process|job|batch|automate)\b",
            lower,
        )
    )


def _infer_route(lower: str) -> str:
    """Infer an advisory route without confusing host domain with live context."""
    code_subject = bool(
        re.search(
            r"\b(code|function|method|class|helper|implementation|definition|"
            r"file|module|script|source|caller|usage|symbol|repo|project)\b",
            lower,
        )
    )
    live_dcc_subject = bool(
        re.search(
            r"\b(selected|selection|current scene|open scene|scene object|"
            r"viewport|active asset|current level|loaded level|transform|"
            r"joint position|move|rotate|scale|set key|keyframe)\b",
            lower,
        )
    )
    host_domain = bool(
        re.search(
            r"\b(maya|unreal|blender|houdini|unity|motionbuilder|substance)\b",
            lower,
        )
    )

    if code_subject:
        return "project_code"
    if host_domain and live_dcc_subject:
        return "dcc"
    if re.search(r"\b(github|git|slack|discord|email|gmail|confluence|jira|vcs)\b", lower):
        return "service_or_mcp"
    if host_domain:
        return "project_code"
    return "general"
