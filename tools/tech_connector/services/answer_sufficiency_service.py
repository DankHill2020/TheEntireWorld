from __future__ import annotations

"""Validate that retrieved/generated results satisfy the user's answer contract.

This is deliberately separate from code/runtime validation.  It answers the
question: did the returned evidence actually match the requested target, scope,
deliverable, and success condition?  Retrieval success is not completion.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


_PATH_RE = re.compile(r"(?P<path>(?:[A-Za-z]:[\\/]|(?:^|\s))(?:[^\n\r:*?\"<>|]+[\\/])*[^\n\r:*?\"<>|]+\.(?:py|pyw|cpp|h|hpp|cs|js|ts|json|yaml|yml|uasset))", re.IGNORECASE)
_FUNCTION_RE = re.compile(r"\b(?:def\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_REFERENCE_RE = re.compile(r"\b(that|this|the previous|previous|same)\s+(file|function|class|helper|one)\b|\bin that file\b", re.IGNORECASE)


@dataclass(frozen=True)
class AnswerValidationResult:
    sufficient: bool
    score: float
    checks: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_action: str = ""
    escalation_tier: int | None = None
    expected_scope: str = ""
    expected_target: str = ""
    returned_paths: list[str] = field(default_factory=list)
    returned_symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_answer_sufficiency(
    state: Any,
    result: Any,
    *,
    goal: Mapping[str, Any] | None = None,
) -> AnswerValidationResult:
    """Validate one goal result against canonical request constraints."""

    prompt = str(getattr(state, "original_prompt", "") or "")
    intent = dict(getattr(state, "intent_frame", {}) or {})
    contract = dict(getattr(state, "execution_contract", {}) or {})
    goal = dict(goal or {})
    result_text = _result_text(result)
    returned_paths = _extract_paths(result)
    returned_symbols = _extract_symbols(result)

    expected_target = _expected_target(state, contract, goal)
    expected_scope = _expected_scope(prompt, intent, contract, expected_target)
    deliverable = _expected_deliverable(prompt, intent, contract, goal)

    checks: dict[str, bool] = {}
    failures: list[str] = []
    warnings: list[str] = []

    reference_required = bool(_REFERENCE_RE.search(prompt))
    reference_resolved = not reference_required or bool(expected_target)
    checks["reference_resolved"] = reference_resolved
    if not reference_resolved:
        failures.append("The conversational reference was not resolved to a concrete target before retrieval.")

    nonempty = bool(result_text.strip())
    checks["result_present"] = nonempty
    if not nonempty:
        failures.append("No concrete result was returned.")

    scope_ok = _scope_matches(expected_scope, expected_target, returned_paths)
    checks["scope_fidelity"] = scope_ok
    if not scope_ok:
        failures.append("Returned evidence includes results outside the requested file or target scope.")

    deliverable_ok = _deliverable_matches(deliverable, result, result_text, returned_symbols, returned_paths)
    checks["deliverable_fidelity"] = deliverable_ok
    if not deliverable_ok:
        failures.append(f"The result does not provide the requested deliverable type: {deliverable or 'answer'}.")

    behavior_ok = _behavior_matches(prompt, result_text, returned_symbols)
    checks["behavioral_relevance"] = behavior_ok
    if not behavior_ok:
        failures.append("The returned evidence is only a loose keyword match and does not establish the requested behavior.")

    success_ok = _success_condition_matches(goal, contract, result_text)
    checks["success_condition"] = success_ok
    if not success_ok:
        failures.append("The current goal's success condition is not demonstrated by the result.")

    score = round(sum(1.0 for value in checks.values() if value) / max(1, len(checks)), 3)
    sufficient = not failures and score >= 0.8
    next_action, tier = _next_action(
        checks,
        expected_scope=expected_scope,
        expected_target=expected_target,
    )

    if expected_target and returned_paths and scope_ok:
        warnings.extend(_path_representation_warnings(expected_target, returned_paths))

    return AnswerValidationResult(
        sufficient=sufficient,
        score=score,
        checks=checks,
        failures=failures,
        warnings=warnings,
        next_action="" if sufficient else next_action,
        escalation_tier=None if sufficient else tier,
        expected_scope=expected_scope,
        expected_target=expected_target,
        returned_paths=returned_paths,
        returned_symbols=returned_symbols,
    )


def _result_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, Mapping):
        preferred = []
        for key in ("answer", "text", "content", "summary", "result", "message", "evidence"):
            value = result.get(key)
            if value not in (None, "", [], {}):
                preferred.append(_result_text(value))
        if preferred:
            return "\n".join(part for part in preferred if part)
        return "\n".join(f"{key}: {_result_text(value)}" for key, value in result.items())
    if isinstance(result, Iterable) and not isinstance(result, (bytes, bytearray)):
        return "\n".join(_result_text(item) for item in result)
    return str(result)


def _extract_paths(result: Any) -> list[str]:
    found: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip().strip("`'\"")
        if not text:
            return
        if re.search(r"\.(?:py|pyw|cpp|h|hpp|cs|js|ts|json|yaml|yml|uasset)$", text, re.IGNORECASE):
            normalized = _normalize_path(text)
            if normalized and normalized not in found:
                found.append(normalized)

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).lower() in {"path", "file", "filepath", "file_path", "source_path", "container"}:
                    add(item)
                walk(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in _PATH_RE.finditer(value):
                add(match.group("path").strip())

    walk(result)
    return found


def _extract_symbols(result: Any) -> list[str]:
    found: list[str] = []

    def add(value: Any) -> None:
        name = str(value or "").strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and name not in found:
            found.append(name)

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).lower() in {"name", "symbol", "function", "method", "qualname"}:
                    add(item)
                walk(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in _FUNCTION_RE.finditer(value):
                add(match.group(1))

    walk(result)
    return found


def _expected_target(state: Any, contract: Mapping[str, Any], goal: Mapping[str, Any]) -> str:
    candidates = (
        goal.get("target"),
        goal.get("target_path"),
        contract.get("target"),
        contract.get("target_path"),
        contract.get("container"),
        contract.get("resolved_target"),
        getattr(state, "active_file", ""),
        (getattr(state, "operation_memory", {}) or {}).get("selected_file"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return _normalize_path(text) if _looks_like_path(text) else text
    return ""


def _expected_scope(prompt: str, intent: Mapping[str, Any], contract: Mapping[str, Any], expected_target: str) -> str:
    lower = prompt.lower()
    explicit = str(intent.get("requested_scope") or contract.get("scope") or "").strip().lower()
    if re.search(r"\b(in|inside|within)\s+(that|this|the)\s+file\b", lower):
        return "file"
    if expected_target and _looks_like_path(expected_target) and re.search(r"\b(that file|this file|current file|active file|in the file)\b", lower):
        return "file"
    return explicit or ("file" if expected_target and _looks_like_path(expected_target) else "project")


def _expected_deliverable(prompt: str, intent: Mapping[str, Any], contract: Mapping[str, Any], goal: Mapping[str, Any]) -> str:
    candidates = [
        goal.get("deliverable"),
        contract.get("deliverable"),
        intent.get("object_type"),
    ]
    for candidate in candidates:
        if isinstance(candidate, (list, tuple)) and candidate:
            candidate = candidate[0]
        text = str(candidate or "").strip().lower()
        if text:
            return text
    lower = prompt.lower()
    if re.search(r"\bfunctions?|methods?\b", lower):
        return "function"
    if re.search(r"\bfiles?\b", lower):
        return "file"
    if re.search(r"\bclasses?\b", lower):
        return "class"
    return "answer"


def _scope_matches(scope: str, expected_target: str, paths: list[str]) -> bool:
    if scope not in {"file", "exact_target"}:
        return True
    if not expected_target:
        return False
    if not paths:
        return True  # Text-only answers can still be scoped by the provider query.
    expected = _normalize_path(expected_target)
    expected_name = Path(expected).name.casefold()
    for path in paths:
        normalized = _normalize_path(path)
        if normalized.casefold() == expected.casefold():
            continue
        if Path(normalized).name.casefold() == expected_name and not Path(expected).is_absolute():
            continue
        return False
    return True


def _deliverable_matches(deliverable: str, result: Any, text: str, symbols: list[str], paths: list[str]) -> bool:
    value = deliverable.lower()
    if "function" in value or "method" in value:
        return bool(symbols or re.search(r"\b(?:def\s+)?[A-Za-z_][A-Za-z0-9_]*\s*\(", text))
    if "file" in value or "path" in value:
        return bool(paths)
    if "class" in value:
        return bool(re.search(r"\bclass\s+[A-Za-z_][A-Za-z0-9_]*", text))
    return bool(text.strip())


def _behavior_matches(prompt: str, text: str, symbols: list[str]) -> bool:
    lower = prompt.lower()
    result_lower = text.lower()
    meaningful = [
        token for token in re.findall(r"[a-z_][a-z0-9_]{2,}", lower)
        if token not in {"what", "which", "where", "that", "this", "file", "files", "function", "functions", "actual", "have", "does", "there", "create", "make"}
    ]
    if not meaningful:
        return bool(text.strip())
    matches = sum(1 for token in set(meaningful) if token in result_lower or any(token in symbol.lower() for symbol in symbols))
    # One strong behavior term is enough for narrow symbol queries; two are
    # required when the prompt contains several meaningful constraints.
    required = 1 if len(set(meaningful)) <= 2 else 2
    return matches >= required


def _success_condition_matches(goal: Mapping[str, Any], contract: Mapping[str, Any], text: str) -> bool:
    condition = str(goal.get("success_condition") or goal.get("success") or contract.get("success_condition") or "").strip()
    if not condition:
        return bool(text.strip())
    if re.search(r"\b(return|provide|identify|list|find|resolve|explain)\b", condition, re.IGNORECASE):
        return bool(text.strip())
    return bool(text.strip())


def _next_action(checks: Mapping[str, bool], *, expected_scope: str, expected_target: str) -> tuple[str, int]:
    if not checks.get("reference_resolved", True):
        return "resolve_conversation_reference", 0
    if not checks.get("scope_fidelity", True):
        return "repeat_retrieval_with_hard_target_filter", 1
    if not checks.get("deliverable_fidelity", True):
        return "retrieve_requested_symbol_type", 1
    if not checks.get("behavioral_relevance", True):
        return "inspect_ast_bodies_and_call_relationships", 2
    if not checks.get("success_condition", True):
        return "escalate_evidence_and_revalidate", 2
    return "retry_current_goal", 1


def _path_representation_warnings(expected: str, returned: list[str]) -> list[str]:
    expected_name = Path(expected).name.casefold()
    if any(Path(path).name.casefold() == expected_name and _normalize_path(path).casefold() != _normalize_path(expected).casefold() for path in returned):
        return ["A result used the same filename through a different path representation; verify the canonical path before mutation."]
    return []


def _looks_like_path(value: str) -> bool:
    return bool(re.search(r"[\\/]", value) or re.search(r"\.[A-Za-z0-9]{1,8}$", value))


def _normalize_path(value: str) -> str:
    text = str(value or "").strip().strip("`'\"")
    try:
        return str(Path(text)).replace("\\", "/")
    except Exception:
        return text.replace("\\", "/")
