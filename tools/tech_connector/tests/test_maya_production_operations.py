from __future__ import annotations

import re
from types import SimpleNamespace

from maya_tools.Animation.anim_export.bridge_export import export_fbx
from maya_tools.Rigging.validation_proxy import inspect_rigged_proxy
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.dcc_production_workflow_service import PRODUCTION_WORKFLOWS


def _install_fake_maya(monkeypatch, cmds, mel=None) -> None:
    mel = mel or SimpleNamespace(eval=lambda _code: None)
    maya = SimpleNamespace(cmds=cmds, mel=mel)
    monkeypatch.setitem(__import__("sys").modules, "maya", maya)
    monkeypatch.setitem(__import__("sys").modules, "maya.cmds", cmds)
    monkeypatch.setitem(__import__("sys").modules, "maya.mel", mel)


def test_maya_proxy_inspector_emits_all_named_parity(monkeypatch) -> None:
    def list_relatives(name, **kwargs):
        if kwargs.get("parent"):
            return ["TC_WorkflowCharacter_Root"]
        if kwargs.get("shapes"):
            return ["TC_WorkflowCharacter_MeshShape"]
        return []

    cmds = SimpleNamespace(
        objExists=lambda _name: True,
        listRelatives=list_relatives,
        listHistory=lambda _mesh: ["TC_WorkflowCharacter_Skin"],
        ls=lambda values, **_kwargs: list(values),
        skinCluster=lambda _cluster, **_kwargs: ["TC_WorkflowCharacter_Root", "TC_WorkflowCharacter_Tip"],
        getAttr=lambda _plug: 8,
        polyEvaluate=lambda _mesh, **_kwargs: 2,
        skinPercent=lambda *_args, **_kwargs: [0.5, 0.5],
        keyframe=lambda *_args, **_kwargs: [1.0, 24.0],
        listConnections=lambda *_args, **_kwargs: ["TC_WorkflowCharacter_MaterialSG"],
    )
    _install_fake_maya(monkeypatch, cmds)

    result = inspect_rigged_proxy("TC_WorkflowCharacter", 1, 24)

    assert result["parity_checks"] == {
        "joint hierarchy": True,
        "skin influence count and normalization": True,
        "animation frame range": True,
        "material assignments": True,
    }


def test_maya_current_session_export_requires_a_real_fbx_artifact(monkeypatch, tmp_path) -> None:
    target = tmp_path / "character.fbx"
    selected = []
    cmds = SimpleNamespace(
        pluginInfo=lambda *_args, **_kwargs: False,
        loadPlugin=lambda _name: None,
        objExists=lambda _name: True,
        select=lambda values, **_kwargs: selected.extend(values),
    )

    def mel_eval(code):
        if code.startswith("FBXExport -f"):
            path = re.search(r'FBXExport -f "([^"]+)"', code).group(1)
            __import__("pathlib").Path(path).write_bytes(b"fbx")

    _install_fake_maya(monkeypatch, cmds, SimpleNamespace(eval=mel_eval))

    result = export_fbx(
        str(target), start_frame=1, end_frame=24, nodes=["Mesh", "Root"], selected_only=True,
    )

    assert target.is_file()
    assert result["nodes"] == ["Mesh", "Root"]
    assert selected == ["Mesh", "Root"]


def test_maya_workflow_no_longer_asks_the_rig_builder_to_infer_a_missing_skeleton() -> None:
    workflow = PRODUCTION_WORKFLOWS["maya.character_asset"]
    operations = [step.operation for step in workflow.steps]

    assert operations == [
        "pipeline.create_rigged_proxy", "animation.export", "pipeline.inspect_rigged_proxy",
    ]
    assert workflow.steps[-1].readback
    registry = dcc_operation_registry("maya")
    assert registry["animation.export"].function.endswith("bridge_export.export_fbx")


def test_maya_snapshot_can_skip_material_network_traversal() -> None:
    code = MayaBridge().get_scene_snapshot_code(
        meshes_only=True,
        include_geometry=False,
        include_materials=False,
        limit=3,
    )

    compile(code, "<maya-snapshot>", "exec")
    assert "include_materials = False" in code
    assert "if include_materials:" in code
    assert '"include_materials": include_materials' in code
