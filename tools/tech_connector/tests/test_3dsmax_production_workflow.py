from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from max_tools import operations
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.dcc_production_workflow_service import PRODUCTION_WORKFLOWS


class _Point3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)


def test_3dsmax_nested_transform_key_and_modifier_inspector(monkeypatch, tmp_path) -> None:
    modifier = SimpleNamespace(angle=20.0)
    material = SimpleNamespace(name="TC_WorkflowMaterial")
    node = SimpleNamespace(
        name="TC_WorkflowBox",
        position=_Point3(0, 0, 0),
        scale=_Point3(1, 1, 1),
        modifiers=[modifier],
        material=material,
    )
    runtime = SimpleNamespace(
        getNodeByName=lambda name: node if name == node.name else None,
        Point3=_Point3,
        classOf=lambda value: "Bend" if value is modifier else "Box",
    )
    pymxs = SimpleNamespace(
        runtime=runtime,
        animate=lambda _value: nullcontext(),
        attime=lambda _frame: nullcontext(),
    )
    monkeypatch.setitem(__import__("sys").modules, "pymxs", pymxs)
    artifact = tmp_path / "max_asset.fbx"
    artifact.write_bytes(b"fbx")

    operations.animation_set_key(node.name, "position.x", 24, 25.0)
    result = operations.workflow_inspect_modifier_asset(
        node.name,
        "Bend",
        material.name,
        "position.x",
        24,
        25.0,
        str(artifact),
        {"angle": 20.0},
    )

    assert node.position.x == 25.0
    assert result["parity_checks"] == {
        "editable topology and modifier stack": True,
        "modifier parameters": True,
        "material assignment": True,
        "animation keys": True,
    }


def test_3dsmax_workflow_uses_specific_readback_instead_of_scene_list() -> None:
    steps = PRODUCTION_WORKFLOWS["3dsmax.modifier_asset"].steps

    assert steps[-1].operation == "workflow.inspect_modifier_asset"
    assert steps[-1].readback
    assert dcc_operation_registry("3dsmax")["workflow.inspect_modifier_asset"].function.startswith(
        "max_tools.operations."
    )
