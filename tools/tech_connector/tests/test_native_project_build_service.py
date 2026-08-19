from pathlib import Path

import pytest

from tech_connector.services.native_project_build_service import (
    create_native_build_plan,
    find_cmake_project,
    parse_native_build_diagnostics,
    source_location_from_output_line,
)


def test_cmake_project_discovery_and_incremental_plan(tmp_path: Path) -> None:
    root = tmp_path / "project"
    source = root / "src" / "feature.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    (root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8")

    assert find_cmake_project(source) == root
    plan = create_native_build_plan(source, "release")
    assert plan.project_root == str(root)
    assert plan.configuration == "Release"
    assert plan.action == "build"
    assert plan.source_file == str(source)
    assert Path(plan.build_directory) == root / ".tech_connector" / "cmake" / "Release"
    assert plan.configure_command[:2] == ("cmake", "-S")
    assert plan.build_command[:2] == ("cmake", "--build")
    assert plan.test_command[0] == "ctest"

    analysis = create_native_build_plan(source, "debug", "analyze")
    assert analysis.analysis_command[0] == "clang-tidy"


def test_plan_rejects_unknown_configuration(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text("project(test)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported build configuration"):
        create_native_build_plan(tmp_path, "ShippingButUnspecified")


def test_msvc_and_clang_diagnostics_are_normalized(tmp_path: Path) -> None:
    cpp = tmp_path / "bad.cpp"
    output = "\n".join(
        [
            f"{cpp}(12,7): error C2065: 'value': undeclared identifier",
            f"{cpp}:18:3: warning: unused variable 'other'",
        ]
    )
    diagnostics = parse_native_build_diagnostics(output)
    assert [(item.line, item.column, item.severity) for item in diagnostics] == [
        (12, 7, "error"), (18, 3, "warning")
    ]
    assert diagnostics[0].code == "C2065"
    assert diagnostics[1].code == "CXX"


def test_output_lines_expose_clickable_source_locations() -> None:
    assert source_location_from_output_line(r"C:\work\main.cpp(9,4): error C2143: syntax error") == (
        r"C:\work\main.cpp", 9, 4
    )
    assert source_location_from_output_line('  File "C:\\work\\game.py", line 27, in update') == (
        r"C:\work\game.py", 27, 1
    )
