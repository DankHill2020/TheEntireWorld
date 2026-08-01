"""Domain-neutral request-context model and sanitization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


_SENSITIVE_CONTEXT_KEY = re.compile(
    r"(?:^|_)(?:api_?key|access_?key|secret|token|password|credential|"
    r"authorization|cookie|private_?key)(?:$|_)",
    re.IGNORECASE,
)


def sanitize_prompt_context(value: Any) -> Any:
    """Copy prompt context while removing credentials at the boundary."""

    if isinstance(value, dict):
        return {
            str(key): sanitize_prompt_context(item)
            for key, item in value.items()
            if not _SENSITIVE_CONTEXT_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [sanitize_prompt_context(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_prompt_context(item) for item in value)
    return value


@dataclass(frozen=True)
class RequestContext:
    text: str
    active_tab: str = "Chat"
    current_file_path: str = ""
    open_file_paths: tuple[str, ...] = ()
    selection_text: str = ""
    project_roots: tuple[str, ...] = ()
    attached_images: tuple[str, ...] = ()
    model: str = ""
    index_state: str = "unknown"
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def has_selection(self) -> bool:
        return bool(self.selection_text.strip())

    @property
    def current_file_name(self) -> str:
        return Path(self.current_file_path).name if self.current_file_path else ""

    def context_label(self) -> str:
        parts = [self.active_tab or "Chat"]
        if self.current_file_name:
            parts.append(self.current_file_name)
        elif self.open_file_paths:
            parts.append(f"Open files {len(self.open_file_paths)}")
        if self.has_selection:
            parts.append(f"Selection {len(self.selection_text.splitlines())} lines")
        if self.project_roots:
            parts.append("Project")
        if self.index_state:
            parts.append(self.index_state)
        if self.model:
            parts.append(self.model.replace("ollama:", ""))
        return "Context: " + " - ".join(parts)


def explicitly_requests_open_file_context(text: str) -> bool:
    """Return True when the user is clearly asking about open/current files."""

    lower = (text or "").lower()
    return bool(
        re.search(r"\b(this|current|active|open|selected)\s+(?:file|script|module|code)\b", lower)
        or re.search(r"\b(in|from|inside)\s+(?:this|the current|the active|the open)\s+(?:file|script|module)\b", lower)
        or re.search(r"\b(open|opened)\s+files?\b", lower)
        or re.search(r"\bcurrent\s+selection\b", lower)
    )
