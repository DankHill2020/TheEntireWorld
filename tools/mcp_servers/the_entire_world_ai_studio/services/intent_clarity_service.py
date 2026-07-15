from __future__ import annotations

"""Structured intent clarification and constraint extraction.

This service separates the action, target, qualifiers, scope limiters, success
criteria, and unresolved ambiguity so later stages do not flatten a precise
request into a broad capability label.
"""

from dataclasses import asdict, dataclass, field
import re
from typing import Any


@dataclass
class IntentFrame:
    action: str = "unknown"
    object_type: str = ""
    target_text: str = ""
    qualifiers: list[str] = field(default_factory=list)
    negative_constraints: list[str] = field(default_factory=list)
    quantity: int | None = None
    ordering: str = ""
    requested_scope: str = ""
    success_criteria: list[str] = field(default_factory=list)
    ambiguity: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_intent_frame(prompt: str) -> IntentFrame:
    raw = prompt or ""
    lower = re.sub(r"\s+", " ", raw.lower()).strip()
    action = _action(lower)
    object_type = _object_type(lower)
    quantity = _quantity(lower)
    ordering = "first_match" if re.search(r"\b(first|next)\b", lower) else ""
    scope = _scope(lower)
    qualifiers: list[str] = []
    negatives: list[str] = []
    success: list[str] = []
    ambiguity: list[str] = []

    for label, pattern in (
        ("concise", r"\b(concise|brief|short)\b"),
        ("minimal", r"\b(minimal|smallest|narrow)\b"),
        ("existing_only", r"\b(existing|reuse|do not duplicate|don't duplicate)\b"),
        ("report_changes", r"\b(report back|tell me what|summarize what|report what)\b"),
        ("validate", r"\b(validate|verify|compile|test)\b"),
    ):
        if re.search(pattern, lower):
            qualifiers.append(label)

    for match in re.finditer(r"\b(do not|don't|never|without)\s+([^,.!?;]+)", lower):
        negatives.append(match.group(0).strip())

    if "report_changes" in qualifiers:
        success.append("Report the exact target changed and the precise modification.")
    if "validate" in qualifiers:
        success.append("Provide concrete validation evidence.")
    if action in {"add", "modify", "repair", "refactor", "create"}:
        success.append("Complete only the requested mutation and preserve unrelated behavior.")

    target_text = _target_phrase(raw)
    if action in {"modify", "repair", "refactor"} and not target_text and not ordering:
        ambiguity.append("The mutation target is not explicit.")
    if action == "unknown":
        ambiguity.append("The requested action is unclear.")
    confidence = 0.95 if action != "unknown" and (target_text or ordering or action == "inspect") else 0.65
    return IntentFrame(
        action=action,
        object_type=object_type,
        target_text=target_text,
        qualifiers=qualifiers,
        negative_constraints=negatives,
        quantity=quantity,
        ordering=ordering,
        requested_scope=scope,
        success_criteria=success,
        ambiguity=ambiguity,
        confidence=confidence,
    )


def render_intent_frame(frame: IntentFrame | dict[str, Any]) -> str:
    f = frame if isinstance(frame, IntentFrame) else IntentFrame(**dict(frame or {}))
    lines = [
        "Intent frame:",
        f"- Action: {f.action}",
        f"- Object: {f.object_type or '(unspecified)'}",
        f"- Target: {f.target_text or '(resolve deterministically)'}",
        f"- Quantity/order: {f.quantity if f.quantity is not None else '(unspecified)'} / {f.ordering or '(none)'}",
        f"- Requested scope: {f.requested_scope or '(infer conservatively)'}",
    ]
    if f.qualifiers:
        lines.append("- Qualifiers: " + ", ".join(f.qualifiers))
    if f.negative_constraints:
        lines.append("- Negative constraints: " + " | ".join(f.negative_constraints))
    if f.ambiguity:
        lines.append("- Ambiguity: " + " | ".join(f.ambiguity))
    return "\n".join(lines)


def _action(lower: str) -> str:
    patterns = (
        # Mutation verbs take precedence over incidental retrieval words such as
        # "find" inside "add X to the first function you find".
        ("repair", r"\b(fix|repair|debug|correct)\b"),
        ("refactor", r"\b(refactor|restructure|clean up)\b"),
        ("add", r"\b(add|insert|append)\b"),
        ("create", r"\b(create|build|generate|write|implement)\b"),
        ("modify", r"\b(modify|change|update|wire|connect|rename|remove|delete)\b"),
        ("execute", r"\b(run|execute|call|launch)\b"),
        ("inspect", r"\b(find|search|show|list|inspect|explain|identify|what|which|where)\b"),
    )
    for action, pattern in patterns:
        if re.search(pattern, lower):
            return action
    return "unknown"


def _object_type(lower: str) -> str:
    for kind, pattern in (
        ("docstring", r"\bdocstrings?\b"),
        ("function", r"\bfunctions?|methods?\b"),
        ("class", r"\bclasses?\b"),
        ("ui_handler", r"\bui\s+handler\b"),
        ("file", r"\bfiles?\b"),
        ("graph", r"\bgraphs?|nodes?|pins?\b"),
        ("asset", r"\bassets?\b"),
    ):
        if re.search(pattern, lower):
            return kind
    return ""


def _quantity(lower: str) -> int | None:
    match = re.search(r"\b(?:first|only|exactly)\s+(\d+)\b", lower)
    if match:
        return int(match.group(1))
    if re.search(r"\b(first|one|single)\b", lower):
        return 1
    return None


def _scope(lower: str) -> str:
    if re.search(r"\b(entire project|whole project|project-wide|all files|every file)\b", lower):
        return "project"
    if re.search(r"\b(module|package|folder|directory)\b", lower):
        return "module"
    if re.search(r"\b(this file|current file|active file)\b", lower):
        return "file"
    if re.search(r"\b(first|one|single|this function|selected function|this handler)\b", lower):
        return "exact_target"
    return ""


def _target_phrase(raw: str) -> str:
    # Preserve user wording after common action verbs; this is advisory metadata,
    # not a replacement for indexed target resolution.
    match = re.search(r"\b(?:add|create|write|implement|insert|modify|change|update|fix|repair|refactor|rename|find|show|inspect)\b\s+(.+)", raw, flags=re.I)
    return match.group(1).strip()[:300] if match else ""
