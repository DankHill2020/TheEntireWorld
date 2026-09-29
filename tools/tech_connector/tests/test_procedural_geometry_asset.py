from __future__ import annotations

import json

from tech_connector.game_engine.assets import AssetDatabase, AssetProductionService, ProceduralGraphAssetService
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.authoring.procedural_generation_service import (
    ProceduralBuildQueue, ProceduralGraph, ProceduralGraphCooker,
)
from tech_connector.game_engine.authoring.procedural_graph_tooling_service import (
    ProceduralNodeGroup, ProceduralSimulationSession, build_procedural_execution_plan,
    instantiate_node_group,
)
from tech_connector.game_engine.integration.procedural_native_serializer_service import (
    deserialize_native_procedural_graph, serialize_native_procedural_graph,
)


def _mesh_graph() -> ProceduralGraph:
    graph = ProceduralGraph(name="Procedural Boulder", graph_id="procedural_boulder", seed=17)
    graph.add_node("sphere", "mesh_uv_sphere", parameters={"segments": 12, "rings": 6, "radius": 2.0})
    graph.add_node("subdivide", "mesh_subdivide", inputs=("sphere",), parameters={"levels": 1})
    graph.add_node("output", "output", inputs=("subdivide",))
    return graph


def test_extended_mesh_nodes_and_branch_invalidation() -> None:
    graph = _mesh_graph()
    cooker = ProceduralGraphCooker()
    first = cooker.cook(graph)
    assert first.payload.meshes
    assert all(not diagnostic.cache_hit for diagnostic in first.diagnostics)
    second = cooker.cook(graph)
    assert all(diagnostic.cache_hit for diagnostic in second.diagnostics)

    assert cooker.invalidate_nodes(graph, ("subdivide",)) == ("subdivide", "output")
    third = cooker.cook(graph)
    hits = {diagnostic.node_id: diagnostic.cache_hit for diagnostic in third.diagnostics}
    assert hits == {"sphere": True, "subdivide": False, "output": False}


def test_background_queue_coalesces_and_cooks() -> None:
    queue = ProceduralBuildQueue(workers=2)
    try:
        first = queue.submit(_mesh_graph())
        second = queue.submit(_mesh_graph())
        assert first is second
        result = first.result(timeout=5.0)
        assert result.output_node == "output"
        assert len(result.payload.meshes) == 1
    finally:
        queue.shutdown()


def test_procedural_asset_python_api_and_production_cook(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    service = ProceduralGraphAssetService(tmp_path, database)
    receipt = service.create("ProceduralBoulder", graph=_mesh_graph())

    assert service.validate(receipt.asset_id) == []
    artifact = service.cook(receipt.asset_id, platform="windows", quality="high")
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["schema"] == "tech_connector.procedural_geometry_runtime.v1"
    assert payload["cook"]["output_node"] == "output"
    assert payload["cook"]["payload"]["meshes"]
    first_bytes = artifact.path.read_bytes()
    second_bytes = service.cook(receipt.asset_id, platform="windows", quality="high").path.read_bytes()
    assert second_bytes == first_bytes
    assert all("elapsed_ms" not in row and "cache_hit" not in row for row in payload["cook"]["diagnostics"])

    api = TCEditorAPI(tmp_path, database=database)
    assert "mesh_uv_sphere" in api.procedural_operation_catalog()
    assert api.validate_procedural_graph(receipt.asset_id) == []
    assert api.properties(receipt.asset_id)["graph"]["graph_id"] == "procedural_boulder"
    assert "procedural_geometry_operations" in api.capability_contract()

    cooked = AssetProductionService(tmp_path, database).cook_manifest((receipt.asset_id,))
    manifest = json.loads(cooked.artifact.path.read_text(encoding="utf-8"))
    outputs = manifest["assets"][0]["derived_outputs"]
    assert any(output["kind"] == "procedural_geometry_runtime" for output in outputs)


def test_curve_fields_normals_uv_and_boolean_nodes() -> None:
    graph = ProceduralGraph(name="Cable", graph_id="cable")
    graph.add_node("path", "curve_line", parameters={"start": [0, 0, 0], "end": [0, 0, 4], "points": 5})
    graph.add_node("sweep", "curve_to_mesh", inputs=("path",), parameters={"radius": 0.25, "profile_resolution": 8})
    graph.add_node("field", "field_set", inputs=("sweep",), parameters={"domain": "point", "name": "weight", "value": 0.5})
    graph.add_node("math", "field_math", inputs=("field",), parameters={"domain": "point", "source": "weight", "operation": "multiply", "value": 2})
    graph.add_node("normals", "mesh_compute_normals", inputs=("math",))
    graph.add_node("uv", "mesh_generate_uv", inputs=("normals",), parameters={"projection": "xz"})
    graph.add_node("output", "output", inputs=("uv",))
    result = ProceduralGraphCooker().cook(graph)
    mesh = next(iter(result.payload.meshes.values()))
    assert len(mesh["vertices"]) == 40
    assert mesh["attributes"]["point"]["weight"]["values"] == [1.0] * 40
    assert len(mesh["attributes"]["point"]["normal"]["values"]) == 40
    assert len(mesh["attributes"]["point"]["uv"]["values"]) == 40

    boolean = ProceduralGraph(name="Boolean", graph_id="boolean")
    boolean.add_node("a", "mesh_cube")
    boolean.add_node("b", "mesh_cube")
    boolean.add_node("union", "mesh_boolean", inputs=("a", "b"), parameters={"operation": "union"})
    cooked = ProceduralGraphCooker().cook(boolean)
    assert len(next(iter(cooked.payload.meshes.values()))["vertices"]) == 16


def test_node_groups_execution_plan_native_roundtrip_and_simulation() -> None:
    group_graph = ProceduralGraph(name="Rock Group", graph_id="rock_group")
    group_graph.add_node("sphere", "mesh_uv_sphere", parameters={"segments": 8, "rings": 4})
    group_graph.add_node("normals", "mesh_compute_normals", inputs=("sphere",))
    group = ProceduralNodeGroup("rock", group_graph, outputs=("geometry",))
    parent = ProceduralGraph(name="Grouped", graph_id="grouped")
    mapping = instantiate_node_group(parent, group, prefix="rock_01")
    assert parent.output_node == mapping["normals"]
    assert parent.metadata["node_group_instances"][0]["group_id"] == "rock"

    plan = build_procedural_execution_plan(parent)
    assert plan.gpu_node_count == 1
    assert plan.cpu_node_count == 1
    assert plan.transfer_count == 1

    document = serialize_native_procedural_graph(parent, "blender")
    assert document.schema == "blender.geometry_nodes.adapter.v1"
    assert document.lossless
    restored = deserialize_native_procedural_graph(document.to_dict())
    assert restored.to_dict() == parent.to_dict()

    result = ProceduralGraphCooker().cook(parent)
    simulation = ProceduralSimulationSession("preview")
    first = simulation.step(result, delta_time=0.1)
    second = simulation.step(result, delta_time=0.1)
    first_y = next(iter(first.meshes.values()))["vertices"][0][1]
    second_y = next(iter(second.meshes.values()))["vertices"][0][1]
    assert second_y < first_y
    assert second.metadata["simulation"]["frame"] == 2


def test_domain_mapping_deformation_remesh_and_volume_roundtrip() -> None:
    graph = ProceduralGraph(name="Advanced Mesh", graph_id="advanced_mesh")
    graph.add_node("cube", "mesh_cube", parameters={"size": [2, 2, 2]})
    graph.add_node("weight", "field_set", inputs=("cube",), parameters={"domain": "point", "name": "weight", "value": 0.5})
    graph.add_node("face_weight", "field_map_domain", inputs=("weight",), parameters={"source_domain": "point", "target_domain": "face", "source": "weight"})
    graph.add_node("normals", "mesh_compute_normals", inputs=("face_weight",))
    graph.add_node("displace", "mesh_displace", inputs=("normals",), parameters={"distance": 0.2, "field": "weight"})
    graph.add_node("smooth", "mesh_smooth", inputs=("displace",), parameters={"factor": 0.1})
    graph.add_node("remesh", "mesh_voxel_remesh", inputs=("smooth",), parameters={"voxel_size": 0.05})
    graph.add_node("volume", "mesh_to_volume", inputs=("remesh",), parameters={"resolution": 4})
    graph.add_node("surface", "volume_to_mesh", inputs=("volume",))
    result = ProceduralGraphCooker().cook(graph)
    mesh = next(iter(result.payload.meshes.values()))
    assert len(mesh["vertices"]) == 8
    assert result.payload.metadata["warning_volume_preview"]


def test_procedural_asset_advanced_python_surface(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    api = TCEditorAPI(tmp_path, database=database)
    receipt = api.create_procedural_graph("Advanced", graph=_mesh_graph())
    plan = api.procedural_execution_plan(receipt.asset_id)
    assert plan["graph_id"] == "procedural_boulder"
    native = api.procedural_native_document(receipt.asset_id, "houdini")
    assert native["schema"] == "houdini.sop.network.adapter.v1"
    imported = api.import_procedural_native_document(native, name="HoudiniRoundTrip")
    assert api.get_procedural_graph(imported.asset_id)["graph"]["graph_id"] == "procedural_boulder"
    assert api.procedural_diagnostics(receipt.asset_id)["counts"]["meshes"] == 1
    assert api.step_procedural_simulation(receipt.asset_id)["metadata"]["simulation"]["frame"] == 1
    assert api.reset_procedural_simulation(receipt.asset_id)
