"""Deterministic parsing for references and scoped project queries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


_MEMBER_TYPES = {
    "function": "function",
    "functions": "function",
    "method": "method",
    "methods": "method",
    "class": "class",
    "classes": "class",
    "helper": "helper",
    "helpers": "helper",
    "symbol": "symbol",
    "symbols": "symbol",
}

_BEHAVIOR_VERBS = (
    "create", "creates", "creating",
    "build", "builds", "building",
    "make", "makes", "making",
    "generate", "generates", "generating",
    "find", "finds", "finding",
    "detect", "detects", "detecting",
    "resolve", "resolves", "resolving",
    "handle", "handles", "handling",
    "decide", "decides", "deciding",
    "use", "uses", "using",
    "call", "calls", "calling",
    "validate", "validates", "validating",
    "return", "returns", "returning",
)

_SCOPED_MEMBER_RE = re.compile(
    rf"""
    \b(?:what|which|show|list|find)\s+
    (?P<member_type>functions?|methods?|classes?|helpers?|symbols?)\s+
    (?:from|in|inside|within)\s+
    (?P<container>
        (?:
            .+?
            (?:
                \b[A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]{{1,8}}\b
                |
                \b(?:file|module|service|script|class|package)\b
            )
        )
    )\s+
    (?P<behavior_verb>{'|'.join(_BEHAVIOR_VERBS)})\b
    (?P<behavior_object>.*?)
    [?.!]*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_DEICTIC_FILE_RE = re.compile(
    r"\b(that|this|the previous|the last|the file you just found|the file just found)\s+file\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ScopedMemberQuery:
    original_text: str
    member_type: str
    container_type: str
    container_query: str
    behavior_verb: str
    behavior_object: str
    behavior_description: str
    reference_kind: str = "explicit_description"
    confidence: float = 0.9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_scoped_member_query(text: str) -> ScopedMemberQuery | None:
    source = re.sub(r"\s+", " ", str(text or "")).strip()
    match = _SCOPED_MEMBER_RE.search(source)
    if not match:
        return None

    raw_container = match.group("container").strip(" ,")
    behavior_verb = match.group("behavior_verb").strip().lower()
    behavior_object = match.group("behavior_object").strip(" ,.?")
    member_type = _MEMBER_TYPES.get(
        match.group("member_type").lower(),
        match.group("member_type").lower().rstrip("s"),
    )

    container_type = _infer_container_type(raw_container)
    reference_kind = (
        "conversation_reference"
        if _DEICTIC_FILE_RE.search(raw_container)
        else "explicit_path"
        if re.search(r"\.[A-Za-z0-9_]{1,8}\b", raw_container)
        else "explicit_description"
    )
    confidence = 0.98 if reference_kind == "explicit_path" else 0.94
    if reference_kind == "conversation_reference":
        confidence = 0.88

    return ScopedMemberQuery(
        original_text=source,
        member_type=member_type,
        container_type=container_type,
        container_query=_clean_container_query(raw_container, container_type),
        behavior_verb=behavior_verb,
        behavior_object=behavior_object,
        behavior_description=" ".join(
            part for part in (behavior_verb, behavior_object) if part
        ).strip(),
        reference_kind=reference_kind,
        confidence=confidence,
    )


def contains_conversation_file_reference(text: str) -> bool:
    return bool(_DEICTIC_FILE_RE.search(str(text or "")))


def _infer_container_type(container: str) -> str:
    lower = container.lower()
    for value in ("file", "module", "service", "script", "class", "package"):
        if re.search(rf"\b{re.escape(value)}\b", lower):
            return value
    if re.search(r"\.[A-Za-z0-9_]{1,8}\b", container):
        return "file"
    return "file"


def _clean_container_query(container: str, container_type: str) -> str:
    value = re.sub(
        r"^\s*(?:the|a|an)\s+",
        "",
        container.strip(),
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"\s+\b{re.escape(container_type)}\b\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", value).strip()
