from __future__ import annotations

import json

import pytest

from tech_connector.game_engine.assets import (
    GAMEPLAY_FOUNDATION_RUNTIME_SCHEMA,
    TCEditorAPI,
)


def _character_fields():
    return [
        {"name": "id", "type": "name", "required": True, "default": ""},
        {"name": "health", "type": "float", "required": True, "default": 100.0},
        {"name": "hostile", "type": "bool", "required": False, "default": False},
    ]


def test_schema_data_asset_dependencies_validation_and_cook(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    schema = api.create_data_schema("CharacterStats", fields=_character_fields())
    data = api.create_typed_data_asset(
        "HeroStats", schema_asset_id=schema.asset_id,
        values={"id": "hero", "health": 150.0, "hostile": False},
    )
    assert api.database.dependencies(data.asset_id) == (schema.asset_id,)
    assert api.validate_gameplay_foundation_asset(data.asset_id) == []
    artifact = api.cook_gameplay_foundation_asset(data.asset_id)
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["schema"] == GAMEPLAY_FOUNDATION_RUNTIME_SCHEMA
    assert payload["properties"]["values"]["health"] == 150.0


def test_inherited_schema_and_data_table_enforce_types_and_unique_keys(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    base = api.create_struct("Identified", fields=[{"name": "id", "type": "name", "required": True}])
    stats = api.create_data_schema("Stats", parent_schema_id=base.asset_id, fields=[{"name": "health", "type": "float", "required": True}])
    resolved = api.resolve_data_schema(stats.asset_id)
    assert [field["name"] for field in resolved["fields"]] == ["id", "health"]
    table = api.create_data_table("Enemies", row_schema_id=stats.asset_id, rows=[
        {"id": "grunt", "health": 50.0}, {"id": "boss", "health": 500.0},
    ])
    assert api.validate_gameplay_foundation_asset(table.asset_id) == []
    api.set_properties(table.asset_id, {"rows": [{"id": "grunt", "health": "a lot"}, {"id": "grunt", "health": 20.0}]})
    codes = {row["code"] for row in api.validate_gameplay_foundation_asset(table.asset_id)}
    assert {"duplicate_row_key", "field_type"} <= codes


def test_component_archetype_character_and_project_settings_form_dependency_graph(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    archetype = api.create_component_archetype("ThirdPersonCharacter", components=[
        {"id": "root", "name": "Root", "type": "transform", "parent_id": "", "enabled": True, "properties": {}},
        {"id": "movement", "name": "Movement", "type": "character_movement", "parent_id": "root", "enabled": True, "properties": {"maximum_speed": 7.0}},
        {"id": "camera", "name": "Camera", "type": "camera", "parent_id": "root", "enabled": True, "properties": {"fov": 75.0}},
    ])
    character = api.create_character_definition("Hero", properties={"archetype_asset_id": archetype.asset_id})
    settings = api.create_project_settings(properties={
        "project": {"display_name": "Foundation Demo", "company": "TC", "version": "1.0.0", "description": ""},
        "gameplay": {"ruleset_asset_id": "", "default_character_asset_id": character.asset_id, "input_map_asset_id": "", "game_instance_asset_id": ""},
    })
    assert api.database.dependencies(character.asset_id) == (archetype.asset_id,)
    assert api.database.dependencies(settings.asset_id) == (character.asset_id,)
    assert api.validate_gameplay_foundation_asset(archetype.asset_id) == []
    assert api.validate_gameplay_foundation_asset(settings.asset_id) == []
    manifest = json.loads(api.cook([settings.asset_id]).artifact.path.read_text(encoding="utf-8"))
    assert {row["type_id"] for row in manifest["assets"]} == {"tc.project_settings", "tc.character_definition", "tc.component_archetype"}


def test_only_one_project_settings_asset_is_allowed(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    api.create_project_settings()
    with pytest.raises(ValueError, match="only one"):
        api.create_project_settings("OtherSettings")


def test_unreal_and_unity_typed_data_conversion(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    unreal = api.convert_unreal_data_assets({
        "engine_version": "5.8", "data_assets": [{"name": "DA_Weapon", "object_path": "/Game/Data/DA_Weapon", "values": {"damage": 25.0, "automatic": True}}],
    })
    unity = api.convert_unity_scriptable_objects({
        "unity_version": "6000.0", "scriptable_objects": [{"name": "EnemyConfig", "guid": "enemy-guid", "type": "EnemyConfig", "fields": {"health": 75, "displayName": "Drone"}}],
    })
    assert len(unreal["asset_ids"]) == 2
    assert len(unity["asset_ids"]) == 2
    assert api.properties(unreal["source_to_asset"]["/Game/Data/DA_Weapon"])["values"]["damage"] == 25.0
    assert api.properties(unity["source_to_asset"]["enemy-guid"])["values"]["displayName"] == "Drone"


def test_python_capability_contract_exposes_gameplay_foundation(tmp_path) -> None:
    operations = TCEditorAPI(tmp_path).capability_contract()["gameplay_foundation_operations"]
    assert {"create_project_settings", "create_data_schema", "create_component_archetype", "convert_unity_scriptable_objects"} <= set(operations)
