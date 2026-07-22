"""Keep verified technique knowledge useful without treating it as timeless truth."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
import re


COMPARISON_TERMS = (
    "newer",
    "newest",
    "latest",
    "current technique",
    "current best practice",
    "compare approaches",
    "compare techniques",
    "modern approach",
)


def _major_minor(value: Any) -> str:
    match = re.search(r"\d+\.\d+", str(value or ""))
    return match.group(0) if match else ""


def _source_date(source: dict[str, Any]) -> datetime | None:
    for key in ("last_checked", "retrieved_at", "verified_at", "published_at", "updated_at"):
        raw = str(source.get(key) or "").strip()
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


def build_technique_currency_review(
    request: str,
    *,
    engine_version: str,
    techniques: Iterable[dict[str, Any]],
    verified_episodes: Iterable[dict[str, Any]] | None = None,
    research_mode: dict[str, Any] | None = None,
    research_queries: Iterable[dict[str, Any]] | None = None,
    now: datetime | None = None,
    max_source_age_days: int = 180,
) -> dict[str, Any]:
    """Decide whether a known approach must be compared with current sources."""

    now = now or datetime.now(timezone.utc)
    mode = dict(research_mode or {})
    rows = [dict(row) for row in techniques or []]
    episodes = [dict(row) for row in verified_episodes or []]
    requested_version = _major_minor(engine_version)
    explicit_comparison = any(term in str(request or "").lower() for term in COMPARISON_TERMS)
    version_mismatches = []
    undated_sources = []
    stale_sources = []
    source_count = 0
    for technique in rows:
        technique_version = _major_minor(
            technique.get("applies_to_version")
            or technique.get("engine_version")
            or technique.get("registry_engine_version")
        )
        if requested_version and technique_version and requested_version != technique_version:
            version_mismatches.append(
                {
                    "technique": technique.get("key"),
                    "known_version": technique_version,
                    "requested_version": requested_version,
                }
            )
        for source in technique.get("sources") or []:
            source_count += 1
            checked = _source_date(dict(source))
            if checked is None:
                undated_sources.append({"technique": technique.get("key"), "url": source.get("url")})
                continue
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            age_days = max(0, (now - checked).days)
            if age_days > max_source_age_days:
                stale_sources.append(
                    {"technique": technique.get("key"), "url": source.get("url"), "age_days": age_days}
                )

    reasons = []
    if explicit_comparison:
        reasons.append("The request explicitly asks for newer/current technique comparison.")
    if version_mismatches:
        reasons.append("Known technique engine versions do not match the live target version.")
    if not source_count:
        reasons.append("The known technique has no attributable source evidence.")
    if undated_sources:
        reasons.append("One or more source claims have no recorded freshness check.")
    if stale_sources:
        reasons.append("One or more source claims exceed the freshness window.")
    if episodes:
        reasons.append("A verified project win exists and remains the baseline until a newer candidate is proven better here.")

    required = bool(explicit_comparison or version_mismatches or not source_count)
    recommended = bool(required or undated_sources or stale_sources or rows)
    live_sources_enabled = bool(mode.get("enable_live_sources"))
    online_comparison_enabled = bool(
        live_sources_enabled
        and (
            mode.get("research_official_docs", True)
            or mode.get("research_web_techniques")
            or mode.get("research_github_examples")
        )
    )
    return {
        "framework": "unreal_technique_currency_review_v1",
        "engine_version": requested_version or str(engine_version or ""),
        "known_baseline": {
            "techniques": [row.get("key") for row in rows],
            "verified_episode_count": len(episodes),
            "policy": "Use as a prior and rollback baseline, never as proof that it is still the best fit.",
        },
        "comparison": {
            "required": required,
            "recommended": recommended,
            "online_enabled": online_comparison_enabled,
            "status": (
                "required_but_offline"
                if required and not online_comparison_enabled
                else "ready_to_research"
                if recommended and online_comparison_enabled
                else "recommended_but_offline"
                if recommended
                else "not_needed"
            ),
            "reasons": reasons,
            "research_queries": [dict(row) for row in research_queries or [] if row.get("enabled")],
            "source_policy": [
                "Prefer current official documentation and primary repositories.",
                "Public tutorials may contribute patterns only when access, attribution, prerequisites, and engine version are recorded.",
                "Paid, authenticated, private, or confidential material cannot become shared reusable knowledge.",
            ],
        },
        "freshness": {
            "max_source_age_days": max_source_age_days,
            "undated_sources": undated_sources,
            "stale_sources": stale_sources,
            "version_mismatches": version_mismatches,
        },
        "decision_contract": {
            "outcomes": ["reuse", "adapt", "replace", "retain_as_fallback", "insufficient_evidence"],
            "compare_on": [
                "live project architecture fit",
                "target engine API and plugin availability",
                "runtime behavior and multiplayer requirements",
                "asset and animation compatibility",
                "failure handling and regression risk",
                "measured proof results",
            ],
            "promotion_rule": "A newer approach replaces a known win only after the same proof contract passes in an isolated project fixture.",
        },
        "next_choices": (
            ["research_current_sources", "run_with_known_baseline", "cancel"]
            if recommended
            else ["run_with_known_baseline", "cancel"]
        ),
    }


def compare_technique_candidates(
    baseline: dict[str, Any],
    candidates: Iterable[dict[str, Any]],
    *,
    project_constraints: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Normalize a source-backed comparison without claiming runtime superiority."""

    constraints = [str(value) for value in project_constraints or [] if str(value).strip()]
    from tech_connector.services.open_knowledge_policy_service import (
        assess_open_knowledge_source,
    )

    rows = []
    for raw in candidates or []:
        candidate = dict(raw)
        source = dict(candidate.get("source") or {})
        source_policy = assess_open_knowledge_source(source)
        missing = [
            field
            for field in ("url", "claim", "source_kind", "applies_to_version")
            if not source.get(field)
        ]
        rows.append(
            {
                "key": candidate.get("key") or candidate.get("title"),
                "source": source,
                "architecture": candidate.get("architecture"),
                "prerequisites": list(candidate.get("prerequisites") or []),
                "advantages": list(candidate.get("advantages") or []),
                "risks": list(candidate.get("risks") or []),
                "project_fit_evidence": list(candidate.get("project_fit_evidence") or []),
                "runtime_proof": dict(candidate.get("runtime_proof") or {}),
                "source_policy": source_policy,
                "eligible_for_prototype": bool(not missing and source_policy.get("task_use_allowed")),
                "eligible_to_replace_baseline": bool(
                    not missing
                    and source_policy.get("eligible")
                    and dict(candidate.get("runtime_proof") or {}).get("all_gates_passed")
                ),
                "missing_evidence": [*missing, *list(source_policy.get("reasons") or [])],
            }
        )
    replacements = [row["key"] for row in rows if row["eligible_to_replace_baseline"]]
    return {
        "framework": "unreal_technique_comparison_v1",
        "baseline": dict(baseline or {}),
        "project_constraints": constraints,
        "candidates": rows,
        "decision": "replace" if replacements else "retain_baseline_pending_proof",
        "replacement_candidates": replacements,
        "completion_allowed": False,
        "reason": "Technique comparison selects a prototype path; gameplay completion still requires the feature proof contract.",
    }
