from __future__ import annotations

from tech_connector.game_engine.authoring.tc_ragdoll_service import (
    PhysicalAnimationState, blend_physical_animation, generate_ragdoll, request_animation_recovery,
)
from tech_connector.game_engine.runtime.tc_physics_replay_service import (
    DeterministicPhysicsRecorder, hot_reload_joint_state, replication_packet,
)
from tech_connector.game_engine.runtime.tc_physics_stress_service import (
    STRESS_SCENARIOS, audit_physics_stress_scene, build_physics_stress_scene,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX


def _matrix(x: float, y: float, z: float) -> list[float]:
    value = list(IDENTITY_MATRIX)
    value[12:15] = [x, y, z]
    return value


def test_ragdoll_generation_and_physical_animation_recovery() -> None:
    graph = EditableRigGraph()
    root = graph.add_joint("Root", joint_id="Root", local_matrix=_matrix(0, 1, 0))
    hip = graph.add_joint("Hip", parent_id=root, joint_id="Hip", local_matrix=_matrix(0, 1, 0))
    knee = graph.add_joint("Knee", parent_id=hip, joint_id="Knee", local_matrix=_matrix(0, -1, 0))
    graph.nodes[knee].setdefault("attributes", {})["joint_role"] = "LeftKnee"
    graph.add_joint("Ankle", parent_id=knee, joint_id="Ankle", local_matrix=_matrix(0, -1, 0))
    runtime: dict = {}
    manifest = generate_ragdoll(graph, runtime)
    assert manifest["created_body_count"] == 3
    assert any(item["type"] == "hinge" for item in runtime["physics_joints"])
    state = PhysicalAnimationState(blend=0.5, muscle_strengths={"Hip": 0.5})
    pose = blend_physical_animation({"Hip": {"position": [0, 0, 0]}}, {"Hip": {"position": [4, 0, 0]}}, state)
    assert pose["Hip"]["position"][0] == 1.0
    assert request_animation_recovery(state, upright_error_degrees=10, speed=0.2) is True
    assert state.step(1.0) == 0.0


def test_record_rollback_replication_and_compatible_hot_reload() -> None:
    recorder = DeterministicPhysicsRecorder(capacity=4)
    first = recorder.record(1, {"x": 1}, [{"move": 1}])
    second = recorder.record(2, {"x": 2}, [{"move": 1}])
    assert recorder.rollback(1) == {"x": 1}
    assert recorder.verify() == []
    assert replication_packet(second, first)["baseline_frame"] == 1
    current = {"physics_revision": 4, "physics_joints": [{
        "id": "hinge", "type": "hinge", "first": "A", "second": "B", "broken": True,
        "accumulated_angular_impulse": [1, 2, 3],
    }]}
    updated = hot_reload_joint_state(current, [{"id": "hinge", "type": "hinge", "first": "A", "second": "B", "damping": 0.8}])
    assert updated["physics_revision"] == 5
    assert updated["physics_joints"][0]["broken"] is True


def test_all_stress_scenarios_produce_valid_constraint_graphs() -> None:
    for scenario in STRESS_SCENARIOS:
        world = build_physics_stress_scene(scenario, 1000)
        audit = audit_physics_stress_scene(world)
        assert audit["ready"] is True
        assert audit["constraint_count"] == 1000
