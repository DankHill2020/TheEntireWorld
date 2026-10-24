"""Run a small, identical prompt set through the approved focused-edit lane.

This smoke benchmark does not claim full workflow or DCC-host coverage.  Explicit
cloud selections are refused when unauthenticated instead of measured as local.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from tech_connector.services.llm_router_service import resolve_llm_provider_route
from tech_connector.services.project_edit_tool_loop_service import try_focused_edit
from tech_connector.services.settings_service import load_settings


CASES = (
    (
        "blender_selection", "blender_tools/selection.py",
        "def selected_mesh_names(objects):\n    return [obj.name for obj in objects]\n",
        "In blender_tools/selection.py, fix selected_mesh_names so it returns names "
        "only for selected objects whose type is MESH, preserving input order. "
        "Add focused unittest proof in blender_tools/test_selection.py with fake objects.",
    ),
    (
        "maya_rig_naming", "maya_tools/rig_names.py",
        'def invalid_joint_names(names):\n    return [name for name in names if name.startswith("jnt_")]\n',
        "In maya_tools/rig_names.py, fix invalid_joint_names so it returns only "
        "joint names that do not start with jnt_. Add focused unittest proof in "
        "maya_tools/test_rig_names.py.",
    ),
    (
        "unreal_asset_paths", "unreal_tools/asset_paths.py",
        'def normalize_game_path(path):\n    return path.replace("\\\\", "/")\n',
        "In unreal_tools/asset_paths.py, fix normalize_game_path so it normalizes "
        "backslashes and ensures exactly one /Game prefix for relative content "
        "paths. Add focused unittest proof in unreal_tools/test_asset_paths.py.",
    ),
    (
        "motionbuilder_plot_period", "motionbuilder_tools/plot_time.py",
        "def plot_period_seconds(fps):\n    return 1.0 / 24.0\n",
        "In motionbuilder_tools/plot_time.py, fix plot_period_seconds so a "
        "MotionBuilder plot at the requested finite positive fps uses exactly "
        "1/fps seconds per frame; reject zero, negative, bool, and non-finite "
        "rates with ValueError. Add focused unittest proof in "
        "motionbuilder_tools/test_plot_time.py.",
    ),
    (
        "painter_texture_sets", "substance_painter_tools/texture_sets.py",
        "def enabled_texture_set_names(texture_sets):\n"
        "    return [item.name for item in texture_sets]\n",
        "In substance_painter_tools/texture_sets.py, fix "
        "enabled_texture_set_names so it returns each enabled texture set's "
        "name once, preserving first-seen order; disabled sets must not be "
        "exported. Add focused unittest proof with fake texture sets in "
        "substance_painter_tools/test_texture_sets.py.",
    ),
    (
        "tech_connector_stage_ref", "tech_connector/services/stage_ref.py",
        "def parse_stage_ref(value):\n    return tuple(value.split(':'))\n",
        "In tech_connector/services/stage_ref.py, fix parse_stage_ref to trim "
        "a 'host:operation' reference and return exactly (host, operation). "
        "Only blender, maya, unreal, motionbuilder, and substance_painter are "
        "valid hosts; reject empty or extra segments and unknown hosts with "
        "ValueError. Add focused unittest proof in "
        "tech_connector/services/test_stage_ref.py.",
    ),
)


_HIDDEN_CHECKS = {
    "blender_selection": """from blender_tools.selection import selected_mesh_names
class FakeObject:
    def __init__(self, name, kind, selected):
        self.name = name
        self.type = kind
        self.select = selected
        self.selected = selected
    def select_get(self):
        return self.select
objects = [
    FakeObject('Mesh_A', 'MESH', False),
    FakeObject('Lamp', 'LIGHT', True),
    FakeObject('Mesh_B', 'MESH', True),
    FakeObject('Mesh_C', 'MESH', False),
    FakeObject('Mesh_D', 'MESH', True),
]
assert selected_mesh_names(objects) == ['Mesh_B', 'Mesh_D']
assert selected_mesh_names([]) == []
""",
    "maya_rig_naming": """from maya_tools.rig_names import invalid_joint_names
assert invalid_joint_names(['jnt_arm', 'root', 'spine', 'jnt_leg']) == ['root', 'spine']
assert invalid_joint_names(['jnt_root']) == []
assert invalid_joint_names([]) == []
""",
    "unreal_asset_paths": """from unreal_tools.asset_paths import normalize_game_path
assert normalize_game_path('Props\\\\Crate') == '/Game/Props/Crate'
assert normalize_game_path('Props/Crate') == '/Game/Props/Crate'
assert normalize_game_path('/Game/Props/Crate') == '/Game/Props/Crate'
""",
    "motionbuilder_plot_period": """from motionbuilder_tools.plot_time import plot_period_seconds
import math
assert math.isclose(plot_period_seconds(60), 1.0 / 60.0, rel_tol=1e-12)
assert math.isclose(plot_period_seconds(24), 1.0 / 24.0, rel_tol=1e-12)
for bad in (0, -12, True, float('inf'), float('nan')):
    try:
        plot_period_seconds(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid frame rate accepted')
""",
    "painter_texture_sets": """from substance_painter_tools.texture_sets import enabled_texture_set_names
class FakeSet:
    def __init__(self, name, enabled):
        self.name = name
        self.enabled = enabled
sets = [FakeSet('Body', True), FakeSet('FX', False), FakeSet('Body', True), FakeSet('Head', True)]
assert enabled_texture_set_names(sets) == ['Body', 'Head']
assert enabled_texture_set_names([]) == []
""",
    "tech_connector_stage_ref": """from tech_connector.services.stage_ref import parse_stage_ref
assert parse_stage_ref(' maya : animation.export ') == ('maya', 'animation.export')
assert parse_stage_ref('substance_painter:textures.export') == ('substance_painter', 'textures.export')
for bad in ('', 'maya:', ':export', 'unknown:export', 'maya:a:b'):
    try:
        parse_stage_ref(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid stage reference accepted')
""",
}


def _hidden_behavior_result(
    name: str,
    root: Path,
    source: str,
    relative: str,
    *,
    include_stderr: bool = False,
) -> dict[str, object]:
    """Run independent behavior checks after an approved disposable preview."""

    owner = root / relative
    owner.write_text(source, encoding="utf-8")
    script = (
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        + _HIDDEN_CHECKS[name]
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", script, str(root)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"passed": False, "error": "timeout"}
    stderr = completed.stderr or ""
    error = (
        ""
        if completed.returncode == 0
        else "assertion_failed" if "AssertionError" in stderr else "runtime_error"
    )
    result: dict[str, object] = {
        "passed": completed.returncode == 0,
        "error": error,
    }
    if include_stderr:
        result["stderr"] = stderr[:2000]
    return result


def run(model: str, case_filter: str = "") -> list[dict[str, object]]:
    settings = dict(load_settings())
    explicit_cloud = model.startswith(("openai:", "anthropic:", "gemini:", "x:"))
    if explicit_cloud:
        settings["model_source_mode"] = "auto_with_local_fallback"
    route = resolve_llm_provider_route(model, settings)
    if explicit_cloud and not route.cloud_active:
        return [{"model": model, "status": "provider_unavailable", "cloud_active": False}]
    results = []
    for name, relative, source, prompt in CASES:
        if case_filter and name != case_filter:
            continue
        with tempfile.TemporaryDirectory(
            prefix="tc_focus_smoke_", dir=Path(__file__).resolve().parents[1] / "results"
        ) as directory:
            root = Path(directory)
            owner = root / relative
            owner.parent.mkdir(parents=True, exist_ok=True)
            owner.write_text(source, encoding="utf-8")
            test_relative = (owner.parent / ("test_" + owner.name)).relative_to(root).as_posix()
            workflow = SimpleNamespace(
                dry_run=True,
                approved_plan_id="benchmark-approved",
                approval_id="benchmark-approved",
                root=root,
                manifest=[{"path": relative, "is_test": False}, {"path": test_relative, "is_test": True}],
                user_prompt=prompt,
                selected_model=model,
                timeout=75 if explicit_cloud else 40,
                timings=[],
                implementation_plan={},
                status_callback=None,
                settings={"experimental_focused_tool_loop": True},
                focused_tool_loop_diagnostics=[],
                focused_tool_loop_debug_traceback=True,
                focused_tool_loop_debug_schema=True,
            )
            started = time.perf_counter()
            result = try_focused_edit(workflow)
            hidden: dict[str, object] | None = None
            approved_source = ""
            if result and result.ok and result.preview:
                approved_source = next(
                    (
                        str(change.get("after") or "")
                        for change in result.preview.changes
                        if (
                            (root / Path(str(change.get("path") or ""))).resolve()
                            == owner.resolve()
                        )
                    ),
                    "",
                )
                if approved_source:
                    hidden = _hidden_behavior_result(
                        name, root, approved_source, relative,
                        include_stderr=True,
                    )
            results.append({
                "case": name,
                "model": model,
                "provider": route.provider,
                "cloud_active": route.cloud_active,
                "seconds": round(time.perf_counter() - started, 3),
                "preview_ok": bool(result and result.ok),
                "eligible": bool(result and result.ok and hidden and hidden["passed"]),
                "model_calls": getattr(workflow, "focused_tool_loop_model_calls", 0),
                "focused_tests_passed": bool(result and any(
                    check.get("check") == "disposable_unittest" and check.get("ok")
                    for check in result.preview.validation
                )),
                "hidden_behavior": hidden,
                "failed_source": approved_source[:4000] if hidden and not hidden["passed"] else "",
                "diagnostics": workflow.focused_tool_loop_diagnostics,
            })
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("--case", choices=[item[0] for item in CASES], default="")
    arguments = parser.parse_args()
    for row in run(arguments.model, arguments.case):
        print(json.dumps(row), flush=True)
