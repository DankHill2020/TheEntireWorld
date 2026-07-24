from __future__ import annotations

"""Shared deterministic ranking for tool/function search surfaces."""

from typing import Any
import re


def tool_search_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower().replace("_", " "))


def contains_ordered_terms(tokens: list[str], terms: list[str]) -> bool:
    if not terms:
        return True
    pos = 0
    for token in tokens:
        if token == terms[pos]:
            pos += 1
            if pos == len(terms):
                return True
    return False


def contains_contiguous_terms(tokens: list[str], terms: list[str]) -> bool:
    if not terms or len(terms) > len(tokens):
        return False
    width = len(terms)
    return any(tokens[idx : idx + width] == terms for idx in range(0, len(tokens) - width + 1))


def tool_query_match_score(row: dict[str, Any], terms: list[str]) -> int:
    """Lower score is better.

    Function/name matches beat label/path/docstring matches. This keeps a query
    like "create rig mapping" on create_rig_mapping instead of a nearby rig
    helper whose path or docstring happens to include "mapping".
    """

    if not terms:
        return 20
    name = str(row.get("name") or "").lower()
    label = str(row.get("label_lower") or row.get("label") or "").lower()
    path = str(row.get("path_lower") or row.get("path") or "").lower()
    detail = str(row.get("detail_lower") or row.get("detail") or "").lower()
    query_text = " ".join(terms)
    query_snake = "_".join(terms)
    name_tokens = tool_search_tokens(name)
    label_tokens = tool_search_tokens(label)

    if name == query_snake or name == query_text or name_tokens == terms:
        return 0
    if contains_contiguous_terms(name_tokens, terms):
        return 1
    if name.startswith(query_snake) or name.startswith(query_text):
        return 2
    if all(term in name_tokens for term in terms) and contains_ordered_terms(name_tokens, terms):
        return 3
    if all(term in name_tokens for term in terms):
        return 4
    if query_snake in name or query_text in label:
        return 5
    if all(term in label_tokens for term in terms) and contains_ordered_terms(label_tokens, terms):
        return 6
    if all(term in label_tokens for term in terms):
        return 7
    broad_tokens = tool_search_tokens(" ".join((label, path, detail)))
    if all(term in broad_tokens for term in terms) and contains_ordered_terms(broad_tokens, terms):
        return 8
    return 9


def tool_query_rank(row: dict[str, Any], terms: list[str], *, priority_desc: bool = False) -> tuple[Any, ...]:
    score = tool_query_match_score(row, terms)
    priority = int(row.get("priority") or 0)
    priority_key = -priority if priority_desc else priority
    label = str(row.get("label_lower") or row.get("label") or row.get("name") or "").lower()
    path = str(row.get("path_lower") or row.get("path") or row.get("detail") or "").lower()
    return (score, priority_key, label, path)
