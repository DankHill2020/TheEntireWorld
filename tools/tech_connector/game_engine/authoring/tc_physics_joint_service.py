from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, MutableMapping


PHYSICS_JOINT_TYPES = (
    "fixed", "ball", "hinge", "slider", "distance", "spring", "cone_twist", "six_dof",
)

PHYSICS_JOINT_PRESETS: dict[str, dict[str, Any]] = {
    "weld": {"type": "fixed", "stiffness": 1.0, "damping": 0.35},
    "door_hinge": {
        "type": "hinge", "axis": [0.0, 1.0, 0.0], "minimum_limit": -110.0,
        "maximum_limit": 110.0, "limits_enabled": True, "damping": 0.2,
    },
    "ragdoll": {
        "type": "cone_twist", "axis": [1.0, 0.0, 0.0], "minimum_limit": -35.0,
        "maximum_limit": 35.0, "limits_enabled": True, "stiffness": 0.85, "damping": 0.4,
    },
    "piston": {
        "type": "slider", "axis": [1.0, 0.0, 0.0], "minimum_limit": 0.0,
        "maximum_limit": 1.0, "limits_enabled": True, "damping": 0.25,
    },
    "suspension": {
        "type": "spring", "minimum_limit": 0.5, "maximum_limit": 0.5,
        "limits_enabled": True, "stiffness": 0.65, "damping": 0.55,
    },
    "tether": {
        "type": "distance", "minimum_limit": 1.0, "maximum_limit": 1.0,
        "limits_enabled": True, "stiffness": 1.0, "damping": 0.15,
    },
}

_SIX_DOF_VECTOR_KEYS = (
    "linear_lower_limit", "linear_upper_limit", "angular_lower_limit", "angular_upper_limit",
    "linear_spring_stiffness", "linear_spring_damping", "angular_spring_stiffness", "angular_spring_damping",
    "linear_drive_velocity", "angular_drive_velocity", "linear_drive_maximum_force", "angular_drive_maximum_force",
)
_VECTOR_KEYS = ("first_anchor", "second_anchor", "axis", *_SIX_DOF_VECTOR_KEYS)
_NONNEGATIVE_KEYS = ("damping", "motor_maximum_force", "break_force", "break_torque")
_SETTING_KEYS = {
    "type", *_VECTOR_KEYS, "minimum_limit", "maximum_limit", "limits_enabled", "stiffness", "damping",
    "motor_enabled", "motor_target_velocity", "motor_maximum_force", "break_force", "break_torque",
    "collision_enabled", "enabled",
}


def _finite_vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain exactly three numbers.")
    result = [float(component) for component in value]
    if not all(math.isfinite(component) for component in result):
        raise ValueError(f"{label} must contain only finite numbers.")
    return result


def validate_physics_joint(joint: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized joint dictionary or raise a user-facing contract error."""

    result = dict(joint)
    unknown = sorted(set(result) - ({"id", "first", "second"} | _SETTING_KEYS))
    if unknown:
        raise ValueError("Unknown physics joint properties: " + ", ".join(unknown))
    kind = str(result.get("type") or "fixed").casefold().replace("-", "_")
    if kind not in PHYSICS_JOINT_TYPES:
        raise ValueError(f"Unsupported physics joint type: {kind}")
    result["type"] = kind
    for key in _VECTOR_KEYS:
        result[key] = _finite_vector(result.get(key, [1.0, 0.0, 0.0] if key == "axis" else [0.0, 0.0, 0.0]), key)
    axis_length = math.sqrt(sum(component * component for component in result["axis"]))
    if axis_length <= 1.0e-8:
        raise ValueError("axis must have a non-zero length.")
    result["axis"] = [component / axis_length for component in result["axis"]]
    stiffness = float(result.get("stiffness", 1.0))
    if not math.isfinite(stiffness) or not 0.0 <= stiffness <= 1.0:
        raise ValueError("stiffness must be between 0 and 1.")
    result["stiffness"] = stiffness
    for key in _NONNEGATIVE_KEYS:
        value = float(result.get(key, 0.1 if key == "damping" else 0.0))
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{key} must be a finite number greater than or equal to 0.")
        result[key] = value
    minimum = float(result.get("minimum_limit", 0.0))
    maximum = float(result.get("maximum_limit", 0.0))
    if not math.isfinite(minimum) or not math.isfinite(maximum):
        raise ValueError("Joint limits must be finite numbers.")
    result["minimum_limit"], result["maximum_limit"] = sorted((minimum, maximum))
    for lower_key, upper_key in (("linear_lower_limit", "linear_upper_limit"), ("angular_lower_limit", "angular_upper_limit")):
        lower, upper = result[lower_key], result[upper_key]
        ordered = [sorted((lower[index], upper[index])) for index in range(3)]
        result[lower_key] = [item[0] for item in ordered]
        result[upper_key] = [item[1] for item in ordered]
    for key in ("linear_spring_stiffness", "linear_spring_damping", "angular_spring_stiffness",
                "angular_spring_damping", "linear_drive_maximum_force", "angular_drive_maximum_force"):
        if any(value < 0.0 for value in result[key]):
            raise ValueError(f"{key} values must be greater than or equal to 0.")
    return result


def create_physics_joint(
    runtime_world: MutableMapping[str, Any],
    joint_id: str,
    first: str,
    second: str,
    *,
    joint_type: str = "fixed",
    preset: str = "",
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or replace an engine physics joint without touching the rig skeleton."""

    identifier = str(joint_id).strip()
    first_name, second_name = str(first).strip(), str(second).strip()
    if not identifier:
        raise ValueError("Physics joint id cannot be empty.")
    if not first_name or not second_name or first_name == second_name:
        raise ValueError("A physics joint must connect two different entity names.")
    preset_key = str(preset).casefold()
    if preset_key and preset_key not in PHYSICS_JOINT_PRESETS:
        raise ValueError(f"Unknown physics joint preset: {preset}")
    values = deepcopy(PHYSICS_JOINT_PRESETS.get(preset_key, {}))
    values.update(dict(settings or {}))
    kind = str(values.pop("type", joint_type)).casefold().replace("-", "_")
    joint = {
        "id": identifier,
        "type": kind,
        "first": first_name,
        "second": second_name,
        "first_anchor": [0.0, 0.0, 0.0],
        "second_anchor": [0.0, 0.0, 0.0],
        "axis": [1.0, 0.0, 0.0],
        "stiffness": 1.0,
        "damping": 0.1,
        "collision_enabled": False,
        "enabled": True,
    }
    joint.update(values)
    joint = validate_physics_joint(joint)
    joints = runtime_world.setdefault("physics_joints", [])
    if not isinstance(joints, list):
        raise TypeError("runtime_world.physics_joints must be a list.")
    joints[:] = [item for item in joints if not isinstance(item, dict) or str(item.get("id")) != identifier]
    joints.append(joint)
    return joint


def remove_physics_joint(runtime_world: MutableMapping[str, Any], joint_id: str) -> bool:
    joints = runtime_world.get("physics_joints")
    if not isinstance(joints, list):
        return False
    original_count = len(joints)
    joints[:] = [item for item in joints if not isinstance(item, dict) or str(item.get("id")) != str(joint_id)]
    return len(joints) != original_count


__all__ = [
    "PHYSICS_JOINT_PRESETS", "PHYSICS_JOINT_TYPES", "create_physics_joint", "remove_physics_joint",
    "validate_physics_joint",
]
