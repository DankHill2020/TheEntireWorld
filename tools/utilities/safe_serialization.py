"""Safe parsing helpers for values persisted by DCC scene properties."""

from __future__ import annotations

import ast
from copy import deepcopy
from typing import Any


def parse_literal_collection(
    value: Any,
    expected_type: type | tuple[type, ...],
    default: Any,
) -> Any:

    """
        Parses a Python literal and validates its collection type.

    :param value: serialized literal or already decoded value
    :param expected_type: allowed result type or types
    :param default: fallback returned for invalid content
    :return: validated decoded collection or fallback
    """
    if value is None or value == "":
        return deepcopy(default)
    try:
        decoded = ast.literal_eval(value) if isinstance(value, str) else value
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return deepcopy(default)
    if not isinstance(decoded, expected_type):
        return deepcopy(default)
    return decoded
