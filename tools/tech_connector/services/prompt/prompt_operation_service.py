"""Shared prompt operation taxonomy and deterministic operation helpers.

Intent understanding identifies the target and one or more requested operations.
Routing and execution strategies consume these canonical operation values rather
than inventing route-specific action strings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Any, Iterable


class PromptOperation(str, Enum):
    LOCATE = "locate"
    EXPLAIN_BEHAVIOR = "explain_behavior"
    EXPLAIN_USAGE = "explain_usage"
    FIND_CALLERS = "find_callers"
    FIND_CALLEES = "find_callees"
    FIND_IMPLEMENTATIONS = "find_implementations"
    FIND_RELATED = "find_related"
    SHOW_SIGNATURE = "show_signature"
    SHOW_SOURCE = "show_source"
    COMPARE = "compare"
    EXECUTE = "execute"
    EDIT = "edit"
    GENERATE = "generate"
    VALIDATE = "validate"
    SEARCH = "search"


@dataclass(frozen=True)
class PromptOperationSpec:
    operation: PromptOperation
    goal_type: str
    task_action: str
    capability: str
    read_only: bool
    requires_reasoning: bool = False
    default_artifact: str = "answer"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["operation"] = self.operation.value
        return data


OPERATION_SPECS: dict[PromptOperation, PromptOperationSpec] = {
    PromptOperation.LOCATE: PromptOperationSpec(PromptOperation.LOCATE, "locate", "inspect", "project_index", True, default_artifact="location"),
    PromptOperation.EXPLAIN_BEHAVIOR: PromptOperationSpec(PromptOperation.EXPLAIN_BEHAVIOR, "explain", "explain", "symbol_inspection", True, True, "symbol_explanation"),
    PromptOperation.EXPLAIN_USAGE: PromptOperationSpec(PromptOperation.EXPLAIN_USAGE, "explain", "explain", "symbol_inspection", True, True, "usage_explanation"),
    PromptOperation.FIND_CALLERS: PromptOperationSpec(PromptOperation.FIND_CALLERS, "locate", "inspect", "project_index", True, default_artifact="callers"),
    PromptOperation.FIND_CALLEES: PromptOperationSpec(PromptOperation.FIND_CALLEES, "locate", "inspect", "project_index", True, default_artifact="callees"),
    PromptOperation.FIND_IMPLEMENTATIONS: PromptOperationSpec(PromptOperation.FIND_IMPLEMENTATIONS, "locate", "inspect", "project_index", True, default_artifact="implementations"),
    PromptOperation.FIND_RELATED: PromptOperationSpec(PromptOperation.FIND_RELATED, "locate", "inspect", "project_index", True, default_artifact="related_entities"),
    PromptOperation.SHOW_SIGNATURE: PromptOperationSpec(PromptOperation.SHOW_SIGNATURE, "explain", "inspect", "symbol_inspection", True, default_artifact="signature"),
    PromptOperation.SHOW_SOURCE: PromptOperationSpec(PromptOperation.SHOW_SOURCE, "explain", "inspect", "symbol_inspection", True, default_artifact="source"),
    PromptOperation.COMPARE: PromptOperationSpec(PromptOperation.COMPARE, "compare", "compare", "semantic_reasoning", True, True, "comparison"),
    PromptOperation.EXECUTE: PromptOperationSpec(PromptOperation.EXECUTE, "execute", "execute", "dcc_execution", False, default_artifact="execution_result"),
    PromptOperation.EDIT: PromptOperationSpec(PromptOperation.EDIT, "modify", "modify_code", "project_edit", False, True, "code_change"),
    PromptOperation.GENERATE: PromptOperationSpec(PromptOperation.GENERATE, "generate", "generate", "code_generation", True, True, "generated_result"),
    PromptOperation.VALIDATE: PromptOperationSpec(PromptOperation.VALIDATE, "validate", "validate", "validation", True, default_artifact="validation_result"),
    PromptOperation.SEARCH: PromptOperationSpec(PromptOperation.SEARCH, "locate", "search", "project_index", True, default_artifact="search_results"),
}

SYMBOL_INSPECTION_OPERATIONS = frozenset({
    PromptOperation.EXPLAIN_BEHAVIOR,
    PromptOperation.EXPLAIN_USAGE,
    PromptOperation.FIND_CALLERS,
    PromptOperation.FIND_CALLEES,
    PromptOperation.SHOW_SIGNATURE,
    PromptOperation.SHOW_SOURCE,
})

_OPERATION_PATTERNS: tuple[tuple[PromptOperation, str], ...] = (
    (PromptOperation.EXPLAIN_BEHAVIOR, r"\b(?:what\s+does\s+(?:this|the)?\s*(?:function|method|symbol)?\s*do|what\s+is\s+(?:this|the)?\s*(?:function|method|symbol)|explain\s+(?:what|how)\b|describe\s+(?:this|the)?\s*(?:function|method|symbol))\b"),
    (PromptOperation.EXPLAIN_USAGE, r"\b(?:how\s+(?:do|can|should|would)\s+i\s+use\b|how\s+is\s+(?:this|it|the\s+(?:function|method|symbol))\s+used\b|show\s+me\s+how\s+to\s+use\b|usage\b|example\s+(?:of|using))"),
    (PromptOperation.FIND_CALLERS, r"\b(?:who|what)\s+calls?\b|\b(?:find|show|list)\s+(?:its\s+)?callers?\b|\bwhere\s+is\s+(?:it|this)\s+called\b"),
    (PromptOperation.FIND_CALLEES, r"\bwhat\s+does\s+(?:it|this)\s+call\b|\b(?:find|show|list)\s+(?:its\s+)?callees?\b"),
    (PromptOperation.SHOW_SIGNATURE, r"\b(?:show|what\s+is)\s+(?:its|the)?\s*signature\b|\barguments?\b|\bparameters?\b"),
    (PromptOperation.SHOW_SOURCE, r"\b(?:show|open|display)\s+(?:its|the)?\s*(?:source|implementation|code)\b"),
    (PromptOperation.LOCATE, r"\b(?:where\s+is|locate|find\s+the\s+(?:file|location))\b"),
)


def operation_value(value: PromptOperation | str) -> str:
    return value.value if isinstance(value, PromptOperation) else str(value or "").strip().lower()


def normalize_operation(value: PromptOperation | str) -> PromptOperation | None:
    raw = operation_value(value)
    try:
        return PromptOperation(raw)
    except ValueError:
        return None


def normalize_requested_operations(values: Iterable[PromptOperation | str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or ():
        operation = normalize_operation(value)
        if operation is not None and operation.value not in normalized:
            normalized.append(operation.value)
    return normalized


def operation_spec(value: PromptOperation | str) -> PromptOperationSpec | None:
    operation = normalize_operation(value)
    return OPERATION_SPECS.get(operation) if operation is not None else None


def is_symbol_inspection_operation(value: PromptOperation | str) -> bool:
    operation = normalize_operation(value)
    return operation in SYMBOL_INSPECTION_OPERATIONS if operation is not None else False


def detect_explicit_symbol_operations(text: str, target_symbol: str) -> list[str]:
    """Detect ordered terminal operations for an already-resolved symbol target."""
    if not str(target_symbol or "").strip():
        return []
    lower = str(text or "").lower()
    operations: list[str] = []
    for operation, pattern in _OPERATION_PATTERNS:
        if re.search(pattern, lower) and operation.value not in operations:
            operations.append(operation.value)
    return operations


def operation_objective(value: PromptOperation | str, target: str) -> str:
    operation = normalize_operation(value)
    target = str(target or "the requested target")
    templates = {
        PromptOperation.EXPLAIN_BEHAVIOR: f"Explain what {target} does from its source implementation.",
        PromptOperation.EXPLAIN_USAGE: f"Explain how to use {target}, including required inputs and a grounded example.",
        PromptOperation.FIND_CALLERS: f"Find and summarize project callers of {target}.",
        PromptOperation.FIND_CALLEES: f"Find and summarize functions called by {target}.",
        PromptOperation.FIND_IMPLEMENTATIONS: f"Find concrete implementations of {target}.",
        PromptOperation.FIND_RELATED: f"Find project entities related to {target}.",
        PromptOperation.SHOW_SIGNATURE: f"Show the signature and parameter contract for {target}.",
        PromptOperation.SHOW_SOURCE: f"Show the relevant source implementation for {target}.",
        PromptOperation.LOCATE: f"Locate {target} in the project.",
        PromptOperation.COMPARE: f"Compare {target} using the requested dimensions.",
        PromptOperation.EXECUTE: f"Execute {target} in the resolved environment.",
        PromptOperation.EDIT: f"Apply the requested code change to {target}.",
        PromptOperation.GENERATE: f"Generate the requested result for {target}.",
        PromptOperation.VALIDATE: f"Validate {target} against the requested success criteria.",
        PromptOperation.SEARCH: f"Search for project evidence about {target}.",
    }
    return templates.get(operation, f"Complete {operation_value(value)} for {target}.")
