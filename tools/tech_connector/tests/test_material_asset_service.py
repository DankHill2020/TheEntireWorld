from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import (
    AssetDatabase, AssetOperationsService, AssetProductionService, MaterialService, TCEditorAPI,
)
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor
from tech_connector.ui.game_engine.asset_specialized_editors import (
    MaterialCompileInspectorWidget, MaterialInstanceEditorWidget, TextureInspectorEditorWidget,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _services(tmp_path):
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    return project, database, MaterialService(project, database)


def test_material_instances_resolve_inheritance_and_static_permutations(tmp_path) -> None:
    project, database, materials = _services(tmp_path)
    base = materials.create_material("M_CarPaint", preset="clear_coat")
    first = materials.create_instance(
        "MI_CarPaint_Red", base.asset_id,
        overrides={"base_color": "#d02018", "roughness": 0.2},
        static_switch_overrides={"USE_FLAKES": True},
    )
    second = materials.create_instance(
        "MI_CarPaint_Red_Wet", first.asset_id,
        overrides={"clear_coat_roughness": 0.02},
    )

    resolved = materials.resolve(second.asset_id)

    assert resolved.root_material_id == base.asset_id
    assert resolved.inheritance_chain == (base.asset_id, first.asset_id, second.asset_id)
    assert resolved.properties["base_color"] == "#d02018"
    assert resolved.properties["clear_coat"] == pytest.approx(1.0)
    assert resolved.properties["clear_coat_roughness"] == pytest.approx(0.02)
    assert resolved.properties["static_switches"]["USE_FLAKES"] is True
    assert database.dependency_edges(second.asset_id) == ((first.asset_id, "parent_material"),)
    assert not [item for item in materials.validate(second.asset_id) if item.severity == "error"]


def test_texture_binding_color_space_dependency_and_runtime_cook(tmp_path) -> None:
    project, database, materials = _services(tmp_path)
    texture_path = tmp_path / "T_Packed.png"
    texture_path.write_bytes(b"png-test")
    texture = AssetOperationsService(project, database).import_asset(texture_path)
    material = materials.create_material("M_Packed")
    materials.assign_texture(material.asset_id, "roughness", texture.asset_id)

    resolution = materials.resolve(material.asset_id)
    assert resolution.properties["texture_bindings"]["roughness"]["color_space"] == "linear"
    assert database.dependency_edges(material.asset_id) == ((texture.asset_id, "material_resource"),)

    artifact = materials.compile(material.asset_id, platform="windows", quality="high")
    runtime = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert runtime["schema"] == "tech_connector.runtime.material.v1"
    assert runtime["texture_bindings"]["roughness"]["asset_id"] == texture.asset_id
    assert "TC_Surface EvaluateMaterial" in runtime["generated_source"]

    manifest = AssetProductionService(project, database).cook_manifest([material.asset_id])
    cooked = json.loads(manifest.artifact.path.read_text(encoding="utf-8"))
    row = next(item for item in cooked["assets"] if item["asset_id"] == material.asset_id)
    assert row["derived_outputs"][0]["kind"] == "material_runtime"


def test_material_graph_diagnostics_report_output_cost_and_permutations(tmp_path) -> None:
    project, database, materials = _services(tmp_path)
    material = materials.create_material("M_Complex")
    record = database.asset(material.asset_id)
    payload = json.loads(record.source_path.read_text(encoding="utf-8"))
    payload["properties"]["graph"] = {
        "nodes": [
            {"id": "uv", "title": "Texture Coordinates", "opcode": "uv"},
            {"id": "tex", "title": "Texture Sample", "opcode": "sample_texture"},
            {"id": "noise", "title": "Noise", "opcode": "noise"},
            {"id": "switch_a", "title": "Static Switch", "opcode": "static_switch"},
            {"id": "switch_b", "title": "Static Switch", "opcode": "static_switch"},
            {"id": "out", "title": "Surface Output", "opcode": "surface_output"},
        ],
        "connections": [
            {"source": "uv", "target": "tex"}, {"source": "tex", "target": "switch_a"},
            {"source": "noise", "target": "switch_a"}, {"source": "switch_a", "target": "switch_b"},
            {"source": "switch_b", "target": "out"},
        ],
    }
    record.source_path.write_text(json.dumps(payload), encoding="utf-8")
    database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata)

    runtime = json.loads(materials.compile(material.asset_id).path.read_text(encoding="utf-8"))
    assert runtime["statistics"]["texture_samples"] == 1
    assert runtime["statistics"]["permutations"] == 4
    assert "Noise" in runtime["statistics"]["expensive_nodes"]

    payload["properties"]["graph"]["connections"].append({"source": "out", "target": "uv"})
    record.source_path.write_text(json.dumps(payload), encoding="utf-8")
    database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata)
    issues = materials.validate(material.asset_id)
    assert any(item.code == "dependency_cycle" and item.severity == "error" for item in issues)


def test_material_python_api_has_ui_parity(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    api = TCEditorAPI(project)
    base = api.create_material("M_Glass", preset="glass")
    instance = api.create_material_instance("MI_Glass_Blue", base.asset_id, overrides={"base_color": "#4080ff"})

    resolved = api.resolve_material(instance.asset_id)
    assert resolved["properties"]["shading_model"] == "thin_translucent"
    assert resolved["properties"]["base_color"] == "#4080ff"
    assert api.validate_material(instance.asset_id) == []
    assert api.cook_material(instance.asset_id).path.is_file()
    assert "create_material_instance" in api.capability_contract()["material_operations"]


def test_shader_graph_and_texture_python_workflows_are_cookable(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    api = TCEditorAPI(project)
    shader = api.create_shader_graph("SG_Surface", graph={
        "nodes": [
            {"id": "color", "title": "Uniform Parameter", "opcode": "parameter"},
            {"id": "out", "title": "Shader Output", "opcode": "shader_output"},
        ],
        "connections": [{"source": "color", "target": "out"}],
    })
    compiled = api.compile_shader_graph(shader.asset_id, target="windows")
    assert compiled["succeeded"]
    assert "TC_ShaderMain" in compiled["ir"]["executable"]["generated_source"]

    source = tmp_path / "T_Normal.png"
    source.write_bytes(b"png-test")
    texture = api.import_asset(source)
    settings = api.set_texture_import_settings(texture.asset_id, {
        "usage": "normal", "color_space": "linear", "compression": "bc5",
        "generate_mips": True, "streaming": True,
    })
    assert settings["compression"] == "bc5"
    assert api.texture_import_settings(texture.asset_id)["usage"] == "normal"
    assert "compile_shader_graph" in api.capability_contract()["shader_operations"]


def test_polished_material_instance_texture_and_compile_editors(tmp_path) -> None:
    project, database, materials = _services(tmp_path)
    base = materials.create_material("M_UI", preset="default_lit")
    instance = materials.create_instance("MI_UI", base.asset_id, overrides={"roughness": 0.25})
    values = json.loads(database.asset(instance.asset_id).source_path.read_text(encoding="utf-8"))["properties"]

    instance_editor = MaterialInstanceEditorWidget(project, database, instance.asset_id)
    instance_editor.load_settings(values)
    roughness_row = next(row for row in range(instance_editor.parameters.rowCount()) if instance_editor.parameters.item(row, 0).text() == "roughness")
    assert instance_editor.parameters.item(roughness_row, 4).text() == "Overridden"

    texture_editor = TextureInspectorEditorWidget()
    texture_editor.load_settings({"usage": "normal", "color_space": "srgb", "compression": "bc1"})
    assert len(texture_editor.validation_issues()) == 2

    compile_editor = MaterialCompileInspectorWidget()
    compile_editor.load_settings({"graph": {"nodes": [], "connections": []}})
    assert "READY" in compile_editor.diagnostics.text()

    dedicated = DedicatedAssetEditor(project, database)
    assert dedicated.open_asset(instance.asset_id)
    assert any(key == "__material_instance__" for key, _widget in dedicated._specialized_widgets)
    assert dedicated.compile()
