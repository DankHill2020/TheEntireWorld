"""Tests for first-party package audit boundaries."""

from __future__ import annotations

from pathlib import Path

from reasoning_runtime.project_analysis import audit_python_package_layout


def test_package_audit_ignores_generated_native_dependency_tree(
    tmp_path: Path,
) -> None:
    """Do not parse CMake-fetched third-party sources as first-party Python."""

    package = tmp_path / "tech_connector"
    package.mkdir()
    (package / "__init__.py").write_text('"""Fixture package."""\n', encoding="utf-8")
    generated = (
        package
        / "game_engine"
        / "native"
        / ".tech_connector"
        / "cmake"
        / "Release"
        / "_deps"
        / "vendor"
    )
    generated.mkdir(parents=True)
    (generated / "python2_only.py").write_text(
        'print "legacy vendor script"\n',
        encoding="utf-8",
    )

    audit = audit_python_package_layout(tmp_path)

    assert audit["parse_errors"] == []
    assert audit["module_count"] == 1
