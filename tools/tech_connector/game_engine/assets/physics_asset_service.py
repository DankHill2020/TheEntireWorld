"""First-class character physics and reusable constraint asset contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from types import SimpleNamespace
from typing import Any, Mapping

from tech_connector.game_engine.authoring.tc_physics_joint_service import (
    PHYSICS_JOINT_PRESETS,
    create_physics_joint,
    validate_physics_joint,
)
from tech_connector.game_engine.authoring.tc_ragdoll_service import generate_ragdoll


PHYSICS_BODY_SHAPES = ("sphere", "capsule", "box", "convex")
RAGDOLL_PRESETS: dict[str, dict[str, float]] = {
    "balanced": {"density": 985.0, "linear_damping": 0.08, "angular_damping": 0.18, "pose_drive_strength": 0.80},
    "light": {"density": 650.0, "linear_damping": 0.06, "angular_damping": 0.14, "pose_drive_strength": 0.72},
    "heavy": {"density": 1250.0, "linear_damping": 0.12, "angular_damping": 0.24, "pose_drive_strength": 0.88},
    "passive": {"density": 985.0, "linear_damping": 0.05, "angular_damping": 0.10, "pose_drive_strength": 0.0},
}


@dataclass(frozen=True)
class PhysicsAuthoringIssue:
    severity: str
    code: str
    message: str
    fix: str = ""


@dataclass(frozen=True)
class PhysicsAssetAutoSetupReceipt:
    body_count: int
    constraint_count: int
    bodies: list[dict[str, Any]]
    constraints: list[dict[str, Any]]
    animation_binding: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ragdoll_preset(name: str) -> dict[str, Any]:
    key = str(name).strip().casefold()
    if key not in RAGDOLL_PRESETS:
        raise KeyError(f"Unknown ragdoll preset: {name}")
    return {"preset": key, **RAGDOLL_PRESETS[key]}


def automatic_physics_asset(
    joints: Mapping[str, Mapping[str, Any]],
    *,
    root_joint: str = "",
    preset: str = "balanced",
    include_leaf_joints: bool = False,
) -> PhysicsAssetAutoSetupReceipt:
    """Generate editable bodies and constraints through the runtime ragdoll path."""

    settings = ragdoll_preset(preset)
    rig_graph = SimpleNamespace(joints={str(key): dict(value) for key, value in joints.items()})
    world: dict[str, Any] = {"entities": [], "physics_joints": []}
    manifest = generate_ragdoll(
        rig_graph,
        world,
        root_joint=str(root_joint),
        density=float(settings["density"]),
        include_leaf_joints=bool(include_leaf_joints),
    )
    # The legacy runtime helper creates bodies and constraints in one sorted pass.
    # Complete parent links after every body exists so name ordering cannot drop joints.
    body_names = {str(value.get("name") or "") for value in world["entities"]}
    existing_constraint_ids = {str(value.get("id") or "") for value in world["physics_joints"]}
    for joint_id, joint in rig_graph.joints.items():
        child_body = f"Ragdoll::{joint_id}"
        parent_id = str(joint.get("parent_id") or "")
        parent_body = f"Ragdoll::{parent_id}"
        constraint_id = f"RagdollJoint::{joint_id}"
        if child_body not in body_names or parent_body not in body_names or constraint_id in existing_constraint_ids:
            continue
        role = str(dict(joint.get("attributes") or {}).get("joint_role") or joint_id).casefold()
        hinge = any(token in role for token in ("knee", "elbow"))
        created = create_physics_joint(
            world, constraint_id, parent_body, child_body, preset="ragdoll", settings={
                "type": "hinge" if hinge else "cone_twist",
                "minimum_limit": -5.0 if hinge else -35.0,
                "maximum_limit": 145.0 if hinge else 35.0,
            },
        )
        created["pose_drive"] = {"enabled": True, "strength": 0.8, "damping": 0.5}
        existing_constraint_ids.add(constraint_id)
    bodies: list[dict[str, Any]] = []
    for entity in world["entities"]:
        rigid_body = dict(entity.get("rigid_body") or {})
        collider = dict(entity.get("collider") or {})
        physical_animation = dict(entity.get("physical_animation") or {})
        rigid_body["linear_damping"] = float(settings["linear_damping"])
        rigid_body["angular_damping"] = float(settings["angular_damping"])
        physical_animation["pose_drive_strength"] = float(settings["pose_drive_strength"])
        bodies.append({
            "id": str(entity.get("name") or ""),
            "bone": str(physical_animation.get("joint_id") or ""),
            "transform": dict(entity.get("transform") or {}),
            "rigid_body": rigid_body,
            "collider": collider,
            "physical_animation": physical_animation,
        })
    constraints = [dict(value) for value in world["physics_joints"]]
    return PhysicsAssetAutoSetupReceipt(
        len(bodies), len(constraints), bodies, constraints,
        dict(manifest.get("animation_binding") or {}),
    )


def constraint_from_preset(
    preset: str,
    *,
    constraint_id: str = "Constraint",
    first_body: str,
    second_body: str,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    world: dict[str, Any] = {"physics_joints": []}
    return create_physics_joint(
        world, constraint_id, first_body, second_body,
        preset=str(preset), settings=dict(settings or {}),
    )


def validate_physics_asset_properties(properties: Mapping[str, Any]) -> tuple[PhysicsAuthoringIssue, ...]:
    values = dict(properties or {})
    issues: list[PhysicsAuthoringIssue] = []
    if not values.get("skeleton_id"):
        issues.append(PhysicsAuthoringIssue("error", "missing_skeleton", "Choose the Skeleton this Physics Asset follows.", "Assign Skeleton."))
    bodies = list(values.get("bodies") or ())
    constraints = list(values.get("constraints") or ())
    if not bodies:
        issues.append(PhysicsAuthoringIssue("error", "missing_bodies", "The Physics Asset has no collision bodies.", "Run Auto Generate or add a body."))
    body_ids: set[str] = set()
    bones: set[str] = set()
    for index, raw in enumerate(bodies):
        body = dict(raw or {})
        body_id = str(body.get("id") or "").strip()
        bone = str(body.get("bone") or "").strip()
        if not body_id or body_id in body_ids:
            issues.append(PhysicsAuthoringIssue("error", "invalid_body_id", f"Body {index + 1} has an empty or duplicate ID."))
        body_ids.add(body_id)
        if not bone or bone in bones:
            issues.append(PhysicsAuthoringIssue("error", "invalid_body_bone", f"Body '{body_id or index + 1}' has an empty or duplicate bone binding."))
        bones.add(bone)
        collider = dict(body.get("collider") or {})
        shape = str(collider.get("shape") or "capsule").casefold()
        if shape not in PHYSICS_BODY_SHAPES:
            issues.append(PhysicsAuthoringIssue("error", "invalid_body_shape", f"Body '{body_id}' uses unsupported shape '{shape}'."))
        mass = float(dict(body.get("rigid_body") or {}).get("mass", 0.0))
        if not math.isfinite(mass) or mass <= 0.0:
            issues.append(PhysicsAuthoringIssue("error", "invalid_body_mass", f"Body '{body_id}' must have positive finite mass."))
    constraint_ids: set[str] = set()
    for index, raw in enumerate(constraints):
        constraint = dict(raw or {})
        identifier = str(constraint.get("id") or "").strip()
        if not identifier or identifier in constraint_ids:
            issues.append(PhysicsAuthoringIssue("error", "invalid_constraint_id", f"Constraint {index + 1} has an empty or duplicate ID."))
        constraint_ids.add(identifier)
        missing = [str(constraint.get(key) or "") for key in ("first", "second") if str(constraint.get(key) or "") not in body_ids]
        if missing:
            issues.append(PhysicsAuthoringIssue("error", "missing_constraint_body", f"Constraint '{identifier}' references missing body: {', '.join(missing)}."))
        try:
            validate_physics_joint({key: value for key, value in constraint.items() if key != "pose_drive"})
        except (TypeError, ValueError) as exc:
            issues.append(PhysicsAuthoringIssue("error", "invalid_constraint", f"Constraint '{identifier}': {exc}"))
    return tuple(issues)


def validate_constraint_properties(properties: Mapping[str, Any]) -> tuple[PhysicsAuthoringIssue, ...]:
    values = dict(properties or {})
    joint = dict(values.get("joint") or values)
    joint.setdefault("id", str(values.get("constraint_id") or "Constraint"))
    joint.setdefault("first", str(values.get("first_body") or ""))
    joint.setdefault("second", str(values.get("second_body") or ""))
    try:
        validate_physics_joint(joint)
    except (TypeError, ValueError) as exc:
        return (PhysicsAuthoringIssue("error", "invalid_constraint", str(exc)),)
    return ()


def compile_physics_asset_payload(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    values = dict(properties or {})
    errors = [issue.message for issue in validate_physics_asset_properties(values) if issue.severity == "error"]
    if errors:
        raise ValueError("Physics Asset cannot be cooked: " + "; ".join(errors))
    payload = {
        "schema": "tech_connector.cooked_physics_asset.v1",
        "platform": str(platform), "quality": str(quality),
        "skeletal_mesh_id": str(values.get("skeletal_mesh_id") or ""),
        "skeleton_id": str(values["skeleton_id"]),
        "bodies": list(values.get("bodies") or ()),
        "constraints": [
            validate_physics_joint({key: item for key, item in value.items() if key != "pose_drive"})
            | ({"pose_drive": dict(value.get("pose_drive") or {})} if value.get("pose_drive") else {})
            for value in values.get("constraints") or ()
        ],
        "collision_pairs": list(values.get("collision_pairs") or ()),
        "physical_animation": dict(values.get("physical_animation") or {}),
        "solver": dict(values.get("solver") or {}),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compile_constraint_payload(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    values = dict(properties or {})
    joint = dict(values.get("joint") or values)
    joint.setdefault("id", str(values.get("constraint_id") or "Constraint"))
    joint.setdefault("first", str(values.get("first_body") or ""))
    joint.setdefault("second", str(values.get("second_body") or ""))
    normalized = validate_physics_joint(joint)
    return json.dumps({
        "schema": "tech_connector.cooked_physics_constraint.v1",
        "platform": str(platform), "quality": str(quality), "joint": normalized,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "PHYSICS_BODY_SHAPES", "PHYSICS_JOINT_PRESETS", "RAGDOLL_PRESETS",
    "PhysicsAuthoringIssue", "PhysicsAssetAutoSetupReceipt", "automatic_physics_asset",
    "compile_constraint_payload", "compile_physics_asset_payload", "constraint_from_preset",
    "ragdoll_preset", "validate_constraint_properties", "validate_physics_asset_properties",
]
