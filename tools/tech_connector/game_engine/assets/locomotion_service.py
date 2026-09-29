"""Reusable character-locomotion controller presets and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from typing import Any, Mapping


LOCOMOTION_CONTROLLER_SCHEMA = "tech_connector.locomotion_controller.v1"


@dataclass(frozen=True)
class LocomotionIssue:
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


_PRESETS: dict[str, dict[str, Any]] = {
    "third_person": {
        "movement_mode": "free_3d", "camera_mode": "third_person",
        "camera": {"offset": [0.0, 3.2, -7.5], "look_height": 1.15, "follow_smoothing": 14.0},
    },
    "first_person": {
        "movement_mode": "free_3d", "camera_mode": "first_person",
        "camera": {"offset": [0.0, 0.7, 0.05], "look_height": 0.7, "follow_smoothing": 28.0},
    },
    "side_scroller": {
        "movement_mode": "plane_2d", "camera_mode": "side",
        "camera": {"offset": [0.0, 2.2, -12.0], "look_height": 0.8, "follow_smoothing": 12.0},
    },
    "fighting": {
        "movement_mode": "plane_2d", "camera_mode": "fighting",
        "camera": {"offset": [0.0, 2.4, -11.0], "look_height": 0.9, "follow_smoothing": 10.0},
    },
}


def locomotion_preset(preset: str = "third_person", *, movement_mode: str = "") -> dict[str, Any]:
    key = str(preset).strip().casefold().replace("-", "_")
    if key not in _PRESETS:
        raise KeyError(f"Unknown locomotion preset: {preset}")
    selected = deepcopy(_PRESETS[key])
    if movement_mode:
        selected["movement_mode"] = str(movement_mode)
    states = [
        {"id": "idle", "clip_slot": "idle", "loop": True},
        {"id": "walk_run", "blend_space": "grounded_speed_direction", "loop": True},
        {"id": "jump_start", "clip_slot": "jump_start", "loop": False},
        {"id": "airborne", "clip_slot": "jump_loop", "loop": True},
        {"id": "land", "clip_slot": "land", "loop": False},
        {"id": "crouch_idle", "clip_slot": "crouch_idle", "loop": True},
        {"id": "crouch_move", "clip_slot": "crouch_walk", "loop": True},
    ]
    transitions = [
        {"from": "idle", "to": "walk_run", "condition": "speed > 0.1", "blend_seconds": 0.16},
        {"from": "walk_run", "to": "idle", "condition": "speed <= 0.1", "blend_seconds": 0.18},
        {"from": "idle", "to": "jump_start", "condition": "jump_triggered", "blend_seconds": 0.05},
        {"from": "walk_run", "to": "jump_start", "condition": "jump_triggered", "blend_seconds": 0.05},
        {"from": "jump_start", "to": "airborne", "condition": "vertical_speed <= 0 or state_time >= 0.18", "blend_seconds": 0.08},
        {"from": "airborne", "to": "land", "condition": "is_grounded", "blend_seconds": 0.08},
        {"from": "land", "to": "idle", "condition": "speed <= 0.1 and state_time >= 0.12", "blend_seconds": 0.1},
        {"from": "land", "to": "walk_run", "condition": "speed > 0.1 and state_time >= 0.08", "blend_seconds": 0.1},
        {"from": "idle", "to": "crouch_idle", "condition": "is_crouched", "blend_seconds": 0.14},
        {"from": "walk_run", "to": "crouch_move", "condition": "is_crouched", "blend_seconds": 0.14},
        {"from": "crouch_idle", "to": "crouch_move", "condition": "speed > 0.1", "blend_seconds": 0.12},
        {"from": "crouch_move", "to": "crouch_idle", "condition": "speed <= 0.1", "blend_seconds": 0.12},
        {"from": "crouch_idle", "to": "idle", "condition": "not is_crouched", "blend_seconds": 0.16},
        {"from": "crouch_move", "to": "walk_run", "condition": "not is_crouched", "blend_seconds": 0.16},
    ]
    return {
        "schema": LOCOMOTION_CONTROLLER_SCHEMA,
        "preset": key,
        "movement": {
            "mode": selected["movement_mode"], "maximum_speed": 5.5,
            "walk_speed": 2.2, "run_speed": 5.5, "acceleration": 30.0,
            "deceleration": 38.0, "air_control": 0.35, "jump_impulse": 6.5,
            "gravity_scale": 1.0, "step_height": 0.35, "slope_limit_degrees": 48.0,
            "coyote_time_seconds": 0.1, "jump_buffer_seconds": 0.12,
            "orient_to_movement": selected["camera_mode"] not in {"first_person", "fighting"},
            "locked_axis": "z" if selected["movement_mode"] == "plane_2d" else "",
        },
        "camera": {"mode": selected["camera_mode"], **selected["camera"]},
        "parameters": {
            "speed": {"type": "float", "default": 0.0},
            "direction": {"type": "float", "default": 0.0},
            "vertical_speed": {"type": "float", "default": 0.0},
            "is_grounded": {"type": "bool", "default": True},
            "jump_triggered": {"type": "trigger"},
            "is_sprinting": {"type": "bool", "default": False},
            "is_crouched": {"type": "bool", "default": False},
            "turn_delta": {"type": "float", "default": 0.0},
        },
        "animation_slots": {
            "idle": "builtin://locomotion/humanoid/idle",
            "walk_forward": "builtin://locomotion/humanoid/walk_forward",
            "walk_backward": "builtin://locomotion/humanoid/walk_backward",
            "walk_forward_left": "builtin://locomotion/humanoid/walk_forward_left",
            "walk_forward_right": "builtin://locomotion/humanoid/walk_forward_right",
            "walk_backward_left": "builtin://locomotion/humanoid/walk_backward_left",
            "walk_backward_right": "builtin://locomotion/humanoid/walk_backward_right",
            "strafe_left": "builtin://locomotion/humanoid/strafe_left",
            "strafe_right": "builtin://locomotion/humanoid/strafe_right",
            "run_forward": "builtin://locomotion/humanoid/run_forward",
            "jump_start": "builtin://locomotion/humanoid/jump_start",
            "jump_loop": "builtin://locomotion/humanoid/jump_loop",
            "land": "builtin://locomotion/humanoid/land",
            "start_forward": "builtin://locomotion/humanoid/start_forward",
            "stop_forward": "builtin://locomotion/humanoid/stop_forward",
            "pivot_left": "builtin://locomotion/humanoid/pivot_left",
            "pivot_right": "builtin://locomotion/humanoid/pivot_right",
            "crouch_idle": "builtin://locomotion/humanoid/crouch_idle",
            "crouch_walk": "builtin://locomotion/humanoid/crouch_walk",
            "fall": "builtin://locomotion/humanoid/fall",
        },
        "blend_spaces": [{
            "id": "grounded_speed_direction", "axes": [
                {"parameter": "speed", "minimum": 0.0, "maximum": 5.5},
                {"parameter": "direction", "minimum": -180.0, "maximum": 180.0},
            ],
            "samples": [
                {"slot": "idle", "speed": 0.0, "direction": 0.0},
                {"slot": "walk_forward", "speed": 2.2, "direction": 0.0},
                {"slot": "walk_backward", "speed": 2.2, "direction": 180.0},
                {"slot": "walk_forward_left", "speed": 2.2, "direction": -45.0},
                {"slot": "walk_forward_right", "speed": 2.2, "direction": 45.0},
                {"slot": "strafe_left", "speed": 2.2, "direction": -90.0},
                {"slot": "strafe_right", "speed": 2.2, "direction": 90.0},
                {"slot": "walk_backward_left", "speed": 2.2, "direction": -135.0},
                {"slot": "walk_backward_right", "speed": 2.2, "direction": 135.0},
                {"slot": "run_forward", "speed": 5.5, "direction": 0.0},
            ],
        }],
        "state_machine": {"entry_state": "idle", "states": states, "transitions": transitions},
        "root_motion": {"mode": "in_place", "consume_translation": False, "consume_rotation": False},
        "procedural": {
            "foot_placement": True, "foot_locking": True, "pelvis_compensation": True,
            "stride_warping": True, "orientation_warping": True,
            "contact_events": ["foot_contact_l", "foot_contact_r", "land_contact", "pivot_plant"],
        },
        "graph": {
            "nodes": [
                {"id": "input", "title": "Read Movement Input", "opcode": "input_read_axis"},
                {"id": "velocity", "title": "Calculate Velocity", "opcode": "movement_calculate_velocity"},
                {"id": "ground", "title": "Ground Probe", "opcode": "character_ground_probe"},
                {"id": "state", "title": "Locomotion State Machine", "opcode": "animation_state_machine"},
                {"id": "output", "title": "Output Pose", "opcode": "output_pose"},
            ],
            "connections": [
                {"source": "input", "target": "velocity"},
                {"source": "velocity", "target": "ground"},
                {"source": "ground", "target": "state"},
                {"source": "state", "target": "output"},
            ],
        },
    }


def validate_locomotion_controller(properties: Mapping[str, Any]) -> list[LocomotionIssue]:
    values = dict(properties or {})
    issues: list[LocomotionIssue] = []
    movement = dict(values.get("movement") or {})
    if float(movement.get("maximum_speed", 0.0) or 0.0) <= 0.0:
        issues.append(LocomotionIssue("error", "invalid_maximum_speed", "Maximum movement speed must be greater than zero."))
    if float(movement.get("acceleration", 0.0) or 0.0) <= 0.0:
        issues.append(LocomotionIssue("error", "invalid_acceleration", "Acceleration must be greater than zero."))
    if float(movement.get("jump_impulse", 0.0) or 0.0) <= 0.0:
        issues.append(LocomotionIssue("error", "invalid_jump_impulse", "Jump impulse must be greater than zero."))
    camera = dict(values.get("camera") or {})
    if len(camera.get("offset") or ()) != 3:
        issues.append(LocomotionIssue("error", "invalid_camera_offset", "Camera follow offset needs three values."))
    parameters = dict(values.get("parameters") or {})
    required_parameters = {"speed", "direction", "vertical_speed", "is_grounded", "jump_triggered"}
    missing_parameters = sorted(required_parameters - set(parameters))
    if missing_parameters:
        issues.append(LocomotionIssue("error", "missing_parameters", "Missing locomotion parameters: " + ", ".join(missing_parameters)))
    slots = dict(values.get("animation_slots") or {})
    required_slots = {
        "idle", "walk_forward", "walk_forward_left", "walk_forward_right", "walk_backward",
        "walk_backward_left", "walk_backward_right", "strafe_left", "strafe_right",
        "run_forward", "jump_start", "jump_loop", "land",
    }
    missing_slots = sorted(key for key in required_slots if not str(slots.get(key) or ""))
    if missing_slots:
        issues.append(LocomotionIssue("error", "missing_animation_slots", "Assign animation slots: " + ", ".join(missing_slots)))
    state_machine = dict(values.get("state_machine") or {})
    states = {str(row.get("id") or "") for row in state_machine.get("states") or () if isinstance(row, Mapping)}
    if str(state_machine.get("entry_state") or "") not in states:
        issues.append(LocomotionIssue("error", "invalid_entry_state", "The locomotion state machine needs a valid entry state."))
    for transition in state_machine.get("transitions") or ():
        if not isinstance(transition, Mapping):
            continue
        if str(transition.get("from") or "") not in states or str(transition.get("to") or "") not in states:
            issues.append(LocomotionIssue("error", "invalid_transition", "A locomotion transition references an unknown state."))
            break
    return issues


def compile_locomotion_payload(properties: Mapping[str, Any], *, platform: str, quality: str) -> bytes:
    issues = validate_locomotion_controller(properties)
    errors = [item.message for item in issues if item.severity == "error"]
    if errors:
        raise ValueError("Locomotion Controller is not cookable: " + " ".join(errors))
    payload = {
        "schema": "tech_connector.locomotion_runtime.v1", "platform": str(platform), "quality": str(quality),
        "controller": deepcopy(dict(properties or {})),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "LOCOMOTION_CONTROLLER_SCHEMA", "LocomotionIssue", "compile_locomotion_payload",
    "locomotion_preset", "validate_locomotion_controller",
]
