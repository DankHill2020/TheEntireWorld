from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.game_engine.authoring.procedural_task_graph_service import ProceduralTaskGraph
from tech_connector.game_engine.authoring.procedural_workspace_service import ProceduralWorkspaceState
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewerHarness:
    pass


def _execute(viewer: _ViewerHarness, command: str, payload: dict | None = None) -> dict:
    return ThreeDMeshPainterViewport._execute_tc_procedural_command(viewer, command, payload or {})


def test_scatter_graph_is_retained_and_incremental_cook_reuses_cache() -> None:
    viewer = _ViewerHarness()
    created = _execute(
        viewer,
        "procedural.create_scatter_graph",
        {"graph_id": "forest", "assets": ["Tree", "Rock"], "count": 48, "seed": 7},
    )
    first = _execute(viewer, "procedural.cook_graph", {"graph_id": "forest"})
    second = _execute(viewer, "procedural.cook_graph", {"graph_id": "forest"})

    assert created["graph_id"] == "forest"
    assert first["cook"]["payload"]["instances"]
    assert all(row["cache_hit"] for row in second["cook"]["diagnostics"])


def test_terrain_erosion_and_biome_share_serialized_heightfield() -> None:
    viewer = _ViewerHarness()
    terrain = _execute(
        viewer,
        "procedural.generate_terrain",
        {"graph_id": "terrain", "width": 12, "depth": 10, "seed": 3},
    )
    eroded = _execute(
        viewer,
        "procedural.erode_terrain",
        {"graph_id": "terrain", "iterations": 2},
    )
    biome = _execute(
        viewer,
        "procedural.generate_biome",
        {
            "graph_id": "forest",
            "terrain_graph_id": "terrain",
            "species": [{"asset": "Tree", "minimum_spacing": 0.5}],
            "seed": 4,
        },
    )

    assert terrain["cook"]["payload"]["metadata"]["heightfield"]["width"] == 12
    assert "river_mask" in eroded["cook"]["payload"]["metadata"]["field_outputs"]
    assert biome["cook"]["payload"]["instances"]


def test_mesh_graph_attaches_and_builds_native_transfer_manifest() -> None:
    viewer = _ViewerHarness()
    mesh = _execute(
        viewer,
        "procedural.create_mesh_graph",
        {
            "graph_id": "building",
            "primitive": "cube",
            "operations": [
                {"operation": "mesh_extrude_faces", "faces": [1], "distance": 2.0},
                {"operation": "mesh_triangulate"},
            ],
        },
    )
    attached = _execute(viewer, "procedural.attach_to_scene", {"graph_id": "building"})
    transfer = _execute(
        viewer,
        "procedural.build_transfer_manifest",
        {"graph_id": "building", "target": "blender"},
    )

    assert mesh["cook"]["payload"]["meshes"]
    assert attached["attachment"]["last_cook"]["graph_fingerprint"]
    assert transfer["manifest"]["counts"]["meshes"] == 1
    assert not transfer["manifest"]["unsupported_nodes"]


def test_task_graph_payload_round_trips_and_cooks_in_viewer() -> None:
    graph = ProceduralTaskGraph("world_build")
    graph.add_node("tiles", fan_out=3, parameters={"attributes": {"kind": "tile"}})
    restored = ProceduralTaskGraph.from_dict(graph.to_dict())
    viewer = _ViewerHarness()

    result = _execute(
        viewer,
        "procedural.cook_task_graph",
        {"task_graph": restored.to_dict(), "initial_attributes": {"shot": "A"}},
    )

    assert restored.to_dict() == graph.to_dict()
    assert len(result["work_items"]) == 3
    assert all(item["attributes"]["shot"] == "A" for item in result["work_items"])


def test_procedural_workspace_round_trips_editable_graphs_and_scene_attachment() -> None:
    viewer = _ViewerHarness()
    _execute(viewer, "procedural.create_scatter_graph", {"graph_id": "scatter", "assets": ["Rock"]})
    _execute(viewer, "procedural.cook_graph", {"graph_id": "scatter"})
    _execute(viewer, "procedural.attach_to_scene", {"graph_id": "scatter"})
    task_graph = ProceduralTaskGraph("tasks")
    task_graph.add_node("build", fan_out=2)

    state = ProceduralWorkspaceState(
        graphs=viewer._procedural_graphs,
        task_graphs={"tasks": task_graph},
        active_graph_id="scatter",
        active_task_graph_id="tasks",
        scene_metadata=viewer._procedural_scene_metadata,
    )
    restored = ProceduralWorkspaceState.from_dict(state.to_dict())

    assert restored.graphs["scatter"].to_dict() == viewer._procedural_graphs["scatter"].to_dict()
    assert restored.task_graphs["tasks"].to_dict() == task_graph.to_dict()
    assert restored.active_graph_id == "scatter"
    assert restored.scene_metadata["metadata"]["procedural_graphs"]["scatter"]["last_cook"]["instance_count"] > 0


def test_terrain_generation_rejects_runaway_sample_counts() -> None:
    with pytest.raises(ValueError, match="4,000,000"):
        _execute(_ViewerHarness(), "procedural.generate_terrain", {"width": 2048, "depth": 2048})
