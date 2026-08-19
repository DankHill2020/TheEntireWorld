from __future__ import annotations

import os
from pathlib import Path

from tech_connector.services import tool_discovery_service


def _names(path: Path) -> dict[str, dict]:
    return {
        str(symbol.get("name") or ""): symbol
        for symbol in tool_discovery_service.extract_symbols_from_file(path)
    }


def test_star_facade_indexes_public_implementation_symbols(tmp_path: Path) -> None:
    implementation = tmp_path / "implementation.py"
    implementation.write_text(
        "def public_tool(value):\n    return value\n\n"
        "def _private_helper():\n    return None\n",
        encoding="utf-8",
    )
    facade = tmp_path / "facade.py"
    facade.write_text("from implementation import *\n", encoding="utf-8")

    symbols = _names(facade)

    assert "public_tool" in symbols
    assert "_private_helper" not in symbols
    assert symbols["public_tool"]["file_path"] == str(facade.resolve())
    assert symbols["public_tool"]["implementation_file_path"] == str(implementation.resolve())


def test_explicit_all_preserves_private_compatibility_exports(tmp_path: Path) -> None:
    implementation = tmp_path / "implementation.py"
    implementation.write_text(
        "__all__ = ['_compatibility_helper']\n\n"
        "def _compatibility_helper():\n    return 'ok'\n\n"
        "def excluded_public_tool():\n    return 'hidden'\n",
        encoding="utf-8",
    )
    facade = tmp_path / "facade.py"
    facade.write_text("from implementation import *\n", encoding="utf-8")

    symbols = _names(facade)
    assert "_compatibility_helper" in symbols
    assert "excluded_public_tool" not in symbols


def test_facade_cache_invalidates_when_implementation_changes(tmp_path: Path) -> None:
    implementation = tmp_path / "implementation.py"
    implementation.write_text("def first_tool():\n    return 1\n", encoding="utf-8")
    facade = tmp_path / "facade.py"
    facade.write_text("from implementation import *\n", encoding="utf-8")
    assert "first_tool" in _names(facade)

    previous_mtime = implementation.stat().st_mtime
    implementation.write_text("def second_tool():\n    return 2\n", encoding="utf-8")
    os.utime(implementation, (previous_mtime + 2.0, previous_mtime + 2.0))

    symbols = _names(facade)
    assert "second_tool" in symbols
    assert "first_tool" not in symbols
