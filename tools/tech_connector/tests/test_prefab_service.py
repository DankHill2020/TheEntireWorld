from __future__ import annotations

import json

from tech_connector.game_engine.assets import AssetDatabase, AssetProductionService, PrefabService, TCEditorAPI


def _services(tmp_path):
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    return project, database, PrefabService(project, database)


def test_prefab_variants_resolve_stable_ids_and_non_destructive_overrides(tmp_path) -> None:
    project, database, prefabs = _services(tmp_path)
    base = prefabs.create_from_entities(
        "Vehicle",
        [
            {"name": "Body", "transform": {"scale": [1, 1, 1]}, "components": {"health": 100}},
            {"name": "Antenna", "enabled": True},
        ],
        exposed_properties={"team": "blue"},
    )
    variant = prefabs.create_variant(
        "HeavyVehicle", base.asset_id,
        overrides={"Body_0.components.health": 250},
        removed_entity_ids=["Antenna_1"],
        added_entities=[{"name": "Armor", "strength": 80}],
        exposed_properties={"team": "red"},
    )

    resolved = prefabs.resolve(variant.asset_id)

    assert resolved.inheritance_chain == (base.asset_id, variant.asset_id)
    assert [item["entity_id"] for item in resolved.entities] == ["Body_0", "Armor_0"]
    assert resolved.entities[0]["components"]["health"] == 250
    assert resolved.exposed_properties["team"] == "red"
    assert database.dependency_edges(variant.asset_id) == ((base.asset_id, "base_prefab"),)
    assert prefabs.resolve(base.asset_id).entities[0]["components"]["health"] == 100


def test_nested_prefabs_expand_override_validate_and_cook(tmp_path) -> None:
    project, database, prefabs = _services(tmp_path)
    wheel = prefabs.create_from_entities(
        "Wheel", [{"name": "WheelRoot", "radius": 32, "material": "rubber"}],
    )
    car = prefabs.create_from_entities(
        "Car",
        [{
            "name": "FrontWheel", "prefab_asset_id": wheel.asset_id,
            "prefab_overrides": {"WheelRoot_0.radius": 38},
        }],
    )

    resolved = prefabs.resolve(car.asset_id, expand_nested=True)
    nested = resolved.entities[0]["resolved_prefab_entities"]

    assert nested[0]["radius"] == 38
    assert resolved.nested_asset_ids == (wheel.asset_id,)
    assert database.dependency_edges(car.asset_id) == ((wheel.asset_id, "nested_prefab"),)
    assert prefabs.validate(car.asset_id) == ()
    artifact = prefabs.cook(car.asset_id, platform="windows", quality="high")
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["schema"] == "tech_connector.runtime.prefab.v1"
    assert payload["entities"][0]["resolved_prefab_entities"][0]["radius"] == 38

    manifest = AssetProductionService(project, database).cook_manifest([car.asset_id])
    manifest_payload = json.loads(manifest.artifact.path.read_text(encoding="utf-8"))
    car_row = next(item for item in manifest_payload["assets"] if item["asset_id"] == car.asset_id)
    assert car_row["derived_outputs"][0]["kind"] == "prefab_runtime"


def test_instance_partial_apply_revert_diff_and_hot_reload_conflicts(tmp_path) -> None:
    _project, _database, prefabs = _services(tmp_path)
    source = prefabs.create_from_entities(
        "Crate", [{"name": "Crate", "transform": {"scale": [1, 1, 1]}, "health": 50}],
    )
    instance = prefabs.instantiate(source.asset_id, overrides={
        "Crate_0.transform.scale": [2, 2, 2],
        "Crate_0.health": 80,
    })

    assert [row["state"] for row in prefabs.override_diff(instance)] == ["modified", "modified"]
    reverted = prefabs.revert_overrides(instance, paths=["Crate_0.health"])
    assert reverted.entities[0]["health"] == 50
    assert reverted.entities[0]["transform"]["scale"] == [2, 2, 2]

    applied = prefabs.apply_overrides(instance, paths=["Crate_0.health"])
    assert applied.entities[0]["health"] == 80
    assert applied.entities[0]["transform"]["scale"] == [2, 2, 2]
    assert applied.overrides == {"Crate_0.transform.scale": [2, 2, 2]}


def test_editor_python_api_exposes_prefab_parity(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    api = TCEditorAPI(project)
    base = api.create_prefab("Door", [{"name": "Door", "open": False}])
    variant = api.create_prefab_variant("OpenDoor", base.asset_id, overrides={"Door_0.open": True})

    assert api.resolve_prefab(variant.asset_id)["entities"][0]["open"] is True
    assert api.validate_prefab(variant.asset_id) == []
    assert api.cook_prefab(variant.asset_id).path.is_file()
    assert "create_prefab_variant" in api.capability_contract()["prefab_operations"]
