"""Blender translation endpoint for Tech Connector's shared rigging workspace.

The adapter uses ordinary Blender armatures, empties, and pose constraints so
the resulting rigs remain editable without the Tech Connector UI running.
"""

from __future__ import annotations

from typing import Any

import bpy

from blender_tools.Rigging import surface_spatial_skin_brush as _surface_spatial_skin_brush

_surface_spatial_skin_brush.register()

from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    RiggingOperationResult,
    auto_map_character,
    mirror_character_slots,
    validate_character_definition,
)


HOST = "blender"


def _result(ok: bool, capability: str, message: str = "", **kwargs: Any) -> dict[str, Any]:
    return RiggingOperationResult(ok, capability, HOST, message, **kwargs).to_dict()


def _matrix_values(matrix: Any) -> list[float]:
    return [float(matrix[row][column]) for row in range(4) for column in range(4)]


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


def _control(name: str, target: str, module: str, *, display: str = "CIRCLE") -> Any:
    armature, bone, _pose_bone = _resolve_bone(target)
    existing = bpy.data.objects.get(name)
    control = existing or bpy.data.objects.new(name, None)
    if existing is None:
        bpy.context.scene.collection.objects.link(control)
    control.empty_display_type = display
    control.empty_display_size = max(float(getattr(bone, "length", 1.0)) * 0.35, 0.1)
    control.matrix_world = armature.matrix_world @ bone.matrix_local
    control["tc_rig_module"] = module
    control["tc_target_bone"] = _bone_id(armature, bone)
    return control


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
    try:
        return handler(dict(payload))
    except Exception as exc:
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


def _op_rig_build_module(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"]).lower()
    definition = _definition(payload["definition"])
    targets = _module_targets(module, definition)
    if not targets:
        raise ValueError(f"Character definition has no Blender bones for module {module}")
    created = []
    if module == "nose":
        created.extend(_build_nose_module(definition))
    elif module in {"left_arm", "right_arm", "left_leg", "right_leg"} and len(targets) >= 3:
        limb = _op_rig_create_ik_fk_limb({
            "start": targets[0][1], "mid": targets[1][1], "end": targets[2][1], "module": module,
            "stretch": payload.get("stretch", 1.0),
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
        for slot, target in targets:
            created.append(_copy_control(target, names.get(slot, f"{slot}_ctrl"), module))
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
    return _result(True, "rig.build_module", f"Built Blender module {module}.", created_ids=created, data={"module": module})


def _op_rig_build_full(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    requested_modules = payload.get("modules")
    if requested_modules:
        modules = list(requested_modules)
    else:
        modules = ["root", "pelvis", "spine", "neck", "head", "left_arm", "right_arm", "left_leg", "right_leg"]
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
        result = _op_rig_build_module({"module": module, "definition": definition.to_dict()})
        if result["ok"]:
            created.extend(result["created_ids"])
        else:
            warnings.append(f"{module}: {result['message']}")
    return _result(not warnings, "rig.build_full", f"Built {len(modules) - len(warnings)} Blender rig modules.",
                   created_ids=created, warnings=warnings, data={"modules": modules})


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
    ik_control = _control(f"{end_bone.name}_ik_ctrl", str(payload["end"]), module, display="CUBE")
    pole_control = _control(f"{end_bone.name}_pole_ctrl", str(payload["mid"]), module)
    pole_control.location += pole_control.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 2.0))
    # Blender's IK owner is the final deforming segment (forearm/shin), while
    # the target is placed at the terminal hand/foot bone.
    ik = _constraint(mid_pose, "IK", f"TC_{module}_ik", module)
    ik.target = ik_control
    ik.pole_target = pole_control
    ik.chain_count = 2
    ik.influence = float(payload.get("blend", 1.0))
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
    start_armature["tc_control_rig"] = True
    return _result(True, "rig.create_ik_fk_limb", "Created Blender IK/FK limb controls.",
                   created_ids=[ik_control.name, pole_control.name, f"{mid_armature.name}:{mid_pose.name}:{ik.name}"],
                   data={"limb": module, "ik_control": ik_control.name, "pole_control": pole_control.name,
                         "stretch_control": ik_control.name, "stretch_attribute": "stretch"})


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
        data={"twist_driver": driver.name, "parent": _bone_id(start_armature, start_bone)},
    )


def _op_rig_set_ik_fk_blend(payload: dict[str, Any]) -> dict[str, Any]:
    limb = str(payload["limb"])
    blend = max(0.0, min(1.0, float(payload["blend"])))
    changed = []
    for armature in [obj for obj in bpy.data.objects if getattr(obj, "type", "") == "ARMATURE"]:
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                if constraint.type == "IK" and _constraint_module(constraint) == limb:
                    constraint.influence = blend
                    changed.append(f"{armature.name}:{pose_bone.name}:{constraint.name}")
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
