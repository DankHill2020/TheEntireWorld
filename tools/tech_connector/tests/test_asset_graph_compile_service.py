from __future__ import annotations

import json

from tech_connector.game_engine.assets import (
    COMPILED_ASSET_IR_SCHEMA, AssetDatabase, AssetGraphCompileService, AssetOperationsService,
)


def _write_properties(database, asset_id: str, properties: dict) -> None:
    record = database.asset(asset_id)
    payload = json.loads(record.source_path.read_text(encoding="utf-8"))
    payload["properties"].update(properties)
    record.source_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    database.register_asset(
        record.source_path, record.asset_type, asset_id=record.asset_id,
        metadata=record.metadata, dependencies=database.dependency_edges(record.asset_id),
    )


def test_material_graph_compiles_to_deterministic_runtime_ir(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Compiled")
    _write_properties(database, material.asset_id, {"graph": {
        "nodes": [
            {"id": "texture", "title": "Texture Sample", "parameters": {"slot": "base_color"}},
            {"id": "surface", "title": "Surface Output", "parameters": {}},
        ],
        "connections": [{"source": "texture", "target": "surface"}],
    }})
    compiler = AssetGraphCompileService(database)

    receipt = compiler.compile_asset(material.asset_id, target="desktop")
    repeated = compiler.compile_asset(material.asset_id, target="desktop")

    assert receipt.succeeded
    assert receipt.ir["schema"] == COMPILED_ASSET_IR_SCHEMA
    assert [item["opcode"] for item in receipt.ir["executable"]["operations"]] == ["texture_sample", "surface_output"]
    assert receipt.ir == repeated.ir
    assert receipt.artifact.content_hash == repeated.artifact.content_hash


def test_dependency_cycle_blocks_shader_artifact(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    shader = operations.create_asset("tc.shader_graph", "S_Cycle")
    _write_properties(database, shader.asset_id, {"graph": {
        "nodes": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
        "connections": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    }})

    receipt = AssetGraphCompileService(database).compile_asset(shader.asset_id)

    assert not receipt.succeeded and receipt.artifact is None
    assert any(item.code == "dependency_cycle" for item in receipt.diagnostics)


def test_fx_and_animation_models_compile_to_runtime_operations(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    effect = operations.create_asset("tc.effect_system", "FX_Impact")
    animation = operations.create_asset("tc.animation_clip", "A_Jump")
    _write_properties(database, effect.asset_id, {"emitters": [{
        "id": "sparks", "name": "Sparks", "spawn_rate": 90,
        "modules": ["initialize", "gravity", "collision", "sprite"],
    }]})
    _write_properties(database, animation.asset_id, {"curves": [
        {"frame": 1, "value": 0, "interpolation": "bezier", "out_tangent": 0.5},
        {"frame": 12, "value": 1, "interpolation": "linear", "in_tangent": 0.2},
    ]})
    compiler = AssetGraphCompileService(database)

    fx_receipt = compiler.compile_asset(effect.asset_id)
    animation_receipt = compiler.compile_asset(animation.asset_id)

    assert fx_receipt.succeeded and fx_receipt.operation_count == 4
    assert animation_receipt.succeeded and animation_receipt.operation_count == 1
    assert animation_receipt.ir["executable"]["segments"][0]["start"]["out_tangent"] == 0.5
