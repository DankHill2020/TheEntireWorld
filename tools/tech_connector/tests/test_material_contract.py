from __future__ import annotations

from pathlib import Path

from tech_connector.game_engine.rendering.material_contract import (
    PORTABLE_LOOKDEV_SCHEMA,
    PORTABLE_MATERIAL_SCHEMA,
    canonical_texture_channel,
    embed_portable_lookdev_textures,
    lookdev_state_from_snapshot,
    normalize_portable_lookdev_state,
    normalize_portable_material,
    portable_material_runtime_capabilities,
    provider_lookdev_capture_profile,
    resolve_embedded_lookdev_textures,
    viewer_material_approximation,
)
from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    federated_scene_lookdev_report,
    load_federated_scene,
    save_federated_scene,
)


def test_normalizes_openpbr_parameters_and_legacy_aliases() -> None:
    material = normalize_portable_material({
        "name": "Paint",
        "color": [0.2, 0.4, 0.8, 0.75],
        "metallic": 1.4,
        "roughness": -0.2,
        "ior": 1.42,
        "transmission": 0.3,
        "clearcoat": 0.8,
    }, source_provider="blender")

    assert material.schema == PORTABLE_MATERIAL_SCHEMA
    assert material.parameters["base_color"] == (0.2, 0.4, 0.8, 0.75)
    assert material.parameters["metalness"] == 1.0
    assert material.parameters["specular_roughness"] == 0.0
    assert material.parameters["specular_ior"] == 1.42
    assert material.parameters["transmission_weight"] == 0.3
    assert material.parameters["coat_weight"] == 0.8


def test_texture_roles_get_explicit_color_spaces_and_canonical_channels() -> None:
    material = normalize_portable_material({
        "textures": {
            "base_color_texture": "textures/albedo.png",
            "normal map": {"path": "textures/normal.exr"},
            "roughness": {"path": "textures/roughness.png", "color_space": "Utility - Raw"},
        },
    }, source_path="C:/show/assets/robot/robot.fbx")

    assert canonical_texture_channel("base_color_texture") == "base_color"
    assert material.textures["base_color"].color_space == "sRGB - Texture"
    assert material.textures["normal"].color_space == "Raw"
    assert material.textures["specular_roughness"].color_space == "Utility - Raw"


def test_source_graph_and_unsupported_nodes_survive_viewer_approximation() -> None:
    graph = {"nodes": [{"name": "Layered", "type": "CUSTOM_LAYER"}], "links": []}
    material = normalize_portable_material({
        "name": "Hero",
        "source_shader": "custom_layered_shader",
        "source_graph": graph,
        "unsupported_nodes": ["CUSTOM_LAYER", "CUSTOM_LAYER"],
    }, source_provider="maya")
    approximation = viewer_material_approximation(material)

    assert material.source_graph == graph
    assert material.unsupported_nodes == ("CUSTOM_LAYER",)
    assert material.approximation == "openpbr_with_source_fallback"
    assert approximation["portable_material"]["source_graph"] == graph


def test_optional_sdk_absence_never_disables_portable_contract() -> None:
    capabilities = portable_material_runtime_capabilities()

    assert capabilities["portable_contract"] is True
    assert set(capabilities["available"]) == {"materialx", "opencolorio", "openusd"}


def test_provider_capture_profiles_distinguish_dcc_roles_and_fidelity() -> None:
    assert provider_lookdev_capture_profile("maya")["assignment_level"] == "face"
    assert provider_lookdev_capture_profile("3dsmax")["uv_level"] == "map_channel_1"
    assert provider_lookdev_capture_profile("unreal")["capture_status"] == "partial"
    assert provider_lookdev_capture_profile("substance_painter")["capture_status"] == "lookdev_only"
    assert provider_lookdev_capture_profile("motionbuilder")["capture_status"] == "not_role_required"
    assert "not lookdev authoring" in provider_lookdev_capture_profile("motionbuilder")["limitations"][0]


def test_maya_snapshot_records_honest_object_level_lookdev_and_texture_evidence(tmp_path) -> None:
    texture = tmp_path / "sourceimages" / "hero_base.png"
    texture.parent.mkdir()
    texture.write_bytes(b"portable texture")
    snapshot = {
        "provider_id": "maya",
        "scene": str(tmp_path / "hero.ma"),
        "isolation": {"include_materials": True},
        "objects": [{
            "native_id": "|hero|body_GEO",
            "type": "mesh",
            "geometry": {"representation": "mesh"},
            "material": {
                "name": "body_MAT",
                "source_material_id": "body_MAT",
                "shader_type": "aiStandardSurface",
                "color": [0.2, 0.3, 0.4, 1.0],
                "texture_paths": {"base_color": str(texture)},
            },
        }],
    }

    state = lookdev_state_from_snapshot(snapshot)
    payload = state.to_dict()

    assert payload["schema"] == PORTABLE_LOOKDEV_SCHEMA
    assert list(payload["materials"]) == ["body_MAT"]
    assert payload["assignments"][0]["object_native_id"] == "|hero|body_GEO"
    assert payload["assignments"][0]["assignment_level"] == "object"
    assert payload["parity"]["object_assignments"]["status"] == "complete"
    assert payload["parity"]["face_assignments"]["status"] == "unavailable"
    asset = next(iter(payload["texture_assets"].values()))
    assert asset["exists"] and asset["head_sha256"]


def test_blender_face_assignments_and_uv_sets_survive_normalization() -> None:
    snapshot = {
        "provider_id": "blender",
        "objects": [{
            "native_id": "Cube",
            "type": "mesh",
            "geometry": {"representation": "mesh", "active_uv_set": "UVMap"},
            "materials": [
                {"name": "Red", "source_material_id": "Red", "color": [1, 0, 0, 1]},
                {"name": "Blue", "source_material_id": "Blue", "color": [0, 0, 1, 1]},
            ],
            "material_assignments": [
                {"material_id": "Red", "slot_index": 0, "face_indices": [0, 1, 2], "uv_set": "UVMap"},
                {"material_id": "Blue", "slot_index": 1, "face_indices": [5, 6], "uv_set": "UVMap"},
            ],
        }],
    }

    saved = lookdev_state_from_snapshot(snapshot).to_dict()
    normalized = normalize_portable_lookdev_state(saved).to_dict()

    assert normalized["assignments"][0]["face_ranges"] == [[0, 2]]
    assert normalized["assignments"][1]["face_ranges"] == [[5, 6]]
    assert normalized["parity"]["face_assignments"]["status"] == "complete"
    assert normalized["parity"]["uv_bindings"]["status"] == "complete"
    assert normalized["materials"]["Red"]["parameters"]["base_color"] == (1.0, 0.0, 0.0, 1.0)


def test_unity_texture_binding_lists_normalize_without_host_specific_routing(tmp_path) -> None:
    texture = tmp_path / "Assets" / "Textures" / "hero.png"
    texture.parent.mkdir(parents=True)
    texture.write_bytes(b"unity texture")
    state = lookdev_state_from_snapshot({
        "provider_id": "unity",
        "objects": [{
            "native_id": "GlobalObjectId_V1-2-3",
            "type": "MeshRenderer",
            "bbox": [0, 0, 0, 1, 1, 1],
            "materials": [{
                "name": "Hero",
                "source_material_id": "guid-hero",
                "source_shader": "Universal Render Pipeline/Lit",
                "color": [0.1, 0.2, 0.3, 1.0],
                "textures": [{
                    "channel": "base_color",
                    "source_channel": "_BaseMap",
                    "path": str(texture),
                    "color_space": "sRGB - Texture",
                    "uv_set": "uv0",
                }],
            }],
            "material_assignments": [{"material_id": "guid-hero", "slot_index": 0, "uv_set": "uv0"}],
        }],
    }).to_dict()

    binding = state["materials"]["guid-hero"]["textures"]["base_color"]
    assert binding["path"] == str(texture.resolve())
    assert binding["source_channel"] == "_BaseMap"
    assert state["assignments"][0]["uv_set"] == "uv0"
    assert state["parity"]["object_assignments"]["status"] == "complete"


def test_max_houdini_unreal_and_painter_fixtures_share_one_lookdev_contract() -> None:
    fixtures = {
        "3dsmax": {
            "native_id": "42", "type": "Editable_Poly", "bbox": [0, 0, 0, 1, 1, 1],
            "geometry": {"representation": "mesh", "active_uv_set": "map1"},
            "materials": [{"name": "Physical", "source_material_id": "9001", "roughness": 0.3}],
            "material_assignments": [{"material_id": "9001", "slot_index": 0, "face_indices": [0, 1], "uv_set": "map1"}],
        },
        "houdini": {
            "native_id": "/obj/geo1/OUT", "type": "geo", "bbox": [0, 0, 0, 1, 1, 1],
            "geometry": {"representation": "mesh", "active_uv_set": "uv"},
            "materials": [{"name": "principledshader1", "source_material_id": "/mat/principledshader1"}],
            "material_assignments": [{"material_id": "/mat/principledshader1", "slot_index": 0, "face_indices": [2], "uv_set": "uv"}],
        },
        "unreal": {
            "native_id": "/Game/Maps/Shot.Shot:PersistentLevel.Prop", "type": "StaticMeshActor",
            "bbox": [0, 0, 0, 1, 1, 1],
            "materials": [{"name": "MI_Prop", "source_material_id": "/Game/Materials/MI_Prop"}],
            "material_assignments": [{"material_id": "/Game/Materials/MI_Prop", "slot_index": 0}],
        },
        "substance_painter": {
            "native_id": "textureset:Body", "type": "texture_set",
            "materials": [{
                "name": "Body", "source_material_id": "textureset:Body",
                "unsupported_nodes": ["substance_painter_layer_stack"],
            }],
            "material_assignments": [{"material_id": "textureset:Body", "slot_index": 0}],
        },
    }

    states = {
        provider: lookdev_state_from_snapshot({"provider_id": provider, "objects": [fixture]}).to_dict()
        for provider, fixture in fixtures.items()
    }

    assert states["3dsmax"]["parity"]["face_assignments"]["status"] == "complete"
    assert states["houdini"]["assignments"][0]["uv_set"] == "uv"
    assert states["unreal"]["assignments"][0]["assignment_level"] == "slot"
    assert states["substance_painter"]["materials"]["textureset:Body"]["approximation"] == "openpbr_with_source_fallback"


def test_texture_embedding_is_bounded_and_archive_round_trips_lookdev(tmp_path) -> None:
    small = tmp_path / "small.png"
    large = tmp_path / "large.exr"
    small.write_bytes(b"small")
    large.write_bytes(b"0123456789")
    snapshot = {
        "provider_id": "maya",
        "scene": str(tmp_path / "shot.ma"),
        "objects": [{
            "native_id": "mesh",
            "type": "mesh",
            "material": {
                "name": "Mat",
                "texture_paths": {"base_color": str(small), "normal": str(large)},
            },
        }],
    }
    state = lookdev_state_from_snapshot(snapshot)
    embedded, blobs = embed_portable_lookdev_textures(
        state,
        source_id="maya-shot",
        max_file_bytes=5,
        max_total_bytes=5,
    )
    assets = list(embedded["texture_assets"].values())

    assert len(blobs) == 1
    assert sum(asset["storage"] == "embedded" for asset in assets) == 1
    assert sum(asset.get("embed_reason") == "size_limit" for asset in assets) == 1

    document = FederatedSceneDocument(sources=[{
        "source_id": "maya-shot",
        "provider": "maya",
        "source_path": str(tmp_path / "shot.ma"),
        "lookdev_state": embedded,
    }])
    path = save_federated_scene(tmp_path / "lookdev.tcscene", document, blobs=blobs)
    restored, restored_blobs = load_federated_scene(path)
    report = federated_scene_lookdev_report(restored)

    assert restored.sources[0]["lookdev_state"]["schema"] == PORTABLE_LOOKDEV_SCHEMA
    assert restored.sources[0]["lookdev_state"]["parity"]["texture_assets"]["embedded_count"] == 1
    assert restored_blobs == blobs
    assert report["source_count"] == 1
    assert report["entries"][0]["material_count"] == 1

    resolved_snapshot, resolution = resolve_embedded_lookdev_textures(
        snapshot,
        restored.sources[0]["lookdev_state"],
        restored_blobs,
        cache_root=tmp_path / "resolved",
    )
    resolved_paths = resolved_snapshot["objects"][0]["material"]["texture_paths"]
    assert Path(resolved_paths["base_color"]).read_bytes() == b"small"
    assert resolved_paths["normal"] == str(large)
    assert resolution["resolved_count"] == 1


def test_scene_snapshot_viewer_keeps_multi_material_face_colors() -> None:
    from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel

    model = FBXMeshModel.from_scene_snapshot({
        "provider_id": "maya",
        "unit_linear": "centimeters",
        "up_axis": "y",
        "objects": [{
            "native_id": "mesh",
            "name": "mesh",
            "type": "mesh",
            "bbox": [0, 0, 0, 1, 1, 0],
            "geometry": {
                "representation": "mesh",
                "vertices": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                "faces": [[0, 1, 2], [0, 2, 3]],
            },
            "materials": [
                {"name": "Red", "source_material_id": "Red", "color": [1, 0, 0, 1]},
                {"name": "Blue", "source_material_id": "Blue", "color": [0, 0, 1, 1]},
            ],
            "material_assignments": [
                {"material_id": "Red", "face_indices": [0]},
                {"material_id": "Blue", "face_indices": [1]},
            ],
        }],
    })

    assert [color.name() for color in model.face_colors] == ["#ff0000", "#0000ff"]
    assert [binding.source_material_id for binding in model.scene_proxy_objects[0].materials] == ["Red", "Blue"]
