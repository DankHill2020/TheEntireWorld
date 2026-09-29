from __future__ import annotations

import json
import os
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService, PrefabService, read_asset_metadata
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor
from tech_connector.ui.game_engine.asset_specialized_editors import (
    AssetCurveEditorWidget, AssetNodeGraphWidget, AudioWaveformEditorWidget,
    AudioMixerEditorWidget, AudioAttenuationEditorWidget,
    DataSchemaEditorWidget, ComponentArchetypeEditorWidget,
    ProjectSettingsEditorWidget,
    CollisionGenerationEditorWidget, DopesheetEditorWidget, EmitterStackEditorWidget,
    ClothSetupEditorWidget, FabricMaterialEditorWidget, MaterialPreviewEditorWidget,
    MeshLodEditorWidget, ProceduralIKEditorWidget,
    PrefabHierarchyEditorWidget,
    VehicleRigEditorWidget,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_node_graph_and_curve_models_round_trip() -> None:
    graph = AssetNodeGraphWidget("material")
    first = graph.add_node("Texture Sample")
    second = graph.add_node("Surface Output")
    assert graph.connect(first, second)
    payload = graph.graph()
    assert [node["title"] for node in payload["nodes"]] == ["Texture Sample", "Surface Output"]
    assert payload["connections"] == [{"source": first, "target": second}]

    restored = AssetNodeGraphWidget("material")
    restored.load_graph(payload)
    assert restored.graph()["connections"] == payload["connections"]
    assert not graph.validation_issues()
    assert graph.connect(second, first)
    assert "cycles" in graph.validation_issues()[0]

    curves = AssetCurveEditorWidget()
    curves.add_key(1, 0.0, "linear")
    curves.add_key(12, 1.0, "bezier")
    assert curves.keys() == [
        {"frame": 1.0, "value": 0.0, "interpolation": "linear", "in_tangent": 0.0, "out_tangent": 0.0},
        {"frame": 12.0, "value": 1.0, "interpolation": "bezier", "in_tangent": 0.0, "out_tangent": 0.0},
    ]

    dopesheet = DopesheetEditorWidget()
    dopesheet.add_event("Gameplay", 8, "Footstep", '{"foot":"left"}')
    assert dopesheet.events() == [{
        "track": "Gameplay", "frame": 8.0, "event": "Footstep", "payload": '{"foot":"left"}',
    }]
    assert not dopesheet.validation_issues()


def test_node_graph_palette_search_copy_paste_and_frame() -> None:
    graph = AssetNodeGraphWidget("material")
    graph.node_search.setText("ramp")
    assert graph.node_palette.count() == 1
    assert graph.node_palette.currentText() == "Ramp"
    ramp = graph.add_palette_node()
    output = graph.add_node("Surface Output")
    assert graph.connect(ramp, output)
    ramp_item = next(item for item in graph.scene.items() if item.data(0) == ramp)
    output_item = next(item for item in graph.scene.items() if item.data(0) == output)
    ramp_item.setSelected(True)
    output_item.setSelected(True)
    assert graph.copy_selected()
    pasted = graph.paste()
    assert len(pasted) == 2
    payload = graph.graph()
    assert len(payload["nodes"]) == 4
    assert len(payload["connections"]) == 2
    ramp_payload = next(node for node in payload["nodes"] if node["id"] == ramp)
    assert ramp_payload["opcode"] == "color_ramp"
    assert ramp_payload["outputs"] == ["color:vec4"]
    graph.frame_all()


def test_procedural_geometry_graph_preserves_runtime_schema() -> None:
    source = {
        "schema": "tc.procedural_graph.v1", "name": "Rocks", "graph_id": "rocks", "seed": 42,
        "output_node": "output", "metadata": {"author": "test"},
        "nodes": [
            {"node_id": "sphere", "operation": "mesh_uv_sphere", "inputs": [],
             "parameters": {"segments": 12}, "enabled": True, "label": "Rock Source"},
            {"node_id": "output", "operation": "output", "inputs": ["sphere"],
             "parameters": {}, "enabled": True, "label": "Output"},
        ],
    }
    graph = AssetNodeGraphWidget("procedural_geometry")
    graph.load_graph(source)
    assert graph.node_palette.findText("Hydraulic Erosion") >= 0
    assert not graph.validation_issues()
    restored = graph.graph()
    assert restored["graph_id"] == "rocks"
    assert restored["seed"] == 42
    assert restored["metadata"] == {"author": "test"}
    output = next(node for node in restored["nodes"] if node["node_id"] == "output")
    assert output["inputs"] == ["sphere"]


def test_cloth_and_fabric_editors_preserve_skinning_and_offer_direct_setup() -> None:
    cloth = ClothSetupEditorWidget()
    cloth.load_settings({"quality_profile": "hero", "preserve_imported_skinning": True})
    cloth.vertex_count.setValue(5)
    cloth.fixed_vertices.setText("0, 1")
    cloth._auto_setup()
    settings = cloth.settings()
    assert settings["preserve_imported_skinning"] is True
    assert settings["property_maps"]["skin_simulation"] == [0.0, 0.0, 1.0, 1.0, 1.0]
    assert cloth.paint_target.findData("skin_simulation") >= 0

    fabric = FabricMaterialEditorWidget()
    fabric.load_settings({"preset": "cotton"})
    fabric.preset.setCurrentText("silk")
    assert fabric.settings()["preset"] == "silk"
    assert fabric.settings()["density"] < 0.2


def test_prefab_hierarchy_editor_exposes_inheritance_and_override_state(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    prefabs = PrefabService(project, database)
    base = prefabs.create_from_entities("Door", [{"name": "Door", "open": False}])
    variant = prefabs.create_variant("OpenDoor", base.asset_id, overrides={"Door_0.open": True})
    values = json.loads(database.asset(variant.asset_id).source_path.read_text(encoding="utf-8"))["properties"]

    editor = PrefabHierarchyEditorWidget(project, database, variant.asset_id)
    editor.load_settings(values)

    assert editor.mode.text() == "PREFAB VARIANT"
    assert editor.hierarchy.topLevelItem(0).text(2) == "Inherited"
    assert editor.overrides.item(0, 0).text() == "Door_0.open"
    assert editor.settings()["variant_overrides"]["Door_0.open"] is True


def test_waveform_emitter_and_collision_controls_export_runtime_values(tmp_path) -> None:
    audio_path = tmp_path / "tone.wav"
    with wave.open(str(audio_path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes((b"\x00\x00\xff\x3f\x00\x00\x01\xc0") * 200)
    audio = AudioWaveformEditorWidget()
    audio.load_audio(audio_path, {"trim_start": 0.01, "loop": True})
    assert audio.canvas.samples
    assert audio.settings()["loop"] is True
    assert audio.settings()["trim_start"] == pytest.approx(0.01)

    emitters = EmitterStackEditorWidget()
    emitters.add_emitter("Sparks")
    emitters.spawn_rate.setValue(120.0)
    emitters.module_type.setCurrentIndex(emitters.module_type.findData("collision"))
    emitters._add_module()
    result = emitters.emitters()
    assert result[0]["spawn_rate"] == 120.0
    assert [module["type"] for module in result[0]["modules"]] == ["initialize", "gravity", "collision"]
    assert result[0]["renderers"][0]["type"] == "sprite"

    collision = CollisionGenerationEditorWidget()
    collision.shape.setCurrentText("convex_hull")
    collision.max_hulls.setValue(12)
    collision.generate()
    assert collision.settings()["shape"] == "convex_hull"
    assert collision.settings()["max_hulls"] == 12
    assert "preview ready" in collision.status.text()


def test_audio_mixer_and_attenuation_editors_round_trip_runtime_values() -> None:
    mixer = AudioMixerEditorWidget()
    mixer.load_settings({
        "groups": [
            {"id": "master", "name": "Master", "parent_id": "", "volume_db": 0.0, "effects": [], "sends": []},
            {"id": "sfx", "name": "SFX", "parent_id": "master", "volume_db": -3.0, "effects": [], "sends": []},
        ],
        "snapshots": [{"id": "default", "name": "Default"}],
    })
    mixer.table.item(1, 2).setText("-6")
    mixer.table.item(1, 5).setText('[{"type":"compressor","enabled":true}]')
    values = mixer.settings()
    assert values["groups"][1]["volume_db"] == -6.0
    assert values["groups"][1]["effects"][0]["type"] == "compressor"
    assert values["snapshots"][0]["id"] == "default"
    assert not mixer.validation_issues()

    attenuation = AudioAttenuationEditorWidget()
    attenuation.load_settings({
        "distance_model": "inverse", "minimum_distance": 1.0, "maximum_distance": 40.0,
        "spatial_blend": 1.0, "doppler_scale": 1.0, "spread_degrees": 0.0,
        "occlusion": {"enabled": False, "low_pass_hz": 1200.0},
        "reverb_send": {"enabled": True, "maximum": 1.0},
    })
    attenuation.model.setCurrentText("linear")
    attenuation.maximum.setValue(75.0)
    attenuation.occlusion.setChecked(True)
    spatial = attenuation.settings()
    assert spatial["distance_model"] == "linear"
    assert spatial["maximum_distance"] == 75.0
    assert spatial["occlusion"]["enabled"] is True
    assert spatial["occlusion"]["low_pass_hz"] == 1200.0
    assert not attenuation.validation_issues()


def test_typed_schema_and_component_archetype_editors_round_trip() -> None:
    schema = DataSchemaEditorWidget()
    schema.load_settings({"parent_schema_id": "base", "fields": [
        {"name": "health", "type": "float", "required": True, "default": 100.0, "minimum": 0.0, "description": "Current health"},
    ]})
    schema._add_field()
    schema.table.item(1, 0).setText("display_name")
    authored = schema.settings()
    assert authored["parent_schema_id"] == "base"
    assert authored["fields"][0]["default"] == 100.0
    assert authored["fields"][1]["name"] == "display_name"
    assert not schema.validation_issues()

    components = ComponentArchetypeEditorWidget()
    components.load_settings({"replication": "replicated", "components": [
        {"id": "root", "name": "Root", "type": "transform", "parent_id": "", "enabled": True, "properties": {}},
    ]})
    components.type.setCurrentText("camera")
    components._add()
    result = components.settings()
    assert result["replication"] == "replicated"
    assert result["components"][1]["type"] == "camera"
    assert result["components"][1]["parent_id"] == "root"
    assert not components.validation_issues()

    project = ProjectSettingsEditorWidget()
    project.load_settings({
        "project": {"display_name": "Demo", "company": "TC", "version": "1.0.0"},
        "startup": {"default_level_asset_id": "level-id"},
        "gameplay": {"ruleset_asset_id": "rules-id", "default_character_asset_id": "character-id", "input_map_asset_id": "input-id"},
        "rendering": {"quality_profile": "high", "frame_rate_limit": 60, "hdr": True},
        "physics": {"fixed_time_step": 0.0166667}, "audio": {"mixer_asset_id": "mixer-id", "master_volume": 0.8},
        "build": {"default_build_profile_asset_id": "build-id"}, "platform_overrides": {"mobile": {"rendering.quality_profile": "low"}},
    })
    project.frame_limit.setValue(120); project.master_volume.setValue(0.65)
    settings = project.settings()
    assert settings["rendering"]["frame_rate_limit"] == 120
    assert settings["audio"]["master_volume"] == pytest.approx(0.65)
    assert settings["platform_overrides"]["mobile"]["rendering.quality_profile"] == "low"
    assert not project.validation_issues()


def test_material_preview_and_mesh_lod_authoring_models() -> None:
    material = MaterialPreviewEditorWidget()
    material.load_settings({"base_color": "#804020", "roughness": 0.25, "metalness": 0.8})
    material.preview_mesh.setCurrentText("Cube")
    material.exposure.setValue(1.0)
    settings = material.settings()
    assert settings["base_color"] == "#804020"
    assert settings["roughness"] == pytest.approx(0.25)
    assert settings["metalness"] == pytest.approx(0.8)
    assert settings["preview_mesh"] == "Cube"
    assert not material.validation_issues()

    lods = MeshLodEditorWidget()
    lods.generate_recommended()
    assert [item["triangle_percent"] for item in lods.lods()] == [100.0, 50.0, 25.0, 12.5]
    assert not lods.validation_issues()
    lods.table.item(2, 1).setText("0.75")
    assert "decrease" in lods.validation_issues()[0]


def test_procedural_ik_and_vehicle_rig_presets_are_editable() -> None:
    procedural = ProceduralIKEditorWidget()
    procedural.create_humanoid_legs()
    limbs = procedural.limbs()
    assert [limb["id"] for limb in limbs] == ["left_leg", "right_leg"]
    assert limbs[0]["root_bone"] == "thigh_l"
    assert not procedural.validation_issues()

    vehicle = VehicleRigEditorWidget()
    vehicle.create_four_wheel_rig()
    wheels = vehicle.wheels()
    assert len(wheels) == 4
    assert sum(wheel["steerable"] for wheel in wheels) == 2
    assert sum(wheel["driven"] for wheel in wheels) == 4
    assert not vehicle.validation_issues()

    dopesheet = DopesheetEditorWidget()
    dopesheet.end_frame.setValue(2)
    dopesheet.frame.setValue(2)
    dopesheet._advance_frame()
    assert dopesheet.frame.value() == 0


def test_dedicated_material_and_fx_editors_save_specialized_models(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Graph")
    effect = operations.create_asset("tc.effect_system", "FX_Sparks")
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(material.asset_id)
    graph = next(widget for key, widget in editor._specialized_widgets if key == "graph")
    source = graph.add_node("Noise")
    output = graph.add_node("Surface")
    graph.connect(source, output)
    assert editor.save()
    material_payload = json.loads(database.asset(material.asset_id).source_path.read_text(encoding="utf-8"))
    assert len(material_payload["properties"]["graph"]["nodes"]) == 2
    assert database.derived(material.asset_id, "compiled_ir:runtime") is not None

    assert editor.open_asset(effect.asset_id)
    stack = next(widget for key, widget in editor._specialized_widgets if key == "emitters")
    stack.add_emitter("Sparks")
    stack.spawn_rate.setValue(80.0)
    assert editor.save()
    effect_payload = json.loads(database.asset(effect.asset_id).source_path.read_text(encoding="utf-8"))
    assert effect_payload["properties"]["emitters"][0]["spawn_rate"] == 80.0


def test_material_preview_and_imported_mesh_lods_persist_through_editor(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    mesh_source = tmp_path / "hero.obj"
    mesh_source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Preview")
    mesh = operations.import_asset(mesh_source)
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(material.asset_id)
    preview = next(widget for key, widget in editor._specialized_widgets if key == "__material_preview__")
    preview.base_color.setText("#3060c0")
    preview.base_color.editingFinished.emit()
    preview.roughness.setValue(0.1875)
    preview.metalness.setValue(0.625)
    assert editor.save(compile_after=False)
    material_payload = json.loads(database.asset(material.asset_id).source_path.read_text(encoding="utf-8"))
    assert material_payload["properties"]["base_color"] == "#3060c0"
    assert material_payload["properties"]["roughness"] == pytest.approx(0.1875)
    assert material_payload["properties"]["metalness"] == pytest.approx(0.625)

    assert editor.open_asset(mesh.asset_id)
    lod_editor = next(widget for key, widget in editor._specialized_widgets if key == "lods")
    lod_editor.generate_recommended()
    assert editor.save(compile_after=False)
    metadata = read_asset_metadata(database.asset(mesh.asset_id).source_path)
    assert len(metadata["importer_settings"]["lods"]) == 4
    assert metadata["importer_settings"]["lods"][-1]["triangle_percent"] == pytest.approx(12.5)


def test_procedural_animation_and_vehicle_presets_persist_through_editor(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    procedural = operations.create_asset("tc.procedural_animation_profile", "PA_Grounded")
    vehicle = operations.create_asset("tc.vehicle_rig", "VR_Coupe")
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(procedural.asset_id)
    ik_editor = next(widget for key, widget in editor._specialized_widgets if key == "limbs")
    ik_editor.create_humanoid_legs()
    assert editor.save(compile_after=False)
    procedural_payload = json.loads(database.asset(procedural.asset_id).source_path.read_text(encoding="utf-8"))
    assert [limb["id"] for limb in procedural_payload["properties"]["limbs"]] == ["left_leg", "right_leg"]

    assert editor.open_asset(vehicle.asset_id)
    vehicle_editor = next(widget for key, widget in editor._specialized_widgets if key == "wheels")
    vehicle_editor.create_four_wheel_rig()
    assert editor.save(compile_after=False)
    vehicle_payload = json.loads(database.asset(vehicle.asset_id).source_path.read_text(encoding="utf-8"))
    assert len(vehicle_payload["properties"]["wheels"]) == 4
    assert sum(wheel["steerable"] for wheel in vehicle_payload["properties"]["wheels"]) == 2
