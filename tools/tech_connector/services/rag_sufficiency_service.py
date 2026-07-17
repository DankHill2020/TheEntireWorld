"""Adaptive RAG sufficiency checks for project prompts.

The goal is to stop early when deterministic retrieval already answers the
user, and to escalate to a model only when the retrieved evidence is incomplete,
contradictory, or requires synthesis beyond presentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class RagSufficiencyResult:
    answerable: bool
    confidence: float
    route: str
    reasons: tuple[str, ...] = ()
    evidence_summary: tuple[str, ...] = ()
    missing_requirements: tuple[str, ...] = ()
    recommended_next_stage: str = "deterministic_answer"
    model_tier: str = "none_deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "answerable": self.answerable,
            "confidence": round(float(self.confidence), 3),
            "route": self.route,
            "reasons": list(self.reasons),
            "evidence_summary": list(self.evidence_summary),
            "missing_requirements": list(self.missing_requirements),
            "recommended_next_stage": self.recommended_next_stage,
            "model_tier": self.model_tier,
        }


def evaluate_project_rag_sufficiency(
    question: str,
    project_context: str,
    *,
    intent: str = "project_search",
) -> RagSufficiencyResult:
    """Decide whether indexed project evidence is enough to answer now."""

    lower = (question or "").lower()
    context = project_context or ""
    context_lower = context.lower()
    mutation = bool(
        re.search(r"\b(add|create|write|generate|implement|insert|modify|improve|refactor|fix|update|patch|wire|connect|repair|build)\b", lower)
        and not re.search(r"\b(what functions|which functions|where is|where are|list|show|explain|summarize|report what you find|do not edit|do not change|plan only)\b", lower)
    )
    no_evidence = (
        not context.strip()
        or "no matching" in context_lower
        or "did not return evidence" in context_lower
        or "could not find indexed" in context_lower
    )
    error = "[project search error]" in context_lower
    exact_evidence = any(
        marker in context
        for marker in (
            "Exact symbol/source matches:",
            "Exact text/chunk matches:",
            "Call matches:",
            "Class matches:",
            "Import matches:",
            "Source: local project knowledge index.",
        )
    )
    direct_fact_query = bool(
        re.search(r"\b(what functions|which functions|where is|where are|list callers|list usages|list references|find every|find all|which files|which service)\b", lower)
    )
    reasons: list[str] = []
    missing: list[str] = []
    if error:
        return RagSufficiencyResult(
            False,
            0.2,
            "project_search",
            reasons=("retrieval_error",),
            missing_requirements=("valid project index response",),
            recommended_next_stage="repair_or_report_retrieval_error",
            model_tier="none_deterministic",
        )
    if no_evidence:
        return RagSufficiencyResult(
            False,
            0.25,
            "project_search",
            reasons=("no_matching_project_evidence",),
            missing_requirements=("matching indexed project symbols or chunks",),
            recommended_next_stage="broaden_retrieval_or_ask_clarification",
            model_tier="local_plan_or_fast",
        )
    if mutation or intent == "project_edit":
        reasons.append("mutation_or_edit_request_needs_planning")
        return RagSufficiencyResult(
            False,
            0.65 if exact_evidence else 0.45,
            "project_edit",
            reasons=tuple(reasons),
            evidence_summary=tuple(_evidence_lines(context)),
            missing_requirements=tuple(missing),
            recommended_next_stage="specialist_planning_or_patch_generation",
            model_tier="local_plan_then_local_code",
        )
    if direct_fact_query and exact_evidence:
        return RagSufficiencyResult(
            True,
            0.92,
            "project_search",
            reasons=("direct_fact_query", "exact_index_evidence"),
            evidence_summary=tuple(_evidence_lines(context)),
            recommended_next_stage="deterministic_answer",
            model_tier="none_deterministic",
        )
    if exact_evidence:
        return RagSufficiencyResult(
            True,
            0.82,
            "project_search",
            reasons=("indexed_evidence_present",),
            evidence_summary=tuple(_evidence_lines(context)),
            recommended_next_stage="deterministic_answer_or_small_presentation",
            model_tier="none_deterministic",
        )
    return RagSufficiencyResult(
        False,
        0.55,
        "project_search",
        reasons=("retrieval_needs_synthesis",),
        evidence_summary=tuple(_evidence_lines(context)),
        recommended_next_stage="small_presentation_or_more_retrieval",
        model_tier="local_plan_or_fast",
    )


def build_rag_evidence_packet(
    question: str,
    project_context: str,
    sufficiency: RagSufficiencyResult,
    *,
    max_chars: int = 3500,
) -> dict[str, Any]:
    """Build a compact structured packet for downstream model stages."""

    context = (project_context or "").strip()
    return {
        "framework": "adaptive_project_rag_v1",
        "objective": (question or "").strip(),
        "sufficiency": sufficiency.to_dict(),
        "evidence_excerpt": context[: max(500, int(max_chars or 3500))],
        "source": "local_project_index",
        "rules": [
            "Use retrieved evidence before model synthesis.",
            "Stop when direct indexed evidence answers the question.",
            "Escalate only for missing evidence, contradictions, mutation planning, or synthesis.",
        ],
    }


def render_rag_sufficiency_summary(result: RagSufficiencyResult) -> str:
    status = "answerable" if result.answerable else "needs escalation"
    lines = [
        f"RAG sufficiency: {status} (confidence {result.confidence:.2f})",
        f"Next stage: {result.recommended_next_stage}",
        f"Model tier: {result.model_tier}",
    ]
    if result.reasons:
        lines.append("Reasons: " + ", ".join(result.reasons))
    if result.missing_requirements:
        lines.append("Missing: " + ", ".join(result.missing_requirements))
    return "\n".join(lines)


def _evidence_lines(context: str, limit: int = 5) -> list[str]:
    out: list[str] = []
    for line in (context or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") or stripped.startswith("Mode:") or stripped.startswith("Scope:") or stripped.startswith("File:") or stripped.startswith("Signature:"):
            out.append(stripped[:220])
        if len(out) >= limit:
            break
    return out
