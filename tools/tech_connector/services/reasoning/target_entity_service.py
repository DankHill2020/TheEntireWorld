from __future__ import annotations

"""Phrase-aware target entity extraction for project and DCC requests.

Explicit filenames, paths, symbols, quoted names, and scoped conversational
references remain intact instead of being flattened into generic search tokens.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class TargetEntity:
    value: str
    kind: str
    confidence: float
    explicit: bool = True
    source: str = "prompt"
    normalized: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FILE_EXTENSIONS = (
    "py", "pyi", "cpp", "c", "cc", "h", "hpp", "cs", "json", "yaml", "yml",
    "toml", "ini", "ui", "qml", "md", "txt", "uasset", "umap", "fbx", "ma", "mb",
)


def extract_target_entities(prompt: str) -> list[TargetEntity]:
    text = prompt or ""
    entities: list[TargetEntity] = []
    seen: set[tuple[str, str]] = set()

    def add(value: str, kind: str, confidence: float, **metadata: Any) -> None:
        cleaned = value.strip().strip("`\"'")
        if not cleaned:
            return
        normalized = _normalize(cleaned, kind)
        key = (kind, normalized.casefold())
        if key in seen:
            return
        seen.add(key)
        entities.append(TargetEntity(cleaned, kind, confidence, normalized=normalized, metadata=metadata))

    # Full Windows/POSIX paths first so basename extraction does not lose intent.
    path_pattern = rf"(?P<path>(?:[A-Za-z]:[\\/]|(?:\.{0,2}[\\/])|/)[^\s<>|?*\"']+?(?:\.(?:{'|'.join(_FILE_EXTENSIONS)})))"
    for match in re.finditer(path_pattern, text, flags=re.I):
        add(match.group("path").rstrip(".,;:)"), "path", 0.995)

    filename_pattern = rf"(?<![\w.])(?P<name>[A-Za-z0-9_.-]+\.(?:{'|'.join(_FILE_EXTENSIONS)}))(?![\w.])"
    for match in re.finditer(filename_pattern, text, flags=re.I):
        name = match.group("name")
        add(name, "filename", 0.99, suffix=Path(name).suffix.lower())

    # Backtick/quoted names often denote exact symbols, widgets, assets, or files.
    for match in re.finditer(r"[`\"']([A-Za-z_][A-Za-z0-9_.:/\\-]{1,180})[`\"']", text):
        value = match.group(1)
        kind = "filename" if re.search(r"\.[A-Za-z0-9]{1,8}$", value) else "symbol"
        add(value, kind, 0.96, quoted=True)

    # Chat mentions that look like Python qualified names are strong explicit
    # code targets, not fuzzy search terms.
    for match in re.finditer(
        r"(?<![\w.])@([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,})(?![\w.])",
        text,
    ):
        add(match.group(1), "symbol", 0.995, mention=True, qualified=True)

    # Module-level mentions such as @custom_qt.custom_widgets are explicit
    # scope targets. They are not social handles or fuzzy search terms.
    for match in re.finditer(
        r"(?<![\w.])@([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)(?![\w.])",
        text,
    ):
        add(match.group(1), "module", 0.985, mention=True, qualified=True)

    # A dotted name governed by an explicit location relation is a module
    # target even when the user does not prefix it with ``@``. Restricting the
    # match to target relations avoids treating API calls elsewhere in the
    # request as files to edit.
    for match in re.finditer(
        r"\b(?:in|into|inside|within|module)\s+"
        r"`?([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`?"
        r"(?![\w.])",
        text,
        flags=re.I,
    ):
        add(
            match.group(1),
            "module",
            0.995,
            relation="explicit_target",
            qualified=True,
        )

    # Python-like function/class references, including foo() and Class.method.
    for match in re.finditer(r"(?<![\w])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\(\s*\)", text):
        add(match.group(1), "symbol", 0.97, callable=True)

    # Explicit UI labels and graph/asset labels.
    for match in re.finditer(r"\b(?:the\s+)?([A-Z][A-Za-z0-9 _-]{2,80})\s+(button|dialog|window|widget|menu|handler|graph|asset)\b", text):
        add(f"{match.group(1).strip()} {match.group(2)}", "ui_or_asset", 0.9, subtype=match.group(2).lower())

    # "to/in/from FILE" carries a strong target relationship.
    for match in re.finditer(
        rf"\b(?:to|in|inside|within|from|open)\s+([A-Za-z0-9_.-]+\.(?:{'|'.join(_FILE_EXTENSIONS)}))\b",
        text,
        flags=re.I,
    ):
        add(match.group(1), "filename", 0.995, relation="explicit_target")

    entities.sort(key=lambda item: item.confidence, reverse=True)
    return entities


def primary_target_entity(prompt: str) -> TargetEntity | None:
    entities = extract_target_entities(prompt)
    return entities[0] if entities else None


def render_target_entities(entities: list[TargetEntity] | list[dict[str, Any]]) -> str:
    if not entities:
        return "Explicit target entities: none"
    lines = ["Explicit target entities:"]
    for raw in entities:
        item = raw if isinstance(raw, TargetEntity) else TargetEntity(**dict(raw))
        lines.append(f"- {item.kind}: {item.value} confidence={item.confidence:.3f}")
    return "\n".join(lines)


def _normalize(value: str, kind: str) -> str:
    value = value.strip()
    if kind in {"path", "filename"}:
        return value.replace("\\", "/")
    return value


_MEMBER_TYPES = {
    "function": "function",
    "functions": "function",
    "method": "method",
    "methods": "method",
    "class": "class",
    "classes": "class",
    "helper": "helper",
    "helpers": "helper",
    "widget": "class",
    "widgets": "class",
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

_SCOPED_MEMBER_EXISTENCE_RE = re.compile(
    rf"""
    \b(?:are\s+there|is\s+there|does\s+.+?\s+have|do\s+.+?\s+have|any)\s+
    (?P<member_type>functions?|methods?|classes?|helpers?|symbols?)\s+
    (?:from|in|inside|within)\s+
    (?P<container>.+?)\s+
    (?:that|which|to)\s+
    (?P<behavior_verb>{'|'.join(_BEHAVIOR_VERBS)})\b
    (?P<behavior_object>.*?)[?.!]*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SCOPED_MEMBER_GUIDANCE_RE = re.compile(
    rf"""
    \b(?:what\s+would\s+i\s+do\s+if\s+i\s+needed|what\s+would\s+we\s+do\s+if\s+we\s+needed|
       how\s+would\s+i\s+(?:make|create|build|add)|how\s+would\s+we\s+(?:make|create|build|add))\s+
    (?:a\s+|an\s+|the\s+)?(?P<member_type>functions?|methods?|classes?|helpers?|symbols?|widgets?)\s+
    (?:to|that|which|for)\s+
    (?P<behavior_verb>{'|'.join(_BEHAVIOR_VERBS)})\b
    (?P<behavior_object>.*?)\s+
    (?:in|inside|within|from)\s+
    (?P<container>@?[A-Za-z_][A-Za-z0-9_.]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*|[A-Za-z0-9_.-]+\.[A-Za-z0-9_]{{1,8}})
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
    match = (
        _SCOPED_MEMBER_RE.search(source)
        or _SCOPED_MEMBER_EXISTENCE_RE.search(source)
        or _SCOPED_MEMBER_GUIDANCE_RE.search(source)
    )
    if not match:
        guidance_match = re.search(
            r"\bwhat\s+would\s+i\s+do\s+if\s+i\s+needed\s+"
            r"(?:a\s+|an\s+|the\s+)?(?P<member_type>class|function|method|helper|widget)\s+"
            r"(?:to|that|which|for)\s+(?P<behavior_verb>make|create|build|generate|use)\b"
            r"(?P<behavior_object>.*?)\s+(?:in|inside|within|from)\s+"
            r"(?P<container>@?[A-Za-z_][A-Za-z0-9_.]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)[?.!]*$",
            source,
            flags=re.IGNORECASE,
        )
        if guidance_match:
            match = guidance_match
    if not match:
        return None

    raw_container = match.group("container").strip(" ,").lstrip("@")
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
