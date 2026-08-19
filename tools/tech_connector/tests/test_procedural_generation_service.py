from __future__ import annotations

from tech_connector.game_engine.authoring.procedural_generation_service import (
    ProceduralGraph,
    ProceduralGraphCooker,
    attach_procedural_graph,
    create_scatter_graph,
)
from tech_connector.game_engine.authoring.procedural_spatial_service import (
    PolygonMask2D,
    annotate_point_neighborhoods,
    create_heightfield,
    filter_points_by_heightfield_mask,
    filter_points_by_polygon,
    project_points_to_heightfield,
)
from tech_connector.game_engine.authoring.procedural_biome_service import (
    BiomeDefinition,
    BiomeSpecies,
    generate_noise_heightfield,
    hydraulic_erode_heightfield,
    scatter_biome,
    thermal_erode_heightfield,
)
from tech_connector.game_engine.authoring.procedural_layout_service import (
    GrammarModule,
    ShapeGrammar,
    SplinePath,
    create_road_layout,
    expand_shape_grammar,
    place_shape_grammar_on_spline,
)
from tech_connector.game_engine.authoring.procedural_task_graph_service import (
    ProceduralTaskCooker,
    ProceduralTaskGraph,
    wedge_parameters,
)
from tech_connector.game_engine.authoring.procedural_mesh_service import (
    create_cube_mesh,
    create_grid_mesh,
    mesh_from_data,
)
from tech_connector.game_engine.integration.adaptive_scene_command_service import (
    SceneCommandTarget,
    resolve_adaptive_scene_command,
)
from tech_connector.game_engine.integration.procedural_transfer_service import (
    build_procedural_transfer_manifest,
)
from tech_connector.game_engine.runtime.procedural_runtime_service import (
    ProceduralGenerationSource,
    ProceduralRuntimeProfile,
    partition_procedural_result,
    schedule_procedural_runtime,
)
from tech_connector.game_engine.scene.federated_scene_service import FederatedSceneDocument


def test_scatter_is_deterministic_incremental_and_changes_with_seed() -> None:
    graph = create_scatter_graph(assets=("TreeA", "TreeB"), count=40, seed=17, density=0.65)
    cooker = ProceduralGraphCooker()
    first = cooker.cook(graph)
    second = cooker.cook(graph)

    assert first.payload.fingerprint == second.payload.fingerprint
    assert first.payload.instances
    assert all(row.cache_hit for row in second.diagnostics)

    graph.seed = 18
    changed = cooker.cook(graph)
    assert changed.payload.fingerprint != first.payload.fingerprint
    assert not any(row.cache_hit for row in changed.diagnostics)


def test_graph_supports_spline_repeat_attributes_and_cycle_validation() -> None:
    graph = ProceduralGraph(graph_id="roadside", seed=4)
    graph.add_node(
        "road",
        "spline_sample",
        parameters={"control_points": ((0, 0, 0), (5, 0, 0), (5, 0, 5)), "count": 6},
    )
    graph.add_node("floors", "repeat_transform", inputs=("road",), parameters={"iterations": 3, "offset": (0, 2, 0)})
    graph.add_node("assets", "select_asset", inputs=("floors",), parameters={"assets": ("Lamp",)})
    graph.add_node("instances", "instance_on_points", inputs=("assets",))

    result = ProceduralGraphCooker().cook(graph)
    assert len(result.payload.instances) == 18
    assert result.payload.points[-1].attributes["iteration"] == 2

    graph.connect("instances", "road")
    assert any("cycle" in error.lower() for error in graph.validate())


def test_scene_attachment_and_every_engine_transfer_manifest() -> None:
    graph = create_scatter_graph(assets=({"asset": "Rock", "weight": 2}, "Bush"), count=12, seed=2)
    result = ProceduralGraphCooker().cook(graph)
    scene = FederatedSceneDocument()
    entry = attach_procedural_graph(scene, graph, result)
    assert entry["last_cook"]["instance_count"] == 12

    for target in ("unreal", "blender", "houdini", "unity", "godot"):
        manifest = build_procedural_transfer_manifest(graph, result, target)
        assert manifest["counts"]["instances"] == 12
        assert manifest["validation"]
        assert all(row["support"] == "native" for row in manifest["nodes"])


def test_procedural_commands_are_available_to_chat_and_ui_routing() -> None:
    route = resolve_adaptive_scene_command(
        "procedural.create_scatter_graph",
        SceneCommandTarget(provider="tech_connector", object_type="scene"),
        {"count": 100, "seed": 9},
    )
    assert route.status == "routable"
    assert route.command["department"] == "procedural"


def test_runtime_partitions_prioritizes_and_cleans_procedural_chunks() -> None:
    graph = create_scatter_graph(
        assets=("Tree",),
        count=120,
        seed=8,
        bounds_min=(-100, 0, -100),
        bounds_max=(100, 0, 100),
    )
    result = ProceduralGraphCooker().cook(graph)
    profile = ProceduralRuntimeProfile(
        grid_sizes=(32.0,),
        generation_radii={32.0: 70.0},
        max_parallel_generation=2,
        frame_budget_ms=1.0,
    )
    chunks = partition_procedural_result(result, profile)
    assert sum(len(chunk.instances) for chunk in chunks) == 120
    assert len({instance.instance_id for chunk in chunks for instance in chunk.instances}) == 120

    source = ProceduralGenerationSource("player", (0, 0, 0), forward=(1, 0, 0))
    first = schedule_procedural_runtime(chunks, (source,), profile=profile)
    generated = [item for item in first.items if item.action == "generate"]
    assert len(generated) <= 2
    assert first.deferred

    loaded = {chunks[0].chunk_id, "removed_graph:g32:0_0_0"}
    distant = ProceduralGenerationSource("player", (1000, 0, 1000))
    cleanup = schedule_procedural_runtime(chunks, (distant,), loaded_chunk_ids=loaded, profile=profile)
    assert loaded.issubset({item.chunk_id for item in cleanup.items if item.action == "cleanup"})


def test_heightfield_projection_masks_and_native_point_properties() -> None:
    heightfield = create_heightfield(
        ((0, 1, 2), (0, 1, 2), (0, 1, 2)),
        attributes={"forest": ((0, 0.4, 1), (0, 0.4, 1), (0, 0.4, 1))},
    )
    graph = ProceduralGraph(graph_id="terrain_points")
    graph.add_node("grid", "grid_points", parameters={"count_x": 3, "count_z": 3, "centered": False})
    source = ProceduralGraphCooker().cook(graph).payload
    projected = project_points_to_heightfield(source, heightfield)

    assert projected.points[-1].position == (2.0, 2.0, 2.0)
    assert projected.points[-1].steepness > 0.0
    assert projected.points[-1].seed == graph.seed
    forest = filter_points_by_heightfield_mask(projected, heightfield, "forest", minimum=0.5)
    assert len(forest.points) == 3


def test_polygon_set_masks_and_spatial_hash_neighborhoods() -> None:
    graph = ProceduralGraph(graph_id="mask_points")
    graph.add_node("grid", "grid_points", parameters={"count_x": 4, "count_z": 4, "centered": False})
    payload = ProceduralGraphCooker().cook(graph).payload
    outer = ((0, 0), (4, 0), (4, 4), (0, 4))
    hole = ((1, 1), (3, 1), (3, 3), (1, 3))
    masked = filter_points_by_polygon(payload, PolygonMask2D((outer, hole), "difference"))
    annotated = annotate_point_neighborhoods(masked, 1.1)

    assert 0 < len(masked.points) < len(payload.points)
    assert all("neighbor_count" in point.attributes for point in annotated.points)


def test_spatial_operations_cook_inside_the_graph() -> None:
    heightfield = create_heightfield(((0, 0), (2, 2)))
    graph = ProceduralGraph(graph_id="spatial_graph")
    graph.add_node("grid", "grid_points", parameters={"count_x": 2, "count_z": 2, "centered": False})
    graph.add_node("project", "project_heightfield", inputs=("grid",), parameters={"heightfield": heightfield.to_dict()})
    graph.add_node("neighbors", "point_neighborhood", inputs=("project",), parameters={"radius": 2.0})
    result = ProceduralGraphCooker().cook(graph)

    assert len(result.payload.points) == 4
    assert all(point.attributes["neighbor_count"] > 0 for point in result.payload.points)


def test_terrain_noise_and_erosion_are_deterministic_and_mass_preserving() -> None:
    first = generate_noise_heightfield(12, 10, seed=42, octaves=3)
    second = generate_noise_heightfield(12, 10, seed=42, octaves=3)
    changed = generate_noise_heightfield(12, 10, seed=43, octaves=3)
    eroded = thermal_erode_heightfield(first, iterations=5)

    assert first.heights == second.heights
    assert first.heights != changed.heights
    assert abs(sum(first.heights) - sum(eroded.heights)) < 1e-8
    assert eroded.attributes == first.attributes


def test_hydraulic_erosion_preserves_terrain_sediment_mass_and_exposes_flow_fields() -> None:
    terrain = generate_noise_heightfield(10, 9, seed=71, amplitude=4.0, frequency=0.18, octaves=2)
    first = hydraulic_erode_heightfield(terrain, iterations=12, rainfall=0.03)
    second = hydraulic_erode_heightfield(terrain, iterations=12, rainfall=0.03)

    assert first.heights == second.heights
    assert set(("water_flow", "flow_direction_x", "flow_direction_z", "sediment", "wetness", "river_mask")) <= set(first.attributes)
    assert max(first.attributes["water_flow"]) == 1.0
    assert all(0.0 <= value <= 1.0 for value in first.attributes["river_mask"])
    original_mass = sum(terrain.heights)
    eroded_mass = sum(first.heights) + sum(first.attributes["sediment"])
    assert abs(original_mass - eroded_mass) < 1.0e-7

    graph = ProceduralGraph(graph_id="hydraulic_terrain")
    graph.add_node(
        "erode",
        "terrain_hydraulic_erosion",
        parameters={"heightfield": terrain.to_dict(), "iterations": 4},
    )
    result = ProceduralGraphCooker().cook(graph)
    assert "river_mask" in result.payload.metadata["field_outputs"]
    manifest = build_procedural_transfer_manifest(graph, result, "houdini")
    assert not manifest["unsupported_nodes"]
    assert manifest["field_manifest"]["attributes"]["river_mask"]

    biome = BiomeDefinition(name="River Plants", species=(BiomeSpecies("Reed"),), seed=2)
    graph.add_node("biome", "biome_scatter", inputs=("erode",), parameters={"biome": biome.to_dict()})
    chained = ProceduralGraphCooker().cook(graph)
    assert chained.payload.instances


def test_biome_rules_spacing_runtime_grids_and_graph_cooking() -> None:
    terrain = generate_noise_heightfield(14, 14, seed=5, amplitude=3, frequency=0.15, octaves=2)
    biome = BiomeDefinition(
        name="Temperate Forest",
        seed=11,
        density=1.0,
        species=(
            BiomeSpecies("Oak", weight=3, maximum_slope=55, minimum_spacing=1.5, generation_grid=64),
            BiomeSpecies("Fern", weight=1, maximum_slope=70, generation_grid=16),
        ),
    )
    direct = scatter_biome(terrain, biome)
    repeated = scatter_biome(terrain, biome)
    assert direct.fingerprint == repeated.fingerprint
    assert direct.instances
    assert {row.attributes["generation_grid"] for row in direct.instances}.issubset({16, 64})

    graph = ProceduralGraph(graph_id="biome_graph", seed=3)
    graph.add_node(
        "biome",
        "biome_scatter",
        parameters={"heightfield": terrain.to_dict(), "biome": biome.to_dict()},
    )
    result = ProceduralGraphCooker().cook(graph)
    assert result.payload.instances
    chunks = partition_procedural_result(result)
    assert {chunk.grid_size for chunk in chunks}.issubset({16.0, 64.0})


def test_shape_grammar_expansion_and_spline_placement_are_bounded() -> None:
    path = SplinePath(((0, 0, 0), (10, 0, 0), (10, 0, 10)))
    grammar = ShapeGrammar(
        axiom=("A",),
        productions={"A": (("P", "F", "A"),)},
        modules=(
            GrammarModule("P", "FencePost", 1.0),
            GrammarModule("F", "FencePanel", 2.0),
        ),
        seed=4,
        max_depth=2,
        fit="repeat",
    )
    # The unresolved recursive symbol is intentionally rejected at this depth.
    try:
        expand_shape_grammar(grammar)
    except ValueError as exc:
        assert "unresolved" in str(exc).lower()
    else:
        raise AssertionError("Expected bounded grammar to reject an unresolved recursive symbol.")

    terminal = ShapeGrammar(
        axiom=("P", "F"),
        modules=grammar.modules,
        seed=4,
        fit="repeat",
    )
    first = place_shape_grammar_on_spline(path, terminal)
    second = place_shape_grammar_on_spline(path, terminal)
    assert first.fingerprint == second.fingerprint
    assert first.instances
    assert all("spline_u" in instance.attributes for instance in first.instances)


def test_road_and_graph_layout_share_the_same_spline_contract() -> None:
    path = SplinePath(((0, 0, 0), (12, 0, 0)))
    road = create_road_layout(path, segment_asset="RoadStraight", segment_length=3, lanes=4)
    assert len(road.instances) == 4
    assert all(instance.attributes["lane_count"] == 4 for instance in road.instances)

    grammar = ShapeGrammar(
        axiom=("R",),
        modules=(GrammarModule("R", "RoadStraight", 3.0),),
        seed=1,
    )
    graph = ProceduralGraph(graph_id="road_graph")
    graph.add_node(
        "road",
        "shape_grammar_spline",
        parameters={"control_points": path.control_points, "grammar": grammar.to_dict()},
    )
    result = ProceduralGraphCooker().cook(graph)
    assert len(result.payload.instances) == 4


def test_task_graph_fanout_wedges_partitions_parallelism_and_cache() -> None:
    assert wedge_parameters({"quality": ("low", "high"), "seed": (1, 2)}) == [
        {"quality": "low", "seed": 1},
        {"quality": "low", "seed": 2},
        {"quality": "high", "seed": 1},
        {"quality": "high", "seed": 2},
    ]
    graph = ProceduralTaskGraph("world_build")
    graph.add_node(
        "tiles",
        "tag_tile",
        fan_out=3,
        parameters={"wedges": {"variant": ("A", "B")}},
    )
    graph.add_node("partitions", inputs=("tiles",), partition_by=("variant",))

    cooker = ProceduralTaskCooker(max_workers=4)
    cooker.register_processor(
        "tag_tile",
        lambda attributes, _parameters: {**attributes, "tile": attributes["fan_index"]},
    )
    first = cooker.cook(graph, initial_attributes={"world": "Demo"})
    second = cooker.cook(graph, initial_attributes={"world": "Demo"})

    assert len(first.node_items["tiles"]) == 6
    assert len(first.work_items) == 2
    assert all(item.attributes["partition_size"] == 3 for item in first.work_items)
    assert second.cache_hits == len(second.diagnostics)

    changed = cooker.cook(graph, initial_attributes={"world": "Changed"})
    assert changed.cache_hits == 0


def test_procedural_mesh_primitives_graph_edits_and_transfer_use_tc_topology() -> None:
    cube = create_cube_mesh((2, 2, 2))
    grid = create_grid_mesh(4, 3, 4, 3)
    assert len(cube.faces) == 6
    assert len(grid.faces) == 12

    graph = ProceduralGraph(graph_id="procedural_mesh")
    graph.add_node("cube", "mesh_cube", parameters={"name": "Building", "size": (2, 2, 2)})
    graph.add_node(
        "extrude",
        "mesh_extrude_faces",
        inputs=("cube",),
        parameters={"faces": (1,), "distance": 1.0},
    )
    graph.add_node("triangles", "mesh_triangulate", inputs=("extrude",))
    result = ProceduralGraphCooker().cook(graph)
    mesh = mesh_from_data(result.payload.meshes["Building"])

    assert len(mesh.vertices) > len(cube.vertices)
    assert all(len(face) == 3 for face in mesh.faces)
    assert result.payload.meshes["Building"]["metadata"]["operation"] == "mesh_triangulate"
    for target in ("unreal", "blender", "houdini", "unity", "godot"):
        manifest = build_procedural_transfer_manifest(graph, result, target)
        assert manifest["counts"]["meshes"] == 1
        assert not manifest["unsupported_nodes"]
