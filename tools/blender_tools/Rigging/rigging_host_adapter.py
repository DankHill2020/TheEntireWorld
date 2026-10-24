"""Blender translation endpoint for Tech Connector's shared rigging workspace.

The adapter uses ordinary Blender armatures, empties, and pose constraints so
the resulting rigs remain editable without the Tech Connector UI running.
"""

from __future__ import annotations

import json
import importlib
import re
from typing import Any

import bpy

from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    FINGER_SLOTS,
    RiggingOperationResult,
    auto_map_character,
    mirror_character_slots,
    thumb_rig_contract,
    twist_driver_contract,
    validate_character_definition,
)


HOST = "blender"
RIG_BEHAVIOR_REVISION = 7


def reload_dependencies() -> int:
    """Refresh the shared portable contract used by this live Blender host."""
    global CharacterDefinition, FINGER_SLOTS, RiggingOperationResult
    global auto_map_character, mirror_character_slots, thumb_rig_contract, twist_driver_contract
    global validate_character_definition
    contract = importlib.reload(importlib.import_module(
        "tech_connector.services.dcc.rigging_workspace_service"
    ))
    for name in (
        "CharacterDefinition", "FINGER_SLOTS", "RiggingOperationResult",
        "auto_map_character", "mirror_character_slots", "thumb_rig_contract", "twist_driver_contract",
        "validate_character_definition",
    ):
        globals()[name] = getattr(contract, name)
    return RIG_BEHAVIOR_REVISION


def _result(ok: bool, capability: str, message: str = "", **kwargs: Any) -> dict[str, Any]:
    return RiggingOperationResult(ok, capability, HOST, message, **kwargs).to_dict()


def _matrix_values(matrix: Any) -> list[float]:
    """Convert Blender's column-vector matrix to the portable row-vector layout."""
    return [float(matrix[column][row]) for row in range(4) for column in range(4)]


def _matrix_from_values(values: Any) -> Any:
    """Convert a portable row-vector matrix to Blender's native layout."""
    from mathutils import Matrix

    data = [float(value) for value in values]
    if len(data) != 16:
        raise ValueError("A transform matrix requires 16 values")
    return Matrix([data[index:index + 4] for index in range(0, 16, 4)]).transposed()


def _bone_id(armature: Any, bone: Any) -> str:
    return f"{armature.name}:{bone.name}"


def _resolve_bone(value: str) -> tuple[Any, Any, Any]:
    requested = str(value)
    if ":" in requested:
        armature_name, bone_name = requested.split(":", 1)
        armature = bpy.data.objects.get(armature_name)
        if armature is not None and getattr(armature, "type", "") == "ARMATURE":
            bone = armature.data.bones.get(bone_name)
            pose_bone = armature.pose.bones.get(bone_name)
            if bone is not None and pose_bone is not None:
                return armature, bone, pose_bone
    for armature in bpy.data.objects:
        if getattr(armature, "type", "") != "ARMATURE":
            continue
        bone = armature.data.bones.get(requested)
        pose_bone = armature.pose.bones.get(requested)
        if bone is not None and pose_bone is not None:
            return armature, bone, pose_bone
    raise ValueError(f"Blender armature bone does not exist: {requested}")


def _definition(value: Any) -> CharacterDefinition:
    if isinstance(value, CharacterDefinition):
        return value
    if isinstance(value, dict):
        if "schema" in value or "slots" in value:
            return CharacterDefinition.from_dict(value)
        return CharacterDefinition("Character", {str(key): str(node) for key, node in value.items() if node})
    raise ValueError("A portable character definition is required.")


def _control(
    name: str,
    target: str,
    module: str,
    *,
    display: str = "CIRCLE",
    world_oriented: bool = False,
) -> Any:
    from mathutils import Matrix

    armature, bone, pose_bone = _resolve_bone(target)
    existing = bpy.data.objects.get(name)
    control = existing or bpy.data.objects.new(name, None)
    if existing is None:
        bpy.context.scene.collection.objects.link(control)
    control.empty_display_type = display
    control.empty_display_size = max(float(getattr(bone, "length", 1.0)) * 0.35, 0.1)
    # Controls must be created on the character's current solved pose.  Using
    # matrix_local here silently snapped a T-posed character back toward its
    # authored rest pose as soon as an FK constraint became active.
    target_matrix = armature.matrix_world @ pose_bone.matrix
    control.matrix_world = (
        Matrix.Translation(target_matrix.translation)
        if world_oriented
        else target_matrix
    )
    control["tc_rig_module"] = module
    control["tc_target_bone"] = _bone_id(armature, bone)
    return control


def _mapped_mesh_fit_positions(definition: CharacterDefinition, mesh: Any) -> dict[str, list[float]]:
    """Fit mapped bone heads into a mesh bbox while preserving their proportions."""
    from mathutils import Vector

    if mesh is None or getattr(mesh, "type", "") != "MESH":
        raise ValueError("Blender joint placement requires a mesh object or semantic world positions.")
    rows = []
    for slot, joint_id in definition.slots.items():
        try:
            armature, bone, _pose_bone = _resolve_bone(joint_id)
        except ValueError:
            continue
        rows.append((slot, armature.matrix_world @ bone.head_local))
    if not rows:
        raise ValueError("The character definition has no resolvable Blender bones to place.")
    mesh_points = [mesh.matrix_world @ Vector(corner) for corner in mesh.bound_box]
    source_min = Vector(tuple(min(point[axis] for _slot, point in rows) for axis in range(3)))
    source_max = Vector(tuple(max(point[axis] for _slot, point in rows) for axis in range(3)))
    target_min = Vector(tuple(min(point[axis] for point in mesh_points) for axis in range(3)))
    target_max = Vector(tuple(max(point[axis] for point in mesh_points) for axis in range(3)))
    fitted = {}
    for slot, point in rows:
        values = []
        for axis in range(3):
            source_span = source_max[axis] - source_min[axis]
            fraction = (
                (point[axis] - source_min[axis]) / source_span
                if abs(source_span) > 1.0e-8
                else 0.5
            )
            values.append(target_min[axis] + fraction * (target_max[axis] - target_min[axis]))
        fitted[slot] = values
    return fitted


def _constraint(pose_bone: Any, constraint_type: str, name: str, module: str) -> Any:
    owned_name = f"TCMOD_{module}__{name}"
    existing = pose_bone.constraints.get(owned_name)
    constraint = existing or pose_bone.constraints.new(type=constraint_type)
    constraint.name = owned_name
    return constraint


def _constraint_module(constraint: Any) -> str:
    name = str(getattr(constraint, "name", ""))
    if not name.startswith("TCMOD_") or "__" not in name:
        return ""
    return name[len("TCMOD_"):].split("__", 1)[0]


def _copy_control(target: str, name: str, module: str) -> str:
    armature, _bone, pose_bone = _resolve_bone(target)
    control = _control(name, target, module)
    constraint = _constraint(pose_bone, "COPY_TRANSFORMS", f"TC_{name}", module)
    constraint.target = control
    constraint.target_space = "WORLD"
    constraint.owner_space = "WORLD"
    armature["tc_control_rig"] = True
    return control.name


def _sample_polyline(points: list[Any], count: int) -> list[Any]:
    """Return evenly spaced positions along a world-space polyline."""
    if count < 2:
        raise ValueError("A Blender ribbon requires at least two controls")
    lengths = [0.0]
    for first, second in zip(points, points[1:]):
        lengths.append(lengths[-1] + (second - first).length)
    if lengths[-1] <= 1.0e-8:
        raise ValueError("A Blender ribbon cannot be built from coincident bones")
    samples = []
    for index in range(count):
        distance = lengths[-1] * index / float(count - 1)
        segment = next(
            (item for item in range(len(lengths) - 1) if lengths[item + 1] >= distance),
            len(lengths) - 2,
        )
        span = max(lengths[segment + 1] - lengths[segment], 1.0e-8)
        blend = (distance - lengths[segment]) / span
        samples.append(points[segment].lerp(points[segment + 1], blend))
    return samples


def _curve_world_polyline(curve: Any) -> tuple[list[Any], bool]:
    """Return evaluated points from the first Blender spline in world space."""
    if curve is None or getattr(curve, "type", "") != "CURVE" or not curve.data.splines:
        raise ValueError("Select a Blender Curve object.")
    spline = curve.data.splines[0]
    evaluated = list(getattr(spline, "evaluated_points", []) or [])
    source = evaluated or list(spline.bezier_points) or list(spline.points)
    points = [curve.matrix_world @ point.co.to_3d() for point in source]
    closed = bool(getattr(spline, "use_cyclic_u", False))
    if closed and points and points[-1] != points[0]:
        points.append(points[0].copy())
    if len(points) < 2:
        raise ValueError("The selected curve does not contain enough evaluated points.")
    return points, closed


def _sample_curve_by_length(points: list[Any], count: int, *, closed: bool) -> tuple[list[Any], list[float]]:
    lengths = [0.0]
    for first, second in zip(points, points[1:]):
        lengths.append(lengths[-1] + (second - first).length)
    total = lengths[-1]
    if total <= 1.0e-8:
        raise ValueError("The selected curve has zero length.")
    denominator = count if closed else max(1, count - 1)
    parameters = [index / float(denominator) for index in range(count)]
    samples = []
    for parameter in parameters:
        distance = parameter * total
        segment = next(
            (index for index in range(len(lengths) - 1) if lengths[index + 1] >= distance),
            len(lengths) - 2,
        )
        span = max(lengths[segment + 1] - lengths[segment], 1.0e-8)
        samples.append(points[segment].lerp(points[segment + 1], (distance - lengths[segment]) / span))
    return samples, parameters


def scene_joints() -> dict[str, Any]:
    joints = []
    for armature in bpy.data.objects:
        if getattr(armature, "type", "") != "ARMATURE":
            continue
        for bone in armature.data.bones:
            parent = bone.parent
            joints.append({
                "id": _bone_id(armature, bone),
                "native_id": _bone_id(armature, bone),
                "name": bone.name,
                "parent_id": _bone_id(armature, parent) if parent else "",
                "depth": len(bone.parent_recursive),
                "local_matrix": _matrix_values(bone.matrix_local),
                "world_matrix": _matrix_values(armature.matrix_world @ bone.matrix_local),
            })
    return _result(True, "host.query", data={"joints": joints})


def selection() -> dict[str, Any]:
    selected = [obj.name for obj in bpy.context.selected_objects]
    active = getattr(bpy.context, "active_pose_bone", None)
    armature = getattr(bpy.context, "object", None)
    if active is not None and getattr(armature, "type", "") == "ARMATURE":
        selected.append(_bone_id(armature, active.bone))
    return _result(True, "host.query", data={"selection": selected})


def execute(capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = globals().get("_op_" + str(capability).replace(".", "_"))
    if handler is None:
        return _result(False, capability, f"Blender translation is not implemented: {capability}")
    mutating = str(capability).startswith(("rig.", "skin.", "retarget."))
    undo_started = False
    try:
        if mutating:
            try:
                bpy.ops.ed.undo_push(message="Before Tech Connector: {}".format(capability))
                undo_started = True
            except Exception:
                pass
        result = handler(dict(payload))
        if mutating:
            try:
                bpy.ops.ed.undo_push(message="Tech Connector: {}".format(capability))
            except Exception:
                pass
        return result
    except Exception as exc:
        if undo_started:
            try:
                bpy.ops.ed.undo()
            except Exception:
                pass
        return _result(False, capability, str(exc))


def _op_definition_auto_map(payload: dict[str, Any]) -> dict[str, Any]:
    rows = scene_joints()["data"]["joints"]
    definition = auto_map_character(
        rows, name=str(payload.get("name") or "Character"), source_provider="blender",
        source_root=str(payload.get("root_joint") or ""),
    )
    validation = validate_character_definition(definition, rows)
    return _result(True, "definition.auto_map", f"Mapped {len(definition.slots)} Blender bones.",
                   data={"definition": definition.to_dict(), "validation": validation.to_dict()},
                   warnings=validation.warnings)


def _op_definition_assign_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    armature, bone, _pose_bone = _resolve_bone(str(payload["joint"]))
    definition.slots[str(payload["slot"])] = _bone_id(armature, bone)
    return _result(True, "definition.assign_slot", "Assigned Blender character slot.",
                   data={"definition": definition.to_dict()})


def _op_definition_clear_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.slots.pop(str(payload["slot"]), None)
    return _result(True, "definition.clear_slot", "Cleared Blender character slot.",
                   data={"definition": definition.to_dict()})


def _op_definition_mirror_slots(payload: dict[str, Any]) -> dict[str, Any]:
    definition = mirror_character_slots(_definition(payload.get("definition")), str(payload.get("source_side") or "left"))
    return _result(True, "definition.mirror_slots", "Mirrored Blender slot assignments.",
                   data={"definition": definition.to_dict()})


def _op_definition_validate(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_character_definition(_definition(payload["mapping"]), scene_joints()["data"]["joints"])
    return _result(validation.ok, "definition.validate",
                   "Definition is valid." if validation.ok else "Definition needs attention.",
                   data={"validation": validation.to_dict()}, warnings=validation.warnings)


def _op_definition_set_reference_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.reference_pose = {}
    for joint in set(definition.slots.values()):
        armature, bone, _pose_bone = _resolve_bone(joint)
        definition.reference_pose[joint] = _matrix_values(armature.matrix_world @ bone.matrix_local)
    return _result(True, "definition.set_reference_pose", "Captured Blender reference pose.",
                   changed_ids=list(definition.reference_pose), data={"definition": definition.to_dict()})


def _op_definition_import(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.import", f"Loaded {definition.name}.", data={"definition": definition.to_dict()})


def _op_definition_export(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.export", f"Prepared {definition.name} for export.",
                   data={"definition": definition.to_dict()})


def _op_retarget_create_definition(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["mapping"])
    return _result(True, "retarget.create_definition", f"Created {definition.name} retarget definition.",
                   data={"definition": definition.to_dict()})


def _op_retarget_validate_definition(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_character_definition(_definition(payload["definition"]), scene_joints()["data"]["joints"])
    return _result(validation.ok, "retarget.validate_definition",
                   "Retarget definition is valid." if validation.ok else "Retarget definition needs attention.",
                   data={"validation": validation.to_dict()}, warnings=validation.warnings)


def _module_targets(module: str, definition: CharacterDefinition) -> list[tuple[str, str]]:
    slots = definition.slots
    routes = {
        "root": ("Reference",), "pelvis": ("Hips",),
        "spine": ("Spine", "Spine1", "Spine2", "Spine3"),
        "neck": ("Neck", "Neck1"), "head": ("Head",),
        "left_arm": ("LeftArm", "LeftForeArm", "LeftHand"),
        "right_arm": ("RightArm", "RightForeArm", "RightHand"),
        "left_leg": ("LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase"),
        "right_leg": ("RightUpLeg", "RightLeg", "RightFoot", "RightToeBase"),
        "fingers": FINGER_SLOTS,
        "mouth": ("UpperLipCenter", "LowerLipCenter", "LeftLipCorner", "RightLipCorner"),
        "eyes": ("LeftEye", "RightEye"), "brows": ("LeftBrow", "RightBrow"),
        "jaw": ("Jaw",), "teeth": ("UpperTeeth", "LowerTeeth"),
        "nose": ("NoseRoot",),
    }
    if module not in routes:
        raise ValueError(f"Blender rig has no module route for {module}")
    return [(slot, slots[slot]) for slot in routes[module] if slots.get(slot)]


def _build_nose_module(definition: CharacterDefinition) -> list[str]:
    root_target = definition.slots.get("NoseRoot")
    if not root_target:
        raise ValueError("Character definition has no Blender NoseRoot bone")
    armature, root_bone, _root_pose = _resolve_bone(root_target)
    root_control_name = root_bone.name.removesuffix("_jnt") + "_ctrl"
    root_control = bpy.data.objects[_copy_control(root_target, root_control_name, "nose")]
    created = [root_control.name]
    wanted = {"nose_upper", "nose_base", "nose_tip", "l_nostril", "r_nostril"}
    for bone in root_bone.children_recursive:
        base = bone.name.removesuffix("_jnt")
        if base not in wanted:
            continue
        control = bpy.data.objects[_copy_control(_bone_id(armature, bone), base + "_ctrl", "nose")]
        if control.parent != root_control:
            world_matrix = control.matrix_world.copy()
            control.parent = root_control
            control.parent_type = "OBJECT"
            control.parent_bone = ""
            control.matrix_world = world_matrix
        created.append(control.name)
    return created


def _build_thumb_rigs(definition: CharacterDefinition, blend: float) -> list[str]:
    """Build Maya-parity thumb FK, world IK, and authored-plane PV controls."""
    from mathutils import Vector

    created = []
    for contract in thumb_rig_contract(definition):
        resolved = [_resolve_bone(joint_id) for joint_id in contract["joints"]]
        armatures = {id(item[0]) for item in resolved}
        if len(armatures) != 1:
            raise ValueError("A Blender thumb chain must belong to one armature")
        armature = resolved[0][0]
        bones = [item[1] for item in resolved]
        poses = [item[2] for item in resolved]
        module = "fingers"

        fk_parent = None
        for bone, pose_bone, control_name in zip(
            bones[:3], poses[:3], contract["fk_controls"]
        ):
            control = _control(
                control_name,
                _bone_id(armature, bone),
                module,
                display="CUBE",
            )
            if fk_parent is not None and control.parent != fk_parent:
                world_matrix = control.matrix_world.copy()
                control.parent = fk_parent
                control.matrix_world = world_matrix
            fk_parent = control
            constraint = _constraint(
                pose_bone, "COPY_TRANSFORMS", f"TC_{control_name}_fk", module
            )
            constraint.target = control
            constraint.target_space = "WORLD"
            constraint.owner_space = "WORLD"
            constraint.influence = 1.0 - blend
            created.extend((control.name, f"{armature.name}:{pose_bone.name}:{constraint.name}"))

        ik_control = _control(
            contract["ik_control"],
            contract["endpoint_joint"],
            module,
            display="CUBE",
            world_oriented=True,
        )
        pole_control = _control(
            contract["pole_control"],
            contract["joints"][1],
            module,
            display="CUBE",
            world_oriented=True,
        )

        positions = [armature.matrix_world @ pose.head for pose in poses]
        thumb_line = positions[-1] - positions[0]
        pole_origin = positions[1].copy()
        pole_direction = Vector((0.0, 0.0, 0.0))
        if thumb_line.length_squared > 1.0e-12:
            for position in positions[1:-1]:
                projection = positions[0] + thumb_line * (
                    (position - positions[0]).dot(thumb_line) / thumb_line.length_squared
                )
                candidate = position - projection
                if candidate.length > pole_direction.length:
                    pole_origin = projection
                    pole_direction = candidate
        if pole_direction.length <= 1.0e-8:
            source_axis = armature.matrix_world.to_3x3() @ poses[0].z_axis
            if thumb_line.length_squared > 1.0e-12:
                pole_direction = source_axis - thumb_line * (
                    source_axis.dot(thumb_line) / thumb_line.length_squared
                )
            else:
                pole_direction = source_axis
        if pole_direction.length <= 1.0e-8:
            pole_direction = Vector((0.0, 0.0, 1.0))
        pole_direction.normalize()
        hand_slot = "LeftHand" if contract["side"] == "left" else "RightHand"
        hand_id = definition.slots.get(hand_slot)
        if hand_id:
            hand_armature, _hand_bone, hand_pose = _resolve_bone(hand_id)
            if hand_armature == armature:
                dorsal_direction = -(
                    hand_armature.matrix_world.to_3x3()
                    @ hand_pose.matrix.to_3x3().col[2]
                )
                if dorsal_direction.dot(Vector((0.0, 0.0, 1.0))) < 0.0:
                    dorsal_direction.negate()
                if thumb_line.length_squared > 1.0e-12:
                    dorsal_direction -= thumb_line * (
                        dorsal_direction.dot(thumb_line)
                        / thumb_line.length_squared
                    )
                if (
                    dorsal_direction.length > 1.0e-8
                    and pole_direction.dot(dorsal_direction) < 0.0
                ):
                    pole_direction.negate()
        pole_control.matrix_world.translation = pole_origin + pole_direction * 5.0
        pole_control["tc_pole_side"] = contract["pole_side"]

        ik = _constraint(poses[-2], "IK", f"TC_{contract['side']}_thumb_ik", module)
        ik.target = ik_control
        ik.pole_target = pole_control
        ik.chain_count = 3
        pole_local = armature.matrix_world.inverted() @ pole_control.matrix_world.translation
        chain_axis = poses[-1].head - poses[0].head
        pole_axis = pole_local - poses[0].head
        pole_normal = chain_axis.cross(pole_axis)
        projected_pole_axis = pole_normal.cross(poses[0].vector)
        if projected_pole_axis.length > 1.0e-8:
            projected_pole_axis.normalize()
            pole_angle = poses[0].x_axis.angle(projected_pole_axis)
            if poses[0].x_axis.cross(projected_pole_axis).dot(poses[0].vector) < 0.0:
                pole_angle = -pole_angle
            ik.pole_angle = -pole_angle
        ik.influence = blend
        ik_control["ik_fk_blend"] = blend
        ik_control["tc_thumb_contract_revision"] = contract["revision"]
        armature["tc_control_rig"] = True
        created.extend((
            ik_control.name,
            pole_control.name,
            f"{armature.name}:{poses[-2].name}:{ik.name}",
        ))
    return created


def _op_rig_build_module(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"]).lower()
    definition = _definition(payload["definition"])
    targets = _module_targets(module, definition)
    if not targets:
        raise ValueError(f"Character definition has no Blender bones for module {module}")
    created = []
    if module == "nose":
        created.extend(_build_nose_module(definition))
    elif module == "fingers":
        thumb_joint_ids = {
            joint_id
            for contract in thumb_rig_contract(definition)
            for joint_id in contract["joints"]
        }
        created.extend(_build_thumb_rigs(
            definition,
            max(0.0, min(1.0, float(payload.get("blend", 1.0)))),
        ))
        for slot, target in targets:
            if target not in thumb_joint_ids:
                created.append(_copy_control(target, f"{slot}_ctrl", module))
    elif module in {"left_arm", "right_arm", "left_leg", "right_leg"} and len(targets) >= 3:
        limb = _op_rig_create_ik_fk_limb({
            "start": targets[0][1], "mid": targets[1][1], "end": targets[2][1], "module": module,
            "stretch": payload.get("stretch", 1.0),
            "blend": payload.get("blend", 0.0),
        })
        if not limb["ok"]:
            raise RuntimeError(limb["message"])
        created.extend(limb["created_ids"])
        twist_routes = {
            "left_arm": ((0, 1, "LeftArmRoll"), (1, 2, "LeftForeArmRoll")),
            "right_arm": ((0, 1, "RightArmRoll"), (1, 2, "RightForeArmRoll")),
            "left_leg": ((0, 1, "LeftUpLegRoll"), (1, 2, "LeftLegRoll")),
            "right_leg": ((0, 1, "RightUpLegRoll"), (1, 2, "RightLegRoll")),
        }
        for start_index, end_index, slot in twist_routes[module]:
            twist_joint = definition.slots.get(slot)
            if not twist_joint:
                continue
            twist = _op_rig_create_twist({
                "start": targets[start_index][1], "end": targets[end_index][1],
                "twist_joints": [twist_joint], "module": module,
            })
            if not twist["ok"]:
                raise RuntimeError(twist["message"])
            created.extend(twist["created_ids"])
    else:
        names = {
            "UpperLipCenter": "c_upper_lip_main_ctrl", "LowerLipCenter": "c_lower_lip_main_ctrl",
            "LeftLipCorner": "l_lip_corner_main_ctrl", "RightLipCorner": "r_lip_corner_main_ctrl",
        }
        controls_by_slot = {}
        for slot, target in targets:
            control_name = _copy_control(target, names.get(slot, f"{slot}_ctrl"), module)
            controls_by_slot[slot] = control_name
            created.append(control_name)
            if module == "spine" and slot != targets[-1][0]:
                main = bpy.data.objects[control_name]
                sub_name = control_name.removesuffix("_ctrl") + "_sub_ctrl"
                sub = _control(sub_name, target, module, display="CIRCLE")
                sub_world = sub.matrix_world.copy()
                sub.parent = main
                sub.matrix_world = sub_world
                sub["tc_shape_rotation_x"] = 90.0
                sub["tc_shape_rotation_space"] = "local_cvs"
                armature, _bone, pose_bone = _resolve_bone(target)
                constraint = _constraint(
                    pose_bone, "COPY_TRANSFORMS", f"TC_{control_name}", module
                )
                constraint.target = sub
                constraint.target_space = "WORLD"
                constraint.owner_space = "WORLD"
                armature["tc_control_rig"] = True
                created.append(sub.name)
            if module == "brows":
                bpy.data.objects[control_name]["tc_shape_rotation_y"] = 90.0
                bpy.data.objects[control_name]["tc_shape_rotation_space"] = "local_cvs"
        if module == "brows":
            for slot, prefix in (("LeftBrow", "l"), ("RightBrow", "r")):
                target = dict(targets).get(slot)
                child_name = controls_by_slot.get(slot)
                if not target or not child_name:
                    continue
                main = _control(f"{prefix}_brow_main_ctrl", target, module)
                main["tc_shape_rotation_y"] = 90.0
                main["tc_shape_rotation_space"] = "local_cvs"
                child = bpy.data.objects[child_name]
                child_world = child.matrix_world.copy()
                child.parent = main
                child.matrix_world = child_world
                created.append(main.name)
        if module == "mouth":
            parent = bpy.data.objects.get("lip_main_ctrl")
            if parent is None:
                parent = bpy.data.objects.new("lip_main_ctrl", None)
                bpy.context.scene.collection.objects.link(parent)
            parent.empty_display_type = "CIRCLE"
            parent["tc_rig_module"] = module
            for name in created:
                child = bpy.data.objects[name]
                world_matrix = child.matrix_world.copy()
                child.parent = parent
                child.matrix_world = world_matrix
            created.insert(0, parent.name)
    return _result(
        True,
        "rig.build_module",
        f"Built Blender module {module}.",
        created_ids=created,
        data={
            "module": module,
            "brow_shape_rotation_y": 90.0 if module == "brows" else None,
            "spine_sub_shape_rotation_x": 90.0 if module == "spine" else None,
        },
    )


def _delete_auto_joint_guides() -> list[str]:
    """Remove the temporary placement guide object/collection hierarchy."""
    removed = []
    group = bpy.data.objects.get("auto_joint_guides_grp")
    if group is not None:
        descendants = []
        pending = list(group.children)
        while pending:
            child = pending.pop()
            descendants.append(child)
            pending.extend(list(child.children))
        for obj in reversed(descendants):
            if obj.name in bpy.data.objects:
                removed.append(obj.name)
                bpy.data.objects.remove(obj, do_unlink=True)
        removed.append(group.name)
        bpy.data.objects.remove(group, do_unlink=True)
    collection = bpy.data.collections.get("auto_joint_guides_grp")
    if collection is not None:
        for obj in list(collection.objects):
            if obj.name in bpy.data.objects:
                removed.append(obj.name)
                bpy.data.objects.remove(obj, do_unlink=True)
        removed.append(collection.name)
        bpy.data.collections.remove(collection)
    return list(dict.fromkeys(removed))


def _op_rig_place_joints(payload: dict[str, Any]) -> dict[str, Any]:
    """Place mapped edit bones from explicit points or a selected mesh fit."""
    from mathutils import Vector

    definition = _definition(payload["definition"])
    positions = dict(payload.get("positions") or {})
    mesh = bpy.data.objects.get(str(payload.get("mesh") or ""))
    if not positions:
        if mesh is None:
            mesh = next(
                (obj for obj in bpy.context.selected_objects if getattr(obj, "type", "") == "MESH"),
                None,
            )
        positions = _mapped_mesh_fit_positions(definition, mesh)
    if bool(payload.get("preview", False)):
        return _result(
            True,
            "rig.place_joints",
            "Previewed Blender character joint placement.",
            data={"positions": positions, "applied": False, "behavior_revision": RIG_BEHAVIOR_REVISION},
        )
    grouped = {}
    for key, value in positions.items():
        joint_id = definition.slots.get(str(key), str(key))
        armature, bone, _pose_bone = _resolve_bone(joint_id)
        grouped.setdefault(armature, []).append((bone.name, Vector(tuple(value))))
    changed = []
    face_report = {
        "brows": {},
        "surface_face": {},
        "eyelid_tip_zero_rotates": [],
        "nose_base_translate_x": None,
    }
    previous_active = bpy.context.view_layer.objects.active
    previous_mode = str(getattr(bpy.context, "mode", "OBJECT"))
    try:
        if previous_mode != "OBJECT" and bpy.context.object is not None:
            bpy.ops.object.mode_set(mode="OBJECT")
        for armature, rows in grouped.items():
            bpy.context.view_layer.objects.active = armature
            armature.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            inverse = armature.matrix_world.inverted()
            for bone_name, world_position in rows:
                edit_bone = armature.data.edit_bones.get(bone_name)
                if edit_bone is None:
                    continue
                target = inverse @ world_position
                delta = target - edit_bone.head
                edit_bone.head = target
                edit_bone.tail += delta
                changed.append(_bone_id(armature, edit_bone))
            # Reconnect display tails to their placed primary child without
            # changing any solved head/contact position.
            placed_names = {name for name, _position in rows}
            for bone_name, _world_position in rows:
                edit_bone = armature.data.edit_bones.get(bone_name)
                children = [child for child in edit_bone.children if child.name in placed_names]
                if children:
                    edit_bone.tail = children[0].head

            # Blender bones use local Y as their native head-to-tail axis.
            # Aim that native axis at the next brow landmark while recording
            # the shared semantic contract (X aim, Y surface tangent).
            for side in ("l", "r"):
                brow_rows = []
                for edit_bone in armature.data.edit_bones:
                    short = edit_bone.name.rsplit(":", 1)[-1]
                    match = re.match(rf"^{side}_brow(\d+|_end)$", short, re.IGNORECASE)
                    if match:
                        token = match.group(1).lower()
                        brow_rows.append((6 if token == "_end" else int(token), edit_bone))
                brow_rows.sort(key=lambda row: row[0])
                brow_bones = [bone for _index, bone in brow_rows]
                for index, edit_bone in enumerate(brow_bones):
                    if len(brow_bones) < 2:
                        continue
                    direction = (
                        brow_bones[index + 1].head - edit_bone.head
                        if index < len(brow_bones) - 1
                        else edit_bone.head - brow_bones[index - 1].head
                    )
                    if direction.length <= 1.0e-8:
                        continue
                    edit_bone.tail = edit_bone.head + direction
                    surface_normal = None
                    if mesh is not None and getattr(mesh, "type", "") == "MESH":
                        world_origin = armature.matrix_world @ edit_bone.head
                        hit, _location, normal, _face = mesh.closest_point_on_mesh(
                            mesh.matrix_world.inverted() @ world_origin
                        )
                        if hit:
                            world_normal = mesh.matrix_world.to_3x3() @ normal
                            surface_normal = armature.matrix_world.inverted().to_3x3() @ world_normal
                    if surface_normal is None or surface_normal.length <= 1.0e-8:
                        surface_normal = edit_bone.z_axis.copy()
                    edit_bone.align_roll(surface_normal)
                    edit_bone["tc_semantic_aim_axis"] = "X"
                    edit_bone["tc_native_aim_axis"] = "Y"
                    edit_bone["tc_surface_tangent_axis"] = "X"
                    face_report["brows"][edit_bone.name] = {
                        "x_next_brow_alignment": 1.0,
                        "native_aim_axis": "Y",
                        "surface_roll_aligned": True,
                    }
                    changed.append(_bone_id(armature, edit_bone))

            def surface_normal_for(edit_bone):
                surface_normal = None
                if mesh is not None and getattr(mesh, "type", "") == "MESH":
                    world_origin = armature.matrix_world @ edit_bone.head
                    hit, _location, normal, _face = mesh.closest_point_on_mesh(
                        mesh.matrix_world.inverted() @ world_origin
                    )
                    if hit:
                        world_normal = mesh.matrix_world.to_3x3() @ normal
                        surface_normal = (
                            armature.matrix_world.inverted().to_3x3() @ world_normal
                        )
                if surface_normal is None or surface_normal.length <= 1.0e-8:
                    surface_normal = edit_bone.z_axis.copy()
                return surface_normal.normalized()

            def orient_surface_bone(edit_bone, _tangent_reference):
                normal = surface_normal_for(edit_bone)
                tangent_up = (
                    armature.matrix_world.inverted().to_3x3()
                    @ Vector((0.0, 0.0, 1.0))
                )
                tangent_up -= normal * tangent_up.dot(normal)
                if tangent_up.length <= 1.0e-8:
                    tangent_up = edit_bone.x_axis.copy()
                    tangent_up -= normal * tangent_up.dot(normal)
                if tangent_up.length <= 1.0e-8:
                    return
                tangent_up.normalize()
                direction = tangent_up.cross(normal)
                length = max(float(edit_bone.length), 1.0e-5)
                edit_bone.tail = edit_bone.head + direction.normalized() * length
                # Blender's native bone Y is the shared semantic X. With its
                # native X used as semantic Y, -normal produces the same
                # outward-view-up frame as the row-axis DCC backends.
                edit_bone.align_roll(-normal)
                if edit_bone.x_axis.dot(tangent_up) < 0.0:
                    edit_bone.roll += 3.141592653589793
                edit_bone["tc_semantic_aim_axis"] = "X"
                edit_bone["tc_native_aim_axis"] = "Y"
                edit_bone["tc_semantic_up_axis"] = "Y"
                face_report["surface_face"][edit_bone.name] = {
                    "x_surface_tangent_alignment": 1.0,
                    "y_outward_view_up_alignment": float(
                        edit_bone.x_axis.dot(tangent_up)
                    ),
                    "native_aim_axis": "Y",
                    "surface_roll_aligned": True,
                }
                changed.append(_bone_id(armature, edit_bone))

            for side in ("l", "r"):
                under_rows = []
                for edit_bone in armature.data.edit_bones:
                    match = re.match(
                        rf"^{side}_under_?eye_?(\d+)$",
                        edit_bone.name.rsplit(":", 1)[-1],
                        re.IGNORECASE,
                    )
                    if match:
                        under_rows.append((int(match.group(1)), edit_bone))
                under_rows.sort(key=lambda row: row[0])
                under_bones = [bone for _index, bone in under_rows]
                for index, edit_bone in enumerate(under_bones):
                    neighbor = (
                        under_bones[index + 1]
                        if index < len(under_bones) - 1
                        else under_bones[index - 1] if index else None
                    )
                    if neighbor is not None:
                        direction = (
                            neighbor.head - edit_bone.head
                            if index < len(under_bones) - 1
                            else edit_bone.head - neighbor.head
                        )
                        orient_surface_bone(edit_bone, direction)
                for edit_bone in armature.data.edit_bones:
                    if re.match(
                        rf"^{side}_.+cheek.*$",
                        edit_bone.name.rsplit(":", 1)[-1],
                        re.IGNORECASE,
                    ):
                        orient_surface_bone(
                            edit_bone, edit_bone.tail - edit_bone.head
                        )

            nose_base = next((
                edit_bone for edit_bone in armature.data.edit_bones
                if edit_bone.name.rsplit(":", 1)[-1].lower() == "nose_base"
            ), None)
            if nose_base is not None:
                delta = nose_base.tail - nose_base.head
                if nose_base.parent is not None:
                    local_head = nose_base.parent.matrix.inverted() @ nose_base.head
                    local_head.x = 0.0
                    nose_base.head = nose_base.parent.matrix @ local_head
                else:
                    nose_base.head.x = 0.0
                nose_base.tail = nose_base.head + delta
                nose_base["tc_translate_x"] = 0.0
                face_report["nose_base_translate_x"] = 0.0
                changed.append(_bone_id(armature, nose_base))
            bpy.ops.object.mode_set(mode="OBJECT")

            tip_pattern = re.compile(
                r"^(?:l|r)_(?:inner|outer|upper|lower)_eyelidTip\d*$",
                re.IGNORECASE,
            )
            for pose_bone in armature.pose.bones:
                if not tip_pattern.match(pose_bone.name.rsplit(":", 1)[-1]):
                    continue
                pose_bone.matrix_basis.identity()
                pose_bone["tc_rotate_channels"] = (0.0, 0.0, 0.0)
                face_report["eyelid_tip_zero_rotates"].append(_bone_id(armature, pose_bone.bone))
                changed.append(_bone_id(armature, pose_bone.bone))
    finally:
        bpy.context.view_layer.objects.active = previous_active
        if previous_active is not None:
            previous_active.select_set(True)
    removed_guides = _delete_auto_joint_guides()
    return _result(
        True,
        "rig.place_joints",
        "Placed Blender character joints.",
        changed_ids=changed,
        data={"positions": positions, "applied": True, "face_orientation": face_report,
              "removed_auto_joint_guides": removed_guides,
              "behavior_revision": RIG_BEHAVIOR_REVISION},
    )


def _op_rig_set_t_pose(payload: dict[str, Any]) -> dict[str, Any]:
    """Set a mapped Blender armature to a world-axis T-pose."""
    from mathutils import Matrix, Vector

    definition = _definition(payload["definition"])
    pose_matrices = dict(payload.get("pose_matrices") or {})
    changed = []
    if pose_matrices:
        for key, values in pose_matrices.items():
            joint_id = definition.slots.get(str(key), str(key))
            armature, _bone, pose_bone = _resolve_bone(joint_id)
            world = _matrix_from_values(values)
            pose_bone.matrix = armature.matrix_world.inverted() @ world
            changed.append(joint_id)
        bpy.context.view_layer.update()
        return _result(True, "rig.set_t_pose", "Applied portable Blender T-pose matrices.", changed_ids=changed)

    # Always solve from the authored rest hierarchy.  Deriving each aim delta
    # from the previously posed matrices caused small rotations to accumulate
    # on production skeletons with non-trivial joint roll.
    reset_bones = []
    for joint_id in dict.fromkeys(definition.slots.values()):
        try:
            _armature, _bone, pose_bone = _resolve_bone(joint_id)
        except ValueError:
            continue
        pose_bone.matrix_basis.identity()
        reset_bones.append(joint_id)
    bpy.context.view_layer.update()

    def aim_ids(joint_id, child_id, world_direction):
        if not joint_id or not child_id:
            return
        armature, _bone, pose_bone = _resolve_bone(joint_id)
        child_armature, _child_bone, child_pose = _resolve_bone(child_id)
        if child_armature != armature:
            return
        bpy.context.view_layer.update()
        current = child_pose.head - pose_bone.head
        target = armature.matrix_world.inverted().to_3x3() @ Vector(world_direction)
        if current.length <= 1.0e-8 or target.length <= 1.0e-8:
            return
        delta = current.normalized().rotation_difference(target.normalized())
        pivot = pose_bone.head.copy()
        pose_bone.matrix = (
            Matrix.Translation(pivot) @ delta.to_matrix().to_4x4()
            @ Matrix.Translation(-pivot) @ pose_bone.matrix
        )
        changed.append(joint_id)

    def aim(slot, child_slot, world_direction):
        aim_ids(definition.slots.get(slot), definition.slots.get(child_slot), world_direction)

    # Repeated calls start from the authored reference transforms instead of
    # accumulating pose deltas. These are the native Z-up counterparts of the
    # Maya origin/pelvis/hip-swing world-up contract.
    for slot in ("Reference", "Hips"):
        joint_id = definition.slots.get(slot)
        if joint_id:
            _armature, _bone, pose_bone = _resolve_bone(joint_id)
            pose_bone.matrix_basis.identity()
            changed.append(joint_id)

    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        for slot in (side + "ForeArm", side + "Hand", side + "Leg"):
            joint_id = definition.slots.get(slot)
            if joint_id:
                _armature, _bone, pose_bone = _resolve_bone(joint_id)
                pose_bone.matrix_basis.identity()
        aim(side + "Arm", side + "ForeArm", (sign, 0.0, 0.0))
        aim(side + "ForeArm", side + "Hand", (sign, 0.0, 0.0))
        aim(side + "UpLeg", side + "Leg", (0.0, 0.0, -1.0))
        aim(side + "Leg", side + "Foot", (0.0, 0.0, -1.0))
        foot_id = definition.slots.get(side + "Foot")
        toe_id = definition.slots.get(side + "ToeBase")
        if foot_id and toe_id:
            foot_armature, _foot_bone, foot_pose = _resolve_bone(foot_id)
            toe_armature, toe_bone, toe_pose = _resolve_bone(toe_id)
            if foot_armature == toe_armature:
                foot_world = foot_armature.matrix_world @ foot_pose.head
                toe_world = toe_armature.matrix_world @ toe_pose.head
                direction = toe_world - foot_world
                direction.z = 0.0
                if direction.length > 1.0e-8:
                    aim_ids(foot_id, toe_id, direction)
                terminal_children = list(toe_bone.children)
                if terminal_children:
                    tip_id = _bone_id(toe_armature, terminal_children[0])
                    tip_pose = toe_armature.pose.bones.get(terminal_children[0].name)
                    tip_world = toe_armature.matrix_world @ tip_pose.head
                    toe_world = toe_armature.matrix_world @ toe_pose.head
                    toe_direction = tip_world - toe_world
                    toe_direction.z = 0.0
                    if toe_direction.length > 1.0e-8:
                        aim_ids(toe_id, tip_id, toe_direction)
    bpy.context.view_layer.update()

    grounded_by = 0.0
    if bool(payload.get("ground", True)):
        contact_heights = []
        for side in ("Left", "Right"):
            for slot in (side + "Foot", side + "ToeBase"):
                joint_id = definition.slots.get(slot)
                if not joint_id:
                    continue
                armature, _bone, pose_bone = _resolve_bone(joint_id)
                contact_heights.append(float((armature.matrix_world @ pose_bone.head).z))
        hips_id = definition.slots.get("Hips")
        if contact_heights and hips_id:
            armature, _bone, hips_pose = _resolve_bone(hips_id)
            grounded_by = -min(contact_heights)
            local_delta = armature.matrix_world.inverted().to_3x3() @ Vector((0.0, 0.0, grounded_by))
            hips_matrix = hips_pose.matrix.copy()
            hips_matrix.translation += local_delta
            hips_pose.matrix = hips_matrix
            changed.append(hips_id)
            bpy.context.view_layer.update()
    return _result(
        True,
        "rig.set_t_pose",
        "Set Blender character T-pose.",
        changed_ids=list(dict.fromkeys(changed)),
        data={
            "behavior_revision": RIG_BEHAVIOR_REVISION,
            "world_up_axis": "Z",
            "grounded_by": grounded_by,
            "foot_alignment": "rotation_only",
        },
    )

def _op_rig_build_full(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    options = dict(payload.get("options") or {})
    t_pose_result = None
    if bool(options.get("set_t_pose", True)):
        t_pose_result = _op_rig_set_t_pose({
            "definition": definition.to_dict(),
            "ground": bool(options.get("ground", True)),
            "pose_matrices": payload.get("pose_matrices") or {},
        })
    requested_modules = payload.get("modules")
    if requested_modules:
        modules = list(requested_modules)
    else:
        modules = [
            "root", "pelvis", "spine", "neck", "head",
            "left_arm", "right_arm", "left_leg", "right_leg", "fingers",
        ]
        optional_modules = {
            "mouth": ("UpperLipCenter", "LowerLipCenter", "LeftLipCorner", "RightLipCorner"),
            "eyes": ("LeftEye", "RightEye"), "brows": ("LeftBrow", "RightBrow"),
            "jaw": ("Jaw",), "teeth": ("UpperTeeth", "LowerTeeth"),
            "nose": ("NoseRoot",),
        }
        modules.extend(
            module for module, slots in optional_modules.items()
            if any(definition.slots.get(slot) for slot in slots)
        )
    created, warnings = [], []
    for module in modules:
        result = _op_rig_build_module({
            "module": module,
            "definition": definition.to_dict(),
            "blend": float(options.get("ik_fk_blend", 1.0)),
            "stretch": float(options.get("stretch", 0.0)),
        })
        if result["ok"]:
            created.extend(result["created_ids"])
        else:
            warnings.append(f"{module}: {result['message']}")
    return _result(not warnings, "rig.build_full", f"Built {len(modules) - len(warnings)} Blender rig modules.",
                   created_ids=created, warnings=warnings, data={
                       "modules": modules,
                       "t_pose": t_pose_result,
                       "behavior_revision": RIG_BEHAVIOR_REVISION,
                   })


def _op_rig_remove_module(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"]).lower()
    removed = []
    for armature in [obj for obj in bpy.data.objects if getattr(obj, "type", "") == "ARMATURE"]:
        for pose_bone in armature.pose.bones:
            for constraint in list(pose_bone.constraints):
                if _constraint_module(constraint) == module:
                    removed.append(f"{armature.name}:{pose_bone.name}:{constraint.name}")
                    pose_bone.constraints.remove(constraint)
    for obj in list(bpy.data.objects):
        if obj.get("tc_rig_module") == module:
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    return _result(True, "rig.remove_module", f"Removed Blender module {module}.", removed_ids=removed)


def _op_rig_rebuild_module(payload: dict[str, Any]) -> dict[str, Any]:
    removed = _op_rig_remove_module(payload)
    built = _op_rig_build_module(payload)
    built["capability"] = "rig.rebuild_module"
    built["removed_ids"] = removed["removed_ids"]
    return built


def _op_rig_create_face_module(payload: dict[str, Any]) -> dict[str, Any]:
    return _op_rig_build_module(payload)


def _op_rig_create_control(payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload["target"])
    name = str(payload.get("name") or f"{target.split(':')[-1]}_ctrl")
    created = _copy_control(target, name, str(payload.get("module") or "custom"))
    return _result(True, "rig.create_control", "Created Blender control.", created_ids=[created])


def _op_rig_create_constraint(payload: dict[str, Any]) -> dict[str, Any]:
    driven_armature, _bone, driven = _resolve_bone(str(payload["driven"]))
    kind = str(payload["type"]).lower()
    constraint_type = {"parent": "COPY_TRANSFORMS", "point": "COPY_LOCATION", "orient": "COPY_ROTATION",
                       "rotate": "COPY_ROTATION", "scale": "COPY_SCALE"}.get(kind)
    if constraint_type is None:
        raise ValueError(f"Unsupported Blender constraint: {kind}")
    drivers = list(payload["drivers"])
    if len(drivers) != 1:
        raise ValueError("Blender rig constraints currently require exactly one driver")
    driver = bpy.data.objects.get(str(drivers[0]))
    subtarget = ""
    if driver is None:
        driver, driver_bone, _pose = _resolve_bone(str(drivers[0]))
        subtarget = driver_bone.name
    constraint = _constraint(driven, constraint_type, str(payload.get("name") or f"TC_{kind}"),
                             str(payload.get("module") or "custom"))
    constraint.target = driver
    if subtarget:
        constraint.subtarget = subtarget
    driven_armature["tc_control_rig"] = True
    return _result(True, "rig.create_constraint", f"Created Blender {kind} constraint.",
                   created_ids=[f"{driven_armature.name}:{driven.name}:{constraint.name}"])


def _drive_pose_bone_ik_stretch(pose_bone: Any, control: Any) -> None:
    """Drive Blender's native IK stretch weight from a control property."""
    try:
        pose_bone.driver_remove("ik_stretch")
    except (TypeError, RuntimeError):
        pass
    fcurve = pose_bone.driver_add("ik_stretch")
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    variable = driver.variables.new()
    variable.name = "stretch"
    variable.type = "SINGLE_PROP"
    target = variable.targets[0]
    target.id_type = "OBJECT"
    target.id = control
    target.data_path = '["stretch"]'
    driver.expression = "stretch"


def _op_rig_create_ik_fk_limb(payload: dict[str, Any]) -> dict[str, Any]:
    from mathutils import Vector

    start_armature, start_bone, start_pose = _resolve_bone(str(payload["start"]))
    mid_armature, _mid_bone, mid_pose = _resolve_bone(str(payload["mid"]))
    end_armature, end_bone, end_pose = _resolve_bone(str(payload["end"]))
    if start_armature != mid_armature or start_armature != end_armature:
        raise ValueError("A Blender IK chain must belong to one armature")
    module = str(payload.get("module") or f"{start_bone.name}_limb")
    blend = max(0.0, min(1.0, float(payload.get("blend", 0.0))))

    # Build a real FK hierarchy.  Parenting the controls makes rotating the
    # upper control carry the elbow and wrist controls with it, while the
    # world-space copy constraints keep the deform joints on that hierarchy.
    fk_controls = []
    fk_parent = None
    for bone, pose_bone in ((start_bone, start_pose), (_mid_bone, mid_pose), (end_bone, end_pose)):
        control = _control(
            f"{module}_{bone.name}_fk_ctrl",
            _bone_id(start_armature, bone),
            module,
        )
        if fk_parent is not None and control.parent != fk_parent:
            world_matrix = control.matrix_world.copy()
            control.parent = fk_parent
            control.matrix_world = world_matrix
        fk_parent = control
        fk_controls.append(control)
        constraint = _constraint(pose_bone, "COPY_TRANSFORMS", f"TC_{module}_{bone.name}_fk", module)
        constraint.target = control
        constraint.target_space = "WORLD"
        constraint.owner_space = "WORLD"
        constraint.influence = 1.0 - blend

    ik_control = _control(
        f"{end_bone.name}_ik_ctrl",
        str(payload["end"]),
        module,
        display="CUBE",
        world_oriented=True,
    )
    pole_control = _control(
        f"{end_bone.name}_pole_ctrl",
        str(payload["mid"]),
        module,
        world_oriented=True,
    )
    start_world = start_armature.matrix_world @ start_pose.head
    mid_world = mid_armature.matrix_world @ mid_pose.head
    end_world = end_armature.matrix_world @ end_pose.head
    limb_line = end_world - start_world
    if limb_line.length > 1.0e-8:
        projection = start_world + limb_line * (
            (mid_world - start_world).dot(limb_line) / limb_line.length_squared
        )
        pole_direction = mid_world - projection
    else:
        pole_direction = Vector((0.0, -1.0, 0.0))
    if pole_direction.length <= 1.0e-8:
        pole_direction = Vector((0.0, -1.0, 0.0))
    pole_direction.normalize()
    pole_distance = max((mid_world - start_world).length + (end_world - mid_world).length, 0.1)
    pole_control.matrix_world.translation = mid_world + pole_direction * pole_distance
    # Blender's IK owner is the final deforming segment (forearm/shin), while
    # the target is placed at the terminal hand/foot bone.
    ik = _constraint(mid_pose, "IK", f"TC_{module}_ik", module)
    ik.target = ik_control
    ik.pole_target = pole_control
    ik.chain_count = 2
    # Match Blender's pole basis to the limb's current bend plane.  A pole in
    # the geometrically correct position can still introduce a small axial
    # roll unless pole_angle compensates for the start bone's local X axis.
    pole_local = start_armature.matrix_world.inverted() @ pole_control.matrix_world.translation
    chain_axis = end_pose.head - start_pose.head
    pole_axis = pole_local - start_pose.head
    pole_normal = chain_axis.cross(pole_axis)
    projected_pole_axis = pole_normal.cross(start_pose.vector)
    if projected_pole_axis.length > 1.0e-8:
        projected_pole_axis.normalize()
        pole_angle = start_pose.x_axis.angle(projected_pole_axis)
        if start_pose.x_axis.cross(projected_pole_axis).dot(start_pose.vector) < 0.0:
            pole_angle = -pole_angle
        # Blender applies pole_angle opposite the geometric signed angle used
        # above (its IK solve is expressed in owner-bone space).
        ik.pole_angle = -pole_angle
    ik.influence = blend
    ik_control["ik_fk_blend"] = ik.influence
    ik_control["stretch"] = max(0.0, min(1.0, float(payload.get("stretch", 0.0) or 0.0)))
    try:
        ik_control.id_properties_ui("stretch").update(
            min=0.0,
            max=1.0,
            soft_min=0.0,
            soft_max=1.0,
            default=0.0,
        )
    except (AttributeError, TypeError):
        # Blender versions before IDProperty UI metadata still support the
        # property and its drivers.
        pass
    for pose_bone in (start_pose, mid_pose):
        _drive_pose_bone_ik_stretch(pose_bone, ik_control)

    # The two-bone IK solver positions the wrist/ankle, but it does not make
    # the terminal joint follow the world-oriented IK control's rotation. Use
    # an offset child as the rotation driver: the animator-facing IK control
    # remains zero/world-oriented while the driven joint retains its exact
    # current orientation at an FK/IK switch.
    orient_driver_name = f"{end_bone.name}_ik_orient_driver"
    orient_driver = bpy.data.objects.get(orient_driver_name)
    if orient_driver is None:
        orient_driver = bpy.data.objects.new(orient_driver_name, None)
        bpy.context.scene.collection.objects.link(orient_driver)
    orient_driver.empty_display_type = "PLAIN_AXES"
    orient_driver.empty_display_size = max(float(getattr(end_bone, "length", 1.0)) * 0.1, 0.05)
    orient_driver["tc_rig_module"] = module
    orient_driver["tc_internal_driver"] = True
    orient_world = end_armature.matrix_world @ end_pose.matrix
    orient_driver.parent = ik_control
    orient_driver.matrix_world = orient_world
    orient_driver.hide_viewport = True
    orient_driver.hide_render = True
    end_rotation = _constraint(end_pose, "COPY_ROTATION", f"TC_{module}_ik_rotation", module)
    end_rotation.target = orient_driver
    end_rotation.target_space = "WORLD"
    end_rotation.owner_space = "WORLD"
    if hasattr(end_rotation, "mix_mode"):
        end_rotation.mix_mode = "REPLACE"
    end_rotation.influence = blend
    start_armature["tc_control_rig"] = True
    return _result(True, "rig.create_ik_fk_limb", "Created Blender IK/FK limb controls.",
                   created_ids=[control.name for control in fk_controls] + [
                       ik_control.name,
                       pole_control.name,
                       orient_driver.name,
                       f"{mid_armature.name}:{mid_pose.name}:{ik.name}",
                       f"{end_armature.name}:{end_pose.name}:{end_rotation.name}",
                   ],
                   data={"limb": module, "fk_controls": [control.name for control in fk_controls],
                         "ik_control": ik_control.name, "pole_control": pole_control.name,
                         "stretch_control": ik_control.name, "stretch_attribute": "stretch",
                         "controls_world_oriented": True, "bind_pose_preserved": True,
                         "behavior_revision": RIG_BEHAVIOR_REVISION})


def _op_rig_create_curve_joints(payload: dict[str, Any]) -> dict[str, Any]:
    from mathutils import Vector

    curve = bpy.data.objects.get(str(payload["curve"]))
    points, closed = _curve_world_polyline(curve)
    count = int(payload.get("joint_count", 5) or 5)
    if count < 1:
        raise ValueError("Joint count must be at least 1.")
    samples, parameters = _sample_curve_by_length(points, count, closed=closed)
    keep_attached = bool(payload.get("keep_attached", True))
    prefix = str(payload.get("name_prefix") or curve.name.removesuffix("_crv"))

    armature_data = bpy.data.armatures.new(f"{prefix}_path_joints_data")
    armature = bpy.data.objects.new(f"{prefix}_path_joints", armature_data)
    bpy.context.scene.collection.objects.link(armature)

    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    bone_names = []
    display_length = max((points[-1] - points[0]).length / max(count * 3.0, 1.0), 0.05)
    inverse = armature.matrix_world.inverted()
    for index, position in enumerate(samples, start=1):
        name = f"{prefix}_path_{index:02d}_jnt"
        edit_bone = armature_data.edit_bones.new(name)
        head = Vector((0.0, 0.0, 0.0)) if keep_attached else inverse @ position
        sample_index = index - 1
        if sample_index + 1 < len(samples):
            tangent = samples[sample_index + 1] - position
        elif sample_index:
            tangent = position - samples[sample_index - 1]
        else:
            tangent = Vector((1.0, 0.0, 0.0))
        if tangent.length <= 1.0e-8:
            tangent = Vector((1.0, 0.0, 0.0))
        tangent.normalize()
        edit_bone.head = head
        edit_bone.tail = head + tangent * display_length
        bone_names.append(name)
    bpy.ops.object.mode_set(mode="POSE")

    constraint_ids = []
    if keep_attached:
        curve.data.use_path = True
        for name, parameter in zip(bone_names, parameters):
            pose_bone = armature.pose.bones[name]
            constraint = _constraint(pose_bone, "FOLLOW_PATH", f"TC_{name}_path", prefix)
            constraint.target = curve
            constraint.use_fixed_location = True
            constraint.offset_factor = parameter
            constraint.use_curve_follow = True
            # Blender bones point down local Y. Match the common curve-joint
            # contract and avoid a constraint-time quarter turn.
            constraint.forward_axis = "FORWARD_Y"
            constraint.up_axis = "UP_Z"
            constraint_ids.append(f"{armature.name}:{name}:{constraint.name}")
    bpy.ops.object.mode_set(mode="OBJECT")
    armature["tc_control_rig"] = True
    armature["tc_curve_joints"] = True
    armature["tc_keep_attached"] = keep_attached
    created = [armature.name] + [f"{armature.name}:{name}" for name in bone_names] + constraint_ids
    return _result(
        True,
        "rig.create_curve_joints",
        f"Created {len(bone_names)} Blender joints along the curve.",
        created_ids=created,
        data={"armature": armature.name, "joints": bone_names, "parameters": parameters,
              "keep_attached": keep_attached, "closed": closed},
    )


def _op_rig_create_ribbon(payload: dict[str, Any]) -> dict[str, Any]:
    """Create Blender's native ribbon equivalent using a hooked Spline IK curve."""
    from mathutils import Matrix

    chain = [str(value) for value in payload["joint_chain"]]
    if len(chain) < 2:
        raise ValueError("A Blender ribbon requires at least two connected bones")
    resolved = [_resolve_bone(value) for value in chain]
    armature = resolved[0][0]
    if any(item[0] != armature for item in resolved[1:]):
        raise ValueError("A Blender ribbon chain must belong to one armature")
    for previous, current in zip(resolved, resolved[1:]):
        if current[1].parent != previous[1]:
            raise ValueError("Blender Spline IK requires a contiguous parented bone chain")

    module = str(payload.get("module") or payload.get("name") or f"{resolved[0][1].name}_ribbon")
    control_count = max(2, int(payload.get("control_count", 3) or 3))
    world_points = [armature.matrix_world @ item[1].head_local for item in resolved]
    world_points.append(armature.matrix_world @ resolved[-1][1].tail_local)
    control_positions = _sample_polyline(world_points, control_count)

    curve_data = bpy.data.curves.new(f"{module}_curveData", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = max(8, control_count * 3)
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(control_count - 1)
    for point, position in zip(spline.bezier_points, control_positions):
        point.co = position
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"

    curve = bpy.data.objects.new(f"{module}_curve", curve_data)
    bpy.context.scene.collection.objects.link(curve)
    curve["tc_rig_module"] = module
    curve["tc_ribbon"] = True
    curve["tc_rig_region"] = str(payload.get("region") or "surface")
    curve["tc_rig_side"] = str(payload.get("side") or "c")
    curve.display_type = "WIRE"
    curve.hide_render = True

    created = [curve.name]
    parent_name = str(payload.get("parent") or "")
    parent = bpy.data.objects.get(parent_name) if parent_name else None
    for index, position in enumerate(control_positions, 1):
        control = bpy.data.objects.new(f"{module}_ctrl_{index:02d}", None)
        bpy.context.scene.collection.objects.link(control)
        control.empty_display_type = "SPHERE"
        control.empty_display_size = max(float(payload.get("width", 1.0) or 1.0) * 0.5, 0.05)
        control.matrix_world = Matrix.Translation(position)
        control["tc_rig_module"] = module
        control["tc_ribbon_control"] = index
        if parent is not None:
            world_matrix = control.matrix_world.copy()
            control.parent = parent
            control.matrix_world = world_matrix
        hook = curve.modifiers.new(name=f"TCMOD_{module}__hook_{index:02d}", type="HOOK")
        hook.object = control
        hook.vertex_indices_set(((index - 1) * 3, (index - 1) * 3 + 1, (index - 1) * 3 + 2))
        created.append(control.name)

    owner = resolved[-1][2]
    constraint = _constraint(owner, "SPLINE_IK", f"TC_{module}_spline_ik", module)
    constraint.target = curve
    constraint.chain_count = len(chain)
    constraint.use_even_divisions = bool(payload.get("even_divisions", False))
    constraint.use_chain_offset = False
    constraint.use_curve_radius = False
    if hasattr(constraint, "y_scale_mode"):
        constraint.y_scale_mode = "FIT_CURVE" if bool(payload.get("stretch", True)) else "NONE"
    if hasattr(constraint, "xz_scale_mode"):
        constraint.xz_scale_mode = "VOLUME_PRESERVE" if bool(payload.get("volume", True)) else "NONE"
    created.append(f"{armature.name}:{owner.name}:{constraint.name}")
    armature["tc_control_rig"] = True
    return _result(
        True,
        "rig.create_ribbon",
        "Created Blender hooked-curve Spline IK ribbon.",
        created_ids=created,
        data={
            "module": module,
            "region": str(payload.get("region") or "surface"),
            "side": str(payload.get("side") or "c"),
            "curve": curve.name,
            "controls": created[1:-1],
            "bind_joints": chain,
        },
    )


def _op_rig_create_twist(payload: dict[str, Any]) -> dict[str, Any]:
    """Create weighted twist constraints plus a start-bone-owned twist driver."""
    start_armature, start_bone, _start_pose = _resolve_bone(str(payload["start"]))
    end_armature, end_bone, _end_pose = _resolve_bone(str(payload["end"]))
    if start_armature != end_armature:
        raise ValueError("A Blender twist distribution must belong to one armature")
    module = str(payload.get("module") or f"{start_bone.name}_twist")
    default_world_up = (
        _bone_id(start_armature, start_bone.parent)
        if start_bone.parent is not None
        else _bone_id(start_armature, start_bone)
    )
    settings = twist_driver_contract(
        start_bone.name,
        parent=str(payload.get("parent") or default_world_up),
        module=module,
        overrides=payload,
    )
    base_name = start_bone.name
    name = base_name[:-7] + "_twist_driver" if base_name.endswith("_driver") else base_name + "_twist_driver"
    driver = _control(name, str(payload["end"]), module, display="SPHERE")
    already_parented = (
        driver.parent == start_armature
        and driver.parent_type == "BONE"
        and driver.parent_bone == start_bone.name
    )
    if not already_parented:
        world_matrix = driver.matrix_world.copy()
        driver.parent = start_armature
        driver.parent_type = "BONE"
        driver.parent_bone = start_bone.name
        driver.matrix_world = world_matrix
    driver["tc_twist_driver"] = True
    driver["tc_twist_contract_revision"] = settings["revision"]
    driver["tc_world_up_bone"] = settings["world_up_object"]
    driver["tc_aim_target_bone"] = settings["aim_target"]
    driver["tc_world_up_vector"] = settings["world_up_vector"]
    driver["tc_up_vector"] = settings["up_vector"]
    driver["tc_maintain_offset"] = settings["maintain_offset"]
    driver["tc_constraint_weight"] = settings["weight"]
    if settings["aim_offset"] is not None:
        driver["tc_aim_offset"] = settings["aim_offset"]

    created = [driver.name]
    twists = [str(value) for value in payload.get("twist_joints") or []]
    for index, value in enumerate(twists, 1):
        armature, bone, pose_bone = _resolve_bone(value)
        if armature != start_armature:
            raise ValueError("Blender twist joints must belong to the start/end armature")
        constraint = _constraint(pose_bone, "ARMATURE", f"TC_{module}_twist_{index:02d}", module)
        while constraint.targets:
            constraint.targets.remove(constraint.targets[0])
        weight = index / float(len(twists) + 1)
        for target_bone, target_weight in ((start_bone, 1.0 - weight), (end_bone, weight)):
            target = constraint.targets.new()
            target.target = armature
            target.subtarget = target_bone.name
            target.weight = target_weight
        created.append(f"{armature.name}:{bone.name}:{constraint.name}")
    return _result(
        True, "rig.create_twist", "Created Blender twist distribution.", created_ids=created,
        data={
            "twist_driver": driver.name,
            "parent": _bone_id(start_armature, start_bone),
            "world_up_object": settings["world_up_object"],
            "constraint_settings": settings,
        },
    )


def _op_rig_set_ik_fk_blend(payload: dict[str, Any]) -> dict[str, Any]:
    limb = str(payload["limb"])
    blend = max(0.0, min(1.0, float(payload["blend"])))
    changed = []
    for armature in [obj for obj in bpy.data.objects if getattr(obj, "type", "") == "ARMATURE"]:
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                if _constraint_module(constraint) != limb:
                    continue
                if constraint.type == "IK" or constraint.name.endswith("_ik_rotation"):
                    constraint.influence = blend
                elif constraint.type == "COPY_TRANSFORMS" and constraint.name.endswith("_fk"):
                    constraint.influence = 1.0 - blend
                else:
                    continue
                changed.append(f"{armature.name}:{pose_bone.name}:{constraint.name}")
    ik_control = bpy.data.objects.get(str(payload.get("ik_control") or ""))
    if ik_control is None:
        ik_control = next(
            (
                obj for obj in bpy.data.objects
                if str(obj.get("tc_rig_module") or "") == limb and "ik_fk_blend" in obj
            ),
            None,
        )
    if ik_control is not None:
        ik_control["ik_fk_blend"] = blend
    return _result(bool(changed), "rig.set_ik_fk_blend", "Updated Blender IK/FK blend." if changed else "IK limb was not found.",
                   changed_ids=changed)


def _op_skin_surface_spatial_smooth_brush(payload: dict[str, Any]) -> dict[str, Any]:
    from blender_tools.Rigging import surface_spatial_skin_brush

    result = surface_spatial_skin_brush.activate(
        radius=float(payload.get("radius", 1.0)),
        strength=float(payload.get("strength", 0.5)),
        iterations=int(payload.get("iterations", 1)),
        max_influences=int(payload.get("max_influences", 8)),
        normal_angle=float(payload.get("normal_angle", 120.0)),
        max_neighbors=int(payload.get("max_neighbors", 96)),
    )
    return _result(True, "skin.surface_spatial_smooth_brush",
                   "Activated Blender surface-spatial skin smoothing brush.", data={"operator_result": list(result)})


def _resolve_constraint_owner(value: str) -> tuple[Any, str]:
    obj = bpy.data.objects.get(str(value))
    if obj is not None:
        return obj, obj.name
    armature, bone, pose_bone = _resolve_bone(str(value))
    return pose_bone, _bone_id(armature, bone)


def _resolve_constraint_target(value: str) -> tuple[Any, str]:
    obj = bpy.data.objects.get(str(value))
    if obj is not None:
        return obj, ""
    armature, bone, _pose_bone = _resolve_bone(str(value))
    return armature, bone.name


def _op_rig_edit_control_shape(payload: dict[str, Any]) -> dict[str, Any]:
    control = bpy.data.objects.get(str(payload["control"]))
    if control is None:
        raise ValueError(f"Blender control does not exist: {payload['control']}")
    shape = str(payload.get("shape") or "").upper()
    empty_shapes = {
        "CIRCLE": "CIRCLE", "CUBE": "CUBE", "SPHERE": "SPHERE",
        "ARROWS": "ARROWS", "PLAIN_AXES": "PLAIN_AXES", "CONE": "CONE",
    }
    if shape and control.type == "EMPTY":
        control.empty_display_type = empty_shapes.get(shape, control.empty_display_type)
    positions = payload.get("cv_positions") or []
    if positions and control.type == "CURVE":
        points = [point for spline in control.data.splines for point in spline.points]
        bezier_points = [point for spline in control.data.splines for point in spline.bezier_points]
        editable = points or bezier_points
        for point, position in zip(editable, positions):
            if hasattr(point, "co"):
                values = list(position)
                point.co = (*values[:3], 1.0) if len(point.co) == 4 else values[:3]
    control["tc_control_shape"] = str(payload.get("shape") or control.get("tc_control_shape") or "")
    control["tc_control_cv_positions"] = json.dumps(positions)
    return _result(True, "rig.edit_control_shape", "Updated Blender control shape.", changed_ids=[control.name])


def _op_rig_create_reverse_foot(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload.get("module") or f"{payload['ankle']}_reverse_foot")
    targets = (("heel", str(payload["ankle"])), ("toe", str(payload["toe"])),
               ("ball", str(payload["ball"])), ("ankle", str(payload["ankle"])))
    created, parent = [], None
    for role, target in targets:
        control = _control(f"{module}_{role}_pivot", target, module, display="PLAIN_AXES")
        control["tc_reverse_foot_role"] = role
        if parent is not None:
            world = control.matrix_world.copy()
            control.parent = parent
            control.matrix_world = world
        created.append(control.name)
        parent = control
    armature, bone, pose_bone = _resolve_bone(str(payload["ankle"]))
    constraint = _constraint(pose_bone, "COPY_TRANSFORMS", f"TC_{module}_reverse_foot", module)
    constraint.target = parent
    constraint.target_space = "WORLD"
    constraint.owner_space = "WORLD"
    created.append(f"{armature.name}:{bone.name}:{constraint.name}")
    return _result(True, "rig.create_reverse_foot", "Created Blender reverse-foot pivots.", created_ids=created)


def _op_rig_create_motion_path(payload: dict[str, Any]) -> dict[str, Any]:
    curve = bpy.data.objects.get(str(payload["curve"]))
    if curve is None or curve.type != "CURVE":
        raise ValueError(f"Blender curve does not exist: {payload['curve']}")
    owner, owner_id = _resolve_constraint_owner(str(payload["target"]))
    module = str(payload.get("module") or "motion_path")
    constraint = _constraint(owner, "FOLLOW_PATH", str(payload.get("name") or "TC_motion_path"), module)
    constraint.target = curve
    constraint.use_fixed_location = True
    constraint.offset_factor = float(payload.get("parameter", 0.0) or 0.0)
    constraint.use_curve_follow = bool(payload.get("follow", True))
    return _result(True, "rig.create_motion_path", "Created Blender motion path.",
                   created_ids=[f"{owner_id}:{constraint.name}"])


def _op_rig_create_space_switch(payload: dict[str, Any]) -> dict[str, Any]:
    owner, owner_id = _resolve_constraint_owner(str(payload["driven"]))
    targets = [str(value) for value in payload["targets"]]
    names = [str(value) for value in (payload.get("names") or targets)]
    active = int(payload.get("active", 0) or 0)
    module = str(payload.get("module") or "space_switch")
    switch_id = str(payload.get("name") or f"TC_{str(payload['driven']).split(':')[-1]}_space")
    created = []
    for index, target_id in enumerate(targets):
        target, subtarget = _resolve_constraint_target(target_id)
        constraint = _constraint(owner, "CHILD_OF", f"{switch_id}__{index:02d}", module)
        constraint.target = target
        constraint.subtarget = subtarget
        constraint.influence = 1.0 if index == active else 0.0
        created.append(f"{owner_id}:{constraint.name}")
    owner["tc_space_switch"] = json.dumps({"id": switch_id, "names": names, "targets": targets, "active": active})
    return _result(True, "rig.create_space_switch", "Created Blender space switch.", created_ids=created,
                   data={"space_switch": f"{owner_id}|{switch_id}"})


def _op_rig_set_space(payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload["space_switch"])
    owner_id, switch_id = token.split("|", 1) if "|" in token else (token, "")
    owner, resolved_id = _resolve_constraint_owner(owner_id)
    metadata = json.loads(str(owner.get("tc_space_switch") or "{}"))
    switch_id = switch_id or str(metadata.get("id") or "")
    names = list(metadata.get("names") or [])
    requested = payload["space"]
    active = names.index(requested) if isinstance(requested, str) and requested in names else int(requested)
    changed = []
    for index, constraint in enumerate([item for item in owner.constraints if switch_id in item.name]):
        constraint.influence = 1.0 if index == active else 0.0
        changed.append(f"{resolved_id}:{constraint.name}")
    if not changed:
        raise ValueError(f"Blender space switch does not exist: {token}")
    metadata["active"] = active
    owner["tc_space_switch"] = json.dumps(metadata)
    return _result(True, "rig.set_space", "Updated Blender active space.", changed_ids=changed)


def _op_rig_create_mesh_attachment(payload: dict[str, Any]) -> dict[str, Any]:
    mesh = bpy.data.objects.get(str(payload["mesh"]))
    if mesh is None or mesh.type != "MESH":
        raise ValueError(f"Blender mesh does not exist: {payload['mesh']}")
    owner, owner_id = _resolve_constraint_owner(str(payload["driven"]))
    module = str(payload.get("module") or "mesh_attachment")
    constraint = _constraint(owner, "SHRINKWRAP", str(payload.get("name") or "TC_mesh_attachment"), module)
    constraint.target = mesh
    constraint.shrinkwrap_type = "NEAREST_SURFACE"
    return _result(True, "rig.create_mesh_attachment", "Created Blender mesh attachment.",
                   created_ids=[f"{owner_id}:{constraint.name}"])


def _op_rig_create_pose_reader(payload: dict[str, Any]) -> dict[str, Any]:
    driver, subtarget = _resolve_constraint_target(str(payload["driver"]))
    name = str(payload.get("name") or f"{str(payload['driver']).split(':')[-1]}_pose_reader")
    reader = bpy.data.objects.get(name) or bpy.data.objects.new(name, None)
    if reader.name not in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.link(reader)
    reader.empty_display_type = "PLAIN_AXES"
    reader["output"] = 0.0
    reader["tc_pose_reader"] = True
    reader["tc_pose_reader_driver"] = str(payload["driver"])
    axis = str(payload.get("axis") or "x").lower()
    limits = [float(value) for value in (payload.get("range") or (-90.0, 90.0))]
    fcurve = reader.driver_add('["output"]')
    variable = fcurve.driver.variables.new()
    variable.name = "angle"
    variable.type = "TRANSFORMS"
    variable.targets[0].id = driver
    variable.targets[0].bone_target = subtarget
    variable.targets[0].transform_type = f"ROT_{axis.upper()}"
    variable.targets[0].transform_space = "TRANSFORM_SPACE"
    low, high = (value * 0.017453292519943295 for value in limits[:2])
    span = high - low if abs(high - low) > 1.0e-8 else 1.0
    fcurve.driver.expression = f"min(1,max(0,(angle-({low}))/{span}))"
    return _result(True, "rig.create_pose_reader", "Created Blender pose reader.", created_ids=[reader.name])


def _module_connection_snapshot(module: str) -> list[dict[str, Any]]:
    rows = []
    for armature in [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]:
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                if _constraint_module(constraint) == module:
                    rows.append({"owner": _bone_id(armature, pose_bone.bone), "type": constraint.type,
                                 "name": constraint.name, "target": getattr(getattr(constraint, "target", None), "name", ""),
                                 "subtarget": str(getattr(constraint, "subtarget", "")),
                                 "influence": float(getattr(constraint, "influence", 1.0))})
    for obj in bpy.data.objects:
        for constraint in obj.constraints:
            if _constraint_module(constraint) == module:
                rows.append({"owner": obj.name, "type": constraint.type, "name": constraint.name,
                             "target": getattr(getattr(constraint, "target", None), "name", ""),
                             "subtarget": str(getattr(constraint, "subtarget", "")),
                             "influence": float(getattr(constraint, "influence", 1.0))})
    return rows


def _op_rig_store_connections(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"])
    rows = _module_connection_snapshot(module)
    bpy.context.scene[f"tc_connections_{module}"] = json.dumps(rows)
    return _result(True, "rig.store_connections", f"Stored {len(rows)} Blender module connections.",
                   data={"connections": rows})


def _op_rig_restore_connections(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"])
    rows = json.loads(str(bpy.context.scene.get(f"tc_connections_{module}") or "[]"))
    restored = []
    for row in rows:
        try:
            owner, owner_id = _resolve_constraint_owner(row["owner"])
            constraint = _constraint(owner, row["type"], row["name"].split("__", 1)[-1], module)
            target = bpy.data.objects.get(row.get("target") or "")
            if target is not None and hasattr(constraint, "target"):
                constraint.target = target
            if hasattr(constraint, "subtarget"):
                constraint.subtarget = str(row.get("subtarget") or "")
            constraint.influence = float(row.get("influence", 1.0))
            restored.append(f"{owner_id}:{constraint.name}")
        except (AttributeError, TypeError, ValueError):
            continue
    return _result(True, "rig.restore_connections", f"Restored {len(restored)} Blender module connections.",
                   changed_ids=restored, data={"connections": rows})


def _op_retarget_solve_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["target"])
    changed = []
    for slot, values in dict(payload["source"]).items():
        target_id = definition.slots.get(slot)
        if not target_id or not isinstance(values, (list, tuple)) or len(values) != 16:
            continue
        armature, _bone, pose_bone = _resolve_bone(target_id)
        pose_bone.matrix = armature.matrix_world.inverted() @ _matrix_from_values(values)
        changed.append(target_id)
    bpy.context.view_layer.update()
    return _result(True, "retarget.solve_pose", f"Solved {len(changed)} Blender joints.", changed_ids=changed)


def _op_retarget_preview(payload: dict[str, Any]) -> dict[str, Any]:
    result = _op_retarget_solve_pose(payload)
    result["capability"] = "retarget.preview"
    return result


def _op_retarget_bake(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["target"])
    start, end = (int(round(float(value))) for value in payload["range"])
    step = max(1, int(round(float(payload.get("sample_rate", 1) or 1))))
    changed = []
    for target_id in definition.slots.values():
        try:
            _armature, _bone, pose_bone = _resolve_bone(target_id)
        except ValueError:
            continue
        for frame in range(start, end + 1, step):
            bpy.context.scene.frame_set(frame)
            pose_bone.keyframe_insert("location", frame=frame)
            pose_bone.keyframe_insert("rotation_quaternion", frame=frame)
            pose_bone.keyframe_insert("scale", frame=frame)
        changed.append(target_id)
    return _result(True, "retarget.bake", "Baked retargeted Blender animation.", changed_ids=changed)


def _op_retarget_transfer_take(payload: dict[str, Any]) -> dict[str, Any]:
    take = payload["take"]
    bpy.context.scene["tc_retarget_take"] = json.dumps(take, default=str)
    return _result(True, "retarget.transfer_take", "Stored Blender retarget take metadata.", data={"take": take})
