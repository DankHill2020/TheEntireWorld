from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


_GENERATED_CODE_INTENTS = {
    "code_generation",
    "function_backed_artifact_generation",
}

_GENERATED_CODE_DELIVERABLES = {
    "code",
    "code_artifact",
    "generated_code",
    "generated_patch",
    "implementation_code",
    "source_code",
    "working_generated_code",
}

_GENERATED_CODE_PLANNING_MODES = {
    "deterministic_complex_implementation",
    "function_backed_artifact_generation",
}


def requests_generated_code_artifact(decision: Mapping[str, Any] | None) -> bool:
    """Return whether the semantic contract requires generated implementation code.

    This intentionally does not inspect prompt wording. Routing should honor the
    structured understanding produced upstream, including read-only requests that
    permit generation and validation only in a disposable workspace.
    """

    root = dict(decision or {})
    execution_context = _mapping(root.get("execution_context"))
    planning = _first_mapping(
        root.get("planning_result"),
        execution_context.get("planning_result"),
    )
    understanding = _first_mapping(
        root.get("request_understanding"),
        execution_context.get("request_understanding"),
    )
    contract = _first_mapping(
        root.get("semantic_execution_contract"),
        execution_context.get("semantic_execution_contract"),
    )

    intents = _normalized_values(
        root.get("intent_category"),
        planning.get("intent_category"),
        understanding.get("primary_intent"),
    )
    deliverables = _normalized_values(
        root.get("deliverable"),
        planning.get("deliverable"),
        understanding.get("requested_artifact"),
        contract.get("deliverable_type"),
    )
    planning_modes = _normalized_values(
        root.get("planning_mode"),
        planning.get("planning_mode"),
    )

    if intents & _GENERATED_CODE_INTENTS:
        return True
    if deliverables & _GENERATED_CODE_DELIVERABLES:
        return True
    if planning_modes & _GENERATED_CODE_PLANNING_MODES:
        return True
    return any(
        value.endswith("_code") or value.startswith("generated_code")
        for value in deliverables
    )


def restricts_live_mutation(prompt: str) -> bool:
    """Return whether generation/execution is confined away from live targets."""

    text = " ".join(str(prompt or "").lower().split())
    negative_live_target = bool(
        re.search(
            r"\b(?:do not|don't|dont|never|without)\s+"
            r"(?:edit|change|modify|write|save|apply|create|add|insert|execute|run|mutate)\b"
            r"[^.;]{0,80}\b(?:live|working|project|source|internal)\s+"
            r"(?:files?|tree|workspace|assets?|project)\b",
            text,
        )
    )
    disposable_only = bool(
        re.search(
            r"\b(?:only\s+)?(?:in|inside|within|to)\s+(?:a\s+|an\s+|the\s+)?"
            r"(?:disposable|temporary|temp|sandbox(?:ed)?|isolated|throwaway)\s+"
            r"(?:workspace|copy|directory|folder|environment|tree)\b",
            text,
        )
    )
    return negative_live_target or disposable_only


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        mapped = _mapping(value)
        if mapped:
            return mapped
    return {}


def _normalized_values(*values: Any) -> set[str]:
    return {
        str(value).strip().lower()
        for value in values
        if str(value or "").strip()
    }
