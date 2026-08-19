from tech_connector.game_engine.deformation import (
    DeformationWeightMap,
    JiggleDeformerSettings,
    JiggleRuntimeState,
    SimulationMeshBinding,
    SimulationMeshBindingEntry,
    attach_jiggle_deformer,
    attach_deformation_map,
    blend_deformation,
    evaluate_jiggle,
    sample_simulation_mesh,
)
from tech_connector.services.dcc.federated_scene_service import EditableRigGraph
from tech_connector.services.dcc.rig_evaluation_service import rig_runtime_capabilities
from tech_connector.services.dcc.adaptive_scene_command_service import resolve_adaptive_scene_command


def test_brush_changes_only_vertices_inside_the_brush_radius() -> None:
    vertices = [(0, 0, 0), (0.75, 0, 0), (2, 0, 0)]
    weights = DeformationWeightMap.create("sim influence", len(vertices))

    changed = weights.paint(vertices, (0, 0, 0), 1.0, value=1.0, hardness=0.5)

    assert changed == [0, 1]
    assert weights.values[0] == 1.0
    assert 0.0 < weights.values[1] < 1.0
    assert weights.values[2] == 0.0


def test_unpainted_mesh_stays_upstream_and_painted_mesh_follows_simulation() -> None:
    upstream = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
    simulated = [(0, 2, 0), (1, 2, 0), (2, 2, 0)]
    weights = DeformationWeightMap("sim", [0.0, 0.5, 1.0])

    result = blend_deformation(upstream, simulated, weights)

    assert result == [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 2.0, 0.0)]


def test_jiggle_can_follow_skin_output_only_in_painted_regions() -> None:
    weights = DeformationWeightMap("jiggle", [0.0, 1.0])
    state = JiggleRuntimeState()
    settings = JiggleDeformerSettings(stiffness=20.0, damping=2.0, max_offset=10.0, substeps=1)
    evaluate_jiggle([(0, 0, 0), (1, 0, 0)], weights, state, settings, 1.0 / 60.0)

    result = evaluate_jiggle([(0, 1, 0), (1, 1, 0)], weights, state, settings, 1.0 / 60.0)

    assert result[0] == (0.0, 1.0, 0.0)
    assert result[1][1] < 1.0


def test_jiggle_attaches_after_skin_cluster_or_other_deformer() -> None:
    graph = EditableRigGraph()
    graph.skins["skin1"] = {"id": "skin1", "mesh_id": "body"}
    weights = DeformationWeightMap.create("body jiggle", 4)

    jiggle_id = attach_jiggle_deformer(graph, "skin1", "body", weights, deformer_id="jiggle1")
    second_id = attach_jiggle_deformer(graph, jiggle_id, "body", weights, deformer_id="jiggle2")

    assert graph.deformers[jiggle_id]["settings"]["source_kind"] == "skin_cluster"
    assert graph.deformers[second_id]["settings"]["source_kind"] == "deformer"
    assert graph.deformers[jiggle_id]["evaluation_mode"] == "runtime_local"
    assert "jiggle" in rig_runtime_capabilities(graph)["local_deformer_types"]


def test_every_skin_cluster_and_deformer_can_own_an_independent_output_map() -> None:
    graph = EditableRigGraph()
    graph.skins["skin1"] = {"id": "skin1", "mesh_id": "body"}
    graph.add_deformer("body", "delta_mush", deformer_id="mush1")
    skin_map = DeformationWeightMap("skin output", [1.0, 0.5, 0.0])
    mush_map = DeformationWeightMap("mush output", [0.0, 0.5, 1.0])

    attach_deformation_map(graph, "skin1", skin_map)
    attach_deformation_map(graph, "mush1", mush_map)

    assert graph.skins["skin1"]["output_influence_map"]["sparse_values"] == {"0": 1.0, "1": 0.5}
    assert graph.deformers["mush1"]["settings"]["influence_map"]["sparse_values"]["1"] == 0.5


def test_simulation_mesh_barycentric_binding_drives_render_mesh_before_paint_blend() -> None:
    binding = SimulationMeshBinding(
        "render",
        "sim",
        (SimulationMeshBindingEntry((0, 1, 2), (0.25, 0.25, 0.5)),),
    )

    sampled = sample_simulation_mesh([(0, 0, 0), (2, 0, 0), (0, 2, 0)], binding)

    assert sampled == [(0.5, 1.0, 0.0)]


def test_sparse_map_receipt_round_trips() -> None:
    source = DeformationWeightMap("mask", [0.0, 0.0, 0.75, 0.0])
    restored = DeformationWeightMap.from_dict(source.to_dict())

    assert restored.values == source.values


def test_deformation_actions_are_chat_routable_to_the_same_local_contract() -> None:
    route = resolve_adaptive_scene_command(
        "deformation.add_jiggle",
        {"provider": "tech_connector", "native_id": "body"},
        {"source_id": "skin1", "stiffness": 60.0},
    )

    assert route.status == "routable"
    assert route.required_payload["source_id"] == "skin1"

    preset_route = resolve_adaptive_scene_command(
        "deformation.add_secondary_motion_preset",
        {"provider": "tech_connector", "native_id": "body"},
        {"source_id": "skin1", "preset_id": "muscle_follow"},
    )
    assert preset_route.status == "routable"
    assert preset_route.required_payload["preset_id"] == "muscle_follow"
