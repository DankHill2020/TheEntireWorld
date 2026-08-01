"""Prompt text normalization helpers."""

from __future__ import annotations

import re


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
        r"\bcreat\b": "create",
        r"\bfiels\b": "files",
        r"\bfunciton\b": "function",
        r"\bfuncton\b": "function",
        r"\btaht\b": "that",
        r"\bcahnge\b": "change",
        r"\bcrete\b": "create",
    }
    for pattern, replacement in typo_map.items():
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    return value.strip()
