"""Shared bridge-output error detection helpers."""

from __future__ import annotations

import re
from typing import Any


_ERROR_RE = re.compile(
    r"Traceback \(most recent call last\):"
    r"|(?:^|\n)\w*(?:Error|Exception):"
    r"|\b(?:error|exception|failed|failure)\b",
    re.IGNORECASE,
)


def bridge_output_has_error(output: Any) -> bool:
    text = "" if output is None else str(output)
    if not text.strip():
        return False
    match = re.search(r"(?:^|\n)STDERR:\s*(.*)", text, re.DOTALL)
    if match:
        stderr_text = match.group(1).strip()
        if stderr_text:
            return True
        text = text[: match.start()]
    return bool(_ERROR_RE.search(text))
