from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService, PrefabService
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.ui.game_engine.asset_editor_workspace import (
    DedicatedAssetEditor, editor_pages_for_asset,
)
from tech_connector.ui.game_engine.asset_specialized_editors import (
    AnimationControllerDebuggerWidget, AnimationControllerParametersEditorWidget,
    AnimationControllerTransitionsEditorWidget, AnimationStateMachineEditorWidget,
    EffectScalabilityEditorWidget, EffectTimelineEditorWidget, MaterialParameterEditorWidget,
    MeshGeometryEditorWidget, MeshMaterialSlotsEditorWidget,
    InputActionsEditorWidget, InputContextsEditorWidget, InputLiveDebugWidget, InputMapEditorWidget,
    PhysicsPhysicalAnimationEditorWidget, PhysicsSolverProfilesEditorWidget,
    TextureChannelEditorWidget, TextureMipEditorWidget, TexturePlatformEditorWidget,
    AnimationClipTimelineEditorWidget, AnimationClipCurvesEditorWidget, AnimationClipEventsEditorWidget,
    AnimationRootMotionEditorWidget, AnimationCompressionEditorWidget,
    SkeletonHierarchyEditorWidget, SkeletonSocketsEditorWidget, SkeletonRetargetPoseEditorWidget,
    SkinDeformerStackEditorWidget, SkinTransferEditorWidget, SkinExportEditorWidget,
)
from tech_connector.game_engine.assets import read_asset_metadata


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_editor_exposes_specialized_pages_and_saves_shared_properties(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Hero")
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(material.asset_id)
    assert editor.pages.count() == len(editor_pages_for_asset("tc.material"))
    assert editor.pages.tabText(0) == "Preview"
    assert editor.save_button.isEnabled()

    roughness = next(
        editor.properties.topLevelItem(index)
        for index in range(editor.properties.topLevelItemCount())
        if editor.properties.topLevelItem(index).data(0, Qt.UserRole) == "roughness"
    )
    roughness.setText(1, "0.25")
    assert editor.save()

    payload = json.loads(database.asset(material.asset_id).source_path.read_text(encoding="utf-8"))
    assert payload["properties"]["roughness"] == 0.25


def test_editor_preview_signal_and_import_settings_are_truthful(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "tone.wav"
    source.write_bytes(b"RIFF-test")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    audio = operations.import_asset(source)
    editor = DedicatedAssetEditor(project, database)
    previews = []
    editor.previewRequested.connect(lambda path, type_id, asset_id: previews.append((path, type_id, asset_id)))

    assert editor.open_asset(audio.asset_id)
    assert editor.pages.tabText(0) == "Waveform"
    assert editor._mode == "import"
    assert editor.reimport_button.isEnabled()
    editor.preview()

    assert previews[0][1:] == ("tc.audio_clip", audio.asset_id)


def test_cloth_editor_is_direct_setup_not_a_required_node_graph(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    cloth = operations.create_asset("tc.cloth", "Cape")
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(cloth.asset_id)
    assert editor.pages.tabText(0) == "Setup & Paint"
    assert all("Graph" not in editor.pages.tabText(index) for index in range(editor.pages.count()))


def test_prefab_editor_uses_prefab_mode_and_compiles_runtime_artifact(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    prefab = PrefabService(project, database).create_from_entities(
        "InteractiveDoor", [{"name": "Door", "open": False}],
    )
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(prefab.asset_id)
    assert editor.pages.tabText(1) == "Hierarchy"
    assert any(key == "__prefab__" for key, _widget in editor._specialized_widgets)
    assert editor.compile()
    assert database.derived(prefab.asset_id, "prefab_runtime:desktop:high") is not None


def test_high_value_asset_editors_use_saveable_specialized_surfaces(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Deep")
    animation = operations.create_asset("tc.animation_controller", "AC_Hero")
    effect = operations.create_asset("tc.effect_system", "FX_Impact")
    mesh_source = tmp_path / "hero.obj"
    mesh_source.write_text("o Hero\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    mesh = operations.import_asset(mesh_source)
    editor = DedicatedAssetEditor(project, database)

    expected = {
        material.asset_id: {MaterialParameterEditorWidget},
        animation.asset_id: {AnimationControllerDebuggerWidget, AnimationControllerParametersEditorWidget, AnimationControllerTransitionsEditorWidget, AnimationStateMachineEditorWidget},
        effect.asset_id: {EffectTimelineEditorWidget, EffectScalabilityEditorWidget},
        mesh.asset_id: {MeshGeometryEditorWidget, MeshMaterialSlotsEditorWidget},
    }
    for asset_id, widget_types in expected.items():
        assert editor.open_asset(asset_id)
        present = {type(widget) for _key, widget in editor._specialized_widgets}
        assert widget_types <= present

    assert editor.open_asset(material.asset_id)
    parameters = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, MaterialParameterEditorWidget))
    parameters._append("Wetness", "float", 0.35, "Surface", False)
    assert editor.save(compile_after=False)
    payload = json.loads(database.asset(material.asset_id).source_path.read_text(encoding="utf-8"))
    assert payload["properties"]["parameters"]["Wetness"]["default"] == 0.35


def test_specialized_editor_validation_blocks_invalid_save(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    source = tmp_path / "bad.obj"
    source.write_text("o Bad\nv 0 0 0\n", encoding="utf-8")
    mesh = operations.import_asset(source)
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(mesh.asset_id)
    materials = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, MeshMaterialSlotsEditorWidget))
    materials._append("Body", "", 0, True)
    materials.table.item(0, 2).setText("not-an-index")

    assert not editor.save(compile_after=False)
    assert "whole-number section index" in editor.diagnostics.text()


def test_texture_editor_routes_channels_mips_and_platform_compression(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "surface.png"
    source.write_bytes(b"not-a-decoded-image-but-valid-import-source")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    texture = AssetOperationsService(project, database).import_asset(source)
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(texture.asset_id)
    present = {type(widget) for _key, widget in editor._specialized_widgets}
    assert {TextureChannelEditorWidget, TextureMipEditorWidget, TexturePlatformEditorWidget} <= present
    channels = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, TextureChannelEditorWidget))
    platforms = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, TexturePlatformEditorWidget))
    channels.flip_green.setChecked(True)
    platforms._append("android", "astc", 2048, "high")
    assert editor.save(compile_after=False)

    settings = read_asset_metadata(database.asset(texture.asset_id).source_path)["importer_settings"]
    assert settings["channels"]["flip_green"] is True
    assert settings["platform_overrides"]["android"]["format"] == "astc"


def test_input_editor_separates_actions_contexts_bindings_and_live_debug(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    input_map = AssetOperationsService(project, database).create_asset(
        "tc.input_map", "IM_Player", properties={
            "contexts": [{"id": "Gameplay", "priority": 0, "enabled": True}],
            "actions": {"Jump": {"value_type": "button", "trigger": "pressed", "bindings": [{"context": "Gameplay", "device": "keyboard_mouse", "key": "Space", "modifiers": [], "scale": 1.0, "consume": True}]}},
        },
    )
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(input_map.asset_id)
    present = {type(widget) for _key, widget in editor._specialized_widgets}
    assert {InputActionsEditorWidget, InputContextsEditorWidget, InputMapEditorWidget, InputLiveDebugWidget} <= present
    actions = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, InputActionsEditorWidget))
    contexts = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, InputContextsEditorWidget))
    actions.table.item(0, 0).setText("Leap")
    actions.table.item(0, 3).setText("0.75")
    contexts.table.item(0, 1).setText("10")
    assert editor.save(compile_after=False)

    payload = json.loads(database.asset(input_map.asset_id).source_path.read_text(encoding="utf-8"))["properties"]
    assert "Jump" not in payload["actions"]
    assert payload["actions"]["Leap"]["threshold"] == 0.75
    assert payload["actions"]["Leap"]["bindings"][0]["key"] == "Space"
    assert payload["contexts"][0]["priority"] == 10


def test_physics_asset_exposes_physical_animation_and_solver_profiles(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    physics = AssetOperationsService(project, database).create_asset(
        "tc.physics_asset", "PHYS_Hero", properties={
            "skeleton_id": "skeleton-demo",
            "bodies": [{"id": "Pelvis", "bone": "pelvis", "collider": {"shape": "capsule"}, "rigid_body": {"mass": 10.0}}],
            "constraints": [],
        },
    )
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(physics.asset_id)
    present = {type(widget) for _key, widget in editor._specialized_widgets}
    assert {PhysicsPhysicalAnimationEditorWidget, PhysicsSolverProfilesEditorWidget} <= present
    animation = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, PhysicsPhysicalAnimationEditorWidget))
    profiles = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, PhysicsSolverProfilesEditorWidget))
    animation.blend.setValue(0.4)
    profiles._append("HitReaction", 0.8, 1.5, 1.2)
    assert editor.save(compile_after=False)

    payload = json.loads(database.asset(physics.asset_id).source_path.read_text(encoding="utf-8"))["properties"]
    assert payload["physical_animation"]["blend"] == 0.4
    assert payload["profiles"]["HitReaction"]["strength_scale"] == 1.5


def test_input_map_python_api_validates_before_persisting(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    api = TCEditorAPI(project)
    receipt = api.create_asset("tc.input_map", "IM_API", properties={
        "contexts": [{"id": "Gameplay", "priority": 0, "enabled": True}],
        "actions": {"Jump": {"value_type": "button", "bindings": [{"context": "Gameplay", "device": "keyboard_mouse", "key": "Space"}]}},
    })

    updated = api.update_input_map(receipt.asset_id, {"contexts": [{"id": "Gameplay", "priority": 20, "enabled": True}]})
    assert updated["contexts"][0]["priority"] == 20
    assert api.input_map_audit(receipt.asset_id)["valid"]
    with pytest.raises(ValueError, match="missing context"):
        api.update_input_map(receipt.asset_id, {"contexts": []})
    assert api.properties(receipt.asset_id)["contexts"][0]["priority"] == 20


def test_animation_clip_has_complete_authoring_pages_and_cooks(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    api = TCEditorAPI(project)
    clip = api.animation.create_clip("Run", skeleton_id="skeleton-demo", duration_seconds=1.25, sample_rate=30.0)
    editor = DedicatedAssetEditor(project, api.database)

    assert editor.open_asset(clip.asset_id)
    present = {type(widget) for _key, widget in editor._specialized_widgets}
    assert {
        AnimationClipTimelineEditorWidget, AnimationClipCurvesEditorWidget,
        AnimationClipEventsEditorWidget, AnimationRootMotionEditorWidget,
        AnimationCompressionEditorWidget,
    } <= present
    events = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, AnimationClipEventsEditorWidget))
    root = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, AnimationRootMotionEditorWidget))
    compression = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, AnimationCompressionEditorWidget))
    events._append_event(0.3, "Footstep", "audio", {"surface": "auto"})
    events._append_marker(0.3, "LeftFoot")
    root.mode.setCurrentText("extract")
    compression.preset.setCurrentText("runtime")
    assert editor.save(compile_after=False)
    values = api.animation.properties(clip.asset_id)
    assert values["events"][0]["name"] == "Footstep"
    assert values["root_motion"]["mode"] == "extract"
    assert api.animation.cook(clip.asset_id).path.is_file()


def test_skeleton_editor_validates_hierarchy_sockets_retarget_and_cooks(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    api = TCEditorAPI(project)
    skeleton = api.create_skeleton("SK_Hero", bones=[
            {"name": "root", "parent": "", "reference_pose": {}, "role": "root", "importance": 1.0},
            {"name": "hand_r", "parent": "root", "reference_pose": {}, "role": "hand", "importance": 0.8},
        ], preserve_bones=["root"])
    editor = DedicatedAssetEditor(project, api.database)

    assert editor.open_asset(skeleton.asset_id)
    present = {type(widget) for _key, widget in editor._specialized_widgets}
    assert {SkeletonHierarchyEditorWidget, SkeletonSocketsEditorWidget, SkeletonRetargetPoseEditorWidget} <= present
    sockets = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, SkeletonSocketsEditorWidget))
    pose = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, SkeletonRetargetPoseEditorWidget))
    sockets._append("Weapon", "hand_r", (0, 0, 0), (0, 90, 0), (1, 1, 1))
    pose._append("hand_r", (0, 0, 0), (0, 0, 5))
    assert editor.save(compile_after=False)
    assert api.validate_character_asset(skeleton.asset_id) == []
    assert api.cook_character_asset(skeleton.asset_id).path.suffix == ".tcskeletonbin"

    assert editor.open_asset(skeleton.asset_id)
    sockets = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, SkeletonSocketsEditorWidget))
    sockets.table.item(0, 1).setText("missing_bone")
    assert not editor.save(compile_after=False)
    assert "missing bone" in editor.diagnostics.text().casefold()
    with pytest.raises(ValueError, match="cycle"):
        api.update_character_asset(skeleton.asset_id, {"bones": [
            {"name": "root", "parent": "hand_r"}, {"name": "hand_r", "parent": "root"},
        ]})
    assert api.properties(skeleton.asset_id)["bones"][0]["parent"] == ""


def test_skin_binding_deformer_transfer_and_export_persist_and_cook(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    api = TCEditorAPI(project)
    skin = api.create_asset("tc.skin_binding", "SKIN_Hero", properties={
        "mesh_id": "mesh-demo", "skeleton_id": "skeleton-demo",
        "influences": [{"name": "root"}],
        "vertex_weights": [{"vertex_index": 0, "weights": {"root": 1.0}}],
        "topology": {"vertex_count": 1, "fingerprint": "demo"},
    })
    editor = DedicatedAssetEditor(project, api.database)

    assert editor.open_asset(skin.asset_id)
    present = {type(widget) for _key, widget in editor._specialized_widgets}
    assert {SkinDeformerStackEditorWidget, SkinTransferEditorWidget, SkinExportEditorWidget} <= present
    deformers = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, SkinDeformerStackEditorWidget))
    transfer = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, SkinTransferEditorWidget))
    export = next(widget for _key, widget in editor._specialized_widgets if isinstance(widget, SkinExportEditorWidget))
    deformers._append("Correctives", "pose_space", True, {"driver": "shoulder"})
    transfer.mode.setCurrentText("closest_point")
    export.max_influences.setValue(8)
    assert editor.save(compile_after=False)
    values = api.properties(skin.asset_id)
    assert values["deformers"][0]["type"] == "pose_space"
    assert values["transfer"]["mode"] == "closest_point"
    assert values["export"]["max_influences"] == 8
    assert api.cook_character_asset(skin.asset_id).path.is_file()
