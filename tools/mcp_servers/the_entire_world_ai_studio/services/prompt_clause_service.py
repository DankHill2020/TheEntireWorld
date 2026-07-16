"""Deterministic prompt clause decomposition for Tech Connector.

This service does not select a route or execute work. It converts raw prompt
text into ordered clause records while preserving sequencing, conditions,
approval gates, negative constraints, and references between clauses.

The semantic intent model receives these smaller units instead of having to
discover all workflow structure from one large paragraph.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


_ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("approval", r"\b(wait for approval|await approval|ask for approval|stop before editing|stop before changing|do not edit until|don't edit until|dont edit until)\b"),
    ("validate", r"\b(validate|verify|compile|syntax[- ]?check|test|check the result|confirm it works)\b"),
    ("report", r"\b(report|summarize|summarise|explain what changed|show me the result|tell me what changed|document)\b"),
    ("plan", r"\b(plan|propose|outline|architect|map out|come up with improvements?|design improvements?)\b"),
    ("modify_code", r"\b(fix|patch|modify|edit|update|refactor|rename|remove|delete|wire|connect|implement)\b"),
    ("generate", r"\b(generate|write|create|build|make|add|design|draft|produce)\b"),
    ("execute", r"\b(run|execute|launch|apply|perform|open|move|select|import|export)\b"),
    ("search", r"\b(find|locate|search|look for|identify|inspect|review|analyze|analyse|determine|check whether|see if)\b"),
    ("explain", r"\b(explain|teach|show me how|how would|how do|how can|compare|describe)\b"),
)

_CONSTRAINT_PATTERN = re.compile(
    r"\b(do not|don't|dont|never|only|must|without|preserve|reuse|before|after|until)\b",
    re.IGNORECASE,
)

_LIST_PREFIX = re.compile(
    r"^\s*(?:[-*•]+|\d+[.)]|[A-Za-z][.)])\s+",
    re.MULTILINE,
)

_CONNECTOR_SPLIT = re.compile(
    r"\s*(?:;|\n+|(?<=[.!?])\s+|"
    r"\b(?:and then|then|after that|next|finally|before that)\b)\s*",
    re.IGNORECASE,
)

_CONDITION_PREFIX = re.compile(
    r"^\s*(if|unless|when|once|otherwise|else|or else)\b[\s,:-]*(.*)$",
    re.IGNORECASE,
)

_PRONOUN_START = re.compile(
    r"^\s*(it|that|this|them|those|these|the result|the code|the file|the function|the helper)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PromptClause:
    clause_id: str
    text: str
    normalized_text: str
    action: str
    object_text: str = ""
    sequence_index: int = 0
    depends_on: tuple[str, ...] = ()
    condition_kind: str = ""
    conditional_on: str = ""
    branch_group: str = ""
    constraints: tuple[str, ...] = ()
    requires_confirmation: bool = False
    read_only: bool = True
    confidence: float = 0.5
    source_span: tuple[int, int] = (0, 0)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["depends_on"] = list(self.depends_on)
        data["constraints"] = list(self.constraints)
        data["source_span"] = list(self.source_span)
        return data


@dataclass(frozen=True)
class PromptClausePlan:
    original_text: str
    normalized_text: str
    clauses: tuple[PromptClause, ...]
    confidence: float
    has_conditions: bool
    has_approval_gate: bool
    has_multiple_actions: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "prompt_clause_plan_v1",
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "clauses": [clause.to_dict() for clause in self.clauses],
            "confidence": self.confidence,
            "has_conditions": self.has_conditions,
            "has_approval_gate": self.has_approval_gate,
            "has_multiple_actions": self.has_multiple_actions,
        }


def normalize_prompt_text(text: str) -> str:
    """Normalize spacing and a small set of safe, high-confidence typos."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    typo_map = {
        r"\bwaht\b": "what",
        r"\bwahat\b": "what",
        r"\bnwo\b": "now",
        r"\bteh\b": "the",
        r"\bhtose\b": "those",
        r"\bweas\b": "was",
        r"\binterpretor\b": "interpreter",
    }
    for pattern, replacement in typo_map.items():
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    return value.strip()


def split_prompt_clauses(text: str) -> PromptClausePlan:
    """Split a prompt into deterministic workflow clauses."""
    original = str(text or "")
    normalized = normalize_prompt_text(original)
    if not normalized:
        return PromptClausePlan(original, "", (), 1.0, False, False, False)

    segments = _segments_with_spans(normalized)
    clauses: list[PromptClause] = []
    last_action_id = ""
    last_nonapproval_id = ""
    branch_anchor_id = ""
    active_branch_group = ""

    for index, (segment, start, end) in enumerate(segments, start=1):
        cleaned = _LIST_PREFIX.sub("", segment).strip(" \t,;")
        if not cleaned:
            continue

        condition_kind = ""
        conditional_on = ""
        branch_group = ""
        condition_match = _CONDITION_PREFIX.match(cleaned)
        if condition_match:
            condition_kind = condition_match.group(1).lower()
            remainder = condition_match.group(2).strip()
            if remainder:
                cleaned = remainder
            if condition_kind in {"if", "unless", "when", "once"}:
                branch_anchor_id = last_nonapproval_id or last_action_id
                active_branch_group = f"branch_{index}"
                conditional_on = branch_anchor_id
                branch_group = active_branch_group
            else:
                conditional_on = branch_anchor_id or last_nonapproval_id
                branch_group = active_branch_group or f"branch_{index}"

        action, action_confidence = _classify_action(cleaned)
        clause_id = f"clause_{len(clauses) + 1}"
        requires_confirmation = action == "approval" or bool(
            re.search(
                r"\b(ask first|wait for approval|until i approve|before editing|before changing|do not edit until|don't edit until)\b",
                cleaned,
                re.IGNORECASE,
            )
        )

        read_only = action not in {"modify_code", "execute"}
        if action == "generate":
            read_only = bool(
                re.search(
                    r"\b(example|show me how|how would|how do i|how can i|"
                    r"do not edit|don't edit|dont edit|plan only|design only|"
                    r"without changing|without editing)\b",
                    cleaned,
                    re.IGNORECASE,
                )
            )

        dependencies: list[str] = []
        if last_action_id:
            dependencies.append(last_action_id)
        if conditional_on and conditional_on not in dependencies:
            dependencies.append(conditional_on)

        if action == "approval":
            # Approval gates depend on the plan immediately before them.
            dependencies = [last_nonapproval_id] if last_nonapproval_id else dependencies

        constraints = _extract_constraints(cleaned)
        object_text = _object_text(cleaned, action)

        clause = PromptClause(
            clause_id=clause_id,
            text=segment.strip(),
            normalized_text=cleaned,
            action=action,
            object_text=object_text,
            sequence_index=len(clauses) + 1,
            depends_on=tuple(dep for dep in dependencies if dep),
            condition_kind=condition_kind,
            conditional_on=conditional_on,
            branch_group=branch_group,
            constraints=tuple(constraints),
            requires_confirmation=requires_confirmation,
            read_only=read_only,
            confidence=action_confidence,
            source_span=(start, end),
            metadata={
                "starts_with_reference": bool(_PRONOUN_START.match(cleaned)),
                "explicit_sequence": index > 1,
            },
        )
        clauses.append(clause)
        last_action_id = clause_id
        if action != "approval":
            last_nonapproval_id = clause_id

    clauses = _repair_dependencies(clauses)
    confidence = (
        sum(clause.confidence for clause in clauses) / len(clauses)
        if clauses
        else 1.0
    )
    actions = {clause.action for clause in clauses if clause.action != "constraint"}
    return PromptClausePlan(
        original_text=original,
        normalized_text=normalized,
        clauses=tuple(clauses),
        confidence=round(confidence, 3),
        has_conditions=any(clause.condition_kind for clause in clauses),
        has_approval_gate=any(clause.requires_confirmation for clause in clauses),
        has_multiple_actions=len(actions) > 1 or len(clauses) > 1,
    )


def clause_plan_for_model(plan: PromptClausePlan | dict[str, Any]) -> str:
    """Render a compact packet for the lightweight semantic model."""
    data = plan.to_dict() if isinstance(plan, PromptClausePlan) else dict(plan or {})
    lines = ["DETERMINISTIC CLAUSE PLAN"]
    for clause in data.get("clauses") or []:
        lines.append(
            f"- {clause.get('clause_id')}: action={clause.get('action')}; "
            f"depends_on={clause.get('depends_on') or []}; "
            f"condition={clause.get('condition_kind') or '-'}; "
            f"text={clause.get('normalized_text') or clause.get('text') or ''}"
        )
    return "\n".join(lines)


def _segments_with_spans(text: str) -> list[tuple[str, int, int]]:
    # Preserve numbered/bulleted lines as independent units before connector splitting.
    line_units: list[tuple[str, int, int]] = []
    cursor = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.strip()
        start = cursor
        end = cursor + len(raw_line)
        cursor = end
        if line:
            line_units.append((line, start, end))

    if len(line_units) <= 1:
        line_units = [(text, 0, len(text))]

    output: list[tuple[str, int, int]] = []
    for line, base_start, _base_end in line_units:
        local_cursor = 0
        for match in _CONNECTOR_SPLIT.finditer(line):
            piece = line[local_cursor:match.start()].strip()
            if piece:
                piece_start = base_start + local_cursor
                output.append((piece, piece_start, piece_start + len(piece)))
            local_cursor = match.end()
        piece = line[local_cursor:].strip()
        if piece:
            piece_start = base_start + local_cursor
            output.append((piece, piece_start, piece_start + len(piece)))

    return _merge_fragments(output)


def _merge_fragments(
    segments: list[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    """Avoid turning small subordinate fragments into fake goals."""
    merged: list[tuple[str, int, int]] = []
    for segment, start, end in segments:
        action, confidence = _classify_action(segment)
        subordinate = bool(
            re.match(
                r"^\s*(that|which|who|where|with|using|based on|for|so that|to)\b",
                segment,
                re.IGNORECASE,
            )
        )
        if merged and (subordinate or (action == "respond" and confidence < 0.6)):
            previous, previous_start, _ = merged[-1]
            merged[-1] = (f"{previous} {segment}".strip(), previous_start, end)
        else:
            merged.append((segment, start, end))
    return merged


def _classify_action(text: str) -> tuple[str, float]:
    lower = text.lower()
    for action, pattern in _ACTION_PATTERNS:
        if re.search(pattern, lower):
            return action, 0.94 if action in {"approval", "validate", "report"} else 0.86
    if _CONSTRAINT_PATTERN.search(lower):
        return "constraint", 0.72
    return "respond", 0.5


def _object_text(text: str, action: str) -> str:
    patterns = {
        "search": r"\b(?:find|locate|search(?: for)?|look for|identify|inspect|review|analy[sz]e|determine)\b\s+(.+)",
        "generate": r"\b(?:generate|write|create|build|make|add|design|draft|produce)\b\s+(.+)",
        "modify_code": r"\b(?:fix|patch|modify|edit|update|refactor|rename|remove|delete|wire|connect|implement)\b\s+(.+)",
        "execute": r"\b(?:run|execute|launch|apply|perform|open|move|select|import|export)\b\s+(.+)",
        "validate": r"\b(?:validate|verify|compile|test|check)\b\s*(.*)",
        "report": r"\b(?:report|summari[sz]e|explain|show|tell|document)\b\s*(.*)",
        "plan": r"\b(?:plan|propose|outline|architect|map out|design)\b\s*(.*)",
        "explain": r"\b(?:explain|teach|show me how|how would|how do|how can|compare|describe)\b\s*(.*)",
    }
    pattern = patterns.get(action)
    if not pattern:
        return text.strip()
    match = re.search(pattern, text, re.IGNORECASE)
    return (match.group(1).strip() if match else text.strip())[:500]


def _extract_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for match in re.finditer(
        r"\b(?:do not|don't|dont|never|only|must|without|preserve|reuse|before|after|until)\b[^.;]*",
        text,
        re.IGNORECASE,
    ):
        value = re.sub(r"\s+", " ", match.group(0)).strip()
        if value and value not in constraints:
            constraints.append(value)
    return constraints[:6]


def _repair_dependencies(
    clauses: list[PromptClause],
) -> list[PromptClause]:
    """Make independent repeated searches parallel while preserving synthesis."""
    if len(clauses) < 2:
        return clauses

    repaired: list[PromptClause] = []
    search_ids: list[str] = []
    for clause in clauses:
        dependencies = list(clause.depends_on)
        if clause.action == "search":
            # Consecutive independent searches should not serialize each other.
            if repaired and repaired[-1].action == "search" and not clause.condition_kind:
                dependencies = [
                    dep
                    for dep in dependencies
                    if dep != repaired[-1].clause_id
                ]
            search_ids.append(clause.clause_id)
        elif clause.action in {"report", "explain"} and len(search_ids) > 1:
            dependencies = list(dict.fromkeys([*search_ids, *dependencies]))

        repaired.append(
            PromptClause(
                clause_id=clause.clause_id,
                text=clause.text,
                normalized_text=clause.normalized_text,
                action=clause.action,
                object_text=clause.object_text,
                sequence_index=clause.sequence_index,
                depends_on=tuple(dependencies),
                condition_kind=clause.condition_kind,
                conditional_on=clause.conditional_on,
                branch_group=clause.branch_group,
                constraints=clause.constraints,
                requires_confirmation=clause.requires_confirmation,
                read_only=clause.read_only,
                confidence=clause.confidence,
                source_span=clause.source_span,
                metadata=clause.metadata,
            )
        )
    return repaired
