from __future__ import annotations

"""Phrase-aware target entity extraction for project and DCC requests.

Explicit filenames, paths, symbols, quoted names, and recently resolved targets
must remain intact instead of being flattened into generic search tokens.
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
