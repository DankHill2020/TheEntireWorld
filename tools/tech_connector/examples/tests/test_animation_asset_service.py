from __future__ import annotations

import json

import pytest

from tech_connector.game_engine.assets.animation_asset_service import (
    ANIMATION_CONTROLLER_SCHEMA,
    ANIMATION_INTERCHANGE_SCHEMA,
    AnimationAssetService,
    blend_space_defaults,
    evaluate_blend_space,
    validate_animation_controller,
)
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.locomotion_service import locomotion_preset
from tech_connector.bridges.unity.unity_bridge import UnityBridge
from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge


def test_blend_space_evaluation_is_local_normalized_and_exact() -> None:
    values = blend_space_defaults(dimensions=2, samples=[
        {"id": "idle", "clip_asset_id": "idle", "position": [0, 0]},
        {"id": "walk", "clip_asset_id": "walk", "position": [3, 0]},
        {"id": "strafe", "clip_asset_id": "strafe", "position": [3, 90]},
        {"id": "far", "clip_asset_id": "far", "position": [6, 180]},
    ])
    assert evaluate_blend_space(values, x=0, y=0) == {"idle": 1.0}
    weights = evaluate_blend_space(values, x=2.5, y=25)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert len(weights) == 3
    assert "far" not in weights


def test_controller_validation_reports_bad_transitions_and_parameters() -> None:
    issues = validate_animation_controller({
        "parameters": {"speed": {"type": "float"}},
        "layers": [{"state_machine": {
            "entry_state": "idle", "states": [{"id": "idle"}],
            "transitions": [{"from": "idle", "to": "run", "conditions": [{"parameter": "missing"}]}],
        }}],
    })
    assert {item.code for item in issues} == {"invalid_transition_target", "unknown_parameter"}


def test_python_api_creates_validates_evaluates_and_cooks_animation_assets(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    idle = api.create_animation_clip("Idle", duration_seconds=2.0)
    walk = api.create_animation_clip("Walk", duration_seconds=1.0)
    space = api.create_blend_space("Speed", dimensions=1, axes=[{
        "name": "Speed", "parameter": "speed", "minimum": 0, "maximum": 6,
    }], samples=[
        {"id": "idle", "clip_asset_id": idle.asset_id, "position": [0]},
        {"id": "walk", "clip_asset_id": walk.asset_id, "position": [3]},
    ])
    assert api.validate_animation_asset(space.asset_id) == []
    assert sum(api.evaluate_blend_space(space.asset_id, 1.5).values()) == pytest.approx(1.0)
    artifact = api.cook_animation_asset(space.asset_id, platform="windows", quality="high")
    runtime = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert runtime["schema"] == "tech_connector.runtime.animation.v1"
    assert runtime["sample_count"] == 2
    manifest = json.loads(api.cook([space.asset_id], platform="windows", quality="high").artifact.path.read_text(encoding="utf-8"))
    blend_row = next(row for row in manifest["assets"] if row["asset_id"] == space.asset_id)
    assert blend_row["derived_outputs"][0]["kind"] == "blend_space_runtime"
    contract = api.capability_contract()
    assert "convert_unreal_animation" in contract["animation_operations"]


def test_unreal_conversion_maps_state_machine_and_preserves_unknown_nodes(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.convert_unreal_animation({
        "engine_version": "5.8", "animation_sequences": [
            {"name": "Idle", "object_path": "/Game/Anim/Idle", "duration": 2.0},
        ],
        "animation_blueprints": [{
            "name": "ABP_Hero", "object_path": "/Game/Anim/ABP_Hero",
            "parameters": {"speed": {"type": "float", "default": 0}},
            "state_machines": [{
                "name": "Locomotion", "entry_state": "idle",
                "states": [{"id": "idle", "animation": "/Game/Anim/Idle"}],
                "transitions": [],
            }],
            "nodes": [{"type": "MotionMatching", "name": "Chooser"}],
        }],
    })
    assert receipt["succeeded"] is True
    assert len(receipt["asset_ids"]) == 2
    assert receipt["source_to_asset"]["/Game/Anim/Idle"]
    assert any(item["code"] == "unsupported_node_preserved" for item in receipt["diagnostics"])
    controller_id = receipt["source_to_asset"]["/Game/Anim/ABP_Hero"]
    properties = api.animation_properties(controller_id)
    assert properties["layers"][0]["state_machine"]["states"][0]["motion"]["asset_id"] == receipt["source_to_asset"]["/Game/Anim/Idle"]
    assert properties["source_extensions"][0]["kind"] == "MotionMatching"


def test_unity_conversion_extracts_blend_tree_and_maps_conditions(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.convert_unity_animation({
        "unity_version": "6000.0",
        "animation_clips": [
            {"name": "Idle", "guid": "idle-guid", "duration": 2.0, "frame_rate": 60.0, "events": [{"name": "Footstep", "time": 0.5}]},
            {"name": "Run", "guid": "run-guid", "duration": 0.8, "frame_rate": 60.0},
            {"name": "Jump", "guid": "jump-guid", "duration": 1.0, "frame_rate": 30.0},
        ],
        "animation_masks": [{"name": "UpperBody", "guid": "mask-guid", "transforms": [{"path": "Root/Spine", "active": True}]}],
        "controllers": [{
            "name": "HeroController", "guid": "controller-guid",
            "parameters": [{"name": "Speed", "type": "Float", "default_float": 1.5}, {"name": "Grounded", "type": "Bool", "default_bool": True}],
            "layers": [{
                "name": "Base Layer", "mask": "mask-guid", "defaultState": "move", "states": [{
                    "id": "move", "name": "Move", "motion": {
                        "type": "BlendTree", "id": "move-tree", "name": "Movement",
                        "blendType": "Simple1D", "blendParameter": "Speed",
                        "children": [{"motion": "idle-guid", "threshold": 0}, {"motion": "run-guid", "threshold": 6}],
                    },
                }, {"id": "air", "name": "Air", "motion": "jump-guid"}],
                "transitions": [{"from": "move", "to": "air", "conditions": [{"parameter": "Grounded", "mode": "IfNot"}]}],
            }],
        }],
    })
    assert len(receipt["asset_ids"]) == 6
    controller = api.animation_properties(receipt["source_to_asset"]["controller-guid"])
    assert controller["parameters"]["Speed"]["default"] == 1.5
    assert controller["parameters"]["Grounded"]["default"] is True
    assert controller["layers"][0]["state_machine"]["transitions"][0]["conditions"][0]["operator"] == "is_false"
    blend_id = receipt["source_to_asset"]["move-tree"]
    assert controller["layers"][0]["state_machine"]["states"][0]["motion"]["asset_id"] == blend_id
    assert controller["layers"][0]["mask_asset_id"] == receipt["source_to_asset"]["mask-guid"]
    assert api.animation_properties(blend_id)["dimensions"] == 1
    samples = api.animation_properties(blend_id)["samples"]
    assert samples[0]["clip_asset_id"] == receipt["source_to_asset"]["idle-guid"]
    assert api.animation_properties(receipt["source_to_asset"]["idle-guid"])["events"][0]["name"] == "Footstep"


def test_interchange_round_trip_keeps_native_properties(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    clip = api.create_animation_clip("Take", duration_seconds=1.25, sample_rate=60)
    exported = api.export_animation_interchange([clip.asset_id])
    assert exported["schema"] == ANIMATION_INTERCHANGE_SCHEMA
    imported = api.import_animation_interchange(exported, folder="Imported")
    imported_values = api.animation_properties(imported["asset_ids"][0])
    assert imported_values["duration_seconds"] == 1.25
    record = api.database.asset(imported["asset_ids"][0])
    assert json.loads(record.source_path.read_text(encoding="utf-8"))["schema"] != ANIMATION_CONTROLLER_SCHEMA


def test_legacy_locomotion_controller_migrates_and_cooks_without_source_rewrite(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.create_asset("tc.animation_controller", "LegacyLocomotion", properties=locomotion_preset("third_person"))
    assert api.validate_animation_asset(receipt.asset_id) == []
    properties = api.animation_properties(receipt.asset_id)
    assert properties["layers"][0]["state_machine"]["entry_state"] == "idle"
    assert api.cook_animation_asset(receipt.asset_id).path.is_file()


def test_live_bridge_export_entry_points_return_converter_ready_documents(monkeypatch) -> None:
    unity = UnityBridge()
    monkeypatch.setattr(unity, "execute_command", lambda command, params, **options: (True, json.dumps({"unity_version": "6000.0", "controllers": []})))
    ok, unity_data = unity.export_animation_controller("Assets/Hero.controller")
    assert ok and unity_data["unity_version"] == "6000.0"

    unreal = UnrealBridge()
    captured = {}
    def execute(source, **_options):
        captured["source"] = source
        return {"ok": True, "data": {"engine_version": "5.8", "animation_sequences": []}}
    monkeypatch.setattr(unreal, "execute_python", execute)
    unreal_data = unreal.export_animation_assets(["/Game/Hero/ABP_Hero"])
    assert unreal_data["ok"] is True
    assert "/Game/Hero/ABP_Hero" in captured["source"]


def test_engine_export_file_imports_to_native_assets_and_rejects_private_formats(tmp_path) -> None:
    api = TCEditorAPI(tmp_path / "project")
    export_path = tmp_path / "unity-animation.json"
    export_path.write_text(json.dumps({
        "unity_version": "6000.0", "animation_clips": [
            {"name": "Attack", "guid": "attack-guid", "duration": 0.75, "frame_rate": 60.0},
        ], "controllers": [],
    }), encoding="utf-8")
    receipt = api.convert_animation_export_file(export_path, provider="unity")
    assert receipt["source_to_asset"]["attack-guid"]
    private_path = tmp_path / "Hero.controller"
    private_path.write_text("private unity yaml", encoding="utf-8")
    with pytest.raises(ValueError, match="engine-private format"):
        api.convert_animation_export_file(private_path, provider="unity")


def test_live_engine_conversion_materializes_native_assets(monkeypatch, tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    monkeypatch.setattr(UnityBridge, "export_animation_controller", lambda self, path, **options: (True, {
        "unity_version": "6000.0", "animation_clips": [
            {"name": "UnityIdle", "guid": "unity-idle", "duration": 1.0, "frame_rate": 30.0},
        ], "controllers": [],
    }))
    unity_receipt = api.convert_live_unity_animation("Assets/Hero.controller")
    assert api.database.asset(unity_receipt["source_to_asset"]["unity-idle"]).asset_type == "tc.animation_clip"

    monkeypatch.setattr(UnrealBridge, "export_animation_assets", lambda self, paths, **options: {
        "ok": True, "data": {"engine_version": "5.8", "animation_sequences": [
            {"name": "UnrealIdle", "object_path": "/Game/Idle", "duration": 1.0, "sample_rate": 30.0},
        ]},
    })
    unreal_receipt = api.convert_live_unreal_animation(["/Game/Idle"])
    assert api.database.asset(unreal_receipt["source_to_asset"]["/Game/Idle"]).asset_type == "tc.animation_clip"
