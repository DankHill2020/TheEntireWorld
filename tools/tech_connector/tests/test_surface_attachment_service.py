from __future__ import annotations

import pytest

from tech_connector.game_engine.authoring.rig_evaluation_service import (
    calculate_constraint_offset_matrix,
    evaluate_rig_graph,
)
from tech_connector.game_engine.authoring.surface_attachment_service import (
    create_surface_attachment,
    update_surface_attachment,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX


def _matrix(x: float, y: float, z: float) -> list[float]:
    value = list(IDENTITY_MATRIX)
    value[12:15] = [x, y, z]
    return value


def test_barycentric_surface_attachment_updates_from_stable_vertex_ids() -> None:
    vertices = [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (0.0, 3.0, 0.0)]
    attachment = create_surface_attachment(
        "Mesh",
        vertices,
        [(0, 1, 2)],
        face_index=0,
        barycentric=(0.5, 0.25, 0.25),
    )
    deformed = update_surface_attachment(attachment, [(0.0, 0.0, 2.0), (3.0, 0.0, 2.0), (0.0, 3.0, 2.0)])

    assert attachment.position == pytest.approx((0.75, 0.75, 0.0))
    assert attachment.normal == pytest.approx((0.0, 0.0, 1.0))
    assert deformed.position == pytest.approx((0.75, 0.75, 2.0))
    assert deformed.face_index == attachment.face_index
    assert deformed.triangle_vertex_ids == attachment.triangle_vertex_ids


def test_normal_constraint_evaluates_surface_frame_and_round_trips() -> None:
    graph = EditableRigGraph()
    target = graph.add_node("Control", "dag.control", node_id="Control", attributes={"matrix": _matrix(5.0, 5.0, 5.0)})
    attachment = create_surface_attachment(
        "Mesh",
        [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (0.0, 3.0, 0.0)],
        [(0, 1, 2)],
        face_index=0,
    )
    constraint = graph.add_constraint(
        "normal",
        ["Mesh"],
        target,
        settings={"attachment": attachment.to_dict()},
    )

    evaluated = evaluate_rig_graph(graph)
    restored = EditableRigGraph.from_dict(graph.to_dict())
    restored_evaluation = evaluate_rig_graph(restored)

    assert evaluated.ok, evaluated.errors
    assert evaluated.world_matrices[target][12:15] == pytest.approx((1.0, 1.0, 0.0))
    assert evaluated.world_matrices[target][4:7] == pytest.approx((0.0, 0.0, 1.0))
    assert restored.constraints[constraint]["settings"]["attachment"]["barycentric"] == pytest.approx([1 / 3] * 3)
    assert restored_evaluation.world_matrices[target] == pytest.approx(evaluated.world_matrices[target])


def test_surface_constraint_maintain_offset_preserves_current_pose() -> None:
    graph = EditableRigGraph()
    target = graph.add_node("Control", "dag.control", node_id="Control", attributes={"matrix": _matrix(5.0, 5.0, 5.0)})
    before = evaluate_rig_graph(graph).world_matrices[target]
    attachment = create_surface_attachment(
        "Mesh",
        [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (0.0, 3.0, 0.0)],
        [(0, 1, 2)],
        face_index=0,
    )
    offset = calculate_constraint_offset_matrix(before, list(attachment.matrix))
    graph.add_constraint(
        "normal",
        ["Mesh"],
        target,
        settings={"attachment": attachment.to_dict(), "maintain_offset": True, "offset_matrix": offset},
    )

    after = evaluate_rig_graph(graph)

    assert after.ok, after.errors
    assert after.world_matrices[target] == pytest.approx(before)
