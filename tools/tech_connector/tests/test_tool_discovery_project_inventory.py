from pathlib import Path

from tech_connector.services.tool_discovery_service import list_internal_functions


def test_unbounded_project_inventory_scans_all_files(tmp_path: Path):
    for index in range(4):
        (tmp_path / f"tool_{index}.py").write_text(
            f"def tool_{index}():\n    return {index}\n",
            encoding="utf-8",
        )

    bounded = list_internal_functions(
        [str(tmp_path)],
        max_files=2,
        time_budget_seconds=None,
    )
    complete = list_internal_functions(
        [str(tmp_path)],
        max_files=None,
        time_budget_seconds=None,
    )

    assert len(bounded) == 2
    assert {symbol["name"] for symbol in bounded} <= {
        "tool_0",
        "tool_1",
        "tool_2",
        "tool_3",
    }
    assert {symbol["name"] for symbol in complete} == {
        "tool_0",
        "tool_1",
        "tool_2",
        "tool_3",
    }


def test_overlapping_roots_do_not_duplicate_symbols(tmp_path: Path):
    package = tmp_path / "maya_tools"
    package.mkdir()
    source = package / "rig.py"
    source.write_text("def build_rig():\n    return True\n", encoding="utf-8")

    symbols = list_internal_functions(
        [str(tmp_path), str(package)],
        max_files=None,
        time_budget_seconds=None,
    )

    assert [symbol["name"] for symbol in symbols] == ["build_rig"]
