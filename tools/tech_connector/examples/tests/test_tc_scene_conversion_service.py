from __future__ import annotations

import array

from tech_connector.services.dcc.federated_scene_service import load_federated_scene
from tech_connector.services.dcc.tc_scene_conversion_service import (
    EMBEDDED_SCENE_SNAPSHOT_BLOB,
    convert_to_tc,
    convert_scene_packets_to_tc,
    _maya_topology_cache_key,
)
from tech_connector.services.dcc.source_conversion_adapter_service import (
    conversion_readiness,
    source_conversion_adapters,
)
from tech_connector.services.dcc.tc_runtime_authoring_service import runtime_authoring_contract


IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _maya_scene_snapshot() -> dict:
    return {
        "provider_id": "maya:7001",
        "scene": "C:/show/hero_rig.ma",
        "unit_linear": "cm",
        "up_axis": "y",
        "current_time": 8,
        "frame_start": 1,
        "frame_end": 24,
        "frame_rate": 24.0,
        "objects": [{
            "native_id": "|Hero|BodyShape",
            "name": "BodyShape",
            "type": "mesh",
            "bbox": [-1.0, 0.0, -1.0, 1.0, 0.0, 1.0],
            "visible": True,
            "geometry": {
                "representation": "mesh",
                "vertices_f32": array.array("f", [-1.0, 0.0, -1.0, 1.0, 0.0, -1.0, 1.0, 0.0, 1.0, -1.0, 0.0, 1.0]),
                "faces": [[0, 1, 2, 3]],
                "uvs": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                "face_uv_indices": [[0, 1, 2, 3]],
            },
            "material": {
                "name": "Hero_Mat",
                "source_material_id": "Hero_Mat",
                "color": [0.25, 0.5, 0.75],
                "roughness": 0.35,
                "metalness": 0.1,
            },
        }],
        "cameras": [{"native_id": "|shotCam|shotCamShape", "name": "shotCamShape", "focal_length_mm": 50.0}],
    }


def _maya_rig_topology() -> dict:
    return {
        "provider_id": "maya:7001",
        "nodes": [
            {
                "native_id": "|Hero|root",
                "name": "root",
                "node_type": "dag.joint",
                "source_type": "joint",
                "dag_parent_native_id": "",
                "source_order": 0,
                "attributes": {"translate": [0.0, 0.0, 0.0]},
                "portable": True,
            },
            {
                "native_id": "|Hero|root|spine",
                "name": "spine",
                "node_type": "dag.joint",
                "source_type": "joint",
                "dag_parent_native_id": "|Hero|root",
                "source_order": 1,
                "attributes": {"translate": [0.0, 5.0, 0.0]},
                "portable": True,
            },
            {
                "native_id": "|Hero|BodyShape",
                "name": "BodyShape",
                "node_type": "dag.mesh",
                "source_type": "mesh",
                "dag_parent_native_id": "",
                "source_order": 2,
                "attributes": {},
                "portable": True,
            },
            {
                "native_id": "spine_rotateY",
                "name": "spine_rotateY",
                "node_type": "animation.curve",
                "source_type": "animCurveTA",
                "dag_parent_native_id": "",
                "source_order": 3,
                "attributes": {
                    "weighted_tangents": True,
                    "pre_infinity": 0,
                    "post_infinity": 0,
                    "keys": [
                        {"frame": 1.0, "value": 0.0, "interpolation": "auto", "out_tangent": "auto"},
                        {"frame": 12.0, "value": 45.0, "interpolation": "spline", "out_tangent": "spline"},
                    ],
                },
                "portable": True,
            },
            {
                "native_id": "heroStudioPluginNode",
                "name": "heroStudioPluginNode",
                "node_type": "source.opaque",
                "source_type": "heroStudioSolver",
                "dag_parent_native_id": "",
                "source_order": 4,
                "attributes": {"strength": 0.75},
                "portable": False,
            },
        ],
        "connections": [{
            "source_node": "spine_rotateY",
            "source_attribute": "output",
            "target_node": "|Hero|root|spine",
            "target_attribute": "rotateY",
            "connection_type": "attribute",
        }],
        "constraints": [{
            "native_id": "hero_parentConstraint",
            "type": "parent",
            "source_type": "parentConstraint",
            "targets": [{"native_id": "|Hero|root", "weight": 1.0}],
            "driven_native_id": "|Hero|root|spine",
            "enabled": True,
        }],
    }


def _maya_skin_binding() -> dict:
    inverse = array.array("f", IDENTITY + IDENTITY)
    rest = array.array("f", [-1.0, 0.0, -1.0, 1.0, 0.0, -1.0, 1.0, 0.0, 1.0, -1.0, 0.0, 1.0])
    offsets = array.array("I", [0, 1, 2, 4, 6])
    indices = array.array("I", [0, 0, 0, 1, 0, 1])
    weights = array.array("f", [1.0, 1.0, 0.5, 0.5, 0.25, 0.75])
    return {
        "provider_id": "maya:7001",
        "skeletons": [{
            "native_id": "HeroSkeleton",
            "joints": [
                {"native_id": "|Hero|root", "name": "root", "parent_native_id": ""},
                {"native_id": "|Hero|root|spine", "name": "spine", "parent_native_id": "|Hero|root"},
            ],
            "inverse_bind_matrices_f32": inverse,
            "inverse_bind_float_offset": 0,
        }],
        "meshes": [{
            "native_id": "|Hero|BodyShape",
            "skeleton_id": "HeroSkeleton",
            "vertex_count": 4,
            "joint_count": 2,
            "bind_vertices_f32": rest,
            "bind_vertex_float_offset": 0,
            "bind_geometry_matrix": IDENTITY,
            "influence_offsets_u32": offsets,
            "influence_offset_offset": 0,
            "joint_indices_u32": indices,
            "joint_index_offset": 0,
            "weights_f32": weights,
            "weight_float_offset": 0,
            "sparse_influence_count": 6,
            "max_influences_per_vertex": 2,
            "deformation_mode": "linear_blend_skinning",
            "runtime_mode": "linear_blend_skinning",
        }],
    }


def test_converts_maya_rig_scene_to_standalone_tc_archive(tmp_path) -> None:
    from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel

    result = convert_scene_packets_to_tc(
        _maya_scene_snapshot(),
        rig_topology=_maya_rig_topology(),
        deformation_binding=_maya_skin_binding(),
        source_provider="maya",
    )

    graph = result.document.rig_graph
    assert graph.validate() == []
    assert len(graph.joints) == 2
    assert len(graph.skins) == 1
    assert len(graph.constraints) == 1
    assert all(item["ownership"] == "native" and item["edit_policy"] == "full" for item in graph.nodes.values())
    receipt = result.report["native_conversion_receipt"]
    root_id = receipt["node_ids"]["maya::|Hero|root"]
    spine_id = receipt["node_ids"]["maya::|Hero|root|spine"]
    proxy_id = receipt["node_ids"]["maya::heroStudioPluginNode"]
    skin_id = next(iter(graph.skins))
    assert all(node_id.startswith("tc.node.") for node_id in graph.nodes)
    assert not any(node_id.startswith("maya::") for node_id in graph.nodes)
    assert graph.nodes[spine_id]["dag_parent_id"] == root_id
    assert graph.nodes[spine_id]["node_type"] == "tc.rig.joint"
    assert graph.nodes[spine_id]["contract_node_type"] == "dag.joint"
    assert graph.nodes[spine_id]["source_ref"]["native_id"] == "|Hero|root|spine"
    assert graph.nodes[proxy_id]["evaluation_mode"] == "source_proxy"
    assert graph.skins[skin_id]["evaluation_mode"] == "gpu_local"

    take = graph.animation["take_maya_base"]
    curve = take["layers"]["BaseAnimation"]["curves"][f"{spine_id}.rotateY"]
    assert [key["value"] for key in curve["keys"]] == [0.0, 45.0]
    assert result.report["counts"]["materials"] == 1
    assert result.report["counts"]["cameras"] == 1
    assert any(issue["source_id"] == "heroStudioPluginNode" for issue in result.report["issues"])
    assert EMBEDDED_SCENE_SNAPSHOT_BLOB in result.blobs
    assert result.scene_snapshot["provider_id"] == "tech_connector"
    assert result.scene_snapshot["source_provider"] == "maya:7001"
    assert result.scene_snapshot["objects"][0]["native_id"].startswith("tc.node.")
    assert any(name.endswith("inverse_bind.f32") and len(data) == 128 for name, data in result.blobs.items())
    assert any(name.endswith("weights.f32") and len(data) == 24 for name, data in result.blobs.items())
    viewport_model = FBXMeshModel.from_scene_snapshot(result.scene_snapshot)
    assert len(viewport_model.scene_proxy_objects) == 1
    assert viewport_model.scene_proxy_objects[0].representation == "mesh"
    assert viewport_model.scene_proxy_objects[0].mesh_data.source_vertex_count == 4

    destination = result.save(tmp_path / "hero_converted.tcscene")
    restored, restored_blobs = load_federated_scene(destination)
    assert restored.rig_graph.validate() == []
    assert restored.sources[0]["reload_policy"] == "embedded"
    assert restored.metadata["tc_native_scene_snapshot_blob"] == EMBEDDED_SCENE_SNAPSHOT_BLOB
    assert EMBEDDED_SCENE_SNAPSHOT_BLOB in restored_blobs
    assert b'"conversion_state":"tc_native"' in restored_blobs[EMBEDDED_SCENE_SNAPSHOT_BLOB]


def test_can_convert_geometry_without_a_rig() -> None:
    result = convert_scene_packets_to_tc(_maya_scene_snapshot(), source_provider="maya")

    assert result.report["status"] == "converted"
    assert result.report["counts"]["meshes"] == 1
    assert result.report["counts"]["joints"] == 0
    assert result.document.rig_graph.validate() == []


def test_blender_snapshot_is_normalized_to_tc_coordinates() -> None:
    snapshot = {
        "provider_id": "blender:7002",
        "unit_linear": "m",
        "up_axis": "z",
        "objects": [{
            "native_id": "Cube",
            "name": "Cube",
            "type": "mesh",
            "bbox": [0.0, 0.0, 0.0, 1.0, 2.0, 3.0],
            "geometry": {"vertices": [[1.0, 2.0, 3.0]], "faces": []},
        }],
    }

    result = convert_scene_packets_to_tc(snapshot, source_provider="blender")

    obj = result.scene_snapshot["objects"][0]
    assert obj["geometry"]["vertices"] == [[100.0, 300.0, -200.0]]
    assert obj["bbox"] == [0.0, 0.0, -200.0, 100.0, 300.0, 0.0]
    assert obj["source_ref"]["native_id"] == "Cube"


def test_adapter_registry_does_not_claim_unimplemented_parity() -> None:
    adapters = source_conversion_adapters()

    assert {"maya", "blender", "3dsmax", "motionbuilder", "unreal", "unity"} <= set(adapters)
    assert conversion_readiness("maya")["standalone_character_conversion_ready"] is True
    assert conversion_readiness("blender")["standalone_character_conversion_ready"] is False
    assert conversion_readiness("motionbuilder")["static_scene_conversion_ready"] is False
    assert conversion_readiness("3dsmax")["live_bridge"] is False


def test_runtime_contract_keeps_rig_cloth_and_effects_engine_native() -> None:
    contract = runtime_authoring_contract()

    assert all(contract["asset_contracts"][name]["runtime_native"] for name in ("rig", "cloth", "effects"))
    assert "photoreal" in contract["asset_contracts"]["cloth"]["quality_profiles"]
    assert "toony" in contract["asset_contracts"]["effects"]["quality_profiles"]
    assert "retro_simple" in contract["asset_contracts"]["effects"]["quality_profiles"]


def test_conversion_reports_headless_progress() -> None:
    updates = []

    result = convert_to_tc(
        scene_snapshot=_maya_scene_snapshot(),
        progress_callback=lambda percent, text: updates.append((percent, text)),
    )

    assert result.report["counts"]["meshes"] == 1
    assert updates[0][0] == 96
    assert updates[-1] == (100, "TC scene conversion complete")


def test_topology_cache_is_allowed_only_for_unchanged_saved_scene(tmp_path) -> None:
    scene = tmp_path / "character.ma"
    scene.write_text("// maya scene", encoding="ascii")
    inventory = {"scene": str(scene), "scene_modified": False, "process_id": 10, "scene_revision": 4}

    key = _maya_topology_cache_key(inventory, 7001, ["|character|body"], True)

    assert key is not None
    assert _maya_topology_cache_key({**inventory, "scene_modified": True}, 7001, ["|character|body"], True) is None
