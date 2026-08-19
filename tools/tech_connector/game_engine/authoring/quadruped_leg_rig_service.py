"""Native four-joint quadruped leg built from two portable RP IK stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np

from tech_connector.game_engine.authoring.rig_evaluation_service import evaluate_rig_graph


QUADRUPED_LEG_SCHEMA = "tech_connector.quadruped_leg_rig.v1"


@dataclass(frozen=True)
class QuadrupedLegRigResult:
    module: str
    joint_chain: tuple[str, str, str, str]
    foot_control: str
    pole_control: str
    hock_target: str
    solver_ids: tuple[str, str]
    schema: str = QUADRUPED_LEG_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_quadruped_leg_rig(
    graph: Any,
    *,
    joint_chain: Sequence[str],
    module: str = "quadruped_leg",
    foot_control: str = "",
    pole_control: str = "",
    pole_distance: float = 5.0,
    gait_phase: float = 0.0,
    stride_scale: float = 1.0,
) -> QuadrupedLegRigResult:
    chain = tuple(str(value) for value in joint_chain)
    if len(chain) != 4:
        raise ValueError("A quadruped leg requires hip, knee, hock, and ankle joints.")
    for index, joint_id in enumerate(chain):
        if joint_id not in getattr(graph, "joints", {}):
            raise KeyError(f"Unknown quadruped joint: {joint_id}")
        if index and str(graph.joints[joint_id].get("parent_id") or "") != chain[index - 1]:
            raise ValueError("Quadruped joints must form a direct hip -> knee -> hock -> ankle hierarchy.")
    module_id = str(module or "quadruped_leg")
    evaluated = evaluate_rig_graph(graph)
    if not evaluated.ok:
        raise ValueError("Cannot build quadruped leg from an invalid rig graph: " + "; ".join(evaluated.errors[:4]))
    worlds = [np.asarray(evaluated.world_matrices[joint_id], dtype=np.float64).reshape((4, 4)) for joint_id in chain]

    foot = str(foot_control or f"{module_id}_foot_ctrl")
    if foot not in graph.nodes:
        graph.add_node(
            foot,
            "dag.control",
            node_id=foot,
            attributes={
                "matrix": worlds[3].reshape(-1).tolist(),
                "control_shape": "foot",
                "foot_roll": 0.0,
                "bank": 0.0,
                "toe_roll": 0.0,
                "gait_phase": float(gait_phase) % 1.0,
                "stride_scale": max(0.0, float(stride_scale)),
                "rig_module": module_id,
            },
        )
    pole = str(pole_control or f"{module_id}_pole_ctrl")
    if pole not in graph.nodes:
        pole_matrix = np.eye(4, dtype=np.float64)
        hip, knee, hock = (world[3, :3] for world in worlds[:3])
        bend_normal = np.cross(knee - hip, hock - knee)
        if float(np.linalg.norm(bend_normal)) <= 1.0e-8:
            bend_normal = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
        bend_normal /= max(1.0e-12, float(np.linalg.norm(bend_normal)))
        pole_matrix[3, :3] = knee + bend_normal * max(0.001, float(pole_distance))
        graph.add_node(
            pole,
            "dag.control",
            node_id=pole,
            attributes={"matrix": pole_matrix.reshape(-1).tolist(), "control_shape": "diamond", "rig_module": module_id},
        )

    hock_target = f"{module_id}_hock_target"
    if hock_target in graph.nodes:
        raise ValueError(f"Quadruped hock target already exists: {hock_target}")
    if foot in evaluated.world_matrices:
        foot_world = np.asarray(evaluated.world_matrices[foot], dtype=np.float64).reshape((4, 4))
    else:
        foot_world = np.asarray((graph.nodes[foot].get("attributes") or {}).get("matrix"), dtype=np.float64).reshape((4, 4))
    local_hock = worlds[2] @ np.linalg.inv(foot_world)
    graph.add_node(
        hock_target,
        "dag.transform",
        parent_id=foot,
        node_id=hock_target,
        attributes={"matrix": local_hock.reshape(-1).tolist(), "hidden": True, "rig_module": module_id},
    )
    upper_solver = graph.add_ik_solver(
        chain[0], chain[1], chain[2], hock_target,
        pole_node_id=pole,
        solver_id=f"{module_id}_upper_ik",
        settings={"rig_module": module_id, "quadruped_stage": "upper", "gait_phase": float(gait_phase) % 1.0},
    )
    lower_solver = graph.add_ik_solver(
        chain[1], chain[2], chain[3], foot,
        pole_node_id=pole,
        solver_id=f"{module_id}_lower_ik",
        settings={"rig_module": module_id, "quadruped_stage": "hock", "foot_roll_source": foot},
    )
    return QuadrupedLegRigResult(module_id, chain, foot, pole, hock_target, (upper_solver, lower_solver))


__all__ = ["QUADRUPED_LEG_SCHEMA", "QuadrupedLegRigResult", "create_quadruped_leg_rig"]
