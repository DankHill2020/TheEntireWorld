"""Small grammatical request-frame extraction for prompt routing.

This sits between raw keyword checks and route selection.  It answers questions
such as whether "selected" is the thing being queried, an argument to an action,
or a scope for a property/list request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class RequestFrame:
    action_kind: str = "respond"
    object_kind: str = ""
    selection_role: str = ""
    read_only: bool = False
    wants_execution: bool = False
    wants_mutation: bool = False
    no_execute_guard: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_request_frame(prompt: str, *, host: str = "") -> RequestFrame:
    text = prompt or ""
    lower = text.lower()
    no_execute = bool(
        re.search(
            r"\b(do not|don't|dont|never|without)\s+"
            r"(?:run|execute|apply|create|add|modify|change|set|delete|remove|edit)\b"
            r"|\b(no execute|dry run|plan only)\b",
            lower,
        )
    )
    query = bool(re.search(r"\b(what|which|where|list|show|report|get|inspect|scan|find|explain|how many)\b", lower))
    execute = bool(not no_execute and re.search(r"\b(run|execute|call|launch|perform|export|import|bake|render|simulate|cook)\b", lower))
    mutate = bool(
        not no_execute
        and re.search(
            r"\b(create|make|add|edit|modify|update|fix|patch|delete|remove|move|connect|set|assign|bind|skin|export|import)\b",
            lower,
        )
    )
    reasons: list[str] = []

    selection_role = ""
    if re.search(r"\bwhat(?:'s|\s+is)\s+(?:currently\s+)?selected\b|\bcurrent\s+selection\s*\??\s*$", lower):
        selection_role = "subject"
        reasons.append("selection is the queried subject")
    elif re.search(r"\b(?:for|from|on|of|with|using)\s+(?:the\s+)?(?:current\s+)?selection\b", lower) or re.search(
        r"\buse\s+(?:the\s+)?(?:current\s+)?selection\s+to\b",
        lower,
    ):
        selection_role = "scope"
        reasons.append("selection scopes another requested object or action")
    elif re.search(r"\bselected\s+(?:actors?|assets?|objects?|nodes?|meshes?|items?|asset|object|node|mesh)\b", lower):
        selection_role = "scope"
        reasons.append("selected modifies the object noun")
    elif re.search(r"\bselected\b|\bselection\b", lower):
        selection_role = "context"
        reasons.append("selection is contextual")

    object_kind = ""
    if re.search(r"\b(properties|attributes|attrs|details|metadata|channels|parameters|params|parms)\b", lower):
        object_kind = "properties"
    elif re.search(r"\b(actors?|assets?|objects?|nodes?|meshes?|items?)\b", lower):
        object_kind = "scene_items"
    elif re.search(r"\b(project|snapshot|level|world|scene)\b", lower):
        object_kind = "host_state"
    elif selection_role == "subject":
        object_kind = "selection"

    if execute or mutate:
        action_kind = "execute"
    elif query:
        action_kind = "query"
    elif re.search(r"\b(explain|teach|summarize|compare|think)\b", lower):
        action_kind = "explain"
    else:
        action_kind = "respond"

    if no_execute:
        reasons.append("explicit no-execute guard")
    if execute:
        reasons.append("execution verb is the main action")
    if mutate:
        reasons.append("mutation verb is the main action")
    if query:
        reasons.append("query verb is present")

    return RequestFrame(
        action_kind=action_kind,
        object_kind=object_kind,
        selection_role=selection_role,
        read_only=bool(no_execute or (query and not execute and not mutate)),
        wants_execution=execute,
        wants_mutation=mutate,
        no_execute_guard=no_execute,
        reasons=reasons,
    )
