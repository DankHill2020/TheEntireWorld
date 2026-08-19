"""Shared semantic classification for project-edit requirements."""

from __future__ import annotations

import re


def is_project_edit_quality_requirement(text: str) -> bool:
    """Return whether a clause constrains quality rather than runtime behavior.

    :param text: Atomic requirement text.
    :return: True when the clause is a quality or scope constraint.
    """

    return bool(re.search(
        r"\b(?:use only|standard library|no external|complete public docstrings?|"
        r"detailed public docstrings?|type hints?|production readiness)\b"
        r"|^\s*(?:modify|edit|change|touch)\s+only\b"
        r"|^\s*do not touch (?:files?|paths?)\b"
        r"|^\s*(?:keep|preserve) (?:the )?(?:existing )?public names?\b"
        r"|^\s*keep (?:the )?(?:public )?"
        r"(?:function|method|class|callable) name\b",
        str(text or ""),
        flags=re.IGNORECASE,
    ))

