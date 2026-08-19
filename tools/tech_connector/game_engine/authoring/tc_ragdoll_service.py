from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import Any, Mapping


@dataclass
class PhysicalAnimationState:
    blend: float = 0.0
    target_blend: float = 0.0
    recovery_seconds: float = 0.35
    muscle_strengths: dict[str, float] = field(default_factory=dict)
    pose_drive_strength: float = 0.8

    def step(self, dt: float) -> float:
        speed = float(dt) / max(1.0e-4, float(self.recovery_seconds))
        self.blend += max(-speed, min(speed, self.target_blend - self.blend))
        self.blend = max(0.0, min(1.0, self.blend))
        return self.blend

    def muscle_strength(self, joint_id: str) -> float:
        return max(0.0, min(1.0, float(self.muscle_strengths.get(str(joint_id), 1.0))))


def generate_ragdoll(
    rig_graph: Any,
    runtime_world: dict[str, Any],
    *,
    root_joint: str = "",
    density: float = 985.0,
    include_leaf_joints: bool = False,
) -> dict[str, Any]:
    """Generate editable rigid bodies and cone/hinge constraints from a TC skeleton."""

    joints = dict(getattr(rig_graph, "joints", {}) or {})
    if not joints:
        raise ValueError("The rig graph has no joints to convert into a ragdoll.")
    children: dict[str, list[str]] = {joint_id: [] for joint_id in joints}
    for joint_id, joint in joints.items():
        parent = str(joint.get("parent_id") or "")
        if parent in children:
            children[parent].append(joint_id)
    included = _descendants(children, root_joint) if root_joint else set(joints)
    entities = runtime_world.setdefault("entities", [])
    physics_joints = runtime_world.setdefault("physics_joints", [])
    existing_entities = {str(item.get("name") or "") for item in entities if isinstance(item, dict)}
    existing_constraints = {str(item.get("id") or "") for item in physics_joints if isinstance(item, dict)}
    created_entities: list[str] = []
    created_constraints: list[str] = []
    world_positions = _joint_world_positions(joints)
    for joint_id in sorted(included):
        child_ids = [child for child in children.get(joint_id, ()) if child in included]
        if not child_ids and not include_leaf_joints:
            continue
        entity_name = f"Ragdoll::{joint_id}"
        if entity_name not in existing_entities:
            start = world_positions[joint_id]
            end = world_positions[child_ids[0]] if child_ids else (start[0], start[1] + 0.1, start[2])
            length = max(0.05, math.dist(start, end))
            radius = max(0.025, min(0.25, length * 0.2))
            volume = math.pi * radius * radius * length
            entities.append({
                "name": entity_name,
                "transform": {"position": list(start)},
                "rigid_body": {"dynamic": True, "mass": max(0.01, volume * float(density)), "linear_damping": 0.08, "angular_damping": 0.18},
                "collider": {"shape": "capsule", "radius": radius, "half_height": max(0.0, length * 0.5 - radius)},
                "physical_animation": {"joint_id": joint_id, "pose_drive_strength": 0.8, "muscle_strength": 1.0},
            })
            existing_entities.add(entity_name)
            created_entities.append(entity_name)
        parent_id = str(joints[joint_id].get("parent_id") or "")
        parent_entity = f"Ragdoll::{parent_id}"
        constraint_id = f"RagdollJoint::{joint_id}"
        if parent_id in included and parent_entity in existing_entities and constraint_id not in existing_constraints:
            role = str(dict(joints[joint_id].get("attributes") or {}).get("joint_role") or joint_id).casefold()
            hinge = any(token in role for token in ("knee", "elbow"))
            physics_joints.append({
                "id": constraint_id, "type": "hinge" if hinge else "cone_twist",
                "first": parent_entity, "second": entity_name,
                "first_anchor": [0.0, 0.0, 0.0], "second_anchor": [0.0, 0.0, 0.0],
                "axis": [1.0, 0.0, 0.0], "minimum_limit": -5.0 if hinge else -35.0,
                "maximum_limit": 145.0 if hinge else 35.0, "limits_enabled": True,
                "stiffness": 0.9, "damping": 0.45, "collision_enabled": False, "enabled": True,
                "pose_drive": {"enabled": True, "strength": 0.8, "damping": 0.5},
            })
            existing_constraints.add(constraint_id)
            created_constraints.append(constraint_id)
    manifest = {
        "schema": "tech_connector.ragdoll.v1", "root_joint": root_joint,
        "body_names": sorted(name for name in existing_entities if name.startswith("Ragdoll::")),
        "constraint_ids": sorted(identifier for identifier in existing_constraints if identifier.startswith("RagdollJoint::")),
        "created_body_count": len(created_entities), "created_constraint_count": len(created_constraints),
        "animation_binding": {joint_id: f"Ragdoll::{joint_id}" for joint_id in included if f"Ragdoll::{joint_id}" in existing_entities},
    }
    runtime_world["ragdoll"] = deepcopy(manifest)
    return manifest


def blend_physical_animation(
    animated_pose: Mapping[str, Mapping[str, Any]],
    physics_pose: Mapping[str, Mapping[str, Any]],
    state: PhysicalAnimationState,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for joint_id in sorted(set(animated_pose) | set(physics_pose)):
        animated = dict(animated_pose.get(joint_id) or {})
        physical = dict(physics_pose.get(joint_id) or animated)
        amount = state.blend * state.muscle_strength(joint_id)
        result[joint_id] = {
            key: _blend_value(animated.get(key), physical.get(key), amount)
            for key in set(animated) | set(physical)
        }
    return result


def request_animation_recovery(state: PhysicalAnimationState, *, upright_error_degrees: float, speed: float) -> bool:
    ready = abs(float(upright_error_degrees)) <= 35.0 and abs(float(speed)) <= 1.5
    state.target_blend = 0.0 if ready else 1.0
    return ready


def _blend_value(first: Any, second: Any, amount: float) -> Any:
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return float(first) * (1.0 - amount) + float(second) * amount
    if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)) and len(first) == len(second):
        return [_blend_value(a, b, amount) for a, b in zip(first, second)]
    return deepcopy(second if amount >= 0.5 else first)


def _descendants(children: dict[str, list[str]], root: str) -> set[str]:
    if root not in children:
        raise KeyError(f"Unknown ragdoll root joint: {root}")
    result, pending = set(), [root]
    while pending:
        joint_id = pending.pop()
        if joint_id in result:
            continue
        result.add(joint_id)
        pending.extend(children.get(joint_id, ()))
    return result


def _joint_world_positions(joints: dict[str, dict[str, Any]]) -> dict[str, tuple[float, float, float]]:
    result: dict[str, tuple[float, float, float]] = {}
    pending = set(joints)
    while pending:
        progressed = False
        for joint_id in sorted(pending):
            joint = joints[joint_id]
            parent = str(joint.get("parent_id") or "")
            if parent and parent not in result:
                continue
            matrix = list(joint.get("bind_world_matrix") or joint.get("world_matrix") or joint.get("local_matrix") or ())
            local = tuple(float(matrix[index]) if len(matrix) > index else 0.0 for index in (12, 13, 14))
            parent_position = result.get(parent, (0.0, 0.0, 0.0))
            result[joint_id] = local if joint.get("bind_world_matrix") or joint.get("world_matrix") else tuple(parent_position[i] + local[i] for i in range(3))
            pending.remove(joint_id)
            progressed = True
            break
        if not progressed:
            raise ValueError("The rig joint hierarchy contains a cycle or missing parent.")
    return result


__all__ = ["PhysicalAnimationState", "blend_physical_animation", "generate_ragdoll", "request_animation_recovery"]
