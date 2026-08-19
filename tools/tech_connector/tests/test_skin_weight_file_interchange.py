from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

import pytest

from tech_connector.game_engine.deformation.skinning_tool_service import (
    SkinClusterState,
    SkinInfluence,
    SkinVertexWeights,
    load_skin_weights_file,
    save_skin_weights_file,
    skin_topology_identity,
)


def _eight_influence_cluster() -> SkinClusterState:
    influences = tuple(SkinInfluence(f"Joint_{index}", (float(index), 0.0, 0.0)) for index in range(8))
    weights = {influence.name: float(index + 1) for index, influence in enumerate(influences)}
    total = sum(weights.values())
    return SkinClusterState(
        mesh_id="HeroMesh",
        influences=influences,
        vertex_weights=(SkinVertexWeights(0, {name: value / total for name, value in weights.items()}),),
        max_influences=8,
    )


def test_tcskin_file_preserves_eight_influences_and_round_trips(tmp_path: Path) -> None:
    vertices = [(0.0, 0.0, 0.0)]
    cluster = _eight_influence_cluster()
    path = tmp_path / "hero.tcskin"

    receipt = save_skin_weights_file(path, cluster, vertex_positions=vertices, faces=[])
    imported = load_skin_weights_file(
        path,
        target_mesh_id="HeroMeshCopy",
        expected_vertex_count=1,
        expected_topology_fingerprint=skin_topology_identity(vertices)["fingerprint"],
        available_influences=cluster.influence_names,
    )

    assert receipt["receipt"]["cluster_sha256"]
    assert imported.topology_matched is True
    assert imported.cluster.mesh_id == "HeroMeshCopy"
    assert imported.cluster.max_influences == 8
    assert len(imported.cluster.vertex_weights[0].weights) == 8
    assert sum(imported.cluster.vertex_weights[0].weights.values()) == pytest.approx(1.0)
    assert not list(tmp_path.glob("hero.*.tcskin"))


def test_tcskin_remaps_influences_without_losing_normalization(tmp_path: Path) -> None:
    cluster = _eight_influence_cluster()
    path = tmp_path / "remap.tcskin"
    save_skin_weights_file(path, cluster, vertex_positions=[(0.0, 0.0, 0.0)])
    remap = {name: f"Rig:{name}" for name in cluster.influence_names}

    imported = load_skin_weights_file(
        path,
        expected_vertex_count=1,
        available_influences=remap.values(),
        influence_map=remap,
    )

    assert imported.cluster.influence_names == tuple(remap.values())
    assert set(imported.cluster.vertex_weights[0].weights) == set(remap.values())
    assert sum(imported.cluster.vertex_weights[0].weights.values()) == pytest.approx(1.0)


def test_tcskin_rejects_corruption_wrong_topology_and_missing_influences(tmp_path: Path) -> None:
    cluster = _eight_influence_cluster()
    path = tmp_path / "strict.tcskin"
    save_skin_weights_file(path, cluster, vertex_positions=[(0.0, 0.0, 0.0)])

    with pytest.raises(ValueError, match="target mesh has 2"):
        load_skin_weights_file(path, expected_vertex_count=2)
    with pytest.raises(ValueError, match="missing skin influences"):
        load_skin_weights_file(path, expected_vertex_count=1, available_influences={"Joint_0"})

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cluster"]["vertex_weights"][0]["weights"]["Joint_0"] = 0.95
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_skin_weights_file(path)


def test_partial_tcskin_import_is_explicit_and_reports_dropped_data(tmp_path: Path) -> None:
    cluster = _eight_influence_cluster()
    path = tmp_path / "partial.tcskin"
    save_skin_weights_file(path, cluster, vertex_positions=[(0.0, 0.0, 0.0)])

    imported = load_skin_weights_file(
        path,
        expected_vertex_count=2,
        available_influences={"Joint_0", "Joint_1"},
        allow_partial=True,
    )

    assert imported.topology_matched is False
    assert len(imported.warnings) == 2
    assert set(imported.cluster.vertex_weights[0].weights) == {"Joint_0", "Joint_1"}
    assert sum(imported.cluster.vertex_weights[0].weights.values()) == pytest.approx(1.0)


def test_tcskin_20k_vertex_eight_influence_baseline(tmp_path: Path) -> None:
    seed = _eight_influence_cluster()
    weights = dict(seed.vertex_weights[0].weights)
    vertex_count = 20_000
    cluster = SkinClusterState(
        mesh_id=seed.mesh_id,
        influences=seed.influences,
        vertex_weights=tuple(SkinVertexWeights(index, weights) for index in range(vertex_count)),
        max_influences=8,
    )
    vertices = [(float(index), 0.0, 0.0) for index in range(vertex_count)]
    path = tmp_path / "baseline.tcskin"

    started = perf_counter()
    save_skin_weights_file(path, cluster, vertex_positions=vertices)
    imported = load_skin_weights_file(
        path,
        expected_vertex_count=vertex_count,
        available_influences=cluster.influence_names,
    )
    elapsed = perf_counter() - started

    assert imported.cluster.vertex_count == vertex_count
    assert path.stat().st_size > 1_000_000
    assert elapsed < 12.0
